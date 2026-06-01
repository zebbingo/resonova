# 全链路修复方案与影响范围分析

> 日期: 2026-05-29 | 基于全链路测试 + 代码/日志/进程诊断
> 用户要求: "记录问题 → 收集线索 → 规划 → 标注影响范围"

---

## 问题总览

| # | 问题 | 严重度 | 影响范围 | 修复复杂度 |
|:-:|:-----|:------:|:---------|:----------:|
| 1 | 模拟引擎竞态条件 | 🔴 P0 | Resonova模拟器所有连续 simulate 请求 | 低（~10 行） |
| 2 | VAD 阻断 STT 触发 | 🔴 P0 | 所有 MQTT 音频 session（全链路核心断点） | 低（环境变量）~ 中（代码级） |
| 3 | 模拟错误不透明 | 🟠 P1 | Resonova用户体验 | 低 |
| 4 | 测试脚本超时不足 | 🟡 P2 | 自动化测试可靠性 | 低 |

---

## 问题 1：模拟引擎竞态条件

### 📍 影响范围

| 维度 | 范围 |
|:-----|:-----|
| **触发条件** | 在已有模拟运行时，发送第 2 个 `/api/device/simulate` 请求 |
| **影响组件** | `mqtt_bridge.py` — `SimulationManager.start_simulation()` / `run_simulation()` |
| **影响用户** | Resonova用户（开发者做全链路测试时） |
| **影响结果** | API 返回 200 OK，后台静默失败，session 停留在 "pending"，300s 后被清理为 "orphan_cleaned" |
| **波及 session** | 仅当前 device_id 的后一次模拟请求失败（不会影响其他设备） |
| **复现率** | ~80%（连续请求时几乎必现） |

### 🔍 根因（已确认）

```python
# mqtt_bridge.py 约 L1487 — start_simulation()
dev.stop_current_session()
self._simulating = False
# ← 没有等待旧线程退出！
# ← 旧线程的 finally 块可能还在执行

# 新线程随后调用 run_session():
if self._simulating:  # ← 旧线程的 finally 刚设回 True
    raise ValueError("Device already has an active session")
```

### 🛠️ 修复方案

```python
# start_simulation() 中增加线程 join
old_thread = self._threads.get(device_id)
if old_thread and old_thread.is_alive():
    old_thread.join(timeout=30)  # 等待旧线程完全退出
```

### ✅ 验证方式
1. 对同一设备连续发 3 次 simulate 请求
2. 全部应返回有效 result（非 orphan_cleaned）
3. 检查服务器日志无 "already has an active session" 错误

---

## 问题 2：VAD 阻断 STT 触发 ★ 核心断点

### 📍 影响范围

| 维度 | 范围 |
|:-----|:-----|
| **触发条件** | 所有 MQTT 音频 session（100% 触发，非概率性问题） |
| **影响组件** | `bot_mqtt.py` → `mqtt_input_transport.py` → `VadSttSegmenter` → ASR pipeline |
| **影响用户** | **所有对话用户**（不仅是测试），真实设备同样受影响 |
| **影响结果** | 音频 ✅ 送达 → VAD ⛔ 不触发 → STT ❌ 空 → LLM ❌ 无 → TTS ❌ 无 → 超时 |
| **波及 session** | 全部 session（所有 device，所有 character） |
| **复现率** | **100%**（只要 `MQTT_HANDLE_VAD_ON_SERVER` 为默认 true 且 VAD 未检测到语音） |

### 🔍 根因（已确认 — 多维度证据链）

**进程层面：** bot_mqtt.py（PID 361840）所有 33 个线程均处于 S (sleeping) 状态：
- 主线程：`do_epoll_wait` — asyncio 事件循环空闲
- 2 线程：`pipe_read` — SherpaONNX 内部线程（正常）
- 其余 30 线程：`futex_wait` — 条件变量等待

