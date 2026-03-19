# Dynamic Agent Relationship Negotiation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite `RelationshipGenerator` so each agent runs its own agentic LLM loop with tool calls to browse the agent roster and growing social graph, then declares its own relationships.

**Architecture:** Sequential per-agent loop using Azure OpenAI function-calling API. Each agent gets four tools (`list_agents`, `get_agent_profile`, `get_full_graph`, `declare_relationship`). Edges are staged per-agent and flushed to a shared graph after each loop. Class name and public interface are preserved so no other files change.

**Tech Stack:** Python, Azure OpenAI (`openai` SDK), `unittest.mock` for tests

---

## Files

| File | Action | Responsibility |
|------|--------|---------------|
| `backend/app/services/relationship_generator.py` | Rewrite | All negotiation logic; public interface preserved |
| `backend/tests/__init__.py` | Create | Makes `tests` a package |
| `backend/tests/services/__init__.py` | Create | Makes `tests/services` a package |
| `backend/tests/services/test_relationship_generator.py` | Create | All unit tests |

---

## Task 1: Create test infrastructure

**Files:**
- Create: `backend/tests/__init__.py`
- Create: `backend/tests/services/__init__.py`
- Create: `backend/tests/services/test_relationship_generator.py`

- [ ] **Step 1: Create the package init files**

```bash
# Run from repo root
touch backend/tests/__init__.py backend/tests/services/__init__.py
```

- [ ] **Step 2: Write the test file with shared fixtures**

Create `backend/tests/services/test_relationship_generator.py`:

```python
"""
Tests for the agentic RelationshipGenerator.
All LLM calls are mocked — no real Azure OpenAI calls are made.
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch, call


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

PROFILES = [
    {
        "user_id": 0,
        "username": "alice",
        "name": "Alice",
        "bio": "Likes cats and coffee.",
        "persona": "Alice is a 30yo barista who posts about daily life.",
        "group_id": "normal",
    },
    {
        "user_id": 1,
        "username": "bob",
        "name": "Bob",
        "bio": "Tech enthusiast, occasional troll.",
        "persona": "Bob is a 25yo developer.",
        "group_id": "tech",
    },
    {
        "user_id": 2,
        "username": "carol",
        "name": "Carol",
        "bio": "Political activist.",
        "persona": "Carol is a 40yo community organiser.",
        "group_id": "normal",
    },
]

GROUPS = [
    {
        "name": "normal",
        "label": "Normal Users",
        "behavior_description": "Everyday social media users",
        "stance": "neutral",
        "communication_style": "casual",
    },
    {
        "name": "tech",
        "label": "Tech Community",
        "behavior_description": "Technology enthusiasts",
        "stance": "positive",
        "communication_style": "informative",
    },
]


from backend.app.services.relationship_generator import RelationshipGenerator, VALID_TYPES


def _make_finish_response(content="Done."):
    """Return a mock ChatCompletion that has no tool calls (natural finish)."""
    msg = MagicMock()
    msg.content = content
    msg.tool_calls = None
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp


def _make_tool_call_response(tool_name, tool_args: dict, call_id="call_1"):
    """Return a mock ChatCompletion with a single tool call."""
    tc = MagicMock()
    tc.id = call_id
    tc.function.name = tool_name
    tc.function.arguments = json.dumps(tool_args)
    msg = MagicMock()
    msg.content = None
    msg.tool_calls = [tc]
    choice = MagicMock()
    choice.message = msg
    resp = MagicMock()
    resp.choices = [choice]
    return resp
```

- [ ] **Step 3: Verify the test file is importable**

