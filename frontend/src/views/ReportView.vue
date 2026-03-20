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
            v-for="mode in ['graph', 'split', 'workbench']" 
            :key="mode"
            class="switch-btn"
            :class="{ active: viewMode === mode }"
            @click="viewMode = mode"
          >
            {{ { graph: 'Graph', split: 'Split', workbench: 'Workbench' }[mode] }}
          </button>
        </div>
      </div>

      <div class="header-right">
        <div class="workflow-step">
          <span class="step-num">Step 4/5</span>
          <span class="step-name">Report</span>
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
      <!-- Left Panel: Graph -->
      <div class="panel-wrapper left" :style="leftPanelStyle">
        <GraphPanel
          :graphData="graphData"
          :loading="graphLoading"
          :currentPhase="4"
          :isSimulating="false"
          :clustered="isDescriptionFlow"
          @refresh="refreshGraph"
          @toggle-maximize="toggleMaximize('graph')"
        />
      </div>

      <!-- Right Panel: Step4 Report -->
      <div class="panel-wrapper right" :style="rightPanelStyle">
        <Step4Report
          :reportId="currentReportId"
          :simulationId="simulationId"
          :systemLogs="systemLogs"
          @add-log="addLog"
          @update-status="updateStatus"
        />
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import GraphPanel from '../components/GraphPanel.vue'
import Step4Report from '../components/Step4Report.vue'
import { getProject, getGraphData } from '../api/graph'
import { getSimulation, getSimulationProfiles, getSimulationRelationships } from '../api/simulation'
import { getSimulationGroups } from '../api/scenario'
import { getReport } from '../api/report'

const route = useRoute()
const router = useRouter()

// Props
const props = defineProps({
  reportId: String
})

// Layout State - Default to workbench view
const viewMode = ref('workbench')

// Data State
const currentReportId = ref(route.params.reportId)
const simulationId = ref(null)
const projectData = ref(null)
const graphData = ref(null)
const graphLoading = ref(false)
const isDescriptionFlow = ref(false)
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
  return 'Generating'
})

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

// --- Data Logic ---
const loadReportData = async () => {
  try {
    addLog(`Loading report data: ${currentReportId.value}`)
    
    // Get report info to retrieve simulation_id
    const reportRes = await getReport(currentReportId.value)
    if (reportRes.success && reportRes.data) {
      const reportData = reportRes.data
      simulationId.value = reportData.simulation_id
      
      if (simulationId.value) {
        // Get simulation info
        const simRes = await getSimulation(simulationId.value)
        if (simRes.success && simRes.data) {
          const simData = simRes.data
          
          // Get project info
          if (simData.project_id) {
            const projRes = await getProject(simData.project_id)
            if (projRes.success && projRes.data) {
              projectData.value = projRes.data
              addLog(`Project loaded: ${projRes.data.project_id}`)
              
              // Get graph data
              if (projRes.data.graph_id) {
                await loadGraph(projRes.data.graph_id)
              } else {
                // Description-flow: no Neo4j graph — build synthetic agent graph
                isDescriptionFlow.value = true
                await buildAgentGraph()
              }
            }
          }
        }
      }
    } else {
      addLog(`Failed to load report: ${reportRes.error || 'Unknown error'}`)
    }
  } catch (err) {
    addLog(`Load error: ${err.message}`)
  }
}

const loadGraph = async (graphId) => {
  graphLoading.value = true
  
  try {
    const res = await getGraphData(graphId)
    if (res.success) {
      graphData.value = res.data
      addLog('Graph data loaded successfully')
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

const buildAgentGraph = async () => {
  if (!simulationId.value) return
  graphLoading.value = true
  try {
    const [profilesRes, groupsRes] = await Promise.allSettled([
      getSimulationProfiles(simulationId.value, 'reddit'),
      getSimulationGroups(simulationId.value),
    ])

    const profiles = profilesRes.status === 'fulfilled' ? (profilesRes.value.data?.profiles || []) : []
    const groups   = groupsRes.status   === 'fulfilled' ? (groupsRes.value.data?.groups || []) : []

    if (profiles.length === 0) return

    const groupByName = {}
    groups.forEach(g => { groupByName[g.name] = g })

    const nodes = profiles.map(p => {
      const groupId = p.group_id || 'agent'
      const group   = groupByName[groupId] || null
      return {
        uuid:   `agent_${p.user_id}`,
        name:   p.username || p.user_name || p.name || `Agent ${p.user_id}`,
        labels: [groupId],
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

    groups.forEach(group => {
      const srcs = groupAgents[group.name] || []
      if (!srcs.length) return
      const intraCount = Math.min(srcs.length, group.communication_style === 'coordinate_within_group' ? srcs.length : 3)
      for (let i = 0; i < srcs.length; i++) {
        for (let j = 1; j <= intraCount; j++) {
          addEdge(srcs[i], srcs[(i + j) % srcs.length],
            group.communication_style === 'coordinate_within_group' ? 'COORDINATES' : 'KNOWS')
        }
      }
      ;(group.interacts_with || []).forEach(targetName => {
        const tgts = groupAgents[targetName] || []
        if (!tgts.length) return
        const n = Math.min(srcs.length, 5)
        for (let i = 0; i < n; i++) {
          addEdge(srcs[i], tgts[i % tgts.length], `${group.name} → ${targetName}`)
        }
      })
    })

    try {
      const relRes = await getSimulationRelationships(simulationId.value)
      const aiEdges = relRes.data?.edges || []
      aiEdges.forEach(e => { addEdge(e.src_id, e.tgt_id, e.type, e.label) })
      addLog(`AI relationships: ${aiEdges.length} edges`)
    } catch (err) {
      addLog(`AI relationships skipped: ${err.message}`)
    }

    graphData.value = { nodes, edges }
    addLog(`Agent graph: ${nodes.length} nodes, ${edges.length} edges`)
  } catch (err) {
    addLog(`Agent graph build failed: ${err.message}`)
  } finally {
    graphLoading.value = false
  }
}

// Watch route params
watch(() => route.params.reportId, (newId) => {
  if (newId && newId !== currentReportId.value) {
    currentReportId.value = newId
    loadReportData()
  }
}, { immediate: true })

onMounted(() => {
  addLog('ReportView initialized')
  loadReportData()
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

.status-indicator.processing .dot { background: #FF9800; animation: pulse 1s infinite; }
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
</style>
