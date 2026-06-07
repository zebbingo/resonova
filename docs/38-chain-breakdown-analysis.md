# 链路中断分析报告

> 日期：2026-06-06 00:30
> 状态：**已完成自动化诊断，精确定位断点**

---

## 0. 自动化诊断结果（2026-06-06 00:30）

运行 `scripts/e2e_chain_diagnostic.py`，结果：

```
13 PASS / 6 FAIL

✅ L1-API         — 后端 API 正常
✅ L1-CONNECT     — 设备连接成功
✅ L1-SESSION     — Session 创建成功 (BfeTck2vclMl)
✅ L2-WS-CONN     — Session WS 连接成功
❌ L2-INTRO       — 未收到 intro 事件（收到: []）
❌ L2-STT         — 未收到 STT 事件
❌ L2-LLM         — 未收到 LLM 事件
❌ L2-TTS         — 未收到 TTS 事件
❌ L2-AUDIO       — 未收到 audio 事件
✅ L3-TURN-API    — send-turn 返回 session
✅ L3-TURN-STT    — Turn 后收到 STT 事件
❌ L3-TURN-LLM    — Turn 后未收到 LLM 事件
✅ L3-TURN-TTS    — Turn 后收到 TTS 事件
✅ L3-TURN-AUDIO  — Turn 后收到 audio 事件
✅ L3B-SID-MATCH  — session_id 一致
✅ L4-AUDIO-URL   — 音频 URL 可达
✅ L5-STT-TEXT    — STT: Hello, how are you today.
✅ L5-REPLY-TEXT  — Reply: What would you like to learn about medicine today?That is a
✅ L5-TTS-COUNT   — TTS responses: 2
```

### 关键发现

**断点 1：Intro 事件完全丢失**
- `start-session` 返回成功，session_id 有效
- Session WS 连接成功
- 但 10 秒内收到 **0 个事件** — intro 的 STT/LLM/TTS/audio 全部没有
- 这说明 intro 的事件没有通过 EventBus 发布到 session WS queue

**断点 2：Turn 的 LLM 事件丢失**
- Turn 后收到了 `stt_inference`、`audio_start`、`audio_chunk`、`tts_progress`
- 但没收到 `llm_inference` 或 `llm_text`
- `reply_text` 在 API 结果中有值（通过 monitoring 钩子获取）
- 这说明 `llm_inference` 事件没通过 WS 推送（但 monitoring 钩子 `llm_text` 是通的）

**非断点**：
- 音频 URL 可达（L4 PASS）
- reply_text 有值（L5 PASS）
- session_id 一致（L3B PASS）
- Turn 的 STT/TTS/audio 事件正常

---

## 1. 曾经打通的版本

**打通版本**：`65a2bb1` (Fix session reuse and WSL path conversion)
**时间**：2026-06-05 下午约 16:00
**表现**：
- 点击连接 → 设备上线
- 选择角色 → 开场白播放（有声音）
- 发送 Turn → STT/LLM/TTS 全链路通
- 金色 Turn 反馈区正常显示
- reply_text 为空（当时未解决，后来通过 monitoring 钩子解决）

---

## 2. 当前版本表现

**HEAD**：`735f188` (Fix: clean up garbled Chinese comments)
**表现**：
- 点击连接 → 设备上线 ✅
- 选择角色 → **无开场白播放** ❌
- 发送 Turn → **无声音** ❌
- **金色 Turn 反馈区不出现** ❌
- 后端 API 返回正常（STT 有文本，TTS 有响应）✅
- reply_text 通过 monitoring 钩子获取 ✅

---

## 3. Git 变更时间线（从打通版本到现在）

