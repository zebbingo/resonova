<script setup lang="ts">
import { ref, computed, watch, onMounted, nextTick } from 'vue'
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

const props = defineProps<{
  audios: AudioItem[]
  formatSize: (bytes: number) => string
}>()

const emit = defineEmits<{
  updateStatus: [status: { figurineId?: string; mode?: string; isOnline?: boolean }]
}>()

const deviceId = ref(`sim-dev-${Math.random().toString(36).substr(2, 6)}`)
const figurineId = ref('')
const mode = ref<'dialogue' | 'story' | 'music'>('dialogue')
const selectedAudioId = ref<string>('')
const selectedStoryId = ref<string>('')
const selectedMusicId = ref<string>('')

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

const {
  isSimulating,
  isConnected,
  isConnecting,
  state,
  logs,
  sttResult,
  connectDevice,
  disconnectDevice,
  startSimulation,
  stopSimulation,
} = useMQTTSimulation()

const showDeviceInfo = ref(false)
const showTurnDetail = ref<string | null>(null)
const copiedSttIdx = ref<number | null>(null)

const contextMenu = ref<{ x: number; y: number; visible: boolean }>({ x: 0, y: 0, visible: false })

const showOtaPanel = ref(false)
const showConfigPanel = ref(false)

const waveformTurnId = ref<string | null>(null)

interface FigurineWithMediaCount extends FigurineConfig {
  story_count?: number
  music_count?: number
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
    addStep('device', 'MQTT 通讯通道', '连接消息队列服务')
    completeStep('device', 'MQTT 通讯通道')
    addStep('device', '设备就绪', '等待角色配置')
    completeStep('device', '设备就绪')
    
    if (resp.figurines.length > 0 && !figurineId.value) {
      figurineId.value = resp.figurines[0].figurine_id
    }
  } catch (error: any) {
    console.error('加载角色列表失败:', error)
    figurineError.value = '加载角色失败，请检查后端服务'
  } finally {
    loadingFigurines.value = false
  }
}

onMounted(() => { loadFigurines() })

const groupedAudios = computed(() => {
  const groups: { source: string; label: string; items: AudioItem[] }[] = []
  const sources = ['model', 'testdata', 'realtime']
  const labels: Record<string, string> = {
    model: '📦 模型测试',
    testdata: '🧪 项目测试',
    realtime: '🎙️ 真实录音',
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
    const fig = figurines.value.find(f => f.figurine_id === newVal)
    const charName = fig?.character_name || newVal
    addStep('role', `角色信息加载`, `加载角色 ${charName} 的配置`)
    setTimeout(() => {
      completeStep('role', `角色信息加载`)
      addStep('role', `角色连接成功`, `🎭 ${charName} 就绪`)
      completeStep('role', `角色连接成功`)
    }, 500)
  }
  
  if (newVal && mode.value === 'dialogue') {
    loadFigurineTTSAudios()
  }
})

