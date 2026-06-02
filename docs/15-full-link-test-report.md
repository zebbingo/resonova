Turn-first reading note: this report should be read by turn completion, not only session creation. A passing result means a turn completes with STT / reply / command output.

# 全链路模拟测试报告

> 日期: 2026-05-29 | 测试脚本: `backend/scripts/full_link_test.py` | Resonova: resonova (port 8765)

---

## 测试结果总览

| 步骤 | 状态 | 说明 |
|:-----|:----:|:-----|
| 1. 设备连接 | ✅ PASS | sim-dev-003 成功连接本地 MQTT (localhost:1883) |
| 2. 设备列表 | ✅ PASS | 返回 2 个设备，状态正确 |
| 3. 启动模拟 | ✅ PASS | session 创建成功，返回 session_id |
| 4. 监控轮询 (120s) | ⚠️ 超时 | 未收到任何模拟事件，全量超时 |
| 5. 获取结果 | ❌ FAIL | status=orphan_cleaned, total_chunks=0 |
| 6. 历史记录 | ✅ PASS | 可查历史，但包含大量失败记录 |

**核心结论：全链路未打通。** 模拟 session 能创建但音频未发送（total_chunks=0），即使少量成功发送了音频的 session 也收不到 STT/TTS 响应。

---

## 问题一：模拟引擎竞态条件 🔴 CRITICAL

### 现象
多个测试 session 出现 `status: "orphan_cleaned"`（即从未从 "pending" 状态更新），且 `total_chunks: 0`。

### 根因分析
服务器日志显示关键错误：

```
ERROR:mqtt_bridge:Simulation failed: Device sim-dev-003 already has an active session
  File "mqtt_bridge.py:1287", in _run
    result = dev.run_session(...)
  File "mqtt_bridge.py:754", in run_session
    raise ValueError(f"Device {self.device_id} already has an active session")
```

**触发条件：** 当第一次模拟还在运行时，发送第二次 `/api/device/simulate` 请求。

**竞态时间线：**
1. 第一次模拟的 `run_simulation()` 创建后台线程 A，`_simulating = True`
2. 第二次模拟到达 `start_simulation()`，检测到 `_simulating = True`
3. 调用 `dev.stop_current_session()` + 设置 `_simulating = False`
4. 第二次模拟的 `run_simulation()` 创建后台线程 B
5. 但线程 A 的 `finally` 块也设置了 `_simulating = False`（此时已为 False）
6. 线程 B 进入 `run_session()`，检查 `_simulating`，**此时可能为 True**（如果线程 A 尚未释放锁/finally 执行完毕）
7. 抛出 ValueError → 模拟失败 → result 停留在 "pending" → 300s 后被清理为 "orphan_cleaned"

### 影响
- 用户看到模拟成功启动（API 返回 200），但实际后台默默失败
- 失败的模拟不产生任何用户可见的错误提示
- 连续跑测试时失败率极高

### 修复方案
在 `start_simulation()` 中更可靠地等待旧线程退出再启动新模拟：

```python
# 在 run_simulation() 中，添加线程等待逻辑
if dev and dev.is_simulating:
    dev.stop_current_session()
    dev._simulating = False
    dev._stop_requested = False
    # 等待旧线程完全退出
    old_thread = self._threads.get(device_id)
    if old_thread and old_thread.is_alive():
        old_thread.join(timeout=30)
```

---

## 问题二：ASR/LLM/TTS 管道始终超时 🔴 CRITICAL

### 现象
所有成功发送了音频的 session，输出均为：

```
INFO:mqtt_bridge:Turn 1 response: timeout
```

具体表现为：
- 762 chunks, 45680ms 音频通过 MQTT 成功发送
- 等待 `wait_for_turn_response()` 90s 超时
- `stt_text: ""`（始终为空）
- `tts_response_count: 0`（无 TTS 响应）
- `reply_text: ""`（无回复文本）

