<template>
  <div class="phone-app">
    <!-- Agents list -->
    <div class="agents-pane">
      <div class="pane-header">
        <span class="pane-title">Agents</span>
        <span class="pane-count">{{ agents.length }}</span>
      </div>
      <div class="agent-list">
        <div
          v-for="agent in agents"
          :key="agent.agent_id"
          class="agent-row"
          :class="{ active: selectedAgent?.agent_id === agent.agent_id }"
          @click="selectAgent(agent)"
        >
          <div class="avatar sm" :style="{ background: avatarColor(agent.name) }">
            {{ (agent.name || '?')[0].toUpperCase() }}
          </div>
          <div class="row-info">
            <div class="row-name">{{ agent.name }}</div>
            <div class="row-sub">{{ agent.phone_number }}</div>
          </div>
          <div class="online-dot"></div>
        </div>
        <div v-if="agents.length === 0" class="pane-empty">No agents yet</div>
      </div>
    </div>

    <!-- Conversations list -->
    <div class="convos-pane">
      <div class="pane-header">
        <span class="pane-title">Messages</span>
        <span class="pane-count">{{ contacts.length }}</span>
      </div>
      <div class="convo-list">
        <div v-if="!selectedAgent" class="pane-empty">Select an agent</div>
        <template v-else>
          <div
            v-for="contact in contacts"
            :key="contact.other_phone"
            class="convo-row"
            :class="{ active: selectedContact?.other_phone === contact.other_phone }"
            @click="selectContact(contact)"
          >
            <div class="avatar md" :style="{ background: avatarColor(contact.other_name) }">
              {{ (contact.other_name || '?')[0].toUpperCase() }}
            </div>
            <div class="row-info">
              <div class="row-name">{{ contact.other_name }}</div>
              <div class="row-sub preview">{{ contact.last_message }}</div>
            </div>
          </div>
          <div v-if="contacts.length === 0" class="pane-empty">No conversations yet</div>
        </template>
      </div>
    </div>

    <!-- Thread pane -->
    <div class="thread-pane">
      <!-- Empty states -->
      <div v-if="!selectedAgent" class="thread-empty">
        <div class="empty-bubble-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="40" height="40">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
        </div>
        <p>Select an agent to view messages</p>
      </div>
      <div v-else-if="!selectedContact" class="thread-empty">
        <div class="empty-bubble-icon">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" width="40" height="40">
            <path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/>
          </svg>
        </div>
        <p>Select a conversation</p>
      </div>

      <template v-else>
        <!-- Chat header -->
        <div class="chat-header">
          <div class="avatar lg" :style="{ background: avatarColor(selectedContact.other_name) }">
            {{ (selectedContact.other_name || '?')[0].toUpperCase() }}
          </div>
          <div class="chat-header-info">
            <div class="chat-contact-name">{{ selectedContact.other_name }}</div>
            <div class="chat-contact-sub">{{ selectedContact.other_phone }}</div>
          </div>
          <div class="chat-header-you">
            <div class="you-label">You</div>
            <div class="avatar sm you-avatar" :style="{ background: avatarColor(selectedAgent.name) }">
              {{ (selectedAgent.name || '?')[0].toUpperCase() }}
            </div>
          </div>
        </div>

        <!-- Messages scroll area -->
        <div class="messages-area" ref="threadContainer">
          <template v-for="(roundMessages, roundNum) in messagesByRound" :key="roundNum">
            <div class="round-sep">
              <span>Round {{ roundNum }}</span>
            </div>
            <div
              v-for="msg in roundMessages"
              :key="msg.id"
              class="msg-row"
              :class="msg.sender_phone === selectedAgent.phone_number ? 'sent' : 'received'"
            >
              <div
                v-if="msg.sender_phone !== selectedAgent.phone_number"
                class="avatar xs"
                :style="{ background: avatarColor(selectedContact.other_name) }"
              >
                {{ (selectedContact.other_name || '?')[0].toUpperCase() }}
              </div>
              <div class="bubble">{{ msg.content }}</div>
            </div>
          </template>
          <div v-if="messages.length === 0" class="thread-empty small">No messages yet</div>
        </div>
      </template>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { getAgents, getThreads, getThread } from '../api/sms.js'

const props = defineProps({
  simulationId: { type: String, required: true },
  isRunning: { type: Boolean, default: false }
})

