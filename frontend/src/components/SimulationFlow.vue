<script setup lang="ts">
import { ref, computed, watch, nextTick } from 'vue'
import { store } from '../composables/simulationStore'
import type { TurnInfo, CommandInfo } from '../composables/useMQTTSimulation'
import { flowStore, phaseStatus } from '../composables/chatFlowStore'
import SessionLog from './SessionLog.vue'
import MetricsPanel from './MetricsPanel.vue'
import InlineGenerator from './InlineGenerator.vue'

type ViewMode = 'flow' | 'log'
const viewMode = ref<ViewMode>('flow')

const entry = computed(() => store.entry)
const hasSimulation = computed(() => store.active && entry.value !== null)
const upCount = computed(() => entry.value?.logs?.filter(l => l.direction === 'up').length ?? 0)
const downCount = computed(() => entry.value?.logs?.filter(l => l.direction === 'down').length ?? 0)

const showV16Panel = ref(false)
const showGenerator = ref(false)

const figurineId = computed(() => entry.value?.figurineId ?? '')

function modeLabel(m: string) {
  const map: Record<string, string> = { dialogue: '对话', story: '故事', music: '音乐' }
  return map[m] || m
}
function shortId(id?: string) {
  if (!id) return '-'
  return id.length > 12 ? id.slice(0, 12) + '…' : id
}
function fmtDuration(ms?: number): string {
  if (ms === undefined) return ''
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}
function turnStateIcon(s: TurnInfo['state']): string {
  const map: Record<string, string> = {
    capturing: '🎙️', uploading: '⬆️', thinking: '🤔',
    playing: '🔊', draining: '⏳', done: '✅', aborted: '⛔',
  }
  return map[s] || '•'
}
function turnTypeIcon(t: TurnInfo['type']): string {
  const map: Record<string, string> = { user: '👤', tts: '🤖', cue: '🔔', command: '📋' }
  return map[t] || '❓'
}
function cmdBadge(cmd: CommandInfo): string {
  if (cmd.preempt) return '🔥'
  if (cmd.afterAudio) return '⏳'
  return '📩'
}

const timelineRef = ref<HTMLElement | null>(null)
watch(
  () => flowStore.phases.map(p => p.steps.length),
  async () => {
    await nextTick()
    if (timelineRef.value) {
      timelineRef.value.scrollTop = timelineRef.value.scrollHeight
    }
  },
  { deep: true },
)
</script>