**环境层面：** 进程环境变量中：
- `MQTT_HOST=localhost` `MQTT_PORT=1883`
- **无 `MQTT_HANDLE_VAD_ON_SERVER`** → 默认 `"true"` ✅ 确认 VAD 模式
- **无 `MQTT_VAD_CONFIDENCE`** → 默认 0.8
- **无 `MQTT_STT_PROVIDER`** → 默认 `sherpa_onnx`

**代码层面（agent 代码审计确认）：**
1. 音频到达 `_handle_turn_chunk` → 解码 Opus → PCM 入队列 ✅
2. `_audio_task_handler` 取帧 → 送入 `_vad_segmenter.process_audio()` ✅
3. VAD 分析器（SileroVADAnalyzer, 置信度 0.8）判断每帧是否为语音
4. **VAD 状态停留在 QUIET** → 没有语音帧达到阈值
5. 超时触发 `_handle_vad_timeout` → 检查 `vad_state != SPEAKING` → **直接 return** ⛔
6. EOS 到达 `_finalize_turn_input` → 检查 `_vad_segmenter is not None` → **return early** ⛔
7. 结果：STT 不被触发 → LLM → TTS 全部不执行

### 🛠️ 修复方案（按优先级排列）

#### 方案 A：环境变量绕过（最快，5 分钟生效）⭐ 已验证通过
```bash
# 如果不是通过 start-local-dev.sh 启动，可手工覆盖
export MQTT_HANDLE_VAD_ON_SERVER=false
```
**原理：** 关闭 VAD 模式后，EOS 消息直接触发 `_finalize_turn_input` → 调用 STT。`start-local-dev.sh` 现在会为 `mqtt_worker` 默认注入这项配置。
**优点：** 零代码改动，立即验证管道是否正常
**缺点：** Resonova也需要测试 VAD，不能永远 bypass
**验证：** 2026-05-29 16:35 实测通过（STT: "Can you speak Chinese." → LLM → TTS: 319 chunks）

#### 方案 B：代码级 VAD 回退修复（长期方案）⭐ 已实现并验证
在 `vad_stt_segmenter.py` + `mqtt_input_transport.py` 中实现：

**`vad_stt_segmenter.py` 改动：**
1. 新增 `_turn_audio_snapshot` 字节缓冲区：**积累当前 turn 的所有音频**（无论 VAD 状态）
2. `process_audio()` 每次调用时检测 turn_id 变更，自动清空快照
3. `force_stop()` 在 QUIET 状态时返回快照音频，附带 `speech_stopped=True`
4. `reset()` 同步清空快照

**`mqtt_input_transport.py` 改动：**
1. `_handle_vad_timeout()` 移除了 `vad_state != SPEAKING` 的 early return
2. 始终调用 `force_stop()`，如有音频则触发 `_handle_vad_event()` → 启动 STT

**验证：** 单元测试通过（Mock VAD, 2s audio, 64000 bytes）：
- ✅ `force_stop()` 在 QUIET 状态返回 `speech_stopped=True` + 完整音频
- ✅ turn 边界检测正确，新 turn 清空快照
- ✅ `reset()` 正确清理所有状态

### ⚠️ 副作用与风险

| 方案 | 风险 | 缓解措施 |
|:----|:-----|:---------|
| A: 关闭 VAD | 真实设备可能依赖服务端 VAD 做二次确认 | 先测试用。确认管道正常后再切换回 VAD |
| B: 降低阈值 | 误触发 STT（环境噪声被当作语音） | 从 0.3 开始逐步上调到合适值 |
| C: 代码修复 | 逻辑改动需充分测试 | 加单元测试 + 全链路重测 |

### ✅ 验证方式
1. 确认 `mqtt_worker` 通过 `start-local-dev.sh` 启动
2. 如需手工覆盖，再设置 `MQTT_HANDLE_VAD_ON_SERVER=false`
3. 跑一次全链路模拟
4. 检查 result：`stt_text` 不应为空，`tts_response_count > 0`

