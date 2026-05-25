<script setup lang="ts">
import { ref, reactive, computed, onMounted } from 'vue'
import {
  fetchTTSOptions,
  generateTTS,
  batchGenerateTTS,
  generatedAudioUrl,
  translateText,
} from '../api'
import type {
  TTSPreset,
  TTSOptionItem,
  TTSRange,
  TTSGenerateResponse,
} from '../types'

// ── 状态 ──

const options = ref<{
  genders: TTSOptionItem[]
  personalities: TTSOptionItem[]
  emotions: TTSOptionItem[]
  presets: TTSPreset[]
  speed_range: TTSRange
  pitch_range: TTSRange
  volume_range: TTSRange
} | null>(null)

const loading = ref(false)
const result = ref<TTSGenerateResponse | null>(null)
const error = ref('')

// ── 生成参数 ──
const text = ref('')
const name = ref('')
const gender = ref('girl')
const personality = ref('cute')
const tone = ref('happy')
const speed = ref(1.0)
const pitch = ref(0)
const volume = ref(1.0)
const language = ref('en')
const saveToDb = ref(true)

// ── 翻译 ──
const translating = ref(false)

// ── 批量模式 ──
const batchMode = ref(false)
const batchTexts = ref<string[]>([''])
const batchNameTemplate = ref('语音_{index}')
const batchProgress = ref(0)
const batchResults = ref<TTSGenerateResponse[]>([])

// ── 预设一键填充 ──
function applyPreset(presetId: string) {
  const preset = options.value?.presets.find(p => p.id === presetId)
  if (!preset) return
  gender.value = preset.gender
  personality.value = preset.personality
  tone.value = preset.default_emotion
  speed.value = preset.default_speed
}

// ── 预设列表计算 ──
const filteredPresets = computed(() => {
  if (!options.value) return []
  return options.value.presets
})

// ── 获取选项 ──
onMounted(async () => {
  try {
    options.value = await fetchTTSOptions()
  } catch (e: any) {
    error.value = `加载参数选项失败: ${e.message}`
  }
})

// ── 添加批量文本行 ──
function addBatchLine() {
  batchTexts.value.push('')
}
function removeBatchLine(index: number) {
  if (batchTexts.value.length > 1) {
    batchTexts.value.splice(index, 1)
  }
}

// ── 翻译为英文 ──
async function translateToEnglish() {
  if (!text.value.trim()) return
  translating.value = true
  try {
    const resp = await translateText(text.value.trim())
    if (resp.success && resp.translated) {
      text.value = resp.translated
      language.value = 'en'
    }
  } catch (e: any) {
    // 静默失败，不影响用户操作
  } finally {
    translating.value = false
  }
}

// ── 批量全部翻译 ──
async function translateAllBatch() {
  translating.value = true
  try {
    for (let i = 0; i < batchTexts.value.length; i++) {
      const t = batchTexts.value[i].trim()
      if (!t) continue
      const resp = await translateText(t)
      if (resp.success && resp.translated) {
        batchTexts.value[i] = resp.translated
      }
    }
    language.value = 'en'
  } catch (e: any) {
    // 静默失败
  } finally {
    translating.value = false
  }
}

// ── 生成语音 ──
async function doGenerate() {
  if (!text.value.trim()) {
    error.value = '请输入要合成的文本'
    return
  }

  loading.value = true
  error.value = ''
  result.value = null

  try {
    result.value = await generateTTS({
      text: text.value.trim(),
      name: name.value.trim() || `语音_${Date.now()}`,
      gender: gender.value,
      personality: personality.value,
      tone: tone.value,
      speed: speed.value,
      pitch: pitch.value,
      volume: volume.value,
      language: language.value,
      save_to_db: saveToDb.value,
    })

    if (!result.value.success) {
      error.value = result.value.error || '生成失败'
      result.value = null
    }
  } catch (e: any) {
    error.value = `生成失败: ${e.message}`
  } finally {
    loading.value = false
  }
}

