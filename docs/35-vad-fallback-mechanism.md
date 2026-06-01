# VAD Fallback 机制

> 文档编号: 35 | 更新日期: 2026-06-01  
> 范围: Resonova 测试平台

---

## 背景

全链路测试发现模拟音频（如 `mqtt_vad_capture_input.wav`）无法触发服务端
SileroVAD 的语音检测，导致 STT 管道空转：

| 模式 | STD 结果 | TTS 响应 | 根因 |
|------|----------|----------|------|
| VAD（默认） | 空 | 0 | SileroVAD 置信度 0.8，模拟音频达不到语音门槛 |
| EOS（绕过 VAD） | "Can you speak Chinese." | 319 chunks | 设备端直接发 audio/eos 触发 STT |

VAD Fallback 机制让模拟流程**自动感知** VAD 阻塞并标记结果，前端/用户据此决定
是否需要切换到 EOS 模式。

---

## 实现方案

### 1. 请求层：`bypass_vad` 参数

```python
# server.py - SimulateRequest
class SimulateRequest(BaseModel):
    ...
    bypass_vad: bool = False   # 新增
```

前端调用时可设 `bypass_vad=True`，模拟结果会标记 `vad_bypassed: true`，
表示本次模拟使用了 EOS 模式绕过 VAD。

### 2. 追踪层：`_vad_bypassed` 字典

```python
# mqtt_bridge.py - SimulationManager
class SimulationManager:
    def __init__(self):
        ...
        self._vad_bypassed: dict[str, bool] = {}  # session_id → bypass flag
```

调用链：

```
start_device_simulation()          # server.py
  → 设置 bypass_vad=True
  → simulation_manager._vad_bypassed[session_id] = True
  → simulation_manager.start_simulation(...)
```

### 3. 输出层：结果端点自动注入

所有结果读取路径都会自动注入 `vad_bypassed` 字段：

| 端点 | 注入方式 |
|------|----------|
| `GET /api/device/result/{id}` | `get_result()` 从 `_vad_bypassed` 读取 |
| `GET /api/device/history` | `get_history()` 遍历结果时批量注入 |
| `GET /api/device/compare` | server.py 对比端点逐条注入 |

### 4. 检测层：`vad_blocked` 自动诊断

history / compare 端点自动判断 VAD 阻塞：

```python
vad_blocked = (
    not stt_text
    and not vad_bypassed
    and tts_response_count == 0
)
```

判定逻辑：

| `stt_text` | `vad_bypassed` | `tts_response_count` | `vad_blocked` |
|------------|----------------|----------------------|---------------|
| 空 | false | 0 | **true** ← VAD 可能阻塞 |
| 非空 | — | — | false |
| 空 | **true** | — | false ← 已绕过 |
| 空 | false | **>0** | false ← TTS 在跑，只是 STT 慢 |

---

## 使用方式

### 绕过 VAD 测试（推荐调试用）

```bash
curl -X POST http://localhost:8765/api/device/simulate \
  -H "Content-Type: application/json" \
  -d '{
    "device_id": "sim-dev-001",
    "figurine_id": "doctor",
    "mode": "dialogue",
    "subscribe_response": true,
    "bypass_vad": true,
    "audio_id": "/path/to/test.wav"
  }'
```

响应包含：

```json
{
  "session_id": "...",
  "bypass_vad": true,
  ...
}
```

### 检查结果

```bash
curl -s http://localhost:8765/api/device/history?limit=1 | jq
```

每条记录包含：

```json
{
  "session_id": "...",
  "stt_text": "Can you speak Chinese.",
  "vad_bypassed": true,
  "vad_blocked": false
}
```

---

## 代码清单

| 文件 | 改动 | 目的 |
|------|------|------|
| `server.py` | `SimulateRequest.bypass_vad` 字段 | API 请求参数 |
| `server.py` | `start_device_simulation()` 设置 `_vad_bypassed` | 存储绕过标记 |
| `server.py` | history/compare 端点 `vad_blocked` 检测 | 自动诊断 VAD 阻塞 |
| `server.py` | history/compare 端点 `vad_bypassed` 输出 | 前端展示 |
| `mqtt_bridge.py` | `SimulationManager._vad_bypassed` | 追踪层存储 |
| `mqtt_bridge.py` | `get_result()` 注入 `vad_bypassed` | 单条结果端点 |
| `mqtt_bridge.py` | `get_history()` 批量注入 `vad_bypassed` | 历史列表端点 |

---

## 局限与后续

| 局限 | 说明 |
|------|------|
| 当前是追踪层，非自动切换 | bypass_vad 仅为标记，需用户/前端手动关联 MQTT profile 切换 |
| 无自动重试 | 若第一次模拟 `vad_blocked=true`，不会自动重试 EOS 模式 |
| 前端集成待完成 | 前端 `vad_blocked` 字段已就绪，UI 提示逻辑待实现 |

如需完全自动化，后续可：

1. 在 `start_device_simulation()` 中检测 `vad_blocked` 条件
2. 自动调用 profile 切换 API 重启 chatbot
3. 重试模拟
