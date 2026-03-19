# Dynamic Agent Relationship Negotiation — Design Spec

**Date:** 2026-03-19
**Status:** Approved

---

## Problem

The current `RelationshipGenerator` makes a single batch LLM call with all agent profiles at once and statically assigns relationships top-down. Agents have no agency in this process — they don't choose who they know or follow based on reasoning about the social landscape.

---

## Goal

Replace the static batch approach with an **agentic, sequential negotiation phase** that runs during simulation setup. Each agent uses AI with tool calls to actively browse the agent roster and the growing social graph, then declares its own relationships. Each subsequent agent sees the full graph so far, enabling emergent social dynamics.

---

## Architecture

### Component: `RelationshipGenerator` (class name preserved)

The class is rewritten in place at `backend/app/services/relationship_generator.py`. The public interface is identical to today:

```python
RelationshipGenerator().generate(simulation_dir, profiles, groups, force=False) -> List[Dict]
```

The `api/simulation.py` import (`from ..services.relationship_generator import RelationshipGenerator`) and the call site require no changes.

**Inputs:**
- `simulation_dir: str` — for cache read/write
- `profiles: List[Dict]` — agent profiles (same format as today)
- `groups: List[Dict]` — group definitions from `scenario_definition.json`
- `force: bool` — skip cache if True

**Output:** `List[Dict]` — edges `[{src_id, tgt_id, type, label}, ...]`
Saved to `relationships_ai.json` (same format, same path — downstream unchanged).

---

## Degenerate Input Handling

Before entering the per-agent loop:

- If `profiles` is empty → log a warning, return `[]` immediately
- If `profiles` has exactly one agent → log a warning, return `[]` immediately (no valid target exists)

---

## Per-Agent Agentic Loop

For each agent (iterated in ascending order of `user_id`):

1. Resolve the agent's group: look up `group_id` from the profile in the `groups` list by matching `group["name"] == profile["group_id"]`. If no match, fall back to `group_name = profile["group_id"]` and `group_description = ""`.
2. Build a **system prompt** from the agent's own full profile + resolved group metadata
3. Open an agentic loop with the Azure OpenAI chat API (tools API / function-calling)
4. The LLM may call any combination of tools (see below)
5. Loop terminates when the LLM produces a response with no tool calls (natural finish) or the **max-turn guard** of 10 is reached. One "turn" = one call to `client.chat.completions.create`.
6. At the end of the loop, all `declare_relationship` calls made during that agent's loop are validated and appended to the **shared graph** in one batch. Mid-loop, `get_full_graph()` returns only edges from **previous agents** — the current agent's in-progress declarations are staged separately and not visible until the loop ends.

If an agent's loop raises an exception (LLM error, timeout), it is skipped with a warning log and the simulation proceeds. If more than 50% of agents fail, `generate()` raises `RuntimeError` to surface the failure clearly.

---

## Tools

| Tool | Signature | Returns |
|------|-----------|---------|
| `list_agents` | `()` | `[{id, username, group, bio_snippet}]` sorted ascending by `user_id` — bio_snippet is `bio[:80]` |
| `get_agent_profile` | `(agent_id: int)` | Full profile dict for that agent |
| `get_full_graph` | `()` | All edges committed by previous agents: `[{src_id, tgt_id, type, label}]` |
| `declare_relationship` | `(tgt_id: int, type: str, label: str)` | `"ok"` on success, error string on validation failure |

### Tool: `declare_relationship` — validation

- `tgt_id` must exist in the profiles list → error if not
- `src_id != tgt_id` → error if same
- `type` must be one of: `KNOWS, FOLLOWS, COORDINATES, REPLIES_TO, INFLUENCES, TARGETS, DISPUTES, AGREES_WITH, RIVALS` → error if invalid
- `label`: required, non-empty string. If `label` is absent or empty, the tool returns an error string prompting the LLM to retry with a valid label. If `label` is non-empty but exceeds 120 characters, it is silently truncated to 120 characters before storing.
- Duplicate `(src_id, tgt_id)` pair within this agent's staged edges → silently deduplicated (not an error). Since `src_id` is always the current agent's own `user_id`, a cross-agent duplicate `(src_id, tgt_id)` is structurally impossible — no cross-agent deduplication logic is needed.

---

## System Prompt Template

```
You are {username}, a social media user.

Your profile:
{full_profile_json}

Your group: {group_name} — {group_description}

You are setting up your social connections before joining a simulation.
Use the available tools to explore who else is participating and what
relationships already exist. Then declare the relationships that feel
authentic to your character.

Guidance: 2–8 relationships is typical for most personas. You may declare
fewer if you are a loner, or more if you are highly social — but let your
character guide you, not a desire to maximise connections.

When you are done declaring relationships, stop calling tools and reply
with a brief closing statement.
```

---

## Shared Graph State

A single `list[dict]` accumulates committed edges across all agents. Each agent's loop stages its `declare_relationship` calls in a **per-agent buffer**. After the loop ends (naturally or via max-turn guard), the buffer is validated and flushed to the shared list. This means:

- `get_full_graph()` called by agent N returns only edges from agents 0…N-1
- Agent N cannot see its own in-progress declarations via `get_full_graph()`
- Any relationships the agent declared before a loop failure (LLM exception or network timeout) are **discarded** for that agent (the buffer is not flushed on error). Hitting the max-turn guard is a clean exit — the buffer **is** flushed.

---

## Tool Call Execution

Tools are pure Python functions operating on in-memory state. The loop:
1. Sends the accumulated message history to `client.chat.completions.create`
2. If the response contains tool calls, dispatches each by name, serializes the result as a JSON string, and appends `role: tool` messages to the history
3. Repeats from step 1 until no tool calls in the response or max turns hit
4. The Azure OpenAI client is initialized with `timeout=90` (same as the existing implementation)

---

## Token Budget Awareness

The message history grows with each turn: `list_agents` responses are O(n_agents) tokens, and `get_full_graph` grows linearly with the number of committed edges. For 120 agents × ~3 edges each = ~360 edges by the time the last agent runs. At ~20 tokens/edge the full graph is ~7,200 tokens — well within a 128k context window but worth logging a warning if the estimated prompt size exceeds 50k tokens.

---

## Error Handling Summary

| Scenario | Behaviour |
|----------|-----------|
| Empty or single-agent profiles | Return `[]` immediately with a warning log |
| Agent loop LLM exception | Skip agent, log warning, continue |
| >50% of agents fail | Raise `RuntimeError` after all agents attempted |
| Invalid `declare_relationship` args | Return error string to LLM; LLM may retry |
| Max turns (10) reached | Flush valid staged edges, continue to next agent |
| `relationships_ai.json` write fails | Log warning, return edges in memory (don't crash) |

---

## Caching

Same as current: if `relationships_ai.json` exists and `force=False`, load and return it. Only regenerate when explicitly forced or the file is absent.

---

## Integration Points

| File | Change |
|------|--------|
| `backend/app/services/relationship_generator.py` | Full rewrite of class internals; class name `RelationshipGenerator` and method signature `generate(...)` preserved |
| `backend/app/api/simulation.py` | No changes required |
| `relationships_ai.json` | Format unchanged |

No other files change.
