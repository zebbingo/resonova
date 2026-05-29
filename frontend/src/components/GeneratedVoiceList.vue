<script setup lang="ts">
import { ref, onMounted } from 'vue'
import {
  fetchGeneratedVoices,
  deleteGeneratedVoice,
  generatedAudioUrl,
  sendToChatbot,
} from '../api'
import type { GeneratedVoice } from '../types'

const emit = defineEmits<{
  /** 用户点击"复用参数"按钮，携带完整 params_json 回传给父组件 */
  reuseParams: [params: any]
}>()

// ── 状态 ──
const records = ref<GeneratedVoice[]>([])
const loading = ref(true)
const error = ref('')
const deleting = ref<Set<number>>(new Set())
const sendingToChatbot = ref<Set<number>>(new Set())
const chatbotResults = ref<Record<number, { transcription?: string; error?: string }>>({})

// ── 筛选 ──
const searchText = ref('')
const filterGender = ref('')
const filterPersonality = ref('')
const showParams = ref<Set<number>>(new Set())

// ── 加载 ──
async function loadRecords() {
  loading.value = true
  error.value = ''
  try {
    const resp = await fetchGeneratedVoices(100, 0)
    records.value = resp.records
  } catch (e: any) {
    error.value = `加载失败: ${e.message}`
  } finally {
    loading.value = false
  }
}

onMounted(() => { loadRecords() })

// ── 删除 ──
async function doDelete(id: number) {
  if (!confirm('确认删除这条生成语音？')) return
  deleting.value.add(id)
  try {
    await deleteGeneratedVoice(id)
    records.value = records.value.filter(r => r.id !== id)
  } catch (e: any) {
    console.error('删除失败:', e)
  } finally {
    deleting.value.delete(id)
  }
}

// ── 发送到 chatbot ──
async function doSendToChatbot(id: number) {
  sendingToChatbot.value.add(id)
  chatbotResults.value[id] = { transcription: undefined, error: undefined }
  try {
    const result = await sendToChatbot(id)
    if (result.success) {
      chatbotResults.value[id] = { transcription: result.transcription }
    } else {
      chatbotResults.value[id] = { error: result.error || '发送失败' }
    }
  } catch (e: any) {
    chatbotResults.value[id] = { error: e.message }
  } finally {
    sendingToChatbot.value.delete(id)
  }
}

// ── 复用参数 ──
function reuseConfig(record: GeneratedVoice) {
  try {
    const params = JSON.parse(record.params_json)
    emit('reuseParams', params)
  } catch (e) {
    console.error('解析参数失败:', e)
  }
}

// ── 筛选后的记录 ──
const filteredRecords = () => {
  return records.value.filter(r => {
    if (searchText.value && !r.name.toLowerCase().includes(searchText.value.toLowerCase())
      && !r.text.toLowerCase().includes(searchText.value.toLowerCase())) {
      return false
    }
    if (filterGender.value && r.gender !== filterGender.value) return false
    if (filterPersonality.value && r.personality !== filterPersonality.value) return false
    return true
  })
}

// ── 格式化文件大小 ──
function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

// ── 性别标签 ──
function genderLabel(g: string): string {
  if (g === 'boy') return '👦 男孩'
  if (g === 'girl') return '👧 女孩'
  return g
}

// ── 暴露刷新方法 ──
defineExpose({ reload: loadRecords })
</script>

