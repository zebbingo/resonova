/**
 * 正式设备状态机 — 与后端 device_firmware.py 完全同步
 *
 * 后端 DeviceState 流转:
 *   OFFLINE → IDLE (power_on)
 *   IDLE → SESSION_ACTIVE (start_session)
 *   SESSION_ACTIVE → CAPTURING (start_turn)
 *   CAPTURING → WAITING (eos 发出)
 *   WAITING → CAPTURING (下一 turn) | SESSION_ENDED (stop_session)
 *   SESSION_ENDED → IDLE (清理完成)
 *   IDLE → OFFLINE (power_off)
 *
 * 前端额外增加 CONNECTING（UI 过渡态，后端无此状态）
 *
 * 使用方式:
 *   import { deviceSM, DeviceState, SessionMode } from '../stores/deviceStateMachine'
 *   deviceSM.transitionTo(DeviceState.CONNECTING, { figurineId: 'doctor' })
 */

import { reactive, computed, type ComputedRef } from 'vue'

// ── 状态枚举 ────────────────────────────────────────────

export enum DeviceState {
  OFFLINE        = 'offline',
  CONNECTING     = 'connecting',       // 前端专有：UI 过渡态
  IDLE           = 'idle',
  SESSION_ACTIVE = 'session_active',
  CAPTURING      = 'capturing',        // 上行音频采集
  WAITING        = 'waiting',          // 等待服务端响应
  SESSION_ENDED  = 'session_ended',
  ERROR          = 'error',            // 错误态
}

export enum SessionMode {
  DIALOGUE = 'dialogue',
  STORY    = 'story',
  MUSIC    = 'music',
}

// ── 有效转换表（key = "源状态->目标状态") ────────────────

const VALID_TRANSITIONS: Record<string, string> = {
  // 连接生命周期
  'offline->connecting':      '启动模拟连接',
  'connecting->idle':         'MQTT 连接成功 / 初始化完成',
  'idle->offline':            '停止模拟 / 设备断电',

  // 会话生命周期
  'idle->session_active':     '开始对话 / 故事 / 音乐',
  'session_active->capturing':'上行音频开始（turn 内 CAPTURING）',
  'capturing->waiting':       '音频 EOS 发出，等待响应',
  'waiting->capturing':       '下一个 turn 开始',
  'waiting->session_active':  '响应接收完毕（无下一 turn）',
  'session_active->session_ended': '会话结束',
  'waiting->session_ended':       '等待中会话结束',
  'capturing->session_ended':     '录音中会话结束',
  'session_ended->idle':          '清理完成，回到待机',

  // 错误恢复
  'error->idle':              '手动重置',
  'error->offline':           '断开连接',
}
Object.freeze(VALID_TRANSITIONS)

// ── 状态机内部状态 ──────────────────────────────────────

interface StateMachineData {
  deviceState: DeviceState
  sessionMode: SessionMode
  figurineId: string
  deviceId: string
  errorMessage: string
  turnCount: number
  sentChunks: number
  receivedChunks: number
  commandCount: number
}

const _state = reactive<StateMachineData>({
  deviceState: DeviceState.OFFLINE,
  sessionMode: SessionMode.DIALOGUE,
  figurineId: '',
  deviceId: '',
  errorMessage: '',
  turnCount: 0,
  sentChunks: 0,
  receivedChunks: 0,
  commandCount: 0,
})

// ── 公开响应式计算属性 ──────────────────────────────────

const deviceState: ComputedRef<DeviceState> = computed(() => _state.deviceState)
const isOffline: ComputedRef<boolean> = computed(() => _state.deviceState === DeviceState.OFFLINE)
const isConnecting: ComputedRef<boolean> = computed(() => _state.deviceState === DeviceState.CONNECTING)
const isIdle: ComputedRef<boolean> = computed(() => _state.deviceState === DeviceState.IDLE)
const isSessionActive: ComputedRef<boolean> = computed(() => _state.deviceState === DeviceState.SESSION_ACTIVE)

const stateLabel: ComputedRef<string> = computed(() => {
  const labels: Record<string, string> = {
    [DeviceState.OFFLINE]:        '离线',
    [DeviceState.CONNECTING]:     '连接中',
    [DeviceState.IDLE]:           '在线待机',
    [DeviceState.SESSION_ACTIVE]: '对话中',
    [DeviceState.CAPTURING]:      '上行录音',
    [DeviceState.WAITING]:        '等待响应',
    [DeviceState.SESSION_ENDED]:  '会话结束',
    [DeviceState.ERROR]:          '错误',
  }
  return labels[_state.deviceState] || _state.deviceState
})

