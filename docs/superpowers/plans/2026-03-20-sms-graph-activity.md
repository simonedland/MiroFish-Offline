# SMS Live Activity on Graph — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** When an SMS message is sent between two agents during a simulation, animate a teal dot traveling along the graph edge from sender to receiver in real time.

**Architecture:** Poll `GET /api/simulation/sms/events?simulation_id=<id>&since=<timestamp>` every 4 seconds during simulation; map sender/receiver display names to graph node UUIDs; feed events into the existing `latestActions` → `GraphPanel` animation pipeline. SMS dots use teal `#4ecdc4`; Reddit action dots remain orange `#ff9f4a`.

**Tech Stack:** Vue 3 (Composition API), D3.js, existing `/frontend/src/api/sms.js` (`getSmsEvents`)

---

## File Map

| File | Change |
|---|---|
| `frontend/src/components/GraphPanel.vue` | Add `color` param to `animateDot`; dispatch color by action type in watcher |
| `frontend/src/views/SimulationRunView.vue` | Add `smsDisplayNameMap`, SMS poll timer, fix Reddit poll to spread instead of replace |

No new files needed. No backend changes needed.

---

### Task 1: Add color parameter to `animateDot` in GraphPanel

**Files:**
- Modify: `frontend/src/components/GraphPanel.vue` (function `animateDot` ~line 960, watcher `watch(() => props.recentActions)` ~line 1015)

- [ ] **Step 1: Open `GraphPanel.vue` and find `animateDot`**

  Locate the function signature at ~line 960:
  ```js
  function animateDot(srcId, tgtId) {
  ```

- [ ] **Step 2: Add `color` parameter with default**

  Change the signature to:
  ```js
  function animateDot(srcId, tgtId, color = '#ff9f4a') {
  ```

- [ ] **Step 3: Replace the two hardcoded color strings inside `animateDot`**

  Find and replace (both are inside `animateDot`, nowhere else in the function):

  1. The temporary arc stroke (~line 982):
     ```js
     // Before:
     .attr('stroke', '#ff9f4a')
     // After:
     .attr('stroke', color)
     ```

  2. The traveling dot fill (~line 998):
     ```js
     // Before:
     .attr('fill', '#ff9f4a')
     // After:
     .attr('fill', color)
     ```

- [ ] **Step 4: Update the `recentActions` watcher to dispatch color by type**

  Locate the watcher at ~line 1015:
  ```js
  watch(() => props.recentActions, (actions) => {
    if (!actions?.length) return
    actions.forEach(a => {
      if (a.srcId) pulseNode(a.srcId)
      if (a.srcId && a.tgtId) {
        animateDot(a.srcId, a.tgtId)
        pulseNodeSoft(a.tgtId)
      }
    })
  }, { deep: true })
  ```

  Replace with:
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

- [ ] **Step 5: Verify visually that existing Reddit animations still work**

  - Start the dev server (or check the running container)
  - Confirm the orange dot animation still fires for Reddit-style actions
  - No automated test for D3 animations — visual check is sufficient

- [ ] **Step 6: Commit**

  ```bash
  git add frontend/src/components/GraphPanel.vue
  git commit -m "feat: add color param to animateDot, dispatch teal for SMS actions"
  ```

---

### Task 2: Wire SMS event polling into SimulationRunView

**Files:**
- Modify: `frontend/src/views/SimulationRunView.vue`

- [ ] **Step 1: Add `getSmsEvents` to the sms import**

  Find the existing sms import (search for `from '../api/sms'` — it may not exist yet). If absent, add at the top of `<script setup>` alongside other imports:
  ```js
  import { getSmsEvents } from '../api/sms'
  ```

  If the file already imports from `'../api/sms'`, add `getSmsEvents` to the existing import.

- [ ] **Step 2: Add `smsDisplayNameMap` ref**

  Find the block of `ref()` declarations near the top of `<script setup>` (alongside `agentNameMap`, `latestActions`, etc.). Add:
  ```js
  const smsDisplayNameMap = ref({})
  ```

- [ ] **Step 3: Add SMS poll variables**

  Find where `let seenActionCount = 0` and `let actionPollTimer = null` are declared. Add alongside them:
  ```js
  let smsPollTimer = null
  let lastSmsTimestamp = 0
  ```

- [ ] **Step 4: Populate `smsDisplayNameMap` inside `buildAgentGraph`**

  Inside `buildAgentGraph`, after the `profiles` array is available (after the `Promise.allSettled` block resolves and profiles are extracted), add this block before the `nodes` array is built:
  ```js
  // Build display-name → user_id map for SMS event resolution
  smsDisplayNameMap.value = {}
  profiles.forEach(p => {
    const n = (p.name || '').toLowerCase()
    if (n) smsDisplayNameMap.value[n] = p.user_id
  })
  ```