```bash
cd backend && python -c "from tests.services.test_relationship_generator import PROFILES; print('ok')"
```
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add backend/tests/ && git commit -m "test: scaffold test infrastructure for RelationshipGenerator"
```

---

## Task 2: Tests for degenerate inputs and caching

**Files:**
- Modify: `backend/tests/services/test_relationship_generator.py`

- [ ] **Step 1: Add tests for empty profiles, single-agent profiles, and cache hit**

Append to `backend/tests/services/test_relationship_generator.py`:

```python
# ---------------------------------------------------------------------------
# Import the class under test (patched at module level to avoid real client)
# ---------------------------------------------------------------------------
@patch("backend.app.services.relationship_generator.AzureOpenAI")
class TestDegenerateInputs:

    def test_empty_profiles_returns_empty(self, mock_azure, tmp_path):
        gen = RelationshipGenerator()
        result = gen.generate(str(tmp_path), [], GROUPS)
        assert result == []

    def test_single_profile_returns_empty(self, mock_azure, tmp_path):
        gen = RelationshipGenerator()
        result = gen.generate(str(tmp_path), [PROFILES[0]], GROUPS)
        assert result == []

    def test_cache_hit_skips_llm(self, mock_azure, tmp_path):
        cached = [{"src_id": 0, "tgt_id": 1, "type": "FOLLOWS", "label": "friends"}]
        cache_path = tmp_path / "relationships_ai.json"
        cache_path.write_text(json.dumps(cached))

        gen = RelationshipGenerator()
        result = gen.generate(str(tmp_path), PROFILES, GROUPS, force=False)

        assert result == cached
        # LLM client should never have been called
        mock_azure.return_value.chat.completions.create.assert_not_called()

    def test_force_ignores_cache(self, mock_azure, tmp_path):
        cached = [{"src_id": 0, "tgt_id": 1, "type": "FOLLOWS", "label": "old"}]
        cache_path = tmp_path / "relationships_ai.json"
        cache_path.write_text(json.dumps(cached))

        # Every agent immediately finishes (no tool calls, no relationships)
        mock_azure.return_value.chat.completions.create.return_value = (
            _make_finish_response()
        )

        gen = RelationshipGenerator()
        result = gen.generate(str(tmp_path), PROFILES, GROUPS, force=True)

        # Result should be fresh (empty, since agents declared nothing)
        assert result == []
```

- [ ] **Step 2: Run the tests (expect failures — class not yet rewritten)**

```bash
cd backend && python -m pytest tests/services/test_relationship_generator.py::TestDegenerateInputs -v
```
Expected: `ImportError` or test failures — the current class doesn't have the right behaviour yet. That's fine.

- [ ] **Step 3: Commit the tests**

```bash
git add backend/tests/services/test_relationship_generator.py
git commit -m "test: add degenerate input and cache tests for RelationshipGenerator"
```

---

## Task 3: Rewrite `RelationshipGenerator` — skeleton + degenerate inputs + caching

**Files:**
- Modify: `backend/app/services/relationship_generator.py`

- [ ] **Step 1: Replace the file with the new skeleton**

```python
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
```

- [ ] **Step 2: Run the degenerate input and cache tests**

```bash
cd backend && python -m pytest tests/services/test_relationship_generator.py::TestDegenerateInputs -v
```
Expected: all 4 tests PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/services/relationship_generator.py
git commit -m "feat: RelationshipGenerator skeleton with degenerate inputs and caching"
```

---

## Task 4: Implement and test the four tool functions

**Files:**
- Modify: `backend/app/services/relationship_generator.py`
- Modify: `backend/tests/services/test_relationship_generator.py`

Tools are pure functions that operate on in-memory data. Implement them as static/instance methods, then write tests against them directly (not through the LLM loop).

- [ ] **Step 1: Add the tool helper methods to `RelationshipGenerator`**

Add these methods inside the class, below `_negotiate_all`:

```python
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
```

- [ ] **Step 2: Add unit tests for the tool functions**

Append to the test file:

