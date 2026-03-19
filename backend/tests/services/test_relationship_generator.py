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
