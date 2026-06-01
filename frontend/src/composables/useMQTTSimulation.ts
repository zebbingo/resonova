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
  lastEventSummary?: string
  lastEventAt?: Date
  lastSessionStatus?: string
  lastSttText?: string
  lastReplyText?: string

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
  mqttProfile?: 'local' | 'relay' | 'custom' | 'aws_iot'
  mqttEnv?: string
  mqttHost?: string
  mqttPort?: number
  mqttTls?: boolean
  mqttTlsCaCert?: string
  mqttTlsClientCert?: string
  mqttTlsClientKey?: string
}

export interface MQTTBrokerConfig {
  mqttProfile?: 'local' | 'relay' | 'custom' | 'aws_iot'
  mqttEnv?: string
  mqttHost?: string
  mqttPort?: number
  mqttTls?: boolean
  mqttTlsCaCert?: string
  mqttTlsClientCert?: string
  mqttTlsClientKey?: string
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
    lastEventSummary: undefined,
    lastEventAt: undefined,
    lastSessionStatus: undefined,
    lastSttText: undefined,
    lastReplyText: undefined,

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
  let systemWs: WebSocket | null = null
  let _deviceId: string = ''
  let _keepaliveTimer: ReturnType<typeof setInterval> | null = null
  let _onEvictedCallback: ((deviceId: string) => void) | null = null

  /** 濠电偛顦崝宀勫船閻ｅ本濯奸柟顖嗗本校闂佹悶鍎抽崑鐐哄极瑜版帒鐐婇柣鎰濞堝爼鏌ㄥ☉妯煎ⅱ闁?DeviceManager 闁荤姳绀佹晶浠嬫偪閸℃稒鏅?*/
  function onDeviceEvicted(cb: (deviceId: string) => void) {
    _onEvictedCallback = cb
  }