// ── 批量生成 ──
async function doBatchGenerate() {
  const validTexts = batchTexts.value.map(t => t.trim()).filter(t => t.length > 0)
  if (validTexts.length === 0) {
    error.value = '请至少输入一条文本'
    return
  }

  loading.value = true
  error.value = ''
  batchProgress.value = 0
  batchResults.value = []

  try {
    const resp = await batchGenerateTTS({
      name_template: batchNameTemplate.value || '语音_{index}',
      texts: validTexts,
      gender: gender.value,
      personality: personality.value,
      tone: tone.value,
      speed: speed.value,
      pitch: pitch.value,
      volume: volume.value,
      language: language.value,
      save_to_db: saveToDb.value,
    })
    batchResults.value = resp.results
    batchProgress.value = resp.success_count
    if (resp.success_count === 0) {
      error.value = '全部生成失败'
    }
  } catch (e: any) {
    error.value = `批量生成失败: ${e.message}`
  } finally {
    loading.value = false
  }
}

// ── 重置 ──
function resetForm() {
  gender.value = 'girl'
  personality.value = 'cute'
  tone.value = 'happy'
  speed.value = 1.0
  pitch.value = 0
  volume.value = 1.0
  language.value = 'en'
  text.value = ''
  name.value = ''
  result.value = null
  error.value = ''
  batchResults.value = []
  batchTexts.value = ['']
}
</script>