```python
class TestToolFunctions:
    """Test the four tool methods directly — no LLM involved."""

    def setup_method(self):
        self.profiles_by_id = {p["user_id"]: p for p in PROFILES}

    # list_agents --------------------------------------------------------

    def test_list_agents_returns_sorted_roster(self):
        result = json.loads(RelationshipGenerator._tool_list_agents(self.profiles_by_id))
        ids = [r["id"] for r in result]
        assert ids == sorted(ids)
        assert len(result) == 3
        assert result[0]["username"] == "alice"

    def test_list_agents_bio_snippet_truncated(self):
        long_bio_profiles = {
            0: {**PROFILES[0], "bio": "x" * 200},
        }
        result = json.loads(RelationshipGenerator._tool_list_agents(long_bio_profiles))
        assert len(result[0]["bio_snippet"]) == 80

    # get_agent_profile --------------------------------------------------

    def test_get_agent_profile_returns_profile(self):
        result = json.loads(RelationshipGenerator._tool_get_agent_profile(1, self.profiles_by_id))
        assert result["username"] == "bob"

    def test_get_agent_profile_unknown_id_returns_error(self):
        result = json.loads(RelationshipGenerator._tool_get_agent_profile(99, self.profiles_by_id))
        assert "error" in result

    # get_full_graph -----------------------------------------------------

    def test_get_full_graph_returns_edges(self):
        graph = [{"src_id": 0, "tgt_id": 1, "type": "FOLLOWS", "label": "friends"}]
        result = json.loads(RelationshipGenerator._tool_get_full_graph(graph))
        assert len(result) == 1
        assert result[0]["type"] == "FOLLOWS"

    def test_get_full_graph_empty(self):
        result = json.loads(RelationshipGenerator._tool_get_full_graph([]))
        assert result == []

    # declare_relationship -----------------------------------------------

    def test_declare_relationship_valid(self):
        staged = []
        out = RelationshipGenerator._tool_declare_relationship(
            0, 1, "FOLLOWS", "alice follows bob", self.profiles_by_id, staged
        )
        assert out == "ok"
        assert len(staged) == 1
        assert staged[0] == {"src_id": 0, "tgt_id": 1, "type": "FOLLOWS", "label": "alice follows bob"}

    def test_declare_relationship_unknown_target(self):
        staged = []
        out = RelationshipGenerator._tool_declare_relationship(
            0, 99, "FOLLOWS", "test", self.profiles_by_id, staged
        )
        assert "error" in out
        assert staged == []

    def test_declare_relationship_self_loop(self):
        staged = []
        out = RelationshipGenerator._tool_declare_relationship(
            0, 0, "FOLLOWS", "test", self.profiles_by_id, staged
        )
        assert "error" in out

    def test_declare_relationship_invalid_type(self):
        staged = []
        out = RelationshipGenerator._tool_declare_relationship(
            0, 1, "HATES", "test", self.profiles_by_id, staged
        )
        assert "error" in out

    def test_declare_relationship_empty_label(self):
        staged = []
        out = RelationshipGenerator._tool_declare_relationship(
            0, 1, "FOLLOWS", "", self.profiles_by_id, staged
        )
        assert "error" in out

    def test_declare_relationship_label_truncated_to_120(self):
        staged = []
        RelationshipGenerator._tool_declare_relationship(
            0, 1, "FOLLOWS", "x" * 200, self.profiles_by_id, staged
        )
        assert len(staged[0]["label"]) == 120

    def test_declare_relationship_deduplicates_within_buffer(self):
        staged = []
        RelationshipGenerator._tool_declare_relationship(
            0, 1, "FOLLOWS", "first", self.profiles_by_id, staged
        )
        RelationshipGenerator._tool_declare_relationship(
            0, 1, "KNOWS", "second", self.profiles_by_id, staged
        )
        # Should update, not append
        assert len(staged) == 1
        assert staged[0]["type"] == "KNOWS"
        assert staged[0]["label"] == "second"
```

- [ ] **Step 3: Run tool tests**

```bash
cd backend && python -m pytest tests/services/test_relationship_generator.py::TestToolFunctions -v
```
Expected: all 12 tests PASS

