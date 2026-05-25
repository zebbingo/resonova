<script setup lang="ts">
import { computed, ref } from 'vue'
import type { AudioItem } from '../types'
import { audioUrl } from '../api'

const props = defineProps<{
  audios: AudioItem[]
  selected: AudioItem | null
  formatSize: (bytes: number) => string
}>()

const emit = defineEmits<{
  select: [item: AudioItem]
}>()

const LANG_LABELS: Record<string, string> = {
  zh: '中文', en: 'English', ja: '日本語', ko: '한국어', yue: '粤语',
}

const SOURCE_LABELS: Record<string, string> = {
  model: '📦 模型测试',
  testdata: '🧪 项目测试',
  realtime: '🎙️ 真实录音',
}

const SOURCE_ORDER = ['model', 'testdata', 'realtime']

const activeTab = ref<string>('all')

const filteredAudios = computed(() => {
  if (activeTab.value === 'all') return props.audios
  return props.audios.filter(a => a.source === activeTab.value)
})

/** 按 source 分组，source 内按 duration 降序 */
const groupedAudios = computed(() => {
  const groups: { source: string; label: string; items: AudioItem[] }[] = []
  for (const src of SOURCE_ORDER) {
    const items = filteredAudios.value.filter(a => a.source === src)
    if (items.length > 0) {
      items.sort((a, b) => b.duration - a.duration)
      groups.push({ source: src, label: SOURCE_LABELS[src] || src, items })
    }
  }
  return groups
})
</script>

<template>
  <div class="audio-list">
    <!-- 筛选栏 -->
    <div class="filter-bar">
      <button
        :class="{ active: activeTab === 'all' }"
        @click="activeTab = 'all'"
      >全部 ({{ audios.length }})</button>
      <button
        v-for="(label, key) in SOURCE_LABELS"
        :key="key"
        :class="{ active: activeTab === key }"
        @click="activeTab = key"
      >{{ label }}</button>
    </div>

    <!-- 分组列表 -->
    <div v-for="group in groupedAudios" :key="group.source" class="group">
      <div class="group-title">{{ group.label }}</div>

      <div
        v-for="a in group.items"
        :key="a.id"
        class="audio-card"
        :class="{ active: selected?.id === a.id }"
        @click="emit('select', a)"
      >
        <div class="audio-main">
          <span class="audio-icon">🎵</span>
          <div class="audio-info">
            <span class="audio-name">{{ a.name }}</span>
            <span class="audio-lang">
              {{ LANG_LABELS[a.language] || a.language }}
              <span v-if="a.source === 'realtime' && !a.duration" class="badge-uncached">未缓存</span>
            </span>
          </div>
        </div>
        <div class="audio-meta">
          <span v-if="a.duration > 0">{{ a.duration.toFixed(1) }}s</span>
          <span v-if="a.size > 0">{{ formatSize(a.size) }}</span>
          <span v-if="a.sample_rate > 0">{{ (a.sample_rate / 1000).toFixed(0) }}kHz</span>
        </div>

        <!-- 播放器 -->
        <audio
          v-if="selected?.id === a.id"
          :src="audioUrl(a.id)"
          controls
          class="audio-player"
        ></audio>
      </div>
    </div>

    <div v-if="audios.length === 0" class="empty">暂无可用音频</div>
  </div>
</template>

<style scoped>
.audio-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* 筛选栏 */
.filter-bar {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  margin-bottom: 8px;
}

.filter-bar button {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 4px 10px;
  font-size: 0.78rem;
  color: var(--text2);
  cursor: pointer;
  transition: all 0.15s;
}

.filter-bar button:hover {
  border-color: var(--accent);
  color: var(--text);
}

.filter-bar button.active {
  background: var(--accent);
  border-color: var(--accent);
  color: #fff;
}

/* 分组 */
.group {
  margin-bottom: 4px;
}

.group-title {
  font-size: 0.72rem;
  color: var(--text3);
  padding: 4px 2px;
  font-weight: 600;
  letter-spacing: 0.5px;
}

.audio-card {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 8px 10px;
  cursor: pointer;
  transition: all 0.15s;
  margin-bottom: 4px;
}

.audio-card:hover {
  border-color: var(--accent);
  background: var(--surface2);
}

.audio-card.active {
  border-color: var(--accent);
  background: #1b2340;
}

.audio-main {
  display: flex;
  align-items: center;
  gap: 8px;
}

.audio-icon {
  font-size: 1rem;
  flex-shrink: 0;
}

.audio-info {
  display: flex;
  flex-direction: column;
  min-width: 0;
  flex: 1;
}

.audio-name {
  font-size: 0.82rem;
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.audio-lang {
  font-size: 0.7rem;
  color: var(--accent);
  margin-top: 1px;
}

.badge-uncached {
  display: inline-block;
  background: #f59e0b33;
  color: #f59e0b;
  font-size: 0.65rem;
  padding: 0 5px;
  border-radius: 4px;
  margin-left: 4px;
}

.audio-meta {
  display: flex;
  gap: 8px;
  font-size: 0.7rem;
  color: var(--text2);
  margin-top: 3px;
}

.audio-player {
  width: 100%;
  height: 32px;
  margin-top: 6px;
}

.empty {
  color: var(--text2);
  text-align: center;
  padding: 24px;
  font-size: 0.9rem;
}
</style>
