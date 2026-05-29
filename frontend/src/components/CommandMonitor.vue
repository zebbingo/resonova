<script setup lang="ts">
import { ref, onMounted, onUnmounted, nextTick, computed } from 'vue'

interface InterceptEvent {
  id: number
  time: string
  type: 'kws_match' | 'command_detected' | 'command_forwarded' | 'mqtt_command' | 'other'
  summary: string
  detail: string
  raw: any
}

const events = ref<InterceptEvent[]>([])
const wsRef = ref<WebSocket | null>(null)
const autoScroll = ref(true)
const stats = computed(() => {
  const kws = events.value.filter(e => e.type === 'kws_match').length
  const cmd = events.value.filter(e => e.type === 'command_detected').length
  const pub = events.value.filter(e => e.type === 'mqtt_command').length
  return { kws, cmd, pub, total: events.value.length }
})

let eventId = 0

function formatTime(): string {
  const now = new Date()
  return now.toLocaleTimeString('zh-CN', { hour12: false })
}

function classify(raw: any): InterceptEvent['type'] {
  const t = raw.type || ''
  if (t === 'kws_match') return 'kws_match'
  if (t === 'command_detected') return 'command_detected'
  if (t === 'command_forwarded') return 'command_forwarded'
  if (t === 'mqtt_publish') {
    const mt = raw.message_type || ''
    if (mt === 'command') return 'mqtt_command'
  }
  return 'other'
}

function summarize(raw: any, type: InterceptEvent['type']): string {
  const m = raw.metrics || raw
  switch (type) {
    case 'kws_match':
      return `🔊 KWS 命中: "${m.keyword}" → ${m.command}`
    case 'command_detected':
      return `🎯 指令检测: ${m.intent || raw.intent} (${m.command || raw.command})`
    case 'command_forwarded':
      return `🧹 文本清理: "${m.cleaned_text || raw.cleaned_text || ''}"`
    case 'mqtt_command':
      return `📤 指令下发: ${m.command || raw.command} → ${raw.topic || m.topic || ''}`.substring(0, 100)
    default:
      return `${raw.type || 'event'}: ${JSON.stringify(raw).substring(0, 60)}`
  }
}

function detailize(raw: any, type: InterceptEvent['type']): string {
  const m = raw.metrics || raw
  switch (type) {
    case 'kws_match':
      return `keyword="${m.keyword}" → command="${m.command}" turn_id="${m.turn_id}" mode="${m.mode}"`
    case 'command_detected':
      return `intent="${m.intent}" command="${m.command}" session_mode="${m.session_mode}" text="${(m.original_text || raw.original_text || '').substring(0, 80)}"`
    case 'command_forwarded':
      return `origin="${(m.original_text || raw.original_text || '').substring(0, 60)}" → cleaned="${(m.cleaned_text || raw.cleaned_text || '').substring(0, 60)}"`
    case 'mqtt_command':
      return `cmd="${m.command}" preempt=${m.preempt} after_audio=${m.after_audio} topic="${(raw.topic || '').substring(0, 80)}"`
    default:
      return JSON.stringify(raw).substring(0, 120)
  }
}

function handleEvent(raw: any) {
  const type = classify(raw)
  if (type === 'other' && raw.type !== 'mqtt_publish') return // skip irrelevant events

  eventId++
  events.value.unshift({
    id: eventId,
    time: formatTime(),
    type,
    summary: summarize(raw, type),
    detail: detailize(raw, type),
    raw,
  })

  // Keep max 200 events
  if (events.value.length > 200) {
    events.value = events.value.slice(0, 200)
  }

  if (autoScroll.value) {
    nextTick(() => {
      const el = document.querySelector('.event-list')
      if (el) el.scrollTop = 0
    })
  }
}

