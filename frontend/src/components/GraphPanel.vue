<template>
  <div class="graph-panel">
    <div class="panel-header">
      <span class="panel-title">Graph Relationship Visualization</span>
      <!-- Top Toolbar (Internal Top Right) -->
      <div class="header-tools">
        <button class="tool-btn" @click="$emit('refresh')" :disabled="loading" title="Refresh graph">
          <span class="icon-refresh" :class="{ 'spinning': loading }">↻</span>
          <span class="btn-text">Refresh</span>
        </button>
        <button class="tool-btn" @click="$emit('toggle-maximize')" title="Maximize/Restore">
          <span class="icon-maximize">⛶</span>
        </button>
      </div>
    </div>
    
    <div class="graph-container" ref="graphContainer">
      <!-- Graph Visualization -->
      <div v-if="graphData" class="graph-view">
        <svg ref="graphSvg" class="graph-svg"></svg>
        
        <!-- Building/Simulating Hint -->
        <div v-if="currentPhase === 1 || isSimulating" class="graph-building-hint">
          <div class="memory-icon-wrapper">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="memory-icon">
              <path d="M9.5 2A2.5 2.5 0 0 1 12 4.5v15a2.5 2.5 0 0 1-4.96.44 2.5 2.5 0 0 1-2.96-3.08 3 3 0 0 1-.34-5.58 2.5 2.5 0 0 1 1.32-4.24 2.5 2.5 0 0 1 4.44-4.04z" />
              <path d="M14.5 2A2.5 2.5 0 0 0 12 4.5v15a2.5 2.5 0 0 0 4.96.44 2.5 2.5 0 0 0 2.96-3.08 3 3 0 0 0 .34-5.58 2.5 2.5 0 0 0-1.32-4.24 2.5 2.5 0 0 0-4.44-4.04z" />
            </svg>
          </div>
          {{ isSimulating ? 'GraphRAG short-term/long-term memory updating in real-time' : 'Updating in real-time...' }}
        </div>
        
        <!-- Simulation Finished Hint -->
        <div v-if="showSimulationFinishedHint" class="graph-building-hint finished-hint">
          <div class="hint-icon-wrapper">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" class="hint-icon">
              <circle cx="12" cy="12" r="10"></circle>
              <line x1="12" y1="16" x2="12" y2="12"></line>
              <line x1="12" y1="8" x2="12.01" y2="8"></line>
            </svg>
          </div>
          <span class="hint-text">Some content is still being processed. It is recommended to manually refresh the graph later</span>
          <button class="hint-close-btn" @click="dismissFinishedHint" title="Close hint">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2">
              <line x1="18" y1="6" x2="6" y2="18"></line>
              <line x1="6" y1="6" x2="18" y2="18"></line>
            </svg>
          </button>
        </div>
        
        <!-- Node/Edge Details Panel -->
        <div v-if="selectedItem" class="detail-panel">
          <div class="detail-panel-header">
            <span class="detail-title">{{ selectedItem.type === 'node' ? 'Node Details' : 'Relationship' }}</span>
            <span v-if="selectedItem.type === 'node'" class="detail-type-badge" :style="{ background: selectedItem.color, color: '#fff' }">
              {{ selectedItem.entityType }}
            </span>
            <button class="detail-close" @click="closeDetailPanel">×</button>
          </div>
          
          <!-- Node Details -->
          <div v-if="selectedItem.type === 'node'" class="detail-content">

            <!-- Agent card (description-flow: has bio/persona/group) -->
            <template v-if="selectedItem.data.bio || selectedItem.data.persona">

              <!-- Identity row -->
              <div class="agent-identity">
                <div class="agent-avatar" :style="{ background: selectedItem.color }">
                  {{ (selectedItem.data.username || selectedItem.data.name || '?')[0].toUpperCase() }}
                </div>
                <div class="agent-identity-text">
                  <div class="agent-username">@{{ selectedItem.data.username || selectedItem.data.name }}</div>
                  <div class="agent-fullname">{{ selectedItem.data.name || '' }}</div>
                </div>
              </div>

              <!-- Bio -->
              <div v-if="selectedItem.data.bio" class="agent-section">
                <div class="agent-section-title">Bio</div>
                <div class="agent-prose">{{ selectedItem.data.bio }}</div>
              </div>

              <!-- Persona -->
              <div v-if="selectedItem.data.persona" class="agent-section">
                <div class="agent-section-title">Persona</div>
                <div class="agent-prose small">{{ selectedItem.data.persona }}</div>
              </div>

              <!-- Profile facts -->
              <div class="agent-section">
                <div class="agent-section-title">Profile</div>
                <div class="agent-facts-grid">
                  <span v-if="selectedItem.data.age" class="agent-fact"><span class="fact-k">Age</span><span class="fact-v">{{ selectedItem.data.age }}</span></span>
                  <span v-if="selectedItem.data.gender" class="agent-fact"><span class="fact-k">Gender</span><span class="fact-v">{{ selectedItem.data.gender }}</span></span>
                  <span v-if="selectedItem.data.mbti" class="agent-fact"><span class="fact-k">MBTI</span><span class="fact-v">{{ selectedItem.data.mbti }}</span></span>
                  <span v-if="selectedItem.data.country" class="agent-fact"><span class="fact-k">Country</span><span class="fact-v">{{ selectedItem.data.country }}</span></span>
                  <span v-if="selectedItem.data.profession" class="agent-fact"><span class="fact-k">Profession</span><span class="fact-v">{{ selectedItem.data.profession }}</span></span>
                  <span v-if="selectedItem.data.karma" class="agent-fact"><span class="fact-k">Karma</span><span class="fact-v">{{ selectedItem.data.karma }}</span></span>
                </div>
                <div v-if="selectedItem.data.interested_topics?.length" class="agent-topics">
                  <span v-for="t in selectedItem.data.interested_topics" :key="t" class="topic-tag">{{ t }}</span>
                </div>
              </div>

              <!-- Group / Behaviour -->
              <div v-if="selectedItem.data.group" class="agent-section group-section">
                <div class="agent-section-title">
                  Group · <span :style="{ color: selectedItem.color }">{{ selectedItem.data.group.label || selectedItem.data.group_id }}</span>
                </div>

                <div v-if="selectedItem.data.group.behavior_description" class="agent-prose small muted">
                  {{ selectedItem.data.group.behavior_description }}
                </div>

                <div class="agent-facts-grid" style="margin-top:8px">
                  <span class="agent-fact"><span class="fact-k">Style</span><span class="fact-v">{{ selectedItem.data.group.communication_style }}</span></span>
                  <span class="agent-fact"><span class="fact-k">Stance</span><span class="fact-v">{{ selectedItem.data.group.stance }}</span></span>
                </div>

                <!-- Activity level bar -->
                <div class="agent-bar-row">
                  <span class="bar-label">Activity</span>
                  <div class="bar-track">
                    <div class="bar-fill activity" :style="{ width: (selectedItem.data.group.activity_level * 100) + '%' }" />
                  </div>
                  <span class="bar-val">{{ Math.round(selectedItem.data.group.activity_level * 100) }}%</span>
                </div>

                <!-- Sentiment bar (center = 0) -->
                <div class="agent-bar-row">
                  <span class="bar-label">Sentiment</span>
                  <div class="bar-track sentiment-track">
                    <div class="bar-fill sentiment"
                      :style="sentimentStyle(selectedItem.data.group.sentiment_bias)" />
                  </div>
                  <span class="bar-val">{{ selectedItem.data.group.sentiment_bias > 0 ? '+' : '' }}{{ selectedItem.data.group.sentiment_bias.toFixed(1) }}</span>
                </div>

                <!-- Schedule -->
                <div class="agent-bar-row">
                  <span class="bar-label">Schedule</span>
                  <span class="schedule-badge">{{ selectedItem.data.group.active_hours_hint }}</span>
                </div>

                <!-- Targets -->
                <div v-if="selectedItem.data.group.interacts_with?.length" class="agent-bar-row" style="align-items:flex-start">
                  <span class="bar-label">Targets</span>
                  <div style="display:flex;flex-wrap:wrap;gap:4px">
                    <span v-for="t in selectedItem.data.group.interacts_with" :key="t" class="target-tag">{{ t }}</span>
                  </div>
                </div>
              </div>

            </template>

            <!-- Fallback: document-flow node (knowledge graph entity) -->
            <template v-else>
              <div class="detail-row">
                <span class="detail-label">Name:</span>
                <span class="detail-value">{{ selectedItem.data.name }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">UUID:</span>
                <span class="detail-value uuid-text">{{ selectedItem.data.uuid }}</span>
              </div>
              <div class="detail-row" v-if="selectedItem.data.created_at">
                <span class="detail-label">Created:</span>
                <span class="detail-value">{{ formatDateTime(selectedItem.data.created_at) }}</span>
              </div>
              <div class="detail-section" v-if="selectedItem.data.attributes && Object.keys(selectedItem.data.attributes).length > 0">
                <div class="section-title">Properties:</div>
                <div class="properties-list">
                  <div v-for="(value, key) in selectedItem.data.attributes" :key="key" class="property-item">
                    <span class="property-key">{{ key }}:</span>
                    <span class="property-value">{{ value || 'None' }}</span>
                  </div>
                </div>
              </div>
              <div class="detail-section" v-if="selectedItem.data.summary">
                <div class="section-title">Summary:</div>
                <div class="summary-text">{{ selectedItem.data.summary }}</div>
              </div>
              <div class="detail-section" v-if="selectedItem.data.labels?.length">
                <div class="section-title">Labels:</div>
                <div class="labels-list">
                  <span v-for="label in selectedItem.data.labels" :key="label" class="label-tag">{{ label }}</span>
                </div>
              </div>
            </template>
          </div>
          
          <!-- Edge Details -->
          <div v-else class="detail-content">
            <!-- Self-Loop Group Details -->
            <template v-if="selectedItem.data.isSelfLoopGroup">
              <div class="edge-relation-header self-loop-header">
                {{ selectedItem.data.source_name }} - Self Relations
                <span class="self-loop-count">{{ selectedItem.data.selfLoopCount }} items</span>
              </div>
              
              <div class="self-loop-list">
                <div 
                  v-for="(loop, idx) in selectedItem.data.selfLoopEdges" 
                  :key="loop.uuid || idx" 
                  class="self-loop-item"
                  :class="{ expanded: expandedSelfLoops.has(loop.uuid || idx) }"
                >
                  <div 
                    class="self-loop-item-header"
                    @click="toggleSelfLoop(loop.uuid || idx)"
                  >
                    <span class="self-loop-index">#{{ idx + 1 }}</span>
                    <span class="self-loop-name">{{ loop.name || loop.fact_type || 'RELATED' }}</span>
                    <span class="self-loop-toggle">{{ expandedSelfLoops.has(loop.uuid || idx) ? '−' : '+' }}</span>
                  </div>
                  
                  <div class="self-loop-item-content" v-show="expandedSelfLoops.has(loop.uuid || idx)">
                    <div class="detail-row" v-if="loop.uuid">
                      <span class="detail-label">UUID:</span>
                      <span class="detail-value uuid-text">{{ loop.uuid }}</span>
                    </div>
                    <div class="detail-row" v-if="loop.fact">
                      <span class="detail-label">Fact:</span>
                      <span class="detail-value fact-text">{{ loop.fact }}</span>
                    </div>
                    <div class="detail-row" v-if="loop.fact_type">
                      <span class="detail-label">Type:</span>
                      <span class="detail-value">{{ loop.fact_type }}</span>
                    </div>
                    <div class="detail-row" v-if="loop.created_at">
                      <span class="detail-label">Created:</span>
                      <span class="detail-value">{{ formatDateTime(loop.created_at) }}</span>
                    </div>
                    <div v-if="loop.episodes && loop.episodes.length > 0" class="self-loop-episodes">
                      <span class="detail-label">Episodes:</span>
                      <div class="episodes-list compact">
                        <span v-for="ep in loop.episodes" :key="ep" class="episode-tag small">{{ ep }}</span>
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </template>
            
            <!-- Regular Edge Details -->
            <template v-else>
              <div class="edge-relation-header">
                {{ selectedItem.data.source_name }} → {{ selectedItem.data.name || 'RELATED_TO' }} → {{ selectedItem.data.target_name }}
              </div>
              
              <div class="detail-row">
                <span class="detail-label">UUID:</span>
                <span class="detail-value uuid-text">{{ selectedItem.data.uuid }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Label:</span>
                <span class="detail-value">{{ selectedItem.data.name || 'RELATED_TO' }}</span>
              </div>
              <div class="detail-row">
                <span class="detail-label">Type:</span>
                <span class="detail-value">{{ selectedItem.data.fact_type || 'Unknown' }}</span>
              </div>
              <div class="detail-row" v-if="selectedItem.data.fact">
                <span class="detail-label">Fact:</span>
                <span class="detail-value fact-text">{{ selectedItem.data.fact }}</span>
              </div>
              
              <!-- Episodes -->
              <div class="detail-section" v-if="selectedItem.data.episodes && selectedItem.data.episodes.length > 0">
                <div class="section-title">Episodes:</div>
                <div class="episodes-list">
                  <span v-for="ep in selectedItem.data.episodes" :key="ep" class="episode-tag">
                    {{ ep }}
                  </span>
                </div>
              </div>
              
              <div class="detail-row" v-if="selectedItem.data.created_at">
                <span class="detail-label">Created:</span>
                <span class="detail-value">{{ formatDateTime(selectedItem.data.created_at) }}</span>
              </div>
              <div class="detail-row" v-if="selectedItem.data.valid_at">
                <span class="detail-label">Valid From:</span>
                <span class="detail-value">{{ formatDateTime(selectedItem.data.valid_at) }}</span>
              </div>
            </template>
          </div>
        </div>
      </div>
      
      <!-- Loading State -->
      <div v-else-if="loading" class="graph-state">
        <div class="loading-spinner"></div>
        <p>Loading graph data...</p>
      </div>

      <!-- Waiting/Empty State -->
      <div v-else class="graph-state">
        <div class="empty-icon">❖</div>
        <p class="empty-text">Waiting for ontology generation...</p>
      </div>
    </div>

    <!-- Bottom Legend (Bottom Left) -->
    <div v-if="graphData && entityTypes.length" class="graph-legend">
      <span class="legend-title">Entity Types</span>
      <div class="legend-items">
        <div class="legend-item" v-for="type in entityTypes" :key="type.name">
          <span class="legend-dot" :style="{ background: type.color }"></span>
          <span class="legend-label">{{ type.name }}</span>
        </div>
      </div>
    </div>
    
    <!-- Show Edge Labels Toggle -->
    <div v-if="graphData" class="edge-labels-toggle">
      <label class="toggle-switch">
        <input type="checkbox" v-model="showEdgeLabels" />
        <span class="slider"></span>
      </label>
      <span class="toggle-label">Show Edge Labels</span>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted, watch, nextTick, computed } from 'vue'
import * as d3 from 'd3'

const props = defineProps({
  graphData: Object,
  loading: Boolean,
  currentPhase: Number,
  isSimulating: Boolean,
  clustered: { type: Boolean, default: false },       // group-based cluster layout
  recentActions: { type: Array, default: () => [] },  // [{srcId, tgtId?, type}]
})

const emit = defineEmits(['refresh', 'toggle-maximize', 'node-click'])

const graphContainer = ref(null)
const graphSvg = ref(null)
const selectedItem = ref(null)
const showEdgeLabels = ref(!props.clustered) // Default off for clustered (large agent graphs)
const expandedSelfLoops = ref(new Set()) // Expanded self-loop items
const showSimulationFinishedHint = ref(false) // Simulation finished hint
const wasSimulating = ref(false) // Track whether was simulating before

// Dismiss simulation finished hint
const dismissFinishedHint = () => {
  showSimulationFinishedHint.value = false
}

// Watch isSimulating change, detect simulation end
watch(() => props.isSimulating, (newValue, oldValue) => {
  if (wasSimulating.value && !newValue) {
    // Changed from simulating to not simulating, show finished hint
    showSimulationFinishedHint.value = true
  }
  wasSimulating.value = newValue
}, { immediate: true })

// Toggle self-loop item expand/collapse state
const toggleSelfLoop = (id) => {
  const newSet = new Set(expandedSelfLoops.value)
  if (newSet.has(id)) {
    newSet.delete(id)
  } else {
    newSet.add(id)
  }
  expandedSelfLoops.value = newSet
}

// Calculate entity types for legend
const entityTypes = computed(() => {
  if (!props.graphData?.nodes) return []
  const typeMap = {}
  // Beautiful color palette
  const colors = ['#FF6B35', '#004E89', '#7B2D8E', '#1A936F', '#C5283D', '#E9724C', '#3498db', '#9b59b6', '#27ae60', '#f39c12']
  
  props.graphData.nodes.forEach(node => {
    const type = node.labels?.find(l => l !== 'Entity') || 'Entity'
    if (!typeMap[type]) {
      typeMap[type] = { name: type, count: 0, color: colors[Object.keys(typeMap).length % colors.length] }
    }
    typeMap[type].count++
  })
  return Object.values(typeMap)
})

// Format datetime
const formatDateTime = (dateStr) => {
  if (!dateStr) return ''
  try {
    const date = new Date(dateStr)
    return date.toLocaleString('en-US', { 
      month: 'short', 
      day: 'numeric', 
      year: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true 
    })
  } catch {
    return dateStr
  }
}

const closeDetailPanel = () => {
  selectedItem.value = null
  expandedSelfLoops.value = new Set()
}

// Returns inline style for the sentiment bar (centred at 50%)
const sentimentStyle = (bias) => {
  const pct  = Math.abs(bias) * 50        // 0–50 % wide
  const left = bias >= 0 ? '50%' : (50 - pct) + '%'
  const color = bias >= 0 ? '#4ade80' : '#f87171'
  return { left, width: pct + '%', background: color }
}

let currentSimulation = null
let linkLabelsRef = null
let linkLabelBgRef = null
let nodeByUuid = {}   // uuid → DOM circle element
let edgeByPair = {}   // "srcId_tgtId" → DOM path element
let svgG = null       // main <g> group for animation overlay

const renderGraph = () => {
  if (!graphSvg.value || !props.graphData) return

  // Stop previous simulation
  if (currentSimulation) {
    currentSimulation.stop()
  }
  
  const container = graphContainer.value
  const width = container.clientWidth
  const height = container.clientHeight
  
  const svg = d3.select(graphSvg.value)
    .attr('width', width)
    .attr('height', height)
    .attr('viewBox', `0 0 ${width} ${height}`)
    
  svg.selectAll('*').remove()
  
  const nodesData = props.graphData.nodes || []
  const edgesData = props.graphData.edges || []
  
  if (nodesData.length === 0) return

  // Prepare data
  const nodeMap = {}
  nodesData.forEach(n => nodeMap[n.uuid] = n)

  const nodes = nodesData.map(n => ({
    id: n.uuid,
    name: n.name || 'Unnamed',
    type: n.labels?.find(l => l !== 'Entity') || 'Entity',
    rawData: n
  }))

  const nodeIds = new Set(nodes.map(n => n.id))

  // Process edge data, calculate edge count and index between same pair of nodes
  const edgePairCount = {}
  const selfLoopEdges = {} // Self-loop edges grouped by node
  const tempEdges = edgesData
    .filter(e => nodeIds.has(e.source_node_uuid) && nodeIds.has(e.target_node_uuid))

  // Count edges between each pair of nodes, collect self-loop edges
  tempEdges.forEach(e => {
    if (e.source_node_uuid === e.target_node_uuid) {
      // Self-loop - collect into array
      if (!selfLoopEdges[e.source_node_uuid]) {
        selfLoopEdges[e.source_node_uuid] = []
      }
      selfLoopEdges[e.source_node_uuid].push({
        ...e,
        source_name: nodeMap[e.source_node_uuid]?.name,
        target_name: nodeMap[e.target_node_uuid]?.name
      })
    } else {
      const pairKey = [e.source_node_uuid, e.target_node_uuid].sort().join('_')
      edgePairCount[pairKey] = (edgePairCount[pairKey] || 0) + 1
    }
  })

  // Record which edge index we're at for each pair of nodes
  const edgePairIndex = {}
  const processedSelfLoopNodes = new Set() // Processed self-loop nodes
  
  const edges = []
  
  tempEdges.forEach(e => {
    const isSelfLoop = e.source_node_uuid === e.target_node_uuid

    if (isSelfLoop) {
      // Self-loop edge - add only one merged self-loop per node
      if (processedSelfLoopNodes.has(e.source_node_uuid)) {
        return // Already processed, skip
      }
      processedSelfLoopNodes.add(e.source_node_uuid)
      
      const allSelfLoops = selfLoopEdges[e.source_node_uuid]
      const nodeName = nodeMap[e.source_node_uuid]?.name || 'Unknown'
      
      edges.push({
        source: e.source_node_uuid,
        target: e.target_node_uuid,
        type: 'SELF_LOOP',
        name: `Self Relations (${allSelfLoops.length})`,
        curvature: 0,
        isSelfLoop: true,
        rawData: {
          isSelfLoopGroup: true,
          source_name: nodeName,
          target_name: nodeName,
          selfLoopCount: allSelfLoops.length,
          selfLoopEdges: allSelfLoops // Store detailed information of all self-loop edges
        }
      })
      return
    }
    
    const pairKey = [e.source_node_uuid, e.target_node_uuid].sort().join('_')
    const totalCount = edgePairCount[pairKey]
    const currentIndex = edgePairIndex[pairKey] || 0
    edgePairIndex[pairKey] = currentIndex + 1

    // Check if edge direction matches normalized direction (source UUID < target UUID)
    const isReversed = e.source_node_uuid > e.target_node_uuid

    // Calculate curvature: spread out when multiple edges, straight when single
    let curvature = 0
    if (totalCount > 1) {
      // Evenly distribute curvature to ensure clear distinction
      // Curvature range increases with edge count
      const curvatureRange = Math.min(1.2, 0.6 + totalCount * 0.15)
      curvature = ((currentIndex / (totalCount - 1)) - 0.5) * curvatureRange * 2

      // If edge direction is opposite to normalized direction, flip curvature
      // This ensures all edges distribute in same reference frame, no overlap from direction difference
      if (isReversed) {
        curvature = -curvature
      }
    }
    
    edges.push({
      source: e.source_node_uuid,
      target: e.target_node_uuid,
      type: e.fact_type || e.name || 'RELATED',
      name: e.name || e.fact_type || 'RELATED',
      curvature,
      isSelfLoop: false,
      pairIndex: currentIndex,
      pairTotal: totalCount,
      rawData: {
        ...e,
        source_name: nodeMap[e.source_node_uuid]?.name,
        target_name: nodeMap[e.target_node_uuid]?.name,
        fact_type: e.fact_type || e.relationship_type || e.type || null,
        uuid: e.uuid || e.id || null,
      }
    })
  })
    
  // Color scale
  const colorMap = {}
  entityTypes.value.forEach(t => colorMap[t.name] = t.color)
  const getColor = (type) => colorMap[type] || '#999'

  // Pre-position nodes near their cluster center so they settle faster
  if (props.clustered) {
    const groupNames = [...new Set(nodes.map(n => n.type))]
    const clusterRadius = Math.min(width, height) * 0.30
    const _centers = {}
    groupNames.forEach((g, i) => {
      const angle = (2 * Math.PI * i) / groupNames.length - Math.PI / 2
      _centers[g] = {
        x: width / 2 + clusterRadius * Math.cos(angle),
        y: height / 2 + clusterRadius * Math.sin(angle),
      }
    })
    nodes.forEach(n => {
      const c = _centers[n.type]
      if (c) { n.x = c.x + (Math.random() - 0.5) * 50; n.y = c.y + (Math.random() - 0.5) * 50 }
    })
  }

  const simulation = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(edges).id(d => d.id).distance(d => {
      const base = props.clustered ? 60 : 150
      return base + ((d.pairTotal || 1) - 1) * 30
    }))
    .force('charge', d3.forceManyBody().strength(props.clustered ? -150 : -400))
    .force('center', d3.forceCenter(width / 2, height / 2))
    .force('collide', d3.forceCollide(props.clustered ? 18 : 50))

  if (props.clustered) {
    // Pull each node toward its group center
    const groupNames = [...new Set(nodes.map(n => n.type))]
    const clusterRadius = Math.min(width, height) * 0.30
    const groupCenters = {}
    groupNames.forEach((g, i) => {
      const angle = (2 * Math.PI * i) / groupNames.length - Math.PI / 2
      groupCenters[g] = {
        x: width / 2 + clusterRadius * Math.cos(angle),
        y: height / 2 + clusterRadius * Math.sin(angle),
      }
    })
    simulation.force('cluster', (alpha) => {
      for (const n of nodes) {
        const c = groupCenters[n.type]
        if (!c) continue
        n.vx -= (n.x - c.x) * 0.12 * alpha
        n.vy -= (n.y - c.y) * 0.12 * alpha
      }
    })
  } else {
    simulation
      .force('x', d3.forceX(width / 2).strength(0.04))
      .force('y', d3.forceY(height / 2).strength(0.04))
  }
  
  currentSimulation = simulation

  const g = svg.append('g')
  svgG = g.node()

  // Zoom
  svg.call(d3.zoom().extent([[0, 0], [width, height]]).scaleExtent([0.1, 4]).on('zoom', (event) => {
    g.attr('transform', event.transform)
  }))

  // Links - use path to support curves
  const linkGroup = g.append('g').attr('class', 'links')

  // Calculate curve path
  const getLinkPath = (d) => {
    const sx = d.source.x, sy = d.source.y
    const tx = d.target.x, ty = d.target.y

    // Detect self-loop
    if (d.isSelfLoop) {
      // Self-loop: draw an arc from node and back
      const loopRadius = 30
      // Start from node's right side, circle around and back
      const x1 = sx + 8  // Start offset
      const y1 = sy - 4
      const x2 = sx + 8  // End offset
      const y2 = sy + 4
      // Use arc to draw self-loop (sweep-flag=1 clockwise)
      return `M${x1},${y1} A${loopRadius},${loopRadius} 0 1,1 ${x2},${y2}`
    }

    if (d.curvature === 0) {
      // Straight line
      return `M${sx},${sy} L${tx},${ty}`
    }

    // Calculate curve control point - dynamically adjust based on edge count and distance
    const dx = tx - sx, dy = ty - sy
    const dist = Math.sqrt(dx * dx + dy * dy)
    // Offset perpendicular to connection direction, calculated by distance ratio to ensure visible curve
    // More edges means larger offset proportion
    const pairTotal = d.pairTotal || 1
    const offsetRatio = 0.25 + pairTotal * 0.05 // Base 25%, add 5% per additional edge
    const baseOffset = Math.max(35, dist * offsetRatio)
    const offsetX = -dy / dist * d.curvature * baseOffset
    const offsetY = dx / dist * d.curvature * baseOffset
    const cx = (sx + tx) / 2 + offsetX
    const cy = (sy + ty) / 2 + offsetY

    return `M${sx},${sy} Q${cx},${cy} ${tx},${ty}`
  }

  // Calculate curve midpoint (for label positioning)
  const getLinkMidpoint = (d) => {
    const sx = d.source.x, sy = d.source.y
    const tx = d.target.x, ty = d.target.y

    // Detect self-loop
    if (d.isSelfLoop) {
      // Self-loop label position: right side of node
      return { x: sx + 70, y: sy }
    }
    
    if (d.curvature === 0) {
      return { x: (sx + tx) / 2, y: (sy + ty) / 2 }
    }

    // Quadratic Bezier curve midpoint t=0.5
    const dx = tx - sx, dy = ty - sy
    const dist = Math.sqrt(dx * dx + dy * dy)
    const pairTotal = d.pairTotal || 1
    const offsetRatio = 0.25 + pairTotal * 0.05
    const baseOffset = Math.max(35, dist * offsetRatio)
    const offsetX = -dy / dist * d.curvature * baseOffset
    const offsetY = dx / dist * d.curvature * baseOffset
    const cx = (sx + tx) / 2 + offsetX
    const cy = (sy + ty) / 2 + offsetY

    // Quadratic Bezier curve formula B(t) = (1-t)²P0 + 2(1-t)tP1 + t²P2, t=0.5
    const midX = 0.25 * sx + 0.5 * cx + 0.25 * tx
    const midY = 0.25 * sy + 0.5 * cy + 0.25 * ty

    return { x: midX, y: midY }
  }

  const link = linkGroup.selectAll('path')
    .data(edges)
    .enter().append('path')
    .attr('stroke', '#2e2e42')
    .attr('stroke-width', 1.5)
    .attr('fill', 'none')
    .style('cursor', 'pointer')
    .on('click', (event, d) => {
      event.stopPropagation()
      // Reset previous selected edge style
      linkGroup.selectAll('path').attr('stroke', '#2e2e42').attr('stroke-width', 1.5)
      linkLabelBg.attr('fill', 'rgba(26,26,46,0.95)')
      linkLabels.attr('fill', '#888')
      // Highlight currently selected edge
      d3.select(event.target).attr('stroke', '#3498db').attr('stroke-width', 3)

      selectedItem.value = {
        type: 'edge',
        data: d.rawData
      }
    })

  // Link labels background (white background for clearer text)
  const linkLabelBg = linkGroup.selectAll('rect')
    .data(edges)
    .enter().append('rect')
    .attr('fill', 'rgba(26,26,46,0.95)')
    .attr('rx', 3)
    .attr('ry', 3)
    .style('cursor', 'pointer')
    .style('pointer-events', 'all')
    .style('display', showEdgeLabels.value ? 'block' : 'none')
    .on('click', (event, d) => {
      event.stopPropagation()
      linkGroup.selectAll('path').attr('stroke', '#2e2e42').attr('stroke-width', 1.5)
      linkLabelBg.attr('fill', 'rgba(26,26,46,0.95)')
      linkLabels.attr('fill', '#888')
      // Highlight corresponding edge
      link.filter(l => l === d).attr('stroke', '#3498db').attr('stroke-width', 3)
      d3.select(event.target).attr('fill', 'rgba(52, 152, 219, 0.1)')

      selectedItem.value = {
        type: 'edge',
        data: d.rawData
      }
    })

  // Link labels
  const linkLabels = linkGroup.selectAll('text')
    .data(edges)
    .enter().append('text')
    .text(d => d.name)
    .attr('font-size', '9px')
    .attr('fill', '#888')
    .attr('text-anchor', 'middle')
    .attr('dominant-baseline', 'middle')
    .style('cursor', 'pointer')
    .style('pointer-events', 'all')
    .style('font-family', 'system-ui, sans-serif')
    .style('display', showEdgeLabels.value ? 'block' : 'none')
    .on('click', (event, d) => {
      event.stopPropagation()
      linkGroup.selectAll('path').attr('stroke', '#2e2e42').attr('stroke-width', 1.5)
      linkLabelBg.attr('fill', 'rgba(26,26,46,0.95)')
      linkLabels.attr('fill', '#888')
      // Highlight corresponding edge
      link.filter(l => l === d).attr('stroke', '#3498db').attr('stroke-width', 3)
      d3.select(event.target).attr('fill', '#3498db')

      selectedItem.value = {
        type: 'edge',
        data: d.rawData
      }
    })

  // Save references for external control of visibility
  linkLabelsRef = linkLabels
  linkLabelBgRef = linkLabelBg

  // Pre-cache bbox for each label once (getBBox in tick is extremely expensive)
  const edgeLabelMeta = []
  linkLabels.each(function() {
    const bbox = this.getBBox()
    edgeLabelMeta.push({ w: bbox.width, h: bbox.height })
  })

  // Build edge lookup for animation
  edgeByPair = {}
  link.each(function(d) {
    edgeByPair[`${d.source.id}_${d.target.id}`] = this
    edgeByPair[`${d.target.id}_${d.source.id}`] = this
  })

  // Nodes group
  const nodeGroup = g.append('g').attr('class', 'nodes')

  // Node circles
  const node = nodeGroup.selectAll('circle')
    .data(nodes)
    .enter().append('circle')
    .attr('r', 10)
    .attr('fill', d => getColor(d.type))
    .attr('stroke', '#1a1a2e')
    .attr('stroke-width', 2.5)
    .style('cursor', 'pointer')
    .call(d3.drag()
      .on('start', (event, d) => {
        // Only record position, don't restart simulation (distinguish click from drag)
        d.fx = d.x
        d.fy = d.y
        d._dragStartX = event.x
        d._dragStartY = event.y
        d._isDragging = false
      })
      .on('drag', (event, d) => {
        // Check if truly dragging (moved beyond threshold)
        const dx = event.x - d._dragStartX
        const dy = event.y - d._dragStartY
        const distance = Math.sqrt(dx * dx + dy * dy)

        if (!d._isDragging && distance > 3) {
          // First time detecting true drag, restart simulation
          d._isDragging = true
          simulation.alphaTarget(0.3).restart()
        }

        if (d._isDragging) {
          d.fx = event.x
          d.fy = event.y
        }
      })
      .on('end', (event, d) => {
        // Only stop simulation gradually if truly dragged
        if (d._isDragging) {
          simulation.alphaTarget(0)
        }
        d.fx = null
        d.fy = null
        d._isDragging = false
      })
    )
    .on('click', (event, d) => {
      event.stopPropagation()
      // Reset all node styles
      node.attr('stroke', '#1a1a2e').attr('stroke-width', 2.5)
      linkGroup.selectAll('path').attr('stroke', '#2e2e42').attr('stroke-width', 1.5)
      // Highlight selected node
      d3.select(event.target).attr('stroke', '#E91E63').attr('stroke-width', 4)
      // Highlight edges connected to this node
      link.filter(l => l.source.id === d.id || l.target.id === d.id)
        .attr('stroke', '#E91E63')
        .attr('stroke-width', 2.5)

      selectedItem.value = {
        type: 'node',
        data: d.rawData,
        entityType: d.type,
        color: getColor(d.type)
      }
      emit('node-click', { name: d.rawData.name, uuid: d.rawData.uuid, entityType: d.type })
    })
    .on('mouseenter', (event, d) => {
      if (!selectedItem.value || selectedItem.value.data?.uuid !== d.rawData.uuid) {
        d3.select(event.target).attr('stroke', '#333').attr('stroke-width', 3)
      }
    })
    .on('mouseleave', (event, d) => {
      if (!selectedItem.value || selectedItem.value.data?.uuid !== d.rawData.uuid) {
        d3.select(event.target).attr('stroke', '#1a1a2e').attr('stroke-width', 2.5)
      }
    })

  // Build node lookup for animation
  nodeByUuid = {}
  node.each(function(d) { nodeByUuid[d.id] = this })

  // Node Labels
  const nodeLabels = nodeGroup.selectAll('text')
    .data(nodes)
    .enter().append('text')
    .text(d => d.name.length > 8 ? d.name.substring(0, 8) + '…' : d.name)
    .attr('font-size', '11px')
    .attr('fill', '#ccc')
    .attr('font-weight', '500')
    .attr('dx', 14)
    .attr('dy', 4)
    .style('pointer-events', 'none')
    .style('font-family', 'system-ui, sans-serif')

  simulation.on('tick', () => {
    // Update curve paths
    link.attr('d', d => getLinkPath(d))

    // Only update label positions when visible (getBBox in tick is extremely expensive)
    if (showEdgeLabels.value) {
      linkLabels.each(function(d) {
        const mid = getLinkMidpoint(d)
        d3.select(this).attr('x', mid.x).attr('y', mid.y)
      })

      // Use pre-cached bbox dimensions — never call getBBox per tick
      linkLabelBg.each(function(d, i) {
        const mid = getLinkMidpoint(d)
        const meta = edgeLabelMeta[i]
        if (!meta) return
        d3.select(this)
          .attr('x', mid.x - meta.w / 2 - 4)
          .attr('y', mid.y - meta.h / 2 - 2)
          .attr('width', meta.w + 8)
          .attr('height', meta.h + 4)
      })
    }

    node
      .attr('cx', d => d.x)
      .attr('cy', d => d.y)

    nodeLabels
      .attr('x', d => d.x)
      .attr('y', d => d.y)
  })

  // Click on blank area to close detail panel
  svg.on('click', () => {
    selectedItem.value = null
    node.attr('stroke', '#1a1a2e').attr('stroke-width', 2.5)
    linkGroup.selectAll('path').attr('stroke', '#2e2e42').attr('stroke-width', 1.5)
    linkLabelBg.attr('fill', 'rgba(26,26,46,0.95)')
    linkLabels.attr('fill', '#888')
  })
}

