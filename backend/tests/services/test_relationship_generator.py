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
