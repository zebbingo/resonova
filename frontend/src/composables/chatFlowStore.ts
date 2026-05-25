/**
 * 会话流程步骤共享状态
 *
 * 管理流程时间线：设备初始化 → 角色配置 → 对话交互（自动推导 + WS 监控）。
 *
 * 数据来源：
 * 1. DeviceCard 生命周期中直接调用 addStep/completeStep
 * 2. watch(simulationStore.logs) 自动推导 MQTT 步骤
 * 3. WebSocket /ws/monitoring 补充精确耗时
 */
import { reactive, watch } from 'vue'
import { store as simStore } from './simulationStore'

// ── 类型 ────────────────────────────────────────────────

export type FlowPhaseId = 'device' | 'role' | 'session'

export interface FlowStepNode {
  id: string
  label: string
  detail?: string
  status: 'pending' | 'running' | 'completed' | 'error'
  timestamp: string
  extra?: string          // 特殊内容如开场白文本
  duration_ms?: number    // 后端监控事件提供的精确耗时
}

export interface FlowPhase {
  id: FlowPhaseId
  title: string
  icon: string
  steps: FlowStepNode[]
  expanded: boolean
}

// ── 模块级单例 ──────────────────────────────────────────

export const flowStore = reactive<{
  active: boolean
  phases: FlowPhase[]
}>({
  active: false,
  phases: [],
})

let _counter = 0

function now(): string {
  const d = new Date()
  return [
    String(d.getHours()).padStart(2, '0'),
    String(d.getMinutes()).padStart(2, '0'),
    String(d.getSeconds()).padStart(2, '0'),
  ].join(':')
}

const MAX_STEPS = 100 // 单阶段最大步骤数，避免长时间测试导致内存膨胀

// ── 公共方法 ────────────────────────────────────────────

export function initFlow() {
  _counter = 0
  flowStore.active = true
  flowStore.phases = [
    { id: 'device', title: '设备初始化', icon: '📱', steps: [], expanded: true },
    { id: 'role',   title: '角色配置',    icon: '🎭', steps: [], expanded: true },
    { id: 'session',title: '对话交互',    icon: '💬', steps: [], expanded: false },
  ]
}

export function resetFlow() {
  flowStore.active = false
  flowStore.phases = []
  _counter = 0
  _processedLogCount = 0
  disconnectMonitoring()
}

/** 添加一个步骤（status = running）并返回其 id */
export function addStep(
  phase: FlowPhaseId,
  label: string,
  detail?: string,
  extra?: string,
  duration_ms?: number,
): string {
  const p = flowStore.phases.find(x => x.id === phase)
  if (!p) return ''

  // 限制阶段内步骤数量
  if (p.steps.length >= MAX_STEPS) {
    p.steps.shift()
  }

  _counter++
  const id = `step_${_counter}`
  p.expanded = true
  p.steps.push({ id, label, detail, status: 'running', timestamp: now(), extra, duration_ms })
  return id
}

/** 用 id 或 label 匹配并标记完成 */
export function completeStep(phase: FlowPhaseId, idOrLabel: string, detail?: string, duration_ms?: number) {
  const p = flowStore.phases.find(x => x.id === phase)
  if (!p) return
  const s = p.steps.find(x => x.id === idOrLabel || x.label === idOrLabel)
  if (s) {
    s.status = 'completed'
    s.timestamp = now()
    if (detail) s.detail = detail
    if (duration_ms !== undefined) s.duration_ms = duration_ms
  }
}

/** 标记为失败 */
export function failStep(phase: FlowPhaseId, idOrLabel: string, detail?: string) {
  const p = flowStore.phases.find(x => x.id === phase)
  if (!p) return
  const s = p.steps.find(x => x.id === idOrLabel || x.label === idOrLabel)
  if (s) {
    s.status = 'error'
    s.timestamp = now()
    if (detail) s.detail = detail
  }
}