  /** 濠?15 缂備礁顦扮敮鎺楀箖濠婂牆瑙﹂幖杈剧秵娴煎倿鏌涘▎鎰伌闁?keepalive闂佹寧绋戦惌鍌毼ｇ拠宸桨闁靛骏缍嗛崯搴☆熆鐠虹儤绌挎い顐畵瀹曞爼鎮欑€涙ɑ姣?*/
  function _startKeepalive() {
    _stopKeepalive()
    _keepaliveTimer = setInterval(async () => {
      if (!_deviceId) return
      try {
        await axios.post(`/api/device/keepalive/${_deviceId}`)
      } catch {
        // 闂傚倸鐗婇悷鈺冨垝椤栨稑绶為弶鍫亯琚?闂?闂佸憡鑹惧ù鐑筋敂椤掑嫬鐭楁い鏍ㄧ箓閸樻挳鏌￠崱妤€鈧绮径鎰煑妞ゆ牗绻冭ぐ?      }
    }, 15_000)
  }

  function _stopKeepalive() {
    if (_keepaliveTimer !== null) {
      clearInterval(_keepaliveTimer)
      _keepaliveTimer = null
    }
  }

  /** 闁哄鏅濋崑鐐垫暜鐎电瀵查柤濮愬€楅崺鐘电磼?/ws/system闂佹寧绋戦張顒傛暜閹绢喖缁?device_evicted 缂備焦绋戦ˇ鐢稿焵椤掍焦鐨戦柣?*/
  function connectSystemWS() {
    if (systemWs) {
      systemWs.close()
      systemWs = null
    }
    try {
      systemWs = new WebSocket(`ws://${window.location.host}/ws/system`)
      systemWs.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          if (data.type === 'device_evicted' && data.device_id === _deviceId) {
            // 閻熸粎澧楅幐鍛婃櫠閻樺灚濯奸柟顖嗗本校闁荤偞鍑归崑鍕洪弽顓炵哗?
            state.isOnline = false
            state.status = 'idle'
            isConnected.value = false
            deviceSM.transitionTo(DeviceState.OFFLINE)
            if (_onEvictedCallback) {
              _onEvictedCallback(data.device_id)
            }
          }
        } catch { /* ignore parse errors */ }
      }
      systemWs.onclose = () => {
        // 2s 闂佸憡鑹鹃柊锝夊闯閸涘﹥浜?
        setTimeout(() => { connectSystemWS() }, 2000)
      }
    } catch { /* ignore */ }
  }

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

  function _setLiveTrace(
    summary: string,
    updates: Partial<Pick<DeviceSimulationState, 'lastSessionStatus' | 'lastSttText' | 'lastReplyText'>> = {},
  ) {
    state.lastEventSummary = summary
    state.lastEventAt = new Date()
    if (updates.lastSessionStatus !== undefined) state.lastSessionStatus = updates.lastSessionStatus
    if (updates.lastSttText !== undefined) state.lastSttText = updates.lastSttText
    if (updates.lastReplyText !== undefined) state.lastReplyText = updates.lastReplyText
  }

  async function connectDevice(config: { deviceId: string; figurineId: string; mode: string } & MQTTBrokerConfig) {
    isConnecting.value = true
    _deviceId = config.deviceId

    // 闂佺粯顭堥崺鏍焵椤戣法鍔嶆繝褉鍋撻梺鎸庣⊕閻″瓗FLINE 闂?CONNECTING
    deviceSM.transitionTo(DeviceState.CONNECTING, {
      deviceId: config.deviceId,
      figurineId: config.figurineId,
    })

    try {
      await axios.post('/api/device/connect', {
        device_id: config.deviceId,
        figurine_id: config.figurineId,
        mode: config.mode,
        mqtt_profile: config.mqttProfile,
        mqtt_env: config.mqttEnv,
        mqtt_host: config.mqttHost,
        mqtt_port: config.mqttPort,
        mqtt_tls: config.mqttTls,
        mqtt_tls_ca_cert: config.mqttTlsCaCert,
        mqtt_tls_client_cert: config.mqttTlsClientCert,
        mqtt_tls_client_key: config.mqttTlsClientKey,
      })
      state.isOnline = true
      state.status = 'active'
      isConnected.value = true

      // 闂佺粯顭堥崺鏍焵椤戣法鍔嶆繝褉鍋撻梺鎸庣⊕椤戝栋NNECTING 闂?IDLE
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
        // 婵炴垶鎸哥粔鎾疮閳ь剛绱掗弬娆惧剰鐎规挸妫濆浠嬪炊椤忓秴鏁圭紓浣稿€藉畷鐢稿吹?闂?keepalive 闂佸綊鏅查懗鍫曟偨婵犳艾绀嗛梺鍨儐閻撯偓闂佸憡鐟崹璺何ｇ拠宸桨?cleanup 缂備焦宕樺▔鏇㈠煝婵傜鐐婇柣鎰摠閺?        // 闂佸憡鎸哥粔鍫曨敂椤掑嫬鐭楁い鏍ㄦ皑濮ｏ箓鎮归崶銊︾闁革絾鎮傚顒勬偋閸績鍙洪悗娈垮枓閸?WS
      }

      // 闂佸啿鍘滈崑鎾绘煃閸忓浜?Keepalive 濠?15s 闂佸憡甯￠弨閬嶅蓟婵犲嫭濯奸柟顖嗗本校濠电偛寮跺Σ鎺旂矚椤掑嫬绫嶉柛顐ｆ礃閿?闂佸啿鍘滈崑鎾绘煃閸忓浜?      _startKeepalive()

      // 闂佸啿鍘滈崑鎾绘煃閸忓浜?闁哄鏅濋崑鐐垫暜鐎电瀵查柤濮愬€楅崺鐘裁瑰鍐惧剮婵炲棎鍨洪敍鎰板箣閿斿灝顥氶梺鎸庣☉閺堫剛鏁幘顔肩哗?device_evicted 闂備緡鍋呭銊╂偂?闂佸啿鍘滈崑鎾绘煃閸忓浜?      connectSystemWS()
    } catch (error: any) {
      state.errorMessage = error.response?.data?.error || error.message
      state.status = 'error'
      deviceSM.setError(state.errorMessage || '闁哄鏅濋崑鐐垫暜鐎涙ê绶為弶鍫亯琚?)
    } finally {
      isConnecting.value = false
    }
  }

  async function disconnectDevice() {
    if (!_deviceId) return
    try {
      await axios.post(`/api/device/disconnect/${_deviceId}`)
    } catch {}
    _stopKeepalive()
    if (deviceWs) { deviceWs.close(); deviceWs = null }
    if (ws) { ws.close(); ws = null }
    if (systemWs) { systemWs.close(); systemWs = null }
    isConnected.value = false
    isSimulating.value = false
    state.isOnline = false
    state.status = 'idle'
    state.heartbeatActive = false
    state.sessionId = undefined
    state.lastEventSummary = undefined
    state.lastEventAt = undefined
    state.lastSessionStatus = undefined
    state.lastSttText = undefined
    state.lastReplyText = undefined

    // 闂佺粯顭堥崺鏍焵椤戣法鍔嶆繝褉鍋撻梺鎸庣⊕椤戞—LE 闂?OFFLINE
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
    state.lastEventSummary = undefined
    state.lastEventAt = undefined
    state.lastSessionStatus = undefined
    state.lastSttText = undefined
    state.lastReplyText = undefined
    state.otaStatus = { currentVersion: '1.6.0', status: 'idle' }
    state.configStatus = { ver: 0, status: 'idle' }
    logs.value = []
    sttResult.value = null

    // 闂佺粯顭堥崺鏍焵椤戣法鍔嶆繝褉鍋撻梺鎸庣⊕椤戞—LE 闂?SESSION_ACTIVE
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
        mqtt_profile: config.mqttProfile,
        mqtt_env: config.mqttEnv,
        mqtt_host: config.mqttHost,
        mqtt_port: config.mqttPort,
        mqtt_tls: config.mqttTls,
        mqtt_tls_ca_cert: config.mqttTlsCaCert,
        mqtt_tls_client_cert: config.mqttTlsClientCert,
        mqtt_tls_client_key: config.mqttTlsClientKey,
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
        state.errorMessage = 'WebSocket 闁哄鏅濋崑鐐垫暜閹绢喗鐓ユ繛鍡樺俯閸?
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
      deviceSM.setError(state.errorMessage || '闂佸憡鍑归崹鐗堟叏閳哄倸绶為弶鍫亯琚?)
    }
  }

  async function sendTurn(audioId: string) {
    if (!_deviceId) {
      throw new Error('Device is not connected')
    }
    if (!audioId) {
      throw new Error('audioId is required')
    }

    const resp = await axios.post('/api/device/send-turn', {
      device_id: _deviceId,
      audio_id: audioId,
    })

    const sessionId = resp?.data?.session_id
    if (sessionId && !state.sessionId) {
      state.sessionId = sessionId
    }
    return resp.data
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
        _setLiveTrace(`STT 闁荤姴娲ゅΛ妤呭春閸℃瑢鍋撻悷鐗堟拱闁搞劍宀搁弫?{data.text ? String(data.text).slice(0, 80) : '闂佸搫鐗滄禍锝夋儊閹达箑绀嗘い鎰╁灩閻撳倿鏌涢幇顒佸櫣妞?}`, {
          lastSttText: data.text,
          lastSessionStatus: 'completed',
        })
        break

      case 'session_complete':
        state.status = 'completed'
        state.isOnline = false
        // 闂佺粯顭堥崺鏍焵椤戣法鍔嶆繝褉鍋撻梺鎸庣⊕閻喚妲愰幍顔藉珰婵犻潧妫涢弳姘舵煙?闂?SESSION_ENDED
        deviceSM.transitionTo(DeviceState.SESSION_ENDED)
        addLog('down', 'Session Complete', {}, 'session_end')
        _setLiveTrace('婵炴潙鍚嬫穱娲儊閽樺鍟呴柤纰卞墰濞夈垽鏌?, { lastSessionStatus: 'completed' })
        break

      case 'stt_inference':
        addLog('down', 'Pipeline/STT', { text: data.text, duration_ms: data.duration_ms }, 'stt_inference', turnId)
        if (data.text) {
          sttResult.value = data
          state.sttTexts.push(data.text)
          if (state.sttTexts.length > 50) state.sttTexts.shift()
        }
        _setLiveTrace(
          data.text ? `STT 闁荤姴娲ゅΛ妤呭春閸℃瑢鍋撻悷鐗堟拱闁搞劍宀搁弫?{String(data.text).slice(0, 80)}` : 'STT 濠殿喗绻愮徊钘夛耿椤忓棙瀚氶柛鈩冾殔閻掔厧鈽?,
          { lastSttText: data.text || state.lastSttText, lastSessionStatus: 'stt_inference' },
        )
        break

      case 'llm_inference':
        addLog('down', 'Pipeline/LLM', { text: data.text, cmd: data.cmd, duration_ms: data.duration_ms }, 'llm_inference', turnId)
        _setLiveTrace(
          data.cmd ? `LLM 閻庤鐡曠亸娆撳极閹捐绠ｉ柟閭﹀幖閻︾懓霉閻橆喖鈧呮?{data.cmd}` : 'LLM 濠殿喗绻愮徊钘夛耿椤忓牆绠戞繝闈浥堥崑鎾诲礃閵婏妇顦ユ繝?,
          { lastReplyText: data.text || state.lastReplyText, lastSessionStatus: 'llm_inference' },
        )
        break

      case 'tts_synthesis':
        addLog('down', 'Pipeline/TTS', { status: data.status ?? (data.state === 'complete' ? 'success' : data.state), duration_ms: data.duration_ms, chunk_count: data.chunk_count }, 'tts_synthesis', turnId)
        _setLiveTrace(
          data.status === 'success' || data.state === 'complete'
            ? `TTS 閻庤鐡曠亸娆撳极閹捐绠?${data.chunk_count ?? 0} 婵炴垶鎼╂禍顏堟偂閼哥绱ｉ柟瀛樼箖閸嬵櫐
            : 'TTS 濠殿喗绻愮徊钘夛耿椤忓牆瑙﹂柛顐ゅ枎閻忓洭鎮归崶璺哄籍闁?,
          { lastSessionStatus: 'tts_synthesis', lastReplyText: state.lastReplyText },
        )
        break

      case 'intro_start':
        addLog('down', 'response/audio/intro/start', {}, 'intro_start', '0')
        _setLiveTrace('閻庢鍠掗崑鎾绘煕閿曚焦顏犳繛鍛囧洤绠绘い鎾跺枑閺夌懓鈽?, { lastSessionStatus: 'intro_playing' })
        break

      case 'intro_end':
        addLog('down', 'response/audio/intro/eos', {}, 'intro_end', '0')
        _setLiveTrace('閻庢鍠掗崑鎾绘煕閿曚焦顏犳繛鍛囧喚鍟呴柟缁樺笧閺嗘岸鏌?, { lastSessionStatus: 'intro_complete' })
        break

      case 'vad_speech_started':
        addLog('down', 'VAD/speech_started', {}, 'vadeos')
        _setLiveTrace('VAD 濠碘槅鍋€閸嬫挻绻涢弶鎴剰闁糕晛鐭傞幃浠嬪Ω閿曗偓閻撴洜鈧鍠掗崑鎾斥攽椤旂⒈鍎撴い鏇楁櫇閹?, { lastSessionStatus: 'capturing' })
        break

      case 'vad_speech_stopped':
        addLog('down', 'VAD/speech_stopped', {}, 'vadeos')
        _setLiveTrace('VAD 濠碘槅鍋€閸嬫挻绻涢弶鎴剰闁糕晛鐭傞幃浠嬪Ω閿曗偓閻撴洟鎮归崶鈺婃闁伙妇鏅槐鎺楀箻鐎涙ê鐨?, { lastSessionStatus: 'active' })
        break

      case 'moderation_complete':
        addLog('down', 'Moderation/complete', { flagged: data.flagged, block_reasons: data.block_reasons, duration_ms: data.duration_ms }, 'moderation_complete')
        break

      case 'output_moderation_complete':
        addLog('down', 'Moderation/output_complete', { flagged: data.flagged, source: data.source }, 'output_moderation_complete')
        break

      case 'session_status':
        if (payload?.session_id && payload.session_id !== state.sessionId) {
          state.sessionId = payload.session_id
        }
        if (payload?.status === 'error') {
          state.errorMessage = payload?.error || state.errorMessage
          state.status = 'error'
        } else if (payload?.status === 'completed' || payload?.status === 'session_closed') {
          state.status = isConnected.value ? 'active' : 'idle'
        } else if (payload?.status === 'turn_completed' || payload?.status === 'intro_complete' || payload?.status === 'intro_timeout' || payload?.status === 'active') {
          state.status = 'active'
        }
        break

        addLog('down', 'Session/Status', payload, 'session_status')
        let sessionSummary = 'status update'
        if (payload?.status === 'turn_completed') {
          sessionSummary = 'turn completed; waiting next turn'
        } else if (payload?.status === 'intro_complete') {
          sessionSummary = 'intro completed'
        } else if (payload?.status === 'intro_timeout') {
          sessionSummary = 'intro timeout'
        } else if (payload?.status === 'error') {
          sessionSummary = 'session error: ' + (payload?.error || 'unknown error')
        } else if (payload?.status === 'completed') {
          sessionSummary = 'session completed'
        } else if (payload?.status === 'active') {
          sessionSummary = 'session active'
        }
        _setLiveTrace(sessionSummary, {
          lastSessionStatus: String(payload?.status || state.lastSessionStatus || 'active'),
          lastReplyText: payload?.reply_text || state.lastReplyText,
          lastSttText: payload?.stt_text || state.lastSttText,
        })
        break
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
          // 闂佺粯顭堥崺鏍焵椤戣法鍔嶆繝褉鍋撻柡澶嗘櫅閳ь剛鍠栭崵瀣槈閹炬剚鍎撴い?chunk
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
          // 闂佺粯顭堥崺鏍焵椤戣法鍔嶆繝褉鍋撻梺鎸庣⊕閻喚绮崒婊勫仒鐎光偓閸曨厼寰撴俊顐ゅ閸ㄥ湱鍒掗妸鈺佺骇?闂?WAITING
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
        // 闂佺粯顭堥崺鏍焵椤戣法鍔嶆繝褉鍋撻柡澶嗘櫅閳ь剛鍠栭崵瀣煙缁嬫寧鐭楅柟?        deviceSM.incrementCommands()
        addLog('down', topic, payload, cmdInfo.preempt ? 'command_preempt' : 'command', extractedTurnId)
        _setLiveTrace(
          cmdInfo.cmd ? `閻庤鐡曠亸娆撳极閹捐绠ｉ柟閭﹀幖閻︾懓霉閻橆喖鈧呮?{cmdInfo.cmd}` : '閻庤鐡曠亸娆撳极閹捐绠ｉ柟閭﹀幖閻︾懓霉?,
          { lastReplyText: cmdInfo.cmd || state.lastReplyText, lastSessionStatus: 'command' },
        )
        break

      case 'session_hb':
        state.heartbeatActive = true
        state.lastHeartbeatAt = new Date()
        state.heartbeatHistory.push({ timestamp: new Date() })
        if (state.heartbeatHistory.length > MAX_HEARTBEATS) state.heartbeatHistory.shift()
        addLog('up', topic, payload, 'session_hb')
        if (!state.lastEventSummary) {
          _setLiveTrace('婵炴潙鍚嬫穱娲儊閸婄喓鐤€闁告劦鍘鹃崕鑼偓鐟版啞瑜板啴宕虹仦鐐秶?, { lastSessionStatus: state.lastSessionStatus || 'active' })
        }
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
    // 闂佺粯顭堥崺鏍焵椤戣法鍔嶆繝褉鍋撻梺鎸庣⊕閼归箖宕㈠☉姘皫闁哄鐏濋悡?SESSION_ENDED闂佹寧绋戦悧鍡涘触鐎ｎ兘鍋?CAPTURING / WAITING / SESSION_ACTIVE闂?
    deviceSM.transitionTo(DeviceState.SESSION_ENDED)
    if (isConnected.value) {
      state.status = 'active'
      // 闂佺粯顭堥崺鏍焵椤戣法鍔嶆繝褉鍋撻梺鎸庣⊕閻℃摗SSION_ENDED 闂?IDLE闂佹寧绋戦悧鎰邦敊閺囩喎绶為柛銉閻繈鏌涢敂鍝勫闁搞倕閰ｉ弫?
      deviceSM.transitionTo(DeviceState.IDLE)
    } else {
      state.isOnline = false
      state.status = 'idle'
      // 闂佺粯顭堥崺鏍焵椤戣法鍔嶆繝褉鍋撻梺鎸庣⊕椤戞—LE 闂?OFFLINE
      deviceSM.transitionTo(DeviceState.OFFLINE)
    }
    state.sessionId = undefined
    state.lastEventSummary = undefined
    state.lastEventAt = undefined
    state.lastSessionStatus = undefined
    state.lastSttText = undefined
    state.lastReplyText = undefined
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
    sendTurn,
    stopSimulation,
    clearLogs,
    onDeviceEvicted,
    connectSystemWS,
  }
}

function isCueTopic(turnId?: string): boolean {
  return !!turnId && turnId.startsWith('cue-')
}