<template>
  <div class="gen-voice-list">
    <div class="list-header">
      <h3>💾 已生成语音 ({{ records.length }})</h3>
      <button class="btn-refresh" @click="loadRecords">🔄 刷新</button>
    </div>

    <!-- 筛选栏 -->
    <div class="filter-bar">
      <input
        v-model="searchText"
        placeholder="🔍 搜索名称/文本..."
        class="search-input"
      />
      <select v-model="filterGender" class="filter-select">
        <option value="">全部性别</option>
        <option value="boy">👦 男孩</option>
        <option value="girl">👧 女孩</option>
      </select>
      <select v-model="filterPersonality" class="filter-select">
        <option value="">全部性格</option>
        <option value="lively">活泼</option>
        <option value="gentle">温柔</option>
        <option value="naughty">调皮</option>
        <option value="shy">害羞</option>
        <option value="cute">可爱</option>
        <option value="calm">冷静</option>
      </select>
    </div>

    <!-- 加载中 -->
    <div v-if="loading" class="loading">加载中...</div>

    <!-- 错误 -->
    <div v-if="error" class="error-msg">{{ error }}</div>

    <!-- 列表 -->
    <div v-if="!loading && records.length > 0" class="voice-cards">
      <div
        v-for="r in filteredRecords()"
        :key="r.id"
        class="voice-card"
      >
        <div class="card-main">
          <div class="card-info">
            <span class="card-name">{{ r.name || '未命名' }}</span>
            <span class="card-meta">
              {{ genderLabel(r.gender) }} · {{ r.personality }} · {{ r.tone }}
            </span>
            <span class="card-meta">
              语速 {{ r.speed.toFixed(2) }}x ·
              音调 {{ r.pitch > 0 ? '+' : '' }}{{ r.pitch }} ·
              音量 {{ r.volume.toFixed(1) }}x
            </span>
            <span class="card-meta" v-if="r.duration_sec > 0 || r.file_size > 0">
              <template v-if="r.duration_sec > 0">{{ r.duration_sec.toFixed(1) }}s · </template>
              {{ formatSize(r.file_size) }}
            </span>
            <span class="card-date">{{ r.created_at?.slice(0, 19).replace('T', ' ') }}</span>
          </div>

          <div class="card-actions">
            <button
              v-if="r.audio_path"
              class="btn-play"
              @click="showParams.has(r.id) ? showParams.delete(r.id) : showParams.add(r.id)"
              :title="showParams.has(r.id) ? '收起' : '播放/查看'"
            >
              {{ showParams.has(r.id) ? '🔽' : '▶️' }}
            </button>
            <button
              class="btn-reuse"
              @click="reuseConfig(r)"
              title="复用参数到生成器"
            >
              📋 复用参数
            </button>
            <button
              class="btn-del"
              :disabled="deleting.has(r.id)"
              @click="doDelete(r.id)"
              title="删除"
            >
              🗑️
            </button>
            <button
              class="btn-chatbot"
              :disabled="sendingToChatbot.has(r.id)"
              @click="doSendToChatbot(r.id)"
              title="发送此音频到 chatbot 进行 STT 识别"
            >
              {{ sendingToChatbot.has(r.id) ? '⏳' : '🤖' }}
            </button>
          </div>
        </div>

        <!-- 展开详情（播放器 + 参数 + 文本 + chatbot 结果） -->
        <div v-if="showParams.has(r.id)" class="card-detail">
          <audio
            v-if="r.audio_path"
            :src="generatedAudioUrl(r.id)"
            controls
            class="card-audio"
          ></audio>
          <div class="param-detail">
            <span><strong>音色:</strong> {{ r.tts_voice_id }}</span>
            <span><strong>引擎:</strong> {{ r.tts_type }}</span>
          </div>
          <div class="text-preview">
            <strong>文本:</strong> {{ r.text }}
          </div>
          <div class="param-detail" v-if="r.params_json">
            <strong>完整参数:</strong>
            <pre class="param-json">{{ JSON.stringify(JSON.parse(r.params_json), null, 2) }}</pre>
          </div>
          <!-- chatbot 识别结果 -->
          <div v-if="chatbotResults[r.id]" class="chatbot-result">
            <strong>🤖 Chatbot STT 识别:</strong>
            <div v-if="chatbotResults[r.id].transcription" class="stt-text">
              {{ chatbotResults[r.id].transcription }}
            </div>
            <div v-else-if="chatbotResults[r.id].error" class="stt-error">
              ❌ {{ chatbotResults[r.id].error }}
            </div>
          </div>
        </div>
      </div>
    </div>

    <!-- 空状态 -->
    <div v-if="!loading && records.length === 0" class="empty">
      📭 暂无生成语音，去"语音生成器"创建吧
    </div>
  </div>
