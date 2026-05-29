<script setup lang="ts">
import { onMounted, ref } from 'vue'
import type { AudioItem } from './types'
import { fetchTestAudios } from './api'
import DeviceManager from './components/DeviceManager.vue'
import VoiceGenerator from './components/VoiceGenerator.vue'
import GeneratedVoiceList from './components/GeneratedVoiceList.vue'
import SimulationFlow from './components/SimulationFlow.vue'
import CommandMonitor from './components/CommandMonitor.vue'
import CommandManager from './components/CommandManager.vue'
import ServiceManager from './components/ServiceManager.vue'
import { flowStore } from './composables/chatFlowStore'

type Tab = 'service-manager' | 'mqtt' | 'tts-generator' | 'tts-list' | 'command-monitor' | 'command-manager'

const activeTab = ref<Tab>('mqtt')
const audios = ref<AudioItem[]>([])
const error = ref('')

onMounted(async () => {
  try {
    audios.value = (await fetchTestAudios()).audios
  } catch (e: any) {
    error.value = `加载音频列表失败: ${e.message}`
  }
})

function formatSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

function onReuseParams() {
  activeTab.value = 'tts-generator'
}
</script>

<template>
  <div class="app">
    <header class="topbar">
      <h1>VoicePipe</h1>
      <p class="subtitle">
        语音管道测试平台 · STT / LLM / TTS 全链路 · MQTT 多设备模拟 · 后端: 192.168.52.134:8765
      </p>
    </header>

    <nav class="tab-bar">
      <button :class="{ active: activeTab === 'service-manager' }" @click="activeTab = 'service-manager'">
        服务管理
      </button>
      <button :class="{ active: activeTab === 'mqtt' }" @click="activeTab = 'mqtt'">
        MQTT 多设备模拟
      </button>
      <button :class="{ active: activeTab === 'tts-generator' }" @click="activeTab = 'tts-generator'">
        语音生成
      </button>
      <button :class="{ active: activeTab === 'tts-list' }" @click="activeTab = 'tts-list'">
        已生成语音
      </button>
      <button :class="{ active: activeTab === 'command-monitor' }" @click="activeTab = 'command-monitor'">
        指令拦截监控
      </button>
      <button :class="{ active: activeTab === 'command-manager' }" @click="activeTab = 'command-manager'">
        指令管理
      </button>
    </nav>

    <div v-if="activeTab === 'service-manager'" class="panel-shell">
      <ServiceManager />
    </div>

    <div v-if="activeTab === 'mqtt'" class="layout">
      <aside class="sidebar">
        <h2>MQTT 多设备模拟</h2>
        <DeviceManager :audios="audios" :format-size="formatSize" />
      </aside>

      <main class="main">
        <template v-if="flowStore.active">
          <SimulationFlow />
        </template>
        <template v-else>
          <div class="info-panel">
            <h3>使用说明</h3>

            <div class="info-section">
              <h4>1. 管理设备</h4>
              <p>点击“添加设备”创建新设备，最多支持 4 个设备。</p>
              <p>每个设备都可以单独配置角色和模式。</p>
            </div>

            <div class="info-section">
              <h4>2. 配置设备</h4>
              <ul>
                <li><strong>角色</strong> - 选择 figurine</li>
                <li><strong>模式</strong> - 对话 / 故事 / 音乐三种模式</li>
                <li><strong>内容</strong> - 根据模式选择音频 / 故事 / 音乐</li>
              </ul>
            </div>

            <div class="info-section">
              <h4>3. 启动模拟</h4>
              <p>点击“启动 MQTT 模拟”按钮：</p>
              <ul>
                <li>后端连接 MQTT Broker</li>
                <li>按 v1.1 协议分帧上传音频</li>
                <li>Chatbot 后端执行真实 STT → LLM → TTS 全链路</li>
                <li>右侧面板实时显示流程阶段和性能指标</li>
              </ul>
            </div>

            <div class="info-section highlight">
              <h4>核心特性</h4>
              <ul>
                <li>使用数据库中的真实音频文件</li>
                <li>完整 MQTT v1.x 协议模拟（Opus 编码）</li>
                <li>真实生产链路：STT → LLM → TTS → 指令</li>
                <li>支持最多 4 个设备并发测试</li>
                <li>流程阶段可视化（时间线 + 日志）</li>
                <li>可对比不同角色 / 模式的端到端表现</li>
              </ul>
            </div>

            <div class="info-section">
              <h4>典型场景</h4>
              <ul>
                <li><strong>单设备测试</strong> - 验证某个角色的 STT 精度</li>
                <li><strong>多设备对比</strong> - 同时测试 4 个角色，比较 RTF</li>
                <li><strong>模式切换</strong> - 测试对话 / 故事 / 音乐的不同表现</li>
                <li><strong>问题复现</strong> - 用固定音频 + 配置精确复现线上问题</li>
              </ul>
            </div>
          </div>
        </template>

        <div v-if="error" class="error-card">❌ {{ error }}</div>
      </main>
    </div>

    <div v-if="activeTab === 'tts-generator'" class="panel-shell">
      <VoiceGenerator />
    </div>

    <div v-if="activeTab === 'tts-list'" class="panel-shell">
      <GeneratedVoiceList @reuse-params="onReuseParams" />
    </div>

    <div v-if="activeTab === 'command-monitor'" class="panel-shell">
      <CommandMonitor />
    </div>

    <div v-if="activeTab === 'command-manager'" class="panel-shell">
      <CommandManager />
    </div>
  </div>
