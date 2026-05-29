<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import axios from 'axios'
import type { AudioItem } from '../types'
import { fetchFigurines } from '../api'
import DeviceCard from './DeviceCard.vue'

const props = defineProps<{
  audios: AudioItem[]
  formatSize: (bytes: number) => string
}>()

// 从 API 加载数据库中的真实角色（用于折叠时显示角色名）
const figurineNameMap = ref<Record<string, string>>({})

async function loadFigurineNames() {
  try {
    const resp = await fetchFigurines()
    const map: Record<string, string> = {}
    for (const fig of resp.figurines) {
      map[fig.figurine_id] = fig.character_name
    }
    figurineNameMap.value = map
  } catch (error) {
    console.error('加载角色列表失败:', error)
  }
}

// ── 轮询后端设备状态 ──────────────────────────────────────
// 每 20 秒检查一次后端有哪些设备是活跃的，同步 isOnline 状态
let _statusPollTimer: ReturnType<typeof setInterval> | null = null
let _deviceCounter = 2

async function pollDeviceStatus() {
  try {
    const resp = await axios.get('/api/device/list')
    const activeDeviceIds = new Set(
      (resp.data.devices || [])
        .filter((d: any) => d.connected)
        .map((d: any) => d.device_id)
    )
    for (const device of devices.value) {
      const wasOnline = device.isOnline
      device.isOnline = activeDeviceIds.has(device.id)
      // 如果设备从在线变为离线（被后端回收），更新状态
      if (wasOnline && !device.isOnline) {
        console.warn(`[DeviceManager] 设备 ${device.id} 已被后端回收或断线`)
      }
    }
  } catch {
    // 后端可能暂不可达，静默处理
  }
}

onMounted(() => {
  loadFigurineNames()
  // 立即轮询一次，然后每 20s 自动轮询
  pollDeviceStatus()
  _statusPollTimer = setInterval(pollDeviceStatus, 20_000)
})

onUnmounted(() => {
  if (_statusPollTimer !== null) {
    clearInterval(_statusPollTimer)
    _statusPollTimer = null
  }
})

// 设备列表（最多4个设备）
interface Device {
  id: string
  name: string
  expanded: boolean  // 展开/折叠状态
  figurineId: string  // 选择的角色
  mode: 'dialogue' | 'story' | 'music'  // 模式
  isOnline: boolean  // 是否在线
  mqttProfile: string  // MQTT broker 连接配置文件
}

const devices = ref<Device[]>([
  { 
    id: 'device-1', 
    name: '设备 1', 
    expanded: true,
    figurineId: '',
    mode: 'dialogue',
    isOnline: false,
    mqttProfile: 'local',
  },
])

// 添加设备
function addDevice() {
  if (devices.value.length >= 4) {
    alert('最多支持 4 个设备')
    return
  }
  const newId = `device-${_deviceCounter++}`
  devices.value.push({
    id: newId,
    name: `设备 ${devices.value.length + 1}`,
    expanded: false,  // 新设备默认折叠
    figurineId: '',
    mode: 'dialogue',
    isOnline: false,
    mqttProfile: 'local',
  })
}

// 删除设备
function removeDevice(deviceId: string) {
  if (devices.value.length <= 1) {
    alert('至少保留一个设备')
    return
  }
  devices.value = devices.value.filter(d => d.id !== deviceId)
}

// 切换展开/折叠
function toggleExpand(deviceId: string) {
  const device = devices.value.find(d => d.id === deviceId)
  if (device) {
    device.expanded = !device.expanded
  }
}

// 更新设备状态（由 DeviceCard 触发）
function updateDeviceStatus(deviceId: string, status: { figurineId?: string; mode?: string; isOnline?: boolean; mqttProfile?: string }) {
  const device = devices.value.find(d => d.id === deviceId)
  if (device) {
    if (status.figurineId !== undefined) device.figurineId = status.figurineId
    if (status.mode !== undefined) device.mode = status.mode as any
    if (status.isOnline !== undefined) device.isOnline = status.isOnline
    if (status.mqttProfile !== undefined) device.mqttProfile = status.mqttProfile
  }
}

// 获取角色名称（从动态加载的 API 数据中查）
function getFigurineName(figurineId: string): string {
  if (!figurineId) return '未选择'
  return figurineNameMap.value[figurineId] || '未选择'
}

// 获取模式名称
function getModeName(mode: string): string {
  const names: Record<string, string> = {
    'dialogue': '💬 对话',
    'story': '📖 故事',
    'music': '🎵 音乐',
  }
  return names[mode] || '未知'
}