- [ ] **Step 5: Add `startSmsPoll` and `stopSmsPoll` functions**

  Add these two functions directly after `stopActionPoll`:
  ```js
  const startSmsPoll = () => {
    if (smsPollTimer) return
    // Guard: only start if name map is populated (avoids empty-map polling
    // when isSimulating fires before buildAgentGraph completes)
    if (Object.keys(smsDisplayNameMap.value).length === 0) return

    smsPollTimer = setInterval(async () => {
      try {
        const res = await getSmsEvents(currentSimulationId.value, lastSmsTimestamp)
        const events = res.data?.data || []
        if (!events.length) return

        const newActions = []
        events.forEach(ev => {
          // Advance cursor before name-resolution guard — prevents re-fetching
          // events whose names can't be resolved
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
          latestActions.value = [...latestActions.value, ...newActions]
        }
      } catch (_) {}
    }, 4000)
  }

  const stopSmsPoll = () => {
    if (smsPollTimer) { clearInterval(smsPollTimer); smsPollTimer = null }
  }
  ```

- [ ] **Step 6: Call `startSmsPoll` at the end of `buildAgentGraph`**

  At the very end of `buildAgentGraph` (inside the `try` block, after `agentNameMap.value = agentByName`), add:
  ```js
  // Start SMS poll now if simulation is already running
  // (handles the race where isSimulating fired before buildAgentGraph completed)
  if (isSimulating.value && !smsPollTimer) {
    startSmsPoll()
  }
  ```

- [ ] **Step 7: Add SMS poll to `isSimulating` watcher**

  Find the existing `watch(isSimulating, ...)` block:
  ```js
  watch(isSimulating, (newValue) => {
    if (newValue) {
      if (isDescriptionFlow.value) {
        startActionPoll()
      }
    } else {
      stopActionPoll()
    }
  }, { immediate: true })
  ```

  Update it to:
  ```js
  watch(isSimulating, (newValue) => {
    if (newValue) {
      if (isDescriptionFlow.value) {
        startActionPoll()
        startSmsPoll()
      }
    } else {
      stopActionPoll()
      stopSmsPoll()
    }
  }, { immediate: true })
  ```

- [ ] **Step 8: Add `stopSmsPoll` to `onUnmounted`**

  Find `onUnmounted`:
  ```js
  onUnmounted(() => {
    stopActionPoll()
  })
  ```

  Update to:
  ```js
  onUnmounted(() => {
    stopActionPoll()
    stopSmsPoll()
  })
  ```

- [ ] **Step 9: Reset `lastSmsTimestamp` in `loadSimulationData`**

  At the top of `loadSimulationData` (before any `await` calls), add:
  ```js
  lastSmsTimestamp = 0
  ```

- [ ] **Step 10: Fix Reddit action poll to spread instead of replace**

  Find `processNewActions` (~line 422). It currently ends with:
  ```js
  latestActions.value = fresh.map(a => {
    ...
  }).filter(a => a.srcId)
  ```

  Change the assignment to spread so it doesn't overwrite any SMS events appended in the same tick:
  ```js
  latestActions.value = [
    ...latestActions.value,
    ...fresh.map(a => {
      ...
    }).filter(a => a.srcId)
  ]
  ```

  Only the assignment line changes — the `fresh.map(...)` body stays identical.

- [ ] **Step 11: Commit**

  ```bash
  git add frontend/src/views/SimulationRunView.vue
  git commit -m "feat: poll SMS events and animate teal dots on graph edges"
  ```

---

### Task 3: Rebuild container and verify end-to-end

- [ ] **Step 1: Rebuild the Docker container**

  From the project root:
  ```bash
  docker compose build frontend
  docker compose up -d
  ```
  (Or whatever the project's rebuild command is — check `Dockerfile` and `docker-compose.yml`.)

- [ ] **Step 2: Start a simulation and switch to Graph view**

  - Open the app, start or resume a simulation that uses SMS (description-flow / scenario_flow)
  - Switch to the **Graph** view

- [ ] **Step 3: Confirm teal dots appear on SMS send**

  - Watch the graph during an active simulation round
  - When agents exchange SMS messages, a teal dot should travel along the edge between the two agent nodes
  - Source node should pulse larger on send; target node should pulse softly on receive
  - If no static edge exists between the pair, a temporary arc appears and fades after the dot completes

- [ ] **Step 4: Confirm orange dots still appear for Reddit actions**

  - If the simulation also produces Reddit-style actions, confirm those dots are still orange (not teal)

- [ ] **Step 5: Confirm no console errors**

  - Open browser dev tools → Console
  - No JS errors during animation