### 成功发送的 session 列表（均有 TTS timeout）

| Session ID | Chunks | 音频时长 | 结果 |
|:-----------|:------:|:--------:|:----:|
| 6L28YJ1xSAoA | 762 | 45.68s | timeout |
| jV10xb_lNzcV | 762 | 45.68s | timeout |
| SbMgEi40Tuwn | 762 | 45.68s | timeout |
| I4oXImlCC_CM | 762 | 45.68s | timeout |
| SY2W_MeOW9Qx | 762 | 45.68s | timeout |

### 根因分析（已确认）

通过深入诊断（进程栈 + 全量环境变量 + 代码审计），确认根因分为两个层面：

**层面一：处理管道是 bot_mqtt.py 而非 bot_runner.py**

模拟器通过 MQTT 发音频 → 但处理管道是 `bot_mqtt.py`（独立进程，PID 361840），而非 `bot_runner.py`（port 7860 的 FastAPI）。bot_runner 仅负责 WebRTC 子进程和设备生命周期管理，不处理 MQTT 音频。

**层面二：VAD 模式阻断 STT 触发（核心根因）**

bot_mqtt 运行在 **VAD 模式**（`MQTT_HANDLE_VAD_ON_SERVER` 未设置，默认 `"true"`）：
- chatbot 收到了完整的音频（log 确认 session/start + chunks 0..520）
- 音频通过 Opus 解码为 PCM，送入 SileroVADAnalyzer（默认置信度 0.8）
- **VAD 从未达到 SPEAKING 状态** — 模拟音频可能电平过低/无语音特征
- VAD 超时处理器检查 `vad_state != SPEAKING` → 直接返回，不做 force-stop
- EOS 消息架构上被忽略（`_finalize_turn_input` 在 VAD 模式下 return early）
- 结果：STT 不被触发 → 无 LLM → 无 TTS → 管道永久空闲

**证据链：**
1. 进程 PID 361840 所有 33 个线程均处于 S (sleeping) 状态，无一活跃
2. 主线程在 `do_epoll_wait`（asyncio 事件循环空闲等待 I/O）
3. 2 个线程在 `pipe_read`（SherpaONNX 内部线程，正常）
4. 其余均在 `futex_wait`（条件变量等待）
5. 环境变量中无 `MQTT_HANDLE_VAD_ON_SERVER`、`MQTT_VAD_CONFIDENCE`、`MQTT_STT_PROVIDER`，全部走默认值
6. 最后日志停留在 16:05:14（chunk #520），之后无任何 STT/LLM/TTS 输出

### ✅ 修复验证结果（2026-05-29 16:35）

通过 `start-local-dev.sh` 为 `mqtt_worker` 默认注入 `MQTT_HANDLE_VAD_ON_SERVER=false`（EOS 模式，绕过 VAD）后重新测试：

**Session:** `F5wWj9HD0vDe` → MQTT session `WgUsFfDPTtO7`
**音频:** `mqtt_vad_capture_input.wav`（45.68s, 762 chunks, 22s 发送完毕）

**结果:**

| 指标 | 修复前（VAD 模式） | 修复后（EOS 模式） | 判定 |
|:-----|:------------------:|:------------------:|:----:|
| STT 转写 | 空 | `"Can you speak Chinese."` | ✅ **成功** |
| 指令拦截 | — | `no command matched, forwarding to LLM` | ✅ **正常路由** |
| LLM 回复 | 无 | 生成回复 | ✅ **成功** |
| TTS 响应数 | 0 | **2** | ✅ **成功** |
| TTS chunks | 0 | **319** | ✅ **成功** |
| 端到端耗时 | — | **3.5s** | ✅ **正常** |

**日志关键行（`bot_vad_test.log`）：**
```
[PERF] stt: 1.39ms
[PERF] response_time: 2705ms (STT+审核+LLM+TTS)
[PERF] message_e2e: 3533ms (两条 TTS 消息)
```

