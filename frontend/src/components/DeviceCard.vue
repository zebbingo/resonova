<script setup lang="ts">
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import type { AudioItem, FigurineConfig, StoryItem, MusicItem } from '../types'
import { audioUrl, mediaStreamUrl, fetchFigurines, fetchStories, fetchMusic, fetchFigurineTTSAudios, generateTTS, fetchGeneratedVoices, generatedAudioUrl, translateText } from '../api'
import type { GeneratedVoice } from '../types'
import { useMQTTSimulation } from '../composables/useMQTTSimulation'
import type { TurnInfo, CommandInfo } from '../composables/useMQTTSimulation'
import { registerSimulation } from '../composables/simulationStore'
import {
  initFlow, addStep, completeStep, failStep, startAutoDerive, resetFlow, flowStore,
} from '../composables/chatFlowStore'

import InlineGenerator from './InlineGenerator.vue'

const props = withDefaults(defineProps<{
  audios: AudioItem[]
  formatSize: (bytes: number) => string
  persistenceKey?: string
}>(), {
  persistenceKey: 'default',
})

const emit = defineEmits<{
  updateStatus: [status: { figurineId?: string; mode?: string; isOnline?: boolean; mqttProfile?: string }]
}>()

function deviceStorageKey() {
  return `vpp_device_id:${props.persistenceKey}`
}

function generateDeviceId() {
  return `sim-dev-${Math.random().toString(36).slice(2, 8)}`
}

function loadSavedDeviceId() {
  try {
    const saved = localStorage.getItem(deviceStorageKey())
    if (saved) return saved
    const generated = generateDeviceId()
    localStorage.setItem(deviceStorageKey(), generated)
    return generated
  } catch {
    return generateDeviceId()
  }
}

function persistDeviceId(id: string) {
  try {
    localStorage.setItem(deviceStorageKey(), id)
  } catch {}
}

const deviceId = ref(loadSavedDeviceId())
const figurineId = ref('')
const mode = ref<'dialogue' | 'story' | 'music'>('dialogue')
const selectedAudioId = ref<string>('')
const selectedStoryId = ref<string>('')
const selectedMusicId = ref<string>('')
const mqttProfile = ref<'local' | 'relay' | 'custom' | 'aws_iot'>('local')
const mqttEnv  = ref('development')
const mqttHost = ref('localhost')
const mqttPort = ref<number | null | ''>(1883)
const mqttTls = ref<'default' | 'enabled' | 'disabled'>('disabled')
const mqttTlsCaCert = ref('')
const mqttTlsClientCert = ref('')
const mqttTlsClientKey = ref('')

const stories = ref<StoryItem[]>([])
const musicList = ref<MusicItem[]>([])
const loadingMedia = ref(false)

const ttsAudios = ref<GeneratedVoice[]>([])
const loadingTTS = ref(false)
const ttsAudioError = ref('')

const showInlineGenerator = ref(false)
const showLibraryBrowser = ref(false)
const libraryAudios = ref<GeneratedVoice[]>([])
const librarySearch = ref('')
const loadingLibrary = ref(false)

const RECENT_KEY = 'vpp_recent_audios'
const recentAudios = ref<GeneratedVoice[]>([])
const BROKER_KEY = 'vpp_mqtt_broker_config'

function loadRecentAudios() {
  try {
    const raw = localStorage.getItem(RECENT_KEY)
    if (raw) recentAudios.value = JSON.parse(raw)
  } catch {}
}

// ── 从后端获取 MQTT 默认配置（动态，不硬编码） ──
let _backendMqttDefaults: { env: string; host: string; port: number } | null = null

async function fetchBackendMqttDefaults() {
  try {
    const resp = await fetch('/api/debug/runtime-config')
    if (!resp.ok) return
    const data = await resp.json()
    const mqtt = data?.mqtt
    if (mqtt) {
      _backendMqttDefaults = {
        env: mqtt.env || 'development',
        host: mqtt.host || 'localhost',
        port: mqtt.port || 1883,
      }
    }
  } catch {}
}

function setLocalBrokerDefaults() {
  mqttProfile.value = 'local'
  mqttEnv.value = _backendMqttDefaults?.env || 'development'
  mqttHost.value = _backendMqttDefaults?.host || 'localhost'
  mqttPort.value = _backendMqttDefaults?.port || 1883
  mqttTls.value = 'disabled'
}

function applyBrokerProfile(profile: 'local' | 'relay' | 'custom' | 'aws_iot') {
  const previous = mqttProfile.value
  mqttProfile.value = profile

  if (profile === 'local') {
    setLocalBrokerDefaults()
    mqttTlsCaCert.value = ''
    mqttTlsClientCert.value = ''
    mqttTlsClientKey.value = ''
    return
  }

  if (profile === 'aws_iot') {
    // AWS IoT: TLS on, port 8883 by default
    mqttEnv.value = mqttEnv.value || 'development'
    mqttHost.value = mqttHost.value || ''
    mqttPort.value = mqttPort.value || 8883
    mqttTls.value = 'enabled'
    // TLS cert paths can be filled manually or auto-discovered by backend
    return
  }

  if (previous === 'local') {
    mqttEnv.value = ''
    mqttHost.value = ''
    mqttPort.value = null
    mqttTls.value = 'default'
  }
}

function loadBrokerConfig() {
  try {
    const raw = localStorage.getItem(BROKER_KEY)
    if (!raw) {
      setLocalBrokerDefaults()
      return
    }
    const parsed = JSON.parse(raw)
    mqttProfile.value = ['relay', 'custom', 'aws_iot'].includes(parsed.mqttProfile) ? parsed.mqttProfile : 'local'
    // local profile: 使用后端动态默认值，不从 localStorage 读取 env/host/port
    if (mqttProfile.value === 'local') {
      mqttEnv.value = _backendMqttDefaults?.env || 'development'
      mqttHost.value = _backendMqttDefaults?.host || 'localhost'
      mqttPort.value = _backendMqttDefaults?.port || 1883
    } else {
      mqttEnv.value = parsed.mqttEnv || ''
      mqttHost.value = parsed.mqttHost || ''
      mqttPort.value = typeof parsed.mqttPort === 'number' ? parsed.mqttPort : null
    }
    if (parsed.mqttTlsMode === 'enabled' || parsed.mqttTlsMode === 'disabled' || parsed.mqttTlsMode === 'default') {
      mqttTls.value = parsed.mqttTlsMode
    } else if (typeof parsed.mqttTls === 'boolean') {
      mqttTls.value = parsed.mqttTls ? 'enabled' : 'disabled'
    } else {
      mqttTls.value = mqttProfile.value === 'local' ? 'disabled' : (mqttProfile.value === 'aws_iot' ? 'enabled' : 'default')
    }
    if (mqttProfile.value === 'local') {
      mqttTls.value = 'disabled'
    }
    // Restore TLS cert paths
    if (parsed.mqttTlsCaCert) mqttTlsCaCert.value = parsed.mqttTlsCaCert
    if (parsed.mqttTlsClientCert) mqttTlsClientCert.value = parsed.mqttTlsClientCert
    if (parsed.mqttTlsClientKey) mqttTlsClientKey.value = parsed.mqttTlsClientKey
  } catch {}
}

function saveBrokerConfig() {
  try {
    localStorage.setItem(BROKER_KEY, JSON.stringify({
      mqttProfile: mqttProfile.value,
      mqttEnv: mqttEnv.value,
      mqttHost: mqttHost.value,
      mqttPort: mqttPort.value,
      mqttTlsMode: mqttTls.value,
      mqttTlsCaCert: mqttTlsCaCert.value,
      mqttTlsClientCert: mqttTlsClientCert.value,
      mqttTlsClientKey: mqttTlsClientKey.value,
    }))
  } catch {}
}

function saveRecentAudio(audio: GeneratedVoice) {
  recentAudios.value = recentAudios.value.filter(a => a.id !== audio.id)
  recentAudios.value.unshift(audio)
  if (recentAudios.value.length > 50) recentAudios.value = recentAudios.value.slice(0, 50)
  localStorage.setItem(RECENT_KEY, JSON.stringify(recentAudios.value))
}

const {
  isSimulating,
  isConnected,
  isConnecting,
  state,
  logs,
  sttResult,
  connectDevice,
  disconnectDevice,
  startSession,
  startSimulation,
  sendTurn,
  stopSimulation,
} = useMQTTSimulation()

watch(deviceId, (next) => {
  if (next) persistDeviceId(next)
})

function disconnectOnExit() {
  if (!isConnected.value && !isSimulating.value && !isConnecting.value) return
  void disconnectDevice()
}

if (typeof window !== 'undefined') {
  window.addEventListener('beforeunload', disconnectOnExit)
}