watch(() => state.isOnline, (newVal) => {
  emit('updateStatus', { isOnline: newVal })
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

async function handleConnect() {
  if (!figurineId.value) {
    alert('请先选择角色')
    return
  }
  addStep('device', '设备连接', `连接 MQTT Broker: ${deviceId.value}`)
  try {
    await connectDevice({
      deviceId: deviceId.value,
      figurineId: figurineId.value,
      mode: mode.value,
    })
    completeStep('device', '设备连接', `${deviceId.value} 已上线`)
  } catch (err: any) {
    failStep('device', '设备连接', err.message || '连接失败')
  }
}

function handleDisconnect() {
  disconnectDevice()
}

async function handleStart() {
  if (!isConnected.value) {
    await handleConnect()
    if (!isConnected.value) return
  }

  const audioId = getCurrentAudioId()
  if (!audioId) {
    alert('请先选择音频/故事/音乐')
    return
  }

  addStep('session', 'MQTT 会话启动', '连接后端 MQTT Broker')

  const sessionPhase = flowStore.phases.find(p => p.id === 'session')
  if (sessionPhase) sessionPhase.expanded = true

  try {
    await startSimulation({
      deviceId: deviceId.value,
      figurineId: figurineId.value,
      mode: mode.value,
      audioId: audioId,
    })

    completeStep('session', 'MQTT 会话启动', `会话 ID: ${state.sessionId || ''}`)

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
  } catch (err: any) {
    failStep('session', 'MQTT 会话启动', err.message || '启动失败')
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
    capturing: '🎙️ 录音中', uploading: '⬆️ 上传中', thinking: '🤔 思考中',
    playing: '🔊 播放中', draining: '⏳ 排空中', done: '✅ 完成', aborted: '⛔ 中断',
  }
  return map[s] || s
}

function turnTypeIcon(t: TurnInfo['type']): string {
  const map: Record<TurnInfo['type'], string> = { user: '👤', tts: '🤖', cue: '🔔', command: '📋' }
  return map[t] || '❓'
}

function turnDuration(turn: TurnInfo): string {
  if (!turn.endTime) return '...'
  const ms = turn.endTime.getTime() - turn.startTime.getTime()
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}

function heartbeatAge(): string {
  if (!state.lastHeartbeatAt) return '未启动'
  const sec = Math.round((Date.now() - state.lastHeartbeatAt.getTime()) / 1000)
  return sec < 60 ? `${sec}s 前` : `${Math.floor(sec / 60)}m${sec % 60}s 前`
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
    ttsAudios.value = resp.records
  } catch (error: any) {
    console.error('加载 TTS 音频失败:', error)
    ttsAudioError.value = '加载 TTS 音频失败'
  } finally {
    loadingTTS.value = false
  }
}

function onInlineGenerated(audioId: string) {
  selectedAudioId.value = audioId
  showInlineGenerator.value = false
  loadFigurineTTSAudios()
}

async function openLibraryBrowser() {
  showLibraryBrowser.value = true
  loadingLibrary.value = true
  try {
    const resp = await fetchGeneratedVoices(200, 0)
    libraryAudios.value = resp.records
  } catch (error: any) {
    console.error('加载音频库失败:', error)
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
  loadingMsg.textContent = '⏳ 正在加载音频...'
  document.body.appendChild(loadingMsg)
  
  try {
    const audio = new Audio(url)
    await audio.play()
    setTimeout(() => {
      if (document.body.contains(loadingMsg)) document.body.removeChild(loadingMsg)
    }, 1000)
  } catch (err) {
    console.error('播放失败:', err)
    loadingMsg.textContent = '❌ 音频加载失败，请检查后端服务'
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
          {{ !isConnected && !isSimulating ? '⚪ 离线' :
             isConnecting ? '🟡 连接中' :
             state.status === 'idle' ? '⚪ 空闲' :
             state.status === 'connecting' ? '🟡 连接中' :
             state.status === 'active' ? '🟢 活跃' :
             state.status === 'capturing' ? '🎙️ 录音中' :
             state.status === 'playing' ? '🔊 播放中' :
             state.status === 'completed' ? '✅ 完成' :
             state.status === 'error' ? '❌ 错误' : '未知' }}
        </span>
      </div>
      
      <div class="header-right">
        <button v-if="state.heartbeatActive" class="btn-icon heartbeat-btn" :class="{ alive: heartbeatAlive }" @click="showDeviceInfo = !showDeviceInfo" title="心跳监控">
          {{ heartbeatAlive ? '💚' : '💛' }}
        </button>
        <button v-if="!isSimulating" class="btn-refresh" @click="deviceId = `sim-dev-${Math.random().toString(36).substr(2, 6)}`" title="刷新设备ID">
          🔄
        </button>
      </div>
    </div>

    <!-- 设备详情折叠区 -->
    <div v-if="showDeviceInfo && isSimulating" class="device-info-panel">
      <div class="info-row">
        <span class="info-label">Session</span>
        <span class="info-value mono">{{ state.sessionId || '-' }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">Turn</span>
        <span class="info-value">{{ state.currentTurn }}</span>
        <span class="info-label" style="margin-left:12px">Cue</span>
        <span class="info-value">{{ state.cueCount }}</span>
      </div>
      <div class="info-row">
        <span class="info-label">♥ 心跳</span>
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
    <div class="config-section">
      <label>🎭 角色 (Figurine)</label>
      <div v-if="loadingFigurines" class="loading" style="padding:8px">加载角色列表中...</div>
      <div v-else-if="figurineError" class="error-message" style="padding:8px;margin:0">❌ {{ figurineError }}</div>
      <select v-else v-model="figurineId" class="select-input">
        <option value="" disabled>-- 请选择角色 --</option>
        <option v-for="fig in figurines" :key="fig.figurine_id" :value="fig.figurine_id">
          {{ fig.character_name }} ({{ fig.name }}) - 📖{{ fig.story_count || 0 }} 🎵{{ fig.music_count || 0 }}
        </option>
      </select>
    </div>

    <!-- 模式选择 -->
    <div class="config-section">
      <label>📱 设备模式</label>
      <div class="mode-buttons">
        <button :class="['mode-btn', { active: mode === 'dialogue' }]" @click="mode = 'dialogue'">💬 对话</button>
        <button :class="['mode-btn', { active: mode === 'story' }]" @click="mode = 'story'">📖 故事</button>
        <button :class="['mode-btn', { active: mode === 'music' }]" @click="mode = 'music'">🎵 音乐</button>
      </div>
    </div>

    <!-- 内容选择 -->
    <div class="content-section">
      <template v-if="mode === 'dialogue'">
        <h4>🎤 选择 TTS 音频</h4>
        <div class="tts-actions">
          <button class="btn-sm" @click="showInlineGenerator = !showInlineGenerator">
            {{ showInlineGenerator ? '✕ 关闭生成' : '✨ 生成新语音' }}
          </button>
          <button class="btn-sm btn-outline" @click="openLibraryBrowser">📂 音频库</button>
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
            <button class="btn-play-sm" @click.stop="playTTSPreview(audio)" title="预览播放">▶️</button>
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
            <button class="btn-play" @click.stop="playPreview('story', story.id)" title="预览播放">▶️</button>
          </div>
        </div>
      </template>

      <template v-else-if="mode === 'music'">
        <h4>🎶 选择音乐</h4>
        <div v-if="loadingMedia" class="loading">加载中...</div>
        <div v-else-if="musicList.length === 0" class="empty-list">暂无音乐数据</div>
        <div v-else>
          <div v-for="music in musicList" :key="music.id" class="content-item" :class="{ active: selectedMusicId === music.id }" @click="selectedMusicId = music.id">
            <div class="content-info">
              <div class="content-title">{{ music.title }}</div>
              <div class="content-desc">{{ music.artist }}</div>
              <div class="content-meta">{{ music.duration }}s</div>
            </div>
            <button class="btn-play" @click.stop="playPreview('music', music.id)" title="预览播放">▶️</button>
          </div>
        </div>
      </template>
    </div>

    <!-- ═══ v1.6 信息面板（模拟中显示）═══ -->
    <template v-if="isSimulating">
      <!-- 活跃 Turn 折叠区 -->
      <div class="v16-section">
        <div class="v16-header" @click="toggleDeviceInfo">
          <span>▼ 活跃 Turn ({{ state.activeTurns.length }})</span>
          <span v-if="state.cueCount > 0" class="cue-badge">🔔 {{ state.cueCount }} cue</span>
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
            <span class="stt-copy">{{ copiedSttIdx === idx ? '✅' : '📋' }}</span>
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
            <span v-if="cmd.preempt" class="cmd-badge preempt">🔥 PREEMPT</span>
            <span v-else-if="cmd.afterAudio" class="cmd-badge after">⏳ AFTER</span>
            <span v-else class="cmd-badge normal">📩</span>
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
            <button class="btn-tab" :class="{ active: showOtaPanel }" @click.stop="toggleOtaPanel">📦 OTA</button>
            <button class="btn-tab" :class="{ active: showConfigPanel }" @click.stop="toggleConfigPanel">⚙️ Config</button>
          </span>
        </div>
        <div v-if="showOtaPanel" class="v16-body">
          <div class="detail-row"><span class="detail-label">当前版本</span><span>{{ state.otaStatus.currentVersion }}</span></div>
          <div v-if="state.otaStatus.targetVersion" class="detail-row"><span class="detail-label">目标版本</span><span>{{ state.otaStatus.targetVersion }}</span></div>
          <div class="detail-row">
            <span class="detail-label">状态</span>
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
            <span class="detail-label">状态</span>
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
        <button class="btn-connect" :disabled="isConnecting || !figurineId" @click="handleConnect">
          {{ isConnecting ? '⏳ 连接中...' : '🔌 连接设备' }}
        </button>
      </template>
      <template v-else-if="isConnected && !isSimulating">
        <button class="btn-start" :disabled="!getCurrentAudioId()" @click="handleStart">🟢 开始测试</button>
        <button class="btn-disconnect" @click="handleDisconnect">🔌 断开设备</button>
      </template>
      <template v-else-if="isSimulating">
        <button class="btn-stop" @click="handleStop">🔴 停止模拟</button>
      </template>
    </div>

    <div v-if="state.errorMessage" class="error-message">❌ {{ state.errorMessage }}</div>

    <!-- 音频库浏览器弹窗 -->
    <div v-if="showLibraryBrowser" class="modal-overlay" @click.self="closeLibraryBrowser">
      <div class="modal-content">
        <div class="modal-header">
          <h3>📂 TTS 音频库</h3>
          <button class="modal-close" @click="closeLibraryBrowser">✕</button>
        </div>
        <div class="modal-search">
          <input v-model="librarySearch" class="search-input" placeholder="搜索音频名称或文本..." />
        </div>
        <div class="modal-body">
          <div v-if="loadingLibrary" class="modal-loading">加载中...</div>
          <div v-else-if="filteredLibraryAudios.length === 0" class="modal-empty">没有匹配的音频</div>
          <div v-else class="modal-list">
            <div v-for="audio in filteredLibraryAudios" :key="audio.id" class="modal-item" :class="{ active: selectedAudioId === `tts/${audio.id}` }" @click="selectFromLibrary(audio)">
              <div class="modal-item-info">
                <div class="modal-item-name">{{ audio.name }}</div>
                <div class="modal-item-text">{{ (audio.text || '').slice(0, 80) }}</div>
                <div class="modal-item-meta">
                  {{ audio.duration_sec ? `${audio.duration_sec.toFixed(1)}s` : '' }}
                  {{ audio.gender }} / {{ audio.personality }}
                  {{ audio.created_at ? `· ${new Date(audio.created_at).toLocaleDateString()}` : '' }}
                </div>
              </div>
              <button class="btn-play-sm" @click.stop="playTTSPreview(audio)" title="预览">▶️</button>
            </div>
          </div>
        </div>
        <div class="modal-footer">
          <span>{{ filteredLibraryAudios.length }} / {{ libraryAudios.length }} 条</span>
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
.btn-disconnect {
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
