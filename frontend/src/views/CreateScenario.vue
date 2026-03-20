<template>
  <div :style="s.page">
    <!-- Navigation bar -->
    <nav :style="s.navbar">
      <div :style="s.navBrand">MIROFISH OFFLINE</div>
      <div :style="s.navRight">
        <span :style="s.navTag">Azure OpenAI · Multi-Agent Simulation</span>
        <a href="https://github.com/nikmcfly/MiroFish-Offline" target="_blank" :style="s.githubLink">
          GitHub ↗
        </a>
      </div>
    </nav>

    <!-- Main content -->
    <div :style="s.body">

      <!-- ── Phase: input ─────────────────────────────────────────── -->
      <div v-if="phase === 'input'" :style="s.inputPhase">
        <div :style="s.heading">
          <h1 :style="s.h1">Describe your scenario</h1>
          <p :style="s.subheading">
            Specify agent groups, counts, behaviors and platform.
            MiroFish uses Azure OpenAI to parse your description, generate realistic personas,
            and build a full simulation config — no documents required.
          </p>
        </div>

        <div :style="s.card">
          <textarea
            v-model="description"
            :placeholder="placeholder"
            :disabled="parsing"
            :style="s.textarea"
          />

          <div v-if="errorMsg" :style="s.errorBanner">
            {{ errorMsg }}
            <button :style="s.errorClose" @click="errorMsg = ''">×</button>
          </div>

          <div :style="s.cardFooter">
            <span :style="s.charCount">{{ description.length }} characters</span>
            <button
              :disabled="parsing || !description.trim()"
              :style="[s.parseBtn, (parsing || !description.trim()) ? s.btnDisabled : {}]"
              @click="doParse"
            >
              <span v-if="parsing">Parsing…</span>
              <span v-else>Parse Scenario →</span>
            </button>
          </div>
        </div>

        <!-- Hint row -->
        <div :style="s.hints">
          <div v-for="h in hints" :key="h.label" :style="s.hintItem">
            <span :style="s.hintIcon">{{ h.icon }}</span>
            <div>
              <div :style="s.hintLabel">{{ h.label }}</div>
              <div :style="s.hintDesc">{{ h.desc }}</div>
            </div>
          </div>
        </div>

        <!-- Past simulations -->
        <div v-if="pastSimulations.length" :style="s.pastSection">
          <div :style="s.pastHeading">Recent simulations</div>
          <div :style="s.pastList">
            <div
              v-for="sim in pastSimulations"
              :key="sim.simulation_id"
              :style="s.pastItem"
              @click="openSimulation(sim)"
            >
              <div :style="s.pastLeft">
                <div :style="s.pastTitle">{{ simTitle(sim) }}</div>
                <div :style="s.pastMeta">{{ sim.simulation_id }} · {{ sim.total_agents || 0 }} agents</div>
              </div>
              <div :style="s.pastRight">
                <span :style="[s.pastStatus, { color: simStatusColor(sim.status) }]">{{ sim.status }}</span>
                <span :style="s.pastAge">{{ simAge(sim.created_at) }}</span>
                <button
                  :style="[s.deleteBtn, deletingId === sim.simulation_id ? s.deleteBtnSpinning : (hoveredDeleteId === sim.simulation_id ? s.deleteBtnHover : null)]"
                  :disabled="deletingId === sim.simulation_id"
                  @click="removeSimulation(sim, $event)"
                  @mouseenter="hoveredDeleteId = sim.simulation_id"
                  @mouseleave="hoveredDeleteId = null"
                  title="Delete simulation"
                >
                  <svg v-if="deletingId !== sim.simulation_id" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <polyline points="3 6 5 6 21 6"/>
                    <path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>
                  </svg>
                  <span v-else style="font-size:11px;line-height:1">···</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- ── Phase: preview ───────────────────────────────────────── -->
      <div v-else-if="phase === 'preview'" :style="s.previewPhase">
        <div :style="s.previewHeader">
          <div>
            <h2 :style="s.h2">Parsed groups</h2>
            <p :style="s.subheading">Confirm the agent groups before generating profiles.</p>
          </div>
          <button :style="s.editBtn" @click="phase = 'input'">← Edit description</button>
        </div>

        <div v-if="errorMsg" :style="s.errorBanner">
          {{ errorMsg }}
          <button :style="s.errorClose" @click="errorMsg = ''">×</button>
        </div>

        <GroupsPreview
          :scenario="parsedScenario"
          :generating="generating"
          @edit="phase = 'input'"
          @generate="doGenerate"
        />
      </div>

      <!-- ── Phase: generating ────────────────────────────────────── -->
      <div v-else-if="phase === 'generating'" :style="s.progressPhase">
        <h2 :style="s.h2">Generating agents</h2>
        <p :style="s.subheading">
          Profiles are being created in parallel. This usually takes 1–3 minutes.
        </p>

        <div v-if="errorMsg" :style="s.errorBanner">
          {{ errorMsg }}
          <button :style="s.errorClose" @click="errorMsg = ''">×</button>
        </div>

        <div :style="s.card">
          <ProfileGenerationProgress
            :simulation-id="simulationId"
            :total-agents="parsedScenario ? parsedScenario.total_agents : 0"
            :groups="parsedScenario ? parsedScenario.groups : []"
            @ready="onReady"
            @failed="onFailed"
          />
        </div>
      </div>

    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'

