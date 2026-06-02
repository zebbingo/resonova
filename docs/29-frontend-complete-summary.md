Turn-first reading note: this summary now has to be read as a turn-centric frontend story, not just a session lifecycle report.

# Resonova - 前端完善总结

> **完成时间**: 2026-05-20  
> **状态**: ✅ 前端代码已完成，等待后端 API 实现

---

## 📁 新增文件清单

### 1. Composables（组合式函数）

#### `src/composables/useMQTTSimulation.ts` (213 行)
**功能**：封装 MQTT 设备模拟的核心逻辑

**主要特性**：
- ✅ 调用后端 `/api/device/simulate` 启动模拟
- ✅ WebSocket 连接接收实时反馈
- ✅ 管理设备状态（idle/connecting/active/completed/error）
- ✅ 记录 MQTT 消息日志
- ✅ 接收 STT 识别结果和性能指标

**核心接口**：
```typescript
interface SimulationConfig {
  deviceId: string
  figurineId: string
  mode: 'dialogue' | 'story' | 'music'
  audioId: string
}

interface DeviceSimulationState {
  isOnline: boolean
  sessionId?: string
  currentTurn: number
  sentChunks: number
  status: 'idle' | 'connecting' | 'active' | 'completed' | 'error'
  errorMessage?: string
}

interface MQTTMessageLog {
  timestamp: Date
  direction: 'up' | 'down'
  topic: string
  payload?: any
  type: 'session_start' | 'audio_start' | 'chunk' | 'eos' | 'session_end' | 'stt_result' | 'other'
}
```

**使用方法**：
```typescript
const {
  isSimulating,
  state,
  logs,
  sttResult,
  startSimulation,
  stopSimulation,
} = useMQTTSimulation()

await startSimulation({
  deviceId: 'sim-dev-abc123',
  figurineId: 't-rex',
  mode: 'dialogue',
  audioId: 'intro/t-rex/long/1',
})
```

---

### 2. Components（组件）

#### `src/components/DeviceCard.vue` (596 行)
**功能**：单个设备的完整控制面板

**主要特性**：
- ✅ 角色选择下拉框（从数据库加载 21 个 figurine）
- ✅ 三种模式切换（对话/故事/音乐）
- ✅ 动态加载内容列表
  - 对话模式：显示本地测试音频
  - 故事模式：从 `/api/media/stories` 加载
  - 音乐模式：从 `/api/media/music` 加载
- ✅ 音频预览播放（点击 ▶️ 按钮）
- ✅ 启动/停止 MQTT 模拟
- ✅ 集成 SessionLog 和 MetricsPanel

**UI 结构**：
```
┌─────────────────────────────┐
│ 设备ID · 状态徽章            │
├─────────────────────────────┤
│ 🎭 角色选择                  │
│ [下拉框: 医生/霸王龙/...]    │
├─────────────────────────────┤
│ 📱 设备模式                  │
│ [💬 对话] [📖 故事] [🎵 音乐]│
├─────────────────────────────┤
│ 内容列表                     │
│ - 音频/故事/音乐项           │
│ - 每个项有 ▶️ 预览按钮       │
├─────────────────────────────┤
│ [🟢 启动 MQTT 模拟]          │
├─────────────────────────────┤
│ SessionLog 组件              │
├─────────────────────────────┤
│ MetricsPanel 组件            │
└─────────────────────────────┘
```

---

#### `src/components/SessionLog.vue` (222 行)
**功能**：展示 MQTT 消息流日志

**主要特性**：
- ✅ 实时显示上行/下行消息
- ✅ 消息类型标签（SESSION/AUDIO/CHUNK/EOS/STT）
- ✅ 时间戳精确到毫秒
- ✅ 方向指示（↑ 上行 / ↓ 下行）
- ✅ Payload 截断显示（最多 100 字符）
- ✅ 颜色编码
  - 上行消息：蓝色边框
  - 下行消息：绿色边框
  - STT 结果：橙色高亮
- ✅ 自动滚动，最多保留 100 条日志

**UI 示例**：
```
10:43:12.345 ↑ 📡 SESSION  development/sim-dev-001/request/session/sess_abc/start
               {"character":"t-rex","mode":"dialogue"}

10:43:12.456 ↑ 🎵 AUDIO    development/sim-dev-001/request/audio/sess_abc/1/start
               {"codec":"opus","sr":16000,"channels":1}

10:43:12.567 ↑ 📦 CHUNK    development/sim-dev-001/request/audio/sess_abc/1/chunk/1
               <binary data 85 bytes>

10:43:13.789 ↓ ✨ STT      STT Result
               {"text":"Hello world","metrics":{"rtf":0.012}}
```

