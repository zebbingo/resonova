<script setup lang="ts">
import type { MQTTMessageLog } from '../composables/useMQTTSimulation'

defineProps<{
  logs: MQTTMessageLog[]
}>()

function formatTime(date: Date): string {
  const h = String(date.getHours()).padStart(2, '0')
  const m = String(date.getMinutes()).padStart(2, '0')
  const s = String(date.getSeconds()).padStart(2, '0')
  const ms = String(date.getMilliseconds()).padStart(3, '0')
  return `${h}:${m}:${s}.${ms}`
}

function getTypeLabel(type: MQTTMessageLog['type']): string {
  if (type === 'session_status') return 'STATUS'
  if (type === 'intro_start' || type === 'intro_end') return 'INTRO'
  if (type === 'stt_inference' || type === 'stt_result') return 'STT'
  if (type === 'llm_inference') return 'LLM'
  if (type === 'tts_synthesis') return 'TTS'
  if (type === 'vad_speech_started' || type === 'vad_speech_stopped') return 'VAD'
  if (type === 'command') return 'CMD'
  if (type === 'command_preempt') return 'CMD'
  if (type === 'mqtt_publish') return 'MQTT'

  const labels: Partial<Record<MQTTMessageLog['type'], string>> = {
    session_start: 'SESSION',
    audio_start: 'AUDIO',
    chunk: 'CHUNK',
    eos: 'EOS',
    session_end: 'END',
    other: 'INFO',
  }
  return labels[type] || 'INFO'
}

function getDirectionIcon(direction: 'up' | 'down'): string {
  return direction === 'up' ? 'UP' : 'DOWN'
}

function truncatePayload(payload: any): string {
  if (!payload) return ''
  const str = typeof payload === 'string' ? payload : JSON.stringify(payload)
  return str.length > 120 ? `${str.slice(0, 120)}...` : str
}
</script>

<template>
  <div class="session-log">
    <div class="log-header">
      <h3>Session Log</h3>
      <span class="log-count">{{ logs.length }} messages</span>
    </div>

    <div v-if="logs.length === 0" class="empty-log">
      No logs yet. Start the device to see MQTT messages.
    </div>

    <div v-else class="log-list">
      <div
        v-for="(log, index) in logs"
        :key="index"
        class="log-item"
        :class="[log.direction, log.type]"
      >
        <div class="log-time">
          {{ formatTime(log.timestamp) }}
        </div>

        <div class="log-direction">
          {{ getDirectionIcon(log.direction) }}
        </div>

        <div class="log-type">
          {{ getTypeLabel(log.type) }}
        </div>

        <div class="log-topic">
          {{ log.topic }}
        </div>

        <div v-if="log.payload" class="log-payload">
          {{ truncatePayload(log.payload) }}
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.session-log {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  height: 100%;
  display: flex;
  flex-direction: column;
}

.log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 12px;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.log-header h3 {
  font-size: 0.95rem;
  margin: 0;
}

.log-count {
  font-size: 0.8rem;
  color: var(--text2);
}

.empty-log {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--text2);
  font-size: 0.9rem;
  text-align: center;
  padding: 40px 20px;
}

.log-list {
  flex: 1;
  overflow-y: auto;
  max-height: 500px;
}

.log-item {
  display: grid;
  grid-template-columns: 85px 30px 80px 1fr;
  gap: 8px;
  padding: 6px 8px;
  margin-bottom: 4px;
  background: var(--surface2);
  border-radius: 4px;
  font-size: 0.75rem;
  border-left: 3px solid transparent;
  transition: all 0.15s;
}

.log-item:hover {
  background: #2a2e3f;
}

.log-item.up {
  border-left-color: var(--accent);
}

.log-item.down {
  border-left-color: var(--green);
}

.log-item.stt_result {
  border-left-color: var(--orange);
  background: #2a2520;
}

.log-time {
  color: var(--text2);
  font-family: 'Courier New', monospace;
}

.log-direction {
  text-align: center;
  font-weight: bold;
}

.log-item.up .log-direction {
  color: var(--accent);
}

.log-item.down .log-direction {
  color: var(--green);
}

.log-type {
  font-weight: 600;
  white-space: nowrap;
}

.log-topic {
  color: var(--text);
  word-break: break-all;
  font-family: 'Courier New', monospace;
}

.log-payload {
  grid-column: 1 / -1;
  color: var(--text2);
  font-size: 0.7rem;
  padding-left: 8px;
  margin-top: 2px;
  word-break: break-all;
}

.log-list::-webkit-scrollbar {
  width: 6px;
}

.log-list::-webkit-scrollbar-track {
  background: var(--surface);
}

.log-list::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 3px;
}

.log-list::-webkit-scrollbar-thumb:hover {
  background: var(--text2);
}
</style>
