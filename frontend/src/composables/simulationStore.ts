import { reactive, computed } from 'vue'
import type { MQTTMessageLog, TurnInfo, CommandInfo, DeviceSimulationState } from './useMQTTSimulation'

export interface SimulationEntry {
  deviceId: string
  figurineId: string
  mode: string
  logs: MQTTMessageLog[]
  sttResult: any
  state: DeviceSimulationState
  isSimulating: boolean
  isConnected: boolean
  status: string
  sentChunks: number
  sessionId: string | undefined
  activeTurns: TurnInfo[]
  commands: CommandInfo[]
  sttTexts: string[]
  cueCount: number
  currentTurn: number
  protocolVersion: string
  fwVersion: string
}

export const store = reactive<{
  active: boolean
  entry: SimulationEntry | null
}>({
  active: false,
  entry: null,
})

export const hasActive = computed(() => store.active && store.entry !== null)

export function registerSimulation(opts: {
  deviceId: string
  figurineId: string
  mode: string
  logsRef: any
  sttResultRef: any
  state: any
  isSimulatingRef: any
  isConnectedRef?: any
}) {
  store.active = true
  const s = opts.state as DeviceSimulationState
  store.entry = {
    deviceId: opts.deviceId,
    figurineId: opts.figurineId,
    mode: opts.mode,
    logs: opts.logsRef,
    sttResult: opts.sttResultRef,
    state: s,
    isSimulating: opts.isSimulatingRef,
    isConnected: opts.isConnectedRef?.value ?? false,
    get status() { return s.status },
    get sentChunks() { return s.sentChunks ?? 0 },
    get sessionId() { return s.sessionId },
    get activeTurns() { return s.activeTurns ?? [] },
    get commands() { return s.commands ?? [] },
    get sttTexts() { return s.sttTexts ?? [] },
    get cueCount() { return s.cueCount ?? 0 },
    get currentTurn() { return s.currentTurn ?? 0 },
    get protocolVersion() { return s.protocolVersion ?? 'v1.6' },
    get fwVersion() { return s.fwVersion ?? '1.6.0' },
  }
}

export function clearSimulation() {
  store.active = false
  store.entry = null
}
