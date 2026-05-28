<script setup lang="ts">
/**
 * CommandManager.vue — 指令 YAML 配置管理器
 *
 * 功能：
 * 1. 加载现有 commands.yaml 中的全部指令
 * 2. 分类展示：KWS 关键词 / 指令意图 / MQTT hex 指令 / 文本过滤规则
 * 3. 选择一个指令后在结构化表单中编辑
 * 4. 保存修改回 commands.yaml
 */
import { ref, reactive, computed, onMounted, nextTick } from 'vue'

// ── 类型定义 ────────────────────────────────────────────────

interface KwsKeyword {
  id: string
  keyword: string
  command: string
  mode: string[]
  description: string
  enabled: boolean
}

interface CommandIntent {
  id: string
  intent: string
  command: string
  session_mode: string[]
  description: string
  priority: number
  enabled: boolean
}

interface MqttCommand {
  id: string
  name: string
  hex: string
  description: string
  type: string
  enabled: boolean
}

interface CommandFilter {
  id: string
  pattern: string
  replacement: string
  description: string
  enabled: boolean
}

interface CommandsData {
  kws_keywords: KwsKeyword[]
  command_intents: CommandIntent[]
  mqtt_commands: MqttCommand[]
  command_filters: CommandFilter[]
}

// ── Tab 类别 ────────────────────────────────────────────────

type TabKey = 'kws' | 'intents' | 'mqtt' | 'filters'
interface TabItem {
  key: TabKey
  label: string
  icon: string
  count: number
}

// ── 状态 ────────────────────────────────────────────────────

const baseURL = ''
const loading = ref(false)
const saving = ref(false)
const error = ref('')
const successMsg = ref('')
const activeTab = ref<TabKey>('kws')

const chatbotConfigLoading = ref(false)
const chatbotConfigSaving = ref(false)
const chatbotConfigError = ref('')
const chatbotConfigSuccess = ref('')
const chatbotConfigPath = ref('')
const chatbotConfigText = ref('')

/** 完整的指令数据集 */
const data = reactive<CommandsData>({
  kws_keywords: [],
  command_intents: [],
  mqtt_commands: [],
  command_filters: [],
})

/** 当前选中的项（在不同 tab 间共享选中 ID） */
const selectedId = ref<string>('')

/** 编辑器：正在编辑的项 */
const editingItem = reactive<Record<string, any>>({})
const editorDirty = ref(false)
const editorMode = ref<'view' | 'edit' | 'new'>('view')

const MUTABLE_MODES = ['music', 'story', 'dialogue']

// ── 计算属性 ────────────────────────────────────────────────

const tabs = computed<TabItem[]>(() => [
  { key: 'kws', label: 'KWS 关键词', icon: '🔊', count: data.kws_keywords.length },
  { key: 'intents', label: '指令意图', icon: '🎯', count: data.command_intents.length },
  { key: 'mqtt', label: 'MQTT 指令', icon: '📤', count: data.mqtt_commands.length },
  { key: 'filters', label: '过滤规则', icon: '🧹', count: data.command_filters.length },
])

/** 当前 tab 的列表 */
const currentList = computed<any[]>(() => {
  switch (activeTab.value) {
    case 'kws': return data.kws_keywords
    case 'intents': return data.command_intents
    case 'mqtt': return data.mqtt_commands
    case 'filters': return data.command_filters
  }
})

/** 当前选中的完整项 */
const selectedItem = computed<any>(() => {
  return currentList.value.find((i: any) => i.id === selectedId.value) || null
})

function getTabFieldLabel(key: TabKey): { title: string; idLabel: string; descLabel: string } {
  switch (key) {
    case 'kws': return { title: 'KWS 关键词→指令', idLabel: '关键词', descLabel: '触发后指令' }
    case 'intents': return { title: '意图→指令映射', idLabel: '意图 ID', descLabel: '执行指令' }
    case 'mqtt': return { title: 'MQTT 十六进制指令', idLabel: '指令名称', descLabel: '用途说明' }
    case 'filters': return { title: '文本过滤规则', idLabel: '规则 ID', descLabel: '匹配模式' }
  }
}

const fieldLabels = computed(() => getTabFieldLabel(activeTab.value))

// ── 字段生成（根据当前 tab 动态渲染表单）─────────────────────

interface FieldDef {
  key: string
  label: string
  type: 'text' | 'textarea' | 'switch' | 'select' | 'tags' | 'number'
  options?: { label: string; value: any }[]
  placeholder?: string
}