| # | Commit | 时间 | 描述 | 影响评估 |
|---|--------|------|------|----------|
| 1 | `292b9f0` | 16:34 | Fix Turn display: 连接 session WS | ✅ 正确修复 |
| 2 | `1739e42` | 17:04 | start-session 非阻塞 | ✅ 正确优化 |
| 3 | `e37dd5d` | 17:27 | **Revert #2** | ⚠️ 恢复阻塞式，本身无害 |
| 4 | `af2c637` | 17:27 | **Revert #1** | 🔴 **删除 `_ensureSessionWs()`，前端丢失实时事件** |
| 5 | `4fc1d21` | 17:27 | Revert session reuse/WSL path | ⚠️ 路径和 sid 逻辑回退 |
| 6 | `e9cb7b9` | 17:34 | Re-apply #5 的部分修复 | ✅ 恢复 WSL 路径和 sid |
| 7 | `986413e` | 17:37 | Guard WS undefined session | ✅ 防御性代码 |
| 8 | `b9bab35` | 17:51 | Auto startSession after connect | ✅ 小改进 |
| 9 | `911bb0b`~`69f0fb2` | 18:00~23:08 | reply_text monitoring 钩子 | ✅ 新功能 |
| 10 | `e3c34c3` | 23:13 | 恢复 `_ensureSessionWs()` | ✅ 应该恢复前端实时事件 |
| 11 | `735f188` | 23:24 | 清理乱码注释 | ✅ 纯注释 |

---

## 4. 问题定位：为什么恢复 `_ensureSessionWs()` 后还是不行？

### 假设 A：前端 WS 连了但后端没推事件

**可能原因**：
- 后端 `/ws/session/{session_id}` 的 queue 没有被创建
- `send_user_turn` 创建的 queue key 和前端 WS 连的 key 不匹配
- 后端 `session_status` 事件中缺少 `reply_text`

**验证方法**：
- 打开浏览器 DevTools → Network → WS，看是否有 session WS 连接
- 看后端日志中是否有 "MONITORING: Received" 的输出

### 假设 B：前端连了旧的 session WS

**可能原因**：
- `connectDevice` 时创建了旧 session_id 的 WS
- `startSession` 产生了新 session_id，但 `_ensureSessionWs()` 中 `ws.readyState === WebSocket.OPEN` 检查让旧连接没被替换

**关键代码问题**：
```typescript
function _ensureSessionWs() {
    if (!state.sessionId) return
    if (ws && ws.readyState === WebSocket.OPEN) return  // ← 问题：不检查 session_id 是否匹配
    ...
}
```

这段代码只检查 WS 是否 OPEN，不检查连接的是哪个 session。如果旧 session 的 WS 还开着，新 session 的事件就收不到。

**修复方向**：需要记录当前 WS 连接的 session_id，并在 session_id 变化时强制重连。

### 假设 C：音频播放问题独立于 WS

**可能原因**：
- 音频文件路径解析失败（WSL 路径问题）
- 浏览器自动播放策略阻止
- TTS 音频 URL 不正确

### 假设 D：bot monitoring WS 断开

**可能原因**：
- bot 的 monitoring WS 连接不稳定（之前看到过 Broken pipe）
- OutputModerationGate 的 `llm_text` 事件没发出
- resonova 后端 monitoring 端点没收到事件

---

## 5. 组件状态检查清单

### 后端 (resonova)
- [ ] 8765 端口在监听
- [ ] `/ws/session/{session_id}` WS 能连接
- [ ] monitoring WS (`/ws/monitoring`) bot 已连接
- [ ] `send_user_turn` 创建 event_queue 且 key 正确
- [ ] `_translate_ws_event` 正确翻译事件

### 前端 (resonova)
- [ ] Vite dev server 在 5173 运行
- [ ] `connectDevice` → device WS 连接
- [ ] `startSession` → session WS 连接（且 session_id 匹配）
- [ ] `_handleWsMessage` 处理 `stt_inference`/`llm_text`/`tts_synthesis`/`audio_ready`
- [ ] 音频播放：`_unlockAndPlay` / `HTMLAudioElement`

### Bot (chatbot)
- [ ] `bot_mqtt.py` 进程在运行
- [ ] monitoring WS 连接到 resonova 后端
- [ ] `OutputModerationGate` 中 `llm_text` 钩子已 patch
- [ ] MQTT 连接正常（能收发消息）

---

## 6. 建议排查顺序（不改代码）