onBeforeUnmount(() => {
  if (typeof window !== 'undefined') {
    window.removeEventListener('beforeunload', disconnectOnExit)
  }
  disconnectOnExit()
})

const showDeviceInfo = ref(false)
const showTurnDetail = ref<string | null>(null)
const copiedSttIdx = ref<number | null>(null)
const isSendingTurn = ref(false)
const pendingSendTurnStepId = ref<string | null>(null)

const contextMenu = ref<{ x: number; y: number; visible: boolean }>({ x: 0, y: 0, visible: false })

const showOtaPanel = ref(false)
const showConfigPanel = ref(false)

const waveformTurnId = ref<string | null>(null)

const latestSessionStatus = computed(() => {
  const latest = [...logs.value].reverse().find(log => log.type === 'session_status')
  const status = latest?.payload?.status || (state.sessionId ? 'active' : 'idle')
  return String(status)
})

const latestIntroStatus = computed(() => {
  const latestStatus = [...logs.value].reverse().find(log => {
    const status = log.type === 'session_status' ? String(log.payload?.status || '') : ''
    return status.startsWith('intro_')
  })
  const status = String(latestStatus?.payload?.status || '')
  if (status === 'intro_complete') return 'completed'
  if (status === 'intro_timeout') return 'timeout'
  if (status === 'intro_playing') return 'playing'

  const introEvents = [...logs.value].reverse().filter(log => log.type === 'intro_start' || log.type === 'intro_end')
  const last = introEvents[0]
  if (!last) return 'waiting'
  return last.type === 'intro_end' ? 'completed' : 'playing'
})

function formatSessionStatus(status?: string): string {
  const map: Record<string, string> = {
    idle: '空闲',
    active: '活跃',
    connecting: '连接中',
    capturing: '录音中',
    playing: '播放中',
    completed: '已完成',
    error: '错误',
    turn_sent: '已发送',
    turn_completed: '已完成',
    session_closed: '已关闭',
    vad_retrying: 'VAD 重试中',
  }
  if (!status) return '未知'
  return map[status] || status
}

function formatIntroStatus(status?: string): string {
  const map: Record<string, string> = {
    waiting: '等待中',
    playing: '播放中',
    completed: '已完成',
    timeout: '超时',
  }
  if (!status) return '未知'
  return map[status] || status
}

const sessionStatusLabel = computed(() => formatSessionStatus(latestSessionStatus.value || state.lastSessionStatus || state.status))
const introStatusLabel = computed(() => formatIntroStatus(latestIntroStatus.value))

const canSendTurn = computed(() => !!getCurrentAudioId() && !!state.sessionId && (isConnected.value || isSimulating.value))

const liveFeedback = computed(() => {
  const stamp = state.lastEventAt
    ? new Intl.DateTimeFormat('zh-CN', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    }).format(state.lastEventAt)
    : ''

  const parts = []
  if (state.currentTurn > 0) parts.push(`Turn #${state.currentTurn}`)
  if (state.lastEventSummary) parts.push(state.lastEventSummary)
  if (!parts.length) parts.push(state.status === 'error' ? state.errorMessage || 'Flow error' : 'Waiting for turn updates')
  if (state.lastSessionStatus) parts.push(`Session: ${state.lastSessionStatus}`)
  if (state.lastSttText) parts.push(`STT: ${state.lastSttText}`)
  if (state.lastReplyText) parts.push(`Reply: ${state.lastReplyText}`)
  if (stamp) parts.push(`Updated: ${stamp}`)
  return parts
})

watch(
  () => state.lastSessionStatus,
  (nextStatus) => {
    if (!isSendingTurn.value || !pendingSendTurnStepId.value) return
    if (nextStatus === 'vad_retrying') {
      state.lastEventSummary = 'VAD 阻塞，正在切换 Profile 重试...'
      return
    }
    // Turn 完成：intro_complete = 开场白/回复播放完毕，capturing = VAD 重新开始（下一轮）
    // 也保留 completed/session_closed/error 作为会话级结束
    const turnDoneStatuses = ['turn_completed', 'completed', 'session_closed', 'error', 'intro_complete', 'capturing']
    if (turnDoneStatuses.includes(nextStatus || '')) {
      const stepId = pendingSendTurnStepId.value
      pendingSendTurnStepId.value = null
      isSendingTurn.value = false
      if (nextStatus === 'error') {
        failStep('session', stepId, state.errorMessage || '发送失败')
      } else {
        completeStep('session', stepId, state.lastEventSummary || '已收到回复')
      }
    }
  },
)

interface FigurineWithMediaCount extends FigurineConfig {
  story_count?: number
  music_count?: number
  has_intro?: boolean
}

const figurines = ref<FigurineWithMediaCount[]>([])
const loadingFigurines = ref(true)
const figurineError = ref('')

async function loadFigurines() {
  loadingFigurines.value = true
  figurineError.value = ''
  try {
    const resp = await fetchFigurines()
    figurines.value = resp.figurines

    initFlow()
    addStep('device', '设备激活', `设备 ID: ${deviceId.value}`)
    completeStep('device', '设备激活')
    addStep('device', 'MQTT 通道', '连接消息队列服务')
    completeStep('device', 'MQTT 通道')
    addStep('device', '设备就绪', '等待角色配置')
    completeStep('device', '设备就绪')

    // 让用户自己选择，不设默认值
  } catch (error: any) {
    console.error('Failed to load figurines:', error)
    figurineError.value = 'Failed to load figurines, please check the backend service.'
  } finally {
    loadingFigurines.value = false
  }
}

onMounted(async () => {
  await fetchBackendMqttDefaults()
  loadBrokerConfig()
  loadRecentAudios()
  loadFigurines()
})

const groupedAudios = computed(() => {
  const groups: { source: string; label: string; items: AudioItem[] }[] = []
  const sources = ['model', 'testdata', 'realtime']
  const labels: Record<string, string> = {
    model: '🤖 模型生成语音',
    testdata: '📁 测试数据语音',
    realtime: '🎤 实时录制语音',
  }
  
  for (const src of sources) {
    let items = props.audios.filter(a => a.source === src)
    if (mode.value === 'dialogue' && figurineId.value) {
      items = items.filter(a => a.figurine_id === figurineId.value)
    }
    if (items.length > 0) {
      items.sort((a, b) => b.duration - a.duration)
      groups.push({ source: src, label: labels[src] || src, items })
    }
  }
  return groups
})

async function loadStories() {
  loadingMedia.value = true
  try {
    const resp = await fetchStories(figurineId.value)
    stories.value = resp.stories
  } catch (error) {
    console.error('加载故事失败:', error)
  } finally {
    loadingMedia.value = false
  }
}

async function loadMusic() {
  loadingMedia.value = true
  try {
    const resp = await fetchMusic(figurineId.value)
    musicList.value = resp.music
  } catch (error) {
    console.error('加载音乐失败:', error)
  } finally {
    loadingMedia.value = false
  }
}

watch(mode, async (newMode) => {
  emit('updateStatus', { mode: newMode })
  if (newMode === 'dialogue' && figurineId.value) {
    await loadFigurineTTSAudios()
  } else if (newMode === 'story' && stories.value.length === 0) {
    await loadStories()
  } else if (newMode === 'music' && musicList.value.length === 0) {
    await loadMusic()
  }
})

watch(figurineId, (newVal) => {
  emit('updateStatus', { figurineId: newVal })
  
  if (newVal && flowStore.active) {
    // 切换角色时清空旧步骤
    const rolePhase = flowStore.phases.find(p => p.id === 'role')
    if (rolePhase) rolePhase.steps.splice(0)

    const fig = figurines.value.find(f => f.figurine_id === newVal)
    const charName = fig?.character_name || newVal
    const stepId = addStep('role', '角色信息加载', `加载角色 ${charName} 的配置`)
    setTimeout(() => {
      completeStep('role', stepId)
      if (fig && !fig.has_intro) {
        const nextId = addStep('role', '角色就绪', `🎁 ${charName} 无开场白配置，会话启动后由 LLM 处理`)
        completeStep('role', nextId)
      } else {
        const nextId = addStep('role', '角色连接成功', `🎁 ${charName} 就绪`)
        completeStep('role', nextId)
      }
    }, 500)
  }
  
  if (newVal && mode.value === 'dialogue') {
    loadFigurineTTSAudios()
  }

  // 模拟 NFC 碰触：设备已连接时，选角色自动触发 session/start + 开场白
  if (newVal && isConnected.value && !isSimulating.value) {
    startSession({ figurineId: newVal, mode: mode.value }).catch(err => {
      console.warn('[NFC] 自动启动会话失败:', err.message)
    })
  }
})

