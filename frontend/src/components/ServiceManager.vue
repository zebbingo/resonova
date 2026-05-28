<script setup lang="ts">
import { ref, onMounted, onUnmounted, reactive } from 'vue'

interface ServiceInfo {
  id: string
  name: string
  running: boolean
  pid: number | null
  port: number | null
  suites: string[]
  log: string
}

interface EnvVar {
  key: string
  description: string
  default: string
  current?: string
  source?: string
}

interface ProfileInfo {
  group: string
  group_label: string
  group_description: string
  active: string
  available: string[]
  available_labels: Record<string, string>
  available_descriptions: Record<string, string>
}

interface EnvFileInfo {
  id: string
  path: string
  exists: boolean
  label: string
  description: string
}

interface EnvSwitchOption {
  value: string
  active: boolean
  line: number
  comment: string
}

interface EnvSwitchGroup {
  key: string
  description: string[]
  options: EnvSwitchOption[]
  has_active: boolean
  active_value: string | null
}

interface EnvScanResult {
  success: boolean
  file: string
  file_id: string
  file_label: string
  switch_groups: EnvSwitchGroup[]
  single_var_count: number
  total_lines: number
}

interface ServiceAnnotation {
  name: string
  description: string
  env_vars: EnvVar[]
  profile: ProfileInfo | null
}

const services = ref<ServiceInfo[]>([])
const annotations = ref<Record<string, ServiceAnnotation>>({})
const error = ref('')
const expandedSvc = ref<string | null>(null)
const logContent = ref('')
const logBusy = ref(false)
const actionBusy = ref<Set<string>>(new Set())
const envExpanded = ref<Set<string>>(new Set())
const profileBusy = ref(false)
const envVarsCache = ref<Record<string, EnvVar[]>>({})
const envFiles = ref<EnvFileInfo[]>([])
const envScans = ref<Record<string, EnvScanResult>>({})
const envSwitchBusy = ref<Set<string>>(new Set())
const envError = ref('')
let pollTimer: ReturnType<typeof setInterval> | null = null

const suites: { id: string; label: string }[] = [
  { id: 'all', label: '全部服务' },
  { id: 'chatbot', label: 'Chatbot 套件' },
  { id: 'stt', label: 'STT 套件' },
]

async function fetchStatus() {
  try {
    const [r, a] = await Promise.all([
      fetch('/api/services'),
      fetch('/api/services/annotations'),
    ])
    const d = await r.json()
    const ad = await a.json()
    if (d.services) services.value = d.services
    if (ad) annotations.value = ad
  } catch {
    // silent — poll will retry
  }
}

async function doAction(action: string, suite: string) {
  const key = `${action}:${suite}`
  actionBusy.value = new Set([...actionBusy.value, key])
  error.value = ''
  try {
    const r = await fetch(`/api/services/${action}/${suite}`, { method: 'POST' })
    const d = await r.json()
    if (d.services) services.value = d.services
    if (!d.success && d.error) error.value = d.error
  } catch {
    error.value = `${action} ${suite} 操作失败`
  } finally {
    const next = new Set(actionBusy.value)
    next.delete(key)
    actionBusy.value = next
  }
}

function isBusy(action: string, suite: string): boolean {
  return actionBusy.value.has(`${action}:${suite}`)
}

async function toggleLog(svcId: string) {
  if (expandedSvc.value === svcId) {
    expandedSvc.value = null
    return
  }
  expandedSvc.value = svcId
  logBusy.value = true
  logContent.value = ''
  try {
    const r = await fetch(`/api/services/log/${svcId}?lines=200`)
    const d = await r.json()
    logContent.value = d.log || '[无日志内容]'
  } catch {
    logContent.value = '[获取日志失败]'
  } finally {
    logBusy.value = false
  }
}

function toggleEnv(svcId: string) {
  const next = new Set(envExpanded.value)
  if (next.has(svcId)) {
    next.delete(svcId)
  } else {
    next.add(svcId)
    // 懒加载 env 详情
    if (!envVarsCache.value[svcId]) {
      fetch(`/api/services/${svcId}/env`)
        .then(r => r.json())
        .then(d => {
          if (d.success && d.env_vars) {
            envVarsCache.value[svcId] = d.env_vars
          }
        })
        .catch(() => {})
    }
  }
  envExpanded.value = next
}

