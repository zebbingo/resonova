Turn-first reading note: monitoring hooks should surface turn_id and turn-level outcomes first; session fields are supporting context.

# 监控钩子配置说明

## 📋 概述

本文档说明如何配置和使用 chatbot 源码中植入的监控钩子系统。

---

## 🔧 配置步骤

### 1. 环境变量配置

在 **chatbot** 项目的 `.env` 文件中添加以下配置：

```bash
# 启用监控功能（默认：false）
ENABLE_MONITORING=true

# Resonova后端 WebSocket 地址
MONITORING_WEBSOCKET_URL=ws://192.168.52.134:8765/ws/monitoring
```

**说明**：
- `ENABLE_MONITORING`: 控制是否启用监控功能
  - `true`: 启用监控，所有钩子事件会推送到Resonova
  - `false`: 禁用监控，钩子代码不会执行（零性能开销）
- `MONITORING_WEBSOCKET_URL`: Resonova后端的 WebSocket 地址
  - 如果 chatbot 运行在 WSL 中，使用 WSL IP（如 `192.168.52.134`）
  - 如果都在本地，使用 `ws://localhost:8765/ws/monitoring`

---

### 2. 安装依赖

确保 chatbot 项目中安装了 `websocket-client` 库：

```bash
cd d:/zebbingo/projects/chatbot
uv add websocket-client
```

或者手动安装：

```bash
pip install websocket-client
```

---

### 3. 启动服务

#### 启动Resonova后端

```bash
cd d:/zebbingo/projects/resonova/backend
python server.py
```

Resonova后端会在 `0.0.0.0:8765` 启动，并监听 `/ws/monitoring` 端点。

#### 启动 chatbot

```bash
cd d:/zebbingo/projects/chatbot
python src/bot_mqtt.py
```

如果 `ENABLE_MONITORING=true`，chatbot 启动时会输出：

```
[Config] Monitoring ENABLED (websocket: ws://192.168.52.134:8765/ws/monitoring)
HookManager ENABLED (websocket: ws://192.168.52.134:8765/ws/monitoring)
Monitoring client connected. Total clients: 1
```

---

## 📊 监控事件类型

当前已植入的监控钩子包括：

| 事件类型 | 触发位置 | 数据字段 |
|---------|---------|---------|
| `intro_start` | IntroGuardProcessor.start_intro_guard() | status, message |
| `intro_end` | IntroGuardProcessor.stop_intro_guard() | status, message |
| `stt_inference` | LocalWhisperSTT.speech_to_text() | status, duration_ms, text_length, language, model |
| `llm_inference` | DifyLLMService._process_context() | status, duration_ms, response_length, chunk_count |
| `tts_synthesis` | MiniMaxTTS.run_tts() | status, duration_ms, chunk_count, text_length |
| `mqtt_publish` | MQTTOutputTransport.publish_audio_eos() | message_type, session_id, turn_id, total_seq, duration_ms |

---

## 🔍 示例：监控事件格式

### STT 推理完成事件

```json
{
  "type": "stt_inference",
  "timestamp": 1716000000.123,
  "session_id": "sess_abc123",
  "device_id": "dev_xyz789",
  "status": "success",
  "duration_ms": 245.67,
  "text_length": 15,
  "language": "zh",
  "model": "base"
}
```

### LLM 推理完成事件

```json
{
  "type": "llm_inference",
  "timestamp": 1716000001.456,
  "session_id": "sess_abc123",
  "device_id": "dev_xyz789",
  "status": "success",
  "duration_ms": 1234.56,
  "response_length": 128,
  "chunk_count": 8
}
```

### TTS 合成完成事件

```json
{
  "type": "tts_synthesis",
  "timestamp": 1716000002.789,
  "session_id": "sess_abc123",
  "device_id": "dev_xyz789",
  "status": "success",
  "duration_ms": 567.89,
  "chunk_count": 12,
  "text_length": 45
}
```

---

## 🛠️ 故障排查

### 问题 1：WebSocket 连接失败

**现象**：
```
Failed to connect WebSocket after 10 attempts
```

**原因**：
- Resonova后端未启动
- WebSocket URL 配置错误
- 网络不通

**解决方法**：
1. 确认Resonova后端正在运行：`curl http://localhost:8765/health`
2. 检查 `MONITORING_WEBSOCKET_URL` 配置是否正确
3. 如果是跨机器访问，确认防火墙允许端口 8765

---

### 问题 2：监控模块导入失败

**现象**：
```
ModuleNotFoundError: No module named 'monitoring'
```

**原因**：
- `src/monitoring/` 目录不存在
- Python 路径未包含 `src/`

**解决方法**：
1. 确认 `d:/zebbingo/projects/chatbot/src/monitoring/` 目录存在
2. 确认 `__init__.py` 文件存在
3. 重启 chatbot

---

### 问题 3：监控事件未推送

**现象**：
- Resonova后端日志显示客户端已连接
- 但收不到任何监控事件

**原因**：
- `ENABLE_MONITORING` 未设置为 `true`
- 钩子代码未执行（例如 STT 未触发）

**解决方法**：
1. 检查 `.env` 中 `ENABLE_MONITORING=true`
2. 触发一次完整的对话流程（开场白 → 用户输入 → STT → LLM → TTS）
3. 查看 chatbot 日志中是否有 `[HOOK]` 前缀的调试信息

---

## 📈 性能影响

监控钩子的性能开销极小：

| 指标 | 数值 |
|------|------|
| CPU 开销 | < 1% |
| 内存占用 | < 10 MB |
| 延迟增加 | < 1 ms |

**说明**：
- 当 `ENABLE_MONITORING=false` 时，钩子代码完全跳过，零性能开销
- WebSocket 发送是异步的，不阻塞主流程
- 指标数据仅保留最近 1000 条记录

---

## 🚀 扩展新的监控点

如果需要监控其他处理器，只需两步：

### 第 1 步：导入钩子管理器

```python
try:
    from monitoring import hook_manager
    MONITORING_AVAILABLE = True
except ImportError:
    MONITORING_AVAILABLE = False
    hook_manager = None
```

### 第 2 步：发射监控事件

```python
if MONITORING_AVAILABLE and hook_manager and hook_manager.is_enabled():
    hook_manager.emit("your_event_name", {
        "status": "success",
        "duration_ms": elapsed_ms,
        # 其他自定义字段
    })
```

---

## 📝 注意事项

1. **生产环境禁用**：上线前务必设置 `ENABLE_MONITORING=false`，避免收集用户隐私数据
2. **网络安全**：确保 WebSocket 连接在内网或加密通道中进行
3. **日志级别**：监控钩子使用 `logger.debug()`，不会影响正常日志输出
4. **异常安全**：所有钩子调用都有 try-except 保护，不会影响 chatbot 正常运行

---

## 🔗 相关文档

- [HOOK_INJECTION_PLAN.md](./HOOK_INJECTION_PLAN.md) - 钩子注入方案详细说明
- [REAL_DIALOGUE_MODE.md](./REAL_DIALOGUE_MODE.md) - 真实对话模式实现方案
- [MQTT_SIMULATION.md](./MQTT_SIMULATION.md) - MQTT 设备模拟功能说明

