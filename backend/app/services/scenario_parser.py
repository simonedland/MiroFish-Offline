"""
ScenarioParser — parse a free-form scenario description into a ScenarioDefinition.
"""

import json
import time
from typing import Dict, Any

from openai import AzureOpenAI

from ..config import Config
from ..utils.logger import get_logger
from ..models.scenario import AgentGroup, ScenarioDefinition

logger = get_logger('mirofish.scenario_parser')


class ScenarioParser:
    """Parse free-form scenario descriptions into structured ScenarioDefinition objects."""

    def __init__(self):
        self.client = AzureOpenAI(
            api_key=Config.AZURE_OPENAI_API_KEY,
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            api_version=Config.AZURE_OPENAI_API_VERSION,
        )
        self.model_name = Config.AZURE_OPENAI_CHAT_DEPLOYMENT
        if not self.model_name:
            raise ValueError("AZURE_OPENAI_CHAT_DEPLOYMENT not configured")

    def parse(self, description: str) -> ScenarioDefinition:
        """
        Parse a free-form scenario description into a ScenarioDefinition.

        Args:
            description: Free-form scenario description from the user.

        Returns:
            ScenarioDefinition with validated groups.

        Raises:
            RuntimeError: if all attempts fail.
        """
        prompt = self._build_prompt(description)
        system_prompt = (
            "You are a social simulation designer. "
            "Extract structured group definitions from scenario descriptions. "
            "Return only valid JSON with no markdown fences."
        )

        max_attempts = 3
        last_error = None

        for attempt in range(max_attempts):
            try:
                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=max(0.1, 0.3 - attempt * 0.1),
                )

                content = response.choices[0].message.content
                data = json.loads(content)
                return self._build_scenario(data, description)

            except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                logger.warning(f"Scenario parse attempt {attempt + 1} failed (parse/validate): {e}")
                last_error = e

            except Exception as e:
                logger.warning(f"Scenario parse attempt {attempt + 1} failed (LLM call): {e}")
                last_error = e
                time.sleep(2 * (attempt + 1))

        raise RuntimeError(
            f"ScenarioParser failed after {max_attempts} attempts: {last_error}"
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _build_prompt(self, description: str) -> str:
        return f"""Parse the following scenario description into a structured JSON format.

Scenario Description:
{description}

Return a JSON object with this exact structure:
{{
  "title": "<short title for the scenario>",
  "total_agents": <total number of agents as integer>,
  "theme": "<theme or topic of the scenario>",
  "platform_hint": "<twitter|reddit|both>",
  "groups": [
    {{
      "name": "<snake_case group identifier, no spaces>",
      "label": "<human-readable group label>",
      "count": <number of agents in this group, integer>,
      "percentage": <fraction of total agents, 0.0-1.0>,
      "behavior_description": "<what agents in this group post and do>",
      "communication_style": "<independent|coordinate_within_group|broadcast>",
      "interacts_with": ["<other group name>"],
      "sentiment_bias": <-1.0 hostile to 1.0 positive>,
      "activity_level": <0.0 very inactive to 1.0 very active>,
      "stance": "<neutral|supportive|opposing|disruptive>",
      "active_hours_hint": "<all day|late night|business hours|morning|evening>"
    }}
  ]
}}

Rules:
- counts across all groups MUST sum exactly to total_agents
- percentages MUST sum to 1.0
- name must be snake_case (letters, digits, underscores only — no spaces)
- infer platform_hint from context; default to "both" if unclear
- use English for all field values"""

    def _build_scenario(self, data: Dict[str, Any], description: str) -> ScenarioDefinition:
        """Build and validate a ScenarioDefinition from parsed LLM output."""
        raw_groups = data.get("groups", [])
        groups = []
        for g in raw_groups:
            name = str(g.get("name", "group")).replace(" ", "_").lower()
            # Strip non-alphanumeric chars except underscores
            name = "".join(c for c in name if c.isalnum() or c == "_")
            group = AgentGroup(
                name=name or "group",
                label=str(g.get("label", g.get("name", "Group"))),
                count=int(g.get("count", 0)),
                percentage=float(g.get("percentage", 0.0)),
                behavior_description=str(g.get("behavior_description", "")),
                communication_style=str(g.get("communication_style", "independent")),
                interacts_with=[str(x) for x in g.get("interacts_with", [])],
                sentiment_bias=float(g.get("sentiment_bias", 0.0)),
                activity_level=float(g.get("activity_level", 0.5)),
                stance=str(g.get("stance", "neutral")),
                active_hours_hint=str(g.get("active_hours_hint", "all day")),
            )
            groups.append(group)

        total_agents = int(data.get("total_agents", sum(g.count for g in groups)))

        # Guard: if counts don't sum to total_agents, adjust the last group
        count_sum = sum(g.count for g in groups)
        if count_sum != total_agents and groups:
            groups[-1].count += total_agents - count_sum
            # Recalculate percentages
            for g in groups:
                g.percentage = g.count / total_agents if total_agents > 0 else 0.0

        scenario = ScenarioDefinition(
            title=str(data.get("title", "Untitled Scenario")),
            total_agents=total_agents,
            theme=str(data.get("theme", "")),
            platform_hint=str(data.get("platform_hint", "both")),
            groups=groups,
            original_description=description,
        )

        logger.info(
            f"Parsed scenario: '{scenario.title}', "
            f"{scenario.total_agents} agents across {len(scenario.groups)} groups"
        )
        return scenario