- [ ] **Step 4: Commit**

```bash
git add backend/app/services/relationship_generator.py backend/tests/services/test_relationship_generator.py
git commit -m "feat: implement four tool functions (list_agents, get_agent_profile, get_full_graph, declare_relationship)"
```

---

## Task 5: Implement and test the per-agent agentic loop

**Files:**
- Modify: `backend/app/services/relationship_generator.py`
- Modify: `backend/tests/services/test_relationship_generator.py`

- [ ] **Step 1: Add the OpenAI tools schema builder and tool dispatcher**

Add these methods inside the class:

```python
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
            f"You are {username}, a social media user.\n\n"
            f"Your profile:\n{profile_json}\n\n"
            f"Your group: {group_name} — {group_description}\n\n"
            "You are setting up your social connections before joining a simulation.\n"
            "Use the available tools to explore who else is participating and what\n"
            "relationships already exist. Then declare the relationships that feel\n"
            "authentic to your character.\n\n"
            "Guidance: 2–8 relationships is typical for most personas. You may declare\n"
            "fewer if you are a loner, or more if you are highly social — but let your\n"
            "character guide you, not a desire to maximise connections.\n\n"
            "When you are done declaring relationships, stop calling tools and reply\n"
            "with a brief closing statement."
        )

    def _run_agent_loop(
        self,
        profile: Dict,
        groups: List[Dict],
        profiles_by_id: Dict[int, Dict],
        shared_graph: List[Dict],
    ) -> List[Dict]:
        """
        Run the agentic loop for a single agent.
        Returns the list of edges staged (flushed on clean exit or max-turn; discarded on exception).
        """
        src_id = profile.get("user_id", profile.get("id"))
        group_id = profile.get("group_id", "")
        matched = next((g for g in groups if g.get("name") == group_id), None)
        group_name = matched["name"] if matched else group_id
        group_description = matched.get("behavior_description", "") if matched else ""

        system_prompt = self._build_system_prompt(profile, group_name, group_description)
        messages = [{"role": "system", "content": system_prompt}]
        tools = self._build_tools_schema()
        staged_buffer: List[Dict] = []

        for turn in range(MAX_TURNS):
            resp = self.client.chat.completions.create(
                model=self.model_name,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=0.7,
            )
            msg = resp.choices[0].message

            # Append assistant message to history
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
                result = self._dispatch_tool(
                    tc.function.name, args, src_id, profiles_by_id, shared_graph, staged_buffer
                )
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })
        else:
            logger.warning(f"Agent {src_id} hit max-turn guard ({MAX_TURNS} turns)")

        return staged_buffer
```

- [ ] **Step 2: Implement `_negotiate_all`**

Replace the `_negotiate_all` stub:

```python
    def _negotiate_all(
        self,
        profiles: List[Dict[str, Any]],
        groups: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Iterate agents sequentially; each runs its own agentic loop."""
        profiles_sorted = sorted(profiles, key=lambda p: p.get("user_id", p.get("id", 0)))
        profiles_by_id = {p.get("user_id", p.get("id")): p for p in profiles_sorted}

        shared_graph: List[Dict] = []
        failed = 0

        for profile in profiles_sorted:
            uid = profile.get("user_id", profile.get("id"))
            username = profile.get("username", profile.get("user_name", f"agent_{uid}"))
            logger.info(f"Negotiating relationships for agent {uid} ({username})")

            # Token budget warning: rough estimate
            estimated_tokens = len(json.dumps(shared_graph)) // 4
            if estimated_tokens > 50_000:
                logger.warning(
                    f"Shared graph is large (~{estimated_tokens} tokens). "
                    "get_full_graph() calls may approach context limits."
                )

            try:
                staged = self._run_agent_loop(profile, groups, profiles_by_id, shared_graph)
                shared_graph.extend(staged)
                logger.info(f"Agent {uid} declared {len(staged)} relationship(s); graph total: {len(shared_graph)}")
            except Exception as e:
                failed += 1
                logger.warning(f"Agent {uid} loop failed: {e}")

        total = len(profiles_sorted)
        if total > 0 and failed / total > FAILURE_THRESHOLD:
            raise RuntimeError(
                f"RelationshipGenerator: {failed}/{total} agents failed "
                f"(>{FAILURE_THRESHOLD:.0%} threshold). Check LLM connectivity."
            )

        return shared_graph
```

