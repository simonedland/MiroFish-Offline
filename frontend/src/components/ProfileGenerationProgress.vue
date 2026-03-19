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
          {{ phase > 3 ? 'done' : phase === 3 ? (relAgentTotal > 0 ? relAgentCurrent + '/' + relAgentTotal + ' agents · ' + relCount + ' links' : 'starting...') : 'waiting' }}
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

// ── Phase 3: real relationship progress from backend ─────────────────────────
const relAgentCurrent = ref(0)
const relAgentTotal   = ref(0)
const relCount        = ref(0)

const connProgress  = computed(() => relAgentCurrent.value)
const connTotal     = computed(() => relAgentTotal.value || totalAgents.value || 1)
const connPairLabel = computed(() =>
  relAgentTotal.value > 0
    ? `agent ${relAgentCurrent.value} / ${relAgentTotal.value}`
    : ''
)
const connCurrentType = computed(() => `${relCount.value} links`)
const connTick = ref(0)

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
  return Math.min(99, Math.round((connProgress.value / connTotal.value) * 100))
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

watch(relAgentCurrent, () => { connTick.value++ })

async function poll() {
  try {
    const res  = await getSimulation(props.simulationId)
    const data = res.data || res

    simStatus.value          = data.status || 'preparing'
    profilesCount.value      = data.profiles_count || 0
    configBatchCurrent.value = data.config_batch_current || 0
    configBatchTotal.value   = data.config_batch_total   || 0
    relAgentCurrent.value    = data.relationship_agent_current || 0
    relAgentTotal.value      = data.relationship_agent_total   || 0
    relCount.value           = data.relationship_count         || 0

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
