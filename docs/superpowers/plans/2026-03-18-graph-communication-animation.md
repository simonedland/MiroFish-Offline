# Graph Communication Animation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Animate every agent-to-agent communication on the graph — traveling dot + temporary arc for node pairs without a static edge, plus a soft pulse on the target node.

**Architecture:** All changes are confined to `GraphPanel.vue`. Extend `animateDot` to draw a temporary quadratic-bezier arc when no static edge exists between src/tgt, animate a dot along it, then fade/remove both. Add `pulseNodeSoft` for target node acknowledgment. No backend changes, no new files.

**Tech Stack:** Vue 3, D3 v7 (already in use)

---

## Files

- Modify: `frontend/src/components/GraphPanel.vue` — `pulseNode`, `animateDot`, `recentActions` watcher (lines ~944–976)

---

### Task 1: Add `pulseNodeSoft` for target node acknowledgment

**Files:**
- Modify: `frontend/src/components/GraphPanel.vue` (after line 950, the `pulseNode` function)

- [ ] **Step 1: Locate `pulseNode` at line 944 and insert `pulseNodeSoft` directly after it**

```javascript
function pulseNodeSoft(uuid) {
  const el = nodeByUuid[uuid]
  if (!el) return
  d3.select(el)
    .transition().duration(200).attr('r', 15)
    .transition().duration(400).ease(d3.easeElasticOut).attr('r', 10)
}
```

- [ ] **Step 2: Run the dev server and verify no console errors**

```bash
cd frontend && npm run dev
```

Expected: No errors, graph still renders normally.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/GraphPanel.vue
git commit -m "feat: add soft target-node pulse for communication feedback"
```

---

### Task 2: Extend `animateDot` to handle missing edges via temporary arc

**Files:**
- Modify: `frontend/src/components/GraphPanel.vue` — replace `animateDot` (lines 952–968)

- [ ] **Step 1: Replace the existing `animateDot` function with the version below**

The new version:
1. Falls through to a temporary arc if no static edge is found
2. Computes a quadratic bezier control point offset perpendicular to the midpoint
3. Appends a temporary `<path>` that fades out after the dot finishes

```javascript
function animateDot(srcId, tgtId) {
  if (!svgG) return
  const pathEl = edgeByPair[`${srcId}_${tgtId}`] || edgeByPair[`${tgtId}_${srcId}`]
  let pathNode = pathEl
  let tempPath = null

  if (!pathEl) {
    // No static edge — draw a temporary arc between the two node positions
    const srcEl = nodeByUuid[srcId]
    const tgtEl = nodeByUuid[tgtId]
    if (!srcEl || !tgtEl) return
    const srcD = d3.select(srcEl).datum()
    const tgtD = d3.select(tgtEl).datum()
    if (!srcD || !tgtD) return
    const sx = srcD.x, sy = srcD.y, tx = tgtD.x, ty = tgtD.y
    const dx = tx - sx, dy = ty - sy
    const len = Math.sqrt(dx * dx + dy * dy) || 1
    const offset = Math.min(len * 0.3, 60)
    const cx = (sx + tx) / 2 - (dy / len) * offset
    const cy = (sy + ty) / 2 + (dx / len) * offset
    tempPath = d3.select(svgG).append('path')
      .attr('d', `M${sx},${sy} Q${cx},${cy} ${tx},${ty}`)
      .attr('stroke', '#e8642a')
      .attr('stroke-width', 1.5)
      .attr('fill', 'none')
      .attr('opacity', 0.35)
      .attr('pointer-events', 'none')
    pathNode = tempPath.node()
  }

  const total = pathNode.getTotalLength()
  if (!total) {
    if (tempPath) tempPath.remove()
    return
  }

  const dot = d3.select(svgG).append('circle')
    .attr('r', 5)
    .attr('fill', '#e8642a')
    .attr('pointer-events', 'none')
    .attr('opacity', 0.85)

  dot.transition()
    .duration(700)
    .ease(d3.easeLinear)
    .attrTween('cx', () => t => pathNode.getPointAtLength(t * total).x)
    .attrTween('cy', () => t => pathNode.getPointAtLength(t * total).y)
    .on('end', () => {
      dot.remove()
      if (tempPath) {
        tempPath.transition().duration(300).attr('opacity', 0).on('end', () => tempPath.remove())
      }
    })
}
```

- [ ] **Step 2: Verify dev server still runs without errors**

```bash
cd frontend && npm run dev
```

Expected: No console errors. Graph renders normally.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/GraphPanel.vue
git commit -m "feat: animate communication arc for node pairs without static edges"
```

---

### Task 3: Add target node soft-pulse to the recentActions watcher

**Files:**
- Modify: `frontend/src/components/GraphPanel.vue` — `recentActions` watcher (lines ~970–976)

- [ ] **Step 1: Update the watcher to also call `pulseNodeSoft` on the target node**

Replace:
```javascript
watch(() => props.recentActions, (actions) => {
  if (!actions?.length) return
  actions.forEach(a => {
    if (a.srcId) pulseNode(a.srcId)
    if (a.srcId && a.tgtId) animateDot(a.srcId, a.tgtId)
  })
}, { deep: true })
```

With:
```javascript
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

- [ ] **Step 2: Run dev server and manually verify by starting a description-flow simulation**

Trigger a simulation run and observe:
- Source agent node bounces hard (elastic, r 10→20→10)
- Target agent node bounces softly (r 10→15→10)
- A dot travels along the edge (or temporary arc if no static edge exists)
- Temporary arc fades out cleanly after the dot finishes

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/GraphPanel.vue
git commit -m "feat: pulse target node on communication event"
```
