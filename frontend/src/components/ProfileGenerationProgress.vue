<template>
  <div :style="s.container">

    <!-- Phase 1: Generating profiles -->
    <div :style="s.phase">
      <div :style="s.phaseHeader">
        <span :style="s.phaseNum">1</span>
        <span :style="[s.phaseLabel, phase >= 1 ? s.activeLabel : s.dimLabel]">Generating agent profiles</span>
        <span :style="[s.phaseBadge, phaseColor(1)]">
          {{ phase > 1 ? 'done' : phase === 1 ? profilesCount + '/' + totalAgents : 'waiting' }}
        </span>
      </div>
      <div :style="s.barTrack">
        <div :style="[s.barFill, { width: phase1Pct + '%' }, phaseBarColor(1)]" />
      </div>
    </div>

    <!-- Phase 2: Generating agent configs -->
    <div :style="s.phase">
      <div :style="s.phaseHeader">
        <span :style="s.phaseNum">2</span>
        <span :style="[s.phaseLabel, phase >= 2 ? s.activeLabel : s.dimLabel]">Generating agent configs</span>
        <span :style="[s.phaseBadge, phaseColor(2)]">
          {{ phase > 2 ? 'done' : phase === 2 ? configBatchCurrent + '/' + configBatchTotal + ' batches' : 'waiting' }}
        </span>
      </div>
      <div :style="s.barTrack">
        <div :style="[s.barFill, { width: phase2Pct + '%' }, phaseBarColor(2)]" />
      </div>
    </div>

    <!-- Phase 3: Establishing relations -->
    <div :style="s.phase">
      <div :style="s.phaseHeader">
        <span :style="s.phaseNum">3</span>
        <span :style="[s.phaseLabel, phase >= 3 ? s.activeLabel : s.dimLabel]">Establishing agent relations</span>
        <span :style="[s.phaseBadge, phaseColor(3)]">
          {{ phase > 3 ? 'done' : phase === 3 ? connProgress + '/' + connTotal + ' links' : 'waiting' }}
        </span>
      </div>
      <div :style="s.barTrack">
        <div :style="[s.barFill, { width: phase3Pct + '%' }, phaseBarColor(3)]" />
      </div>
      <!-- Live connection ticker -->
      <transition name="conn-fade">
        <div v-if="phase === 3" :key="connTick" :style="s.connTicker">
          <span :style="s.connType">{{ connCurrentType }}</span>
          <span :style="s.connArrow">→</span>
          <span :style="s.connPair">{{ connPairLabel }}</span>
        </div>
      </transition>
    </div>

    <p v-if="errorMsg" :style="s.error">{{ errorMsg }}</p>

  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { getSimulation } from '../api/simulation'

const props = defineProps({
  simulationId: { type: String, required: true },
  totalAgents:  { type: Number, default: 0 },
  groups:       { type: Array, default: () => [] },
})

const emit = defineEmits(['ready', 'failed'])

const profilesCount     = ref(0)
const totalAgents       = ref(props.totalAgents)
const configBatchCurrent = ref(0)
const configBatchTotal   = ref(0)
const simStatus         = ref('preparing')
const errorMsg          = ref('')
let pollTimer = null

// ── Phase 3 connection animation ─────────────────────────────────────────────
const INTRA_TYPES  = ['KNOWS', 'COORDINATES', 'AGREES_WITH', 'TRUSTS', 'ALIGNS_WITH']
const CROSS_TYPES  = ['REPLIES', 'FOLLOWS', 'MENTIONS', 'REACTS_TO', 'DISPUTES', 'CHALLENGES']
const connProgress   = ref(0)
const connTotal      = ref(0)
const connTick       = ref(0)   // key for transition re-trigger
const connCurrentType = ref('KNOWS')
const connPairLabel  = ref('')
let connTimer = null

// Build a flat list of (srcGroup, tgtGroup, relType) connection pairs to cycle through
function buildConnPairs() {
  const groups = props.groups || []
  if (!groups.length) return null  // fallback to index-based
  const pairs = []
  groups.forEach(g => {
    const targets = g.interacts_with?.length ? g.interacts_with : []
    // intra-group pairs
    for (let k = 0; k < 4; k++) {
      pairs.push({ src: g.name, tgt: g.name, type: INTRA_TYPES[k % INTRA_TYPES.length] })
    }
    // cross-group pairs
    targets.forEach(t => {
      for (let k = 0; k < 3; k++) {
        pairs.push({ src: g.name, tgt: t, type: CROSS_TYPES[k % CROSS_TYPES.length] })
      }
    })
    // if no explicit targets, pair with every other group
    if (!targets.length && groups.length > 1) {
      groups.forEach(other => {
        if (other.name !== g.name) {
          pairs.push({ src: g.name, tgt: other.name, type: CROSS_TYPES[Math.floor(Math.random() * CROSS_TYPES.length)] })
        }
      })
    }
  })
  return pairs.length ? pairs : null
}

function startConnAnimation() {
  if (connTimer) return
  const n = totalAgents.value || 50
  connTotal.value  = Math.round(n * 3.2)
  connProgress.value = 0

  const pairs    = buildConnPairs()
  const duration = 12000
  const steps    = connTotal.value
  const interval = Math.max(40, Math.round(duration / steps))

  connTimer = setInterval(() => {
    if (connProgress.value >= connTotal.value) {
      clearInterval(connTimer)
      connTimer = null
      return
    }
    const jump = Math.ceil(Math.random() * 3)
    connProgress.value = Math.min(connTotal.value, connProgress.value + jump)
    connTick.value++

    if (pairs) {
      // Cycle through group-aware pairs, occasionally shuffle
      const idx = (connTick.value + Math.floor(Math.random() * 2)) % pairs.length
      const p = pairs[idx]
      connCurrentType.value = p.type
      const arrow = p.src === p.tgt ? '↔' : '→'
      connPairLabel.value = `${p.src} ${arrow} ${p.tgt}`
    } else {
      // Fallback: agent index pairs
      if (connTick.value % 8 === 0) {
        connCurrentType.value = INTRA_TYPES[Math.floor(Math.random() * INTRA_TYPES.length)]
      }
      const a = Math.floor(Math.random() * n)
      let b = Math.floor(Math.random() * n)
      if (b === a) b = (a + 1) % n
      connPairLabel.value = `agent_${a} ↔ agent_${b}`
    }
  }, interval)
}

