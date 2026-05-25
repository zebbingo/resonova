<script setup lang="ts">
import type { STTMetrics } from '../composables/useMQTTSimulation'

defineProps<{
  metrics: STTMetrics | null
  sessionId?: string
  sentChunks: number
}>()
</script>

<template>
  <div class="metrics-panel">
    <h3>📊 性能指标</h3>

    <div v-if="!metrics" class="empty-metrics">
      等待 STT 识别结果...
    </div>

    <template v-else>
      <div class="metric-row">
        <span class="metric-label">会话 ID</span>
        <span class="metric-value mono">{{ sessionId || '-' }}</span>
      </div>

      <div class="metric-row">
        <span class="metric-label">音频时长</span>
        <span class="metric-value">{{ metrics.duration_sec.toFixed(2) }}s</span>
      </div>

      <div class="metric-row highlight">
        <span class="metric-label">模型加载</span>
        <span class="metric-value">{{ metrics.load_ms.toFixed(1) }}ms</span>
      </div>

      <div class="metric-row highlight">
        <span class="metric-label">识别耗时</span>
        <span class="metric-value">{{ metrics.transcribe_ms.toFixed(1) }}ms</span>
      </div>

      <div class="metric-row rt">
        <span class="metric-label">RTF (实时因子)</span>
        <span class="metric-value">{{ metrics.rtf.toFixed(3) }}</span>
      </div>

      <div class="metric-row">
        <span class="metric-label">已发送 Chunk</span>
        <span class="metric-value">{{ sentChunks }}</span>
      </div>

      <div class="metric-note">
        💡 RTF < 0.1 表示识别速度快于音频播放速度
      </div>
    </template>
  </div>
</template>

<style scoped>
.metrics-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 16px;
}

.metrics-panel h3 {
  font-size: 0.95rem;
  margin: 0 0 12px 0;
  padding-bottom: 8px;
  border-bottom: 1px solid var(--border);
}

.empty-metrics {
  color: var(--text2);
  font-size: 0.85rem;
  text-align: center;
  padding: 20px;
}

.metric-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 8px 0;
  border-bottom: 1px solid rgba(46, 51, 72, 0.3);
}

.metric-row:last-of-type {
  border-bottom: none;
}

.metric-row.highlight {
  background: rgba(91, 141, 239, 0.1);
  margin: 0 -8px;
  padding: 8px;
  border-radius: 4px;
}

.metric-row.rt {
  background: rgba(76, 175, 125, 0.1);
  margin: 0 -8px;
  padding: 8px;
  border-radius: 4px;
}

.metric-label {
  font-size: 0.85rem;
  color: var(--text2);
}

.metric-value {
  font-size: 0.9rem;
  font-weight: 600;
  color: var(--text);
}

.metric-value.mono {
  font-family: 'Courier New', monospace;
  font-size: 0.8rem;
}

.metric-note {
  margin-top: 12px;
  padding: 8px;
  background: rgba(232, 168, 56, 0.1);
  border-left: 3px solid var(--orange);
  border-radius: 4px;
  font-size: 0.75rem;
  color: var(--text2);
  line-height: 1.5;
}
</style>
