# SMS Live Activity on Graph — Design Spec

**Date:** 2026-03-20
**Status:** In Review (revision 3)

---

## Goal

When an SMS message is sent between two agents during a simulation, animate the corresponding connection in the Graph Relationship Visualization in real time. The animation style is a dot traveling from sender to receiver along the edge, with node pulses on send and receive. SMS dots use teal (`#4ecdc4`) to distinguish them from existing orange Reddit-action dots. Node pulse rings are not color-coded (remain the default behavior).

---

## Architecture

### Data Flow

```
sms_events.jsonl (backend, written by SmsSimulationRunner)
  → GET /api/simulation/sms/events?simulation_id=<id>&since=<timestamp>
  → SimulationRunView: smsPollTimer (every 4s, same as actionPollTimer)
  → map sender_name / receiver_name → node UUIDs via smsDisplayNameMap
  → merged into latestActions[] alongside existing Reddit action events
  → GraphPanel :recentActions prop
  → watch(recentActions) → animateDot(srcId, tgtId, color) + pulseNode(srcId) + pulseNodeSoft(tgtId)
  → D3 animated teal dot travels along edge path
```

---

## Changes

### `frontend/src/views/SimulationRunView.vue`

**1. `smsDisplayNameMap` ref**

A new `ref({})` built inside `buildAgentGraph` alongside the existing `agentNameMap`. Maps `profile.name.toLowerCase()` → `profile.user_id`. Needed because SMS messages carry the agent's display name (from `OasisAgentProfile.name`), not their username.

**Assumption:** `OasisAgentProfile.name` is always populated for SMS-flow agents. (The SMS runner uses `sender.name` directly when emitting events, so if `name` were missing the SMS message itself would be malformed upstream. Agents with a missing `name` will simply produce no animation — same "silently skipped" behavior as unresolvable events.)

```js
const smsDisplayNameMap = ref({})
// built inside buildAgentGraph (after profiles are fetched):
profiles.forEach(p => {
  const n = (p.name || '').toLowerCase()
  if (n) smsDisplayNameMap.value[n] = p.user_id
})
```

The map is rebuilt from scratch each time `buildAgentGraph` runs (e.g., on Refresh). The SMS poll does not need to restart on rebuild — any events arriving during a brief rebuild window will use the stale map, at worst skipping one poll tick's worth of animations. This is acceptable.

**2. SMS event poll**

New variables alongside `actionPollTimer`:

```js
let smsPollTimer = null
let lastSmsTimestamp = 0
```

`lastSmsTimestamp` is module-level (`let`, not `ref`). It is reset to `0` at the top of `loadSimulationData()`, which is called on `onMounted` — so SPA re-navigation will reset it correctly as long as `loadSimulationData` is always called on mount (it is, unconditionally).

```js
const startSmsPoll = () => {
  if (smsPollTimer) return
  // Guard: only start if the name map is populated (avoids polling with empty map
  // when isSimulating fires before buildAgentGraph completes)
  if (Object.keys(smsDisplayNameMap.value).length === 0) return

  smsPollTimer = setInterval(async () => {
    try {
      const res = await getSmsEvents(currentSimulationId.value, lastSmsTimestamp)
      const events = res.data?.data || []
      if (!events.length) return

      const newActions = []
      events.forEach(ev => {
        // Always advance the timestamp cursor, even for events we can't resolve —
        // this prevents infinite re-fetching of unresolvable events
        if (ev.timestamp > lastSmsTimestamp) lastSmsTimestamp = ev.timestamp

        if (ev.type !== 'sms_message') return
        const d = ev.data || {}
        const srcUserId = smsDisplayNameMap.value[(d.sender_name || '').toLowerCase()]
        const tgtUserId = smsDisplayNameMap.value[(d.receiver_name || '').toLowerCase()]
        if (srcUserId == null || tgtUserId == null) return

        newActions.push({
          srcId: `agent_${srcUserId}`,
          tgtId: `agent_${tgtUserId}`,
          type: 'SMS',
        })
      })

      if (newActions.length) {
        // Merge with any pending Reddit actions rather than overwriting them
        latestActions.value = [...latestActions.value, ...newActions]
      }
    } catch (_) {}
  }, 4000)
}

const stopSmsPoll = () => {
  if (smsPollTimer) { clearInterval(smsPollTimer); smsPollTimer = null }
}
```

**Polling interval:** Both `actionPollTimer` and `smsPollTimer` use 4 s. They are independent timers started at different times, so their ticks will naturally drift apart.