- [ ] **Step 3: Add tests for the agentic loop**

Append to the test file:

```python
@patch("backend.app.services.relationship_generator.AzureOpenAI")
class TestAgenticLoop:
    """Tests for _run_agent_loop and _negotiate_all via generate()."""

    def _make_generator(self, mock_azure):
        """Return a RelationshipGenerator with a mocked LLM client."""
        gen = RelationshipGenerator()
        gen.client = mock_azure.return_value
        return gen

    # Natural finish (no tool calls) -------------------------------------

    def test_agent_with_no_tool_calls_adds_no_edges(self, mock_azure, tmp_path):
        mock_azure.return_value.chat.completions.create.return_value = _make_finish_response()
        gen = self._make_generator(mock_azure)
        result = gen.generate(str(tmp_path), PROFILES, GROUPS, force=True)
        assert result == []

    # Single declare_relationship ----------------------------------------

    def test_agent_declares_one_relationship(self, mock_azure, tmp_path):
        # Turn 1: declare_relationship; Turn 2: finish
        mock_azure.return_value.chat.completions.create.side_effect = [
            _make_tool_call_response("declare_relationship", {"tgt_id": 1, "type": "FOLLOWS", "label": "follows bob"}),
            _make_finish_response(),
            # remaining agents also immediately finish
            _make_finish_response(),
            _make_finish_response(),
        ]
        gen = self._make_generator(mock_azure)
        # Only run agent 0 by passing just 2 profiles
        result = gen.generate(str(tmp_path), PROFILES[:2], GROUPS, force=True)
        assert len(result) == 1
        assert result[0] == {"src_id": 0, "tgt_id": 1, "type": "FOLLOWS", "label": "follows bob"}

    # Staged edges not visible mid-loop via get_full_graph ---------------

    def test_agent_staged_edges_not_in_graph_during_loop(self, mock_azure, tmp_path):
        captured_graph_responses = []

        def side_effect(*args, **kwargs):
            messages = kwargs.get("messages", args[1] if len(args) > 1 else [])
            # Check if any tool result for get_full_graph is in the history
            for m in messages:
                if m.get("role") == "tool" and m.get("content", "").startswith("["):
                    captured_graph_responses.append(json.loads(m["content"]))
            # Turn 1 for agent 0: declare, then finish
            call_count = mock_azure.return_value.chat.completions.create.call_count
            if call_count == 1:
                return _make_tool_call_response("declare_relationship", {"tgt_id": 1, "type": "FOLLOWS", "label": "test"})
            if call_count == 2:
                return _make_finish_response()
            # Agent 1: get_full_graph, then finish
            if call_count == 3:
                return _make_tool_call_response("get_full_graph", {})
            return _make_finish_response()

        mock_azure.return_value.chat.completions.create.side_effect = side_effect
        gen = self._make_generator(mock_azure)
        gen.generate(str(tmp_path), PROFILES[:2], GROUPS, force=True)

        # Agent 1's get_full_graph should see agent 0's committed edge
        assert any(len(g) == 1 for g in captured_graph_responses), \
            "Agent 1 should see agent 0's committed edge via get_full_graph"

    # Max-turn guard flushes staged edges --------------------------------

    def test_max_turn_guard_flushes_staged_edges(self, mock_azure, tmp_path):
        # Agent 0 declares one relationship, then keeps calling tools until max turns
        responses = []
        # Turn 1: declare
        responses.append(_make_tool_call_response(
            "declare_relationship", {"tgt_id": 1, "type": "KNOWS", "label": "met at event"}
        ))
        # Turns 2–10: keep calling list_agents (never finishes naturally)
        for _ in range(9):
            responses.append(_make_tool_call_response("list_agents", {}))
        # Remaining agents finish immediately
        responses.extend([_make_finish_response()] * 10)

        mock_azure.return_value.chat.completions.create.side_effect = responses
        gen = self._make_generator(mock_azure)
        result = gen.generate(str(tmp_path), PROFILES[:2], GROUPS, force=True)

        # Edge should be flushed even though max turns was hit
        assert any(e["type"] == "KNOWS" for e in result)

    # Exception handling -------------------------------------------------

    def test_single_agent_failure_is_skipped(self, mock_azure, tmp_path):
        call_count = [0]

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("LLM timeout")
            return _make_finish_response()

        mock_azure.return_value.chat.completions.create.side_effect = side_effect
        gen = self._make_generator(mock_azure)
        # Should not raise; agent 0 fails, agent 1 succeeds
        result = gen.generate(str(tmp_path), PROFILES[:2], GROUPS, force=True)
        assert isinstance(result, list)

    def test_majority_failure_raises_runtime_error(self, mock_azure, tmp_path):
        mock_azure.return_value.chat.completions.create.side_effect = RuntimeError("LLM down")
        gen = self._make_generator(mock_azure)
        with pytest.raises(RuntimeError, match="threshold"):
            gen.generate(str(tmp_path), PROFILES, GROUPS, force=True)

    # Cache is written after successful run ------------------------------

    def test_edges_are_written_to_cache(self, mock_azure, tmp_path):
        mock_azure.return_value.chat.completions.create.side_effect = [
            _make_tool_call_response("declare_relationship", {"tgt_id": 1, "type": "FOLLOWS", "label": "test"}),
            _make_finish_response(),
            _make_finish_response(),
            _make_finish_response(),
        ]
        gen = self._make_generator(mock_azure)
        gen.generate(str(tmp_path), PROFILES[:2], GROUPS, force=True)

        cache_path = tmp_path / "relationships_ai.json"
        assert cache_path.exists()
        cached = json.loads(cache_path.read_text())
        assert len(cached) == 1
```

