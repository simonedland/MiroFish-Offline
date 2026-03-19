"""
SMS-based agent simulation runner.

Replaces the OASIS subprocess model with a pure-Python async loop where
agents communicate via simulated SMS messages instead of public social media posts.
"""

import asyncio
import json
import logging
import os
import random
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

from openai import AsyncAzureOpenAI

from .sms_db import init_db, register_agents, insert_message, get_thread

logger = logging.getLogger("mirofish.sms_runner")

MAX_TURNS_PER_ROUND = 6


@dataclass
class SmsMessage:
    simulation_id: str
    sender_phone: str
    sender_name: str
    receiver_phone: str
    receiver_name: str
    content: str
    round_num: int
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AgentTurnResult:
    send_message: Optional[str]
    continue_conversation: bool


# Relationship type → base probability of initiating contact this round
RELATIONSHIP_WEIGHTS = {
    "COORDINATES": 0.9,
    "TARGETS": 0.7,
    "DISPUTES": 0.6,
    "KNOWS": 0.5,
    "FOLLOWS": 0.4,
    "REPLIES_TO": 0.5,
    "INFLUENCES": 0.6,
    "AGREES_WITH": 0.5,
    "RIVALS": 0.65,
}
DEFAULT_WEIGHT = 0.3


def _get_sim_dir(simulation_id: str) -> str:
    return os.path.join("uploads", "simulations", simulation_id)


def _get_events_path(simulation_id: str) -> str:
    return os.path.join(_get_sim_dir(simulation_id), "sms_events.jsonl")


def _get_stop_flag_path(simulation_id: str) -> str:
    return os.path.join(_get_sim_dir(simulation_id), "sms_stop.flag")


def _emit_event(simulation_id: str, event_type: str, data: dict) -> None:
    """Append an event to sms_events.jsonl for frontend polling."""
    event = {
        "type": event_type,
        "data": data,
        "timestamp": time.time(),
    }
    events_path = _get_events_path(simulation_id)
    with open(events_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, ensure_ascii=False) + "\n")