/** 获取指定阶段的步骤计数 */
export function phaseStatus(phase: FlowPhaseId | string): { total: number; done: number; running: number; error: number } {
  const p = flowStore.phases.find(x => x.id === phase)
  if (!p) return { total: 0, done: 0, running: 0, error: 0 }
  const steps = p.steps
  return {
    total: steps.length,
    done: steps.filter(s => s.status === 'completed').length,
    running: steps.filter(s => s.status === 'running').length,
    error: steps.filter(s => s.status === 'error').length,
  }
}

// ── WebSocket 监控连接（补充精确耗时）─────────────────────

let _monitoringWS: WebSocket | null = null
let _reconnectAttempts = 0
const MAX_RECONNECT = 10
let _reconnectTimer: ReturnType<typeof setTimeout> | null = null

function wsUrl(): string {
  // 使用相对路径，通过 Vite 代理转发到 WSL 后端
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
  return `${protocol}//${window.location.host}/ws/monitoring/events`
}

export function connectMonitoring() {
  if (_monitoringWS && (_monitoringWS.readyState === WebSocket.OPEN || _monitoringWS.readyState === WebSocket.CONNECTING)) {
    return
  }

  try {
    _monitoringWS = new WebSocket(wsUrl())

    _monitoringWS.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data)
        handleMonitoringEvent(data)
      } catch {
        // ignore malformed messages
      }
    }

    _monitoringWS.onopen = () => {
      _reconnectAttempts = 0
    }

    _monitoringWS.onclose = () => {
      _monitoringWS = null
      scheduleReconnect()
    }

    _monitoringWS.onerror = () => {
      // onclose will fire next
    }
  } catch {
    scheduleReconnect()
  }
}

function scheduleReconnect() {
  if (!flowStore.active) return // 已退出不再重连
  if (_reconnectAttempts >= MAX_RECONNECT) return

  _reconnectAttempts++
  const delay = Math.min(2 ** _reconnectAttempts * 1000, 30000) // 指数退避 2s~30s
  _reconnectTimer = setTimeout(() => { connectMonitoring() }, delay)
}

function disconnectMonitoring() {
  if (_reconnectTimer) { clearTimeout(_reconnectTimer); _reconnectTimer = null }
  _reconnectAttempts = 0
  if (_monitoringWS) {
    _monitoringWS.onclose = null // 阻止意图关闭触发重连
    _monitoringWS.close()
    _monitoringWS = null
  }
}