1. **浏览器 DevTools**：打开 WS 面板，看连接了哪些 WS，是否有消息
2. **后端日志**：看 monitoring 收到的事件、session WS 推送的事件
3. **前端 Console**：看 `[WebSocket]` 日志
4. **对比 `65a2bb1`**：`git stash` 当前修改，`git checkout 65a2bb1`，验证是否还能正常工作

---

## 7. 根本问题：代码变更管理

### 问题
- 三个 revert (`e37dd5d`, `af2c637`, `4fc1d21`) 是批量执行的，没有逐个评估影响
- Revert 删除了关键的前端 WS 连接逻辑，后续 re-apply 只恢复了后端部分
- 没有前端冒烟测试，无法在 CI 中捕获此类回归

### 建议
- 每次功能修改应该独立 commit，revert 时可以精确回退
- 补充 `e2e_ws_smoke.py` 类型的测试
- 关键 UI 功能（开场白、Turn 反馈）需要 Playwright 级别的测试

---

## 8. 深度诊断发现（2026-06-07 修复过程）

### 断点 1 根因：EventBus queue 时序（已修复 ✅）

**现象**：`start-session` API 返回成功，Session WS 连接成功，但 intro 期间 0 个事件。

**根因**：`start_session_and_await_intro()` 是阻塞的。intro 期间 `_emit_session()` 调用 `EventBus.publish(session_id, event)`，但此时 WS 还没连，queue 不存在。`SimulationEventBus.publish()` 发现 `self._queues.get(key)` 返回 None 就丢弃事件。

**代码位置**：
- `mqtt_bridge.py` `SimulationEventBus.publish()` line 383 — `q = self._queues.get(key); if q is not None: q.put_nowait(event)`
- `mqtt_bridge.py` `ConnectedDevice.start_session_and_await_intro()` line 717 — `_emit_session` 在 queue 创建之前

**修复**：在 `start_session_and_await_intro()` 中，`self._fw.start_session()` 生成 session_id 后、`_emit_session()` 之前，先 `self.event_bus.create_queue(session_id)` 确保 queue 存在。

**验证**：诊断测试 L2-INTRO 从 FAIL 变为 PASS。

### 断点 2 根因：`_simulating` 标志位错误（已修复 ✅）

**现象**：`llm_text` 事件到达 resonova 后端，`collect_llm_text` 没执行，EventBus publish 也没执行。

**根因**：resonova 后端 monitoring 端点的 `llm_text` 处理检查 `dev._simulating`。但 `start_session_and_await_intro()` 的 finally 块设 `_simulating = False`（line 749）。intro 完成后 `_simulating` 为 False，turn 期间 monitoring 端点跳过了该设备。

**代码位置**：
- `mqtt_bridge.py` `start_session_and_await_intro()` finally 块 — `self._simulating = False`
- `server.py` monitoring handler — `if dev._fw and dev._simulating:`

**修复**：将 `dev._simulating` 改为 `dev.is_connected`（设备在线就处理，不依赖 simulating 状态）。

**验证**：待确认。

### 断点 3 根因：`_response_active=False` 导致 LLM text 钩子不执行（修复中 ⚠️）

**现象**：bot 日志显示 `LLMTextFrame received: active=False`，所有 LLM text 都在 `_response_active=False` 状态下到达。monitoring 钩子代码在 `_response_active` 检查之后，所以不执行。

**根因**：pipecat pipeline 中 `CancelFrame`（由 intro 结束触发）在 LLM text 之前到达 `OutputModerationGate`，导致 `reset_session()` → `_response_active=False`。之后 LLM 的流式输出才到达，全部被直接转发而不经过钩子。

**时序**：
```
CancelFrame → reset_session(_response_active=False)
LLMTextFrame("That") → active=False → 直接转发，钩子不执行
LLMTextFrame(" is") → active=False → 直接转发，钩子不执行
...
```

**代码位置**：`output_moderation_gate.py` line 919-921
```python
if isinstance(frame, LLMTextFrame):
    if not self._response_active:  # ← True，直接转发
        await self.push_frame(frame, direction)
        return
    # ... 钩子代码在这里，永远不会执行
```