const fieldsForTab = computed<FieldDef[]>(() => {
  switch (activeTab.value) {
    case 'kws': return [
      { key: 'id', label: 'ID', type: 'text', placeholder: '唯一标识，如 next_track' },
      { key: 'keyword', label: '唤醒关键词', type: 'text', placeholder: '如 下一首' },
      { key: 'command', label: '触发指令', type: 'text', placeholder: '如 NEXT_TRACK' },
      { key: 'mode', label: '适用模式', type: 'tags', options: MUTABLE_MODES.map(m => ({ label: m, value: m })) },
      { key: 'description', label: '描述', type: 'textarea', placeholder: '说明该关键词的作用' },
      { key: 'enabled', label: '启用', type: 'switch' },
    ]
    case 'intents': return [
      { key: 'id', label: 'ID', type: 'text', placeholder: '如 play_music_intent' },
      { key: 'intent', label: '意图名称', type: 'text', placeholder: '如 play_music' },
      { key: 'command', label: '执行指令', type: 'text', placeholder: '如 PLAY_MUSIC' },
      { key: 'session_mode', label: '适用会话模式', type: 'tags', options: MUTABLE_MODES.map(m => ({ label: m, value: m })) },
      { key: 'priority', label: '优先级(数字越大越高)', type: 'number' },
      { key: 'description', label: '描述', type: 'textarea', placeholder: '说明该意图的用途' },
      { key: 'enabled', label: '启用', type: 'switch' },
    ]
    case 'mqtt': return [
      { key: 'id', label: 'ID', type: 'text', placeholder: '如 ch1_on' },
      { key: 'name', label: '指令名称', type: 'text', placeholder: '如 一路打开' },
      { key: 'hex', label: '十六进制编码', type: 'text', placeholder: '如 55 AA AA AA AA 81 01 01' },
      { key: 'type', label: '指令类型', type: 'select', options: [
        { label: '控制指令', value: 'control' },
        { label: '查询指令', value: 'query' },
      ]},
      { key: 'description', label: '功能说明', type: 'textarea', placeholder: '说明该指令的作用' },
      { key: 'enabled', label: '启用', type: 'switch' },
    ]
    case 'filters': return [
      { key: 'id', label: 'ID', type: 'text', placeholder: '如 strip_modal_particles' },
      { key: 'pattern', label: '正则匹配模式', type: 'text', placeholder: '如 ^(请|帮我)' },
      { key: 'replacement', label: '替换文本', type: 'text', placeholder: '替换为空字符串' },
      { key: 'description', label: '规则说明', type: 'textarea', placeholder: '说明该过滤规则的作用' },
      { key: 'enabled', label: '启用', type: 'switch' },
    ]
  }
})

// ── 方法 ────────────────────────────────────────────────────

/** 加载指令数据 */
async function loadCommands() {
  loading.value = true
  error.value = ''
  try {
    const res = await fetch(`${baseURL}/api/commands`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const json = await res.json()
    data.kws_keywords = json.kws_keywords || []
    data.command_intents = json.command_intents || []
    data.mqtt_commands = json.mqtt_commands || []
    data.command_filters = json.command_filters || []

    // 如果当前选中项在加载后消失则清空
    if (selectedId.value) {
      const exists = currentList.value.find((i: any) => i.id === selectedId.value)
      if (!exists) {
        selectedId.value = ''
        editorMode.value = 'view'
      }
    }
  } catch (e: any) {
    error.value = `加载指令配置失败: ${e.message}`
  } finally {
    loading.value = false
  }
}

/** 加载 chatbot 的命令 YAML 配置 */
async function loadChatbotConfig() {
  chatbotConfigLoading.value = true
  chatbotConfigError.value = ''
  try {
    const res = await fetch(`${baseURL}/api/command-config/chatbot`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const json = await res.json()
    chatbotConfigPath.value = json.path || ''
    chatbotConfigText.value = json.content || ''
  } catch (e: any) {
    chatbotConfigError.value = `加载 chatbot 配置失败: ${e.message}`
  } finally {
    chatbotConfigLoading.value = false
  }
}

/** 替换 chatbot 的命令 YAML 配置 */
async function saveChatbotConfig() {
  chatbotConfigSaving.value = true
  chatbotConfigError.value = ''
  chatbotConfigSuccess.value = ''
  try {
    const res = await fetch(`${baseURL}/api/command-config/chatbot`, {
      method: 'PUT',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content: chatbotConfigText.value }),
    })
    if (!res.ok) {
      const body = await res.text()
      throw new Error(`HTTP ${res.status}: ${body}`)
    }
    const result = await res.json()
    chatbotConfigPath.value = result.path || chatbotConfigPath.value
    chatbotConfigSuccess.value = `已替换 chatbot 配置: ${result.path}`
    setTimeout(() => chatbotConfigSuccess.value = '', 3000)
  } catch (e: any) {
    chatbotConfigError.value = `替换 chatbot 配置失败: ${e.message}`
  } finally {
    chatbotConfigSaving.value = false
  }
}