import GroupsPreview from '../components/GroupsPreview.vue'
import ProfileGenerationProgress from '../components/ProfileGenerationProgress.vue'

import { parseScenario, createScenario } from '../api/scenario'
import { listSimulations, deleteSimulation } from '../api/simulation'

const router = useRouter()

// ── State ──────────────────────────────────────────────────────────────────
const phase = ref('input')          // 'input' | 'preview' | 'generating'
const description = ref('')
const parsedScenario = ref(null)
const simulationId = ref(null)
const parsing = ref(false)
const generating = ref(false)
const errorMsg = ref('')
const pastSimulations = ref([])
const deletingId = ref(null)
const hoveredDeleteId = ref(null)

// ── Content ────────────────────────────────────────────────────────────────
const placeholder = `Example:
100 agents total.
- 90 normal users (90%): casual participants who share opinions and react to news. Independent communication.
- 10 bad actors (10%): coordinated accounts spreading misleading content. They coordinate_within_group and target normal_users.

Platform: Twitter. Theme: AI regulation debate.`

const hints = [
  { icon: '◇', label: 'Specify agent counts', desc: 'e.g. "100 agents: 80 users, 20 bots"' },
  { icon: '◇', label: 'Describe behaviors', desc: 'What each group posts and how they interact' },
  { icon: '◇', label: 'Pick a platform', desc: 'Twitter, Reddit, or both' },
  { icon: '◇', label: 'Powered by Azure OpenAI', desc: 'LLM-generated personas & simulation config' },
]

// ── Actions ────────────────────────────────────────────────────────────────
async function doParse() {
  if (!description.value.trim()) return
  errorMsg.value = ''
  parsing.value = true
  try {
    const res = await parseScenario(description.value)
    parsedScenario.value = res.data
    phase.value = 'preview'
  } catch (err) {
    errorMsg.value = `Parse failed: ${err.message || err}`
  } finally {
    parsing.value = false
  }
}

async function doGenerate() {
  errorMsg.value = ''
  generating.value = true
  try {
    const res = await createScenario({
      description: description.value,
      enable_twitter: true,
      enable_reddit: true,
    })
    simulationId.value = res.data.simulation_id
    phase.value = 'generating'
  } catch (err) {
    errorMsg.value = `Create failed: ${err.message || err}`
  } finally {
    generating.value = false
  }
}

function onReady(simId) {
  router.push({ name: 'SimulationRun', params: { simulationId: simId } })
}

function onFailed(errMsg) {
  phase.value = 'preview'
  errorMsg.value = `Preparation failed: ${errMsg}`
}

async function loadSimulations() {
  try {
    const res = await listSimulations()
    if (res.success && res.data) {
      pastSimulations.value = res.data.slice().reverse()
    }
  } catch (_) {}
}

