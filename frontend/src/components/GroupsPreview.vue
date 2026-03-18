<template>
  <div :style="s.container">
    <div :style="s.header">
      <span :style="s.title">{{ scenario.title }}</span>
      <span :style="s.badge">{{ scenario.total_agents }} agents · {{ scenario.platform_hint }}</span>
    </div>

    <div :style="s.groupList">
      <div
        v-for="group in scenario.groups"
        :key="group.name"
        :style="[s.groupCard, stanceStyle(group.stance)]"
      >
        <div :style="s.groupHeader">
          <span :style="s.groupLabel">{{ group.label }}</span>
          <span :style="s.groupCount">{{ group.count }} agents ({{ pct(group.percentage) }})</span>
        </div>
        <p :style="s.groupBehavior">{{ group.behavior_description }}</p>
        <div :style="s.groupMeta">
          <span :style="s.tag">{{ group.stance }}</span>
          <span :style="s.tag">{{ group.communication_style }}</span>
          <span :style="s.tag">{{ group.active_hours_hint }}</span>
          <span :style="s.tag">activity {{ activityLabel(group.activity_level) }}</span>
        </div>
      </div>
    </div>

    <div :style="s.actions">
      <button :style="s.editBtn" @click="$emit('edit')">← Edit description</button>
      <button :style="[s.generateBtn, generating ? s.btnDisabled : {}]"
              :disabled="generating"
              @click="$emit('generate')">
        <span v-if="generating">Generating agents…</span>
        <span v-else>Generate Agents</span>
      </button>
    </div>
  </div>
</template>

<script setup>
const props = defineProps({
  scenario: { type: Object, required: true },
  generating: { type: Boolean, default: false },
})

defineEmits(['edit', 'generate'])

function pct(p) {
  return `${Math.round(p * 100)}%`
}

function activityLabel(v) {
  if (v >= 0.8) return 'high'
  if (v >= 0.5) return 'medium'
  return 'low'
}

const stanceColors = {
  neutral: '#1a2a1a',
  supportive: '#1a2730',
  opposing: '#2a1a1a',
  disruptive: '#2a1a2a',
}

function stanceStyle(stance) {
  return { background: stanceColors[stance] || '#1a1a1a' }
}

const s = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '16px',
  },
  header: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    gap: '12px',
  },
  title: {
    fontFamily: 'monospace',
    fontSize: '16px',
    fontWeight: '700',
    color: '#e0e0e0',
  },
  badge: {
    fontFamily: 'monospace',
    fontSize: '12px',
    color: '#888',
    background: '#222',
    border: '1px solid #333',
    borderRadius: '4px',
    padding: '3px 8px',
    whiteSpace: 'nowrap',
  },
  groupList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
  },
  groupCard: {
    border: '1px solid #333',
    borderRadius: '6px',
    padding: '12px 14px',
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  groupHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'baseline',
    gap: '8px',
  },
  groupLabel: {
    fontFamily: 'monospace',
    fontSize: '14px',
    fontWeight: '700',
    color: '#e0e0e0',
  },
  groupCount: {
    fontFamily: 'monospace',
    fontSize: '12px',
    color: '#e8642a',
    fontWeight: '600',
  },
  groupBehavior: {
    fontFamily: 'monospace',
    fontSize: '12px',
    color: '#aaa',
    margin: '0',
    lineHeight: '1.5',
  },
  groupMeta: {
    display: 'flex',
    flexWrap: 'wrap',
    gap: '6px',
    marginTop: '4px',
  },
  tag: {
    fontFamily: 'monospace',
    fontSize: '11px',
    color: '#888',
    background: '#252525',
    border: '1px solid #333',
    borderRadius: '3px',
    padding: '2px 7px',
  },
  actions: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: '12px',
    marginTop: '4px',
  },
  editBtn: {
    background: 'transparent',
    color: '#888',
    border: '1px solid #444',
    borderRadius: '5px',
    padding: '9px 16px',
    fontFamily: 'monospace',
    fontSize: '12px',
    cursor: 'pointer',
  },
  generateBtn: {
    background: '#e8642a',
    color: '#fff',
    border: 'none',
    borderRadius: '5px',
    padding: '10px 24px',
    fontFamily: 'monospace',
    fontSize: '13px',
    fontWeight: '700',
    cursor: 'pointer',
  },
  btnDisabled: {
    background: '#444',
    cursor: 'not-allowed',
    opacity: '0.6',
  },
}
</script>