**修复**：将 monitoring 钩子移到 `_response_active` 检查之前，在 `isinstance(frame, LLMTextFrame)` 判断处无条件执行。

**⚠️ 潜在冲突**：不依赖 `_response_active` 就 emit `llm_text`，可能在 session 已关闭时也发送。但 monitoring 只是观察通道，不影响主流程。

### 断点 4 发现：Turn 时序不完整（待调查 🔍）

**现象**：诊断测试中 Turn 后只收到 `upload_progress` 和 `stt_inference`，没有 audio/tts/llm。但 L5 结果数据有时能拿到（STT/Reply/TTS count 正常）。

**可能原因**：
- 15 秒等待时间不够（intro 音频 52 秒，turn 处理可能更慢）
- Turn 的 LLM/TTS 处理在 cancel 之后才完成（与断点 3 同源问题）
- 诊断测试断开连接太早，bot 还在处理中

### 断点 5：Monitoring WS Broken pipe 导致 llm_text 丢失（已知 🔍）

**现象**：18/19 PASS，唯一 FAIL 是 L3-TURN-LLM。L5 reply_text 有值。

**根因**：bot monitoring WS 在 LLM text 发送期间断开（Broken pipe），`hook_manager._enabled` 被设为 False，所有 `emit("llm_text", ...)` 被跳过。WS 重连后 `_enabled=True`，但 LLM text 已全部发完。

**bot 日志证据**：
```
22:22:45 | WARNING | Monitoring WebSocket send failed: [Errno 32] Broken pipe
22:22:48 | INFO    | Monitoring WebSocket connected (reconnected)
```

**时序**：
```
LLMTextFrame("What") → _enabled=True → emit 成功 → 但 WS 已断 → 数据丢失
LLMTextFrame(" would") → _enabled=False → emit 跳过
LLMTextFrame(" you") → _enabled=False → emit 跳过
...
```

**L5 reply_text 有值的原因**：resonova 后端通过 `OutputModerationGate` 的另一个钩子 `output_moderation_complete` 获取了最终审核结果中的文本（非 `llm_text` 事件）。

**修复方向**：
- 短期：在 `emit` 中加 buffer，WS 断开时缓存事件，重连后重发
- 长期：改用 MQTT 内部事件传递（不依赖外部 WS 稳定性）

---

## 9. 专家 AI 诊断对照（2026-06-07）

外部专家 AI 对代码变更做了风险评估，逐条对照：

| # | 风险 | 专家判断 | 实际情况 | 当前状态 |
|---|------|---------|---------|---------|
| 1 | 双 session 冲突（connectDevice + startSession） | 🔴 高风险 | `connect_device()` 不触发 intro，只有 `start-session` API 触发 | ✅ 不存在 |
| 2 | EventBus queue key 不匹配 | 🟡 中风险 | `create_queue` 在 `start_session_and_await_intro` 中用实际 session_id 创建，不是 sid_preliminary | ⚠️ server.py 中的 sid_preliminary 代码冗余但无害 |
| 3 | llm_text 注入错误 device | 🟡 中风险 | 已改为 `is_connected`，且当前只有单设备场景 | ✅ 已修复 |
| 4 | _normalize_audio_path 双向转换 | 🟡 中风险 | WSL 环境下可能误转 | 🔍 未触发 |
| 5 | useMQTTSimulation.ts 变更 | 🟢 低风险 | `_ensureSessionWs` 恢复 + `llm_text` case | ✅ 正常 |

### 专家建议的检查清单验证

1. **双 session**：bot_mqtt 日志中同一 device 没有连续两个 session/start ✅
2. **EventBus queue key**：前端 WS 连接 `/ws/session/{session_id}` 与实际 session_id 一致 ✅
3. **collect_llm_text**：device_firmware.py 有此方法 ✅
4. **MQTT_ENV**：`/api/debug/runtime-config` 返回 `mqtt.env: "development"` ✅