const agents = ref([])
const selectedAgent = ref(null)
const contacts = ref([])
const selectedContact = ref(null)
const messages = ref([])
const threadContainer = ref(null)
let pollTimer = null

const messagesByRound = computed(() => {
  const grouped = {}
  for (const msg of messages.value) {
    if (!grouped[msg.round_num]) grouped[msg.round_num] = []
    grouped[msg.round_num].push(msg)
  }
  return grouped
})

const AVATAR_COLORS = [
  '#FF6B6B', '#FF9F43', '#FECA57', '#48DBFB', '#54A0FF',
  '#5F27CD', '#A29BFE', '#00D2D3', '#1DD1A1', '#F368E0'
]

function avatarColor(name) {
  if (!name) return '#555'
  let hash = 0
  for (let i = 0; i < name.length; i++) hash = name.charCodeAt(i) + ((hash << 5) - hash)
  return AVATAR_COLORS[Math.abs(hash) % AVATAR_COLORS.length]
}

async function loadAgents() {
  try {
    const res = await getAgents(props.simulationId)
    if (res.success) {
      agents.value = res.data
      if (!selectedAgent.value && agents.value.length > 0) {
        await selectAgent(agents.value[0])
      }
    }
  } catch (e) {
    console.error('Failed to load agents', e)
  }
}

async function selectAgent(agent) {
  selectedAgent.value = agent
  selectedContact.value = null
  messages.value = []
  await loadContacts()
}

async function loadContacts() {
  if (!selectedAgent.value) return
  try {
    const res = await getThreads(props.simulationId, selectedAgent.value.phone_number)
    if (res.success) {
      contacts.value = res.data
      if (!selectedContact.value && contacts.value.length > 0) {
        await selectContact(contacts.value[0])
      }
    }
  } catch (e) {
    console.error('Failed to load contacts', e)
  }
}

async function selectContact(contact) {
  selectedContact.value = contact
  await loadThread()
}

async function loadThread() {
  if (!selectedAgent.value || !selectedContact.value) return
  try {
    const res = await getThread(
      props.simulationId,
      selectedAgent.value.phone_number,
      selectedContact.value.other_phone
    )
    if (res.success) {
      messages.value = res.data
      await nextTick()
      scrollToBottom()
    }
  } catch (e) {
    console.error('Failed to load thread', e)
  }
}

function scrollToBottom() {
  if (threadContainer.value) {
    threadContainer.value.scrollTop = threadContainer.value.scrollHeight
  }
}