</template>

<style>
*,
*::before,
*::after {
  box-sizing: border-box;
  margin: 0;
  padding: 0;
}

:root {
  --bg: #0f1117;
  --surface: #1a1d27;
  --surface2: #242838;
  --border: #2e3348;
  --text: #e4e6f0;
  --text2: #9298b0;
  --accent: #5b8def;
  --radius: 8px;
}

html {
  font-size: 14px;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Noto Sans SC', sans-serif;
  background: var(--bg);
  color: var(--text);
  min-height: 100vh;
}

.app {
  max-width: 1300px;
  margin: 0 auto;
  padding: 20px;
}

.topbar {
  margin-bottom: 16px;
}

.topbar h1 {
  font-size: 1.6rem;
  font-weight: 700;
}

.subtitle {
  color: var(--text2);
  font-size: 0.85rem;
  margin-top: 4px;
}

.tab-bar {
  display: flex;
  gap: 2px;
  margin-bottom: 20px;
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 4px;
}

.tab-bar button {
  flex: 1;
  background: none;
  border: none;
  border-radius: 6px;
  padding: 8px 16px;
  font-size: 0.85rem;
  color: var(--text2);
  cursor: pointer;
  transition: all 0.15s;
  font-weight: 500;
}

.tab-bar button:hover {
  color: var(--text);
  background: var(--surface2);
}

.tab-bar button.active {
  background: var(--accent);
  color: #fff;
}

.layout {
  display: grid;
  grid-template-columns: 320px 1fr;
  gap: 24px;
  align-items: start;
}

.sidebar h2 {
  font-size: 0.9rem;
  color: var(--text2);
  margin-bottom: 12px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}

.main {
  min-width: 0;
}

.info-panel {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}

.info-panel h3 {
  font-size: 1.05rem;
  margin-bottom: 16px;
}

.info-section {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}

.info-section:first-of-type {
  margin-top: 0;
  padding-top: 0;
  border-top: none;
}

.info-section h4 {
  font-size: 0.95rem;
  margin-bottom: 8px;
}

.info-section p,
.info-section li {
  color: var(--text2);
  line-height: 1.6;
}

.info-section ul {
  padding-left: 18px;
}

.highlight {
  background: rgba(91, 141, 239, 0.08);
  border: 1px solid rgba(91, 141, 239, 0.22);
  border-radius: 6px;
  padding: 14px;
}

.error-card {
  margin-top: 14px;
  padding: 12px 14px;
  border-radius: 6px;
  background: rgba(229, 85, 79, 0.12);
  border: 1px solid rgba(229, 85, 79, 0.25);
  color: #ffb8b3;
}

.panel-shell {
  background: var(--surface);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 20px;
}
</style>
