"""
DescriptionProfileGenerator — generate OASIS agent profiles from a ScenarioDefinition.

Bypasses the knowledge graph entirely; uses group context injected into the
persona prompt to create realistic, group-differentiated agents.
"""

import json
import random
import time
import concurrent.futures
from threading import Lock
from typing import List, Optional, Callable

from openai import AzureOpenAI

from ..config import Config
from ..utils.logger import get_logger
from ..models.scenario import AgentGroup, ScenarioDefinition
from .oasis_profile_generator import (
    OasisAgentProfile,
    build_individual_persona_prompt,
    _get_profile_system_prompt,
)

logger = get_logger('mirofish.description_profile_generator')

_US_AREA_CODES = [212, 310, 415, 206, 312, 713, 404, 617, 305, 503, 720, 512, 214, 303, 702]

_FALLBACK_NAMES = [
    "Alex Morgan", "Jordan Lee", "Sam Rivera", "Casey Chen", "Riley Kim",
    "Morgan Davis", "Taylor Smith", "Drew Johnson", "Quinn Martinez", "Blake Wilson",
    "Avery Brown", "Parker Thomas", "Cameron White", "Skyler Harris", "Jamie Clark",
]


def _generate_phone_pool(count: int) -> list:
    """Generate a pool of unique realistic US phone numbers."""
    phones: set = set()
    while len(phones) < count:
        area = random.choice(_US_AREA_CODES)
        number = random.randint(1000000, 9999999)
        phones.add(f"+1{area}{number}")
    return list(phones)