// 获取 Broker 标签
function getBrokerLabel(profile: string): string {
  const labels: Record<string, string> = {
    'local': '📡 本地',
    'relay': '🔁 中转',
    'custom': '⚙️ 自定义',
    'aws_iot': '☁️ AWS IoT',
  }
  return labels[profile] || '📡 ' + profile
}
</script>

<template>
  <div class="device-manager">
    <!-- 添加设备按钮 -->
    <div class="manager-header">
      <button 
        class="btn-add" 
        :disabled="devices.length >= 4"
        @click="addDevice"
      >
        ➕ 添加设备 ({{ devices.length }}/4)
      </button>
    </div>

    <!-- 设备列表 -->
    <div class="device-list">
      <div v-for="device in devices" :key="device.id" class="device-wrapper">
        <!-- 设备头部（可点击展开/折叠） -->
        <div class="device-header" @click="toggleExpand(device.id)">
          <div class="header-left">
            <span class="expand-icon">{{ device.expanded ? '▼' : '▶' }}</span>
            <span class="device-name">{{ device.name }}</span>
          </div>
          
          <!-- 收缩时显示的基本信息 -->
          <div v-if="!device.expanded" class="device-summary">
            <span class="summary-item">
              🎭 {{ getFigurineName(device.figurineId) }}
            </span>
            <span class="summary-item">
              {{ getModeName(device.mode) }}
            </span>
            <span class="summary-item broker-indicator" :title="'MQTT: ' + device.mqttProfile">
              {{ getBrokerLabel(device.mqttProfile) }}
            </span>
            <span class="status-badge" :class="{ online: device.isOnline }">
              {{ device.isOnline ? '🟢 在线' : '⚪ 离线' }}
            </span>
          </div>
          
          <button 
            v-if="devices.length > 1"
            class="btn-remove"
            @click.stop="removeDevice(device.id)"
            title="删除设备"
          >
            ❌
          </button>
        </div>

        <!-- 设备卡片（展开时显示） -->
        <div v-show="device.expanded" class="device-content">
          <DeviceCard
            :audios="audios"
            :format-size="formatSize"
            :persistence-key="device.id"
            @update-status="updateDeviceStatus(device.id, $event)"
          />
        </div>
      </div>
    </div>

    <!-- 空状态提示 -->
    <div v-if="devices.length === 0" class="empty-state">
      点击“➕ 添加设备”开始测试
    </div>
  </div>
</template>

<style scoped>
.device-manager {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.manager-header {
  margin-bottom: 8px;
}

.btn-add {
  width: 100%;
  background: var(--accent);
  border: none;
  color: #fff;
  padding: 10px 16px;
  border-radius: var(--radius);
  font-size: 0.9rem;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}

.btn-add:hover:not(:disabled) {
  background: var(--accent2);
}

.btn-add:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.device-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.device-wrapper {
  position: relative;
}

.device-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 12px 16px;
  background: var(--bg);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  cursor: pointer;
  transition: all 0.2s;
}

.device-header:hover {
  background: var(--bg2);
  border-color: var(--accent);
}

.header-left {
  display: flex;
  align-items: center;
  gap: 8px;
}

.expand-icon {
  font-size: 0.8rem;
  color: var(--text2);
  width: 16px;
  text-align: center;
}

.device-name {
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--text);
}

/* 收缩时的基本信息 */
.device-summary {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-left: auto;
  margin-right: 12px;
}

.summary-item {
  font-size: 0.85rem;
  color: var(--text2);
  white-space: nowrap;
}

.status-badge {
  font-size: 0.8rem;
  padding: 4px 8px;
  border-radius: 12px;
  background: #f3f4f6;
  color: #6b7280;
}

.status-badge.online {
  background: #d1fae5;
  color: #065f46;
}

.broker-indicator {
  font-size: 0.75rem;
  padding: 2px 8px;
  border-radius: 10px;
  background: #1a1a2a;
  color: #a78bfa;
}

.btn-remove {
  background: none;
  border: none;
  font-size: 1rem;
  cursor: pointer;
  opacity: 0.6;
  transition: opacity 0.2s;
  padding: 4px 8px;
}

.btn-remove:hover {
  opacity: 1;
}

.empty-state {
  text-align: center;
  color: var(--text2);
  padding: 40px 20px;
  font-size: 0.9rem;
}
</style>