/** 导出 chatbot 的命令 YAML 配置 */
async function exportChatbotConfig() {
  chatbotConfigError.value = ''
  try {
    const res = await fetch(`${baseURL}/api/command-config/chatbot/export`)
    if (!res.ok) throw new Error(`HTTP ${res.status}`)
    const blob = await res.blob()
    const url = window.URL.createObjectURL(blob)
    const link = document.createElement('a')
    link.href = url
    link.download = chatbotConfigPath.value ? chatbotConfigPath.value.split(/[\\/]/).pop() || 'voice_commands.yaml' : 'voice_commands.yaml'
    document.body.appendChild(link)
    link.click()
    link.remove()
    window.URL.revokeObjectURL(url)
  } catch (e: any) {
    chatbotConfigError.value = `导出 chatbot 配置失败: ${e.message}`
  }
}

/** 选择一项 */
function selectItem(id: string) {
  selectedId.value = id
  editorMode.value = 'view'
  editorDirty.value = false
  copyToEditor()
}

/** 将当前选中项拷贝到编辑器 */
function copyToEditor() {
  Object.keys(editingItem).forEach(k => delete editingItem[k])
  if (selectedItem.value) {
    Object.assign(editingItem, JSON.parse(JSON.stringify(selectedItem.value)))
  }
}

/** 开始编辑 */
function startEdit() {
  if (!selectedItem.value) return
  editorMode.value = 'edit'
  editorDirty.value = false
  copyToEditor()
}

/** 开始新增 */
function startNew() {
  // 根据当前 tab 创建空模板
  const template = createEmptyItem(activeTab.value)
  const newId = `new_${Date.now()}`
  template.id = newId

  // 先清空选中
  selectedId.value = ''
  Object.keys(editingItem).forEach(k => delete editingItem[k])
  Object.assign(editingItem, template)
  editorMode.value = 'new'
  editorDirty.value = false
}

function createEmptyItem(tab: TabKey): Record<string, any> {
  switch (tab) {
    case 'kws': return { id: '', keyword: '', command: '', mode: ['dialogue'], description: '', enabled: true }
    case 'intents': return { id: '', intent: '', command: '', session_mode: ['dialogue'], priority: 5, description: '', enabled: true }
    case 'mqtt': return { id: '', name: '', hex: '', type: 'control', description: '', enabled: true }
    case 'filters': return { id: '', pattern: '', replacement: '', description: '', enabled: true }
  }
}

/** 取消编辑 */
function cancelEdit() {
  editorMode.value = 'view'
  editorDirty.value = false
  if (selectedItem.value) {
    copyToEditor()
  } else {
    Object.keys(editingItem).forEach(k => delete editingItem[k])
  }
}

/** 应用编辑（写入 data 但尚未保存到后端） */
function applyEdit() {
  const list = currentList.value
  if (editorMode.value === 'new') {
    // 检查 id 重复
    if (list.find((i: any) => i.id === editingItem.id)) {
      error.value = `ID "${editingItem.id}" 已存在`
      return
    }
    list.push(JSON.parse(JSON.stringify(editingItem)))
    selectedId.value = editingItem.id
    editorMode.value = 'view'
    editorDirty.value = false
    successMsg.value = `已添加 "${editingItem.id}"`
    setTimeout(() => successMsg.value = '', 2000)
  } else if (editorMode.value === 'edit' && selectedItem.value) {
    const idx = list.findIndex((i: any) => i.id === selectedId.value)
    if (idx !== -1) {
      list[idx] = JSON.parse(JSON.stringify(editingItem))
      selectedId.value = editingItem.id
      editorMode.value = 'view'
      editorDirty.value = false
      successMsg.value = `已更新 "${editingItem.id}"`
      setTimeout(() => successMsg.value = '', 2000)
    }
  }
}

/** 删除选中的项 */
function deleteSelected() {
  if (!selectedItem.value || !confirm(`确定删除 "${selectedItem.value.id}" ？`)) return
  const list = currentList.value
  const idx = list.findIndex((i: any) => i.id === selectedId.value)
  if (idx !== -1) {
    list.splice(idx, 1)
    selectedId.value = ''
    editorMode.value = 'view'
    Object.keys(editingItem).forEach(k => delete editingItem[k])
    successMsg.value = '已删除'
    setTimeout(() => successMsg.value = '', 2000)
  }
}

/** 保存到后端 */
async function saveToBackend() {
  saving.value = true
  error.value = ''
  try {
    const res = await fetch(`${baseURL}/api/commands/save`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        kws_keywords: data.kws_keywords,
        command_intents: data.command_intents,
        mqtt_commands: data.mqtt_commands,
        command_filters: data.command_filters,
      }),
    })
    if (!res.ok) {
      const body = await res.text()
      throw new Error(`HTTP ${res.status}: ${body}`)
    }
    const result = await res.json()
    successMsg.value = `✅ 已保存到 ${result.path}`
    setTimeout(() => successMsg.value = '', 3000)
  } catch (e: any) {
    error.value = `保存失败: ${e.message}`
  } finally {
    saving.value = false
  }
}

/** 导出 YAML 预览 */
const previewYaml = computed(() => {
  const out: Record<string, any> = {}
  out.kws_keywords = data.kws_keywords
  out.command_intents = data.command_intents
  out.mqtt_commands = data.mqtt_commands
  out.command_filters = data.command_filters
  return out
})