async function switchProfile(svcId: string, profile: string) {
  profileBusy.value = true
  error.value = ''
  try {
    const r = await fetch(`/api/services/${svcId}/profiles`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ profile }),
    })
    const d = await r.json()
    if (d.services) services.value = d.services
    if (!d.success && d.error) error.value = d.error
    // 刷新注释信息
    await fetchStatus()
  } catch {
    error.value = '切换 profile 失败'
  } finally {
    profileBusy.value = false
  }
}

function envDisplay(svcId: string): string {
  const ann = annotations.value[svcId]
  if (!ann || !ann.env_vars || ann.env_vars.length === 0) return ''
  return ann.env_vars
    .map(v => `${v.key}=${v.current || v.default || ''}`)
    .join('\n')
}

async function fetchEnvFiles() {
  try {
    const r = await fetch('/api/env-config/files')
    const d = await r.json()
    if (d.files) {
      envFiles.value = d.files
      for (const f of d.files) {
        if (f.exists && !envScans.value[f.id]) {
          fetchEnvScan(f.id)
        }
      }
    }
  } catch {}
}

async function fetchEnvScan(fileId: string) {
  try {
    const r = await fetch(`/api/env-config/scan/${fileId}`)
    const d: EnvScanResult = await r.json()
    if (d.success) envScans.value[fileId] = d
  } catch {}
}

async function switchEnvOption(fileId: string, key: string, value: string) {
  const busyKey = `${fileId}:${key}:${value}`
  envSwitchBusy.value = new Set([...envSwitchBusy.value, busyKey])
  envError.value = ''
  try {
    const r = await fetch('/api/env-config/switch', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ file_id: fileId, key, target_value: value }),
    })
    const d = await r.json()
    if (d.success) {
      fetchEnvScan(fileId)
    } else {
      envError.value = d.error || '切换失败'
    }
  } catch {
    envError.value = '切换失败'
  } finally {
    const next = new Set(envSwitchBusy.value)
    next.delete(busyKey)
    envSwitchBusy.value = next
  }
}

onMounted(() => {
  fetchStatus()
  fetchEnvFiles()
  pollTimer = setInterval(fetchStatus, 5000)
})

onUnmounted(() => {
  if (pollTimer) clearInterval(pollTimer)
})
</script>

