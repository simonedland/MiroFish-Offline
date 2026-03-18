<template>
  <div :style="s.container">
    <label :style="s.label">Describe your simulation scenario</label>
    <textarea
      v-model="localValue"
      :placeholder="placeholder"
      :disabled="loading"
      :style="s.textarea"
      @input="$emit('update:modelValue', localValue)"
    />
    <div :style="s.footer">
      <span :style="s.hint">
        Tip: specify total agent count, group types, behaviors, and platform.
      </span>
      <button
        :disabled="loading || !localValue.trim()"
        :style="[s.btn, (!localValue.trim() || loading) ? s.btnDisabled : {}]"
        @click="$emit('parse')"
      >
        <span v-if="loading">Parsing…</span>
        <span v-else>Parse Scenario</span>
      </button>
    </div>
  </div>
</template>

<script setup>
import { ref, watch } from 'vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  loading: { type: Boolean, default: false },
})

defineEmits(['update:modelValue', 'parse'])

const localValue = ref(props.modelValue)
watch(() => props.modelValue, v => { localValue.value = v })

const placeholder = `Example: 100 agents total.
- 90 normal users (90%): casual social media participants sharing opinions about tech news. Independent communication.
- 10 bad actors (10%): coordinated accounts posting misleading content. They coordinate_within_group and target normal_users.
Platform: Twitter. Theme: AI regulation debate.`

const s = {
  container: {
    display: 'flex',
    flexDirection: 'column',
    gap: '12px',
  },
  label: {
    fontFamily: 'monospace',
    fontSize: '13px',
    fontWeight: '600',
    color: '#ccc',
    textTransform: 'uppercase',
    letterSpacing: '0.05em',
  },
  textarea: {
    width: '100%',
    minHeight: '180px',
    background: '#111',
    border: '1px solid #333',
    borderRadius: '6px',
    color: '#e0e0e0',
    fontFamily: 'monospace',
    fontSize: '14px',
    lineHeight: '1.6',
    padding: '14px',
    resize: 'vertical',
    outline: 'none',
    boxSizing: 'border-box',
  },
  footer: {
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    gap: '12px',
  },
  hint: {
    fontFamily: 'monospace',
    fontSize: '12px',
    color: '#666',
    flex: '1',
  },
  btn: {
    background: '#e8642a',
    color: '#fff',
    border: 'none',
    borderRadius: '5px',
    padding: '10px 22px',
    fontFamily: 'monospace',
    fontSize: '13px',
    fontWeight: '600',
    cursor: 'pointer',
    whiteSpace: 'nowrap',
  },
  btnDisabled: {
    background: '#444',
    cursor: 'not-allowed',
    opacity: '0.6',
  },
}
</script>