<template>
  <div class="simulation-flow">
    <!-- 状态条 -->
    <div v-if="hasSimulation" class="status-bar">
      <div class="status-bar__left">
        <span class="device-badge">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="2" y="3" width="20" height="14" rx="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
          {{ entry!.deviceId }}
        </span>
        <span class="mode-chip">{{ modeLabel(entry!.mode) }}</span>
      </div>
      <div class="status-bar__right">
        <span class="stat proto-stat" title="Protocol">v1.6</span>
        <span class="stat" title="Session ID">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          {{ shortId(entry!.sessionId) }}
        </span>
        <span class="stat up">↑ {{ upCount }}</span>
        <span class="stat down">↓ {{ downCount }}</span>
        <span class="stat chunk">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>
          {{ entry!.sentChunks }}
        </span>
        <span class="stat turn-stat" title="Turn">T{{ entry!.currentTurn }}</span>
        <span v-if="entry!.cueCount > 0" class="stat cue-stat">🔔{{ entry!.cueCount }}</span>
        <button class="btn-v16-toggle" :class="{ active: showV16Panel }" @click="showV16Panel = !showV16Panel" title="v1.6 详情">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="9" y1="3" x2="9" y2="21"/></svg>
        </button>
        <span class="status-dot" :class="entry!.status" />
        <span class="status-label" :class="entry!.status">
          {{ entry!.status === 'idle' ? '空闲' : entry!.status === 'connecting' ? '连接中' : entry!.status === 'active' ? '活跃' : entry!.status === 'capturing' ? '录音中' : entry!.status === 'playing' ? '播放中' : entry!.status === 'completed' ? '已完成' : entry!.status === 'error' ? '错误' : '未知' }}
        </span>
      </div>
    </div>

    <!-- v1.6 详情折叠面板 -->
    <div v-if="showV16Panel && hasSimulation" class="v16-panel">
      <div class="v16-grid">
        <div class="v16-col">
          <div class="v16-col-title">Turn ({{ entry!.activeTurns.length }})</div>
          <div v-if="entry!.activeTurns.length === 0" class="v16-empty">暂无</div>
          <div v-for="turn in entry!.activeTurns.slice(-6).reverse()" :key="turn.turnId" class="v16-turn">
            <span>{{ turnTypeIcon(turn.type) }}</span>
            <span class="v16-turn-id">{{ turn.turnId }}</span>
            <span class="v16-turn-state">{{ turnStateIcon(turn.state) }} {{ turn.state }}</span>
            <span class="v16-turn-chunks">{{ turn.type === 'user' ? '↑' : '↓' }}{{ turn.type === 'user' ? turn.chunksSent : turn.chunksReceived }}</span>
          </div>
        </div>
        <div class="v16-col">
          <div class="v16-col-title">STT ({{ entry!.sttTexts.length }})</div>
          <div v-if="entry!.sttTexts.length === 0" class="v16-empty">暂无</div>
          <div v-for="(text, i) in entry!.sttTexts.slice(-5)" :key="i" class="v16-stt">
            <span class="v16-stt-idx">#{{ i + 1 }}</span>
            <span class="v16-stt-text">{{ text }}</span>
          </div>
        </div>
        <div class="v16-col">
          <div class="v16-col-title">Command ({{ entry!.commands.length }})</div>
          <div v-if="entry!.commands.length === 0" class="v16-empty">暂无</div>
          <div v-for="(cmd, i) in entry!.commands.slice(-5).reverse()" :key="i" class="v16-cmd" :class="{ preempt: cmd.preempt, after: cmd.afterAudio }">
            <span>{{ cmdBadge(cmd) }}</span>
            <span class="v16-cmd-name">{{ cmd.cmd }}</span>
            <span v-if="cmd.turnId" class="v16-cmd-turn">{{ cmd.turnId }}</span>
          </div>
        </div>
      </div>
    </div>

    <!-- 视图切换 -->
    <div class="view-tabs">
      <button :class="{ active: viewMode === 'flow' }" @click="viewMode = 'flow'">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        流程视图
      </button>
      <button :class="{ active: viewMode === 'log' }" @click="viewMode = 'log'" :disabled="!hasSimulation">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/><polyline points="10 9 9 9 8 9"/></svg>
        日志视图
      </button>
    </div>

    <!-- ═══ 流程视图 ═══ -->
    <div v-if="viewMode === 'flow'" ref="timelineRef" class="flow-timeline">
      <div
        v-for="phase in flowStore.phases"
        :key="phase.id"
        class="phase-card"
        :class="[`phase--${phase.id}`, { 'phase--empty': phase.steps.length === 0 }]"
      >
        <div class="phase-accent" />

        <!-- 阶段头部 -->
        <div class="phase-header" @click="phase.expanded = !phase.expanded">
          <div class="phase-header__left">
            <span class="phase-icon-wrapper"><span class="phase-icon">{{ phase.icon }}</span></span>
            <div>
              <span class="phase-title">{{ phase.title }}</span>
              <span v-if="phase.steps.length > 0" class="phase-progress-text">
                <span v-if="phaseStatus(phase.id).error > 0" class="text-error">{{ phaseStatus(phase.id).error }} 个错误</span>
                <span v-else>{{ phaseStatus(phase.id).done }}/{{ phaseStatus(phase.id).total }} 步</span>
              </span>
            </div>
          </div>
          <div class="phase-header__right">
            <div v-if="phaseStatus(phase.id).total > 0" class="ring-container">
              <svg viewBox="0 0 36 36" width="26" height="26">
                <path d="M18 2.0845 a15.9155 15.9155 0 0 1 0 31.831 a15.9155 15.9155 0 0 1 0-31.831" fill="none" stroke="var(--border)" stroke-width="3" />
                <path
                  d="M18 2.0845 a15.9155 15.9155 0 0 1 0 31.831 a15.9155 15.9155 0 0 1 0-31.831"
                  fill="none"
                  :stroke="phaseStatus(phase.id).done === phaseStatus(phase.id).total ? 'var(--green)' : 'var(--accent)'"
                  stroke-width="3"
                  :stroke-dasharray="`${(phaseStatus(phase.id).done / phaseStatus(phase.id).total) * 100}, 100`"
                  stroke-linecap="round"
                  style="transition: stroke-dasharray 0.4s ease;"
                />
                <text x="18" y="20" text-anchor="middle" font-size="8" fill="var(--text2)" font-weight="600">
                  {{ Math.round((phaseStatus(phase.id).done / phaseStatus(phase.id).total) * 100) }}
                </text>
              </svg>
            </div>
            <span class="phase-arrow" :class="{ open: phase.expanded }">
              <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3"><polyline points="6 9 12 15 18 9"/></svg>
            </span>
          </div>
        </div>

        <!-- 步骤时间线 -->
        <div v-if="phase.expanded && phase.steps.length > 0" class="phase-body">
          <div
            v-for="(step, idx) in phase.steps"
            :key="step.id"
            class="step-node"
            :class="[step.status, { 'step--first': idx === 0, 'step--last': idx === phase.steps.length - 1 }]"
          >
            <!-- 连接线 -->
            <div class="line-track">
              <div v-if="idx < phase.steps.length - 1" class="line-connector" :class="step.status === 'completed' ? 'done' : step.status === 'error' ? 'err' : step.status" />
            </div>

            <!-- 圆点 -->
            <div class="dot-wrapper">
              <div class="dot" :class="step.status">
                <template v-if="step.status === 'completed'">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="4"><polyline points="20 6 9 17 4 12"/></svg>
                </template>
                <template v-else-if="step.status === 'error'">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="4"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                </template>
                <template v-else-if="step.status === 'running'">
                  <span class="dot-running-ring"><span class="dot-running-core" /></span>
                </template>
                <template v-else>
                  <span class="dot-pending-inner" />
                </template>
              </div>
            </div>

            <!-- 内容 -->
            <div class="step-content" :class="{ 'has-extra': !!step.extra }">
              <div class="step-main">
                <span class="step-name">{{ step.label }}</span>
                <span v-if="fmtDuration(step.duration_ms)" class="step-duration">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                  {{ fmtDuration(step.duration_ms) }}
                </span>
              </div>
              <div v-if="step.detail" class="step-detail">{{ step.detail }}</div>
              <div v-if="step.extra" class="step-extra">
                <span class="extra-icon">💬</span>{{ step.extra }}
              </div>
              <div class="step-footer">
                <span class="step-time">
                  <svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
                  {{ step.timestamp }}
                </span>
                <span v-if="step.status === 'running'" class="tag tag-running">进行中</span>
                <span v-else-if="step.status === 'completed'" class="tag tag-done">完成</span>
                <span v-else-if="step.status === 'error'" class="tag tag-error">失败</span>
                <span v-else class="tag tag-pending">等待</span>
              </div>
            </div>
          </div>
        </div>

        <!-- 折叠摘要 -->
        <div v-else-if="!phase.expanded && phase.steps.length > 0" class="phase-collapsed">
          已折叠 · {{ phaseStatus(phase.id).done }}/{{ phaseStatus(phase.id).total }} 步
          <span v-if="phaseStatus(phase.id).error > 0" class="collapsed-error"> {{ phaseStatus(phase.id).error }} 个错误</span>
        </div>

        <!-- 空状态 -->
        <div v-if="phase.expanded && phase.steps.length === 0" class="phase-empty">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="10"/><line x1="12" y1="8" x2="12" y2="12"/><line x1="12" y1="16" x2="12.01" y2="16"/></svg>
          等待步骤…
        </div>
      </div>

      <!-- 全局空状态 -->
      <div v-if="flowStore.phases.every(p => p.steps.length === 0)" class="timeline-empty">
        <div class="empty-icon">
          <svg width="42" height="42" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
        </div>
        <div class="empty-title">等待流程启动</div>
        <div class="empty-desc">选择角色后，流程步骤将在此实时展示</div>
      </div>
    </div>

    <!-- ═══ 日志视图 ═══ -->
    <div v-else class="flow-body">
      <div v-if="hasSimulation" class="flow-log">
        <SessionLog :logs="entry!.logs" />
      </div>
      <div v-if="hasSimulation" class="flow-metrics">
        <MetricsPanel
          :metrics="(entry!.sttResult as any)?.metrics ?? null"
          :session-id="entry!.sessionId"
          :sent-chunks="entry!.sentChunks"
        />
      </div>
      <div v-else class="flow-empty-log">
        <svg width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
        <p>等待模拟启动…</p>
      </div>
    </div>

    <!-- TTS 语音生成 -->
    <div class="generator-section">
      <button class="generator-toggle" @click="showGenerator = !showGenerator">
        {{ showGenerator ? '✕ 关闭' : '🎙️ 快速生成 TTS 语音' }}
      </button>
      <div v-if="showGenerator && figurineId" class="generator-body">
        <InlineGenerator :figurineId="figurineId" @generated="() => showGenerator = false" />
      </div>
    </div>
  </div>