function startPolling() {
  if (pollTimer) return
  pollTimer = setInterval(async () => {
    await loadAgents()
    if (selectedAgent.value) await loadContacts()
    if (selectedContact.value) await loadThread()
  }, 3000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

watch(() => props.isRunning, (running) => {
  if (running) startPolling()
  else stopPolling()
}, { immediate: true })

onMounted(loadAgents)
onUnmounted(stopPolling)
</script>

<style scoped>
/* ── Root ─────────────────────────────────────────────────────────────────── */
.phone-app {
  container-type: inline-size;
  display: grid;
  grid-template-columns: 160px 200px 1fr;
  height: 100%;
  min-height: 0;
  background: #000;
  overflow: hidden;
}

/* Narrow: hide agents pane, shrink convos */
@container (max-width: 700px) {
  .phone-app {
    grid-template-columns: 170px 1fr;
  }
  .agents-pane {
    display: none;
  }
}

/* Very narrow: hide convos too, show only thread */
@container (max-width: 400px) {
  .phone-app {
    grid-template-columns: 1fr;
  }
  .convos-pane {
    display: none;
  }
}

/* ── Shared avatar ────────────────────────────────────────────────────────── */
.avatar {
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
  text-shadow: 0 1px 2px rgba(0,0,0,0.4);
}
.avatar.xs  { width: 28px; height: 28px; font-size: 11px; }
.avatar.sm  { width: 36px; height: 36px; font-size: 14px; }
.avatar.md  { width: 44px; height: 44px; font-size: 17px; }
.avatar.lg  { width: 52px; height: 52px; font-size: 21px; }

/* ── Shared pane structure ────────────────────────────────────────────────── */
.agents-pane,
.convos-pane {
  display: flex;
  flex-direction: column;
  background: #1c1c1e;
  border-right: 1px solid #2c2c2e;
  overflow: hidden;
}

.pane-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 16px 12px;
  border-bottom: 1px solid #2c2c2e;
  flex-shrink: 0;
  background: #1c1c1e;
}

.pane-title {
  font-size: 17px;
  font-weight: 700;
  color: #fff;
  letter-spacing: -0.3px;
}

.pane-count {
  font-size: 12px;
  color: #636366;
  background: #2c2c2e;
  padding: 2px 8px;
  border-radius: 10px;
}

.pane-empty {
  font-size: 13px;
  color: #48484a;
  text-align: center;
  padding: 32px 16px;
}

/* ── Agent list ──────────────────────────────────────────────────────────── */
.agent-list,
.convo-list {
  overflow-y: auto;
  flex: 1;
}

.agent-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  cursor: pointer;
  transition: background 0.12s;
  border-bottom: 1px solid #2c2c2e;
  position: relative;
}
.agent-row:hover  { background: #2c2c2e; }
.agent-row.active { background: #3a3a3c; }

.online-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #30d158;
  flex-shrink: 0;
  margin-left: auto;
  box-shadow: 0 0 0 2px #1c1c1e;
}

/* ── Conversation list ───────────────────────────────────────────────────── */
.convo-row {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 12px 16px;
  cursor: pointer;
  transition: background 0.12s;
  border-bottom: 1px solid #2c2c2e;
}
.convo-row:hover  { background: #2c2c2e; }
.convo-row.active { background: #3a3a3c; }

/* ── Shared row text ─────────────────────────────────────────────────────── */
.row-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.row-name {
  font-size: 14px;
  font-weight: 600;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.row-sub {
  font-size: 12px;
  color: #8e8e93;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.row-sub.preview {
  font-size: 13px;
  color: #636366;
}

/* ── Thread pane ─────────────────────────────────────────────────────────── */
.thread-pane {
  display: flex;
  flex-direction: column;
  background: #000;
  overflow: hidden;
  min-width: 0;
}

/* Empty states */
.thread-empty {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 14px;
  color: #48484a;
  font-size: 14px;
}
.thread-empty.small { font-size: 13px; padding: 24px; }
.empty-bubble-icon { color: #3a3a3c; }

/* Chat header */
.chat-header {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 14px 18px;
  background: #1c1c1e;
  border-bottom: 1px solid #2c2c2e;
  flex-shrink: 0;
}

.chat-header-info {
  flex: 1;
  min-width: 0;
}
.chat-contact-name {
  font-size: 16px;
  font-weight: 700;
  color: #fff;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.chat-contact-sub {
  font-size: 12px;
  color: #8e8e93;
  margin-top: 1px;
}

.chat-header-you {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-shrink: 0;
}
.you-label {
  font-size: 11px;
  color: #636366;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

/* Messages scroll */
.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 16px 14px 20px;
  display: flex;
  flex-direction: column;
  gap: 3px;
  scroll-behavior: smooth;
}

/* Round separator */
.round-sep {
  display: flex;
  align-items: center;
  justify-content: center;
  margin: 14px 0 10px;
}
.round-sep span {
  font-size: 11px;
  font-weight: 500;
  color: #636366;
  background: #1c1c1e;
  padding: 3px 12px;
  border-radius: 10px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
}

/* Message row */
.msg-row {
  display: flex;
  align-items: flex-end;
  gap: 7px;
  max-width: 82%;
}
.msg-row.sent {
  align-self: flex-end;
  flex-direction: row-reverse;
}
.msg-row.received {
  align-self: flex-start;
}

/* Bubble */
.bubble {
  padding: 10px 14px;
  border-radius: 18px;
  font-size: 14px;
  line-height: 1.45;
  word-break: break-word;
  position: relative;
}

.msg-row.sent .bubble {
  background: #0A84FF;
  color: #fff;
  border-bottom-right-radius: 5px;
}

.msg-row.received .bubble {
  background: #1c1c1e;
  color: #e5e5ea;
  border-bottom-left-radius: 5px;
  border: 1px solid #2c2c2e;
}

/* Scrollbar */
.agent-list::-webkit-scrollbar,
.convo-list::-webkit-scrollbar,
.messages-area::-webkit-scrollbar {
  width: 4px;
}
.agent-list::-webkit-scrollbar-thumb,
.convo-list::-webkit-scrollbar-thumb,
.messages-area::-webkit-scrollbar-thumb {
  background: #3a3a3c;
  border-radius: 4px;
}
.agent-list::-webkit-scrollbar-track,
.convo-list::-webkit-scrollbar-track,
.messages-area::-webkit-scrollbar-track {
  background: transparent;
}
</style>