**结论：管道本身完好。** VAD 模式对模拟音频不触发是唯一阻断原因。使用 `MQTT_HANDLE_VAD_ON_SERVER=false` 绕过 VAD 后，全链路 STT→LLM→TTS 完全正常；现在这项配置会由本地测试启动脚本默认注入给 `mqtt_worker`。

---

## 问题三：测试脚本局限性

### 缺陷列表

| # | 问题 | 影响 | 建议修复 |
|:-:|:-----|:----|:---------|
| 1 | 120s 超时小于模拟引擎内部超时 (90s intro + 90s turn = 180s) | 测试脚本先超时退出 | 增大到 200s 或使用更精准的退出条件 |
| 2 | 不等待上一 session 完成就发新的 simulate 请求 | 触发竞态条件 | 加等待重试逻辑 |
| 3 | 无重试机制 | 单次失败无法自动恢复 | 添加重试 |
| 4 | 无 MQTT 层验证 | 无法区分 "音频没发" vs "音频发了但 chatbot 没处理" | 添加 MQTT 订阅嗅探 |
| 5 | 忽略 events API 的响应 | 监控循环中 events API 未返回有效事件 | 改进 events 处理逻辑 |

---

## 四、对比：测试流程 vs 真实生产流程

### 模拟测试流程（当前 `full_link_test.py`）

```
用户/脚本                                    模拟器(server.py)          MQTT Broker         chatbot (bot_runner)
   |                                              |                       |                      |
   |-- POST /api/device/simulate ---------------->|                       |                      |
   |                                              |-- spawn background    |                      |
   |                                              |   thread              |                      |
   |                                              |-- device_firmware     |                      |
   |                                              |   .power_on()         |                      |
   |                                              |-- .start_session() -->|-- session/start ---->|  ?
   |                                              |                       |                      |
   |                                              |-- .start_turn() ----->|-- audio/start ------>|  ?
   |                                              |                       |-- audio/chunk/* ---->|  ?
   |                                              |                       |-- audio/eos -------->|  ?
   |                                              |                       |                      |
   |                                              |<-- wait_for_response -|<-- response/audio/* -|  ?
   |                                              |    90s timeout       |                      |
   |                                              |                       |                      |
   |-- polling 120s <---- GET /api/device/result  |                       |                      |
   |                                              |                       |                      |
```

### 真实生产流程

```
真实设备                                    MQTT Broker        Zebbie API/server    chatbot (bot_runner)
   |                                            |                     |                     |
   |-- MQTT connect (WiFi ~2-5s)              |                     |                     |
   |-- meta/online (retained + LWT) ---------->|                     |                     |
   |-- session/start ------------------------->|                     |                     |
   |                                            |-- validate_toy ---->|                     |
   |                                            |                     |-- play intro ------->|  ?
   |                                            |                     |                     |
   |-- (intro audio plays on speaker)          |                     |                     |
   |-- (mic captures user speech)              |                     |                     |
   |-- audio/start (turn=1) ------------------>|                     |                     |
   |-- audio/chunk/0..N (realtime, 60ms/frame)>|                     |                     |
   |-- audio/eos (total_seq+N) --------------->|                     |                     |
   |                                            |  forward to         |                     |
   |                                            |  chatbot ---------->|                     |
   |                                            |                     |  process ASR ------->|  ?
   |<-- response/audio/start ------------------|                     |                     |
   |<-- response/audio/chunk/* -----------------|                     |                     |
   |<-- response/audio/eos ---------------------|                     |                     |
   |-- audio/done (played_seq) --------------->|                     |                     |
```

### 关键差异