</template>

<style scoped>
/* ════════════════════════════════════════
   Simulation Flow — 视觉升级版
   深色系 · 精致圆角 · 流畅动画
   ════════════════════════════════════════ */

.simulation-flow {
  display: flex; flex-direction: column; height: 100%; gap: 8px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans SC', sans-serif;
}

/* ── 状态条 ── */
.status-bar {
  display: flex; justify-content: space-between; align-items: center;
  background: linear-gradient(135deg, var(--surface) 0%, #1e2130 100%);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 8px 14px;
  flex-shrink: 0;
}
.status-bar__left, .status-bar__right { display: flex; align-items: center; gap: 8px; }

.device-badge {
  display: inline-flex; align-items: center; gap: 5px;
  font-family: 'SF Mono', 'Fira Code', 'Cascadia Code', 'Courier New', monospace;
  font-size: 0.8rem; font-weight: 600; color: var(--text);
  background: rgba(91, 141, 239, 0.1);
  border: 1px solid rgba(91, 141, 239, 0.2);
  padding: 2px 8px 2px 6px;
  border-radius: 6px;
}
.device-badge svg { color: var(--accent); }

.mode-chip {
  font-size: 0.72rem; color: var(--text2);
  background: var(--surface2); padding: 2px 8px; border-radius: 4px; font-weight: 500;
}

.stat {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 0.72rem; color: var(--text3); white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.stat svg { flex-shrink: 0; }
.stat.up { color: var(--accent); }
.stat.down { color: var(--green); }
.stat.chunk { color: var(--orange); }

.status-dot {
  width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0;
}
.status-dot.idle { background: var(--text3); }
.status-dot.connecting { background: var(--orange); animation: dot-pulse 1.5s ease infinite; }
.status-dot.active { background: var(--green); box-shadow: 0 0 6px rgba(76, 175, 125, 0.5); }
.status-dot.completed { background: var(--accent); }
.status-dot.error { background: var(--red); }

.status-label { font-size: 0.72rem; font-weight: 500; }
.status-label.idle { color: var(--text3); }
.status-label.connecting { color: var(--orange); }
.status-label.active { color: var(--green); }
.status-label.completed { color: var(--accent); }
.status-label.error { color: var(--red); }

@keyframes dot-pulse {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.6; transform: scale(1.3); }
}

/* ── 视图切换 ── */
.view-tabs {
  display: flex; gap: 2px;
  background: var(--surface); border: 1px solid var(--border); border-radius: 10px;
  padding: 3px; flex-shrink: 0;
}
.view-tabs button {
  flex: 1; display: inline-flex; align-items: center; justify-content: center; gap: 5px;
  background: none; border: none; border-radius: 7px;
  padding: 7px 12px; font-size: 0.8rem; color: var(--text2);
  cursor: pointer; transition: all 0.2s cubic-bezier(0.4,0,0.2,1);
  font-weight: 500; font-family: inherit;
}
.view-tabs button:hover:not(:disabled) { color: var(--text); background: var(--surface2); }
.view-tabs button.active {
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent2) 100%);
  color: #fff; box-shadow: 0 2px 8px rgba(91, 141, 239, 0.3);
}
.view-tabs button:disabled { opacity: 0.35; cursor: not-allowed; }