- [ ] **Step 4: Run all loop tests**

```bash
cd backend && python -m pytest tests/services/test_relationship_generator.py::TestAgenticLoop -v
```
Expected: all 7 tests PASS

- [ ] **Step 5: Run the full test suite**

```bash
cd backend && python -m pytest tests/services/test_relationship_generator.py -v
```
Expected: all tests PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/relationship_generator.py backend/tests/services/test_relationship_generator.py
git commit -m "feat: implement agentic loop and _negotiate_all for RelationshipGenerator"
```

---

## Task 6: Smoke test — verify the API endpoint still works

No code changes in this task. Verify the integration point.

- [ ] **Step 1: Confirm the import still resolves**

```bash
cd backend && python -c "
from app.services.relationship_generator import RelationshipGenerator
import inspect
sig = inspect.signature(RelationshipGenerator.generate)
print('Params:', list(sig.parameters.keys()))
"
```
Expected output:
```
Params: ['self', 'simulation_dir', 'profiles', 'groups', 'force']
```

- [ ] **Step 2: Confirm `api/simulation.py` imports cleanly**

```bash
cd backend && python -c "from app.api.simulation import simulation_bp; print('import ok')"
```
Expected: `import ok`

- [ ] **Step 3: Run all tests one final time**

```bash
cd backend && python -m pytest tests/services/test_relationship_generator.py -v --tb=short
```
Expected: all tests PASS, 0 errors

- [ ] **Step 4: Final commit**

```bash
git add backend/app/services/relationship_generator.py backend/tests/
git commit -m "feat: dynamic agent relationship negotiation complete"
```