</template>

<style scoped>
.gen-voice-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.list-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.list-header h3 {
  font-size: 1rem;
  color: var(--accent);
}

.btn-refresh {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 4px 10px;
  font-size: 0.78rem;
  color: var(--text2);
  cursor: pointer;
}
.btn-refresh:hover {
  border-color: var(--accent);
  color: var(--text);
}

/* 筛选 */
.filter-bar {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}
.search-input {
  flex: 1;
  min-width: 120px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 5px 8px;
  font-size: 0.78rem;
  color: var(--text);
  outline: none;
}
.search-input:focus {
  border-color: var(--accent);
}
.filter-select {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 5px 8px;
  font-size: 0.78rem;
  color: var(--text);
  cursor: pointer;
}

.loading {
  color: var(--text2);
  font-size: 0.85rem;
  text-align: center;
  padding: 20px;
}

.error-msg {
  color: var(--red);
  font-size: 0.82rem;
}

/* 卡片 */
.voice-cards {
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 500px;
  overflow-y: auto;
}

.voice-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 10px 12px;
  transition: border-color 0.15s;
}
.voice-card:hover {
  border-color: var(--accent);
}

.card-main {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  gap: 8px;
}

.card-info {
  display: flex;
  flex-direction: column;
  gap: 2px;
  flex: 1;
  min-width: 0;
}
.card-name {
  font-size: 0.85rem;
  font-weight: 500;
  color: var(--text);
}
.card-meta {
  font-size: 0.72rem;
  color: var(--text2);
}
.card-date {
  font-size: 0.68rem;
  color: var(--text3);
}

.card-actions {
  display: flex;
  gap: 4px;
  flex-shrink: 0;
}
.card-actions button {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 4px 8px;
  font-size: 0.75rem;
  cursor: pointer;
  transition: all 0.15s;
  color: var(--text2);
}
.card-actions button:hover {
  border-color: var(--accent);
  color: var(--text);
}
.btn-reuse {
  color: var(--orange) !important;
}
.btn-del:hover {
  border-color: var(--red) !important;
  color: var(--red) !important;
}
.btn-play:hover {
  border-color: var(--green) !important;
  color: var(--green) !important;
}
.card-actions button:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.btn-chatbot {
  background: linear-gradient(135deg, var(--accent2, #6366f1), var(--accent, #4f46e5));
  border: none;
  border-radius: var(--radius);
  padding: 4px 8px;
  font-size: 0.8rem;
  color: #fff;
  cursor: pointer;
  transition: opacity 0.15s;
}
.btn-chatbot:hover {
  opacity: 0.85;
}
.btn-chatbot:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}

/* 展开详情 */
.card-detail {
  margin-top: 8px;
  padding-top: 8px;
  border-top: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.card-audio {
  width: 100%;
  height: 32px;
}
.param-detail {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
  font-size: 0.75rem;
  color: var(--text2);
}
.text-preview {
  font-size: 0.75rem;
  color: var(--text);
  word-break: break-all;
  max-height: 60px;
  overflow-y: auto;
}
.param-json {
  background: var(--surface2);
  padding: 6px 8px;
  border-radius: 4px;
  font-size: 0.7rem;
  max-height: 120px;
  overflow-y: auto;
  white-space: pre-wrap;
  word-break: break-all;
  margin: 4px 0;
}
.chatbot-result {
  margin-top: 6px;
  padding: 6px 8px;
  background: var(--surface2);
  border-radius: 4px;
  font-size: 0.78rem;
}
.stt-text {
  color: var(--accent);
  font-weight: 500;
  margin-top: 2px;
}
.stt-error {
  color: var(--red, #ef4444);
  margin-top: 2px;
}

.empty {
  color: var(--text2);
  text-align: center;
  padding: 24px;
  font-size: 0.9rem;
}
</style>