const showPreview = ref(false)

function togglePreview() {
  showPreview.value = !showPreview.value
}

// ── 标签切换 ────────────────────────────────────────────────

function switchTab(key: TabKey) {
  activeTab.value = key
  selectedId.value = ''
  editorMode.value = 'view'
  editorDirty.value = false
  Object.keys(editingItem).forEach(k => delete editingItem[k])
}

// ── Tags toggle helper ────────────────────────────────────────

function toggleTag(key: string, value: string, checked: boolean) {
  const arr: string[] = editingItem[key] || []
  if (checked) {
    if (!arr.includes(value)) arr.push(value)
  } else {
    const idx = arr.indexOf(value)
    if (idx !== -1) arr.splice(idx, 1)
  }
  editingItem[key] = [...arr]
  markDirty()
}

// ── 初始化 ──────────────────────────────────────────────────

onMounted(() => {
  loadCommands()
  loadChatbotConfig()
})

// ── 辅助: 从 editor 标记 dirty ────────────────────────────
function markDirty() {
  editorDirty.value = true
}
</script>

<template>
  <div class="cmd-manager">
    <!-- Header -->
    <div class="cm-header">
      <div class="cm-header-left">
        <h2>📋 指令配置管理</h2>
        <span class="cm-subtitle">编辑 commands.yaml — 标准 YAML 格式</span>
      </div>
      <div class="cm-header-actions">
        <button class="cm-btn cm-btn-outline" @click="togglePreview">
          {{ showPreview ? '隐藏预览' : 'YAML 预览' }}
        </button>
        <button
          class="cm-btn cm-btn-primary"
          :disabled="saving"
          @click="saveToBackend"
        >
          {{ saving ? '保存中...' : '💾 保存到文件' }}
        </button>
        <button class="cm-btn cm-btn-secondary" :disabled="loading" @click="loadCommands">
          🔄 刷新
        </button>
      </div>
    </div>

    <!-- 状态消息 -->
    <div v-if="error" class="cm-alert cm-alert-error">{{ error }}</div>
    <div v-if="successMsg" class="cm-alert cm-alert-success">{{ successMsg }}</div>
    <div v-if="chatbotConfigError" class="cm-alert cm-alert-error">{{ chatbotConfigError }}</div>
    <div v-if="chatbotConfigSuccess" class="cm-alert cm-alert-success">{{ chatbotConfigSuccess }}</div>

    <div v-if="loading" class="cm-loading">加载中...</div>

    <div v-if="chatbotConfigLoading" class="cm-loading">正在读取 chatbot 命令配置...</div>

    <div class="cm-bridge-panel">
      <div class="cm-bridge-header">
        <div>
          <h3>🤝 Chatbot 命令配置桥</h3>
          <div class="cm-bridge-subtitle">
            直接读写 chatbot 的 voice_commands.yaml
            <span v-if="chatbotConfigPath" class="cm-bridge-path">· {{ chatbotConfigPath }}</span>
          </div>
        </div>
        <div class="cm-bridge-actions">
          <button class="cm-btn cm-btn-small cm-btn-secondary" :disabled="chatbotConfigLoading" @click="loadChatbotConfig">
            📥 读取
          </button>
          <button class="cm-btn cm-btn-small cm-btn-primary" :disabled="chatbotConfigSaving" @click="saveChatbotConfig">
            {{ chatbotConfigSaving ? '替换中...' : '🔁 替换配置' }}
          </button>
          <button class="cm-btn cm-btn-small cm-btn-outline" @click="exportChatbotConfig">
            📤 导出
          </button>
        </div>
      </div>
      <textarea
        v-model="chatbotConfigText"
        class="cm-bridge-textarea"
        placeholder="读取 chatbot 的 voice_commands.yaml 后会显示在这里。你可以直接替换整份 YAML，然后保存回 chatbot。"
        spellcheck="false"
      />
    </div>

    <template v-if="!loading">
      <!-- Tab 导航 -->
      <div class="cm-tabs">
        <button
          v-for="tab in tabs"
          :key="tab.key"
          class="cm-tab"
          :class="{ active: activeTab === tab.key }"
          @click="switchTab(tab.key)"
        >
          <span class="cm-tab-icon">{{ tab.icon }}</span>
          <span class="cm-tab-label">{{ tab.label }}</span>
          <span class="cm-tab-badge">{{ tab.count }}</span>
        </button>
      </div>

      <!-- 主体：列表 + 编辑器 -->
      <div class="cm-body">
        <!-- 左侧：列表 -->
        <div class="cm-list-panel">
          <div class="cm-list-header">
            <span class="cm-list-title">{{ fieldLabels.title }}</span>
            <button class="cm-btn cm-btn-small cm-btn-primary" @click="startNew">➕ 新增</button>
          </div>
          <div class="cm-list">
            <div
              v-for="item in currentList"
              :key="item.id"
              class="cm-list-item"
              :class="{ selected: selectedId === item.id, disabled: !item.enabled }"
              @click="selectItem(item.id)"
            >
              <div class="cm-item-primary">
                <span class="cm-item-status" :class="{ on: item.enabled }">
                  {{ item.enabled ? '●' : '○' }}
                </span>
                <span class="cm-item-main">
                  <span class="cm-item-id">{{ item.id }}</span>
                  <span class="cm-item-desc">{{ item.description }}</span>
                </span>
              </div>
              <div v-if="item.keyword" class="cm-item-secondary">
                关键词: <code>{{ item.keyword }}</code>
                → <code>{{ item.command }}</code>
              </div>
              <div v-else-if="item.intent" class="cm-item-secondary">
                意图: <code>{{ item.intent }}</code>
                → <code>{{ item.command }}</code>
              </div>
              <div v-else-if="item.hex" class="cm-item-secondary">
                <code class="cm-hex">{{ item.hex }}</code>
              </div>
              <div v-else-if="item.pattern" class="cm-item-secondary">
                <code>{{ item.pattern }}</code> → "{{ item.replacement }}"
              </div>
              <div v-else class="cm-item-secondary">
                <code>{{ item.command || item.name || '-' }}</code>
              </div>
            </div>
            <div v-if="currentList.length === 0" class="cm-list-empty">
              暂无数据，点击「➕ 新增」添加
            </div>
          </div>
        </div>

        <!-- 右侧：编辑器 -->
        <div class="cm-editor-panel">
          <div class="cm-editor-header">
            <span v-if="editorMode === 'view' && selectedItem" class="cm-editor-title">
              📖 {{ selectedItem.id }}
            </span>
            <span v-else-if="editorMode === 'new'" class="cm-editor-title">📝 新建条目</span>
            <span v-else-if="editorMode === 'edit'" class="cm-editor-title">✏️ 编辑: {{ editingItem.id }}</span>
            <span v-else class="cm-editor-title cm-editor-placeholder">← 从左侧列表选择一项进行编辑</span>
            <div class="cm-editor-actions">
              <template v-if="editorMode === 'view' && selectedItem">
                <button class="cm-btn cm-btn-small cm-btn-primary" @click="startEdit">✏️ 编辑</button>
                <button class="cm-btn cm-btn-small cm-btn-danger" @click="deleteSelected">🗑️ 删除</button>
              </template>
              <template v-if="editorMode === 'edit' || editorMode === 'new'">
                <button class="cm-btn cm-btn-small cm-btn-primary" @click="applyEdit">✅ 应用</button>
                <button class="cm-btn cm-btn-small cm-btn-outline" @click="cancelEdit">取消</button>
              </template>
            </div>
          </div>

          <!-- 编辑器表单 -->
          <div v-if="editorMode !== 'view' || selectedItem" class="cm-editor-form">
            <div v-if="editorMode === 'view' && selectedItem" class="cm-view-fields">
              <div v-for="field in fieldsForTab" :key="field.key" class="cm-field">
                <label class="cm-field-label">{{ field.label }}</label>
                <div class="cm-field-value">
                  <template v-if="field.type === 'switch'">
                    <span class="cm-bool" :class="{ on: selectedItem[field.key] }">
                      {{ selectedItem[field.key] ? '是' : '否' }}
                    </span>
                  </template>
                  <template v-else-if="field.type === 'tags'">
                    <span v-for="tag in (selectedItem[field.key] || [])" :key="tag" class="cm-tag">{{ tag }}</span>
                    <span v-if="!selectedItem[field.key]?.length" class="cm-empty-val">—</span>
                  </template>
                  <template v-else>
                    <code v-if="['command', 'hex', 'pattern', 'replacement'].includes(field.key)">{{ selectedItem[field.key] || '—' }}</code>
                    <span v-else>{{ selectedItem[field.key] ?? '—' }}</span>
                  </template>
                </div>
              </div>
            </div>

            <div v-if="editorMode === 'edit' || editorMode === 'new'" class="cm-edit-fields">
              <div v-for="field in fieldsForTab" :key="field.key" class="cm-field">
                <label class="cm-field-label" :for="`ef_${field.key}`">{{ field.label }}</label>
                <div class="cm-field-value">
                  <!-- Text input -->
                  <input
                    v-if="field.type === 'text'"
                    :id="`ef_${field.key}`"
                    v-model="editingItem[field.key]"
                    class="cm-input"
                    :placeholder="field.placeholder"
                    @input="markDirty"
                  />
                  <!-- Textarea -->
                  <textarea
                    v-if="field.type === 'textarea'"
                    :id="`ef_${field.key}`"
                    v-model="editingItem[field.key]"
                    class="cm-input cm-textarea"
                    :placeholder="field.placeholder"
                    @input="markDirty"
                  />
                  <!-- Switch -->
                  <div v-if="field.type === 'switch'" class="cm-toggle-wrap">
                    <label class="cm-toggle">
                      <input
                        type="checkbox"
                        :checked="editingItem[field.key]"
                        @change="editingItem[field.key] = ($event.target as HTMLInputElement).checked; markDirty()"
                      />
                      <span class="cm-toggle-slider"></span>
                    </label>
                    <span class="cm-toggle-label">{{ editingItem[field.key] ? '启用' : '禁用' }}</span>
                  </div>
                  <!-- Select -->
                  <select
                    v-if="field.type === 'select'"
                    v-model="editingItem[field.key]"
                    class="cm-input cm-select"
                    @change="markDirty"
                  >
                    <option v-for="opt in field.options" :key="opt.value" :value="opt.value">
                      {{ opt.label }}
                    </option>
                  </select>
                  <!-- Tags -->
                  <div v-if="field.type === 'tags'" class="cm-tags-edit">
                    <label
                      v-for="opt in field.options"
                      :key="opt.value"
                      class="cm-tag-checkbox"
                      :class="{ checked: (editingItem[field.key] || []).includes(opt.value) }"
                    >
                      <input
                        type="checkbox"
                        :value="opt.value"
                        :checked="(editingItem[field.key] || []).includes(opt.value)"
                        @change="toggleTag(field.key, opt.value, ($event.target as HTMLInputElement).checked)"
                      />
                      {{ opt.label }}
                    </label>
                  </div>
                  <!-- Number -->
                  <input
                    v-if="field.type === 'number'"
                    v-model.number="editingItem[field.key]"
                    class="cm-input cm-input-narrow"
                    type="number"
                    @input="markDirty"
                  />
                </div>
              </div>
              <div v-if="editorDirty" class="cm-dirty-hint">⚠️ 有未应用的修改</div>
            </div>
          </div>
          <div v-else class="cm-editor-empty">
            ← 从左侧列表选择一项，或点击「➕ 新增」
          </div>
        </div>
      </div>

      <!-- YAML 预览面板 -->
      <div v-if="showPreview" class="cm-preview-panel">
        <div class="cm-preview-header">
          <h3>📄 YAML 预览</h3>
          <button class="cm-btn cm-btn-small cm-btn-outline" @click="showPreview = false">关闭</button>
        </div>
        <pre class="cm-preview-code">{{ JSON.stringify(previewYaml, null, 2) }}</pre>
      </div>
    </template>
  </div>
