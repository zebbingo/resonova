import { ref, reactive } from 'vue'
import axios from 'axios'
import { deviceSM, DeviceState, SessionMode } from '../stores/deviceStateMachine'

export type MQTTMessageType =
  | 'session_start' | 'session_end' | 'session_hb'
  | 'audio_start' | 'chunk' | 'eos' | 'abort' | 'done'
  | 'cue_start' | 'cue_eos'
  | 'command' | 'command_preempt'
  | 'vadeos' | 'introeos'
  | 'stt_result' | 'stt_inference' | 'llm_inference' | 'tts_synthesis'
  | 'audio_chunk' | 'audio_eos' | 'audio_start as audio_start_down'
  | 'intro_start' | 'intro_end'
  | 'moderation_complete' | 'output_moderation_complete'
  | 'session_status' | 'mqtt_publish'
  | 'ota_update' | 'config_update'
  | 'other'

export interface MQTTMessageLog {
  timestamp: Date
  direction: 'up' | 'down'
  topic: string
  payload?: any
  type: MQTTMessageType
  turnId?: string
}

export interface STTMetrics {
  load_ms: number
  transcribe_ms: number
  rtf: number
  duration_sec: number
}

export interface SttResultData {
  text: string
  metrics: STTMetrics | null
  duration_ms?: number
}

export interface TurnInfo {
  turnId: string
  type: 'user' | 'tts' | 'cue' | 'command'
  state: 'capturing' | 'uploading' | 'thinking' | 'playing' | 'draining' | 'done' | 'aborted'
  chunksSent: number
  chunksReceived: number
  sttText?: string
  startTime: Date
  endTime?: Date
  totalSeq?: number
  durationMs?: number
}

export interface CommandInfo {
  cmd: string
  turnId?: string
  preempt: boolean
  afterAudio: boolean
  timestamp: Date
  params?: any
}

export interface HeartbeatRecord {
  timestamp: Date
  latencyMs?: number
}

export interface OTAStatus {
  currentVersion: string
  targetVersion?: string
  status: 'idle' | 'downloading' | 'installing' | 'success' | 'failed'
  ver?: number
}

export interface ConfigStatus {
  ver: number
  appliedAt?: number
  status: 'idle' | 'applying' | 'applied' | 'failed'
}

export interface DeviceSimulationState {
  isOnline: boolean
  sessionId?: string
  currentTurn: number
  sentChunks: number
  status: 'idle' | 'connecting' | 'active' | 'capturing' | 'playing' | 'completed' | 'error'
  errorMessage?: string

  activeTurns: TurnInfo[]
  commands: CommandInfo[]
  sttTexts: string[]
  cueCount: number

  heartbeatActive: boolean
  heartbeatHistory: HeartbeatRecord[]
  lastHeartbeatAt?: Date

  otaStatus: OTAStatus
  configStatus: ConfigStatus

  protocolVersion: string
  fwVersion: string
}

export interface SimulationConfig {
  deviceId: string
  figurineId: string
  mode: 'dialogue' | 'story' | 'music'
  audioId: string
}

const MAX_LOGS = 500
const MAX_TURNS = 50
const MAX_COMMANDS = 100
const MAX_HEARTBEATS = 20