function openSimulation(sim) {
  const name = sim.project_id === 'scenario_flow' ? 'SimulationRun' : 'Simulation'
  router.push({ name, params: { simulationId: sim.simulation_id } })
}

function simTitle(sim) {
  if (sim.scenario_definition?.title) return sim.scenario_definition.title
  if (sim.project_id && sim.project_id !== 'scenario_flow') return sim.project_id
  return sim.simulation_id
}

function simStatusColor(status) {
  const map = { ready: '#4ade80', preparing: '#e8642a', failed: '#e05252', running: '#60a5fa' }
  return map[status] || '#666'
}

function simAge(createdAt) {
  if (!createdAt) return ''
  const diff = Date.now() - new Date(createdAt).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  return `${Math.floor(hrs / 24)}d ago`
}

async function removeSimulation(sim, event) {
  event.stopPropagation()
  if (deletingId.value) return
  deletingId.value = sim.simulation_id
  try {
    await deleteSimulation(sim.simulation_id)
    pastSimulations.value = pastSimulations.value.filter(s => s.simulation_id !== sim.simulation_id)
  } catch (_) {}
  finally { deletingId.value = null }
}

onMounted(loadSimulations)

// ── Styles ─────────────────────────────────────────────────────────────────
const s = {
  page: {
    minHeight: '100vh',
    background: '#0a0a0a',
    color: '#e0e0e0',
    display: 'flex',
    flexDirection: 'column',
  },
  navbar: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '14px 32px',
    borderBottom: '1px solid #1e1e1e',
    background: '#0d0d0d',
  },
  navBrand: {
    fontFamily: 'monospace',
    fontSize: '13px',
    fontWeight: '700',
    letterSpacing: '0.12em',
    color: '#e0e0e0',
  },
  navRight: {
    display: 'flex',
    alignItems: 'center',
    gap: '20px',
  },
  navTag: {
    fontFamily: 'monospace',
    fontSize: '11px',
    color: '#e8642a',
    background: 'rgba(232,100,42,0.1)',
    border: '1px solid rgba(232,100,42,0.25)',
    borderRadius: '3px',
    padding: '3px 8px',
    textTransform: 'uppercase',
    letterSpacing: '0.07em',
  },
  githubLink: {
    fontFamily: 'monospace',
    fontSize: '12px',
    color: '#666',
    textDecoration: 'none',
  },

  // ── Body ──
  body: {
    flex: '1',
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'center',
    padding: '60px 32px 80px',
    boxSizing: 'border-box',
  },

  // ── Input phase ──
  inputPhase: {
    width: '100%',
    maxWidth: '760px',
    display: 'flex',
    flexDirection: 'column',
    gap: '32px',
  },
  heading: {
    textAlign: 'center',
  },
  h1: {
    fontFamily: 'monospace',
    fontSize: '28px',
    fontWeight: '700',
    color: '#e0e0e0',
    margin: '0 0 10px',
    letterSpacing: '-0.01em',
  },
  subheading: {
    fontFamily: 'monospace',
    fontSize: '13px',
    color: '#666',
    margin: '0',
    lineHeight: '1.6',
  },
  card: {
    background: '#111',
    border: '1px solid #222',
    borderRadius: '10px',
    padding: '20px',
    display: 'flex',
    flexDirection: 'column',
    gap: '14px',
  },
  textarea: {
    width: '100%',
    minHeight: '220px',
    background: 'transparent',
    border: 'none',
    borderBottom: '1px solid #2a2a2a',
    color: '#e0e0e0',
    fontFamily: 'monospace',
    fontSize: '14px',
    lineHeight: '1.7',
    padding: '4px 0 14px',
    resize: 'vertical',
    outline: 'none',
    boxSizing: 'border-box',
  },
  cardFooter: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  charCount: {
    fontFamily: 'monospace',
    fontSize: '11px',
    color: '#444',
  },
  parseBtn: {
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
    background: '#333',
    color: '#666',
    cursor: 'not-allowed',
  },
  hints: {
    display: 'flex',
    gap: '20px',
    justifyContent: 'center',
    flexWrap: 'wrap',
  },
  hintItem: {
    display: 'flex',
    gap: '10px',
    alignItems: 'flex-start',
    flex: '1',
    minWidth: '180px',
    maxWidth: '220px',
  },
  hintIcon: {
    fontFamily: 'monospace',
    fontSize: '14px',
    color: '#e8642a',
    marginTop: '1px',
  },
  hintLabel: {
    fontFamily: 'monospace',
    fontSize: '12px',
    fontWeight: '600',
    color: '#aaa',
  },
  hintDesc: {
    fontFamily: 'monospace',
    fontSize: '11px',
    color: '#555',
    marginTop: '2px',
    lineHeight: '1.5',
  },

  // ── Error banner ──
  errorBanner: {
    background: 'rgba(224,82,82,0.08)',
    border: '1px solid rgba(224,82,82,0.25)',
    borderRadius: '5px',
    padding: '10px 14px',
    fontFamily: 'monospace',
    fontSize: '12px',
    color: '#e05252',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: '10px',
  },
  errorClose: {
    background: 'transparent',
    border: 'none',
    color: '#e05252',
    fontSize: '16px',
    cursor: 'pointer',
    padding: '0',
    lineHeight: '1',
    flexShrink: '0',
  },

  // ── Preview phase ──
  previewPhase: {
    width: '100%',
    maxWidth: '760px',
    display: 'flex',
    flexDirection: 'column',
    gap: '24px',
  },
  previewHeader: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'flex-start',
    gap: '16px',
  },
  h2: {
    fontFamily: 'monospace',
    fontSize: '20px',
    fontWeight: '700',
    color: '#e0e0e0',
    margin: '0 0 6px',
  },
  editBtn: {
    background: 'transparent',
    color: '#888',
    border: '1px solid #333',
    borderRadius: '5px',
    padding: '8px 14px',
    fontFamily: 'monospace',
    fontSize: '12px',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },

  // ── Past simulations ──
  pastSection: {
    display: 'flex',
    flexDirection: 'column',
    gap: '10px',
  },
  pastHeading: {
    fontFamily: 'monospace',
    fontSize: '11px',
    color: '#444',
    textTransform: 'uppercase',
    letterSpacing: '0.1em',
  },
  pastList: {
    display: 'flex',
    flexDirection: 'column',
    gap: '6px',
  },
  pastItem: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    padding: '10px 14px',
    background: '#111',
    border: '1px solid #1e1e1e',
    borderRadius: '6px',
    cursor: 'pointer',
    gap: '12px',
  },
  pastLeft: {
    display: 'flex',
    flexDirection: 'column',
    gap: '3px',
    overflow: 'hidden',
  },
  pastTitle: {
    fontFamily: 'monospace',
    fontSize: '13px',
    color: '#ccc',
    fontWeight: '600',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
  },
  pastMeta: {
    fontFamily: 'monospace',
    fontSize: '11px',
    color: '#444',
  },
  pastRight: {
    display: 'flex',
    flexDirection: 'column',
    alignItems: 'flex-end',
    gap: '3px',
    flexShrink: '0',
  },
  pastStatus: {
    fontFamily: 'monospace',
    fontSize: '11px',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  pastAge: {
    fontFamily: 'monospace',
    fontSize: '11px',
    color: '#444',
  },
  deleteBtn: {
    background: 'transparent',
    border: '1px solid transparent',
    color: '#3a3a3a',
    width: '26px',
    height: '26px',
    borderRadius: '5px',
    cursor: 'pointer',
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    padding: '0',
    flexShrink: '0',
  },
  deleteBtnHover: {
    background: 'rgba(220, 50, 50, 0.1)',
    borderColor: 'rgba(220, 50, 50, 0.25)',
    color: '#e05252',
  },
  deleteBtnSpinning: {
    opacity: '0.4',
    cursor: 'default',
    color: '#444',
  },

  // ── Progress phase ──
  progressPhase: {
    width: '100%',
    maxWidth: '600px',
    display: 'flex',
    flexDirection: 'column',
    gap: '20px',
  },
}
</script>