<template>
  <div class="svc-panel">
    <h2 class="svc-title">服务管理</h2>

    <!-- 套件操作 -->
    <div class="suite-actions">
      <div v-for="s in suites" :key="s.id" class="suite-row">
        <span class="suite-label">{{ s.label }}</span>
        <div class="suite-btns">
          <button
            class="act-btn start"
            :disabled="isBusy('start', s.id)"
            @click="doAction('start', s.id)"
          >启动</button>
          <button
            class="act-btn stop"
            :disabled="isBusy('stop', s.id)"
            @click="doAction('stop', s.id)"
          >停止</button>
          <button
            class="act-btn restart"
            :disabled="isBusy('restart', s.id)"
            @click="doAction('restart', s.id)"
          >重启</button>
        </div>
      </div>
    </div>

    <div v-if="error" class="svc-error">⚠ {{ error }}</div>

    <!-- 服务状态卡片 -->
    <div class="svc-cards">
      <div
        v-for="svc in services"
        :key="svc.id"
        class="svc-card"
        :class="{ running: svc.running, expanded: expandedSvc === svc.id }"
      >
        <!-- 卡片主行（点击展开日志） -->
        <div class="card-main" @click="toggleLog(svc.id)">
          <span class="dot" :class="{ live: svc.running }"></span>
          <span class="svc-label">{{ svc.name }}</span>
          <span v-if="svc.pid" class="svc-pid">PID {{ svc.pid }}</span>
          <span v-if="svc.port !== null" class="svc-port">:{{ svc.port }}</span>
          <span v-else class="svc-port no-port">无端口</span>
          <span class="svc-status" :class="svc.running ? 'up' : 'down'">
            {{ svc.running ? '运行中' : '已停止' }}
          </span>
        </div>

        <!-- 注释 / 描述 -->
        <div v-if="annotations[svc.id]?.description" class="svc-desc">
          {{ annotations[svc.id].description }}
        </div>

        <!-- Profile 切换（仅支持 profile 的服务） -->
        <div v-if="annotations[svc.id]?.profile" class="profile-section">
          <div class="profile-header">
            <svg class="profile-icon" viewBox="0 0 16 16" width="14" height="14">
              <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.2"/>
              <path d="M2 8h12M8 2v12" stroke="currentColor" stroke-width="1.2"/>
            </svg>
            <span class="profile-label">{{ annotations[svc.id].profile.group_label }}</span>
            <span class="profile-desc">{{ annotations[svc.id].profile.group_description }}</span>
          </div>
          <div class="profile-options">
            <button
              v-for="p in annotations[svc.id].profile.available"
              :key="p"
              class="profile-btn"
              :class="{ active: annotations[svc.id].profile.active === p }"
              :disabled="profileBusy"
              @click="switchProfile(svc.id, p)"
              :title="annotations[svc.id].profile.available_descriptions[p]"
            >
              <span class="profile-btn-label">{{ annotations[svc.id].profile.available_labels[p] }}</span>
              <span class="profile-btn-desc">{{ annotations[svc.id].profile.available_descriptions[p].split('\n')[0] }}</span>
            </button>
          </div>
        </div>

        <!-- 环境变量展开区域 -->
        <div class="env-toggle" @click="toggleEnv(svc.id)">
          <span class="env-toggle-icon">{{ envExpanded.has(svc.id) ? '▼' : '▶' }}</span>
          <span class="env-toggle-label">环境变量</span>
          <span v-if="!envExpanded.has(svc.id) && annotations[svc.id]?.env_vars" class="env-preview">
            {{ annotations[svc.id].env_vars.slice(0, 2).map(v => v.key).join(', ') }}{{ annotations[svc.id].env_vars.length > 2 ? '...' : '' }}
          </span>
        </div>
        <div v-if="envExpanded.has(svc.id)" class="env-section">
          <div v-if="envVarsCache[svc.id] && envVarsCache[svc.id].length > 0" class="env-table">
            <div
              v-for="v in envVarsCache[svc.id]"
              :key="v.key"
              class="env-row"
              :class="{ 'env-profile': v.source === 'profile' }"
            >
              <div class="env-key">
                <code>{{ v.key }}</code>
                <span v-if="v.source === 'profile'" class="env-badge">profile</span>
              </div>
              <div class="env-val">
                <code>{{ v.current || v.default }}</code>
              </div>
              <div class="env-desc">{{ v.description }}</div>
            </div>
          </div>
          <div v-else class="env-loading">加载中…</div>
        </div>
      </div>
    </div>

    <!-- 日志面板 -->
    <div v-if="expandedSvc" class="log-panel">
      <div class="log-header">
        <span>{{ services.find(s => s.id === expandedSvc)?.name }} — 日志</span>
        <button class="log-close" @click="toggleLog(expandedSvc!)">✕</button>
      </div>
      <pre v-if="!logBusy" class="log-body">{{ logContent }}</pre>
      <div v-else class="log-body loading">加载中…</div>
    </div>

    <!-- ═══ .env 配置文件管理（动态扫描 "注释/取消注释" 开关组）═══ -->
    <h2 class="svc-title" style="margin-top: 12px">⚙️ .env 配置管理</h2>
    <p style="font-size: 0.75rem; color: var(--text2); margin: -8px 0 4px">
      自动扫描 .env 文件中的"注释/取消注释"开关组，点击切换选项后自动修改对应 .env 文件
    </p>

    <div v-for="file in envFiles" :key="file.id" class="env-file-card">
      <div class="env-file-header">
        <span class="env-file-label">{{ file.label }}</span>
        <span class="env-file-path">{{ file.path }}</span>
        <span v-if="!file.exists" class="env-file-missing">文件不存在</span>
      </div>

      <div v-if="!file.exists" class="env-file-empty">.env 文件未找到</div>

      <template v-else-if="envScans[file.id]">
        <!-- 开关组列表 -->
        <div
          v-for="group in envScans[file.id].switch_groups"
          :key="group.key"
          class="env-group"
        >
          <div class="env-group-header">
            <code class="env-group-key">{{ group.key }}</code>
            <span v-if="group.description.length" class="env-group-desc">
              {{ group.description.slice(0, 2).join(' | ') }}
            </span>
          </div>
          <div class="env-group-options">
            <button
              v-for="opt in group.options"
              :key="opt.value"
              class="env-opt-btn"
              :class="{ active: opt.active }"
              :disabled="opt.active || envSwitchBusy.has(`${file.id}:${group.key}:${opt.value}`)"
              :title="opt.comment || opt.value"
              @click="switchEnvOption(file.id, group.key, opt.value)"
            >
              <span class="env-opt-value">{{ opt.value || '(空)' }}</span>
              <span v-if="opt.comment" class="env-opt-comment">{{ opt.comment }}</span>
            </button>
          </div>
        </div>

        <div v-if="envScans[file.id].single_var_count > 0" class="env-file-meta">
          另有 {{ envScans[file.id].single_var_count }} 个单值变量（不可切换）
        </div>
      </template>

      <div v-else class="env-file-loading">扫描中…</div>
    </div>

    <div v-if="envError" class="svc-error">⚠ {{ envError }}</div>
  </div>
