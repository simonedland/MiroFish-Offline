<template>
  <div class="main-view">
    <!-- Header -->
    <header class="app-header">
      <div class="header-left">
        <div class="brand" @click="router.push('/')">MIROFISH OFFLINE</div>
      </div>
      
      <div class="header-center">
        <div class="view-switcher">
          <button
            v-for="mode in ['graph', 'split', 'workbench', 'sms']"
            :key="mode"
            class="switch-btn"
            :class="{ active: viewMode === mode }"
            @click="viewMode = mode"
          >
            {{ { graph: 'Graph', split: 'Split', workbench: 'Workbench', sms: 'SMS Inbox' }[mode] }}
          </button>
        </div>
      </div>

      <div class="header-right">
        <div class="workflow-step">
          <span class="step-num">Step 3/5</span>
          <span class="step-name">Simulation</span>
        </div>
        <div class="step-divider"></div>
        <span class="status-indicator" :class="statusClass">
          <span class="dot"></span>
          {{ statusText }}
        </span>
      </div>
    </header>

    <!-- Main Content Area -->
    <main class="content-area">
      <!-- SMS Inbox Panel -->
      <div v-if="viewMode === 'sms'" class="panel-wrapper sms-full">
        <SmsInboxPanel
          :simulation-id="currentSimulationId"
          :is-running="isSimulating"
        />
      </div>

      <template v-else>
        <!-- Left Panel: Graph -->
        <div class="panel-wrapper left" :style="leftPanelStyle">
          <GraphPanel
            :graphData="graphData"
            :loading="graphLoading"
            :currentPhase="3"
            :isSimulating="isSimulating"
            :clustered="isDescriptionFlow"
            :recentActions="latestActions"
            @refresh="refreshGraph"
            @toggle-maximize="toggleMaximize('graph')"
          />
        </div>

        <!-- Right Panel: Step3 Simulation -->
        <div class="panel-wrapper right" :style="rightPanelStyle">
          <Step3Simulation
            :simulationId="currentSimulationId"
            :maxRounds="maxRounds"
            :minutesPerRound="minutesPerRound"
            :projectData="projectData"
            :graphData="graphData"
            :systemLogs="systemLogs"
            @go-back="handleGoBack"
            @next-step="handleNextStep"
            @add-log="addLog"
            @update-status="updateStatus"
          />
        </div>
      </template>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import GraphPanel from '../components/GraphPanel.vue'
import Step3Simulation from '../components/Step3Simulation.vue'
import SmsInboxPanel from '../components/SmsInboxPanel.vue'
import { getProject, getGraphData } from '../api/graph'
import { getSimulation, getSimulationConfig, getSimulationProfiles, getSimulationActions, getRunStatusDetail, stopSimulation, closeSimulationEnv, getEnvStatus, getSimulationRelationships } from '../api/simulation'
import { getSimulationGroups } from '../api/scenario'

const route = useRoute()
const router = useRouter()

// Props
const props = defineProps({
  simulationId: String
})

// Layout State
const viewMode = ref('split')

// Data State
const currentSimulationId = ref(route.params.simulationId)
// Get maxRounds from query param during init to ensure child components get value immediately
const maxRounds = ref(route.query.maxRounds ? parseInt(route.query.maxRounds) : null)
const minutesPerRound = ref(30) // Default 30 minutes per round
const projectData = ref(null)
const graphData = ref(null)
const graphLoading = ref(false)
const isDescriptionFlow = ref(false)
const agentNameMap = ref({})    // username.lower → user_id (built by buildAgentGraph)
const latestActions = ref([])   // [{srcId, tgtId?}] — fed to GraphPanel for animation
let seenActionCount = 0
let actionPollTimer = null
const systemLogs = ref([])
const currentStatus = ref('processing') // processing | completed | error

// --- Computed Layout Styles ---
const leftPanelStyle = computed(() => {
  if (viewMode.value === 'graph') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'workbench') return { width: '0%', opacity: 0, transform: 'translateX(-20px)' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)' }
})

const rightPanelStyle = computed(() => {
  if (viewMode.value === 'workbench') return { width: '100%', opacity: 1, transform: 'translateX(0)' }
  if (viewMode.value === 'graph') return { width: '0%', opacity: 0, transform: 'translateX(20px)' }
  return { width: '50%', opacity: 1, transform: 'translateX(0)' }
})

// --- Status Computed ---
const statusClass = computed(() => {
  return currentStatus.value
})

const statusText = computed(() => {
  if (currentStatus.value === 'error') return 'Error'
  if (currentStatus.value === 'completed') return 'Completed'
  return 'Running'
})

const isSimulating = computed(() => currentStatus.value === 'processing')

