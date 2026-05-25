# STT 测试平台 / Voice Command 全链路测试平台

基于 sherpa-onnx SenseVoice 的语音识别测试工具，支持模拟 MQTT 设备模式，覆盖语音指令拦截全链路可观测性。

## 🚀 快速启动

### 架构说明

```
Windows (IDE + 浏览器)           WSL (Ubuntu)
┌─────────────────────────┐    ┌───────────────────────────────┐
│ 前端 (Vue 3 + TS)       │    │ 后端 (FastAPI :8765)          │
│ pnpm dev :5173           │─── │ uv run python server.py       │
│   ├─ 设备模拟管理         │    │   ├─ /api/   REST 接口        │
│   ├─ 流程可视化           │    │   ├─ /ws/    WebSocket 推送    │
│   ├─ 日志&指标面板        │    │   ├─ mqtt_bridge.py (模拟器)  │
│   ├─ 指令拦截面板 ← NEW   │    │   └─ scripts/device_firmware  │
│   └─ TTS 语音生成         │    │                               │
└─────────────────────────┘    │ chatbot/src (符号链接)         │
                                │   └─ monitoring/hook_manager  │
                                │   └─ command_intent_router    │
                                │   └─ kws_processor            │
                                │   └─ mqtt/mqtt_output         │
                                └───────────────────────────────┘
```

### 前置条件

| 环境 | 工具 | 用途 |
|------|------|------|
| **WSL** | **uv** | 管理后端 Python 依赖（fastapi, uvicorn, numpy 等） |
| **WSL** | **ffmpeg** | 音频格式转换（wav ⇄ mp3） |
| **Windows** | **pnpm** | 管理前端 JS 依赖 |

> WSL 上 `uv` 安装：`pip install uv`

### 1. 后端（WSL）— 安装依赖

```bash
wsl ~
cd /home/administrator/projects/stt-test-tool
uv sync          # 首次: 创建 .venv + 安装依赖
```

### 2. 后端（WSL）— 启动服务

```bash
wsl ~
cd /home/administrator/projects/stt-test-tool
uv run python server.py
```

后端将在 `http://localhost:8765` 启动（WSL2 自动端口转发到 Windows）。

### 3. 前端（Windows）— 启动开发服务器

```bash
cd d:\zebbingo\projects\stt-test-tool\frontend
pnpm install  # 首次需要安装依赖
pnpm dev
```

前端将在 `http://localhost:5173` 启动，通过 Vite proxy 自动代理 `/api` 和 `/ws` 到 WSL 的 `:8765`。

> 💡 **提示**：所有 Python 命令都通过 `uv run python ...` 执行，无需手动激活 `.venv`。

### 4. chatbot 监控钩子配置

测试平台的监控 WebSocket 依赖 chatbot 端主动推送埋点事件，在 chatbot `.env` 中配置：

```dotenv
# 启用监控钩子
ENABLE_MONITORING=true
MONITORING_WEBSOCKET_URL=ws://localhost:8765/ws/monitoring
```

## 📱 功能特性

### 多设备管理

支持最多 4 个设备同时测试，每个设备独立配置。

#### 设备配置
- **角色选择**: 医生、霸王龙、老师、故事大王等
- **设备模式**: 对话模式 / 故事模式 / 音乐模式
- **测试内容**: 模型测试音频 / 项目测试音频 / 预设故事/音乐

### 模拟 MQTT 设备模式

实现完整的 v1.6 协议设备端模拟：

- 设备上线/离线（含 LWT 遗嘱消息）
- 会话生命周期（start → turn → end）
- Opus 编码音频上传（turn 级 topic）
- 下行音频接收（start / chunk / eos / abort）
- 心跳维持（设备 30s + 会话 60s）
- 指令接收（command/ 含 preempt/after_audio 语义）
- OTA / 配置同步

### 语音指令拦截监控（v1.6 协议可观测性）← NEW

#### 数据流

```
chatbot 处理链                           测试平台
─────────────────                       ──────────
用户说话 → KwsProcessor ──kws_match────→ server.py:8765
        → ASR/STT                         WS /ws/monitoring
        → CommandIntentRouter                ↓
            ──command_detected────        _evaluate_and_transform_event()
        → MQTTOutputTransport                ↓
            ──mqtt_publish────────        WS /ws/monitoring/events
            (command_published)              ↓
                                      前端组件展示
```

#### 监控事件类型

| 事件类型 | 来源 | 触发时机 | 关键字段 |
|----------|------|----------|----------|
| `stt_inference` | asr 处理 | STT 识别完成 | text, duration_ms, chars_per_sec |
| `vad_speech_started/stopped` | VAD 处理 | 语音段开始/结束 | — |
| `kws_match` | KwsProcessor | KWS 命中关键词 | **keyword, command, turn_id** ← NEW |
| `command_detected` | CommandIntentRouter | 文本指令匹配 | **intent, text, cleaned, mode** ← NEW |
| `llm_inference` | 大模型 | LLM 响应完成 | tokens, duration_ms |
| `tts_synthesis` | TTS 引擎 | TTS 合成完成 | audio_duration, rtf |
| `mqtt_publish` | OutputTransport | MQTT 消息发布 | **message_type, session_id, turn_id** |
| `moderation_complete` | 审核 | 输入审核完成 | flagged, block_reasons |
| `output_moderation_complete` | 审核 | 输出审核完成 | flagged, source |
| `intro_start/end` | 开场白 | 开场白播放 | — |