<template>
  <div class="voice-generator">
    <div class="gen-header">
      <h3>🎙️ 语音生成器</h3>
      <div class="header-actions">
        <label class="toggle-label">
          <input type="checkbox" v-model="batchMode" />
          批量模式
        </label>
        <button class="btn-reset" @click="resetForm" title="重置表单">🔄 重置</button>
      </div>
    </div>

    <!-- 预设快速选择 -->
    <div class="section presets">
      <label class="section-label">🎯 快速选择（性别×性格）</label>
      <div class="preset-grid">
        <button
          v-for="preset in filteredPresets"
          :key="preset.id"
          class="preset-btn"
          :class="{
            active: gender === preset.gender && personality === preset.personality,
            [preset.gender]: true,
          }"
          @click="applyPreset(preset.id)"
          :title="preset.description"
        >
          <span class="preset-icon">{{ preset.gender === 'boy' ? '👦' : '👧' }}</span>
          <span class="preset-name">{{ preset.name }}</span>
        </button>
      </div>
    </div>

    <!-- 参数调节 -->
    <div class="params-row">
      <!-- 性别 -->
      <div class="param-group">
        <label>性别</label>
        <div class="option-btns">
          <button
            v-for="g in options?.genders || []"
            :key="g.id"
            :class="{ active: gender === g.id }"
            @click="gender = g.id"
          >{{ g.label }}</button>
        </div>
      </div>

      <!-- 性格 -->
      <div class="param-group">
        <label>性格</label>
        <select v-model="personality" class="select">
          <option v-for="p in options?.personalities || []" :key="p.id" :value="p.id">
            {{ p.label }}
          </option>
        </select>
      </div>

      <!-- 语气/情感 -->
      <div class="param-group">
        <label>语气</label>
        <select v-model="tone" class="select">
          <option v-for="e in options?.emotions || []" :key="e.id" :value="e.id">
            {{ e.label }}
          </option>
        </select>
      </div>

      <!-- 输出语种 -->
      <div class="param-group">
        <label>输出语种</label>
        <select v-model="language" class="select">
          <option v-for="l in options?.languages || []" :key="l.id" :value="l.id">
            {{ l.label }}
          </option>
        </select>
      </div>
    </div>

    <div class="params-row">
      <div class="param-group slider-group">
        <label>语速: <strong>{{ speed.toFixed(2) }}x</strong></label>
        <input type="range"
          v-model.number="speed"
          :min="options?.speed_range.min ?? 0.5"
          :max="options?.speed_range.max ?? 2.0"
          :step="options?.speed_range.step ?? 0.05"
        />
        <div class="range-labels">
          <span>慢</span>
          <span>快</span>
        </div>
      </div>

      <div class="param-group slider-group">
        <label>音调: <strong>{{ pitch > 0 ? '+' : '' }}{{ pitch }}</strong></label>
        <input type="range"
          v-model.number="pitch"
          :min="options?.pitch_range.min ?? -12"
          :max="options?.pitch_range.max ?? 12"
          :step="options?.pitch_range.step ?? 1"
        />
        <div class="range-labels">
          <span>低沉</span>
          <span>尖亮</span>
        </div>
      </div>

      <div class="param-group slider-group">
        <label>音量: <strong>{{ volume.toFixed(1) }}x</strong></label>
        <input type="range"
          v-model.number="volume"
          :min="options?.volume_range.min ?? 0.1"
          :max="options?.volume_range.max ?? 2.0"
          :step="options?.volume_range.step ?? 0.1"
        />
        <div class="range-labels">
          <span>小</span>
          <span>大</span>
        </div>
      </div>
    </div>

    <!-- 名称 -->
    <div class="section">
      <label class="section-label">🏷️ 名称（可选，自动生成）</label>
      <input v-model="name" placeholder="留空自动生成" class="input" />
    </div>

    <!-- 文本输入（单条 / 批量） -->
    <div v-if="!batchMode" class="section">
      <label class="section-label">📝 合成文本</label>
      <div class="translatable-textarea">
        <textarea
          v-model="text"
          placeholder="输入中文后点击右侧翻译按钮转为英文语音…"
          rows="4"
          class="textarea"
        ></textarea>
        <button
          class="btn-translate"
          :disabled="translating || !text.trim()"
          @click="translateToEnglish"
          title="将中文翻译为英文"
        >
          {{ translating ? '⏳' : '🌐 译' }}
        </button>
      </div>
    </div>

    <div v-else class="section">
      <label class="section-label">📝 批量文本（每行一条）</label>
      <div class="batch-list">
        <div v-for="(_, i) in batchTexts" :key="i" class="batch-line">
          <span class="batch-index">{{ i + 1 }}.</span>
          <input v-model="batchTexts[i]" :placeholder="`第 ${i + 1} 条文本`" class="input batch-input" />
          <button class="btn-remove" @click="removeBatchLine(i)" :disabled="batchTexts.length <= 1">✕</button>
        </div>
      </div>
      <button class="btn-add-line" @click="addBatchLine">➕ 添加一行</button>
      <button
        class="btn-translate-batch"
        :disabled="translating || batchTexts.every(t => !t.trim())"
        @click="translateAllBatch"
      >
        {{ translating ? '⏳ 翻译中...' : '🌐 全部翻译为英文' }}
      </button>
      <div class="batch-name-row">
        <label>名称模板:</label>
        <input v-model="batchNameTemplate" class="input" style="width:200px" />
        <span class="hint">用 {index} 表示序号</span>
      </div>
    </div>

    <!-- 保存开关 -->
    <div class="section">
      <label class="toggle-label">
        <input type="checkbox" v-model="saveToDb" />
        保存到数据库（下次测试可用）
      </label>
    </div>

    <!-- 生成按钮 -->
    <button
      class="btn-generate"
      :disabled="loading"
      @click="batchMode ? doBatchGenerate() : doGenerate()"
    >
      {{ loading ? '⏳ 生成中...' : batchMode ? '🚀 批量生成' : '🎤 生成语音' }}
    </button>

    <!-- 错误信息 -->
    <div v-if="error" class="error-msg">❌ {{ error }}</div>

    <!-- 生成结果预览 -->
    <div v-if="result && result.success" class="result-card">
      <div class="result-header">✅ 生成成功</div>
      <div class="result-meta">
        <span>名称: {{ result.name }}</span>
        <span>音色: {{ result.voice_id }}</span>
        <span v-if="result.duration_sec > 0">时长: {{ result.duration_sec.toFixed(1) }}s</span>
        <span v-if="result.file_size > 0">大小: {{ (result.file_size / 1024).toFixed(1) }}KB</span>
      </div>
      <div class="result-text">文本: {{ result.text }}</div>
      <audio
        v-if="result.id"
        :src="generatedAudioUrl(result.id)"
        controls
        class="audio-player"
      ></audio>
    </div>

    <!-- 批量结果 -->
    <div v-if="batchResults.length > 0" class="batch-results">
      <div class="result-header">
        ✅ 批量完成: {{ batchProgress }}/{{ batchResults.length }}
      </div>
      <div v-for="(r, i) in batchResults" :key="i" class="batch-result-item" :class="{ failed: !r.success }">
        <span class="br-index">#{{ i + 1 }}</span>
        <span class="br-text">
          {{ r.success ? '✅' : '❌' }} {{ r.text?.slice(0, 40) }}{{ (r.text?.length || 0) > 40 ? '...' : '' }}
        </span>
        <span v-if="r.success && r.duration_sec > 0" class="br-duration">{{ r.duration_sec.toFixed(1) }}s</span>
        <audio v-if="r.success && r.id" :src="generatedAudioUrl(r.id)" controls class="br-audio"></audio>
        <span v-if="!r.success" class="br-error">{{ r.error }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.voice-generator {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.gen-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.gen-header h3 {
  font-size: 1rem;
  color: var(--accent);
}

.header-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.btn-reset {
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text2);
  padding: 4px 10px;
  border-radius: var(--radius);
  font-size: 0.78rem;
  cursor: pointer;
}
.btn-reset:hover {
  border-color: var(--accent);
  color: var(--text);
}

.section {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.section-label {
  font-size: 0.8rem;
  color: var(--text2);
  font-weight: 500;
}

/* 预设网格 */
.preset-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(120px, 1fr));
  gap: 6px;
}