watch(() => state.isOnline, (newVal) => {
  emit('updateStatus', { isOnline: newVal })
})

watch(mqttProfile, (newVal) => {
  emit('updateStatus', { mqttProfile: newVal })
})

function getCurrentAudioId(): string {
  if (mode.value === 'dialogue') {
    return selectedAudioId.value
  } else if (mode.value === 'story') {
    return selectedStoryId.value
  } else {
    return selectedMusicId.value
  }
}

function getBrokerConfig() {
  const mqttTlsValue = mqttTls.value === 'default' ? undefined : mqttTls.value === 'enabled'
  const parsedPort = mqttPort.value === '' ? undefined : (
    typeof mqttPort.value === 'number' ? mqttPort.value : Number(mqttPort.value)
  )
  return {
    mqttProfile: mqttProfile.value,
    mqttEnv: mqttEnv.value.trim() || undefined,
    mqttHost: mqttHost.value.trim() || undefined,
    mqttPort: parsedPort !== undefined && Number.isFinite(parsedPort) ? parsedPort : undefined,
    mqttTls: mqttTlsValue,
    mqttTlsCaCert: mqttTlsCaCert.value.trim() || undefined,
    mqttTlsClientCert: mqttTlsClientCert.value.trim() || undefined,
    mqttTlsClientKey: mqttTlsClientKey.value.trim() || undefined,
  }
}

async function handleConnect() {
  const brokerLabel = mqttProfile.value === 'local'
    ? `本地 NanoMQ (${mqttHost.value.trim() || 'localhost'}${mqttPort.value ? `:${mqttPort.value}` : ':1883'})`
    : (mqttHost.value.trim()
      ? `${mqttHost.value.trim()}${mqttPort.value ? `:${mqttPort.value}` : ''}`
      : (mqttEnv.value.trim() || '默认 broker'))
  addStep('device', '设备连接', `连接 MQTT Broker: ${brokerLabel}`)
  saveBrokerConfig()
  try {
    await connectDevice({
      deviceId: deviceId.value,
      figurineId: figurineId.value,
      mode: mode.value,
      ...getBrokerConfig(),
    })
    completeStep('device', '设备连接', `${deviceId.value} 已上线`)
    // 连接成功后如果已选角色，自动触发 session/start（NFC 碰触）
    if (figurineId.value && !isSimulating.value) {
      startSession({ figurineId: figurineId.value, mode: mode.value }).catch(err => {
        console.warn('[Auto-NFC] 连接后自动启动会话失败:', err.message)
      })
    }
  } catch (err: any) {
    failStep('device', '设备连接', err.message || '连接失败')
  }
}

function handleDisconnect() {
  disconnectDevice()
}

function regenerateDeviceId() {
  if (isConnected.value || isSimulating.value || isConnecting.value) return
  const next = generateDeviceId()
  deviceId.value = next
  persistDeviceId(next)
}

async function handleStart() {
  if (!isConnected.value) {
    await handleConnect()
    if (!isConnected.value) return
  }

  const audioId = getCurrentAudioId()
  if (!audioId) {
    alert('请先选择音频')
    return
  }

  const brokerLabel = mqttProfile.value === 'local'
    ? `本地 NanoMQ (${mqttHost.value.trim() || 'localhost'}${mqttPort.value ? `:${mqttPort.value}` : ':1883'})`
    : (mqttHost.value.trim()
      ? `${mqttHost.value.trim()}${mqttPort.value ? `:${mqttPort.value}` : ''}`
      : (mqttEnv.value.trim() || '默认 broker'))
  addStep('session', 'MQTT 会话启动', `连接后端 MQTT Broker: ${brokerLabel}`)
  saveBrokerConfig()

  const sessionPhase = flowStore.phases.find(p => p.id === 'session')
  if (sessionPhase) sessionPhase.expanded = true

  try {
    await startSimulation({
      deviceId: deviceId.value,
      figurineId: figurineId.value,
      mode: mode.value,
      audioId: audioId,
      ...getBrokerConfig(),
    })

    completeStep('session', 'MQTT 会话启动', `Session ID: ${state.sessionId || ''}`)

    registerSimulation({
      deviceId: deviceId.value,
      figurineId: figurineId.value,
      mode: mode.value,
      logsRef: logs,
      sttResultRef: sttResult,
      state,
      isSimulatingRef: isSimulating,
    })

    startAutoDerive()

    const recent = ttsAudios.value.find(a => `tts/${a.id}` === audioId)
    if (recent) saveRecentAudio(recent)
  } catch (err: any) {
    failStep('session', 'MQTT 会话启动', err.message || '启动失败')
  }
}

async function handleSendTurn() {
  const audioId = getCurrentAudioId()
  if (!audioId) {
    alert('请先选择音频')
    return
  }
  if (!state.sessionId) {
    alert('请先等待会话建立完成')
    return
  }

  const phase = flowStore.phases.find(p => p.id === 'session')
  if (phase) phase.expanded = true

  addStep('session', '手动发送一轮', `audio_id: ${audioId}`)

  try {
    const resp = await sendTurn(audioId)
    const nextSessionId = resp?.session_id || state.sessionId
    if (nextSessionId) {
      completeStep('session', '手动发送一轮', `Session ID: ${nextSessionId}`)
    } else {
      completeStep('session', '手动发送一轮')
    }
  } catch (err: any) {
    failStep('session', '手动发送一轮', err.message || '发送失败')
  }
}

async function handleSendTurnWithFeedback() {
  const audioId = getCurrentAudioId()
  if (!audioId) {
    alert('请先选择音频')
    return
  }
  if (!state.sessionId) {
    alert('请先等待会话建立完成')
    return
  }

  const phase = flowStore.phases.find(p => p.id === 'session')
  if (phase) phase.expanded = true

  const stepId = addStep('session', '手动发送一轮', `audio_id: ${audioId} · 等待系统回复`)
  pendingSendTurnStepId.value = stepId || null
  isSendingTurn.value = true
  state.lastReplyText = undefined
  state.lastEventSummary = '请求已发出，等待设备回复'
  state.lastEventAt = new Date()
  state.lastSessionStatus = 'turn_sent'

  try {
    const resp = await sendTurn(audioId)
    const nextSessionId = resp?.session_id || state.sessionId
    if (nextSessionId && !state.sessionId) {
      state.sessionId = nextSessionId
    }
  } catch (err: any) {
    isSendingTurn.value = false
    pendingSendTurnStepId.value = null
    failStep('session', stepId || '手动发送一轮', err.message || '发送失败')
  }
}

function handleStop() {
  stopSimulation()
}

function toggleDeviceInfo() {
  showDeviceInfo.value = !showDeviceInfo.value
}

function toggleTurnDetail(turnId: string) {
  showTurnDetail.value = showTurnDetail.value === turnId ? null : turnId
}

async function copySttText(text: string, idx: number) {
  try {
    await navigator.clipboard.writeText(text)
    copiedSttIdx.value = idx
    setTimeout(() => { copiedSttIdx.value = null }, 1500)
  } catch {
    // fallback
  }
}

function onCardContextMenu(e: MouseEvent) {
  e.preventDefault()
  contextMenu.value = { x: e.clientX, y: e.clientY, visible: true }
  const handler = () => { contextMenu.value.visible = false; document.removeEventListener('click', handler) }
  document.addEventListener('click', handler)
}

function ctxCopySessionId() {
  if (state.sessionId) navigator.clipboard.writeText(state.sessionId).catch(() => {})
  contextMenu.value.visible = false
}

function ctxCopyDeviceId() {
  navigator.clipboard.writeText(deviceId.value).catch(() => {})
  contextMenu.value.visible = false
}

function ctxReconnect() {
  contextMenu.value.visible = false
  if (isConnected.value) {
    handleDisconnect()
    setTimeout(() => handleConnect(), 500)
  } else {
    handleConnect()
  }
}

function ctxClearLogs() {
  logs.value = []
  contextMenu.value.visible = false
}

function toggleOtaPanel() {
  showOtaPanel.value = !showOtaPanel.value
  showConfigPanel.value = false
}

function toggleConfigPanel() {
  showConfigPanel.value = !showConfigPanel.value
  showOtaPanel.value = false
}

function toggleWaveform(turnId: string) {
  waveformTurnId.value = waveformTurnId.value === turnId ? null : turnId
}

function turnStateLabel(s: TurnInfo['state']): string {
  const map: Record<TurnInfo['state'], string> = {
    capturing: 'capturing',
    uploading: 'uploading',
    thinking: 'thinking',
    playing: 'playing',
    draining: 'draining',
    done: 'done',
    aborted: 'aborted',
  }
  return map[s] || s
}