// --- Helpers ---
const addLog = (msg) => {
  const time = new Date().toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' }) + '.' + new Date().getMilliseconds().toString().padStart(3, '0')
  systemLogs.value.push({ time, msg })
  if (systemLogs.value.length > 200) {
    systemLogs.value.shift()
  }
}

const updateStatus = (status) => {
  currentStatus.value = status
}

// --- Layout Methods ---
const toggleMaximize = (target) => {
  if (viewMode.value === target) {
    viewMode.value = 'split'
  } else {
    viewMode.value = target
  }
}

const handleGoBack = async () => {
  // Close running simulation before returning to Step 2
  addLog('Returning to Step 2, closing simulation...')

  try {
    // First try gracefully closing the simulation environment
    const envStatusRes = await getEnvStatus({ simulation_id: currentSimulationId.value })
    
    if (envStatusRes.success && envStatusRes.data?.env_alive) {
      addLog('Closing simulation environment...')
      try {
        await closeSimulationEnv({
          simulation_id: currentSimulationId.value,
          timeout: 10
        })
        addLog('✓ Simulation environment closed')
      } catch (closeErr) {
        addLog(`Failed to close env, force stopping...`)
        try {
          await stopSimulation({ simulation_id: currentSimulationId.value })
          addLog('✓ Simulation force stopped')
        } catch (stopErr) {
          addLog(`Force stop failed: ${stopErr.message}`)
        }
      }
    } else {
      // Environment not running, check if process needs to be stopped
      if (isSimulating.value) {
        addLog('Stopping simulation process...')
        try {
          await stopSimulation({ simulation_id: currentSimulationId.value })
          addLog('✓ Simulation stopped')
        } catch (err) {
          addLog(`Stop simulation failed: ${err.message}`)
        }
      }
    }
  } catch (err) {
    addLog(`Failed to check simulation status: ${err.message}`)
  }

  // Return to Step 2 (Env Setup)
  router.push({ name: 'Simulation', params: { simulationId: currentSimulationId.value } })
}

const handleNextStep = () => {
  // Step3Simulation component will handle report generation and routing
  // This method is for backup only
  addLog('Entering Step 4: Report')
}

// --- Data Logic ---
const loadSimulationData = async () => {
  try {
    addLog(`Loading simulation data: ${currentSimulationId.value}`)

    // Get simulation information
    const simRes = await getSimulation(currentSimulationId.value)
    if (simRes.success && simRes.data) {
      const simData = simRes.data
      
      // Get simulation config to get minutes_per_round
      try {
        const configRes = await getSimulationConfig(currentSimulationId.value)
        if (configRes.success && configRes.data?.time_config?.minutes_per_round) {
          minutesPerRound.value = configRes.data.time_config.minutes_per_round
          addLog(`Time config: ${minutesPerRound.value} min/round`)
        }
      } catch (configErr) {
        addLog(`Failed to get time config, using default: ${minutesPerRound.value} min/round`)
      }

      // For description-flow: build agent relationship graph from profiles + groups
      if (simData.project_id === 'scenario_flow') {
        isDescriptionFlow.value = true
        await buildAgentGraph()
      }

      // Get project information (skip for description-flow simulations)
      if (simData.project_id && simData.project_id !== 'scenario_flow') {
        const projRes = await getProject(simData.project_id)
        if (projRes.success && projRes.data) {
          projectData.value = projRes.data
          addLog(`Project loaded: ${projRes.data.project_id}`)

          // Get graph data
          if (projRes.data.graph_id) {
            await loadGraph(projRes.data.graph_id)
          }
        }
      }
    } else {
      addLog(`Failed to load simulation data: ${simRes.error || 'Unknown error'}`)
    }
  } catch (err) {
    addLog(`Load error: ${err.message}`)
  }
}

const loadGraph = async (graphId) => {
  // Auto-refresh during simulation doesn't show fullscreen loading to avoid flickering
  // Show loading for manual refresh or initial load
  if (!isSimulating.value) {
    graphLoading.value = true
  }

  try {
    const res = await getGraphData(graphId)
    if (res.success) {
      graphData.value = res.data
      if (!isSimulating.value) {
        addLog('Graph data loaded successfully')
      }
    }
  } catch (err) {
    addLog(`Graph load failed: ${err.message}`)
  } finally {
    graphLoading.value = false
  }
}

const refreshGraph = () => {
  if (isDescriptionFlow.value) {
    buildAgentGraph()
  } else if (projectData.value?.graph_id) {
    loadGraph(projectData.value.graph_id)
  }
}