.preset-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 2px;
  padding: 8px 6px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  color: var(--text);
  cursor: pointer;
  font-size: 0.78rem;
  transition: all 0.15s;
}
.preset-btn:hover {
  border-color: var(--accent);
  background: var(--surface2);
}
.preset-btn.active {
  border-color: var(--accent);
  background: #1b2340;
  box-shadow: 0 0 8px rgba(91, 141, 239, 0.3);
}
.preset-btn.boy.active {
  border-color: #5b8def;
}
.preset-btn.girl.active {
  border-color: #e85d8a;
}
.preset-icon {
  font-size: 1.2rem;
}
.preset-name {
  font-size: 0.7rem;
  color: var(--text2);
}

/* 参数行 */
.params-row {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(140px, 1fr));
  gap: 12px;
}

.param-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.param-group > label {
  font-size: 0.78rem;
  color: var(--text2);
}

.option-btns {
  display: flex;
  gap: 4px;
}
.option-btns button {
  flex: 1;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 5px 8px;
  font-size: 0.78rem;
  color: var(--text2);
  cursor: pointer;
  transition: all 0.15s;
}
.option-btns button:hover {
  border-color: var(--accent);
  color: var(--text);
}
.option-btns button.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

.select {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 5px 8px;
  font-size: 0.78rem;
  color: var(--text);
  cursor: pointer;
}

/* 滑动条 */
.slider-group input[type="range"] {
  width: 100%;
  height: 4px;
  -webkit-appearance: none;
  appearance: none;
  background: var(--border);
  border-radius: 2px;
  outline: none;
  cursor: pointer;
}
.slider-group input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  width: 14px;
  height: 14px;
  background: var(--accent);
  border-radius: 50%;
  cursor: pointer;
}

.range-labels {
  display: flex;
  justify-content: space-between;
  font-size: 0.65rem;
  color: var(--text3);
}

/* 输入框 */
.input {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 6px 10px;
  font-size: 0.82rem;
  color: var(--text);
  outline: none;
  transition: border-color 0.15s;
}
.input:focus {
  border-color: var(--accent);
}

.textarea {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 10px;
  font-size: 0.82rem;
  color: var(--text);
  outline: none;
  resize: vertical;
  min-height: 70px;
  font-family: inherit;
}
.textarea:focus {
  border-color: var(--accent);
}

/* 批量模式 */
.batch-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 200px;
  overflow-y: auto;
}

