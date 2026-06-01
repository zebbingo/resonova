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

## 多 AI 协作注意事项

> 当前项目由多个 AI 代理并行协作开发。VAD Fallback 的追踪层需要考虑以下场景：

### 1. `_vad_bypassed` 写入无锁保护

```python
# server.py — start_device_simulation()
if req.bypass_vad:
    simulation_manager._vad_bypassed[session_id] = True  # ⚠️ 无锁访问
```

**问题**：多 AI 同时调用 simulate 时，dict 写入不在 `manager._lock` 保护范围内，
理论上存在竞态条件。虽 Python dict 的 key 赋值是原子的，但不保证跨线程可见性。

**规避**：当前写入与 `start_simulation()` 调用在同一线程（FastAPI 请求处理线程），
且 `start_simulation()` 在内部使用 `self._lock` 保护状态变更，故实际风险极低。
后续如需严格保护，可将写入移至 `start_simulation()` 内部。

### 2. `_vad_bypassed` 不持久化

```python
# 服务重启后
simulation_manager._vad_bypassed = {}  # 清空
```

**问题**：`_vad_bypassed` 仅存内存，不写入 `simulation_history.json`。
服务器重启后，历史记录的 `vad_bypassed` 标记全部丢失。

**影响**：低。因为 `vad_blocked` 在 history 端点是实时计算的，即便 `vad_bypassed` 丢失，
`vad_blocked` 也能根据 `stt_text` + `tts_response_count` 重新推导。

### 3. `clear_history()` 未清理 `_vad_bypassed`（已修复 `cd71be4`）

⚠️ 这是已发现的 bug — `clear_history()` 虽然清空了 `_results`，
但没有清空 `_vad_bypassed`，导致残留的 session_id 仍返回 True。

**修复**：`commit cd71be4` 在 `clear_history()` 中追加 `self._vad_bypassed.clear()`。

### 4. 多 AI 绕过策略覆盖

当 AI-A 以 `bypass_vad=false` 发起模拟（session A），
AI-B 以 `bypass_vad=true` 发起模拟（session B）时，
各自的 `_vad_bypassed` 记录互不干扰（以 session_id 为 key）。

**但若使用相同 session_id 重试**，后一个会覆盖前一个的 `vad_bypassed` 标记。
这是预期行为 — 最终结果反映的是最近一次运行的实际配置。

### 5. 线程安全性

| 访问路径 | 锁保护 | 风险 |
|----------|--------|------|
| `server.py` 写入 `_vad_bypassed` | ❌ 无 | 极低，dict key 赋值原子，同线程 |
| `get_result()` 读取 `_vad_bypassed` | ✅ `self._lock` | 无 |
| `get_history()` 读取 `_vad_bypassed` | ❌ 锁外 | 低，锁在 `all_results` 排序时已释放，后续只读 |
| `clear_history()` 清空 `_vad_bypassed` | ✅ `self._lock` | 无 |

---

## 后续路线

如需完全自动化，后续可：

1. 在 `start_device_simulation()` 中检测 `vad_blocked` 条件
2. 自动调用 profile 切换 API 重启 chatbot
3. 重试模拟
4. 将 `_vad_bypassed` 持久化到 `simulation_history.json`
5. 在 `cleanup_orphan_sessions()` 中同步清理 `_vad_bypassed`
