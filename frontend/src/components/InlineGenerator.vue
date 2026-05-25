<script setup lang="ts">
import { ref, computed } from 'vue'
import { generateTTS, translateText } from '../api'

const props = defineProps<{
  figurineId: string
}>()

const emit = defineEmits<{
  generated: [audioId: string]
}>()

const text = ref('')
const gender = ref('girl')
const personality = ref('cute')
const tone = ref('happy')
const speed = ref(1.0)
const pitch = ref(0)
const volume = ref(1.0)
const generating = ref(false)
const translating = ref(false)
const translated = ref(false)

const genName = computed(() => {
  const prefix = text.value.slice(0, 20)
  return prefix ? `对话_${prefix}` : `对话_${Date.now()}`
})

async function handleGenerate() {
  if (!text.value.trim()) {
    alert('请输入文本')
    return
  }
  generating.value = true
  try {
    const resp = await generateTTS({
      text: text.value.trim(),
      name: genName.value,
      gender: gender.value,
      personality: personality.value,
      tone: tone.value,
      speed: speed.value,
      pitch: pitch.value,
      volume: volume.value,
      save_to_db: true,
      figurine_id: props.figurineId,
    })
    if (resp.success && resp.id != null) {
      emit('generated', `tts/${resp.id}`)
      text.value = ''
    } else {
      alert(`生成失败: ${resp.error || '未知错误'}`)
    }
  } catch (error: any) {
    alert(`生成出错: ${error.message}`)
  } finally {
    generating.value = false
  }
}

async function handleTranslate() {
  if (!text.value.trim()) return
  translating.value = true
  try {
    const resp = await translateText(text.value.trim())
    if (resp.success && resp.translated) {
      text.value = resp.translated
      translated.value = true
      setTimeout(() => { translated.value = false }, 2000)
    }
  } catch {
  } finally {
    translating.value = false
  }
}
</script>

<template>
  <div class="inline-generator">
    <div class="inline-textarea-wrap">
      <textarea v-model="text" class="inline-textarea" :class="{ translated }" placeholder="输入中文后点击翻译按钮转为英文语音…" rows="3" />
      <button class="btn-translate-inline" :class="{ success: translated }" :disabled="translating || !text.trim()" @click="handleTranslate" title="将中文翻译为英文">
        <span v-if="translating" class="spinner" />
        <span v-else-if="translated">✓ 已翻译</span>
        <span v-else>🌐 翻译</span>
      </button>
    </div>
    <div class="inline-options">
      <select v-model="gender" class="inline-select"><option value="boy">👦 男孩</option><option value="girl">👧 女孩</option></select>
      <select v-model="personality" class="inline-select"><option value="cute">😊 可爱</option><option value="cool">😎 酷</option><option value="warm">🤗 温暖</option><option value="funny">😂 搞笑</option><option value="serious">🧐 严肃</option></select>
      <select v-model="tone" class="inline-select"><option value="happy">😄 快乐</option><option value="sad">😢 悲伤</option><option value="angry">😠 生气</option><option value="surprised">😲 惊讶</option><option value="neutral">😐 平静</option></select>
    </div>
    <div class="inline-sliders">
      <label>语速 <input type="range" min="0.5" max="2" step="0.05" v-model.number="speed" /> {{ speed.toFixed(2) }}</label>
      <label>音高 <input type="range" min="-12" max="12" step="1" v-model.number="pitch" /> {{ pitch }}</label>
      <label>音量 <input type="range" min="0.1" max="2" step="0.1" v-model.number="volume" /> {{ volume.toFixed(1) }}</label>
    </div>
    <button class="btn-generate" :disabled="generating || !text.trim()" @click="handleGenerate">
      {{ generating ? '⏳ 生成中...' : '🎙️ 生成并自动选择' }}
    </button>
  </div>
</template>

<style scoped>
.inline-generator {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 12px;
}

.inline-textarea-wrap {
  display: flex;
  gap: 6px;
  align-items: flex-start;
}

.inline-textarea {
  flex: 1;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 8px 10px;
  border-radius: 6px;
  font-size: 0.85rem;
  resize: vertical;
  min-height: 60px;
  font-family: inherit;
  box-sizing: border-box;
  transition: border-color 0.2s, box-shadow 0.2s;
}

.inline-textarea:focus { outline: none; border-color: var(--accent); }

.inline-textarea.translated {
  border-color: #4caf50;
  box-shadow: 0 0 8px rgba(76, 175, 80, 0.3);
}

.btn-translate-inline {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  min-width: 80px;
  background: #2a3a5c;
  border: 1px solid #3a5a8c;
  color: #8ab4f8;
  padding: 8px 12px;
  border-radius: var(--radius);
  cursor: pointer;
  font-size: 0.82rem;
  font-weight: 500;
  white-space: nowrap;
  transition: all 0.2s;
  flex-shrink: 0;
}

.btn-translate-inline:hover:not(:disabled) { background: #3a5a8c; border-color: var(--accent); color: #fff; }
.btn-translate-inline:disabled { opacity: 0.4; cursor: not-allowed; }

.btn-translate-inline.success {
  background: #1b5e20;
  border-color: #4caf50;
  color: #a5d6a7;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid #8ab4f8;
  border-top-color: transparent;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

.inline-options {
  display: flex;
  gap: 6px;
  margin: 8px 0;
}

.inline-select {
  flex: 1;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 5px 8px;
  border-radius: 5px;
  font-size: 0.78rem;
}

.inline-sliders { margin: 8px 0; }

.inline-sliders label {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 0.78rem;
  color: var(--text2);
  margin-bottom: 4px;
}

.inline-sliders input[type="range"] {
  flex: 1;
  max-width: 120px;
  accent-color: var(--accent);
}

.btn-generate {
  width: 100%;
  background: var(--accent);
  color: #fff;
  border: none;
  padding: 10px;
  border-radius: var(--radius);
  font-weight: 600;
  cursor: pointer;
  transition: all 0.15s;
}
.btn-generate:hover:not(:disabled) { filter: brightness(1.1); }
.btn-generate:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
