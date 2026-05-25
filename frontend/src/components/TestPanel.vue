<script setup lang="ts">
import type { AudioItem } from '../types'
import { audioUrl } from '../api'

const props = defineProps<{
  audio: AudioItem
  loading: boolean
  testMode: string
  testLang: string
  simulateDevice: boolean
  selectedFigurine: string
  deviceMode: string
  formatSize: (bytes: number) => string
}>()

const emit = defineEmits<{
  'update:testMode': [v: string]
  'update:testLang': [v: string]
  run: []
}>()

const LANGUAGES = [
  { value: 'auto', label: '自动检测' },
  { value: 'zh', label: '中文' },
  { value: 'en', label: 'English' },
  { value: 'ja', label: '日本語' },
  { value: 'ko', label: '한국어' },
  { value: 'yue', label: '粤语' },
]
</script>

<template>
  <div class="panel">
    <!-- 当前选中音频 -->
    <div class="selected-info">
      <div class="sel-name">{{ audio.name }}</div>
      <div class="sel-meta">
        {{ audio.duration }}s · {{ props.formatSize(audio.size) }} ·
        {{ audio.sample_rate / 1000 }}kHz · {{ audio.language }}
      </div>
      <audio :src="audioUrl(audio.id)" controls class="player-inline"></audio>
    </div>

    <!-- 模拟设备信息 -->
    <div v-if="simulateDevice" class="device-info">
      <div class="info-row">
        <span class="label">🎭 角色:</span>
        <span class="value">{{ selectedFigurine }}</span>
      </div>
      <div class="info-row">
        <span class="label">📱 模式:</span>
        <span class="value">{{ deviceMode === 'chat' ? '💬 对话' : deviceMode === 'story' ? '📖 故事' : '🎵 音乐' }}</span>
      </div>
    </div>

    <!-- 测试选项 -->
    <div class="options">
      <div class="option-row">
        <label>测试模式</label>
        <div class="btn-group">
          <button
            :class="{ active: testMode === 'simple' }"
            @click="emit('update:testMode', 'simple')"
          >
            直接 STT
          </button>
          <button
            :class="{ active: testMode === 'vad' }"
            @click="emit('update:testMode', 'vad')"
          >
            VAD + STT 管道
          </button>
        </div>
      </div>

      <div class="option-row">
        <label>语言</label>
        <select
          :value="testLang"
          @change="emit('update:testLang', ($event.target as HTMLSelectElement).value)"
        >
          <option v-for="l in LANGUAGES" :key="l.value" :value="l.value">
            {{ l.label }}
          </option>
        </select>
      </div>
    </div>

    <!-- 执行按钮 -->
    <button
      class="run-btn"
      :disabled="loading"
      @click="emit('run')"
    >
      <span v-if="loading" class="spinner"></span>
      {{ loading ? '识别中...' : '▶ 开始测试' }}
    </button>
  </div>
</template>

<style scoped>
.panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
}

.selected-info {
  margin-bottom: 16px;
}

.sel-name {
  font-weight: 600;
  font-size: 1rem;
  margin-bottom: 2px;
}

.sel-meta {
  font-size: 0.8rem;
  color: var(--text2);
}

.player-inline {
  width: 100%;
  height: 36px;
  margin-top: 8px;
}

.device-info {
  background: var(--surface2);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 10px 12px;
  margin-bottom: 16px;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.85rem;
  margin-bottom: 4px;
}

.info-row:last-child {
  margin-bottom: 0;
}

.info-row .label {
  color: var(--text2);
}

.info-row .value {
  color: var(--text);
  font-weight: 500;
}

.options {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin-bottom: 16px;
}

.option-row {
  display: flex;
  align-items: center;
  gap: 12px;
}

.option-row label {
  font-size: 0.85rem;
  color: var(--text2);
  min-width: 64px;
}

.btn-group {
  display: flex;
  gap: 4px;
}

.btn-group button {
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text2);
  padding: 6px 14px;
  border-radius: 6px;
  font-size: 0.82rem;
  cursor: pointer;
  transition: all 0.12s;
}

.btn-group button.active {
  background: var(--accent2);
  border-color: var(--accent);
  color: #fff;
}

.btn-group button:hover:not(.active) {
  border-color: var(--accent);
}

select {
  background: var(--surface2);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 0.85rem;
}

.run-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 8px;
  width: 100%;
  background: var(--accent2);
  border: none;
  color: #fff;
  padding: 10px;
  border-radius: var(--radius);
  font-size: 0.95rem;
  font-weight: 600;
  cursor: pointer;
  transition: background 0.12s;
}

.run-btn:hover:not(:disabled) {
  background: var(--accent);
}

.run-btn:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

.spinner {
  display: inline-block;
  width: 14px;
  height: 14px;
  border: 2px solid rgba(255, 255, 255, 0.3);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.6s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}
</style>