</template>

<style scoped>
/* ── 布局 ── */
.cmd-manager {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 12px;
  font-size: 13px;
  color: var(--text, #e4e6f0);
}

/* ── Header ── */
.cm-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  flex-wrap: wrap;
  gap: 8px;
}
.cm-header-left h2 {
  margin: 0;
  font-size: 1.1rem;
  font-weight: 700;
}
.cm-subtitle {
  font-size: 0.75rem;
  color: var(--text3, #6a7088);
}
.cm-header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

/* ── Buttons ── */
.cm-btn {
  border: none;
  border-radius: 6px;
  padding: 6px 14px;
  font-size: 0.8rem;
  cursor: pointer;
  transition: all 0.12s;
  font-weight: 500;
  font-family: inherit;
}
.cm-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}
.cm-btn-primary {
  background: var(--accent, #5b8def);
  color: #fff;
}
.cm-btn-primary:hover:not(:disabled) {
  background: var(--accent2, #3b6edc);
}
.cm-btn-secondary {
  background: var(--surface2, #242838);
  color: var(--text2, #9298b0);
  border: 1px solid var(--border, #2e3348);
}
.cm-btn-secondary:hover:not(:disabled) {
  color: var(--text, #e4e6f0);
  border-color: var(--text3, #6a7088);
}
.cm-btn-outline {
  background: transparent;
  color: var(--text2, #9298b0);
  border: 1px solid var(--border, #2e3348);
}
.cm-btn-outline:hover:not(:disabled) {
  color: var(--text, #e4e6f0);
  border-color: var(--text3, #6a7088);
}
.cm-btn-danger {
  background: var(--red, #e5554f);
  color: #fff;
}
.cm-btn-danger:hover:not(:disabled) {
  opacity: 0.85;
}
.cm-btn-small {
  padding: 4px 10px;
  font-size: 0.75rem;
}

/* ── Alert ── */
.cm-alert {
  padding: 8px 14px;
  border-radius: 6px;
  font-size: 0.8rem;
}
.cm-alert-error {
  background: #2a1515;
  border: 1px solid #4a2020;
  color: var(--red, #e5554f);
}
.cm-alert-success {
  background: #142b1e;
  border: 1px solid #1e3a28;
  color: var(--green, #4caf7d);
}

/* ── Loading ── */
.cm-loading {
  padding: 40px;
  text-align: center;
  color: var(--text2, #9298b0);
}

/* ── Tabs ── */
.cm-tabs {
  display: flex;
  gap: 2px;
  background: var(--surface, #1a1d27);
  border: 1px solid var(--border, #2e3348);
  border-radius: var(--radius, 8px);
  padding: 3px;
}
.cm-tab {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  background: none;
  border: none;
  border-radius: 6px;
  padding: 8px 12px;
  font-size: 0.8rem;
  color: var(--text2, #9298b0);
  cursor: pointer;
  transition: all 0.12s;
  font-family: inherit;
}
.cm-tab:hover { color: var(--text, #e4e6f0); background: var(--surface2, #242838); }
.cm-tab.active { background: var(--accent, #5b8def); color: #fff; }
.cm-tab-icon { font-size: 0.9rem; }
.cm-tab-label { font-weight: 500; }
.cm-tab-badge {
  font-size: 0.7rem;
  background: rgba(255,255,255,0.12);
  padding: 1px 7px;
  border-radius: 10px;
  font-weight: 600;
}

/* ── Body ── */
.cm-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  flex: 1;
  min-height: 0;
}

/* ── List panel ── */
.cm-list-panel {
  background: var(--surface, #1a1d27);
  border: 1px solid var(--border, #2e3348);
  border-radius: var(--radius, 8px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.cm-list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border, #2e3348);
  background: var(--surface2, #242838);
}
.cm-list-title {
  font-size: 0.8rem;
  font-weight: 600;
  color: var(--text2, #9298b0);
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.cm-list {
  flex: 1;
  overflow-y: auto;
  max-height: 420px;
  padding: 4px;
}
.cm-list-item {
  padding: 8px 10px;
  margin-bottom: 2px;
  border-radius: 6px;
  cursor: pointer;
  transition: all 0.08s;
  border-left: 3px solid transparent;
}
.cm-list-item:hover { background: var(--surface2, #242838); }
.cm-list-item.selected {
  background: rgba(91, 141, 239, 0.12);
  border-left-color: var(--accent, #5b8def);
}
.cm-list-item.disabled { opacity: 0.45; }
.cm-item-primary {
  display: flex;
  align-items: flex-start;
  gap: 6px;
}
.cm-item-status {
  font-size: 0.6rem;
  color: var(--text3, #6a7088);
  margin-top: 3px;
}
.cm-item-status.on { color: var(--green, #4caf7d); }
.cm-item-main {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}
.cm-item-id {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--text, #e4e6f0);
  font-family: 'Cascadia Code', 'Fira Code', monospace;
}
.cm-item-desc {
  font-size: 0.7rem;
  color: var(--text3, #6a7088);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.cm-item-secondary {
  margin-top: 3px;
  font-size: 0.72rem;
  color: var(--text2, #9298b0);
  padding-left: 16px;
}
.cm-item-secondary code {
  font-size: 0.7rem;
  background: rgba(255,255,255,0.06);
  padding: 1px 5px;
  border-radius: 3px;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
}
code.cm-hex {
  color: var(--orange, #e8a838);
  font-size: 0.68rem;
}
.cm-list-empty {
  padding: 30px;
  text-align: center;
  color: var(--text3, #6a7088);
  font-size: 0.8rem;
}

/* ── Editor panel ── */
.cm-editor-panel {
  background: var(--surface, #1a1d27);
  border: 1px solid var(--border, #2e3348);
  border-radius: var(--radius, 8px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.cm-editor-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border, #2e3348);
  background: var(--surface2, #242838);
}
.cm-editor-title {
  font-size: 0.85rem;
  font-weight: 500;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
}
.cm-editor-placeholder {
  font-family: inherit;
  font-weight: 400;
  color: var(--text3, #6a7088);
}
.cm-editor-actions { display: flex; gap: 6px; }
.cm-editor-empty {
  flex: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 40px;
  color: var(--text3, #6a7088);
  font-size: 0.85rem;
}

/* ── Form fields ── */
.cm-editor-form {
  flex: 1;
  overflow-y: auto;
  padding: 12px 14px;
  max-height: 480px;
}
.cm-field {
  margin-bottom: 12px;
}
.cm-field-label {
  display: block;
  font-size: 0.72rem;
  color: var(--text2, #9298b0);
  margin-bottom: 4px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.cm-field-value {
  font-size: 0.85rem;
  color: var(--text, #e4e6f0);
}
.cm-field-value code {
  font-size: 0.8rem;
  background: rgba(255,255,255,0.06);
  padding: 2px 6px;
  border-radius: 4px;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  word-break: break-all;
}
.cm-empty-val { color: var(--text3, #6a7088); }
.cm-bool {
  display: inline-block;
  padding: 2px 10px;
  border-radius: 4px;
  font-size: 0.75rem;
  background: rgba(255,255,255,0.06);
  color: var(--text3, #6a7088);
}
.cm-bool.on {
  background: rgba(76, 175, 125, 0.15);
  color: var(--green, #4caf7d);
}
.cm-tag {
  display: inline-block;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 0.72rem;
  background: rgba(91, 141, 239, 0.15);
  color: var(--accent, #5b8def);
  margin-right: 4px;
  margin-bottom: 2px;
}

/* ── Edit mode ── */
.cm-input {
  width: 100%;
  background: var(--surface2, #242838);
  border: 1px solid var(--border, #2e3348);
  border-radius: 5px;
  padding: 7px 10px;
  color: var(--text, #e4e6f0);
  font-size: 0.8rem;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  transition: border-color 0.12s;
  box-sizing: border-box;
}
.cm-input:focus {
  outline: none;
  border-color: var(--accent, #5b8def);
}
.cm-input::placeholder {
  color: var(--text3, #6a7088);
  font-family: inherit;
}
.cm-textarea {
  min-height: 60px;
  resize: vertical;
}
.cm-input-narrow {
  width: 100px;
}
.cm-select {
  cursor: pointer;
  appearance: auto;
}
.cm-select option {
  background: var(--surface, #1a1d27);
  color: var(--text, #e4e6f0);
}

/* Toggle switch */
.cm-toggle-wrap {
  display: flex;
  align-items: center;
  gap: 8px;
}
.cm-toggle {
  position: relative;
  display: inline-block;
  width: 38px;
  height: 22px;
}
.cm-toggle input { opacity: 0; width: 0; height: 0; }
.cm-toggle-slider {
  position: absolute;
  inset: 0;
  background: var(--surface2, #242838);
  border: 1px solid var(--border, #2e3348);
  border-radius: 22px;
  cursor: pointer;
  transition: 0.15s;
}
.cm-toggle-slider::before {
  content: '';
  position: absolute;
  width: 16px; height: 16px;
  left: 2px; top: 2px;
  background: var(--text3, #6a7088);
  border-radius: 50%;
  transition: 0.15s;
}
.cm-toggle input:checked + .cm-toggle-slider {
  background: var(--accent, #5b8def);
  border-color: var(--accent, #5b8def);
}
.cm-toggle input:checked + .cm-toggle-slider::before {
  transform: translateX(16px);
  background: #fff;
}
.cm-toggle-label {
  font-size: 0.78rem;
  color: var(--text2, #9298b0);
}

/* Tags editing */
.cm-tags-edit {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.cm-tag-checkbox {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 0.75rem;
  padding: 4px 10px;
  border-radius: 5px;
  border: 1px solid var(--border, #2e3348);
  cursor: pointer;
  transition: all 0.1s;
  background: var(--surface2, #242838);
  color: var(--text2, #9298b0);
}
.cm-tag-checkbox input { display: none; }
.cm-tag-checkbox.checked {
  background: rgba(91, 141, 239, 0.15);
  border-color: var(--accent, #5b8def);
  color: var(--accent, #5b8def);
}
.cm-dirty-hint {
  padding: 6px 10px;
  background: rgba(232, 168, 56, 0.1);
  border: 1px solid rgba(232, 168, 56, 0.3);
  border-radius: 5px;
  color: var(--orange, #e8a838);
  font-size: 0.75rem;
  margin-top: 8px;
}

/* ── View mode ── */
.cm-view-fields {
  padding-bottom: 8px;
}

/* ── Preview ── */
.cm-preview-panel {
  background: var(--surface, #1a1d27);
  border: 1px solid var(--border, #2e3348);
  border-radius: var(--radius, 8px);
  overflow: hidden;
}
.cm-preview-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border, #2e3348);
  background: var(--surface2, #242838);
}
.cm-preview-header h3 {
  margin: 0;
  font-size: 0.85rem;
}
.cm-preview-code {
  margin: 0;
  padding: 14px;
  font-size: 0.72rem;
  line-height: 1.5;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  color: var(--text2, #9298b0);
  max-height: 300px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  background: transparent;
}

/* Chatbot config bridge */
.cm-bridge-panel {
  background: var(--surface, #1a1d27);
  border: 1px solid var(--border, #2e3348);
  border-radius: var(--radius, 8px);
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.cm-bridge-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 12px;
  padding: 10px 12px;
  border-bottom: 1px solid var(--border, #2e3348);
  background: var(--surface2, #242838);
}
.cm-bridge-header h3 {
  margin: 0;
  font-size: 0.9rem;
}
.cm-bridge-subtitle {
  font-size: 0.75rem;
  color: var(--text3, #6a7088);
  margin-top: 3px;
}
.cm-bridge-path {
  word-break: break-all;
}
.cm-bridge-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.cm-bridge-textarea {
  width: 100%;
  min-height: 220px;
  box-sizing: border-box;
  border: none;
  outline: none;
  resize: vertical;
  padding: 14px;
  font-family: 'Cascadia Code', 'Fira Code', monospace;
  font-size: 0.75rem;
  line-height: 1.6;
  color: var(--text, #e4e6f0);
  background: #11141b;
}
.cm-bridge-textarea::placeholder {
  color: var(--text3, #6a7088);
}
</style>