---

## 问题 3：模拟错误不透明

### 📍 影响范围

| 维度 | 范围 |
|:-----|:-----|
| **触发条件** | 任何模拟执行失败时 |
| **影响组件** | `mqtt_bridge.py` — `_run()` 中 `try/except` 只日志不 propagate |
| **影响用户** | Resonova API 调用者 |
| **影响结果** | 用户看到 200 OK，不知道后台失败 |

### 🔍 根因

```python
def _run(self, ...):
    try:
        result = dev.run_session(...)
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        # ← 没有设置 result 为失败状态
        # ← 没有向 API 返回错误
```

### 🛠️ 修复方案

```python
def _run(self, ...):
    try:
        result = dev.run_session(...)
    except Exception as e:
        logger.error(f"Simulation failed: {e}")
        result = SimulationResult(
            device_id=device_id,
            status="failed",
            error=str(e),
            session_id=session_id,
        )
    finally:
        ...
```

### ✅ 验证方式
1. 触发模拟失败（如竞态条件）
2. API 应返回 status=failed 或 error 字段，而非 200 OK + pending

---

## 问题 4：测试脚本超时不足

### 📍 影响范围

| 维度 | 范围 |
|:-----|:-----|
| **触发条件** | 模拟引擎内部超时（180s）> 脚本轮询超时（120s） |
| **影响组件** | `full_link_test.py` |

### 🛠️ 修复方案
- 增大轮询超时到 200s
- 添加重试机制（失败后等 10s 重试，最多 3 次）

---

## 修复路线图

### Phase 1 — 验证管道（今天）
| 步骤 | 操作 | 预计耗时 |
|:-----|:-----|:---------|
| 1 | 设置 `MQTT_HANDLE_VAD_ON_SERVER=false` 到 bot_mqtt 环境 | 5min |
| 2 | 重启 bot_mqtt（kill + 通过 start-local-dev.sh 重启） | 2min |
| 3 | 跑一次全链路模拟 | 2min |
| 4 | 检查 STT/TTS 是否正常响应 | 1min |

### Phase 2 — 修复竞态条件（今天）
| 步骤 | 操作 | 预计耗时 |
|:-----|:-----|:---------|
| 1 | 修改 `mqtt_bridge.py` 的 `start_simulation()` 加 thread join | 10min |
| 2 | 修改 `_run()` 加错误传播 | 5min |
| 3 | 修改 `full_link_test.py` 超时和重试 | 10min |
| 4 | 提交代码到 resonova | 5min |

### Phase 3 — 验证全链路（今天）
| 步骤 | 操作 | 预计耗时 |
|:-----|:-----|:---------|
| 1 | 连续发 3 次 simulate 测试竞态修复 | 2min |
| 2 | 全链路测试确认 STT/TTS 正常 | 3min |
| 3 | 文档同步更新 | 5min |

### Phase 4 — 长期优化（本周）
| 步骤 | 操作 | 优先级 |
|:-----|:-----|:-------|
| 1 | 代码级 VAD 修复（fallback 触发 STT） | P1 |
| 2 | 增加环境变量配置到 start-local-dev.sh | 已完成 |
| 3 | 增加模拟错误时 API 返回 error 字段 | P1 |
| 4 | 前端增加模拟进度可视化 | P2 |

---

## 影响范围总结

| 问题 | 影响范围 | 用户可见性 | 修复后需验证 |
|:-----|:---------|:----------|:-------------|
| 竞态条件 | 仅Resonova连续 simulate | ⛔ 不可见（API 200 但失败） | 连续 3 次 simulate 均成功 |
| VAD 阻断 STT | **所有对话用户 + 所有 session** | ✅ 可见（永远超时无回复） | STT/TTS 有输出 |
| 错误不透明 | Resonova用户 | ⛔ 不可见 | API 返回 error 字段 |
| 脚本超时 | 自动化测试 | ⛔ 不可见 | 脚本通过率 |
