"""
AI-driven agent relationship negotiator for description-flow simulations.

Each agent runs its own agentic LLM loop with tool calls to browse the agent
roster and the growing social graph, then declares its own relationships.
Results are cached to relationships_ai.json in the simulation dir.
"""

import json
import logging
import os
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional

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
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Return edges [{src_id, tgt_id, type, label}]. Cached unless force=True.

        progress_callback(agent_current, agent_total, relationship_count) is called
        after each agent completes its negotiation loop.
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

        # Degenerate inputs
        if len(profiles) < 2:
            logger.warning(
                f"RelationshipGenerator: need at least 2 profiles, got {len(profiles)}. Returning []."
            )
            return []

        edges = self._negotiate_all(profiles, groups, progress_callback=progress_callback)

        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(edges, f, indent=2)
        except Exception as e:
            logger.warning(f"Cache write failed: {e}")

        return edges

    # ------------------------------------------------------------------
    # Tools schema + dispatcher
    # ------------------------------------------------------------------

    @staticmethod
    def _build_tools_schema() -> List[Dict]:
        """Return the OpenAI function-calling tools schema for all four tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": "list_agents",
                    "description": "List all agents in the simulation: id, username, group, bio_snippet.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_agent_profile",
                    "description": "Get the full profile of an agent by their user_id.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "agent_id": {"type": "integer", "description": "The user_id of the agent to look up."}
                        },
                        "required": ["agent_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_full_graph",
                    "description": "Get all social relationships declared by previous agents so far.",
                    "parameters": {"type": "object", "properties": {}, "required": []},
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "declare_relationship",
                    "description": "Declare a relationship from yourself to another agent.",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "tgt_id": {"type": "integer", "description": "user_id of the target agent."},
                            "type": {
                                "type": "string",
                                "enum": sorted(VALID_TYPES),
                                "description": "Relationship type.",
                            },
                            "label": {"type": "string", "description": "Short human-readable phrase (e.g. 'childhood friends')."},
                        },
                        "required": ["tgt_id", "type", "label"],
                    },
                },
            },
        ]

    def _dispatch_tool(
        self,
        tool_name: str,
        tool_args: Dict,
        src_id: int,
        profiles_by_id: Dict[int, Dict],
        shared_graph: List[Dict],
        staged_buffer: List[Dict],
    ) -> str:
        """Dispatch a tool call by name and return the result as a string."""
        if tool_name == "list_agents":
            return self._tool_list_agents(profiles_by_id)
        elif tool_name == "get_agent_profile":
            return self._tool_get_agent_profile(
                int(tool_args.get("agent_id", -1)), profiles_by_id
            )
        elif tool_name == "get_full_graph":
            return self._tool_get_full_graph(shared_graph)
        elif tool_name == "declare_relationship":
            return self._tool_declare_relationship(
                src_id=src_id,
                tgt_id=int(tool_args.get("tgt_id", -1)),
                rel_type=str(tool_args.get("type", "")),
                label=str(tool_args.get("label", "")),
                profiles_by_id=profiles_by_id,
                staged_buffer=staged_buffer,
            )
        else:
            return f"error: unknown tool '{tool_name}'"

    @staticmethod
    def _build_system_prompt(profile: Dict, group_name: str, group_description: str) -> str:
        username = profile.get("username", profile.get("user_name", "agent"))
        profile_json = json.dumps(profile, ensure_ascii=False, indent=2)
        return (
            f"Simulation character: {username}\n\n"
            f"Profile:\n{profile_json}\n\n"
            f"Group: {group_name} — {group_description}\n\n"
            "Task: establish social connections for this character before the simulation begins.\n"
            "Use the available tools to browse other participants and the growing social graph,\n"
            "then declare the relationships that fit this character's background.\n\n"
            "Guidance: 2–8 relationships is typical. Fewer for a loner, more for a highly social\n"
            "character — let the background guide the count, not a desire to maximise connections.\n\n"
            "When finished declaring relationships, stop calling tools and send a brief closing note."
        )

    def _run_agent_loop(
        self,
        profile: Dict,
        groups: List[Dict],
        profiles_by_id: Dict[int, Dict],
        shared_graph: List[Dict],
        graph_lock: threading.Lock = None,
    ) -> List[Dict]:
        """
        Run the agentic loop for a single agent.
        Returns the list of edges staged (flushed on clean exit or max-turn; discarded on exception).
        """
        src_id = profile.get("user_id", profile.get("id", 0))
        group_id = profile.get("group_id", "")
        matched = next((g for g in groups if g.get("name") == group_id), None)
        group_name = matched["name"] if matched else group_id
        group_description = matched.get("behavior_description", "") if matched else ""

        system_prompt = self._build_system_prompt(profile, group_name, group_description)
        messages = [{"role": "system", "content": system_prompt}]
        tools = self._build_tools_schema()
        staged_buffer: List[Dict] = []

        for turn in range(MAX_TURNS):
            resp = None
            for attempt in range(4):
                try:
                    resp = self.client.chat.completions.create(
                        model=self.model_name,
                        messages=messages,
                        tools=tools,
                        tool_choice="auto",
                        temperature=0.7,
                    )
                    break
                except Exception as exc:
                    exc_str = str(exc)
                    if "429" in exc_str or "RateLimitReached" in exc_str:
                        wait = 5 * (2 ** attempt)
                        m = re.search(r"retry after (\d+) second", exc_str, re.IGNORECASE)
                        if m:
                            wait = int(m.group(1)) + 1
                        logger.warning("Rate limited, waiting %ds (attempt %d/4)", wait, attempt + 1)
                        time.sleep(wait)
                    else:
                        raise
            if resp is None:
                raise RuntimeError("LLM call failed after 4 rate-limit retries")
            msg = resp.choices[0].message

            # Build a serialisable dict for the assistant turn
            assistant_entry: Dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
            if msg.tool_calls:
                assistant_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {"name": tc.function.name, "arguments": tc.function.arguments},
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_entry)

            if not msg.tool_calls:
                # Natural finish
                logger.debug(f"Agent {src_id} finished naturally after {turn + 1} turn(s)")
                break

            # Dispatch each tool call and append results
            for tc in msg.tool_calls:
                try:
                    args = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    args = {}
                # Take a thread-safe snapshot of shared_graph for read-only tools
                if graph_lock is not None and tc.function.name == "get_full_graph":
                    with graph_lock:
                        graph_snapshot = list(shared_graph)
                else:
                    graph_snapshot = shared_graph
                result = self._dispatch_tool(
                    tc.function.name, args, src_id, profiles_by_id, graph_snapshot, staged_buffer
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            logger.warning(f"Agent {src_id} hit max-turn guard ({MAX_TURNS} turns)")

        return staged_buffer

    # ------------------------------------------------------------------
    # Core negotiation loop
    # ------------------------------------------------------------------

    MAX_PARALLEL_AGENTS = 3

    def _negotiate_all(
        self,
        profiles: List[Dict[str, Any]],
        groups: List[Dict[str, Any]],
        progress_callback: Optional[Callable[[int, int, int], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Run agent agentic loops in parallel (up to MAX_PARALLEL_AGENTS at once)."""
        profiles_sorted = sorted(profiles, key=lambda p: p.get("user_id", p.get("id", 0)))
        profiles_by_id = {p.get("user_id", p.get("id", 0)): p for p in profiles_sorted}

        shared_graph: List[Dict] = []
        graph_lock = threading.Lock()
        counter_lock = threading.Lock()
        completed = 0
        failed = 0
        total = len(profiles_sorted)

        def run_one(profile: Dict) -> tuple:
            uid = profile.get("user_id", profile.get("id"))
            username = profile.get("username", profile.get("user_name", f"agent_{uid}"))
            logger.info(f"Negotiating relationships for agent {uid} ({username})")
            try:
                staged = self._run_agent_loop(
                    profile, groups, profiles_by_id, shared_graph, graph_lock
                )
                with graph_lock:
                    existing_typed = {
                        (min(e["src_id"], e["tgt_id"]), max(e["src_id"], e["tgt_id"]), e["type"])
                        for e in shared_graph
                    }
                    deduped = []
                    for edge in staged:
                        key = (min(edge["src_id"], edge["tgt_id"]), max(edge["src_id"], edge["tgt_id"]), edge["type"])
                        if key not in existing_typed:
                            deduped.append(edge)
                            existing_typed.add(key)
                    shared_graph.extend(deduped)
                    graph_size = len(shared_graph)
                logger.info(f"Agent {uid} declared {len(staged)} relationship(s); graph total: {graph_size}")
                return False
            except Exception as e:
                logger.warning(f"Agent {uid} loop failed: {e}")
                return True

        workers = min(self.MAX_PARALLEL_AGENTS, total)
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(run_one, p) for p in profiles_sorted]
            for future in as_completed(futures):
                is_failed = future.result()
                with counter_lock:
                    completed += 1
                    if is_failed:
                        failed += 1
                    current = completed
                with graph_lock:
                    graph_size = len(shared_graph)
                if progress_callback:
                    try:
                        progress_callback(current, total, graph_size)
                    except Exception:
                        pass

        if total > 0 and failed / total > FAILURE_THRESHOLD:
            raise RuntimeError(
                f"RelationshipGenerator: {failed}/{total} agents failed "
                f"(>{FAILURE_THRESHOLD:.0%} threshold). Check LLM connectivity."
            )

        return shared_graph

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
        """declare_relationship(...) → 'ok' or error string. Mutates staged_buffer on success."""
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