| 维度 | 模拟测试 | 真实生产 | 差距影响 |
|:-----|:--------|:---------|:---------|
| **连接建立** | API 调用 → 后端后门创建 DeviceFirmware | 真实 WiFi 连接 + MQTT 直连 | 流程正确性 OK，时序不同 |
| **音频发送** | 后端后台线程一次性批量发送所有 chunks | 设备实时编码发送（60ms/frame）| **不影响协议层测试** |
| **延迟模拟** | <1ms 本地 MQTT | 100-500ms RTT 云端 | 测试响应时间不可比 |
| **intro 时序** | 等待 intro EOS 后才发音频 | 用户说话和 intro 有重叠 | 影响时序但**不影响指令拦截测试** |
| **error 可见性** | 后端静默吃掉异常，API 返回 200 | 真实设备能看到 MQTT 连接状态 | **需要改进** — 模拟错误不透明 |
| **会话管理** | 单设备单线程，**竞态条件严重** | 设备自身状态机，不会自冲突 | **需要修复** |
| **音频质量** | 干净 WAV 文件 | 麦克风录音含噪声 | STT 准确率差异 |
| **ASR 处理** | 通过 MQTT 发 chunks，等待 bot 处理 | 同 | 逻辑一致，EOS 模式下已验证通过 |

---

## 五、优化建议

### P0 — 立即修复

1. **修复模拟引擎竞态条件** — `start_simulation()` 中加线程 join 等待
2. **切换为 EOS 触发模式（临时绕过）** — 通过 `start-local-dev.sh` 默认注入 `MQTT_HANDLE_VAD_ON_SERVER=false`，让 EOS 消息直接触发 STT
3. **修复 VAD 触发（长期方案）** — 以下任一：
   - 降低 `MQTT_VAD_CONFIDENCE`（0.3-0.5），使 VAD 更容易检测到语音
   - 或确认模拟音频包含清晰的语音信号
   - 或在启动模拟时传递 `handle_vad_on_server=false` 参数
4. **增加模拟错误可见性** — 模拟失败时 API 返回 500 或 error 字段

### P1 — 短期改进

4. **full_link_test.py 增加重试和等待逻辑** — 避免连续快速请求触发竞态
5. **增大监控超时到 200s** — 匹配模拟引擎内部超时
6. **添加 MQTT 流量监控到测试脚本** — 订阅 `#` 实时观察消息流

### P2 — 中期改进

7. **添加网络延迟注入选项** — 能让本地测试延迟更接近真实环境
8. **多轮对话批量测试自动化** — 连续指令场景
9. **保存详细测试报告到 JSON 文件** — 包括 MQTT 消息流快照

---

## 六、当前测试的充分性与结论

### 能测什么（已验证通过）
- ✅ 设备连接/断开 API
- ✅ 创建模拟 session
- ✅ 查询设备列表
- ✅ 查询 session 结果和历史
- ✅ 模拟引擎启动后台音频发送线程

### 修复前不能测什么（VAD 模式）
- ❌ **端到端语音交互** — 音频发送到 MQTT 后 chatbot 不响应
- ❌ **STT 转写** — 始终为空
- ❌ **LLM 回复** — 无回复文本
- ❌ **TTS 音频合成** — 无 TTS chunks
- ❌ **连续请求模拟** — 竞态条件导致模拟不可靠

### 修复后（EOS 模式）已验证
- ✅ **STT 转写** — `"Can you speak Chinese."` (SherpaONNX)
- ✅ **指令路由** — CommandIntentRouter 正常处理 STT 文本
- ✅ **LLM 回复** — 生成自然语言回复
- ✅ **TTS 合成** — 2 条回复, 319 chunks, 19s 音频
- ✅ **端到端耗时** — 3.5s (stt 1.4ms + llm 2s + tts 0.5s)

### 总体评估

**在有 `MQTT_HANDLE_VAD_ON_SERVER=false` 条件下，全链路已打通。** 管道本身完好，主要阻断原因已确认为 VAD 模式对模拟音频不触发。

仍存在的问题:
1. **竞态条件**导致大部分模拟 session 不发音频（total_chunks=0）— 待修复
2. **VAD 默认模式不适用于模拟** — 已在 `start-local-dev.sh` 中为本地 `mqtt_worker` 默认处理