function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws/monitoring/events`)
  ws.onopen = () => {
    console.log('[CommandMonitor] WebSocket connected')
    handleEvent({ type: 'system', text: '✅ 已连接监控服务' })
  }
  ws.onmessage = (msg) => {
    try {
      const data = JSON.parse(msg.data)
      handleEvent(data)
    } catch { /* ignore */ }
  }
  ws.onclose = () => {
    console.log('[CommandMonitor] WebSocket disconnected, reconnecting in 3s...')
    handleEvent({ type: 'system', text: '⚠️ 监控连接断开，3秒后重连...' })
    wsRef.value = null
    setTimeout(connect, 3000)
  }
  ws.onerror = () => {
    ws.close()
  }
  wsRef.value = ws
}

function clearLog() {
  events.value = []
}

onMounted(() => {
  connect()
})

onUnmounted(() => {
  wsRef.value?.close()
})

function iconFor(type: InterceptEvent['type']): string {
  switch (type) {
    case 'kws_match': return '🔊'
    case 'command_detected': return '🎯'
    case 'command_forwarded': return '🧹'
    case 'mqtt_command': return '📤'
    default: return '💬'
  }
}

function colorFor(type: InterceptEvent['type']): string {
  switch (type) {
    case 'kws_match': return '#e8a838'
    case 'command_detected': return '#5b8def'
    case 'command_forwarded': return '#4caf7d'
    case 'mqtt_command': return '#ab6cf0'
    default: return '#9298b0'
  }
}
</script>

<template>
  <div class="cmd-monitor">
    <!-- Header: Stats -->
    <div class="stats-bar">
      <div class="stat">
        <span class="stat-num">{{ stats.total }}</span>
        <span class="stat-label">总事件</span>
      </div>
      <div class="stat">
        <span class="stat-num" style="color: #e8a838">{{ stats.kws }}</span>
        <span class="stat-label">KWS 命中</span>
      </div>
      <div class="stat">
        <span class="stat-num" style="color: #5b8def">{{ stats.cmd }}</span>
        <span class="stat-label">指令检测</span>
      </div>
      <div class="stat">
        <span class="stat-num" style="color: #ab6cf0">{{ stats.pub }}</span>
        <span class="stat-label">指令下发</span>
      </div>
      <div class="stat-actions">
        <label class="auto-scroll">
          <input type="checkbox" v-model="autoScroll" />
          自动滚动
        </label>
        <button class="clear-btn" @click="clearLog">清空</button>
      </div>
    </div>

    <!-- Event list -->
    <div class="event-list">
      <div
        v-for="evt in events"
        :key="evt.id"
        class="event-row"
        :style="{ borderLeftColor: colorFor(evt.type) }"
      >
        <div class="event-header">
          <span class="event-icon">{{ iconFor(evt.type) }}</span>
          <span class="event-time">{{ evt.time }}</span>
          <span class="event-type-tag" :style="{ background: colorFor(evt.type) + '22', color: colorFor(evt.type) }">
            {{ evt.type }}
          </span>
          <span class="event-summary">{{ evt.summary }}</span>
        </div>
        <div class="event-detail">
          <code>{{ evt.detail }}</code>
        </div>
      </div>

      <div v-if="events.length === 0" class="empty-state">
        <div class="empty-icon">📟</div>
        <p>等待指令拦截事件...</p>
        <p class="empty-hint">启动 chatbot 并与设备对话后，拦截事件将实时显示</p>
      </div>
    </div>
  </div>
</template>

<style scoped>
.cmd-monitor {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  display: flex;
  flex-direction: column;
  height: 100%;
}

.stats-bar {
  display: flex;
  align-items: center;
  gap: 16px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--surface2);
}

.stat {
  display: flex;
  flex-direction: column;
  align-items: center;
  min-width: 60px;
}

.stat-num {
  font-size: 1.3rem;
  font-weight: 700;
  color: var(--text);
}

.stat-label {
  font-size: 0.7rem;
  color: var(--text3);
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.stat-actions {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 12px;
}

.auto-scroll {
  font-size: 0.8rem;
  color: var(--text2);
  display: flex;
  align-items: center;
  gap: 4px;
  cursor: pointer;
}

.clear-btn {
  background: transparent;
  border: 1px solid var(--border);
  color: var(--text2);
  padding: 4px 12px;
  border-radius: 4px;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.12s;
}

.clear-btn:hover {
  border-color: var(--red);
  color: var(--red);
}

.event-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
  max-height: 500px;
}

.event-row {
  border-left: 3px solid var(--border);
  padding: 8px 12px;
  margin-bottom: 4px;
  background: var(--surface);
  border-radius: 0 6px 6px 0;
  transition: background 0.1s;
}

.event-row:hover {
  background: var(--surface2);
}

.event-header {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.event-icon {
  font-size: 1rem;
}

.event-time {
  font-size: 0.75rem;
  color: var(--text3);
  font-family: monospace;
  min-width: 60px;
}

.event-type-tag {
  font-size: 0.7rem;
  padding: 1px 8px;
  border-radius: 10px;
  font-weight: 600;
  text-transform: uppercase;
}

.event-summary {
  font-size: 0.85rem;
  color: var(--text);
  flex: 1;
}

.event-detail {
  margin-top: 4px;
  padding-left: 28px;
}

.event-detail code {
  font-size: 0.75rem;
  color: var(--text3);
  word-break: break-all;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
}

.empty-state {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 60px 20px;
  color: var(--text2);
}

.empty-icon {
  font-size: 3rem;
  margin-bottom: 12px;
  opacity: 0.5;
}

.empty-state p {
  font-size: 0.95rem;
  margin-bottom: 8px;
}

.empty-hint {
  font-size: 0.8rem !important;
  color: var(--text3);
}

/* Scrollbar styling */
.event-list::-webkit-scrollbar {
  width: 6px;
}
.event-list::-webkit-scrollbar-track {
  background: transparent;
}
.event-list::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 3px;
}
.event-list::-webkit-scrollbar-thumb:hover {
  background: var(--text3);
}
</style>