function turnTypeIcon(t: TurnInfo['type']): string {
  const map: Record<TurnInfo['type'], string> = { user: 'user', tts: 'tts', cue: 'cue', command: 'command' }
  return map[t] || 'unknown'
}

function turnDuration(turn: TurnInfo): string {
  if (!turn.endTime) return '...'
  const ms = turn.endTime.getTime() - turn.startTime.getTime()
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function heartbeatAge(): string {
  if (!state.lastHeartbeatAt) return 'no heartbeat'
  const sec = Math.round((Date.now() - state.lastHeartbeatAt.getTime()) / 1000)
  return sec < 60 ? `${sec}s ago` : `${Math.floor(sec / 60)}m${sec % 60}s ago`
}

const heartbeatAlive = computed(() => {
  if (!state.heartbeatActive || !state.lastHeartbeatAt) return false
  return (Date.now() - state.lastHeartbeatAt.getTime()) < 120_000
})

function fmtTime(d: Date | undefined): string {
  if (!d) return ''
  return d.toLocaleTimeString('zh-CN', { hour12: false })
}

function commandAge(cmd: CommandInfo): string {
  const sec = Math.round((Date.now() - cmd.timestamp.getTime()) / 1000)
  return sec < 60 ? `${sec}s` : `${Math.floor(sec / 60)}m${sec % 60}s`
}

const turnProgressPercent = (turn: TurnInfo): number => {
  if (turn.state === 'done') return 100
  if (turn.totalSeq && turn.totalSeq > 0) {
    const received = turn.type === 'user' ? turn.chunksSent : turn.chunksReceived
    return Math.min(95, Math.round((received / turn.totalSeq) * 100))
  }
  return 0
}

async function loadFigurineTTSAudios() {
  if (!figurineId.value) return
  loadingTTS.value = true
  ttsAudioError.value = ''
  try {
    const resp = await fetchFigurineTTSAudios(figurineId.value)
    const seen = new Set<number>()
    const merged: GeneratedVoice[] = []
    for (const a of recentAudios.value) {
      if (!seen.has(a.id)) { seen.add(a.id); merged.push(a) }
    }
    for (const a of resp.records) {
      if (!seen.has(a.id)) { seen.add(a.id); merged.push(a) }
    }
    ttsAudios.value = merged
  } catch (error: any) {
    console.error('Failed to load TTS audios:', error)
    ttsAudioError.value = 'Failed to load TTS audios'
  } finally {
    loadingTTS.value = false
  }
}

function onInlineGenerated(audioId: string) {
  selectedAudioId.value = audioId
  showInlineGenerator.value = false
  loadFigurineTTSAudios()
  const idNum = parseInt(audioId.replace('tts/', ''), 10)
  if (!isNaN(idNum)) {
    const found = ttsAudios.value.find(a => a.id === idNum)
    if (found) saveRecentAudio(found)
  }
}

async function openLibraryBrowser() {
  showLibraryBrowser.value = true
  loadingLibrary.value = true
  try {
    const resp = await fetchGeneratedVoices(200, 0)
    libraryAudios.value = resp.records
  } catch (error: any) {
    console.error('Failed to load voice library:', error)
  } finally {
    loadingLibrary.value = false
  }
}

function closeLibraryBrowser() {
  showLibraryBrowser.value = false
  librarySearch.value = ''
}

function selectFromLibrary(audio: GeneratedVoice) {
  selectedAudioId.value = `tts/${audio.id}`
  closeLibraryBrowser()
  if (!ttsAudios.value.find(a => a.id === audio.id)) {
    ttsAudios.value.unshift(audio)
  }
}

const filteredLibraryAudios = computed(() => {
  if (!librarySearch.value.trim()) return libraryAudios.value
  const q = librarySearch.value.toLowerCase()
  return libraryAudios.value.filter(a =>
    (a.name && a.name.toLowerCase().includes(q)) ||
    (a.text && a.text.toLowerCase().includes(q))
  )
})

const currentPreviewAudio = ref<HTMLAudioElement | null>(null)

function playTTSPreview(audio: GeneratedVoice) {
  if (currentPreviewAudio.value) {
    currentPreviewAudio.value.pause()
    currentPreviewAudio.value = null
  }
  const url = generatedAudioUrl(audio.id)
  const el = new Audio(url)
  el.play().catch(() => {})
  currentPreviewAudio.value = el
  el.onended = () => { currentPreviewAudio.value = null }
}

async function playPreview(type: 'audio' | 'story' | 'music', id: string) {
  const url = type === 'audio' 
    ? audioUrl(id)
    : mediaStreamUrl(id.replace('media_', ''))
  
  const loadingMsg = document.createElement('div')
  loadingMsg.style.cssText = `
    position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
    background: rgba(0, 0, 0, 0.8); color: white; padding: 20px 40px;
    border-radius: 8px; z-index: 9999; font-size: 16px;
  `
  loadingMsg.textContent = 'Loading...'
  document.body.appendChild(loadingMsg)
  
  try {
    const audio = new Audio(url)
    await audio.play()
    setTimeout(() => {
      if (document.body.contains(loadingMsg)) document.body.removeChild(loadingMsg)
    }, 1000)
  } catch (err) {
    console.error('Playback preview failed:', err)
    loadingMsg.textContent = 'Playback failed'
    setTimeout(() => {
      if (document.body.contains(loadingMsg)) document.body.removeChild(loadingMsg)
    }, 3000)
  }
}
</script>

<template>
  <div class="device-card" :class="{ online: state.isOnline }" @contextmenu="onCardContextMenu">
    <!-- 设备头部 -->
    <div class="card-header">
      <div class="header-left">
        <span class="device-id">{{ deviceId }}</span>
        <span class="proto-badge">v1.6</span>
        <span class="fw-badge">fw {{ state.fwVersion }}</span>
        <span class="status-badge" :class="state.status">
          {{ !isConnected && !isSimulating ? '⏹ 离线' :
             isConnecting ? '🔄 连接中' :
             state.status === 'idle' ? '⏸ 空闲' :
             state.status === 'connecting' ? '🔄 连接中' :
             state.status === 'active' ? '▶ 活跃' :
             state.status === 'capturing' ? '🎤️ 录音中' :
             state.status === 'playing' ? '🔊 播放中' :
             state.status === 'completed' ? '✅ 完成' :
             state.status === 'error' ? '❌ 错误' : '未知' }}
        </span>
      </div>
      
      <div class="header-right">
        <button
          v-if="isConnected || isSimulating"
          class="btn-icon info-btn"
          :class="{ active: showDeviceInfo }"
          @click="showDeviceInfo = !showDeviceInfo"
          title="会话信息"
        >
          i
        </button>
        <button v-if="state.heartbeatActive" class="btn-icon heartbeat-btn" :class="{ alive: heartbeatAlive }" @click="showDeviceInfo = !showDeviceInfo" title="心跳监控">
          {{ heartbeatAlive ? '' : '' }}
        </button>
        <button v-if="!isSimulating" class="btn-refresh" @click="regenerateDeviceId" title="刷新设备ID">
          🔄
        </button>
      </div>
    </div>

    <!-- 设备详情折叠区 -->
    <div v-if="showDeviceInfo && (isSimulating || isConnected)" class="device-info-panel">
      <div class="info-row">
        <span class="info-label">Session</span>
        <span class="info-value mono">{{ state.sessionId || '-' }}</span>
        <span class="info-label" style="margin-left:12px">状态</span>
        <span class="info-value">{{ sessionStatusLabel }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">Intro</span>
        <span class="info-value">{{ introStatusLabel }}</span>
        <span class="info-label" style="margin-left:12px">Heartbeat</span>
        <span class="info-value" :class="{ 'text-green': state.heartbeatActive, 'text-yellow': !state.heartbeatActive }">
          {{ state.heartbeatActive ? '开启' : '关闭' }}
        </span>
      </div>
      <div class="info-row">
        <span class="info-label">Turn</span>
        <span class="info-value">{{ state.currentTurn }}</span>
        <span class="info-label" style="margin-left:12px">Cue</span>
        <span class="info-value">{{ state.cueCount }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">❤️ 心跳</span>
        <span class="info-value" :class="{ 'text-green': heartbeatAlive, 'text-yellow': !heartbeatAlive }">
          {{ heartbeatAge() }}
        </span>
        <div v-if="state.heartbeatHistory.length > 1" class="hb-dots">
          <span v-for="(hb, i) in state.heartbeatHistory.slice(-10)" :key="i" class="hb-dot" />
        </div>
      </div>
      <div class="info-row">
        <span class="info-label">↑ Sent</span>
        <span class="info-value">{{ state.sentChunks }}</span>
        <span class="info-label" style="margin-left:12px">STT</span>
        <span class="info-value">{{ state.sttTexts.length }}</span>
        <span class="info-label" style="margin-left:12px">CMD</span>
        <span class="info-value">{{ state.commands.length }}</span>
      </div>
    </div>

    <!-- 角色选择 -->
    <div v-if="(isSimulating || isConnected) && (state.lastEventSummary || state.lastSessionStatus || state.lastSttText || state.lastReplyText)" class="live-feedback">
      <div class="live-feedback-head">
        <span class="live-feedback-title">Turn 反馈</span>
        <span class="live-feedback-badge" :class="state.status" :title="state.status">{{ formatSessionStatus(state.status) }}</span>
      </div>
      <div class="live-feedback-main">{{ liveFeedback[0] }}</div>
      <div class="live-feedback-line">
        <span class="live-feedback-label">Turn</span>
        <span class="mono">#{{ state.currentTurn || '-' }} · {{ state.lastSessionStatus || sessionStatusLabel }}</span>
      </div>
      <div class="live-feedback-line">
        <span class="live-feedback-label">进度</span>
        <span class="mono">会话: {{ sessionStatusLabel }} · Intro: {{ introStatusLabel }}</span>
      </div>
      <div v-if="isSendingTurn" class="live-feedback-line">
        <span class="live-feedback-label">当前</span>
        <span class="mono">{{ state.lastSessionStatus === 'vad_retrying' ? 'VAD 阻塞，正在自动重试' : '请求已发送，等待回复' }}</span>
      </div>
      <div v-if="state.lastSttText" class="live-feedback-line">
        <span class="live-feedback-label">STT</span>
        <span class="mono">{{ state.lastSttText }}</span>
      </div>
      <div v-if="state.lastReplyText" class="live-feedback-line">
        <span class="live-feedback-label">回复</span>
        <span class="mono">{{ state.lastReplyText }}</span>
      </div>
      <div v-if="state.lastAudioUrl" class="live-feedback-line" style="flex-direction:column;gap:4px">
        <div style="display:flex;align-items:center;gap:8px">
          <span class="live-feedback-label">Audio</span>
          <span class="mono" style="font-size:0.7rem;color:var(--text2)">{{ state.lastAudioUrl.split('/').pop() }}</span>
        </div>
        <audio :src="state.lastAudioUrl" controls style="width:100%;height:32px;margin-top:2px"></audio>
      </div>
    </div>

    <div class="config-section">
      <label>🎭 角色 (Figurine)</label>
      <div v-if="loadingFigurines" class="loading" style="padding:8px">加载角色列表中...</div>
      <div v-else-if="figurineError" class="error-message" style="padding:8px;margin:0">❌ {{ figurineError }}</div>
      <select v-else v-model="figurineId" class="select-input">
        <option value="" disabled>-- 请选择角色 --</option>
        <option v-for="fig in figurines" :key="fig.figurine_id" :value="fig.figurine_id">
          {{ fig.character_name }} ({{ fig.name }}) - 📚 {{ fig.story_count || 0 }} 🎵 {{ fig.music_count || 0 }}
        </option>
      </select>
    </div>

    <!-- 模式选择 -->
    <div class="config-section">
      <label>📣 设备模式</label>
      <div class="mode-buttons">
        <button :class="['mode-btn', { active: mode === 'dialogue' }]" @click="mode = 'dialogue'">💰 对话</button>
        <button :class="['mode-btn', { active: mode === 'story' }]" @click="mode = 'story'">📚 故事</button>
        <button :class="['mode-btn', { active: mode === 'music' }]" @click="mode = 'music'">🎵 音乐</button>
      </div>
    </div>

    <div class="config-section broker-section">
      <label>📳 MQTT Broker 配置</label>
      <div class="broker-grid">
        <select v-model="mqttProfile" class="search-input" @change="applyBrokerProfile(mqttProfile)">
          <option value="local">本地 NanoMQ</option>
          <option value="relay">Relay 中转</option>
          <option value="custom">自定义 Broker</option>
          <option value="aws_iot">AWS IoT Core</option>
        </select>
        <input v-model="mqttEnv" class="search-input" placeholder="环境前缀，如 development / prod" />
        <input v-model="mqttHost" class="search-input" placeholder="Broker Host / 端点地址" />
        <div class="broker-inline">
          <input v-model.number="mqttPort" type="number" min="1" max="65535" class="search-input broker-port" placeholder="1883 / 8883" />
          <select v-model="mqttTls" class="search-input broker-tls">
            <option value="default">TLS 跟随默认</option>
            <option value="enabled">TLS 开启</option>
            <option value="disabled">TLS 关闭</option>
          </select>
        </div>
        <!-- TLS 证书路径（仅 custom / aws_iot 显示） -->
        <template v-if="mqttProfile === 'custom' || mqttProfile === 'aws_iot'">
          <input v-model="mqttTlsCaCert" class="search-input" placeholder="CA 证书路径（可选，如 /certs/AmazonRootCA1.pem）" />
          <input v-model="mqttTlsClientCert" class="search-input" placeholder="设备证书路径（可选，如 /certs/device.cert.pem）" />
          <input v-model="mqttTlsClientKey" class="search-input" placeholder="私钥路径（可选，如 /certs/device.private.key）" />
        </template>
      </div>
      <div class="broker-hint">
        本地模式默认走 WSL NanoMQ；Relay / 自定义 / AWS IoT 可填远程 broker 参数。
        AWS IoT Core 使用 TLS 端口 8883，后端支持从 AWS_IOT_CERT_ROOT 自动发现证书。
      </div>
    </div>

    <!-- 内容选择 -->
    <div class="content-section">
      <template v-if="mode === 'dialogue'">
        <h4>📳 选择 TTS 音频</h4>
        <div class="tts-actions">
          <button class="btn-sm" @click="showInlineGenerator = !showInlineGenerator">
            {{ showInlineGenerator ? '✅ 关闭生成' : '✅ 生成新语音' }}
          </button>
          <button class="btn-sm btn-outline" @click="openLibraryBrowser">📨 音频库</button>
        </div>

        <div v-if="showInlineGenerator">
          <InlineGenerator :figurineId="figurineId" @generated="onInlineGenerated" />
        </div>

        <div v-if="loadingTTS" class="loading">加载 TTS 音频中...</div>
        <div v-else-if="ttsAudioError" class="error-message" style="margin-top:0">{{ ttsAudioError }}</div>
        <div v-else-if="ttsAudios.length === 0" class="empty-list">该角色暂无 TTS 音频，请生成或从音频库选择</div>
        <div v-else class="tts-list">
          <div v-for="audio in ttsAudios" :key="audio.id" class="content-item" :class="{ active: selectedAudioId === `tts/${audio.id}` }" @click="selectedAudioId = `tts/${audio.id}`">
            <div class="content-info">
              <div class="content-title">{{ audio.name }}</div>
              <div class="content-desc">{{ (audio.text || '').slice(0, 60) }}{{ (audio.text || '').length > 60 ? '...' : '' }}</div>
              <div class="content-meta">{{ audio.duration_sec ? `${audio.duration_sec.toFixed(1)}s` : '' }} · {{ audio.gender }} / {{ audio.personality }}</div>
            </div>
            <button class="btn-play-sm" @click.stop="playTTSPreview(audio)" title="preview">▶</button>
          </div>
        </div>
      </template>

      <template v-else-if="mode === 'story'">
        <h4>📚 选择故事</h4>
        <div v-if="loadingMedia" class="loading">加载中...</div>
        <div v-else-if="stories.length === 0" class="empty-list">暂无故事数据</div>
        <div v-else>
          <div v-for="story in stories" :key="story.id" class="content-item" :class="{ active: selectedStoryId === story.id }" @click="selectedStoryId = story.id">
            <div class="content-info">
              <div class="content-title">{{ story.title }}</div>
              <div class="content-desc">{{ story.description }}</div>
              <div class="content-meta">{{ story.duration }}s</div>
            </div>
            <button class="btn-play" @click.stop="playPreview('story', story.id)" title="preview">▶</button>
          </div>
        </div>
      </template>

      <template v-else-if="mode === 'music'">
        <h4>🎵 选择音乐</h4>
        <div v-if="loadingMedia" class="loading">加载中...</div>
        <div v-else-if="musicList.length === 0" class="empty-list">暂无音乐数据</div>
        <div v-else>
          <div v-for="music in musicList" :key="music.id" class="content-item" :class="{ active: selectedMusicId === music.id }" @click="selectedMusicId = music.id">
            <div class="content-info">
              <div class="content-title">{{ music.title }}</div>
              <div class="content-desc">{{ music.artist }}</div>
              <div class="content-meta">{{ music.duration }}s</div>
            </div>
            <button class="btn-play" @click.stop="playPreview('music', music.id)" title="preview">▶</button>
          </div>
        </div>
      </template>
    </div>

    <!-- ═══ v1.6 信息面板（模拟中显示）═══ -->
    <template v-if="isSimulating">
      <!-- 活跃 Turn 折叠区 -->
      <div class="v16-section">
        <div class="v16-header" @click="toggleDeviceInfo">
          <span>▶ 活跃 Turn ({{ state.activeTurns.length }})</span>
          <span v-if="state.cueCount > 0" class="cue-badge">📨 {{ state.cueCount }} cue</span>
        </div>
        <div v-if="showDeviceInfo || state.activeTurns.length > 0" class="v16-body">
          <div v-if="state.activeTurns.length === 0" class="v16-empty">暂无活跃 Turn</div>
          <div
            v-for="turn in state.activeTurns.slice(-10).reverse()"
            :key="turn.turnId"
            class="turn-row"
            :class="{ 'turn-expanded': showTurnDetail === turn.turnId }"
            @click="toggleTurnDetail(turn.turnId)"
          >
            <div class="turn-summary">
              <span class="turn-icon">{{ turnTypeIcon(turn.type) }}</span>
              <span class="turn-id">{{ turn.turnId }}</span>
              <span class="turn-state-badge" :class="turn.state">{{ turnStateLabel(turn.state) }}</span>
              <span v-if="turn.type === 'user'" class="turn-chunks">↑ {{ turn.chunksSent }}</span>
              <span v-else class="turn-chunks">↓ {{ turn.chunksReceived }}</span>
              <span class="turn-duration">{{ turnDuration(turn) }}</span>
              <div v-if="turn.state === 'playing' && turn.totalSeq" class="turn-progress-bar">
                <div class="turn-progress-fill" :style="{ width: turnProgressPercent(turn) + '%' }" />
              </div>
            </div>
            <div v-if="showTurnDetail === turn.turnId" class="turn-detail">
              <div class="detail-row"><span class="detail-label">Type</span><span>{{ turn.type }}</span></div>
              <div class="detail-row"><span class="detail-label">State</span><span>{{ turn.state }}</span></div>
              <div class="detail-row"><span class="detail-label">Start</span><span>{{ fmtTime(turn.startTime) }}</span></div>
              <div v-if="turn.endTime" class="detail-row"><span class="detail-label">End</span><span>{{ fmtTime(turn.endTime) }}</span></div>
              <div v-if="turn.sttText" class="detail-row"><span class="detail-label">STT</span><span class="stt-in-detail">{{ turn.sttText }}</span></div>
              <div v-if="turn.totalSeq" class="detail-row"><span class="detail-label">Total Seq</span><span>{{ turn.totalSeq }}</span></div>
              <div v-if="turn.durationMs" class="detail-row"><span class="detail-label">Duration</span><span>{{ turn.durationMs }}ms</span></div>
              <button class="btn-sm" style="margin-top:6px" @click.stop="toggleWaveform(turn.turnId)">
                {{ waveformTurnId === turn.turnId ? '隐藏波形' : '📊 查看波形' }}
              </button>
              <div v-if="waveformTurnId === turn.turnId" class="waveform-placeholder">
                <div class="waveform-bars">
                  <div v-for="i in 32" :key="i" class="waveform-bar" :style="{ height: Math.random() * 100 + '%' }" />
                </div>
                <span class="waveform-label">模拟波形 ({{ turn.chunksReceived || turn.chunksSent }} frames)</span>
              </div>
            </div>
          </div>
        </div>
      </div>

      <!-- STT 文本折叠区 -->
      <div class="v16-section">
        <div class="v16-header">
          <span>📝 STT 文本 ({{ state.sttTexts.length }})</span>
        </div>
        <div class="v16-body">
          <div v-if="state.sttTexts.length === 0" class="v16-empty">暂无 STT 文本</div>
          <div v-for="(text, idx) in state.sttTexts.slice(-10)" :key="idx" class="stt-row" @click="copySttText(text, idx)">
            <span class="stt-index">#{{ idx + 1 }}</span>
            <span class="stt-text">{{ text }}</span>
            <span class="stt-copy">{{ copiedSttIdx === idx ? '✔' : '🔍' }}</span>
          </div>
        </div>
      </div>

      <!-- Command 折叠区 -->
      <div class="v16-section">
        <div class="v16-header">
          <span>📋 Command ({{ state.commands.length }})</span>
        </div>
        <div class="v16-body">
          <div v-if="state.commands.length === 0" class="v16-empty">暂无 Command</div>
          <div v-for="(cmd, idx) in state.commands.slice(-10).reverse()" :key="idx" class="cmd-row" :class="{ preempt: cmd.preempt, after_audio: cmd.afterAudio }">
            <span v-if="cmd.preempt" class="cmd-badge preempt">📢 PREEMPT</span>
            <span v-else-if="cmd.afterAudio" class="cmd-badge after">🎵 AFTER</span>
            <span v-else class="cmd-badge normal">📌</span>
            <span class="cmd-name">{{ cmd.cmd }}</span>
            <span v-if="cmd.turnId" class="cmd-turn">turn={{ cmd.turnId }}</span>
            <span class="cmd-age">{{ commandAge(cmd) }}</span>
          </div>
        </div>
      </div>

      <!-- OTA / 配置状态 -->
      <div class="v16-section">
        <div class="v16-header">
          <span>
            <button class="btn-tab" :class="{ active: showOtaPanel }" @click.stop="toggleOtaPanel">📝 OTA</button>
            <button class="btn-tab" :class="{ active: showConfigPanel }" @click.stop="toggleConfigPanel">⚙️ Config</button>
          </span>
        </div>
        <div v-if="showOtaPanel" class="v16-body">
          <div class="detail-row"><span class="detail-label">当前版本</span><span>{{ state.otaStatus.currentVersion }}</span></div>
          <div v-if="state.otaStatus.targetVersion" class="detail-row"><span class="detail-label">目标版本</span><span>{{ state.otaStatus.targetVersion }}</span></div>
          <div class="detail-row">
            <span class="detail-label">Status</span>
            <span :class="{
              'text-green': state.otaStatus.status === 'success',
              'text-yellow': state.otaStatus.status === 'downloading',
              'text-red': state.otaStatus.status === 'failed',
            }">{{ state.otaStatus.status }}</span>
          </div>
        </div>
        <div v-if="showConfigPanel" class="v16-body">
          <div class="detail-row"><span class="detail-label">版本</span><span>{{ state.configStatus.ver }}</span></div>
          <div class="detail-row">
            <span class="detail-label">Status</span>
            <span :class="{
              'text-green': state.configStatus.status === 'applied',
              'text-yellow': state.configStatus.status === 'applying',
              'text-red': state.configStatus.status === 'failed',
            }">{{ state.configStatus.status }}</span>
          </div>
        </div>
      </div>
    </template>

    <!-- 控制按钮 -->
    <div class="control-section">
      <template v-if="!isConnected && !isSimulating">
        <button class="btn-connect" :disabled="isConnecting" @click="handleConnect">
          {{ isConnecting ? '🔄 连接中...' : '🔲 连接设备' }}
        </button>
      </template>
      <template v-else-if="isConnected && !isSimulating">
        <button class="btn-start" :disabled="!getCurrentAudioId()" @click="handleStart">▶ Start</button>
        <button class="btn-send-turn" :disabled="!canSendTurn || isSendingTurn" @click="handleSendTurnWithFeedback">{{ isSendingTurn ? (state.lastSessionStatus === 'vad_retrying' ? '🔄 VAD 重试中...' : '⏳ 等待回复...') : '📣 Send Turn' }}</button>
        <button class="btn-disconnect" @click="handleDisconnect">🔲 断开设备</button>
      </template>
      <template v-else-if="isSimulating">
        <button class="btn-stop" @click="handleStop">🔶 停止模拟</button>
        <button class="btn-send-turn" :disabled="!canSendTurn || isSendingTurn" @click="handleSendTurnWithFeedback">{{ isSendingTurn ? (state.lastSessionStatus === 'vad_retrying' ? '🔄 VAD 重试中...' : '⏳ 等待回复...') : '📣 Send Turn' }}</button>
      </template>
    </div>

    <div v-if="state.errorMessage" class="error-message">❌ {{ state.errorMessage }}</div>

    <!-- 音频库浏览器弹窗 -->
    <div v-if="showLibraryBrowser" class="modal-overlay" @click.self="closeLibraryBrowser">
      <div class="modal-content">
        <div class="modal-header">
          <h3>TTS Audio Library</h3>
          <button class="modal-close" @click="closeLibraryBrowser">✕</button>
        </div>
        <div class="modal-search">
          <input v-model="librarySearch" class="search-input" placeholder="搜索音频名称或文本..." />
        </div>
        <div class="modal-body">
          <div v-if="loadingLibrary" class="modal-loading">加载中...</div>
          <div v-else-if="filteredLibraryAudios.length === 0" class="modal-empty">No matching audio</div>
          <div v-else class="modal-list">
            <div v-for="audio in filteredLibraryAudios" :key="audio.id" class="modal-item" :class="{ active: selectedAudioId === `tts/${audio.id}` }" @click="selectFromLibrary(audio)">
              <div class="modal-item-info">
                <div class="modal-item-name">{{ audio.name }}</div>
                <div class="modal-item-text">{{ (audio.text || '').slice(0, 80) }}</div>
                <div class="modal-item-meta">
                  {{ audio.duration_sec ? `${audio.duration_sec.toFixed(1)}s` : '' }}
                  {{ audio.gender }} / {{ audio.personality }}
                  {{ audio.created_at ? ` · ${new Date(audio.created_at).toLocaleDateString()}` : '' }}
                </div>
              </div>
              <button class="btn-play-sm" @click.stop="playTTSPreview(audio)" title="preview">▶</button>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <span>{{ filteredLibraryAudios.length }} / {{ libraryAudios.length }} items</span>
          <button class="btn-close" @click="closeLibraryBrowser">关闭</button>
        </div>
      </div>
    </div>

    <!-- 右键上下文菜单 -->
    <div v-if="contextMenu.visible" class="ctx-menu" :style="{ left: contextMenu.x + 'px', top: contextMenu.y + 'px' }">
      <button v-if="state.sessionId" class="ctx-item" @click="ctxCopySessionId">📋 复制 Session ID</button>
      <button class="ctx-item" @click="ctxCopyDeviceId">📋 复制 Device ID</button>
      <button v-if="!isSimulating" class="ctx-item" @click="ctxReconnect">🔄 重新连接</button>
      <button class="ctx-item" @click="ctxClearLogs">🗑️ 清除日志</button>
    </div>
  </div>
</template>

<style scoped>
.device-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
  margin-bottom: 16px;
  transition: all 0.2s;
  position: relative;
}

