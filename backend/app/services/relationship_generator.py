"""
AI-driven agent relationship negotiator for description-flow simulations.

Each agent runs its own agentic LLM loop with tool calls to browse the agent
roster and the growing social graph, then declares its own relationships.
Results are cached to relationships_ai.json in the simulation dir.
"""

import json
import logging
import os
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI

from ..config import Config

logger = logging.getLogger("mirofish.relationship_generator")

VALID_TYPES = {
    "KNOWS", "FOLLOWS", "COORDINATES", "REPLIES_TO",
    "INFLUENCES", "TARGETS", "DISPUTES", "AGREES_WITH", "RIVALS",
}

MAX_TURNS = 10
FAILURE_THRESHOLD = 0.5  # raise RuntimeError if more than this fraction of agents fail


class RelationshipGenerator:

    def __init__(self):
        self.client = AzureOpenAI(
            api_key=Config.AZURE_OPENAI_API_KEY,
            azure_endpoint=Config.AZURE_OPENAI_ENDPOINT,
            api_version=Config.AZURE_OPENAI_API_VERSION,
            timeout=90,
        )
        self.model_name = Config.AZURE_OPENAI_CHAT_DEPLOYMENT
        if not self.model_name:
            raise ValueError("AZURE_OPENAI_CHAT_DEPLOYMENT not configured")

    # ------------------------------------------------------------------
    # Public interface (unchanged from original)
    # ------------------------------------------------------------------

    def generate(
        self,
        simulation_dir: str,
        profiles: List[Dict[str, Any]],
        groups: List[Dict[str, Any]],
        force: bool = False,
    ) -> List[Dict[str, Any]]:
        """Return edges [{src_id, tgt_id, type, label}]. Cached unless force=True."""
        cache_path = os.path.join(simulation_dir, "relationships_ai.json")
        if not force and os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                logger.info(f"Loaded {len(cached)} relationships from cache")
                return cached
            except Exception as e:
                logger.warning(f"Cache read failed, regenerating: {e}")

        # Degenerate inputs
        if len(profiles) < 2:
            logger.warning(
                f"RelationshipGenerator: need at least 2 profiles, got {len(profiles)}. Returning []."
            )
            return []

        edges = self._negotiate_all(profiles, groups)

        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(edges, f, indent=2)
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")

        return edges

    # ------------------------------------------------------------------
    # (stubs — implemented in later tasks)
    # ------------------------------------------------------------------

    def _negotiate_all(self, profiles, groups):
        raise NotImplementedError

    # ------------------------------------------------------------------
    # Tool implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _tool_list_agents(profiles_by_id: Dict[int, Dict]) -> str:
        """list_agents() → JSON array sorted ascending by user_id."""
        roster = []
        for uid in sorted(profiles_by_id.keys()):
            p = profiles_by_id[uid]
            bio = (p.get("bio") or "")[:80].replace("\n", " ")
            roster.append({
                "id": uid,
                "username": p.get("username", p.get("user_name", f"agent_{uid}")),
                "group": p.get("group_id", ""),
                "bio_snippet": bio,
            })
        return json.dumps(roster)

    @staticmethod
    def _tool_get_agent_profile(agent_id: int, profiles_by_id: Dict[int, Dict]) -> str:
        """get_agent_profile(agent_id) → JSON profile or error."""
        if agent_id not in profiles_by_id:
            return json.dumps({"error": f"agent_id {agent_id} not found"})
        return json.dumps(profiles_by_id[agent_id])

    @staticmethod
    def _tool_get_full_graph(shared_graph: List[Dict]) -> str:
        """get_full_graph() → JSON array of committed edges."""
        return json.dumps(shared_graph)

    @staticmethod
    def _tool_declare_relationship(
        src_id: int,
        tgt_id: int,
        rel_type: str,
        label: str,
        profiles_by_id: Dict[int, Dict],
        staged_buffer: List[Dict],
    ) -> str:
        """declare_relationship(...) → 'ok' or error string."""
        if tgt_id not in profiles_by_id:
            return f"error: tgt_id {tgt_id} does not exist"
        if src_id == tgt_id:
            return "error: src_id and tgt_id must be different"
        rel_type = str(rel_type).upper()
        if rel_type not in VALID_TYPES:
            return f"error: type must be one of {sorted(VALID_TYPES)}"
        if not label or not str(label).strip():
            return "error: label is required and must be non-empty"
        label = str(label)[:120]

        # Deduplicate within this agent's staged buffer
        for existing in staged_buffer:
            if existing["src_id"] == src_id and existing["tgt_id"] == tgt_id:
                # Silently replace with latest declaration
                existing["type"] = rel_type
                existing["label"] = label
                return "ok"

        staged_buffer.append({"src_id": src_id, "tgt_id": tgt_id, "type": rel_type, "label": label})
        return "ok"