</template>

<style scoped>
.svc-panel {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.svc-title {
  font-size: 1rem;
  font-weight: 600;
  letter-spacing: 0.03em;
  text-transform: uppercase;
  color: var(--text2);
}

/* 套件操作行 */
.suite-actions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.suite-row {
  display: flex;
  align-items: center;
  gap: 12px;
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 14px;
}

.suite-label {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text);
  min-width: 100px;
}

.suite-btns {
  display: flex;
  gap: 6px;
}

.act-btn {
  padding: 4px 14px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.15s;
}

.act-btn:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

.act-btn.start:hover:not(:disabled) {
  background: #2d7a3a;
  border-color: #3da04f;
  color: #fff;
}

.act-btn.stop:hover:not(:disabled) {
  background: #8b2d2d;
  border-color: #c04040;
  color: #fff;
}

.act-btn.restart:hover:not(:disabled) {
  background: #8d6d1a;
  border-color: #c09820;
  color: #fff;
}

/* 错误信息 */
.svc-error {
  font-size: 0.8rem;
  color: #ffb8b3;
  background: rgba(229, 85, 79, 0.12);
  border: 1px solid rgba(229, 85, 79, 0.25);
  border-radius: 6px;
  padding: 8px 12px;
}

/* 服务卡片 */
.svc-cards {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.svc-card {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 14px;
  cursor: default;
  transition: all 0.15s;
}

.svc-card:hover {
  border-color: var(--accent);
}

.svc-card.expanded {
  border-color: var(--accent);
  box-shadow: 0 0 0 1px var(--accent);
}

.card-main {
  display: flex;
  align-items: center;
  gap: 10px;
  cursor: pointer;
}

.dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  background: #555;
  flex-shrink: 0;
  transition: background 0.3s;
}

.dot.live {
  background: #3dd68c;
  box-shadow: 0 0 6px rgba(61, 214, 140, 0.5);
}

.svc-label {
  font-size: 0.9rem;
  font-weight: 500;
  color: var(--text);
}

.svc-pid {
  font-size: 0.75rem;
  color: var(--text2);
  font-family: monospace;
}

.svc-port {
  font-size: 0.75rem;
  color: var(--accent);
  font-family: monospace;
}

.svc-port.no-port {
  color: var(--text2);
}

.svc-status {
  margin-left: auto;
  font-size: 0.75rem;
  font-weight: 500;
  padding: 2px 8px;
  border-radius: 10px;
}

.svc-status.up {
  color: #3dd68c;
  background: rgba(61, 214, 140, 0.1);
}

.svc-status.down {
  color: var(--text2);
  background: rgba(255, 255, 255, 0.04);
}

/* 服务描述 */
.svc-desc {
  margin-top: 8px;
  padding: 8px 10px;
  font-size: 0.78rem;
  line-height: 1.5;
  color: var(--text2);
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  border: 1px solid var(--border);
}

/* Profile 切换区域 */
.profile-section {
  margin-top: 10px;
  padding: 10px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  border: 1px solid var(--border);
}

.profile-header {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 8px;
  font-size: 0.78rem;
}

.profile-icon {
  color: var(--accent);
  flex-shrink: 0;
}

.profile-label {
  font-weight: 600;
  color: var(--text);
}

.profile-desc {
  color: var(--text2);
  margin-left: 4px;
}

.profile-options {
  display: flex;
  gap: 8px;
}

.profile-btn {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 8px 10px;
  border-radius: 6px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text);
  cursor: pointer;
  transition: all 0.15s;
  text-align: center;
}

.profile-btn:hover:not(:disabled) {
  border-color: var(--accent);
  background: rgba(100, 180, 255, 0.06);
}

.profile-btn.active {
  border-color: var(--accent);
  background: rgba(100, 180, 255, 0.12);
  box-shadow: 0 0 0 1px var(--accent);
}

.profile-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.profile-btn-label {
  font-size: 0.82rem;
  font-weight: 600;
  color: var(--text);
}

.profile-btn-desc {
  font-size: 0.7rem;
  color: var(--text2);
  line-height: 1.3;
}

/* 环境变量展开 */
.env-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 10px;
  padding: 6px 0;
  cursor: pointer;
  user-select: none;
  font-size: 0.78rem;
  color: var(--text2);
  border-top: 1px solid transparent;
  transition: color 0.15s;
}

