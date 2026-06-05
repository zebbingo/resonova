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