// ── Message animation ────────────────────────────────────────────────────────

function pulseNode(uuid) {
  const el = nodeByUuid[uuid]
  if (!el) return
  d3.select(el)
    .transition().duration(120).attr('r', 20)
    .transition().duration(500).ease(d3.easeElasticOut).attr('r', 10)
}

function pulseNodeSoft(uuid) {
  const el = nodeByUuid[uuid]
  if (!el) return
  d3.select(el)
    .transition().duration(200).attr('r', 15)
    .transition().duration(400).ease(d3.easeElasticOut).attr('r', 10)
}

function animateDot(srcId, tgtId, color = '#ff9f4a') {
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
      .attr('stroke', color)
      .attr('stroke-width', 1.5)
      .attr('fill', 'none')
      .attr('opacity', 0.6)
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
    .attr('fill', color)
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

watch(() => props.graphData, () => {
  nextTick(renderGraph)
}, { deep: true })

// Watch edge label show/hide toggle
watch(showEdgeLabels, (newVal) => {
  if (linkLabelsRef) {
    linkLabelsRef.style('display', newVal ? 'block' : 'none')
  }
  if (linkLabelBgRef) {
    linkLabelBgRef.style('display', newVal ? 'block' : 'none')
  }
})

const handleResize = () => {
  nextTick(renderGraph)
}

onMounted(() => {
  window.addEventListener('resize', handleResize)
})

onUnmounted(() => {
  window.removeEventListener('resize', handleResize)
  if (currentSimulation) {
    currentSimulation.stop()
  }
})
</script>

<style scoped>
.graph-panel {
  position: relative;
  width: 100%;
  height: 100%;
  background-color: #13131f;
  background-image: radial-gradient(#2a2a3e 1.5px, transparent 1.5px);
  background-size: 24px 24px;
  overflow: hidden;
}

.panel-header {
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  padding: 16px 20px;
  z-index: 10;
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: linear-gradient(to bottom, rgba(19,19,31,0.95), rgba(19,19,31,0));
  pointer-events: none;
}

.panel-title {
  font-size: 14px;
  font-weight: 600;
  color: #e0e0e0;
  pointer-events: auto;
}

.header-tools {
  pointer-events: auto;
  display: flex;
  gap: 10px;
  align-items: center;
}

.tool-btn {
  height: 32px;
  padding: 0 12px;
  border: 1px solid #2e2e42;
  background: #1a1a2e;
  border-radius: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  cursor: pointer;
  color: #888;
  transition: all 0.2s;
  box-shadow: 0 2px 4px rgba(0,0,0,0.2);
  font-size: 13px;
}

.tool-btn:hover {
  background: #2a2a3e;
  color: #e0e0e0;
  border-color: #3e3e56;
}

.tool-btn .btn-text {
  font-size: 12px;
}

.icon-refresh.spinning {
  animation: spin 1s linear infinite;
}

@keyframes spin { from { transform: rotate(0deg); } to { transform: rotate(360deg); } }

.graph-container {
  width: 100%;
  height: 100%;
}

.graph-view, .graph-svg {
  width: 100%;
  height: 100%;
  display: block;
}

.graph-state {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  text-align: center;
  color: #555;
}

.empty-icon {
  font-size: 48px;
  margin-bottom: 16px;
  opacity: 0.2;
}

/* Entity Types Legend - Bottom Left */
.graph-legend {
  position: absolute;
  bottom: 24px;
  left: 24px;
  background: rgba(19,19,31,0.95);
  padding: 12px 16px;
  border-radius: 8px;
  border: 1px solid #2e2e42;
  box-shadow: 0 4px 16px rgba(0,0,0,0.4);
  z-index: 10;
}

.legend-title {
  display: block;
  font-size: 11px;
  font-weight: 600;
  color: #E91E63;
  margin-bottom: 10px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.legend-items {
  display: flex;
  flex-wrap: wrap;
  gap: 10px 16px;
  max-width: 320px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 12px;
  color: #888;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  flex-shrink: 0;
}

.legend-label {
  white-space: nowrap;
}

/* ── Agent card styles ──────────────────────────────────────────────────── */
.agent-identity {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 16px 10px;
  border-bottom: 1px solid #2e2e42;
}
.agent-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
}
.agent-identity-text { display: flex; flex-direction: column; gap: 2px; }
.agent-username { font-size: 14px; font-weight: 700; color: #e0e0e0; }
.agent-fullname { font-size: 11px; color: #888; }

.agent-section {
  padding: 10px 16px;
  border-bottom: 1px solid #2e2e42;
}
.agent-section:last-child { border-bottom: none; }
.group-section { background: #0f0f1a; }

.agent-section-title {
  font-size: 10px;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #aaa;
  margin-bottom: 6px;
}

.agent-prose {
  font-size: 12px;
  color: #ccc;
  line-height: 1.55;
}
.agent-prose.small { font-size: 11px; }
.agent-prose.muted { color: #888; }

.agent-facts-grid {
  display: flex;
  flex-wrap: wrap;
  gap: 6px 12px;
}
.agent-fact {
  display: flex;
  gap: 4px;
  font-size: 11px;
}
.fact-k { color: #aaa; }
.fact-v { color: #e0e0e0; font-weight: 600; }

.agent-topics {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  margin-top: 6px;
}
.topic-tag {
  background: #1a1a2e;
  color: #888;
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 20px;
}

.agent-bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-top: 7px;
  font-size: 11px;
}
.bar-label { color: #aaa; width: 60px; flex-shrink: 0; }
.bar-track {
  flex: 1;
  height: 6px;
  background: #2e2e42;
  border-radius: 3px;
  overflow: hidden;
}
.bar-fill { height: 100%; border-radius: 3px; transition: width 0.3s; }
.bar-fill.activity { background: #e8642a; }
.sentiment-track { position: relative; overflow: visible; }
.bar-fill.sentiment { position: absolute; top: 0; height: 100%; border-radius: 2px; min-width: 3px; }
.bar-val { color: #888; font-weight: 600; min-width: 32px; text-align: right; }

.schedule-badge {
  background: #1a1a2e;
  color: #e8c77a;
  font-size: 10px;
  font-weight: 600;
  padding: 2px 8px;
  border-radius: 3px;
  letter-spacing: 0.04em;
}
.target-tag {
  background: #fff0e8;
  color: #c0440f;
  font-size: 10px;
  padding: 2px 7px;
  border-radius: 3px;
  border: 1px solid #f5c9b0;
}
/* ── end agent card styles ─────────────────────────────────────────────── */

/* Edge Labels Toggle - Top Right */
.edge-labels-toggle {
  position: absolute;
  top: 60px;
  right: 20px;
  display: flex;
  align-items: center;
  gap: 10px;
  background: #1a1a2e;
  padding: 8px 14px;
  border-radius: 20px;
  border: 1px solid #2e2e42;
  box-shadow: 0 2px 8px rgba(0,0,0,0.3);
  z-index: 10;
}

.toggle-switch {
  position: relative;
  display: inline-block;
  width: 40px;
  height: 22px;
}

.toggle-switch input {
  opacity: 0;
  width: 0;
  height: 0;
}

.slider {
  position: absolute;
  cursor: pointer;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background-color: #E0E0E0;
  border-radius: 22px;
  transition: 0.3s;
}

.slider:before {
  position: absolute;
  content: "";
  height: 16px;
  width: 16px;
  left: 3px;
  bottom: 3px;
  background-color: white;
  border-radius: 50%;
  transition: 0.3s;
}

input:checked + .slider {
  background-color: #7B2D8E;
}

input:checked + .slider:before {
  transform: translateX(18px);
}

.toggle-label {
  font-size: 12px;
  color: #888;
}

/* Detail Panel - Right Side */
.detail-panel {
  position: absolute;
  top: 60px;
  right: 20px;
  width: 360px;
  max-height: calc(100% - 100px);
  background: #1a1a2e;
  border: 1px solid #2e2e42;
  border-radius: 10px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.5);
  overflow: hidden;
  font-family: 'Noto Sans SC', system-ui, sans-serif;
  font-size: 13px;
  z-index: 20;
  display: flex;
  flex-direction: column;
}

.detail-panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 14px 16px;
  background: #13131f;
  border-bottom: 1px solid #2e2e42;
  flex-shrink: 0;
}

.detail-title {
  font-weight: 600;
  color: #e0e0e0;
  font-size: 14px;
}

.detail-type-badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 11px;
  font-weight: 500;
  margin-left: auto;
  margin-right: 12px;
}

.detail-close {
  background: none;
  border: none;
  font-size: 20px;
  cursor: pointer;
  color: #888;
  line-height: 1;
  padding: 0;
  transition: color 0.2s;
}

.detail-close:hover {
  color: #e0e0e0;
}

.detail-content {
  padding: 16px;
  overflow-y: auto;
  flex: 1;
}

.detail-row {
  margin-bottom: 12px;
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.detail-label {
  color: #888;
  font-size: 12px;
  font-weight: 500;
  min-width: 80px;
}

.detail-value {
  color: #e0e0e0;
  flex: 1;
  word-break: break-word;
}

.detail-value.uuid-text {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #888;
}

.detail-value.fact-text {
  line-height: 1.5;
  color: #ccc;
}

.detail-section {
  margin-top: 16px;
  padding-top: 14px;
  border-top: 1px solid #2e2e42;
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: #888;
  margin-bottom: 10px;
}

.properties-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.property-item {
  display: flex;
  gap: 8px;
}

.property-key {
  color: #888;
  font-weight: 500;
  min-width: 90px;
}

.property-value {
  color: #e0e0e0;
  flex: 1;
}

.summary-text {
  line-height: 1.6;
  color: #ccc;
  font-size: 12px;
}

.labels-list {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.label-tag {
  display: inline-block;
  padding: 4px 12px;
  background: #1a1a2e;
  border: 1px solid #2e2e42;
  border-radius: 16px;
  font-size: 11px;
  color: #888;
}

.episodes-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.episode-tag {
  display: inline-block;
  padding: 6px 10px;
  background: #1a1a2e;
  border: 1px solid #2e2e42;
  border-radius: 6px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 10px;
  color: #888;
  word-break: break-all;
}

/* Edge relation header */
.edge-relation-header {
  background: #13131f;
  padding: 12px;
  border-radius: 8px;
  margin-bottom: 16px;
  font-size: 13px;
  font-weight: 500;
  color: #ccc;
  line-height: 1.5;
  word-break: break-word;
}

/* Building hint */
.graph-building-hint {
  position: absolute;
  bottom: 160px; /* Moved up from 80px */
  left: 50%;
  transform: translateX(-50%);
  background: rgba(0, 0, 0, 0.65);
  backdrop-filter: blur(8px);
  color: #fff;
  padding: 10px 20px;
  border-radius: 30px;
  font-size: 13px;
  display: flex;
  align-items: center;
  gap: 10px;
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.15);
  border: 1px solid rgba(255, 255, 255, 0.1);
  font-weight: 500;
  letter-spacing: 0.5px;
  z-index: 100;
}

.memory-icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
  animation: breathe 2s ease-in-out infinite;
}

.memory-icon {
  width: 18px;
  height: 18px;
  color: #4CAF50;
}

@keyframes breathe {
  0%, 100% { opacity: 0.7; transform: scale(1); filter: drop-shadow(0 0 2px rgba(76, 175, 80, 0.3)); }
  50% { opacity: 1; transform: scale(1.15); filter: drop-shadow(0 0 8px rgba(76, 175, 80, 0.6)); }
}

/* Simulation finished hint style */
.graph-building-hint.finished-hint {
  background: rgba(0, 0, 0, 0.65);
  border: 1px solid rgba(255, 255, 255, 0.1);
}

.finished-hint .hint-icon-wrapper {
  display: flex;
  align-items: center;
  justify-content: center;
}

.finished-hint .hint-icon {
  width: 18px;
  height: 18px;
  color: #FFF;
}

.finished-hint .hint-text {
  flex: 1;
  white-space: nowrap;
}

.hint-close-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 22px;
  height: 22px;
  background: rgba(255, 255, 255, 0.2);
  border: none;
  border-radius: 50%;
  cursor: pointer;
  color: #FFF;
  transition: all 0.2s;
  margin-left: 8px;
  flex-shrink: 0;
}

.hint-close-btn:hover {
  background: rgba(255, 255, 255, 0.35);
  transform: scale(1.1);
}

/* Loading spinner */
.loading-spinner {
  width: 40px;
  height: 40px;
  border: 3px solid #2e2e42;
  border-top-color: #7B2D8E;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 16px;
}

/* Self-loop styles */
.self-loop-header {
  display: flex;
  align-items: center;
  gap: 8px;
  background: linear-gradient(135deg, #0f1a12 0%, #0f1a10 100%);
  border: 1px solid #1a3a1e;
}

.self-loop-count {
  margin-left: auto;
  font-size: 11px;
  color: #888;
  background: rgba(26,26,46,0.8);
  padding: 2px 8px;
  border-radius: 10px;
}

.self-loop-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.self-loop-item {
  background: #13131f;
  border: 1px solid #2e2e42;
  border-radius: 8px;
}

.self-loop-item-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 12px;
  background: #1a1a2e;
  cursor: pointer;
  transition: background 0.2s;
}

.self-loop-item-header:hover {
  background: #2a2a3e;
}

.self-loop-item.expanded .self-loop-item-header {
  background: #2a2a3e;
}

.self-loop-index {
  font-size: 10px;
  font-weight: 600;
  color: #888;
  background: #2e2e42;
  padding: 2px 6px;
  border-radius: 4px;
}

.self-loop-name {
  font-size: 12px;
  font-weight: 500;
  color: #ccc;
  flex: 1;
}

.self-loop-toggle {
  width: 20px;
  height: 20px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 14px;
  font-weight: 600;
  color: #888;
  background: #2e2e42;
  border-radius: 4px;
  transition: all 0.2s;
}

.self-loop-item.expanded .self-loop-toggle {
  background: #3e3e56;
  color: #ccc;
}

.self-loop-item-content {
  padding: 12px;
  border-top: 1px solid #2e2e42;
}

.self-loop-item-content .detail-row {
  margin-bottom: 8px;
}

.self-loop-item-content .detail-label {
  font-size: 11px;
  min-width: 60px;
}

.self-loop-item-content .detail-value {
  font-size: 12px;
}

.self-loop-episodes {
  margin-top: 8px;
}

.episodes-list.compact {
  flex-direction: row;
  flex-wrap: wrap;
  gap: 4px;
}

.episode-tag.small {
  padding: 3px 6px;
  font-size: 9px;
}
</style>
