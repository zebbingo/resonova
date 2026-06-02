<script setup lang="ts">
import type { STTMetrics, PipelineLatency, ProgressInfo } from '../composables/useMQTTSimulation'
import { computed } from 'vue'

const props = defineProps<{
  metrics: STTMetrics | null
  sessionId?: string
  sentChunks: number
  pipelineLatency?: PipelineLatency | null
  uploadProgress?: ProgressInfo | null
  ttsProgress?: ProgressInfo | null
}>()

const hasLatency = computed(() =>
  props.pipelineLatency && (
    props.pipelineLatency.stt_latency_ms > 0 ||
    props.pipelineLatency.llm_latency_ms > 0 ||
    props.pipelineLatency.tts_latency_ms > 0 ||
    props.pipelineLatency.e2e_latency_ms > 0
  )
)

function fmtMs(ms: number): string {
  if (!ms || ms <= 0) return '-'
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}
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

    <!-- ── 管道延迟指标 ── -->
    <template v-if="hasLatency">
      <h3 style="margin-top: 16px;">⏱️ 管道延迟</h3>

      <div class="metric-row delay-stt">
        <span class="metric-label">STT (语音识别)</span>
        <span class="metric-value">{{ fmtMs(pipelineLatency!.stt_latency_ms) }}</span>
      </div>

      <div class="metric-row delay-llm">
        <span class="metric-label">LLM (推理决策)</span>
        <span class="metric-value">{{ fmtMs(pipelineLatency!.llm_latency_ms) }}</span>
      </div>

      <div class="metric-row delay-tts">
        <span class="metric-label">TTS (语音合成)</span>
        <span class="metric-value">{{ fmtMs(pipelineLatency!.tts_latency_ms) }}</span>
      </div>

      <div class="metric-row delay-e2e highlight">
        <span class="metric-label">E2E (端到端)</span>
        <span class="metric-value">{{ fmtMs(pipelineLatency!.e2e_latency_ms) }}</span>
      </div>

      <div v-if="pipelineLatency!.tts_chunks > 0" class="metric-row">
        <span class="metric-label">TTS 块数 / 时长</span>
        <span class="metric-value">{{ pipelineLatency!.tts_chunks }} chunks / {{ fmtMs(pipelineLatency!.tts_duration_ms) }}</span>
      </div>

      <div v-if="pipelineLatency!.done_latency_ms > 0" class="metric-row">
        <span class="metric-label">播放回执 (done)</span>
        <span class="metric-value">{{ fmtMs(pipelineLatency!.done_latency_ms) }}</span>
      </div>

      <!-- ── 上传进度 ── -->
      <div v-if="uploadProgress && uploadProgress.total_chunks" class="progress-section">
        <div class="progress-label">⬆️ 上传: {{ uploadProgress.chunk }} / {{ uploadProgress.total_chunks }} ({{ uploadProgress.percent }}%)</div>
        <div class="progress-bar">
          <div class="progress-fill upload" :style="{ width: uploadProgress.percent + '%' }" />
        </div>
      </div>

      <!-- ── TTS 下载进度 ── -->
      <div v-if="ttsProgress && (ttsProgress.chunks_received ?? 0) > 0" class="progress-section">
        <div class="progress-label">⬇️ TTS 接收: {{ ttsProgress.chunks_received }} chunks</div>
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

.delay-stt { background: rgba(91, 141, 239, 0.08); margin: 0 -8px; padding: 6px 8px; border-radius: 4px; }
.delay-llm { background: rgba(232, 168, 56, 0.08); margin: 0 -8px; padding: 6px 8px; border-radius: 4px; }
.delay-tts { background: rgba(76, 175, 125, 0.08); margin: 0 -8px; padding: 6px 8px; border-radius: 4px; }
.delay-e2e { background: rgba(156, 39, 176, 0.1); margin: 0 -8px; padding: 6px 8px; border-radius: 4px; }

.progress-section {
  margin-top: 10px;
  padding: 8px;
  background: rgba(46, 51, 72, 0.3);
  border-radius: 4px;
}

.progress-label {
  font-size: 0.78rem;
  color: var(--text2);
  margin-bottom: 4px;
}

.progress-bar {
  height: 6px;
  background: var(--surface2);
  border-radius: 3px;
  overflow: hidden;
}

.progress-fill {
  height: 100%;
  border-radius: 3px;
  transition: width 0.3s ease;
}

.progress-fill.upload {
  background: linear-gradient(90deg, var(--blue), #7c4dff);
}
</style>
