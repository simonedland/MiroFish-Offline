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

### Component: `AgentRelationshipNegotiator`

Replaces `RelationshipGenerator`. Located at `backend/app/services/relationship_generator.py` (same file, class renamed/replaced).

**Inputs:**
- `simulation_dir: str` — for cache read/write
- `profiles: List[Dict]` — agent profiles (same format as today)
- `groups: List[Dict]` — group definitions from `scenario_definition.json`
- `force: bool` — skip cache if True

**Output:** `List[Dict]` — edges `[{src_id, tgt_id, type, label}, ...]`
Saved to `relationships_ai.json` (same format, same path — downstream unchanged).

---

## Per-Agent Agentic Loop

For each agent (iterated in order of `user_id`):

1. Build a **system prompt** from the agent's own profile + group membership
2. Open an agentic loop with the Azure OpenAI chat API using `tools=` parameter
3. The LLM may call any combination of:

| Tool | Description |
|------|-------------|
| `list_agents()` | Returns all agents: `[{id, username, group, bio_snippet}]` |
| `get_agent_profile(agent_id: int)` | Returns full profile dict for any agent |
| `get_full_graph()` | Returns all edges declared so far: `[{src_id, tgt_id, type, label}]` |
| `declare_relationship(tgt_id: int, type: str, label: str)` | Commits one outgoing edge from this agent |

4. Loop terminates when:
   - The LLM produces a non-tool-call message (natural finish), OR
   - A **max-turn guard** of 10 LLM turns is hit (prevents runaway loops)
5. All `declare_relationship` calls made during the loop are collected and appended to the shared graph immediately

**System prompt template:**
```
You are {username}, a social media user. Your profile:
{full_profile}

Your group: {group_name} — {group_description}

You are setting up your social connections before joining a simulation.
Use the available tools to explore who else is participating and what
relationships already exist. Then declare the relationships that feel
authentic to your character. You may declare as few or as many as you
feel is right.
```

---

## Shared Graph State

A single `list[dict]` accumulates edges across all agents. After each agent finishes its loop, their declared edges are appended. This means agent #50 calling `get_full_graph()` sees all edges declared by agents #0–#49.

Validation on `declare_relationship`:
- `tgt_id` must exist in the profiles list
- `src_id != tgt_id`
- `type` must be one of: `KNOWS, FOLLOWS, COORDINATES, REPLIES_TO, INFLUENCES, TARGETS, DISPUTES, AGREES_WITH, RIVALS`
- Duplicate `(src_id, tgt_id)` pairs are silently dropped

---

## Tool Call Execution

Tools are implemented as pure Python functions operating on in-memory state. The agentic loop dispatches tool calls by name, serializes results as JSON strings, and appends them to the message history as `role: tool` messages per the OpenAI function-calling protocol.

---

## Error Handling

- If an agent's loop fails entirely (LLM error, timeout), it is skipped with a warning — the simulation proceeds without that agent's relationships
- Invalid `declare_relationship` arguments are returned as an error string in the tool result; the LLM may retry with corrected args
- On exhausting max turns, any relationships declared so far in that agent's loop are kept

---

## Caching

Same as current: if `relationships_ai.json` exists and `force=False`, load and return it. Only regenerate when explicitly forced or the file is absent.

---

## Integration Points

- `backend/app/api/simulation.py`: The `generate_relationships` endpoint already calls `RelationshipGenerator().generate(...)` — the class/method signature is preserved, so this endpoint needs no changes
- `relationships_ai.json` format is unchanged — the frontend graph panel and any downstream consumers are unaffected

---

## Performance Considerations

- For 120 agents × up to 10 turns × 1 LLM call/turn = up to 1,200 LLM calls in the worst case
- In practice, most agents will finish in 2–4 turns (one `list_agents` or `get_full_graph`, one or more `declare_relationship`, then stop)
- Progress is logged per-agent so the operator can see it advancing
- A future optimization (out of scope) could parallelize agents within the same group once intra-group edges are no longer order-dependent

---

## Files Changed

| File | Change |
|------|--------|
| `backend/app/services/relationship_generator.py` | Full rewrite: `RelationshipGenerator` → `AgentRelationshipNegotiator`, same public interface |

No other files change.