.batch-line {
  display: flex;
  align-items: center;
  gap: 6px;
}
.batch-index {
  font-size: 0.78rem;
  color: var(--text2);
  width: 20px;
  text-align: right;
}
.batch-input {
  flex: 1;
}
.btn-remove {
  background: none;
  border: none;
  color: var(--red);
  cursor: pointer;
  font-size: 0.8rem;
  padding: 2px 4px;
}
.btn-remove:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

.btn-add-line {
  background: var(--surface2);
  border: 1px dashed var(--border);
  color: var(--text2);
  padding: 4px 10px;
  border-radius: var(--radius);
  font-size: 0.78rem;
  cursor: pointer;
  align-self: flex-start;
}
.btn-add-line:hover {
  border-color: var(--accent);
  color: var(--text);
}

.batch-name-row {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.78rem;
  color: var(--text2);
}
.hint {
  font-size: 0.7rem;
  color: var(--text3);
}

/* 切换 */
.toggle-label {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 0.82rem;
  cursor: pointer;
  color: var(--text2);
}
.toggle-label input[type="checkbox"] {
  accent-color: var(--accent);
}

/* 生成按钮 */
.btn-generate {
  background: var(--accent);
  border: none;
  border-radius: var(--radius);
  padding: 10px 20px;
  font-size: 0.9rem;
  color: #fff;
  cursor: pointer;
  font-weight: 600;
  transition: all 0.15s;
}
.btn-generate:hover:not(:disabled) {
  background: var(--accent2);
  transform: translateY(-1px);
}
.btn-generate:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.error-msg {
  background: #2a1515;
  border: 1px solid #4a2020;
  color: var(--red);
  padding: 8px 12px;
  border-radius: var(--radius);
  font-size: 0.82rem;
}

/* 结果卡片 */
.result-card {
  background: #0f2a1a;
  border: 1px solid #1e4a2a;
  border-radius: var(--radius);
  padding: 12px;
}
.result-header {
  font-size: 0.85rem;
  font-weight: 600;
  color: var(--green);
  margin-bottom: 6px;
}
.result-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  font-size: 0.75rem;
  color: var(--text2);
  margin-bottom: 6px;
}
.result-text {
  font-size: 0.78rem;
  color: var(--text);
  margin-bottom: 8px;
  word-break: break-all;
}
.audio-player {
  width: 100%;
  height: 36px;
}

/* 批量结果 */
.batch-results {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.batch-result-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
}
.batch-result-item:last-child {
  border-bottom: none;
}
.batch-result-item.failed {
  opacity: 0.7;
}
.br-index {
  font-size: 0.75rem;
  color: var(--text2);
  width: 24px;
}
.br-text {
  font-size: 0.78rem;
  color: var(--text);
  flex: 1;
  min-width: 100px;
}
.br-duration {
  font-size: 0.72rem;
  color: var(--text2);
}
.br-audio {
  height: 28px;
  width: 180px;
}
.br-error {
  font-size: 0.72rem;
  color: var(--red);
}

/* ── 翻译按钮 ── */
.translatable-textarea {
  display: flex;
  gap: 6px;
  align-items: flex-start;
}
.translatable-textarea .textarea {
  flex: 1;
}
.btn-translate {
  background: #2a3a5c;
  border: 1px solid #3a5a8c;
  color: #8ab4f8;
  padding: 8px 10px;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 0.78rem;
  white-space: nowrap;
  transition: all 0.15s;
  flex-shrink: 0;
  margin-top: 0;
}
.btn-translate:hover:not(:disabled) {
  background: #3a5a8c;
  border-color: var(--accent);
  color: #fff;
}
.btn-translate:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
.btn-translate-batch {
  background: #2a3a5c;
  border: 1px solid #3a5a8c;
  color: #8ab4f8;
  padding: 6px 14px;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 0.78rem;
  transition: all 0.15s;
  align-self: flex-start;
}
.btn-translate-batch:hover:not(:disabled) {
  background: #3a5a8c;
  border-color: var(--accent);
  color: #fff;
}
.btn-translate-batch:disabled {
  opacity: 0.4;
  cursor: not-allowed;
}
</style>
