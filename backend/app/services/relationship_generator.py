"""
AI-driven agent relationship generator for description-flow simulations.

Reads profiles + group definitions, sends a compact roster to the LLM,
and gets back a list of typed edges (src_id, tgt_id, type, label).
Results are cached to relationships_ai.json in the simulation dir.
"""

import json
import os
import re
import logging
from typing import List, Dict, Any

from openai import AzureOpenAI

from ..config import Config

logger = logging.getLogger("mirofish.relationship_generator")

# Relationship types the LLM may use
VALID_TYPES = {
    "KNOWS", "FOLLOWS", "COORDINATES", "REPLIES_TO",
    "INFLUENCES", "TARGETS", "DISPUTES", "AGREES_WITH", "RIVALS",
}

# Max agents to send in a single LLM call (token budget: ~50 tok/agent)
BATCH_SIZE = 120


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

    def generate(
        self,
        simulation_dir: str,
        profiles: List[Dict[str, Any]],
        groups: List[Dict[str, Any]],
        force: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        Return a list of edges: [{src_id, tgt_id, type, label}]

        Reads from cache (relationships_ai.json) unless force=True.
        """
        cache_path = os.path.join(simulation_dir, "relationships_ai.json")
        if not force and os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    cached = json.load(f)
                logger.info(f"Loaded {len(cached)} relationships from cache")
                return cached
            except Exception as e:
                logger.warning(f"Cache read failed, regenerating: {e}")

        edges = self._call_llm(profiles, groups)
        # Save cache
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(edges, f, indent=2)
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")

        return edges

    # ------------------------------------------------------------------

    def _call_llm(
        self,
        profiles: List[Dict[str, Any]],
        groups: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Build the prompt, call the LLM, parse the JSON response."""

        # Build group context string
        group_ctx = "\n".join(
            f"- {g['name']} ({g.get('label', '')}): {g.get('behavior_description', '')} | stance={g.get('stance', '')} | style={g.get('communication_style', '')}"
            for g in groups
        )

        # Compact roster — one line per agent
        roster_lines = []
        for p in profiles[:BATCH_SIZE]:
            uid  = p.get("user_id", p.get("id", "?"))
            name = p.get("username", p.get("user_name", p.get("name", f"agent_{uid}")))
            grp  = p.get("group_id", "unknown")
            bio  = (p.get("bio") or p.get("persona") or "")[:80].replace("\n", " ")
            roster_lines.append(f"[{uid}] @{name} ({grp}) — {bio}")
        roster = "\n".join(roster_lines)

        n_agents = len(profiles[:BATCH_SIZE])
        n_edges  = min(n_agents * 3, 300)  # aim for ~3 edges per agent, capped at 300

        prompt = f"""You are building a social network graph for a simulation.

GROUPS:
{group_ctx}

AGENTS (id, username, group, bio):
{roster}

Generate exactly {n_edges} meaningful social relationships between these agents.

Rules:
- src_id != tgt_id
- Agents in the same group should have denser connections
- "coordinate_within_group" groups should mostly use COORDINATES
- Bad-actor / disruptive groups should TARGETS or INFLUENCES normal users
- Use varied, realistic relationship types
- type must be one of: KNOWS, FOLLOWS, COORDINATES, REPLIES_TO, INFLUENCES, TARGETS, DISPUTES, AGREES_WITH, RIVALS
- label is a short human-readable phrase (e.g. "childhood friends", "political rivals", "often replies to posts")

Return ONLY a valid JSON array, no markdown fences, no commentary:
[{{"src_id": 0, "tgt_id": 5, "type": "FOLLOWS", "label": "follows for news"}}, ...]"""

        for attempt in range(3):
            try:
                resp = self.client.chat.completions.create(
                    model=self.model_name,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.7,
                    max_tokens=4000,
                )
                raw = resp.choices[0].message.content.strip()
                edges = self._parse_edges(raw, profiles)
                logger.info(f"LLM returned {len(edges)} relationships (attempt {attempt+1})")
                return edges
            except Exception as e:
                logger.warning(f"LLM attempt {attempt+1} failed: {e}")

        logger.error("All LLM attempts failed — returning empty edge list")
        return []

    def _parse_edges(
        self,
        raw: str,
        profiles: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Parse LLM JSON output, validate and deduplicate edges."""
        # Strip markdown fences if present
        raw = re.sub(r"^```[a-z]*\n?", "", raw.strip())
        raw = re.sub(r"\n?```$", "", raw.strip())

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Try to extract the first JSON array from the response
            m = re.search(r"\[.*\]", raw, re.DOTALL)
            if not m:
                return []
            data = json.loads(m.group())

        valid_ids = {p.get("user_id", p.get("id")) for p in profiles}
        seen = set()
        edges = []

        for item in data:
            if not isinstance(item, dict):
                continue
            src = item.get("src_id")
            tgt = item.get("tgt_id")
            typ = str(item.get("type", "KNOWS")).upper()
            label = item.get("label") or typ

            # Validate
            if src == tgt:
                continue
            if src not in valid_ids or tgt not in valid_ids:
                continue
            if typ not in VALID_TYPES:
                typ = "KNOWS"

            key = (src, tgt)
            if key in seen:
                continue
            seen.add(key)

            edges.append({"src_id": src, "tgt_id": tgt, "type": typ, "label": label})

        return edges