function stopConnAnimation() {
  if (connTimer) { clearInterval(connTimer); connTimer = null }
}

// Which phase are we in: 1=profiles, 2=configs, 3=relations, 4=done
const phase = computed(() => {
  if (simStatus.value === 'ready') return 4
  if (configBatchTotal.value > 0) {
    // Config generation started
    if (configBatchCurrent.value >= configBatchTotal.value) return 3
    return 2
  }
  if (profilesCount.value >= totalAgents.value && totalAgents.value > 0) return 2
  return 1
})

const phase1Pct = computed(() => {
  if (phase.value > 1) return 100
  if (!totalAgents.value) return 0
  return Math.min(100, Math.round((profilesCount.value / totalAgents.value) * 100))
})

const phase2Pct = computed(() => {
  if (phase.value > 2) return 100
  if (phase.value < 2 || !configBatchTotal.value) return 0
  return Math.min(100, Math.round((configBatchCurrent.value / configBatchTotal.value) * 100))
})

const phase3Pct = computed(() => {
  if (phase.value > 3) return 100
  if (phase.value < 3) return 0
  if (!connTotal.value) return 5
  return Math.min(95, Math.round((connProgress.value / connTotal.value) * 95))
})

const phaseColor = (n) => {
  if (phase.value > n) return { color: '#4ade80' }
  if (phase.value === n) return { color: '#e8642a' }
  return { color: '#444' }
}

const phaseBarColor = (n) => {
  if (phase.value > n) return { background: '#4ade80' }
  if (phase.value === n) return { background: 'linear-gradient(90deg,#e8642a,#f0884a)' }
  return { background: '#2a2a2a' }
}

watch(phase, (p) => {
  if (p === 3) startConnAnimation()
  else if (p > 3) { stopConnAnimation(); connProgress.value = connTotal.value }
})

async function poll() {
  try {
    const res  = await getSimulation(props.simulationId)
    const data = res.data || res

    simStatus.value          = data.status || 'preparing'
    profilesCount.value      = data.profiles_count || 0
    configBatchCurrent.value = data.config_batch_current || 0
    configBatchTotal.value   = data.config_batch_total   || 0

    if (data.total_agents && data.total_agents > 0) {
      totalAgents.value = data.total_agents
    }

    if (data.status === 'ready') {
      clearInterval(pollTimer)
      emit('ready', props.simulationId)
    } else if (data.status === 'failed') {
      clearInterval(pollTimer)
      errorMsg.value = data.error || 'Preparation failed'
      emit('failed', data.error)
    }
  } catch (err) {
    console.warn('Poll error:', err)
  }
}

onMounted(() => {
  poll()
  pollTimer = setInterval(poll, 3000)
})

onUnmounted(() => {
  clearInterval(pollTimer)
  stopConnAnimation()
})

const s = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '18px',
  },
  phase: {
    display: 'flex',
    flexDirection: 'column',
    gap: '8px',
  },
  phaseHeader: {
    display: 'flex',
    alignItems: 'center',
    gap: '10px',
  },
  phaseNum: {
    fontFamily: 'monospace',
    fontSize: '11px',
    color: '#444',
    background: '#1a1a1a',
    border: '1px solid #2a2a2a',
    borderRadius: '50%',
    width: '20px',
    height: '20px',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    flexShrink: '0',
  },
  phaseLabel: {
    fontFamily: 'monospace',
    fontSize: '13px',
    flex: '1',
  },
  activeLabel: { color: '#e0e0e0', fontWeight: '600' },
  dimLabel:    { color: '#444' },
  phaseBadge: {
    fontFamily: 'monospace',
    fontSize: '11px',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  barTrack: {
    width: '100%',
    height: '6px',
    background: '#1a1a1a',
    borderRadius: '3px',
    overflow: 'hidden',
    border: '1px solid #2a2a2a',
  },
  barFill: {
    height: '100%',
    borderRadius: '3px',
    transition: 'width 0.5s ease',
  },
  error: {
    fontFamily: 'monospace',
    fontSize: '12px',
    color: '#e05252',
    margin: '0',
  },
  connTicker: {
    display: 'flex',
    alignItems: 'center',
    gap: '6px',
    marginTop: '4px',
    fontFamily: 'monospace',
    fontSize: '11px',
    color: '#555',
    overflow: 'hidden',
    whiteSpace: 'nowrap',
  },
  connType: {
    color: '#e8642a',
    fontWeight: '700',
    letterSpacing: '0.04em',
    minWidth: '110px',
  },
  connArrow: {
    color: '#444',
  },
  connPair: {
    color: '#888',
  },
}
</script>

<style scoped>
.conn-fade-enter-active,
.conn-fade-leave-active {
  transition: opacity 0.18s ease, transform 0.18s ease;
}
.conn-fade-enter-from {
  opacity: 0;
  transform: translateY(-4px);
}
.conn-fade-leave-to {
  opacity: 0;
  transform: translateY(4px);
}
</style>
