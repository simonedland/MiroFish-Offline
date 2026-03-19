<template>
  <div class="sms-inbox">
    <div class="sms-sidebar">
      <div class="sms-sidebar-title">Agents</div>
      <div
        v-for="agent in agents"
        :key="agent.agent_id"
        class="sms-agent-item"
        :class="{ active: selectedAgent && selectedAgent.agent_id === agent.agent_id }"
        @click="selectAgent(agent)"
      >
        <span class="agent-dot">●</span> {{ agent.name }}
      </div>
    </div>

    <div class="sms-contacts" v-if="selectedAgent">
      <div class="sms-sidebar-title">Conversations</div>
      <div
        v-for="contact in contacts"
        :key="contact.phone"
        class="sms-contact-item"
        :class="{ active: selectedContact && selectedContact.phone === contact.phone }"
        @click="selectContact(contact)"
      >
        <div class="contact-name">{{ contact.other_name }}</div>
        <div class="contact-preview">{{ contact.last_message }}</div>
      </div>
      <div v-if="contacts.length === 0" class="sms-empty">No conversations yet</div>
    </div>

    <div class="sms-thread" ref="threadContainer">
      <div v-if="!selectedAgent" class="sms-placeholder">Select an agent to view their messages</div>
      <div v-else-if="!selectedContact" class="sms-placeholder">Select a conversation</div>
      <div v-else>
        <div class="thread-header">{{ selectedAgent.name }} ↔ {{ selectedContact.other_name }}</div>

        <template v-for="(roundMessages, roundNum) in messagesByRound" :key="roundNum">
          <div class="round-divider">── Round {{ roundNum }} ──</div>
          <div
            v-for="msg in roundMessages"
            :key="msg.id"
            class="message-bubble"
            :class="msg.sender_phone === selectedAgent.phone_number ? 'sent' : 'received'"
          >
            {{ msg.content }}
          </div>
        </template>

        <div v-if="messages.length === 0" class="sms-empty">No messages yet</div>
      </div>
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

async function loadAgents() {
  try {
    const res = await getAgents(props.simulationId)
    if (res.success) agents.value = res.data
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
    if (res.success) contacts.value = res.data
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
.sms-inbox {
  display: grid;
  grid-template-columns: 180px 200px 1fr;
  height: 100%;
  min-height: 400px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}

.sms-sidebar, .sms-contacts {
  border-right: 1px solid #e0e0e0;
  overflow-y: auto;
}

.sms-sidebar-title {
  padding: 12px 14px;
  font-size: 12px;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  border-bottom: 1px solid #f0f0f0;
}

.sms-agent-item, .sms-contact-item {
  padding: 10px 14px;
  cursor: pointer;
  transition: background 0.15s;
  border-bottom: 1px solid #f8f8f8;
}

.sms-agent-item:hover, .sms-contact-item:hover { background: #f5f5f5; }
.sms-agent-item.active, .sms-contact-item.active { background: #e8f0fe; }

.agent-dot { color: #4CAF50; font-size: 10px; margin-right: 6px; }

.contact-name { font-size: 13px; font-weight: 500; }
.contact-preview { font-size: 11px; color: #888; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.sms-thread {
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
}

.thread-header {
  font-size: 14px;
  font-weight: 600;
  color: #333;
  margin-bottom: 16px;
  padding-bottom: 8px;
  border-bottom: 1px solid #f0f0f0;
}

.round-divider {
  text-align: center;
  font-size: 11px;
  color: #aaa;
  margin: 12px 0 8px;
}

.message-bubble {
  max-width: 70%;
  padding: 8px 12px;
  border-radius: 14px;
  font-size: 13px;
  line-height: 1.4;
  margin-bottom: 6px;
}

.message-bubble.sent {
  align-self: flex-end;
  background: #4f8ef7;
  color: #fff;
  border-bottom-right-radius: 4px;
}

.message-bubble.received {
  align-self: flex-start;
  background: #f0f0f0;
  color: #333;
  border-bottom-left-radius: 4px;
}

.sms-placeholder, .sms-empty {
  color: #aaa;
  font-size: 13px;
  text-align: center;
  margin: auto;
  padding: 40px 20px;
}
</style>