.env-toggle:hover {
  color: var(--text);
}

.env-toggle-icon {
  font-size: 0.7rem;
  width: 12px;
  flex-shrink: 0;
}

.env-toggle-label {
  font-weight: 500;
}

.env-preview {
  margin-left: 8px;
  font-size: 0.72rem;
  color: var(--text2);
  font-family: monospace;
  opacity: 0.7;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.env-section {
  border-top: 1px solid var(--border);
  padding-top: 8px;
  margin-top: 0;
}

.env-table {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.env-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 0.75rem;
  background: rgba(0, 0, 0, 0.15);
  transition: background 0.15s;
}

.env-row.env-profile {
  background: rgba(100, 180, 255, 0.06);
  border: 1px solid rgba(100, 180, 255, 0.12);
}

.env-key {
  display: flex;
  align-items: center;
  gap: 6px;
}

.env-key code {
  font-family: 'Fira Code', 'Cascadia Code', monospace;
  font-size: 0.72rem;
  color: #8ab4f8;
}

.env-badge {
  font-size: 0.6rem;
  padding: 1px 5px;
  border-radius: 3px;
  background: rgba(100, 180, 255, 0.15);
  color: var(--accent);
  font-weight: 500;
}

.env-val code {
  font-family: 'Fira Code', 'Cascadia Code', monospace;
  font-size: 0.72rem;
  color: #c8ccd4;
}

.env-desc {
  grid-column: 1 / -1;
  font-size: 0.7rem;
  color: var(--text2);
  line-height: 1.4;
}

.env-loading {
  text-align: center;
  padding: 12px;
  font-size: 0.78rem;
  color: var(--text2);
}

/* 日志面板 */
.log-panel {
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}

.log-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 14px;
  background: var(--surface2);
  border-bottom: 1px solid var(--border);
  font-size: 0.82rem;
  color: var(--text2);
}

.log-close {
  background: none;
  border: none;
  color: var(--text2);
  cursor: pointer;
  font-size: 1rem;
  padding: 2px 6px;
  border-radius: 4px;
}

.log-close:hover {
  background: rgba(255, 255, 255, 0.08);
  color: var(--text);
}

.log-body {
  margin: 0;
  padding: 12px 14px;
  font-family: 'Fira Code', 'Cascadia Code', 'JetBrains Mono', 'Consolas', monospace;
  font-size: 0.75rem;
  line-height: 1.5;
  color: #c8ccd4;
  background: #0a0c12;
  max-height: 400px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-all;
}

.log-body.loading {
  color: var(--text2);
  text-align: center;
  padding: 20px;
}

/* .env 配置卡片 */
.env-file-card {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px 14px;
  margin-bottom: 8px;
}

.env-file-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 8px;
}

.env-file-label {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text);
}

.env-file-path {
  font-size: 0.7rem;
  color: var(--text2);
  font-family: monospace;
}

.env-file-missing {
  font-size: 0.75rem;
  color: #c04040;
}

.env-file-empty, .env-file-loading {
  font-size: 0.8rem;
  color: var(--text2);
  padding: 12px 0;
}

.env-file-meta {
  font-size: 0.75rem;
  color: var(--text2);
  margin-top: 6px;
}

.env-group {
  margin: 8px 0;
  padding: 8px 10px;
  background: rgba(255,255,255,0.03);
  border-radius: 6px;
}

.env-group-header {
  display: flex;
  align-items: baseline;
  gap: 8px;
  margin-bottom: 6px;
}

.env-group-key {
  font-size: 0.8rem;
  font-weight: 600;
  color: #7ec8e3;
}

.env-group-desc {
  font-size: 0.7rem;
  color: var(--text2);
}

.env-group-options {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
}

.env-opt-btn {
  display: flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border-radius: 4px;
  border: 1px solid var(--border);
  background: var(--surface);
  color: var(--text2);
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s;
  max-width: 100%;
}

.env-opt-btn:hover:not(:disabled) {
  border-color: #5a9;
  color: var(--text);
  background: rgba(85, 170, 153, 0.08);
}

.env-opt-btn.active {
  border-color: #3dd68c;
  color: #3dd68c;
  background: rgba(61, 214, 140, 0.1);
}

.env-opt-btn:disabled {
  opacity: 0.7;
  cursor: default;
}

.env-opt-value {
  font-family: monospace;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.env-opt-comment {
  font-size: 0.65rem;
  color: var(--text2);
  opacity: 0.7;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
</style>