/* ── 时间线容器 ── */
.flow-timeline {
  flex: 1; overflow-y: auto; display: flex; flex-direction: column; gap: 10px;
  min-height: 0; padding-right: 4px; scroll-behavior: smooth;
}
.flow-timeline::-webkit-scrollbar { width: 5px; }
.flow-timeline::-webkit-scrollbar-track { background: transparent; }
.flow-timeline::-webkit-scrollbar-thumb {
  background: var(--border); border-radius: 10px;
}
.flow-timeline::-webkit-scrollbar-thumb:hover { background: var(--text3); }

/* ── 阶段卡片 ── */
.phase-card {
  position: relative;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 12px;
  overflow: hidden;
  flex-shrink: 0;
  transition: border-color 0.2s, box-shadow 0.2s;
}
.phase-card:hover {
  border-color: rgba(255,255,255,0.08);
  box-shadow: 0 2px 12px rgba(0,0,0,0.2);
}

/* 左边界颜色条 */
.phase-accent {
  position: absolute; left: 0; top: 0; bottom: 0; width: 3px;
  border-radius: 0 2px 2px 0;
}
.phase--device  .phase-accent { background: linear-gradient(180deg, #5b8def, #7c6cf0); }
.phase--role    .phase-accent { background: linear-gradient(180deg, #4caf7d, #45d49b); }
.phase--session .phase-accent { background: linear-gradient(180deg, #e8a838, #f47b4a); }

/* 阶段头部 */
.phase-header {
  display: flex; justify-content: space-between; align-items: center;
  padding: 12px 14px 12px 16px;
  cursor: pointer; user-select: none;
  transition: background 0.15s;
}
.phase-header:hover { background: rgba(255,255,255,0.02); }

.phase-header__left, .phase-header__right {
  display: flex; align-items: center; gap: 10px;
}

.phase-icon-wrapper {
  width: 32px; height: 32px; display: flex; align-items: center; justify-content: center;
  border-radius: 8px; flex-shrink: 0;
}
.phase--device .phase-icon-wrapper { background: rgba(91, 141, 239, 0.12); }
.phase--role .phase-icon-wrapper { background: rgba(76, 175, 125, 0.12); }
.phase--session .phase-icon-wrapper { background: rgba(232, 168, 56, 0.12); }

.phase-icon { font-size: 1rem; line-height: 1; }

.phase-title { font-size: 0.85rem; font-weight: 600; color: var(--text); }
.phase-progress-text {
  font-size: 0.72rem; color: var(--text3); margin-top: 1px; display: block;
}
.text-error { color: var(--red); font-weight: 500; }

/* 进度环 */
.ring-container { display: flex; align-items: center; }
.ring-container svg { display: block; }

.phase-arrow {
  display: flex; align-items: center; transition: transform 0.25s cubic-bezier(0.4,0,0.2,1);
  color: var(--text3);
}
.phase-arrow.open { transform: rotate(180deg); }

/* 折叠摘要 */
.phase-collapsed {
  padding: 0 14px 10px 16px;
  font-size: 0.72rem; color: var(--text3);
}
.collapsed-error { color: var(--red); }

/* 步骤时间线 */
.phase-body { padding: 0 14px 8px 16px; }

.step-node {
  display: flex; align-items: flex-start; position: relative;
  padding: 4px 0; min-height: 40px;
}
.step--first { padding-top: 2px; }
.step--last { min-height: 34px; }

/* 连接线轨道 */
.line-track {
  width: 22px; flex-shrink: 0; position: relative;
  display: flex; justify-content: center;
  z-index: 0;
}
.line-connector {
  width: 2px;
  background: var(--border);
  position: absolute; top: 16px; bottom: -4px;
  transition: background 0.3s;
}
.line-connector.done { background: var(--green); }
.line-connector.err { background: var(--red); }
.line-connector.running { background: var(--accent); }

/* 圆点 */
.dot-wrapper {
  width: 22px; flex-shrink: 0;
  display: flex; justify-content: center;
  padding-top: 2px; z-index: 1;
}
.dot {
  width: 18px; height: 18px; border-radius: 50%;
  display: flex; align-items: center; justify-content: center;
  transition: all 0.3s cubic-bezier(0.4,0,0.2,1);
  position: relative;
}
.dot.completed {
  background: linear-gradient(135deg, #4caf7d 0%, #45d49b 100%);
  color: #fff;
  box-shadow: 0 0 8px rgba(76, 175, 125, 0.35);
}
.dot.running {
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent2) 100%);
  box-shadow: 0 0 10px rgba(91, 141, 239, 0.4);
  animation: running-glow 1.8s ease-in-out infinite;
}
.dot.error {
  background: linear-gradient(135deg, var(--red) 0%, #ff6b6b 100%);
  color: #fff;
  box-shadow: 0 0 8px rgba(229, 85, 79, 0.35);
}
.dot.pending {
  background: var(--surface2);
  border: 2px solid var(--border);
}

.dot-running-ring {
  display: flex; align-items: center; justify-content: center;
  width: 10px; height: 10px;
}
.dot-running-core {
  width: 6px; height: 6px; border-radius: 50%;
  background: #fff;
  animation: dot-blink 0.8s ease-in-out infinite;
}
.dot-pending-inner {
  width: 6px; height: 6px; border-radius: 50%;
  background: var(--text3);
}

@keyframes running-glow {
  0%, 100% { box-shadow: 0 0 8px rgba(91, 141, 239, 0.3); }
  50% { box-shadow: 0 0 16px rgba(91, 141, 239, 0.6); }
}
@keyframes dot-blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.2; }
}

/* 步骤内容 */
.step-content {
  flex: 1; min-width: 0;
  padding: 0 0 0 8px;
  transition: background 0.2s;
}
.step-main {
  display: flex; align-items: center; gap: 6px; flex-wrap: wrap;
}
.step-name {
  font-size: 0.82rem; font-weight: 500; color: var(--text);
  line-height: 1.4;
}
.step-duration {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 0.7rem; color: var(--green);
  background: rgba(76, 175, 125, 0.1);
  padding: 1px 6px; border-radius: 4px;
  font-weight: 500; white-space: nowrap;
  font-variant-numeric: tabular-nums;
}
.step-duration svg { color: var(--green); }

.step-detail {
  font-size: 0.73rem; color: var(--text2);
  margin-top: 2px; line-height: 1.4;
  word-break: break-word;
}
.step-extra {
  font-size: 0.75rem; color: var(--accent);
  background: rgba(91, 141, 239, 0.08);
  padding: 5px 10px; border-radius: 8px;
  margin-top: 4px; line-height: 1.45;
  word-break: break-word;
  display: flex; gap: 6px; align-items: flex-start;
}
.extra-icon { flex-shrink: 0; }
.has-extra { padding-bottom: 2px; }

.step-footer {
  display: flex; align-items: center; gap: 6px;
  margin-top: 3px;
}
.step-time {
  display: inline-flex; align-items: center; gap: 3px;
  font-size: 0.68rem; color: var(--text3);
  font-family: 'SF Mono', 'Fira Code', 'Courier New', monospace;
  font-variant-numeric: tabular-nums;
}
.step-time svg { width: 9px; height: 9px; }

/* 状态标签 */
.tag {
  font-size: 0.65rem; padding: 1px 6px; border-radius: 3px;
  font-weight: 500; line-height: 1.3;
}
.tag-running {
  background: rgba(91, 141, 239, 0.15); color: var(--accent);
  animation: tag-pulse 1.5s ease-in-out infinite;
}
.tag-done { background: rgba(76, 175, 125, 0.12); color: var(--green); }
.tag-error { background: rgba(229, 85, 79, 0.12); color: var(--red); }
.tag-pending { background: var(--surface2); color: var(--text3); }

@keyframes tag-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.6; }
}

/* 已完成/错误步骤的标签淡化 */
.step-node.completed .step-name { color: var(--text2); }
.step-node.error .step-name { color: var(--red); }

/* 空阶段 */
.phase-empty {
  display: flex; align-items: center; justify-content: center; gap: 6px;
  color: var(--text3); font-size: 0.75rem;
  padding: 14px 0 10px;
}

/* 全局空状态 */
.timeline-empty {
  text-align: center;
  padding: 48px 20px;
  color: var(--text3);
}
.empty-icon { opacity: 0.3; margin-bottom: 12px; }
.empty-title { font-size: 0.95rem; color: var(--text2); font-weight: 500; margin-bottom: 4px; }
.empty-desc { font-size: 0.8rem; color: var(--text3); }

/* ═══ 日志视图 ═══ */
.flow-body {
  flex: 1; display: grid; grid-template-columns: 1fr 260px; gap: 12px; min-height: 0;
}
.flow-log { min-height: 0; overflow: hidden; }
.flow-log :deep(.session-log) { height: 100%; }
.flow-metrics { min-height: 0; }
.flow-metrics :deep(.metrics-panel) { height: 100%; }
.flow-empty-log {
  grid-column: 1 / -1; text-align: center;
  padding: 60px 20px; color: var(--text3); font-size: 0.9rem;
}

@media (max-width: 900px) {
  .flow-body { grid-template-columns: 1fr; }
}

/* ── v1.6 面板 ── */
.btn-v16-toggle {
  background: none; border: 1px solid transparent; color: var(--text3);
  border-radius: 4px; padding: 1px 4px; cursor: pointer; transition: all 0.15s;
  display: inline-flex; align-items: center;
}
.btn-v16-toggle:hover { border-color: var(--border); color: var(--text); }
.btn-v16-toggle.active { border-color: var(--accent); color: var(--accent); background: rgba(91,141,239,0.1); }

.proto-stat {
  color: #4ade80 !important; font-weight: 600;
  background: rgba(74,222,128,0.1); padding: 1px 5px; border-radius: 4px;
  font-size: 0.68rem !important;
}
.turn-stat { color: var(--accent) !important; font-weight: 600; font-size: 0.68rem !important; }
.cue-stat { color: #fbbf24 !important; font-size: 0.68rem !important; }

.v16-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 10px 14px;
  flex-shrink: 0;
  animation: v16-slide 0.2s ease;
}
@keyframes v16-slide {
  from { opacity: 0; transform: translateY(-6px); }
  to { opacity: 1; transform: translateY(0); }
}

.v16-grid {
  display: grid;
  grid-template-columns: 1fr 1fr 1fr;
  gap: 12px;
}
@media (max-width: 700px) {
  .v16-grid { grid-template-columns: 1fr; }
}

.v16-col-title {
  font-size: 0.72rem; font-weight: 600; color: var(--text2);
  margin-bottom: 6px; padding-bottom: 4px;
  border-bottom: 1px solid var(--border);
}
.v16-empty {
  font-size: 0.7rem; color: var(--text3); padding: 6px 0; text-align: center;
}

.v16-turn {
  display: flex; align-items: center; gap: 5px;
  font-size: 0.72rem; padding: 3px 0;
  border-bottom: 1px solid rgba(255,255,255,0.03);
}
.v16-turn:last-child { border-bottom: none; }
.v16-turn-id {
  font-family: 'SF Mono', 'Fira Code', monospace;
  color: var(--text); font-weight: 600; min-width: 36px;
}
.v16-turn-state { color: var(--text3); font-size: 0.68rem; }
.v16-turn-chunks { color: var(--text3); font-size: 0.68rem; margin-left: auto; }

.v16-stt {
  display: flex; gap: 6px; padding: 3px 0;
  font-size: 0.72rem;
  border-bottom: 1px solid rgba(255,255,255,0.03);
}
.v16-stt:last-child { border-bottom: none; }
.v16-stt-idx { color: var(--text3); min-width: 20px; font-size: 0.68rem; }
.v16-stt-text { color: var(--text); word-break: break-all; line-height: 1.3; }

.v16-cmd {
  display: flex; align-items: center; gap: 5px;
  font-size: 0.72rem; padding: 3px 0;
  border-bottom: 1px solid rgba(255,255,255,0.03);
}
.v16-cmd:last-child { border-bottom: none; }
.v16-cmd.preempt { border-left: 2px solid var(--red); padding-left: 4px; }
.v16-cmd.after { border-left: 2px solid #fbbf24; padding-left: 4px; }
.v16-cmd-name { color: var(--text); font-weight: 600; }
.v16-cmd-turn { color: var(--text3); font-size: 0.68rem; margin-left: auto; }

/* ── TTS 生成器 ── */
.generator-section {
  flex-shrink: 0;
  padding: 0 12px 12px;
}
.generator-toggle {
  width: 100%;
  background: var(--surface);
  border: 1px solid var(--border);
  color: var(--text);
  padding: 10px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 0.85rem;
  transition: all 0.15s;
}
.generator-toggle:hover { border-color: var(--accent); background: var(--accent2); color: #fff; }
.generator-body {
  margin-top: 8px;
  animation: v16-slide 0.2s ease;
}
</style>