/** 处理后端监控事件 → 补充精确耗时 / 添加日志无法捕获的步骤 */
function handleMonitoringEvent(event: any) {
  if (!flowStore.active) return
  const phase: FlowPhaseId = 'session'

  const updateDuration = (label: string, ms: number) => {
    const step = flowStore.phases.find(x => x.id === phase)?.steps.find(s => s.label === label)
    if (step) step.duration_ms = ms
  }

  switch (event.type) {
    case 'vad_speech_started':
      addStep(phase, '语音检测', '检测到用户开始说话')
      break

    case 'vad_speech_stopped':
      completeStep(phase, '语音检测', '✅ 用户说话结束')
      break

    case 'stt_inference': {
      const text = event.text || ''
      const textDetail = text ? `识别: "${text.slice(0, 60)}${text.length > 60 ? '…' : ''}"` : ''
      addStep(phase, '语音识别 (STT)', textDetail, text.slice(0, 200), event.duration_ms)
      completeStep(phase, '语音识别 (STT)', textDetail, event.duration_ms)
      updateDuration('语音识别', event.duration_ms)
      break
    }

    case 'moderation_complete': {
      const flagged = event.flagged ?? false
      const duration = event.duration_ms ?? '?'
      const blockReasons = event.block_reasons ?? []
      
      if (flagged) {
        addStep(phase, '内容审核（用户）', `⚠️ 检测到违规内容 (${blockReasons.join(', ')})`)
        completeStep(phase, '内容审核（用户）')
      } else {
        addStep(phase, '内容审核（用户）', `正在检查敏感内容...`)
        completeStep(phase, '内容审核（用户）', `✅ 审核通过 (${duration}ms)`)
      }
      break
    }

    case 'llm_inference': {
      const responseText = event.response_text || ''
      const detail = `响应长度: ${event.response_length ?? '?'}字`
      addStep(phase, 'LLM 推理', detail, undefined, event.duration_ms)
      completeStep(phase, 'LLM 推理', detail, event.duration_ms)

      // 回复文本 — 单独步骤展示 LLM 的输出内容
      if (responseText) {
        addStep(phase, '回复文本', responseText.slice(0, 80) + (responseText.length > 80 ? '…' : ''), responseText, event.duration_ms)
        completeStep(phase, '回复文本')
      }
      break
    }

    case 'output_moderation_complete': {
      const flagged = event.flagged ?? false
      const source = event.source ?? 'none'
      
      if (flagged) {
        addStep(phase, '内容审核（Bot）', `⚠️ 回复被拦截 (${source})`)
        completeStep(phase, '内容审核（Bot）')
      } else {
        addStep(phase, '内容审核（Bot）', `正在检查回复内容...`)
        completeStep(phase, '内容审核（Bot）', `✅ 审核通过`)
      }
      break
    }

    case 'tts_synthesis': {
      const ttsText = event.text || ''
      const detail = `音频帧: ${event.chunk_count ?? '?'} | 文本: ${(ttsText || '').slice(0, 30)}${(ttsText || '').length > 30 ? '…' : ''}`
      addStep(phase, '语音合成 (TTS)', detail, ttsText.slice(0, 200), event.duration_ms)
      completeStep(phase, '语音合成 (TTS)', detail, event.duration_ms)
      break
    }

    case 'intro_start':
      addStep(phase, '开场白播放', '播放中…')
      break

    case 'intro_end':
      completeStep(phase, '开场白播放', '播放完成')
      break

    case 'mqtt_publish': {
      // chatbot 向下游发布 MQTT 响应（音频下发）
      const msgType = event.message_type || ''
      if (msgType === 'audio_eos') {
        addStep(phase, '回复音频传输', `下发完成 · 共 ${event.total_seq ?? '?'} 帧 · ${event.duration_ms ?? '?'}ms`)
        completeStep(phase, '回复音频传输')
        addStep(phase, '回复播放完成', '设备端播放')
        completeStep(phase, '回复播放完成')
      }
      break
    }
  }
}

// ── 自动推导：监听 simulationStore.logs → 生成 session 阶段步骤 ──

let _processedLogCount = 0

export function startAutoDerive() {
  _processedLogCount = 0
  // 同时启动 WS 监控连接
  connectMonitoring()
}