---

#### `src/components/MetricsPanel.vue` (132 行)
**功能**：展示 STT 识别性能指标

**主要特性**：
- ✅ 会话 ID 显示
- ✅ 音频时长
- ✅ 模型加载耗时（ms）
- ✅ 识别耗时（ms）
- ✅ RTF（实时因子）- 关键性能指标
- ✅ 已发送 Chunk 数量
- ✅ RTF 说明提示

**UI 示例**：
```
📊 性能指标

会话 ID          sess_abc123
音频时长         5.23s
模型加载         142.5ms     ← 蓝色高亮
识别耗时         88.3ms      ← 蓝色高亮
RTF (实时因子)   0.012       ← 绿色高亮
已发送 Chunk     87

💡 RTF < 0.1 表示识别速度快于音频播放速度
```

---

### 3. 修改的文件

#### `src/types.ts`
**未修改** - 保持原有类型定义，新类型在 composable 中定义

#### `src/api.ts`
**已有 API** - 无需修改，已包含：
- `fetchFigurines()` - 获取角色列表
- `fetchStories(figurineId?)` - 获取故事列表
- `fetchMusic(figurineId?)` - 获取音乐列表
- `mediaStreamUrl(mediaId)` - 获取音频流 URL

#### `src/App.vue`
**重构** - 简化为单设备展示 + 使用说明

**变化**：
- ❌ 移除多设备管理逻辑
- ❌ 移除测试结果聚合
- ✅ 使用新的 DeviceCard 组件
- ✅ 添加详细的使用说明面板
- ✅ 样式优化

---

## 🎯 核心工作流程

### 用户操作流程

```
1. 打开页面
   ↓
2. 选择角色（如：霸王龙 t-rex）
   ↓
3. 选择模式（如：对话 dialogue）
   ↓
4. 选择音频（如：intro/t-rex/long/1）
   ↓
5. 点击"🟢 启动 MQTT 模拟"
   ↓
6. 后端执行：
   - 连接 MQTT Broker
   - 发布 session/start
   - 分帧上传音频（Opus 编码）
   - 发布 audio/eos + session/end
   ↓
7. Chatbot 后端处理：
   - VAD 检测
   - STT 识别
   - LLM 回复（可选）
   - TTS 合成（可选）
   ↓
8. 前端实时展示：
   - SessionLog: MQTT 消息流
   - MetricsPanel: 性能指标
   - STT 识别文本
```

### 技术架构

```
浏览器 (Vue 3)
  ↓ HTTP POST /api/device/simulate
FastAPI 后端 (resonova :8765)
  ↓ MQTT Publish
NanoMQ Broker (:1883，⚠️ Mosquitto 已弃用)
  ↓ MQTT Subscribe
Chatbot Backend (projects/chatbot/src)
  ↓ STT/VAD/LLM/TTS 处理
  ↓ WebSocket 推送
浏览器 (实时展示)
```

---

## 📦 依赖安装

已添加到 `package.json`：
```json
{
  "dependencies": {
    "axios": "^1.6.0",
    "vue": "^3.5.0"
  }
}
```

**安装命令**：
```bash
cd d:\zebbingo\projects\resonova\frontend
pnpm install
```

---

## 🚀 启动前端

```bash
# 开发模式
cd d:\zebbingo\projects\resonova\frontend
pnpm dev

# 访问地址
http://localhost:5173
```

---

## ⏳ 待完成的后端工作

前端已准备就绪，需要后端实现以下 API：

### 1. POST /api/device/simulate
**请求体**：
```json
{
  "device_id": "sim-dev-abc123",
  "figurine_id": "t-rex",
  "mode": "dialogue",
  "audio_id": "intro/t-rex/long/1",
  "test_type": "mqtt",
  "subscribe_response": true
}
```

**响应**：
```json
{
  "session_id": "sess_abc123",
  "status": "started",
  "websocket_url": "ws://localhost:8765/ws/session/sess_abc123"
}
```