#### 如何验证指令拦截

1. 启动测试平台后端 + 前端
2. 在设备管理面板添加设备 → 选择角色 → 连接
3. 用测试音频发起模拟对话
4. 在"指令拦截"面板查看实时拦截记录

或者通过真实设备说话，chatbot 处理时会自动通过监控 WebSocket 推送数据。

## 🔧 技术架构

### 后端 (FastAPI)

- **框架**: FastAPI + Uvicorn
- **STT 引擎**: sherpa-onnx (SenseVoice 模型)
- **VAD**: 简单能量阈值检测
- **端口**: 8765

#### API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/test-audios` | GET | 获取测试音频列表 |
| `/api/audio/{audio_id}` | GET | 获取音频文件 |
| `/api/stt/transcribe` | POST | 直接 STT 识别 |
| `/api/stt/vad-transcribe` | POST | VAD + STT 管道识别 |
| `/api/figurines` | GET | 角色列表 |
| `/api/figurine/{id}/tts-audios` | GET | 角色关联 TTS 音频 |
| `/api/device/connect` | POST | MQTT 设备上线 |
| `/api/device/disconnect/{id}` | POST | 设备离线 |
| `/api/device/simulate` | POST | 启动模拟 |
| `/api/device/result/{id}` | GET | 模拟结果 |
| `/api/device/history` | GET | 历史记录 |
| `/api/tts/generate` | POST | 生成 TTS 语音 |

#### WebSocket 端点

| 端点 | 方向 | 说明 |
|------|------|------|
| `/ws/monitoring` | chatbot → server | 接收 chatbot 埋点事件 |
| `/ws/monitoring/events` | server → 前端 | 广播转换后的事件 |
| `/ws/device/{id}` | server → 前端 | 设备级 MQTT 事件 |
| `/ws/session/{id}` | server → 前端 | 会话级 MQTT 事件 |
| `/ws/test` | echo | 测试 |

### 前端 (Vue 3 + TypeScript)

| 组件 | 功能 |
|------|------|
| `DeviceManager.vue` | 多设备管理 |
| `DeviceCard.vue` | 设备配置卡片 |
| `SimulationFlow.vue` | 模拟流程可视化 |
| `SessionLog.vue` | MQTT 消息日志 |
| `MetricsPanel.vue` | 实时指标面板 |
| `VoiceGenerator.vue` | TTS 语音生成 |
| `GeneratedVoiceList.vue` | 已生成语音列表 |
| **`CommandMonitor.vue`** ← NEW | **指令拦截监控面板** |

## 📊 测试结果指标

### 简单 STT
- **text**: 识别结果文本
- **duration_sec**: 音频时长（秒）
- **load_ms**: 模型加载时间（毫秒）
- **transcribe_ms**: 识别耗时（毫秒）
- **rtf**: Real-Time Factor（实时因子，越低越好）

### VAD + STT
- **total_duration_sec**: 总音频时长
- **segment_count**: 检出的语音段数量
- **segments**: 每个语音段的详细信息

### v1.6 语音指令拦截
- **kws_matches**: KWS 热词匹配数
- **command_detected**: 指令命中数
- **command_published**: 指令下发数
- **cleaned_text**: 指令剥离后的剩余文本

## 🎯 使用场景

### 1. STT 模型性能测试
测试不同语言、不同长度音频的识别准确率和速度。

### 2. VAD 管道调优
调整 VAD 参数，优化语音段切割效果。

### 3. 设备场景模拟
同时测试多设备的不同配置、不同角色、不同模式。

### 4. **语音指令拦截验证** ← NEW
- 验证 KWS 热词是否能正确触发（`kws_match` 事件）
- 验证 CommandIntentRouter 是否能准确匹配指令（`command_detected` 事件）
- 验证 MqttCommandFrame 是否能正确下发（`mqtt_publish` 事件）
- 验证混合指令（如 "你是谁 声音大一点"）的剥离效果

## 🔍 故障排查

### 后端启动失败

**问题**: `ModuleNotFoundError: No module named 'sherpa_onnx'`
**解决**: 
```bash
cd d:\zebbingo\projects\chatbot
uv sync --frozen
```

### 监控事件未显示

**问题**: 前端监控面板无数据
**解决**: 
- 确认 chatbot `.env` 中 `ENABLE_MONITORING=true` 且 `MONITORING_WEBSOCKET_URL` 指向正确的测试平台地址
- 检查 chatbot 日志是否有 `Monitoring ENABLED` 日志
- 检查 server.py 日志是否有 `MONITORING: Connection from` 日志
- 确认前端连接了 `ws://localhost:8765/ws/monitoring/events`

### 前端无法连接后端

**问题**: CORS 错误或网络请求失败
**解决**: 
- 确认后端已启动在 `http://localhost:8765`
- 确认 Vite proxy 配置正确

## 📝 开发计划

- [x] MQTT 设备模拟（多设备 + v1.6 协议）
- [x] STT 识别 + VAD 管道
- [x] TTS 语音生成
- [x] 设备/会话级 WebSocket 事件推送
- [x] 监控 WebSocket + 事件转换
- [x] 语音指令拦截全链路可观测性（KWS → Router → MQTT）
- [ ] 前端指令拦截可视化面板
- [ ] 从 MySQL 动态加载 figurine 配置
- [ ] 支持实时录音测试
- [ ] 识别结果对比功能
- [ ] 导出测试报告（CSV/JSON）
