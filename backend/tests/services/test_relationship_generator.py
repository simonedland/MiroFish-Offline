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