class DescriptionProfileGenerator:
    """
    Generate OASIS Agent Profiles from a ScenarioDefinition.

    Does not require GraphStorage or graph_id.  Group context is injected
    directly into the persona prompt so the LLM produces group-appropriate
    personalities.
    """

    PARALLEL_COUNT = 20  # More parallelism since there is no graph I/O

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
        scenario: ScenarioDefinition,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        realtime_output_path: Optional[str] = None,
    ) -> List[OasisAgentProfile]:
        """
        Generate all agent profiles for a ScenarioDefinition.

        Args:
            scenario: Parsed scenario definition.
            progress_callback: Called with (current, total, message) after each profile.
            realtime_output_path: If provided, write profiles incrementally as they complete (JSON format).

        Returns:
            List of OasisAgentProfile in user_id order (0 … N-1).
        """
        total = scenario.total_agents
        profiles: List[Optional[OasisAgentProfile]] = [None] * total
        completed_count = [0]
        lock = Lock()

        # Build flat list of (global_user_id, group, within_group_index) tuples
        tasks = []
        user_id = 0
        for group in scenario.groups:
            for i in range(group.count):
                tasks.append((user_id, group, i))
                user_id += 1

        used_names: set = set()
        used_usernames: set = set()

        def save_realtime():
            if not realtime_output_path:
                return
            with lock:
                existing = [p for p in profiles if p is not None]
                if not existing:
                    return
                try:
                    data = [p.to_reddit_format() for p in existing]
                    with open(realtime_output_path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, ensure_ascii=False, indent=2)
                except Exception as exc:
                    logger.warning(f"Realtime profile save failed: {exc}")

        def generate_one(uid: int, group: AgentGroup, within_idx: int):
            try:
                profile = self._generate_profile(uid, group, within_idx, used_names, used_usernames, lock)
                return uid, profile, None
            except Exception as exc:
                logger.error(f"Profile generation failed uid={uid} group={group.name}: {exc}")
                fallback = self._rule_based_profile(uid, group, within_idx, used_names, used_usernames, lock)
                return uid, fallback, str(exc)

        logger.info(
            f"Starting profile generation: {total} agents, "
            f"{len(scenario.groups)} groups, parallel={self.PARALLEL_COUNT}"
        )

        # uid -> (group, within_idx) for fallback lookup
        task_lookup = {uid: (group, within_idx) for uid, group, within_idx in tasks}
        completed_futures: set = set()

        with concurrent.futures.ThreadPoolExecutor(max_workers=self.PARALLEL_COUNT) as executor:
            future_map = {
                executor.submit(generate_one, uid, group, within_idx): uid
                for uid, group, within_idx in tasks
            }

            # Each agent can take up to max_attempts × 60 s SDK timeout ≈ 250 s worst-case.
            # Scale the global wall-clock limit with agent count and parallelism so that
            # a legitimate slow run with rate-limiting isn't mistaken for a hang.
            import math
            GLOBAL_TIMEOUT = max(300, math.ceil(total / self.PARALLEL_COUNT) * 90)

            try:
                for future in concurrent.futures.as_completed(future_map, timeout=GLOBAL_TIMEOUT):
                    completed_futures.add(future)
                    uid = future_map[future]
                    try:
                        result_uid, profile, error = future.result()
                        profiles[result_uid] = profile

                        with lock:
                            completed_count[0] += 1
                            current = completed_count[0]

                        save_realtime()

                        if progress_callback:
                            progress_callback(
                                current, total,
                                f"Generated {current}/{total}: {profile.name} ({profile.source_entity_type})"
                            )

                        if error:
                            logger.warning(f"[{current}/{total}] uid={result_uid} using fallback: {error}")
                        else:
                            logger.info(f"[{current}/{total}] uid={result_uid} OK: {profile.name}")

                    except Exception as exc:
                        logger.error(f"Future error uid={uid}: {exc}")
                        with lock:
                            completed_count[0] += 1

            except concurrent.futures.TimeoutError:
                # Some threads are truly stuck (hung TCP connection etc.).
                # Apply rule-based fallback for every agent that didn't finish.
                stuck_uids = [future_map[f] for f in future_map if f not in completed_futures]
                logger.warning(
                    f"Global timeout ({GLOBAL_TIMEOUT}s) hit — applying fallback to "
                    f"{len(stuck_uids)} stuck agents: {stuck_uids}"
                )
                for uid in stuck_uids:
                    group, within_idx = task_lookup[uid]
                    profiles[uid] = self._rule_based_profile(uid, group, within_idx, used_names, used_usernames, lock)
                    with lock:
                        completed_count[0] += 1
                        current = completed_count[0]
                    if progress_callback:
                        progress_callback(current, total, f"Fallback {current}/{total} (timeout)")

        # Final save to ensure completeness
        save_realtime()

        # Assign unique realistic phone numbers to all profiles
        valid_profiles = [p for p in profiles if p is not None]
        phone_pool = _generate_phone_pool(len(valid_profiles))
        for profile, phone in zip(valid_profiles, phone_pool):
            profile.phone_number = phone

        return valid_profiles

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _generate_profile(
        self, user_id: int, group: AgentGroup, within_idx: int,
        used_names: set, used_usernames: set, lock: Lock,
    ) -> OasisAgentProfile:
        """Generate a single agent profile for one member of a group."""
        entity_name = f"agent_{group.name}_{within_idx}"
        entity_type = group.name

        # Build group context that gets prepended to the entity summary
        group_context = (
            f"GROUP CONTEXT: Generate a profile for a \"{group.label}\".\n"
            f"Behavior: {group.behavior_description}\n"
            f"Communication style: {group.communication_style}\n"
            f"Stance: {group.stance}\n"
        )

        base_prompt = build_individual_persona_prompt(
            entity_name=entity_name,
            entity_type=entity_type,
            entity_summary=group_context,  # group context goes into summary slot
            entity_attributes={},
            context="",
        )

        system_prompt = _get_profile_system_prompt()

        # 2 normal attempts + 2 extra for name-collision retries
        max_attempts = 4
        last_error = None
        excluded_names: set = set()

        for attempt in range(max_attempts):
            try:
                # Append name exclusion hint when previous attempts produced duplicates
                if excluded_names:
                    names_str = ", ".join(f'"{n}"' for n in excluded_names)
                    prompt = base_prompt + (
                        f"\n\nIMPORTANT: The following names are already in use by other agents. "
                        f"You MUST choose a completely different name: {names_str}"
                    )
                else:
                    prompt = base_prompt

                response = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": prompt},
                    ],
                    response_format={"type": "json_object"},
                    temperature=max(0.5, 0.9 - attempt * 0.1),
                    timeout=60,
                )

                content = response.choices[0].message.content
                finish_reason = response.choices[0].finish_reason

                if finish_reason == "length":
                    content = self._fix_truncated_json(content)

                data = json.loads(content)

                if not data.get("bio"):
                    data["bio"] = f"{group.label}: {group.behavior_description[:150]}"
                if not data.get("persona"):
                    data["persona"] = f"A {group.label.lower()} who {group.behavior_description}"

                llm_name = data.get("name", entity_name)

                # Atomic check-and-register name
                with lock:
                    name_taken = llm_name in used_names
                    if not name_taken:
                        used_names.add(llm_name)

                if name_taken:
                    excluded_names.add(llm_name)
                    logger.debug(f"Name collision uid={user_id}: '{llm_name}' already taken, retrying")
                    continue

                user_name = self._generate_username_unique(llm_name, used_usernames, lock)
                return OasisAgentProfile(
                    user_id=user_id,
                    user_name=user_name,
                    name=llm_name,
                    bio=data.get("bio", ""),
                    persona=data.get("persona", ""),
                    karma=data.get("karma", random.randint(100, 3000)),
                    friend_count=data.get("friend_count", random.randint(20, 500)),
                    follower_count=data.get("follower_count", random.randint(50, 1000)),
                    statuses_count=data.get("statuses_count", random.randint(50, 2000)),
                    age=data.get("age"),
                    gender=data.get("gender"),
                    mbti=data.get("mbti"),
                    country=data.get("country"),
                    profession=data.get("profession"),
                    interested_topics=data.get("interested_topics", []),
                    source_entity_uuid=f"scenario_{group.name}_{within_idx}",
                    source_entity_type=entity_type,
                    group_id=group.name,
                )

            except json.JSONDecodeError as exc:
                logger.warning(f"JSON decode failed uid={user_id} attempt={attempt+1}: {exc}")
                last_error = exc
            except Exception as exc:
                logger.warning(f"LLM call failed uid={user_id} attempt={attempt+1}: {exc}")
                last_error = exc
                time.sleep(1 * (attempt + 1))

        # Fallback: rule-based
        logger.warning(f"Using rule-based fallback for uid={user_id} group={group.name}")
        return self._rule_based_profile(user_id, group, within_idx, used_names, used_usernames, lock)

    def _rule_based_profile(
        self, user_id: int, group: AgentGroup, within_idx: int,
        used_names: set, used_usernames: set, lock: Lock,
    ) -> OasisAgentProfile:
        """Generate a minimal rule-based profile when LLM fails."""
        with lock:
            name = None
            for offset in range(len(_FALLBACK_NAMES)):
                candidate = _FALLBACK_NAMES[(within_idx + offset) % len(_FALLBACK_NAMES)]
                if candidate not in used_names:
                    name = candidate
                    used_names.add(name)
                    break
            if name is None:
                # All fallback names taken — append a numeric suffix
                base = _FALLBACK_NAMES[within_idx % len(_FALLBACK_NAMES)]
                counter = 2
                while f"{base} {counter}" in used_names:
                    counter += 1
                name = f"{base} {counter}"
                used_names.add(name)

        return OasisAgentProfile(
            user_id=user_id,
            user_name=self._generate_username_unique(name, used_usernames, lock),
            name=name,
            bio=f"{group.label}. {group.behavior_description[:150]}",
            persona=(
                f"A {group.label.lower()} who {group.behavior_description}. "
                f"This agent takes a {group.stance} stance and is active "
                f"during {group.active_hours_hint}."
            ),
            karma=random.randint(100, 1000),
            friend_count=random.randint(20, 300),
            follower_count=random.randint(50, 500),
            statuses_count=random.randint(50, 1000),
            age=random.randint(18, 45),
            gender=random.choice(["male", "female"]),
            mbti=random.choice([
                "INTJ", "INTP", "ENTJ", "ENTP",
                "INFJ", "INFP", "ENFJ", "ENFP",
                "ISTJ", "ISFJ", "ESTJ", "ESFJ",
            ]),
            country="US",
            profession="Social media user",
            interested_topics=["Social Issues", "News", "Online Community"],
            source_entity_uuid=f"scenario_{group.name}_{within_idx}",
            source_entity_type=group.name,
            group_id=group.name,
        )

    @staticmethod
    def _generate_username(name: str) -> str:
        clean = name.lower().replace(" ", "_")
        clean = "".join(c for c in clean if c.isalnum() or c == "_")
        return f"{clean}_{random.randint(100, 999)}"

    def _generate_username_unique(self, name: str, used_usernames: set, lock: Lock) -> str:
        """Generate a username guaranteed unique within the current generation run."""
        clean = name.lower().replace(" ", "_")
        clean = "".join(c for c in clean if c.isalnum() or c == "_")
        with lock:
            for _ in range(900):  # 100–999 = 900 possible suffixes
                candidate = f"{clean}_{random.randint(100, 999)}"
                if candidate not in used_usernames:
                    used_usernames.add(candidate)
                    return candidate
            # Extremely unlikely: all 900 slots taken for this base name
            counter = 1000
            while f"{clean}_{counter}" in used_usernames:
                counter += 1
            candidate = f"{clean}_{counter}"
            used_usernames.add(candidate)
            return candidate

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
