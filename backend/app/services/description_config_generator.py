"""
DescriptionConfigGenerator — build SimulationParameters from a ScenarioDefinition.

No graph entities are used. Group-level behavioral knobs (activity_level,
sentiment_bias, stance, response_delay) are derived from each AgentGroup.
"""

import json
import math
import time
from typing import List, Dict, Any, Optional, Callable

from openai import AzureOpenAI

from ..config import Config
from ..utils.logger import get_logger
from ..models.scenario import AgentGroup, ScenarioDefinition
from .oasis_profile_generator import OasisAgentProfile
from .simulation_config_generator import (
    AgentActivityConfig,
    TimeSimulationConfig,
    EventConfig,
    PlatformConfig,
    SimulationParameters,
)

logger = get_logger('mirofish.description_config_generator')


class DescriptionConfigGenerator:
    """
    Generate SimulationParameters from a ScenarioDefinition + list of profiles.

    Reuses all dataclasses from SimulationConfigGenerator.
    """

    def __init__(self):
        self.client = AzureOpenAI(
            api_key=Config.AZURE_OPENAI_API_KEY,
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            api_version=Config.AZURE_OPENAI_API_VERSION,
        )
        self.model_name = Config.AZURE_OPENAI_CHAT_DEPLOYMENT
        if not self.model_name:
            raise ValueError("AZURE_OPENAI_CHAT_DEPLOYMENT not configured")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate(
        self,
        simulation_id: str,
        scenario: ScenarioDefinition,
        profiles: List[OasisAgentProfile],
        enable_twitter: bool = True,
        enable_reddit: bool = True,
        progress_callback: Optional[Callable[[int, int], None]] = None,
        agents_per_batch: int = 15,
    ) -> SimulationParameters:
        """
        Build complete SimulationParameters from a ScenarioDefinition.

        Args:
            simulation_id: ID of the simulation being created.
            scenario: Parsed scenario definition.
            profiles: Generated agent profiles (user_id must match 0…N-1).
            enable_twitter: Whether Twitter platform is enabled.
            enable_reddit: Whether Reddit platform is enabled.

        Returns:
            SimulationParameters ready to be saved as simulation_config.json.
        """
        logger.info(
            f"Generating config: simulation_id={simulation_id}, "
            f"agents={len(profiles)}, groups={len(scenario.groups)}"
        )

        # 1. Time config (standard defaults)
        time_config = self._build_time_config(scenario)

        # 2. Per-agent activity configs from groups
        agent_configs = self._build_agent_configs(scenario, profiles, progress_callback, agents_per_batch)

        # 3. Event config via LLM
        event_config = self._build_event_config(scenario, agent_configs)

        # 4. Platform configs (standard defaults)
        twitter_config = PlatformConfig(
            platform="twitter",
            recency_weight=0.4,
            popularity_weight=0.3,
            relevance_weight=0.3,
            viral_threshold=10,
            echo_chamber_strength=0.5,
        ) if enable_twitter else None

        reddit_config = PlatformConfig(
            platform="reddit",
            recency_weight=0.3,
            popularity_weight=0.4,
            relevance_weight=0.3,
            viral_threshold=15,
            echo_chamber_strength=0.6,
        ) if enable_reddit else None

        reasoning_parts = [
            f"Description flow: {scenario.title}",
            f"Groups: {', '.join(g.name for g in scenario.groups)}",
            f"Total agents: {scenario.total_agents}",
        ]

        return SimulationParameters(
            simulation_id=simulation_id,
            project_id="scenario_flow",
            graph_id="",
            simulation_requirement=scenario.original_description,
            time_config=time_config,
            agent_configs=agent_configs,
            event_config=event_config,
            twitter_config=twitter_config,
            reddit_config=reddit_config,
            llm_model=self.model_name,
            generation_reasoning=" | ".join(reasoning_parts),
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    AGENTS_PER_BATCH = 15

    def _build_time_config(self, scenario: ScenarioDefinition) -> TimeSimulationConfig:
        """Build time config — each round represents one full day (1440 min)."""
        n = scenario.total_agents
        return TimeSimulationConfig(
            total_simulation_hours=72,
            minutes_per_round=1,
            simulation_start_hour=9,
            agents_per_hour_min=max(1, n // 15),
            agents_per_hour_max=max(5, min(n, n // 3)),
            peak_hours=[19, 20, 21, 22],
            off_peak_hours=[0, 1, 2, 3, 4, 5],
            off_peak_activity_multiplier=0.05,
            morning_hours=[6, 7, 8],
            morning_activity_multiplier=0.4,
            work_hours=list(range(9, 19)),
            work_activity_multiplier=0.7,
            peak_activity_multiplier=1.5,
        )

    def _build_agent_configs(
        self,
        scenario: ScenarioDefinition,
        profiles: List[OasisAgentProfile],
        progress_callback: Optional[Callable[[int, int], None]] = None,
        agents_per_batch: int = 15,
    ) -> List[AgentActivityConfig]:
        """
        Generate one AgentActivityConfig per agent via batched LLM calls.

        Profiles are processed in batches of AGENTS_PER_BATCH.  Each batch
        sends the agent's persona summary + group context to the LLM and
        receives individualised activity parameters back.  Falls back to
        rule-based defaults for any agent the LLM misses.
        """
        import math

        group_map: Dict[str, AgentGroup] = {g.name: g for g in scenario.groups}
        all_configs: List[AgentActivityConfig] = []

        num_batches = math.ceil(len(profiles) / agents_per_batch)

        for batch_idx in range(num_batches):
            start = batch_idx * agents_per_batch
            end = min(start + agents_per_batch, len(profiles))
            batch = profiles[start:end]

            logger.info(
                f"Generating agent configs batch {batch_idx + 1}/{num_batches} "
                f"(agents {start + 1}–{end}/{len(profiles)})"
            )
            if progress_callback:
                progress_callback(batch_idx + 1, num_batches)

            llm_results = self._generate_agent_configs_batch_llm(
                batch, group_map, scenario
            )

            for profile in batch:
                group = group_map.get(profile.group_id or "")
                if group is None:
                    # Resolve group by cumulative index
                    cumulative = 0
                    for g in scenario.groups:
                        cumulative += g.count
                        if profile.user_id < cumulative:
                            group = g
                            break
                    if group is None:
                        group = scenario.groups[0] if scenario.groups else None

                llm_cfg = llm_results.get(profile.user_id, {})

                if llm_cfg and group:
                    cfg = AgentActivityConfig(
                        agent_id=profile.user_id,
                        entity_uuid=f"scenario_{group.name}_{profile.user_id}",
                        entity_name=profile.user_name,
                        entity_type=group.name,
                        group_id=group.name,
                        activity_level=float(llm_cfg.get("activity_level", group.activity_level)),
                        posts_per_hour=float(llm_cfg.get("posts_per_hour", 0.5)),
                        comments_per_hour=float(llm_cfg.get("comments_per_hour", 1.0)),
                        active_hours=llm_cfg.get("active_hours", list(range(8, 24))),
                        response_delay_min=int(llm_cfg.get("response_delay_min", 5)),
                        response_delay_max=int(llm_cfg.get("response_delay_max", 60)),
                        sentiment_bias=float(llm_cfg.get("sentiment_bias", group.sentiment_bias)),
                        stance=str(llm_cfg.get("stance", group.stance)),
                        influence_weight=float(llm_cfg.get("influence_weight", 1.0)),
                    )
                elif group:
                    cfg = self._rule_based_agent_config(profile, group)
                else:
                    cfg = AgentActivityConfig(
                        agent_id=profile.user_id,
                        entity_uuid=f"scenario_unknown_{profile.user_id}",
                        entity_name=profile.user_name,
                        entity_type="unknown",
                        group_id="",
                    )

                all_configs.append(cfg)

        return all_configs

    def _generate_agent_configs_batch_llm(
        self,
        batch: List[OasisAgentProfile],
        group_map: Dict[str, AgentGroup],
        scenario: ScenarioDefinition,
    ) -> Dict[int, Dict]:
        """
        Call LLM once for a batch of agents, returning a dict keyed by agent_id.

        Each entry in the return dict contains activity config fields for that agent.
        Returns an empty dict on failure (callers fall back to rule-based).
        """
        # Build context items for each agent in the batch
        agent_items = []
        for p in batch:
            group = group_map.get(p.group_id or "")
            group_ctx = (
                f"{group.label}: {group.behavior_description[:150]} "
                f"[stance={group.stance}, activity={group.activity_level}, "
                f"hours={group.active_hours_hint}]"
            ) if group else "Unknown group"

            agent_items.append({
                "agent_id": p.user_id,
                "name": p.name,
                "bio": (p.bio or "")[:200],
                "profession": p.profession or "",
                "group_context": group_ctx,
            })

        group_summary = "\n".join(
            f"- {g.name}: activity={g.activity_level}, stance={g.stance}, "
            f"sentiment={g.sentiment_bias}, hours={g.active_hours_hint}"
            for g in scenario.groups
        )

        prompt = f"""Generate social media activity configuration for each agent in this simulation.

Scenario: {scenario.title}
Theme: {scenario.theme}

Group definitions:
{group_summary}

Agents to configure:
```json
{json.dumps(agent_items, ensure_ascii=False, indent=2)}
```

For each agent, generate an activity config that reflects their group membership and persona.
Vary parameters slightly between agents of the same group for realism.

Rules:
- activity_level: 0.0–1.0
- posts_per_hour, comments_per_hour: positive floats
- active_hours: list of ints 0–23
- response_delay_min, response_delay_max: minutes (integers, min < max)
- sentiment_bias: -1.0 (hostile) to 1.0 (positive)
- stance: supportive | opposing | neutral | observer | disruptive
- influence_weight: 0.5–3.0

Return JSON:
{{
  "agent_configs": [
    {{
      "agent_id": <must match input>,
      "activity_level": <float>,
      "posts_per_hour": <float>,
      "comments_per_hour": <float>,
      "active_hours": [<ints>],
      "response_delay_min": <int>,
      "response_delay_max": <int>,
      "sentiment_bias": <float>,
      "stance": "<string>",
      "influence_weight": <float>
    }},
    ...
  ]
}}"""

        system_prompt = (
            "You are a social media behavior analyst. "
            "Return only valid JSON, no markdown."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
            content = response.choices[0].message.content

            if response.choices[0].finish_reason == "length":
                content = self._fix_truncated_json(content)

            data = json.loads(content)
            return {cfg["agent_id"]: cfg for cfg in data.get("agent_configs", [])}

        except Exception as exc:
            logger.warning(f"Agent config batch LLM failed: {exc}, falling back to rule-based")
            return {}

    def _rule_based_agent_config(
        self, profile: OasisAgentProfile, group: AgentGroup
    ) -> AgentActivityConfig:
        """Rule-based fallback config derived from group parameters."""
        activity = group.activity_level

        if activity >= 0.8:
            delay_min, delay_max = 1, 10
        elif activity >= 0.5:
            delay_min, delay_max = 5, 30
        else:
            delay_min, delay_max = 15, 90

        hint = group.active_hours_hint.lower()
        if "late night" in hint:
            active_hours = [20, 21, 22, 23, 0, 1, 2]
        elif "business hours" in hint:
            active_hours = list(range(9, 18))
        elif "morning" in hint:
            active_hours = list(range(6, 13))
        elif "evening" in hint:
            active_hours = list(range(17, 24))
        else:
            active_hours = list(range(8, 24))

        return AgentActivityConfig(
            agent_id=profile.user_id,
            entity_uuid=f"scenario_{group.name}_{profile.user_id}",
            entity_name=profile.user_name,
            entity_type=group.name,
            group_id=group.name,
            activity_level=activity,
            posts_per_hour=round(activity * 1.2, 2),
            comments_per_hour=round(activity * 2.0, 2),
            active_hours=active_hours,
            response_delay_min=delay_min,
            response_delay_max=delay_max,
            sentiment_bias=group.sentiment_bias,
            stance=group.stance,
            influence_weight=1.0,
        )

    @staticmethod
    def _fix_truncated_json(content: str) -> str:
        content = content.strip()
        open_braces = content.count("{") - content.count("}")
        open_brackets = content.count("[") - content.count("]")
        if content and content[-1] not in '",}]':
            content += '"'
        content += "]" * open_brackets
        content += "}" * open_braces
        return content

    def _build_event_config(
        self,
        scenario: ScenarioDefinition,
        agent_configs: List[AgentActivityConfig],
    ) -> EventConfig:
        """Use LLM to generate initial posts seeded by group descriptions."""
        # Find disruptive / coordinator groups — they should seed initial posts
        seeding_groups = [
            g for g in scenario.groups
            if g.communication_style in ("coordinate_within_group", "broadcast")
            or g.stance in ("opposing", "disruptive")
        ]
        if not seeding_groups:
            seeding_groups = scenario.groups[:1]

        group_descriptions = "\n".join(
            f"- {g.label} ({g.name}): {g.behavior_description}" for g in seeding_groups
        )

        prompt = f"""You are designing the initial posts for a social media simulation.

Scenario: {scenario.title}
Theme: {scenario.theme}

Groups that should seed initial content:
{group_descriptions}

Generate 2-4 initial posts that kickstart the simulation. Each post should fit the
behavior of one of the seeding groups above.

Return JSON:
{{
  "hot_topics": ["<keyword1>", "<keyword2>", ...],
  "narrative_direction": "<one sentence describing how opinion unfolds>",
  "initial_posts": [
    {{"content": "<post text>", "poster_type": "<group name from above>"}},
    ...
  ],
  "reasoning": "<brief explanation>"
}}"""

        system_prompt = (
            "You are a social media simulation designer. "
            "Return only valid JSON with no markdown fences."
        )

        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.7,
            )
            data = json.loads(response.choices[0].message.content)
        except Exception as exc:
            logger.warning(f"Event config LLM failed: {exc}, using fallback")
            data = {
                "hot_topics": [scenario.theme] if scenario.theme else [],
                "narrative_direction": f"Discussion unfolds around: {scenario.title}",
                "initial_posts": [
                    {
                        "content": f"Discussing: {g.behavior_description[:200]}",
                        "poster_type": g.name,
                    }
                    for g in seeding_groups[:2]
                ],
                "reasoning": "Fallback event config",
            }

        event_config = EventConfig(
            hot_topics=data.get("hot_topics", []),
            narrative_direction=data.get("narrative_direction", ""),
            initial_posts=data.get("initial_posts", []),
        )

        # Assign poster_agent_id to each initial post
        event_config = self._assign_initial_post_agents(event_config, agent_configs)
        return event_config

    def _assign_initial_post_agents(
        self,
        event_config: EventConfig,
        agent_configs: List[AgentActivityConfig],
    ) -> EventConfig:
        """Match initial posts to agent IDs by poster_type (group name)."""
        if not event_config.initial_posts:
            return event_config

        # Index agents by entity_type (= group name)
        agents_by_type: Dict[str, List[AgentActivityConfig]] = {}
        for agent in agent_configs:
            t = agent.entity_type.lower()
            agents_by_type.setdefault(t, []).append(agent)

        used_indices: Dict[str, int] = {}
        updated_posts = []

        for post in event_config.initial_posts:
            poster_type = post.get("poster_type", "").lower()
            content = post.get("content", "")

            matched_id = None
            if poster_type in agents_by_type:
                agents = agents_by_type[poster_type]
                idx = used_indices.get(poster_type, 0) % len(agents)
                matched_id = agents[idx].agent_id
                used_indices[poster_type] = idx + 1
            elif agent_configs:
                # Fallback: highest-activity agent
                matched_id = max(agent_configs, key=lambda a: a.activity_level).agent_id
            else:
                matched_id = 0

            updated_posts.append({
                "content": content,
                "poster_type": post.get("poster_type", "Unknown"),
                "poster_agent_id": matched_id,
            })
            logger.info(f"Initial post: poster_type='{poster_type}' → agent_id={matched_id}")

        event_config.initial_posts = updated_posts
        return event_config