export function useMQTTSimulation() {
  const isSimulating = ref(false)
  const isConnected = ref(false)
  const isConnecting = ref(false)
  const state = reactive<DeviceSimulationState>({
    isOnline: false,
    sessionId: undefined,
    currentTurn: 0,
    sentChunks: 0,
    status: 'idle',
    errorMessage: undefined,

    activeTurns: [],
    commands: [],
    sttTexts: [],
    cueCount: 0,

    heartbeatActive: false,
    heartbeatHistory: [],

    otaStatus: { currentVersion: '1.6.0', status: 'idle' },
    configStatus: { ver: 0, status: 'idle' },

    protocolVersion: 'v1.6',
    fwVersion: '1.6.0',
  })

  const logs = ref<MQTTMessageLog[]>([])
  const sttResult = ref<SttResultData | null>(null)
  let ws: WebSocket | null = null
  let deviceWs: WebSocket | null = null
  let _deviceId: string = ''

  function _findTurn(turnId: string): TurnInfo | undefined {
    return state.activeTurns.find(t => t.turnId === turnId)
  }

  function _upsertTurn(turnId: string, type: TurnInfo['type'], updates: Partial<TurnInfo>): TurnInfo {
    let turn = _findTurn(turnId)
    if (!turn) {
      turn = {
        turnId, type,
        state: 'thinking',
        chunksSent: 0, chunksReceived: 0,
        startTime: new Date(),
      }
      state.activeTurns.push(turn)
      if (state.activeTurns.length > MAX_TURNS) {
        state.activeTurns.shift()
      }
    }
    Object.assign(turn, updates)
    return turn
  }

  async function connectDevice(config: { deviceId: string; figurineId: string; mode: string }) {
    isConnecting.value = true
    _deviceId = config.deviceId

    // 状态机：OFFLINE → CONNECTING
    deviceSM.transitionTo(DeviceState.CONNECTING, {
      deviceId: config.deviceId,
      figurineId: config.figurineId,
    })

    try {
      await axios.post('/api/device/connect', {
        device_id: config.deviceId,
        figurine_id: config.figurineId,
        mode: config.mode,
      })
      state.isOnline = true
      state.status = 'active'
      isConnected.value = true

      // 状态机：CONNECTING → IDLE
      deviceSM.transitionTo(DeviceState.IDLE)
      addLog('up', 'device/power_on', { device_id: config.deviceId }, 'session_start')

      const wsUrl = `ws://${window.location.host}/ws/device/${config.deviceId}`
      deviceWs = new WebSocket(wsUrl)
      deviceWs.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          _handleWsMessage(data)
        } catch {}
      }
      deviceWs.onclose = () => {
        if (isConnected.value) {
          isConnected.value = false
          state.isOnline = false
          if (state.status === 'active' || state.status === 'idle') {
            state.status = 'idle'
            // 状态机：异常断开 → OFFLINE
            deviceSM.transitionTo(DeviceState.OFFLINE)
          }
        }
      }
    } catch (error: any) {
      state.errorMessage = error.response?.data?.error || error.message
      state.status = 'error'
      deviceSM.setError(state.errorMessage)
    } finally {
      isConnecting.value = false
    }
  }

  async function disconnectDevice() {
    if (!_deviceId) return
    try {
      await axios.post(`/api/device/disconnect/${_deviceId}`)
    } catch {}
    if (deviceWs) { deviceWs.close(); deviceWs = null }
    if (ws) { ws.close(); ws = null }
    isConnected.value = false
    isSimulating.value = false
    state.isOnline = false
    state.status = 'idle'
    state.heartbeatActive = false
    state.sessionId = undefined

    // 状态机：IDLE → OFFLINE
    deviceSM.transitionTo(DeviceState.OFFLINE)
  }

  async function startSimulation(config: SimulationConfig) {
    isSimulating.value = true
    state.status = 'connecting'
    state.sentChunks = 0
    state.currentTurn = 0
    state.activeTurns = []
    state.commands = []
    state.sttTexts = []
    state.cueCount = 0
    state.heartbeatActive = false
    state.heartbeatHistory = []
    state.otaStatus = { currentVersion: '1.6.0', status: 'idle' }
    state.configStatus = { ver: 0, status: 'idle' }
    logs.value = []
    sttResult.value = null

    // 状态机：IDLE → SESSION_ACTIVE
    deviceSM.transitionTo(DeviceState.SESSION_ACTIVE, {
      sessionMode: config.mode as SessionMode,
      figurineId: config.figurineId,
      deviceId: config.deviceId,
    })

    try {
      const resp = await axios.post('/api/device/simulate', {
        device_id: config.deviceId,
        figurine_id: config.figurineId,
        mode: config.mode,
        audio_id: config.audioId,
        test_type: 'mqtt',
        subscribe_response: true,
      })

      state.sessionId = resp.data.session_id
      state.isOnline = true
      state.status = 'active'
      state.fwVersion = resp.data.fw_version || '1.6.0'

      addLog('up', 'session/start', {
        session_id: state.sessionId,
        character: config.figurineId,
        mode: config.mode,
      }, 'session_start')

      const wsUrl = `ws://${window.location.host}/ws/session/${state.sessionId}`
      ws = new WebSocket(wsUrl)

      ws.onopen = () => {
        console.log('[WebSocket] Connected')
        addLog('up', 'WebSocket connected', {}, 'other')
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          _handleWsMessage(data)
        } catch (err) {
          console.error('[WebSocket] Parse error:', err)
        }
      }

      ws.onerror = () => {
        state.errorMessage = 'WebSocket 连接错误'
        state.status = 'error'
        deviceSM.setError(state.errorMessage)
      }

      ws.onclose = () => {
        console.log('[WebSocket] Closed')
        isSimulating.value = false
        state.heartbeatActive = false
        if (state.status !== 'completed') {
          state.status = isConnected.value ? 'active' : 'idle'
        }
        if (!isConnected.value) {
          state.isOnline = false
        }
      }
    } catch (error: any) {
      console.error('[Simulation] Start failed:', error)
      state.errorMessage = error.response?.data?.detail || error.message
      state.status = 'error'
      isSimulating.value = false
      deviceSM.setError(state.errorMessage)
    }
  }

  function _handleWsMessage(data: any) {
    const msgType: string = data.type || ''
    const direction: 'up' | 'down' = data.direction || 'down'
    const topic: string = data.topic || ''
    const payload = data.payload || data
    const turnId: string | undefined = data.turn_id || payload?.turn_id
    const messageSubType: string = data.message_type || ''

    if (msgType === 'mqtt_message') {
      _handleMqttMessage(direction, topic, payload, messageSubType, turnId || data.short_topic)
      return
    }

    switch (msgType) {
      case 'stt_result':
        sttResult.value = data
        state.status = 'completed'
        addLog('down', 'STT Result', { text: data.text, metrics: data.metrics }, 'stt_result', turnId)
        break

      case 'session_complete':
        state.status = 'completed'
        state.isOnline = false
        // 状态机：会话完成 → SESSION_ENDED
        deviceSM.transitionTo(DeviceState.SESSION_ENDED)
        addLog('down', 'Session Complete', {}, 'session_end')
        break

      case 'stt_inference':
        addLog('down', 'Pipeline/STT', { text: data.text, duration_ms: data.duration_ms }, 'stt_inference', turnId)
        if (data.text) {
          sttResult.value = data
          state.sttTexts.push(data.text)
          if (state.sttTexts.length > 50) state.sttTexts.shift()
        }
        break

      case 'llm_inference':
        addLog('down', 'Pipeline/LLM', { text: data.text, cmd: data.cmd, duration_ms: data.duration_ms }, 'llm_inference', turnId)
        break

      case 'tts_synthesis':
        addLog('down', 'Pipeline/TTS', { status: data.status, duration_ms: data.duration_ms, chunk_count: data.chunk_count }, 'tts_synthesis', turnId)
        break

      case 'intro_start':
        addLog('down', 'response/audio/intro/start', {}, 'intro_start', '0')
        break

      case 'intro_end':
        addLog('down', 'response/audio/intro/eos', {}, 'intro_end', '0')
        break

      case 'vad_speech_started':
        addLog('down', 'VAD/speech_started', {}, 'vadeos')
        break

      case 'vad_speech_stopped':
        addLog('down', 'VAD/speech_stopped', {}, 'vadeos')
        break

      case 'moderation_complete':
        addLog('down', 'Moderation/complete', { flagged: data.flagged, block_reasons: data.block_reasons, duration_ms: data.duration_ms }, 'moderation_complete')
        break

      case 'output_moderation_complete':
        addLog('down', 'Moderation/output_complete', { flagged: data.flagged, source: data.source }, 'output_moderation_complete')
        break

      case 'session_status':
        addLog('down', 'Session/Status', payload, 'session_status')
        break

      default:
        addLog(direction, topic || msgType, payload, 'other', turnId)
        break
    }
  }

  function _handleMqttMessage(direction: 'up' | 'down', topic: string, payload: any, messageSubType: string, turnIdHint?: string) {
    const extractedTurnId = _extractTurnIdFromTopic(topic) || turnIdHint

    switch (messageSubType) {
      case 'audio_start':
        if (direction === 'up') {
          state.status = 'capturing'
          state.currentTurn++
          const tid = extractedTurnId || String(state.currentTurn)
          _upsertTurn(tid, 'user', { state: 'uploading', chunksSent: 0, startTime: new Date() })
          // 状态机：开始上行录音 → CAPTURING（可从 SESSION_ACTIVE 或 WAITING 进入）
          deviceSM.transitionTo(DeviceState.CAPTURING)
          addLog('up', topic, payload, 'audio_start', tid)
        } else {
          const tid = extractedTurnId || 'tts'
          const isCue = tid.startsWith('cue-')
          _upsertTurn(tid, isCue ? 'cue' : 'tts', { state: 'playing', chunksReceived: 0, startTime: new Date() })
          if (isCue) state.cueCount++
          state.status = 'playing'
          addLog('down', topic, payload, isCue ? 'cue_start' : 'audio_start', tid)
        }
        break

      case 'audio_chunk':
      case 'chunk':
        if (direction === 'up') {
          state.sentChunks++
          if (extractedTurnId) {
            const turn = _findTurn(extractedTurnId)
            if (turn) turn.chunksSent++
          }
          addLog('up', topic, payload, 'chunk', extractedTurnId)
        } else {
          if (extractedTurnId) {
            const turn = _findTurn(extractedTurnId)
            if (turn) turn.chunksReceived++
          }
          // 状态机追踪下行 chunk
          deviceSM.incrementReceivedChunks()
          addLog('down', topic, payload, 'audio_chunk', extractedTurnId)
        }
        break

      case 'audio_eos':
      case 'eos':
        if (direction === 'up') {
          if (extractedTurnId) {
            _upsertTurn(extractedTurnId, 'user', { state: 'thinking', endTime: new Date() })
          }
          state.status = 'active'
          // 状态机：上行音频结束 → WAITING
          deviceSM.transitionTo(DeviceState.WAITING)
          addLog('up', topic, payload, 'eos', extractedTurnId)
        } else {
          if (extractedTurnId) {
            const turn = _findTurn(extractedTurnId)
            const isCue = extractedTurnId.startsWith('cue-')
            _upsertTurn(extractedTurnId, isCue ? 'cue' : 'tts', {
              state: 'done',
              endTime: new Date(),
              totalSeq: payload?.total_seq,
              durationMs: payload?.duration_ms,
            })
          }
          state.status = 'active'
          addLog('down', topic, payload, isCueTopic(extractedTurnId) ? 'cue_eos' : 'audio_eos', extractedTurnId)
        }
        break

      case 'audio_abort':
      case 'abort':
        if (extractedTurnId) {
          _upsertTurn(extractedTurnId, _findTurn(extractedTurnId)?.type || 'user', { state: 'aborted', endTime: new Date() })
        }
        state.status = 'active'
        addLog(direction, topic, payload, 'abort', extractedTurnId)
        break

      case 'audio_done':
      case 'done':
        addLog('up', topic, payload, 'done', extractedTurnId)
        break

      case 'vadeos':
        if (payload?.text) {
          state.sttTexts.push(payload.text)
          if (state.sttTexts.length > 50) state.sttTexts.shift()
          if (extractedTurnId) {
            const turn = _findTurn(extractedTurnId)
            if (turn) turn.sttText = payload.text
          }
        }
        addLog('down', topic, payload, 'vadeos', extractedTurnId)
        break

      case 'introeos':
        addLog('down', topic, payload, 'introeos', '0')
        break

      case 'command':
        const cmdInfo: CommandInfo = {
          cmd: payload?.cmd || payload?.command || '',
          turnId: extractedTurnId,
          preempt: payload?.preempt ?? false,
          afterAudio: payload?.after_audio ?? false,
          timestamp: new Date(),
          params: payload,
        }
        state.commands.push(cmdInfo)
        if (state.commands.length > MAX_COMMANDS) state.commands.shift()
        // 状态机追踪指令
        deviceSM.incrementCommands()
        addLog('down', topic, payload, cmdInfo.preempt ? 'command_preempt' : 'command', extractedTurnId)
        break

      case 'session_hb':
        state.heartbeatActive = true
        state.lastHeartbeatAt = new Date()
        state.heartbeatHistory.push({ timestamp: new Date() })
        if (state.heartbeatHistory.length > MAX_HEARTBEATS) state.heartbeatHistory.shift()
        addLog('up', topic, payload, 'session_hb')
        break

      case 'ota_update':
      case 'ota_desired':
        state.otaStatus = {
          currentVersion: state.otaStatus.currentVersion,
          targetVersion: payload?.fw_version,
          status: 'downloading',
          ver: payload?.ver,
        }
        addLog('down', topic, payload, 'ota_update')
        break

      case 'ota_reported':
        if (payload?.status === 'success') {
          state.otaStatus = {
            currentVersion: payload?.fw_version || state.otaStatus.currentVersion,
            status: 'success',
            ver: payload?.ver,
          }
          state.fwVersion = payload?.fw_version || state.fwVersion
        }
        addLog('up', topic, payload, 'ota_update')
        break

      case 'config_update':
      case 'state_desired':
        state.configStatus = { ver: payload?.ver || 0, status: 'applying' }
        addLog('down', topic, payload, 'config_update')
        break

      case 'state_reported':
        state.configStatus = { ver: payload?.ver || 0, status: 'applied', appliedAt: payload?.applied_at }
        addLog('up', topic, payload, 'config_update')
        break

      default:
        addLog(direction, topic, payload, 'other', extractedTurnId)
        break
    }
  }

  function _extractTurnIdFromTopic(topic: string): string | undefined {
    const parts = topic.split('/')
    for (let i = 0; i < parts.length - 1; i++) {
      if (parts[i] === 'audio' && i + 1 < parts.length) {
        return parts[i + 1]
      }
    }
    return undefined
  }

  function stopSimulation() {
    if (ws) {
      ws.close()
      ws = null
    }
    isSimulating.value = false
    state.heartbeatActive = false
    // 状态机：先走到 SESSION_ENDED（兼容 CAPTURING / WAITING / SESSION_ACTIVE）
    deviceSM.transitionTo(DeviceState.SESSION_ENDED)
    if (isConnected.value) {
      state.status = 'active'
      // 状态机：SESSION_ENDED → IDLE（设备仍在线）
      deviceSM.transitionTo(DeviceState.IDLE)
    } else {
      state.isOnline = false
      state.status = 'idle'
      // 状态机：IDLE → OFFLINE
      deviceSM.transitionTo(DeviceState.OFFLINE)
    }
    state.sessionId = undefined
    addLog('up', 'Manual Stop', {}, 'session_end')
  }

  function addLog(
    direction: 'up' | 'down',
    topic: string,
    payload?: any,
    type: MQTTMessageType = 'other',
    turnId?: string,
  ) {
    logs.value.push({ timestamp: new Date(), direction, topic, payload, type, turnId })
    if (logs.value.length > MAX_LOGS) logs.value.shift()
  }

  function clearLogs() {
    logs.value = []
  }

  return {
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
    clearLogs,
  }
}

function isCueTopic(turnId?: string): boolean {
  return !!turnId && turnId.startsWith('cue-')
}