.device-card.online {
  border-color: var(--green);
  box-shadow: 0 0 0 1px var(--green);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
  padding-bottom: 12px;
  border-bottom: 1px solid var(--border);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 6px;
}

.device-id {
  font-family: 'Courier New', monospace;
  font-size: 0.85rem;
  color: var(--text);
}

.proto-badge {
  font-size: 0.65rem;
  padding: 1px 6px;
  border-radius: 8px;
  background: #1a3a2a;
  color: #4ade80;
  font-weight: 600;
}

.fw-badge {
  font-size: 0.65rem;
  padding: 1px 6px;
  border-radius: 8px;
  background: #2a2a3a;
  color: #a0a0c0;
}

.status-badge {
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 12px;
  background: var(--surface2);
}

.status-badge.idle { color: var(--text2); }
.status-badge.connecting { color: var(--orange); }
.status-badge.active { color: var(--green); }
.status-badge.capturing { color: #60a5fa; }
.status-badge.playing { color: #a78bfa; }
.status-badge.completed { color: var(--accent); }
.status-badge.error { color: var(--red); }

.btn-icon {
  background: none;
  border: none;
  font-size: 1rem;
  cursor: pointer;
  padding: 2px 4px;
  border-radius: 4px;
  transition: all 0.15s;
}

.btn-icon:hover { background: var(--surface2); }
.btn-icon.active { background: var(--surface2); color: var(--accent); }

.heartbeat-btn.alive { animation: hb-pulse 2s infinite; }

@keyframes hb-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

.btn-refresh {
  background: none;
  border: none;
  font-size: 1.2rem;
  cursor: pointer;
  opacity: 0.6;
  transition: opacity 0.2s;
}

.btn-refresh:hover { opacity: 1; }

/* ── 设备详情面板 ── */
.device-info-panel {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 10px 14px;
  margin-bottom: 12px;
}

.live-feedback {
  margin-bottom: 12px;
  padding: 12px 14px;
  border-radius: 10px;
  border: 1px solid rgba(245, 158, 11, 0.35);
  background: linear-gradient(135deg, rgba(245, 158, 11, 0.18), rgba(15, 23, 42, 0.8));
  box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.04);
}

.live-feedback-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 8px;
}

