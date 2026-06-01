# VAD Fallback — 代码评审报告

> 生成日期: 2026-06-01  
> 评审范围: commits `99a9be0` + `6ee6eb1`  
> 涉及文件: 9 files changed, 214 insertions(+), 22 deletions(-)

---

## 一、改动总览

| 提交 | 信息 | 文件 | 行数 |
|------|------|------|------|
| `99a9be0` | feat: VAD fallback - add bypass_vad to SimulateRequest | 7 | +42/-18 |
| `6ee6eb1` | feat: VAD fallback tracking layer + documentation | 4 | +172/-4 |

## 二、API 变更

### 请求层

```python
# server.py SimulateRequest
- (无)
+ bypass_vad: bool = False
```

### 响应层

4 个端点新增 `vad_bypassed` 字段：

| 端点 | 新增字段 |
|------|----------|
| `POST /api/device/simulate` | 响应体 `bypass_vad` |
| `GET /api/device/result/{id}` | `result.vad_bypassed` |
| `GET /api/device/history` | `records[].vad_bypassed` |
| `GET /api/device/compare` | `rows[].vad_bypassed` + `vad_blocked` |

## 三、核心逻辑

```
SimulateRequest.bypass_vad
  → server.py: simulation_manager._vad_bypassed[session_id] = True
  → mqtt_bridge.py:
      get_result()  → 注入 vad_bypassed
      get_history() → 批量注入 vad_bypassed
  → server.py:
      history/compare 端点自动计算 vad_blocked
```

## 四、风险分析

| 等级 | 风险项 | 说明 |
|------|--------|------|
| HIGH | 无 | 全部为新增字段/参数，不修改既有行为 |
| MEDIUM | `_vad_bypassed` 生命周期 | 调用 `clear_history()` 时不清空该字典，导致旧 session_id 残留。需追加 `clear_history()` 也清理 `_vad_bypassed` |
| LOW | `get_result()` 副作用 | 现在在返回的 dict 上原地注入 `vad_bypassed`，调用者预料外的新字段可能导致序列化差异 |
| LOW | Profile 配置默认值 | `CHATBOT_MQTT_HANDLE_VAD_ON_SERVER` 在 local profile 里设为 `false`，cloud profile 为 `true`，与原先的 profile 切换行为一致 |

## 五、评审意见

1. **建议修复**: `clear_history()` 未清理 `_vad_bypassed` — 追加
2. **建议补充**: docs/35 缺少多 AI 协作场景下的说明（多个 AI 同时操作 bypass_vad，最后一个覆盖前一个）
3. **建议测试**: 并发场景下 `_vad_bypassed` 的线程安全性（当前 RLock 保护有遗漏）

## 六、diff 详情

```
--- a/backend/server.py +++ b/backend/server.py
  + bypass_vad: bool = False (SimulateRequest)
  + if req.bypass_vad: simulation_manager._vad_bypassed[session_id] = True
  + history/compare endpoints vad_blocked auto-detection
  + local profile CHATBOT_MQTT_HANDLE_VAD_ON_SERVER=false
  + cloud profile CHATBOT_MQTT_HANDLE_VAD_ON_SERVER=true

--- a/backend/mqtt_bridge.py +++ b/backend/mqtt_bridge.py
  + SimulationResult.vad_bypassed: bool = False
  + SimulationResult.vad_blocked_warning: str = ""
  + SimulationManager._vad_bypassed: dict[str, bool]
  + get_result() 注入 vad_bypassed
  + get_history() 批量注入 vad_bypassed
```