**Shared `latestActions` and collision safety:** Vue 3's `watch` is flushed asynchronously (post-flush via microtask queue). If both timers fire before the flush drains, the watcher only sees the final value of `latestActions` — whichever poll wrote last. To prevent either poll from silently eating the other's events, **`processNewActions` (the Reddit action handler) must also be updated to spread rather than replace**:

```js
// Before (replaces all):
latestActions.value = fresh.map(...)

// After (appends, same as SMS poll):
latestActions.value = [...latestActions.value, ...fresh.map(...)]
```

With both polls spreading, the watcher sees a combined array regardless of fire order. The watcher processes all entries and triggers animations for each — the array is then implicitly "consumed" by the next poll cycle overwriting it with fresh data.

**3. `isSimulating` watcher — start/stop hooks**

The existing watcher already calls `startActionPoll` / `stopActionPoll`. Add SMS poll calls:

```js
watch(isSimulating, (newValue) => {
  if (newValue) {
    if (isDescriptionFlow.value) {
      startActionPoll()
      startSmsPoll()   // ← added
    }
  } else {
    stopActionPoll()
    stopSmsPoll()      // ← added
  }
}, { immediate: true })
```

**Note on race condition:** `startSmsPoll` guards against an empty `smsDisplayNameMap`. If `isSimulating` fires `true` before `buildAgentGraph` finishes (e.g., page reload with status already `processing`), `startSmsPoll` returns early without starting the timer. To handle this, `startSmsPoll` is also called at the end of `buildAgentGraph` if `isSimulating.value` is already `true`:

```js
// At the end of buildAgentGraph(), after smsDisplayNameMap is populated:
if (isSimulating.value && !smsPollTimer) {
  startSmsPoll()
}
```

**4. `onUnmounted`**

```js
onUnmounted(() => {
  stopActionPoll()
  stopSmsPoll()   // ← added
})
```

**5. Import**

Add `getSmsEvents` to the existing `sms.js` import (it already exists in the API file).

**6. Reset on load**

At the top of `loadSimulationData()`, reset the timestamp cursor:

```js
lastSmsTimestamp = 0
```

---

### `frontend/src/components/GraphPanel.vue`

**1. Color parameter in `animateDot`**

Add a `color` parameter (default `'#ff9f4a'` — preserves existing orange for Reddit actions). Two specific occurrences of the hardcoded color need updating:

- Line ~982: the temporary arc's `.attr('stroke', '#ff9f4a')` → `.attr('stroke', color)`
- Line ~998: the dot's `.attr('fill', '#ff9f4a')` → `.attr('fill', color)`

Updated signature:

```js
function animateDot(srcId, tgtId, color = '#ff9f4a') { ... }
```

**2. Color dispatch in `recentActions` watcher**

```js
watch(() => props.recentActions, (actions) => {
  if (!actions?.length) return
  actions.forEach(a => {
    const color = a.type === 'SMS' ? '#4ecdc4' : '#ff9f4a'
    if (a.srcId) pulseNode(a.srcId)
    if (a.srcId && a.tgtId) {
      animateDot(a.srcId, a.tgtId, color)
      pulseNodeSoft(a.tgtId)
    }
  })
}, { deep: true })
```

Node pulse rings (`pulseNode`, `pulseNodeSoft`) are intentionally not color-coded — they use the node's existing D3 radius animation and are type-agnostic.

---

## Edge Cases

| Scenario | Handling |
|---|---|
| Sender/receiver name not in `smsDisplayNameMap` | Timestamp cursor still advances (no re-fetch loop); animation silently skipped |
| No static graph edge between the pair | `animateDot` draws a temporary curved arc and removes it after the dot completes |
| `isSimulating` fires before `buildAgentGraph` completes | `startSmsPoll` guard returns early; poll starts at end of `buildAgentGraph` instead |
| Reddit action poll and SMS poll emit in same tick | Both spread into `latestActions` — no overwrite |
| `buildAgentGraph` called again (Refresh) | Map rebuilt; poll continues with momentary stale map (at most one missed tick) |
| SPA re-navigation (unmount + re-mount) | `lastSmsTimestamp` reset in `loadSimulationData` on re-mount |

---

## Out of Scope

- Showing SMS message content in the graph (tooltip, etc.)
- Persisting animation history
- Animating SMS events that occurred before the page loaded
- Color-coding node pulse rings by event type