.live-feedback-title {
  font-size: 0.78rem;
  font-weight: 700;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: #fde68a;
}

.live-feedback-badge {
  font-size: 0.72rem;
  padding: 3px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: var(--text2);
  text-transform: uppercase;
}

.live-feedback-badge.error {
  color: #fecaca;
  background: rgba(239, 68, 68, 0.18);
}

.live-feedback-main {
  font-size: 0.92rem;
  color: var(--text);
  line-height: 1.5;
  margin-bottom: 10px;
}

.live-feedback-line {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  margin-top: 4px;
  color: var(--text2);
  font-size: 0.8rem;
}

.live-feedback-label {
  min-width: 42px;
  color: #fbbf24;
  font-weight: 600;
}

.info-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  font-size: 0.8rem;
}

.info-label {
  color: var(--text2);
  min-width: 60px;
  font-size: 0.75rem;
}

.info-value {
  color: var(--text);
  font-weight: 500;
}

.info-value.mono {
  font-family: 'Courier New', monospace;
  font-size: 0.75rem;
}

.text-green { color: var(--green); }
.text-yellow { color: var(--orange); }
.text-red { color: var(--red); }

.hb-dots {
  display: flex;
  gap: 3px;
  margin-left: 8px;
}

.hb-dot {
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: var(--green);
}

