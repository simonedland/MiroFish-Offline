"""
Tests for the agentic RelationshipGenerator.
All LLM calls are mocked — no real Azure OpenAI calls are made.
"""
import json
import os
import pytest
from unittest.mock import MagicMock, patch, call

from app.services.relationship_generator import RelationshipGenerator, VALID_TYPES


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


@patch("app.services.relationship_generator.AzureOpenAI")
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
        assert staged == []

    def test_declare_relationship_invalid_type(self):
        staged = []
        out = RelationshipGenerator._tool_declare_relationship(
            0, 1, "HATES", "test", self.profiles_by_id, staged
        )
        assert "error" in out
        assert staged == []

    def test_declare_relationship_empty_label(self):
        staged = []
        out = RelationshipGenerator._tool_declare_relationship(
            0, 1, "FOLLOWS", "", self.profiles_by_id, staged
        )
        assert "error" in out

    def test_declare_relationship_label_truncated_to_120(self):
        staged = []
        out = RelationshipGenerator._tool_declare_relationship(
            0, 1, "FOLLOWS", "x" * 200, self.profiles_by_id, staged
        )
        assert out == "ok"
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


@patch("app.services.relationship_generator.AzureOpenAI")
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
            # agent 1 finishes immediately
            _make_finish_response(),
        ]
        gen = self._make_generator(mock_azure)
        # Only run agent 0 by passing just 2 profiles
        result = gen.generate(str(tmp_path), PROFILES[:2], GROUPS, force=True)
        assert len(result) == 1
        assert result[0] == {"src_id": 0, "tgt_id": 1, "type": "FOLLOWS", "label": "follows bob"}

    # Staged edges not visible mid-loop via get_full_graph ---------------

    def test_agent_staged_edges_not_in_graph_during_loop(self, mock_azure, tmp_path):
        """
        Invariant 1: An agent cannot see its own staged edges via get_full_graph mid-loop.
        Invariant 2: A later agent CAN see edges committed by previous agents.
        """
        call_count = [0]
        graph_snapshots = []  # captures what get_full_graph returned at each call

        def side_effect(*args, **kwargs):
            call_count[0] += 1
            n = call_count[0]
            # Agent 0, turn 1: get_full_graph (should see empty graph — no prior agents)
            if n == 1:
                return _make_tool_call_response("get_full_graph", {}, call_id="call_g0_t1")
            # Agent 0, turn 2: declare a relationship, then finish
            if n == 2:
                return _make_tool_call_response(
                    "declare_relationship",
                    {"tgt_id": 1, "type": "FOLLOWS", "label": "test"},
                    call_id="call_g0_t2",
                )
            if n == 3:
                # Agent 0, turn 3: get_full_graph again BEFORE finishing
                # Should still see empty graph — own staged edge not committed yet
                return _make_tool_call_response("get_full_graph", {}, call_id="call_g0_t3")
            if n == 4:
                # Agent 0 finishes
                return _make_finish_response()
            # Agent 1, turn 1: get_full_graph (should see agent 0's committed edge)
            if n == 5:
                return _make_tool_call_response("get_full_graph", {}, call_id="call_g1_t1")
            # Agent 1 finishes
            return _make_finish_response()

        # Capture graph snapshots by intercepting only the NEWEST tool message on each call.
        # Each LLM call appends exactly one new tool message to history (the result from the
        # previous turn's tool call). We track seen tool_call_ids to avoid re-counting older
        # messages that are replayed in full each time.
        seen_tool_call_ids: set = set()
        original_side_effect = side_effect

        def capturing_side_effect(*args, **kwargs):
            messages = kwargs.get("messages", [])
            for m in messages:
                if m.get("role") == "tool" and m.get("content", "").startswith("["):
                    tcid = m.get("tool_call_id", "")
                    if tcid not in seen_tool_call_ids:
                        seen_tool_call_ids.add(tcid)
                        graph_snapshots.append(json.loads(m["content"]))
            return original_side_effect(*args, **kwargs)

        mock_azure.return_value.chat.completions.create.side_effect = capturing_side_effect
        gen = self._make_generator(mock_azure)
        gen.generate(str(tmp_path), PROFILES[:2], GROUPS, force=True)

        # Snapshots arrive in declaration order:
        # snapshot[0] = agent 0's first get_full_graph  → must be empty (no prior agents)
        # snapshot[1] = agent 0's second get_full_graph → must be empty (staged, not committed)
        # snapshot[2] = agent 1's get_full_graph        → must have 1 edge (agent 0's committed edge)
        assert len(graph_snapshots) >= 3, \
            f"Expected 3 graph snapshots, got {len(graph_snapshots)}: {graph_snapshots}"

        assert graph_snapshots[0] == [], \
            f"Agent 0's first get_full_graph should be empty (no prior agents), got {graph_snapshots[0]}"

        assert graph_snapshots[1] == [], \
            f"Agent 0's second get_full_graph should be empty (staged edge not committed), got {graph_snapshots[1]}"

        assert len(graph_snapshots[2]) == 1, \
            f"Agent 1 should see agent 0's committed edge, got {graph_snapshots[2]}"

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