**后端职责**：
1. 从数据库/缓存加载音频文件
2. 转换为 16kHz 单声道 PCM
3. Opus 编码（60ms/帧）
4. 连接 MQTT Broker
5. 按协议发布消息：
   - session/start
   - audio/start
   - audio/chunk × N
   - audio/eos
   - session/end
6. 通过 WebSocket 向前端推送日志和结果

### 2. GET /api/figurines
**响应**：
```json
{
  "figurines": [
    {
      "figurine_id": "doctor",
      "name": "Doctor Emma",
      "character_name": "医生"
    },
    ...
  ],
  "total": 21
}
```

**实现**：代理到 chatbot 项目的 `/api/figurines` 或直接查询 MySQL

### 3. GET /api/media/stories?figurine_id=xxx
**响应**：
```json
{
  "stories": [
    {
      "id": "media_123",
      "title": "小红帽",
      "description": "经典童话故事",
      "duration": 180,
      "audio_url": "https://s3.../story.mp3"
    }
  ],
  "total": 50
}
```

### 4. GET /api/media/music?figurine_id=xxx
**响应**：
```json
{
  "music": [
    {
      "id": "media_456",
      "title": "小星星",
      "artist": "儿歌",
      "duration": 120,
      "audio_url": "https://s3.../music.mp3"
    }
  ],
  "total": 30
}
```

### 5. WebSocket /ws/session/{session_id}
**推送消息格式**：
```json
// MQTT 消息日志
{
  "type": "mqtt_message",
  "direction": "up",
  "topic": "development/sim-dev-001/request/session/sess_abc/start",
  "payload": {"character": "t-rex", "mode": "dialogue"},
  "message_type": "session_start"
}

// STT 结果
{
  "type": "stt_result",
  "text": "Hello world",
  "metrics": {
    "load_ms": 142.5,
    "transcribe_ms": 88.3,
    "rtf": 0.012,
    "duration_sec": 5.23
  }
}

// 会话完成
{
  "type": "session_complete"
}
```

---

## 🎨 UI 截图预期

### 初始状态
```
┌──────────────────────────────────────────┐
│ 🎤 Resonova - MQTT 设备模拟           │
├──────────────┬───────────────────────────┤
│ 左侧：        │ 右侧：                     │
│              │                           │
│ 设备卡片      │ 🎯 使用说明                │
│ - 角色选择    │ 1️⃣ 选择角色               │
│ - 模式切换    │ 2️⃣ 选择模式               │
│ - 内容列表    │ 3️⃣ 选择内容               │
│ - 启动按钮    │ 4️⃣ 启动模拟               │
│              │ 💡 核心特点                │
│              │                           │
└──────────────┴───────────────────────────┘
```

### 运行中状态
```
┌──────────────────────────────────────────┐
│ 设备ID: sim-dev-abc123 · 🟢 活跃         │
├──────────────────────────────────────────┤
│ 📋 会话日志                               │
│ 10:43:12 ↑ SESSION  session/start       │
│ 10:43:12 ↑ AUDIO   audio/start          │
│ 10:43:12 ↑ CHUNK   chunk/1 (85 bytes)   │
│ 10:43:12 ↑ CHUNK   chunk/2 (82 bytes)   │
│ ...                                      │
├──────────────────────────────────────────┤
│ 📊 性能指标                               │
│ 音频时长: 5.23s                          │
│ 模型加载: 142.5ms                        │
│ 识别耗时: 88.3ms                         │
│ RTF: 0.012                               │
└──────────────────────────────────────────┘
```

---

## ✅ 完成检查清单

- [x] 创建 `useMQTTSimulation` composable
- [x] 创建 `DeviceCard` 组件
- [x] 创建 `SessionLog` 组件
- [x] 创建 `MetricsPanel` 组件
- [x] 更新 `App.vue` 使用新组件
- [x] 安装 axios 依赖
- [x] 编写使用说明
- [ ] 后端实现 `/api/device/simulate`
- [ ] 后端实现 WebSocket `/ws/session/{id}`
- [ ] 后端实现 MQTT Bridge 模块
- [ ] 测试完整流程

---

## 📝 下一步行动

1. **后端开发** - 按规划文档实现 MQTT Bridge 和 API
2. **联调测试** - 前后端联调，验证完整流程
3. **多设备支持** - 复制多个 DeviceCard 实现并发测试
4. **性能优化** - 优化 Opus 编码效率和内存占用
5. **错误处理** - 完善网络异常、MQTT 断连等场景

---

**文档结束**