/* ── v1.6 信息面板 ── */
.v16-section {
  margin-top: 12px;
  border: 1px solid var(--border);
  border-radius: 8px;
  overflow: hidden;
}

.v16-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  background: var(--surface2);
  font-size: 0.8rem;
  color: var(--text2);
  cursor: pointer;
  user-select: none;
}

.v16-header:hover { background: var(--bg2); }

.v16-body {
  padding: 8px;
}

.v16-empty {
  text-align: center;
  color: var(--text2);
  padding: 8px;
  font-size: 0.78rem;
}

.cue-badge {
  font-size: 0.7rem;
  padding: 1px 6px;
  border-radius: 8px;
  background: #3a2a1a;
  color: #fbbf24;
}

/* ── Turn 行 ── */
.turn-row {
  padding: 8px 10px;
  margin-bottom: 4px;
  background: var(--surface2);
  border: 1px solid transparent;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.turn-row:hover { border-color: var(--accent); }
.turn-row.turn-expanded { border-color: var(--accent); background: #1b2340; }

.turn-summary {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.8rem;
}

.turn-icon { font-size: 0.9rem; }

.turn-id {
  font-family: 'Courier New', monospace;
  color: var(--text);
  font-weight: 600;
  min-width: 50px;
}

.turn-state-badge {
  font-size: 0.68rem;
  padding: 1px 6px;
  border-radius: 8px;
  background: #2a2a3a;
}

.turn-state-badge.done { background: #1a3a2a; color: var(--green); }
.turn-state-badge.playing { background: #2a1a3a; color: #a78bfa; }
.turn-state-badge.uploading { background: #1a2a3a; color: #60a5fa; }
.turn-state-badge.thinking { background: #3a3a1a; color: #fbbf24; }
.turn-state-badge.aborted { background: #3a1a1a; color: var(--red); }

.turn-chunks { color: var(--text2); font-size: 0.72rem; }
.turn-duration { color: var(--text2); font-size: 0.72rem; margin-left: auto; }

.turn-progress-bar {
  width: 60px;
  height: 4px;
  background: var(--border);
  border-radius: 2px;
  overflow: hidden;
  margin-left: 6px;
}

.turn-progress-fill {
  height: 100%;
  background: var(--accent);
  border-radius: 2px;
  transition: width 0.3s ease;
}

.turn-detail {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
}

.detail-row {
  display: flex;
  justify-content: space-between;
  padding: 3px 0;
  font-size: 0.75rem;
}

.detail-label { color: var(--text2); min-width: 80px; }

.stt-in-detail {
  color: var(--text);
  font-style: italic;
  word-break: break-all;
}

/* ── 波形预览 ── */
.waveform-placeholder {
  margin-top: 8px;
  padding: 10px;
  background: var(--surface);
  border-radius: 6px;
}

.waveform-bars {
  display: flex;
  align-items: flex-end;
  gap: 2px;
  height: 40px;
}

.waveform-bar {
  flex: 1;
  background: var(--accent);
  border-radius: 1px 1px 0 0;
  min-height: 2px;
  opacity: 0.7;
}

.waveform-label {
  display: block;
  text-align: center;
  font-size: 0.68rem;
  color: var(--text2);
  margin-top: 4px;
}

/* ── STT 文本行 ── */
.stt-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  margin-bottom: 3px;
  background: var(--surface2);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
  font-size: 0.8rem;
}

.stt-row:hover { background: #1b2340; }

.stt-index {
  color: var(--text2);
  font-size: 0.72rem;
  min-width: 24px;
}

.stt-text {
  flex: 1;
  color: var(--text);
  word-break: break-all;
}

.stt-copy {
  font-size: 0.75rem;
  opacity: 0.5;
  transition: opacity 0.2s;
}

.stt-row:hover .stt-copy { opacity: 1; }

/* ── Command 行 ── */
.cmd-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  margin-bottom: 3px;
  background: var(--surface2);
  border-radius: 6px;
  font-size: 0.8rem;
}

.cmd-row.preempt { border-left: 3px solid var(--red); }
.cmd-row.after_audio { border-left: 3px solid #fbbf24; }

.cmd-badge {
  font-size: 0.68rem;
  padding: 1px 6px;
  border-radius: 8px;
}

.cmd-badge.preempt { background: #3a1a1a; color: var(--red); }
.cmd-badge.after { background: #3a3a1a; color: #fbbf24; }
.cmd-badge.normal { background: #1a2a3a; color: #60a5fa; }

.cmd-name { color: var(--text); font-weight: 600; }
.cmd-turn { color: var(--text2); font-size: 0.72rem; }
.cmd-age { color: var(--text2); font-size: 0.72rem; margin-left: auto; }

/* ── OTA / Config 按钮 ── */
.btn-tab {
  background: none;
  border: 1px solid transparent;
  color: var(--text2);
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 4px;
  cursor: pointer;
  margin-right: 4px;
}

.btn-tab:hover { border-color: var(--border); color: var(--text); }
.btn-tab.active { border-color: var(--accent); color: var(--accent); background: #1a1a2a; }

/* ── 右键菜单 ── */
.ctx-menu {
  position: fixed;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 6px 0;
  min-width: 180px;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.4);
  z-index: 2000;
}

.ctx-item {
  display: block;
  width: 100%;
  text-align: left;
  background: none;
  border: none;
  color: var(--text);
  padding: 8px 16px;
  font-size: 0.82rem;
  cursor: pointer;
  transition: background 0.1s;
}

.ctx-item:hover { background: var(--surface2); }

/* ── 通用样式 ── */
.config-section {
  margin-bottom: 16px;
}

.config-section label {
  display: block;
  font-size: 0.85rem;
  color: var(--text2);
  margin-bottom: 6px;
}

.broker-grid {
  display: grid;
  gap: 8px;
}

.broker-inline {
  display: flex;
  align-items: center;
  gap: 10px;
}

.broker-port {
  width: 140px;
  flex: 0 0 140px;
}

.broker-tls {
  flex: 1;
}

.broker-hint {
  margin-top: 6px;
  color: var(--text2);
  font-size: 0.75rem;
  line-height: 1.4;
}

.select-input {
  width: 100%;
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.9rem;
}

.mode-buttons {
  display: flex;
  gap: 8px;
}

.mode-btn {
  flex: 1;
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text2);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.85rem;
  cursor: pointer;
  transition: all 0.15s;
}

.mode-btn:hover { border-color: var(--accent); }

.mode-btn.active {
  background: var(--accent2);
  border-color: var(--accent);
  color: #fff;
}

.content-section h4 {
  font-size: 0.9rem;
  margin-bottom: 12px;
  color: var(--text);
}

.audio-item,
.content-item {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 8px;
  cursor: pointer;
  transition: all 0.15s;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.audio-item:hover,
.content-item:hover { border-color: var(--accent); }

.audio-item.active,
.content-item.active {
  border-color: var(--accent);
  background: #1b2340;
}

.audio-info,
.content-info { flex: 1; }

.audio-name,
.content-title {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 4px;
}

.audio-meta,
.content-desc,
.content-meta {
  font-size: 0.75rem;
  color: var(--text2);
}

.btn-play {
  background: none;
  border: none;
  font-size: 1.2rem;
  cursor: pointer;
  opacity: 0.6;
  transition: opacity 0.2s;
  padding: 4px 8px;
}

.btn-play:hover { opacity: 1; }

.loading,
.empty-list {
  text-align: center;
  color: var(--text2);
  padding: 20px;
  font-size: 0.85rem;
}

.control-section {
  margin-top: 20px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.btn-start,
.btn-stop,
.btn-restart,
.btn-connect,
.btn-disconnect,
.btn-send-turn {
  width: 100%;
  padding: 12px;
  border: none;
  border-radius: var(--radius);
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-start { background: var(--green); color: #fff; }
.btn-start:hover:not(:disabled) { background: #3d9b65; }
.btn-start:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-stop { background: var(--red); color: #fff; }
.btn-stop:hover { background: #c4443f; }

.btn-restart { background: var(--accent); color: #fff; }
.btn-restart:hover:not(:disabled) { background: var(--accent2); }
.btn-restart:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-connect { background: #4a90d9; color: #fff; }
.btn-connect:hover:not(:disabled) { background: #3a7bc8; }
.btn-connect:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-send-turn {
  background: linear-gradient(135deg, #f59e0b, #f97316);
  color: #fff;
}
.btn-send-turn:hover:not(:disabled) { background: linear-gradient(135deg, #f59e0b, #ea580c); }
.btn-send-turn:disabled { opacity: 0.5; cursor: not-allowed; }

.btn-disconnect {
  background: transparent;
  color: var(--text-muted);
  border: 1px solid var(--border);
  margin-top: 6px;
  padding: 8px;
  font-size: 0.85rem;
}
.btn-disconnect:hover { background: var(--hover); color: var(--red); }

.error-message {
  margin-top: 12px;
  padding: 10px;
  background: #2a1515;
  border: 1px solid #4a2020;
  color: var(--red);
  border-radius: 6px;
  font-size: 0.85rem;
}

.tts-actions {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}

.btn-sm {
  flex: 1;
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 7px 12px;
  border-radius: 6px;
  font-size: 0.82rem;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-sm:hover { border-color: var(--accent); background: var(--accent2); color: #fff; }

.btn-outline { background: transparent; }

.tts-list {
  max-height: 300px;
  overflow-y: auto;
}

.btn-play-sm {
  background: none;
  border: none;
  font-size: 1rem;
  cursor: pointer;
  opacity: 0.5;
  transition: opacity 0.2s;
  padding: 4px 8px;
  flex-shrink: 0;
}

.btn-play-sm:hover { opacity: 1; }

.modal-overlay {
  position: fixed;
  top: 0;
  left: 0;
  right: 0;
  bottom: 0;
  background: rgba(0, 0, 0, 0.65);
  z-index: 1000;
  display: flex;
  align-items: center;
  justify-content: center;
}

.modal-content {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  width: 90%;
  max-width: 520px;
  max-height: 80vh;
  display: flex;
  flex-direction: column;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.4);
}

.modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 16px 20px 0;
}

.modal-header h3 { margin: 0; font-size: 1rem; color: var(--text); }

.modal-close {
  background: none;
  border: none;
  color: var(--text2);
  font-size: 1.2rem;
  cursor: pointer;
  padding: 4px;
}

.modal-close:hover { color: var(--text); }

.modal-search { padding: 12px 20px; }

.search-input {
  width: 100%;
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 8px 12px;
  border-radius: 6px;
  font-size: 0.85rem;
  box-sizing: border-box;
}

.search-input:focus { outline: none; border-color: var(--accent); }

.modal-body {
  flex: 1;
  overflow-y: auto;
  padding: 0 20px;
}

.modal-loading,
.modal-empty {
  text-align: center;
  color: var(--text2);
  padding: 30px;
  font-size: 0.85rem;
}

.modal-list { padding-bottom: 12px; }

.modal-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 10px 12px;
  margin-bottom: 6px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.15s;
}

.modal-item:hover { border-color: var(--accent); }
.modal-item.active { border-color: var(--accent); background: #1b2340; }

.modal-item-info { flex: 1; min-width: 0; }

.modal-item-name {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 2px;
}

.modal-item-text {
  font-size: 0.78rem;
  color: var(--text2);
  margin-bottom: 2px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.modal-item-meta {
  font-size: 0.72rem;
  color: var(--text2);
  opacity: 0.7;
}

.modal-footer {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 20px;
  border-top: 1px solid var(--border);
  font-size: 0.8rem;
  color: var(--text2);
}

.btn-close {
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 6px 16px;
  border-radius: 5px;
  cursor: pointer;
  font-size: 0.82rem;
}

.btn-close:hover { border-color: var(--accent); }
</style>