// Build a D3-compatible agent interaction graph for description-flow simulations.
// Nodes  = agents (colored by group via labels[])
// Edges  = group-level interactions + actual reply/follow actions from the run log
const buildAgentGraph = async () => {
  graphLoading.value = true
  try {
    const [profilesRes, groupsRes, actionsRes] = await Promise.allSettled([
      getSimulationProfiles(currentSimulationId.value, 'reddit'),
      getSimulationGroups(currentSimulationId.value),
      getSimulationActions(currentSimulationId.value, { limit: 500 }),
    ])

    const profiles = profilesRes.status === 'fulfilled' ? (profilesRes.value.data?.profiles || []) : []
    const groups   = groupsRes.status   === 'fulfilled' ? (groupsRes.value.data?.groups || []) : []
    const actions  = actionsRes.status  === 'fulfilled' ? (actionsRes.value.data?.actions || []) : []

    if (profiles.length === 0) return

    // Build group lookup for node enrichment
    const groupByName = {}
    groups.forEach(g => { groupByName[g.name] = g })

    // Build node list — one node per agent, with full profile + group data for detail panel
    const nodes = profiles.map(p => {
      const groupId = p.group_id || 'agent'
      const group   = groupByName[groupId] || null
      return {
        uuid:   `agent_${p.user_id}`,
        name:   p.username || p.user_name || p.name || `Agent ${p.user_id}`,
        labels: [groupId],
        // Agent detail fields
        username:    p.username || p.user_name || '',
        bio:         p.bio || '',
        persona:     p.persona || '',
        age:         p.age || null,
        gender:      p.gender || null,
        mbti:        p.mbti || null,
        country:     p.country || null,
        profession:  p.profession || null,
        interested_topics: p.interested_topics || [],
        karma:       p.karma || null,
        group_id:    groupId,
        // Embedded group definition for schedule/behavior info
        group: group ? {
          label:                group.label,
          behavior_description: group.behavior_description,
          communication_style:  group.communication_style,
          stance:               group.stance,
          sentiment_bias:       group.sentiment_bias,
          activity_level:       group.activity_level,
          active_hours_hint:    group.active_hours_hint,
          interacts_with:       group.interacts_with || [],
        } : null,
      }
    })

    // Lookup maps
    const agentByName = {}
    profiles.forEach(p => {
      const n = (p.username || p.user_name || '').toLowerCase()
      if (n) agentByName[n] = p.user_id
    })

    const groupAgents = {}
    profiles.forEach(p => {
      const g = p.group_id || 'unknown'
      if (!groupAgents[g]) groupAgents[g] = []
      groupAgents[g].push(p.user_id)
    })

    const edgeSet = new Set()
    const edges   = []

    const addEdge = (srcId, tgtId, type, label) => {
      if (srcId === tgtId) return
      const key = `${srcId}_${tgtId}_${type}`
      if (edgeSet.has(key)) return
      edgeSet.add(key)
      edges.push({
        source_node_uuid: `agent_${srcId}`,
        target_node_uuid: `agent_${tgtId}`,
        relationship_type: type,
        name: label || type,
      })
    }

    // 1. Group-defined interactions
    groups.forEach(group => {
      const srcs = groupAgents[group.name] || []
      if (!srcs.length) return

      // Dense intra-group mesh — every agent connects to several neighbours
      // (makes same-group nodes cluster tightly)
      const intraCount = Math.min(srcs.length, group.communication_style === 'coordinate_within_group' ? srcs.length : 3)
      for (let i = 0; i < srcs.length; i++) {
        for (let j = 1; j <= intraCount; j++) {
          addEdge(srcs[i], srcs[(i + j) % srcs.length],
            group.communication_style === 'coordinate_within_group' ? 'COORDINATES' : 'KNOWS')
        }
      }

      // Cross-group targeting — sparse, labelled by relationship
      ;(group.interacts_with || []).forEach(targetName => {
        const tgts = groupAgents[targetName] || []
        if (!tgts.length) return
        const label = `${group.name} → ${targetName}`
        const n = Math.min(srcs.length, 5)
        for (let i = 0; i < n; i++) {
          addEdge(srcs[i], tgts[i % tgts.length], label)
        }
      })
    })

    // 2. AI-generated relationships
    try {
      const relRes = await getSimulationRelationships(currentSimulationId.value)
      const aiEdges = relRes.data?.edges || []
      aiEdges.forEach(e => {
        addEdge(e.src_id, e.tgt_id, e.type, e.label)
      })
      addLog(`AI relationships: ${aiEdges.length} edges`)
    } catch (err) {
      addLog(`AI relationships skipped: ${err.message}`)
    }

    // 3. Actual actions from the simulation run
    actions.forEach(a => {
      const srcId = a.agent_id
      const args  = a.action_args || {}
      const type  = (a.action_type || '').toUpperCase()

      // FOLLOW / LIKE actions carry user_id or target_id
      const targetId = args.user_id ?? args.target_id
      if (targetId != null && targetId !== srcId) {
        addEdge(srcId, targetId, type === 'FOLLOW' ? 'FOLLOWS' : 'INTERACTS')
        return
      }

      // COMMENT / LIKE_POST: target is the post author
      const authorName = (args.post_author_name || args.comment_author_name || args.original_author_name || '').toLowerCase()
      if (authorName) {
        const tgtId = agentByName[authorName]
        if (tgtId != null) addEdge(srcId, tgtId, 'REPLIES')
      }
    })

    graphData.value = { nodes, edges }
    agentNameMap.value = agentByName   // save for action processing
    addLog(`Agent graph: ${nodes.length} nodes, ${edges.length} edges`)
  } catch (err) {
    addLog(`Agent graph failed: ${err.message}`)
  } finally {
    graphLoading.value = false
  }
}