watch(
  () => simStore.entry?.logs,
  (logs) => {
    if (!logs || !simStore.active || !flowStore.active) return
    if (!flowStore.phases.find(x => x.id === 'session')) return

    for (let i = _processedLogCount; i < logs.length; i++) {
      _processedLogCount = i + 1
      const log = logs[i]
      const phase: FlowPhaseId = 'session'

      //
      // 注意：后端 _translate_ws_event() 已将 MQTT 完整路径解析为 short_topic，
      //       useMQTTSimulation.addLog 将其写入 log.type (message_type)。
      //       因此以下匹配以 log.type 为主，log.topic 做向后兼容。
      //

      if (log.direction === 'up') {
        const upType = log.type  // session_start | audio_start | chunk | eos | session_end | other

        if (upType === 'session_start') {
          // 检查是否已存在该步骤，避免重复添加
          const existingStep = flowStore.phases.find(x => x.id === phase)?.steps.find(s => s.label === '会话创建')
          if (!existingStep) {
            addStep(phase, '会话创建')
          }
          completeStep(phase, '会话创建')
        } else if (upType === 'audio_start') {
          // 检查是否已存在该步骤，避免重复添加
          const existingStep = flowStore.phases.find(x => x.id === phase)?.steps.find(s => s.label === '音频数据上传')
          if (!existingStep) {
            addStep(phase, '音频数据上传')
          }
          completeStep(phase, '音频数据上传', `发送 ${log.payload?.total_chunks || '?'} 帧`)
        } else if (upType === 'chunk') {
          // 为每个 chunk 创建独立的步骤（最多显示前 10 个）
          const chunkIndex = log.payload?.seq ?? log.payload?.index ?? 1
          
          // 只显示前 10 个 chunk，避免步骤过多
          if (chunkIndex <= 10) {
            const stepLabel = `音频帧 #${chunkIndex}`
            
            // 检查是否已存在该步骤
            const existingStep = flowStore.phases.find(x => x.id === phase)?.steps.find(s => s.label === stepLabel)
            if (!existingStep) {
              addStep(phase, stepLabel, `大小: ${log.payload?.payload_size ?? '?'} bytes`)
              completeStep(phase, stepLabel)
            }
          }
        } else if (upType === 'eos') {
          // 检查是否已存在该步骤，避免重复添加
          const existingStep = flowStore.phases.find(x => x.id === phase)?.steps.find(s => s.label === '音频传输完成')
          if (!existingStep) {
            addStep(phase, '音频传输完成')
          }
          completeStep(phase, '音频传输完成')
        } else if (upType === 'session_end') {
          // 检查是否已存在该步骤，避免重复添加
          const existingStep = flowStore.phases.find(x => x.id === phase)?.steps.find(s => s.label === '会话结束')
          if (!existingStep) {
            addStep(phase, '会话结束')
          }
          completeStep(phase, '会话结束')
        }
      } else if (log.direction === 'down') {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const downType = (log as any).type

        // VAD 语音检测开始
        if (downType === 'vad_speech_started') {
          addStep(phase, '语音检测', '检测到用户开始说话')
        }
        // VAD 语音检测结束
        else if (downType === 'vad_speech_stopped') {
          completeStep(phase, '语音检测', '✅ 用户说话结束')
        }
        // STT 识别结果
        else if (downType === 'stt_result' || downType === 'stt_inference') {
          const text = log.payload?.text ?? ''
          const duration = log.payload?.duration_ms ?? '?'
          const detail = text ? `识别结果: ${text.slice(0, 60)}${text.length > 60 ? '…' : ''}` : undefined
          
          // 检查是否已存在该步骤
          const existingStep = flowStore.phases.find(x => x.id === phase)?.steps.find(s => s.label === '语音识别')
          if (!existingStep) {
            addStep(phase, '语音识别', `正在转换语音为文字...`)
          }
          completeStep(phase, '语音识别', text ? `✅ ${text.slice(0, 80)}${text.length > 80 ? '…' : ''} (${duration}ms)` : '❌ 未识别到内容')
        } 
        // LLM 推理结果
        else if (downType === 'llm_inference') {
          const status = log.payload?.status
          const duration = log.payload?.duration_ms ?? '?'
          const responseText = log.payload?.response_text ?? ''
          
          // 检查是否已存在该步骤
          const existingStep = flowStore.phases.find(x => x.id === phase)?.steps.find(s => s.label === '大语言模型推理')
          if (!existingStep) {
            addStep(phase, '大语言模型推理', `正在生成回复...`)
          }
          
          if (status === 'success') {
            completeStep(phase, '大语言模型推理', `✅ ${responseText.slice(0, 80)}${responseText.length > 80 ? '…' : ''} (${duration}ms)`)
          } else if (status === 'error') {
            completeStep(phase, '大语言模型推理', `❌ 错误: ${log.payload?.error ?? '未知错误'} (${duration}ms)`)
          } else if (status === 'timeout') {
            completeStep(phase, '大语言模型推理', `⏱️ 超时 (${duration}ms)`)
          }
        }
        // TTS 合成结果
        else if (downType === 'tts_synthesis') {
          const status = log.payload?.status
          const duration = log.payload?.duration_ms ?? '?'
          const chunkCount = log.payload?.chunk_count ?? '?'
          
          // 检查是否已存在该步骤
          const existingStep = flowStore.phases.find(x => x.id === phase)?.steps.find(s => s.label === '语音合成')
          if (!existingStep) {
            addStep(phase, '语音合成', `正在转换为语音...`)
          }
          
          if (status === 'success') {
            completeStep(phase, '语音合成', `✅ 生成 ${chunkCount} 个音频块 (${duration}ms)`)
          } else {
            completeStep(phase, '语音合成', `❌ 错误: ${log.payload?.error ?? '未知错误'} (${duration}ms)`)
          }
        }
        // Intro 开始
        else if (downType === 'intro_start') {
          addStep(phase, '播放开场白', `正在播放...`)
        }
        // Intro 结束
        else if (downType === 'intro_end') {
          completeStep(phase, '播放开场白', `✅ 开场白播放完成`)
        }
        // 用户输入内容审核
        else if (downType === 'moderation_complete') {
          const flagged = log.payload?.flagged ?? false
          const duration = log.payload?.duration_ms ?? '?'
          const blockReasons = log.payload?.block_reasons ?? []
          
          const stepLabel = '内容审核（用户）'
          const existingStep = flowStore.phases.find(x => x.id === phase)?.steps.find(s => s.label === stepLabel)
          if (!existingStep) {
            addStep(phase, stepLabel, `正在检查敏感内容...`)
          }
          
          if (flagged) {
            completeStep(phase, stepLabel, `⚠️ 检测到违规内容 (${blockReasons.join(', ')})`)
          } else {
            completeStep(phase, stepLabel, `✅ 审核通过 (${duration}ms)`)
          }
        }
        // Bot 输出内容审核
        else if (downType === 'output_moderation_complete') {
          const flagged = log.payload?.flagged ?? false
          const source = log.payload?.source ?? 'none'
          
          const stepLabel = '内容审核（Bot）'
          const existingStep = flowStore.phases.find(x => x.id === phase)?.steps.find(s => s.label === stepLabel)
          if (!existingStep) {
            addStep(phase, stepLabel, `正在检查回复内容...`)
          }
          
          if (flagged) {
            completeStep(phase, stepLabel, `⚠️ 回复被拦截 (${source})`)
          } else {
            completeStep(phase, stepLabel, `✅ 审核通过`)
          }
        }
        // 回复音频开始
        else if (downType === 'audio_start') {
          addStep(phase, '回复音频接收', '开始接收音频帧')
        } 
        // 回复音频 chunk
        else if (downType === 'audio_chunk') {
          const step = flowStore.phases.find(x => x.id === phase)?.steps.find(s => s.label === '回复音频接收')
          if (step) {
            step.detail = `接收中 · 第 ${log.payload?.seq || log.payload?.index || '?'} 帧`
          }
        } 
        // 回复音频结束
        else if (downType === 'audio_eos') {
          completeStep(phase, '回复音频接收', `传输完成 · ${log.payload?.total_seq || '?'} 帧 · ${log.payload?.duration_ms || '?'}ms`)
          addStep(phase, '回复播放完成', '设备端播放')
          completeStep(phase, '回复播放完成')
        } 
        // 指令下发
        else if (downType === 'command') {
          const cmd = log.payload?.cmd || log.payload?.command || ''
          addStep(phase, '指令下发', cmd ? `命令: ${cmd}` : undefined)
          completeStep(phase, '指令下发')
        } 
        // Session 状态
        else if (downType === 'session_status') {
          // session_status 包含 TTS 和回复信息的摘要
          const status = log.payload || log
          if (status.reply_text) {
            const hasReplyStep = flowStore.phases.find(x => x.id === phase)?.steps.some(s => s.label === '回复文本')
            if (!hasReplyStep) {
              addStep(phase, '回复文本', status.reply_text.slice(0, 80) + (status.reply_text.length > 80 ? '…' : ''), status.reply_text)
              completeStep(phase, '回复文本')
            }
          }
          if (status.tts_chunks && status.tts_chunks > 0) {
            const detail = `共 ${status.tts_chunks} 音频帧 · ${status.tts_duration_ms ? status.tts_duration_ms + 'ms' : ''}`
            completeStep(phase, '回复音频接收', detail)
            addStep(phase, '回复播放完成', '设备端播放')
            completeStep(phase, '回复播放完成')
          }
        } 
        // 其他 response 消息
        else if (log.topic?.includes('/response/') && downType === 'other') {
          const text = log.payload?.text || ''
          if (text) {
            addStep(phase, '回复文本', text.slice(0, 80) + (text.length > 80 ? '…' : ''), text)
            completeStep(phase, '回复文本')
          }
        }
      }
    }
  },
  { deep: true },
)