class SmsSimulationRunner:
    """
    Runs an SMS-based multi-agent simulation.

    Each round, a subset of agent pairs is selected based on their relationship
    strength. Each selected pair exchanges up to MAX_TURNS_PER_ROUND messages,
    with the LLM deciding when to stop.
    """

    def __init__(
        self,
        simulation_id: str,
        profiles: list,
        relationships: dict,
        config: dict,
    ) -> None:
        self.simulation_id = simulation_id
        self.profiles = profiles
        self.relationships = relationships  # raw relationships_ai.json dict
        self.total_rounds: int = int(config.get("total_rounds", 10))

        # Build phone → profile lookup
        self._phone_to_profile: dict = {p.phone_number: p for p in profiles if p.phone_number}
        self._id_to_profile: dict = {p.user_id: p for p in profiles}

        self._db_lock = asyncio.Lock()
        # Limit concurrent LLM calls to avoid rate-limit errors
        self._llm_semaphore = asyncio.Semaphore(3)

        # Azure OpenAI client (lazy init in async context)
        self._llm_client: Optional[AsyncAzureOpenAI] = None
        self._deployment: str = os.environ.get("AZURE_OPENAI_CHAT_DEPLOYMENT", "gpt-4o")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run(self) -> None:
        """Main entry point. Runs all rounds sequentially."""
        logger.info("SMS simulation %s starting (%d rounds)", self.simulation_id, self.total_rounds)
        self._llm_client = AsyncAzureOpenAI(
            api_key=os.environ.get("AZURE_OPENAI_API_KEY"),
            azure_endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", ""),
            api_version=os.environ.get("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
        try:
            for round_num in range(1, self.total_rounds + 1):
                if self._should_stop():
                    logger.info("Stop flag detected, ending simulation at round %d", round_num)
                    break
                logger.info("Starting round %d/%d", round_num, self.total_rounds)
                await self._run_round(round_num)
        finally:
            await self._llm_client.close()

        _emit_event(self.simulation_id, "simulation_complete", {"total_rounds": self.total_rounds})
        logger.info("SMS simulation %s complete", self.simulation_id)

    # ------------------------------------------------------------------
    # Round execution
    # ------------------------------------------------------------------

    async def _run_round(self, round_num: int) -> None:
        pairs = self._select_active_pairs()
        if not pairs:
            logger.debug("Round %d: no active pairs selected", round_num)
        else:
            tasks = [self._run_conversation(a, b, round_num) for a, b in pairs]
            await asyncio.gather(*tasks, return_exceptions=True)

        _emit_event(self.simulation_id, "round_complete", {"round_num": round_num})

    async def _run_conversation(self, agent_a, agent_b, round_num: int) -> None:
        """Run a back-and-forth conversation between two agents for up to MAX_TURNS_PER_ROUND turns."""
        relationship = self._get_relationship(agent_a.user_id, agent_b.user_id)
        sender, receiver = agent_a, agent_b
        for turn in range(MAX_TURNS_PER_ROUND):
            try:
                result = await self._agent_turn(sender, receiver, round_num, relationship)
            except Exception as exc:
                logger.warning(
                    "Turn %d failed for %s→%s: %s",
                    turn, sender.name, receiver.name, exc, exc_info=True
                )
                break

            if result.send_message:
                msg = SmsMessage(
                    simulation_id=self.simulation_id,
                    sender_phone=sender.phone_number,
                    sender_name=sender.name,
                    receiver_phone=receiver.phone_number,
                    receiver_name=receiver.name,
                    content=result.send_message,
                    round_num=round_num,
                )
                async with self._db_lock:
                    insert_message(self.simulation_id, msg.to_dict())
                    _emit_event(self.simulation_id, "sms_message", msg.to_dict())

            if not result.continue_conversation:
                break

            # Swap for reply
            sender, receiver = receiver, sender

    # ------------------------------------------------------------------
    # Pair selection
    # ------------------------------------------------------------------

    def _select_active_pairs(self) -> list:
        """
        Build a list of (profile_a, profile_b) pairs to converse this round.

        Uses relationship weights and each agent's activity_level to decide
        whether a pair is active. Each unordered pair is evaluated at most once.
        """
        edges = self._extract_edges()
        seen: set = set()
        active_pairs = []

        for edge in edges:
            source_id = edge.get("src_id") or edge.get("source") or edge.get("source_id")
            target_id = edge.get("tgt_id") or edge.get("target") or edge.get("target_id")
            rel_type = (edge.get("type") or edge.get("relationship_type") or "").upper()

            profile_a = self._resolve_profile(source_id)
            profile_b = self._resolve_profile(target_id)
            if profile_a is None or profile_b is None:
                continue
            if not profile_a.phone_number or not profile_b.phone_number:
                continue

            # Deduplicate unordered pairs
            pair_key = tuple(sorted([profile_a.user_id, profile_b.user_id]))
            if pair_key in seen:
                continue
            seen.add(pair_key)

            weight = RELATIONSHIP_WEIGHTS.get(rel_type, DEFAULT_WEIGHT)
            # Scale by activity_level if available (0.0–1.0)
            activity = self._get_activity_level(profile_a)
            weight = min(1.0, weight * (0.5 + activity * 0.5))

            if random.random() < weight:
                active_pairs.append((profile_a, profile_b))

        return active_pairs

    def _extract_edges(self) -> list:
        """Extract edge list from the relationships dict (handles multiple formats)."""
        if isinstance(self.relationships, list):
            return self.relationships
        # Common formats: {"edges": [...]} or {"relationships": [...]}
        for key in ("edges", "relationships", "links"):
            if key in self.relationships:
                val = self.relationships[key]
                if isinstance(val, list):
                    return val
        return []

    def _resolve_profile(self, agent_id):
        """Resolve an agent ID (int, str, or name) to a profile."""
        if agent_id is None:
            return None
        # Try int key first
        try:
            return self._id_to_profile.get(int(agent_id))
        except (ValueError, TypeError):
            pass
        # Try string key
        profile = self._id_to_profile.get(agent_id)
        if profile:
            return profile
        # Try matching by name
        for p in self.profiles:
            if str(p.name).lower() == str(agent_id).lower():
                return p
        return None

    def _get_activity_level(self, profile) -> float:
        """Return activity level 0.0–1.0 from profile."""
        level = getattr(profile, "activity_level", None)
        if level is None:
            return 0.5
        if isinstance(level, str):
            mapping = {"low": 0.25, "medium": 0.5, "high": 0.85, "very_high": 1.0}
            return mapping.get(level.lower(), 0.5)
        try:
            return max(0.0, min(1.0, float(level)))
        except (ValueError, TypeError):
            return 0.5

    # ------------------------------------------------------------------
    # LLM interaction
    # ------------------------------------------------------------------

    async def _agent_turn(self, sender, receiver, round_num: int, relationship: dict = None) -> AgentTurnResult:
        """Ask the LLM to produce one SMS message as sender → receiver."""
        thread = get_thread(self.simulation_id, sender.phone_number, receiver.phone_number, limit=20)
        system_prompt = self._build_system_prompt(sender)
        user_prompt = self._build_user_prompt(sender, receiver, thread, round_num, relationship or {})

        for attempt in range(4):
            try:
                async with self._llm_semaphore:
                    response = await self._llm_client.chat.completions.create(
                        model=self._deployment,
                        messages=[
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_prompt},
                        ],
                        temperature=0.8,
                        max_tokens=256,
                        response_format={"type": "json_object"},
                    )
                raw = response.choices[0].message.content or ""
                return self._parse_turn_response(raw)
            except Exception as exc:
                exc_str = str(exc)
                if "429" in exc_str or "RateLimitReached" in exc_str:
                    # Parse retry-after from error message if available
                    wait = 5 * (2 ** attempt)  # 5, 10, 20, 40s
                    import re as _re
                    match = _re.search(r"retry after (\d+) second", exc_str, _re.IGNORECASE)
                    if match:
                        wait = int(match.group(1)) + 1
                    logger.warning("Rate limited, waiting %ds (attempt %d/4)", wait, attempt + 1)
                    await asyncio.sleep(wait)
                else:
                    logger.warning("LLM call failed: %s", exc)
                    return AgentTurnResult(send_message=None, continue_conversation=False)

        return AgentTurnResult(send_message=None, continue_conversation=False)

    def _get_relationship(self, id_a: int, id_b: int) -> dict:
        """Return the edge dict between two agents (either direction), or {}."""
        for edge in self._extract_edges():
            src = edge.get("src_id") or edge.get("source") or edge.get("source_id")
            tgt = edge.get("tgt_id") or edge.get("target") or edge.get("target_id")
            try:
                src, tgt = int(src), int(tgt)
            except (TypeError, ValueError):
                continue
            if (src == id_a and tgt == id_b) or (src == id_b and tgt == id_a):
                return edge
        return {}

    def _build_system_prompt(self, sender) -> str:
        # Collect contacts with relationship type and label
        contact_lines = []
        for edge in self._extract_edges():
            source_id = edge.get("src_id") or edge.get("source") or edge.get("source_id")
            target_id = edge.get("tgt_id") or edge.get("target") or edge.get("target_id")
            rel_type = (edge.get("type") or edge.get("relationship_type") or "KNOWS").upper()
            label = edge.get("label", "")

            src_profile = self._resolve_profile(source_id)
            tgt_profile = self._resolve_profile(target_id)
            if src_profile is None or tgt_profile is None:
                continue

            if src_profile.user_id == sender.user_id:
                contact = tgt_profile
            elif tgt_profile.user_id == sender.user_id:
                contact = src_profile
            else:
                continue

            if contact.phone_number:
                label_part = f' — "{label}"' if label else ""
                contact_lines.append(
                    f"- {contact.name} ({contact.phone_number}): [{rel_type}]{label_part}"
                )

        contacts_block = "\n".join(contact_lines) if contact_lines else "- (no contacts)"

        persona = getattr(sender, "persona", "") or getattr(sender, "bio", "") or ""

        return (
            f"Simulation character: {sender.name}, phone {sender.phone_number}.\n"
            f"Background: {persona}\n\n"
            f"Contacts:\n{contacts_block}\n\n"
            "Write short, realistic SMS messages (1–3 sentences) as this character would text. "
            "Match the tone and topic suggested by each relationship label."
        )

    def _build_user_prompt(self, sender, receiver, thread: list, round_num: int, relationship: dict = None) -> str:
        rel_type = (relationship.get("type") or "").upper() if relationship else ""
        rel_label = relationship.get("label", "") if relationship else ""

        # Build a short relationship context line
        if rel_label:
            rel_context = f"[{rel_type}: {rel_label}]" if rel_type else f"[{rel_label}]"
        elif rel_type:
            rel_context = f"[{rel_type}]"
        else:
            rel_context = ""

        history_lines = []
        for msg in thread:
            s_name = msg.get("sender_name", "?")
            content = msg.get("content", "")
            history_lines.append(f"{s_name}: {content}")

        history_block = (
            "\n".join(history_lines)
            if history_lines
            else "(no previous messages — you can start a conversation)"
        )

        rel_line = f"\nRelationship: {rel_context}" if rel_context else ""

        return (
            f"[SMS thread with {receiver.name}]{rel_line}\n"
            f"{history_block}\n\n"
            f"Round {round_num}. Write the next SMS from {sender.name} to {receiver.name}, "
            "fitting the relationship and conversation so far. "
            "If there is genuinely nothing to say, set send_message to null.\n"
            'Respond with JSON only: {"send_message": "<text or null>", "continue_conversation": <true|false>}'
        )

    @staticmethod
    def _parse_turn_response(raw: str) -> AgentTurnResult:
        """Parse JSON response from LLM into AgentTurnResult."""
        try:
            data = json.loads(raw.strip())
            msg = data.get("send_message")
            if msg == "null" or msg == "":
                msg = None
            cont = bool(data.get("continue_conversation", True))
            return AgentTurnResult(send_message=msg, continue_conversation=cont)
        except (json.JSONDecodeError, AttributeError):
            logger.warning("Failed to parse LLM response: %r", raw[:200])
            return AgentTurnResult(send_message=None, continue_conversation=False)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _should_stop(self) -> bool:
        return os.path.exists(_get_stop_flag_path(self.simulation_id))