// Process new simulation actions into animation events for GraphPanel
const processNewActions = (actions) => {
  if (actions.length <= seenActionCount) return
  const fresh = actions.slice(seenActionCount)
  seenActionCount = actions.length
  latestActions.value = fresh.map(a => {
    const srcId = `agent_${a.agent_id}`
    const args = a.action_args || {}
    const authorName = (
      args.post_author_name || args.comment_author_name || args.original_author_name || ''
    ).toLowerCase()
    const tgtUserId = agentNameMap.value[authorName]
    const tgtId = tgtUserId != null ? `agent_${tgtUserId}` : null
    return { srcId, tgtId, type: (a.action_type || '').toUpperCase() }
  }).filter(a => a.srcId)
}

const startActionPoll = () => {
  if (actionPollTimer) return
  actionPollTimer = setInterval(async () => {
    try {
      const res = await getRunStatusDetail(currentSimulationId.value)
      processNewActions(res.data?.all_actions || [])
    } catch (_) {}
  }, 4000)
}

const stopActionPoll = () => {
  if (actionPollTimer) { clearInterval(actionPollTimer); actionPollTimer = null }
}

watch(isSimulating, (newValue) => {
  if (newValue) {
    if (isDescriptionFlow.value) {
      startActionPoll()   // description-flow: animate actions, don't rebuild graph
    }
    // document-flow: graph only refreshes on manual Refresh button click
  } else {
    stopActionPoll()
  }
}, { immediate: true })

onMounted(() => {
  addLog('SimulationRunView initialized')

  // Log maxRounds config (value already retrieved from query param during init)
  if (maxRounds.value) {
    addLog(`Custom simulation rounds: ${maxRounds.value}`)
  }
  
  loadSimulationData()
})

onUnmounted(() => {
  stopActionPoll()
})
</script>

<style scoped>
.main-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #FFF;
  overflow: hidden;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
}

/* Header */
.app-header {
  height: 60px;
  border-bottom: 1px solid #EAEAEA;
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 24px;
  background: #FFF;
  z-index: 100;
  position: relative;
}

.header-center {
  position: absolute;
  left: 50%;
  transform: translateX(-50%);
}

.brand {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 800;
  font-size: 18px;
  letter-spacing: 1px;
  cursor: pointer;
}

.view-switcher {
  display: flex;
  background: #F5F5F5;
  padding: 4px;
  border-radius: 6px;
  gap: 4px;
}

.switch-btn {
  border: none;
  background: transparent;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 600;
  color: #666;
  border-radius: 4px;
  cursor: pointer;
  transition: all 0.2s;
}

.switch-btn.active {
  background: #FFF;
  color: #000;
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.workflow-step {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 14px;
}

.step-num {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  color: #999;
}

.step-name {
  font-weight: 700;
  color: #000;
}

.step-divider {
  width: 1px;
  height: 14px;
  background-color: #E0E0E0;
}

.status-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: #666;
  font-weight: 500;
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #CCC;
}

.status-indicator.processing .dot { background: #FF5722; animation: pulse 1s infinite; }
.status-indicator.completed .dot { background: #4CAF50; }
.status-indicator.error .dot { background: #F44336; }

@keyframes pulse { 50% { opacity: 0.5; } }

/* Content */
.content-area {
  flex: 1;
  display: flex;
  position: relative;
  overflow: hidden;
}

.panel-wrapper {
  height: 100%;
  overflow: hidden;
  transition: width 0.4s cubic-bezier(0.25, 0.8, 0.25, 1), opacity 0.3s ease, transform 0.3s ease;
  will-change: width, opacity, transform;
}

.panel-wrapper.left {
  border-right: 1px solid #EAEAEA;
}

.panel-wrapper.sms-full {
  width: 100%;
  padding: 16px;
  box-sizing: border-box;
}


</style>