// ── 状态颜色 / 图标 ────────────────────────────────────

const stateColor: ComputedRef<string> = computed(() => {
  const map: Record<string, string> = {
    [DeviceState.OFFLINE]:        'var(--text3)',
    [DeviceState.CONNECTING]:     'var(--orange)',
    [DeviceState.IDLE]:           'var(--green)',
    [DeviceState.SESSION_ACTIVE]: 'var(--accent)',
    [DeviceState.CAPTURING]:      '#e74c3c',
    [DeviceState.WAITING]:        '#f39c12',
    [DeviceState.SESSION_ENDED]:  '#95a5a6',
    [DeviceState.ERROR]:          '#e74c3c',
  }
  return map[_state.deviceState] || 'var(--red)'
})

const stateIcon: ComputedRef<string> = computed(() => {
  const map: Record<string, string> = {
    [DeviceState.OFFLINE]:        '⏹',
    [DeviceState.CONNECTING]:     '🔄',
    [DeviceState.IDLE]:           '⏸',
    [DeviceState.SESSION_ACTIVE]: '▶',
    [DeviceState.CAPTURING]:      '🎤',
    [DeviceState.WAITING]:        '⏳',
    [DeviceState.SESSION_ENDED]:  '⏹',
    [DeviceState.ERROR]:          '❌',
  }
  return map[_state.deviceState] || '❌'
})

// ── 转换函数 ────────────────────────────────────────────

function transitionTo(
  target: DeviceState,
  opts?: {
    sessionMode?: SessionMode
    figurineId?: string
    deviceId?: string
    errorMessage?: string
  },
): boolean {
  const current = _state.deviceState
  const key = `${current}->${target}`

  if (!VALID_TRANSITIONS[key]) {
    console.warn(
      `[DeviceSM] 非法转换: ${current} → ${target} (${key} 未在 VALID_TRANSITIONS 中定义)`,
    )
    return false
  }

  // 转换前侧效应
  if (target === DeviceState.CONNECTING || target === DeviceState.IDLE) {
    _state.errorMessage = ''
  }
  if (target === DeviceState.OFFLINE) {
    _state.turnCount = 0
    _state.sentChunks = 0
    _state.receivedChunks = 0
    _state.commandCount = 0
    _state.errorMessage = ''
    _state.sessionMode = SessionMode.DIALOGUE
  }

  // 设置新状态
  _state.deviceState = target
  if (opts?.sessionMode) _state.sessionMode = opts.sessionMode
  if (opts?.figurineId !== undefined) _state.figurineId = opts.figurineId
  if (opts?.deviceId !== undefined) _state.deviceId = opts.deviceId
  if (opts?.errorMessage !== undefined) _state.errorMessage = opts.errorMessage

  console.log(`[DeviceSM] ${key} → ${target} (mode=${_state.sessionMode})`)
  return true
}

function setError(message: string) {
  _state.deviceState = DeviceState.ERROR
  _state.errorMessage = message
}

function reset() {
  transitionTo(DeviceState.OFFLINE)
}

// ── 统计追踪 ────────────────────────────────────────────

function incrementTurn() { _state.turnCount++ }
function incrementSentChunks(n = 1) { _state.sentChunks += n }
function incrementReceivedChunks(n = 1) { _state.receivedChunks += n }
function incrementCommands(n = 1) { _state.commandCount += n }

// ── 导出 ────────────────────────────────────────────────

export const deviceSM = {
  get deviceState() { return _state.deviceState },
  get sessionMode() { return _state.sessionMode },
  get figurineId() { return _state.figurineId },
  get deviceId() { return _state.deviceId },
  get errorMessage() { return _state.errorMessage },
  get turnCount() { return _state.turnCount },
  get sentChunks() { return _state.sentChunks },
  get receivedChunks() { return _state.receivedChunks },
  get commandCount() { return _state.commandCount },

  deviceState,
  isOffline,
  isConnecting,
  isIdle,
  isSessionActive,
  stateLabel,
  stateColor,
  stateIcon,

  transitionTo,
  setError,
  reset,
  incrementTurn,
  incrementSentChunks,
  incrementReceivedChunks,
  incrementCommands,
}
