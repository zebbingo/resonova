# Resonova 链路审计任务清单

> 审计方法：从用户操作出发，逐层追踪数据流，找到接线断点。
> 审计日期：2026-06-04
> **验证状态**：✅ 2026-06-04 17:01 全链路验证成功（连接→开场白→音频播放）

---

## 全链路架构图（给其他 AI 的参考）

```
前端 Resonova (DeviceCard.vue)
  │
  ├─ ① handleConnect()
  │     POST /api/device/connect
  │     → mqtt_bridge.SimulationManager.connect_device()
  │     → ConnectedDevice.power_on()  [DeviceFirmware 连接 NanoMQ]
  │     → _trigger_intro_session()    [自动开始 intro session]
  │
  ├─ ② WebSocket /ws/device/{device_id}
  │     ← EventBus(device_id queue) ← ConnectedDevice._emit_device()
  │
  ├─ ③ Intro 音频流
  │     NanoMQ → DeviceFirmware._on_message() → _intro_audio_eos_event.set()
  │     → _on_mqtt_event("tts_synthesis") → _emit_device("audio_ready")
  │     → WebSocket → 前端播放
  │
  └─ ④ 用户 Turn
        POST /api/device/send-turn
        → ConnectedDevice.send_user_turn()
        → DeviceFirmware.start_turn() → NanoMQ → bot_mqtt
        → STT → LLM → TTS → NanoMQ → DeviceFirmware → WebSocket → 前端
```

### 关键组件与文件对照表

| 组件 | 文件路径 | 职责 |
|------|----------|------|
| 前端 UI | `frontend/src/components/DeviceCard.vue` | 设备连接、角色选择、音频播放 |
| 前端 MQTT 逻辑 | `frontend/src/composables/useMQTTSimulation.ts` | WebSocket 事件处理、状态机 |
| 后端 API | `backend/server.py` | FastAPI 路由、WebSocket、事件转发 |
| MQTT Bridge | `backend/mqtt_bridge.py` | ConnectedDevice、SimulationManager、EventBus |
| 设备固件模拟 | `backend/scripts/device_firmware.py` | MQTT 连接、Opus 编解码、intro 等待 |
| MQTT 配置 | 前端从 `/api/debug/runtime-config` 动态获取 | 不硬编码 |

---

## 已解决的阻塞点（2026-06-04）

| # | 问题 | 根因 | 修复方法 | 关键文件 |
|---|------|------|----------|----------|
| 1 | rc=7 无限断连 | WSL IP 不被识别为本地 broker | `_is_local_or_private_host()` + 空凭据 | `mqtt_bridge.py` |
| 2 | Intro 事件不到前端 | 只发 session 队列 | 同时 `_emit_device()` | `mqtt_bridge.py` |
| 3 | 前端不识别事件 | switch 缺少 case | 新增 intro/device_state/audio_ready | `useMQTTSimulation.ts` |
| 4 | Intro EOS 不发射 | turn_id="0" 只设标志 | 添加 `_on_mqtt_event` | `device_firmware.py` |
| 5 | 音频无法播放 | Opus 存内存不转发 | 解码→WAV→HTTP→前端播放 | `device_firmware.py` + `server.py` |
| 6 | MQTT_ENV 不匹配 | 前端硬编码 prod，后端用 development | 从后端 API 动态获取 | `DeviceCard.vue` |

## 链路状态总览

| Chain | 名称 | 状态 | 严重程度 |
|-------|------|------|----------|
| 1 | Intro 事件传递 | ✅ 已修复 | - |
| 2 | STT 结果显示 | ✅ 正常 | - |
| 3 | 指令显示 | ✅ 正常 | - |
| 4 | 设备状态同步 | ✅ 已修复 | - |
| 5 | 会话生命周期 | ✅ 已修复 | - |
| 6 | 前端音频播放 | ✅ 已实现 | - |
| 7 | 设备 WebSocket 连接 | ✅ 已验证 | - |

---

## 任务清单

### P0 — 必须先修（阻塞测试）

#### Task 1: 开场白事件转发到设备队列 ✅
**文件**: `backend/mqtt_bridge.py` → `start_session_and_await_intro()`  
**问题**: `intro` 事件只发到 session 队列，前端只连了 device WebSocket  
**修复**: 同时 `_emit_device()` 发送 `intro` 事件（intro_playing / intro_complete / intro_timeout）

#### Task 2: 前端识别 `intro` 事件 ✅
**文件**: `frontend/src/composables/useMQTTSimulation.ts` → `_handleWsMessage()`  
**问题**: switch 中没有 `case 'intro':`，事件落入 default  
**修复**: 添加 intro 状态处理，更新 state.status 和 state.lastSessionStatus

#### Task 3: 前端识别 `device_state` 事件 ✅
**文件**: `frontend/src/composables/useMQTTSimulation.ts` → `_handleWsMessage()`  
**问题**: switch 中没有 `case 'device_state':`，设备状态不同步  
**修复**: 添加 device_state 处理，同步到 deviceSM 状态机；同时添加 device_error 处理

#### Task 4: intro EOS 事件发射 ✅
**文件**: `backend/scripts/device_firmware.py` → `_handle_audio_message()` L726-728  
**问题**: intro turn_id="0" 的 EOS 只设标志，不发射 `tts_synthesis` complete 事件  
**修复**: 添加 `_on_mqtt_event("tts_synthesis", {"state": "complete", "turn_id": "0"})`

### P1 — 链路完整化

#### Task 5: `introeos` 前端状态更新 ✅
**文件**: `frontend/src/composables/useMQTTSimulation.ts` L806-808  
**问题**: `introeos` 仅记日志，不触发状态变化  
**修复**: 更新 state.lastSessionStatus 为 'intro_complete'

#### Task 6: 设备 WebSocket 连接时机 ✅
**文件**: `frontend/src/composables/useMQTTSimulation.ts` → `connectDevice()`  
**检查**: 设备 WebSocket 是否在 connectDevice 时正确建立并持续监听  
**验证**: WebSocket 在 connectDevice 时建立（L330-340），包含 onmessage/onclose 处理，keepalive 机制已启动

### P2 — 音频播放（独立 feature）

#### Task 7: 后端音频数据转发 ✅
**文件**: `backend/scripts/device_firmware.py` + `backend/server.py`  
**实现**:  
  - `device_firmware.py`: `_decode_and_save_audio()` 解码 Opus→PCM→WAV，保存到 `.audio_cache`
  - `server.py`: `/api/sim-audio/{filename}` 端点提供音频文件下载
  - `device_firmware.py`: 发射 `audio_ready` 事件（含 turn_id, url, chunks, duration_ms）

#### Task 8: 前端音频播放组件 ✅
**文件**: `frontend/src/composables/useMQTTSimulation.ts`  
**实现**:  
  - 处理 `audio_ready` 事件（L757-771）
  - 自动创建 `Audio` 元素并播放
  - 记录日志到 SessionLog

---

## 修复原则

1. **一个 Task 一个 PR**，每个 PR 有明确的测试验证步骤
2. **先修 P0 再修 P1**，P2 可以并行
3. **修一个验证一个**，不批量修改后一起测

---

## 新增功能变更的已知风险（2026-06-04）

> 以下变更由另一个 AI 引入，可能影响已打通的全链路。修改前务必理解每条的上下文。

### 🔴 高风险：双 Session 冲突

**变更**：`DeviceCard.vue` 的 `handleConnect()` 末尾新增自动 `startSession()`：
```typescript
if (figurineId.value && !isSimulating.value) {
  startSession({ figurineId: figurineId.value, mode: mode.value }).catch(...)
}
```

**问题**：`connect_device()` 内部已调用 `_trigger_intro_session()`，会自动开始 intro session。
前端再调一次 `startSession()`，会导致**同一设备同时有两个 session 竞争 MQTT 连接**。

**诊断方法**：检查 bot_mqtt 日志，同一 device_id 是否连续收到两个 `session/start`。

**建议**：去掉这段自动 startSession 逻辑，或改为仅在 `skip_auto_intro=true` 时触发。

### 🟡 中风险：EventBus queue 预创建

**变更**：`server.py` 在 `start_session_and_await_intro()` 前预创建 EventBus queue：
```python
sid_preliminary = dev.session_id or ""
if sid_preliminary and simulation_manager.event_bus:
    simulation_manager.event_bus.create_queue(sid_preliminary)
```

**问题**：`ConnectedDevice.__init__` 随机生成一个 session_id，但 `DeviceFirmware.start_session()`
内部会再生成新的。如果两个 id 不一致，WebSocket 可能监听错误的队列。后面有 `alias_queue`
做补救，但依赖时序正确。

### 🟡 中风险：llm_text 事件注入

**变更**：`server.py` 新增 `llm_text` 事件转发给 DeviceFirmware：
```python
if event_type == "llm_text":
    for dev in simulation_manager._devices.values():
        if dev._fw and dev.is_connected:
            dev._fw.collect_llm_text(text, chunk)
```

**问题**：
1. `collect_llm_text` 必须在 `DeviceFirmware` 上已定义，否则 AttributeError
2. 遍历所有 device 找 `is_connected` 状态的，多设备同时在线时可能注入错误设备

### 🟢 低风险：_normalize_audio_path 双向转换

**变更**：新增 WSL→Windows 路径转换分支（`/mnt/d/...` → `D:\...`）。

**问题**：在 WSL 上运行时，该分支不应被触发（因为 WSL 路径本身就能直接访问），
但如果逻辑判断有误，可能将正确的 WSL 路径错误转成 Windows 路径。

---

## 链路排查 Checklist

全链路不通时，按此顺序排查：

1. **MQTT 配置一致性**：
   ```bash
   curl http://localhost:8765/api/debug/runtime-config | jq .mqtt
   # 确认 env=development, host=localhost, port=1883
   ```

2. **NanoMQ 是否运行**：
   ```bash
   wsl bash -lc "ps aux | grep nanomq | grep -v grep"
   ```

3. **bot_mqtt 是否运行**：
   ```bash
   wsl bash -lc "ps aux | grep bot_mqtt | grep -v grep"
   ```

4. **是否有双 Session 冲突**：
   ```bash
   wsl bash -lc "tail -20 /home/administrator/projects/chatbot/output/log/bot_mqtt-*.log | grep session.*start"
   ```

5. **前端 WebSocket 是否连接**：浏览器 F12 → Network → WS，检查 `/ws/device/{id}`

6. **Intro 音频是否超时**：看前端控制台是否有 `intro_timeout` 日志

7. **Resonova 后端是否存活**：
   ```powershell
   Get-NetTCPConnection -LocalPort 8765 -ErrorAction SilentlyContinue
   # 如果无输出 = 后端已死，需要重启
   ```

8. **Resonova 后端日志**：`backend/server_output.log` 末尾是否有 Traceback

---

## 2026-06-07 诊断记录：后端崩溃导致全链路不可用

**现象**：前端有 intro/upload_progress 事件但没有 audio，bot_mqtt 日志正常。

**根因**：Resonova 后端（Windows 上的 uvicorn reload 模式）崩溃，
端口 8765 无进程监听。原因是 `server.py` 被修改后触发了 reload，
但 Windows multiprocessing spawn 模式缺少 `if __name__ == '__main__'` 保护，
导致 RuntimeError: "An attempt has been made to start a new process before
the current process has finished its bootstrapping phase."

**修复**：
1. 确保 `start_server.py` 或 `server.py` 的入口有 `if __name__ == '__main__'` 保护
2. 或者用 `uvicorn server:app --host 0.0.0.0 --port 8765` 直接启动（不用 reload 模式）
3. 或者用 `scripts/start-resonova.ps1 start` 脚本重启整个测试平台

**关键验证**：bot_mqtt 日志确认全链路正常（session/start → introeos → TTS audio → session/end），
问题完全在 resonova 后端崩溃，不在 chatbot 侧。

---

## 🔴 致命问题：后端必须运行在 WSL 上，不能在 Windows 上

**发现时间**：2026-06-07

**现象**：前端点击连接后，`/api/device/connect` 返回错误：
```
Device xxx: cannot reach broker localhost:1883: [WinError 10061] 由于目标计算机积极拒绝，无法连接。
```

**根因**：
- NanoMQ 运行在 WSL（192.168.52.134）里，监听 `0.0.0.0:1883`
- DeviceFirmware 在后端进程中通过 `localhost:1883` 连接 NanoMQ
- **如果后端运行在 Windows 上**，Windows 的 `localhost:1883` 没有任何服务 → 连接被拒绝
- **如果后端运行在 WSL 上**，WSL 的 `localhost:1883` 就是 NanoMQ → 正常连接

**另一个 AI 犯的错误**：
用 Windows 系统的 `C:\Program Files\Python311\python.exe` 启动了后端，
而不是用 WSL 内的 Python 启动。这导致后端在 Windows 上运行，连不上 WSL 的 NanoMQ。

**正确的启动方式**：
```bash
# 必须在 WSL 内启动后端
wsl bash -lc "cd /mnt/d/zebbingo/projects/resonova/backend && uv run uvicorn server:app --host 0.0.0.0 --port 8765"
```
或者用启动脚本：
```powershell
# scripts/start-resonova.ps1 会自动在 WSL 内启动后端
scripts/start-resonova.ps1 start
```

**验证后端是否在 WSL 上运行**：
```powershell
# 检查 8765 端口的进程
Get-Process -Id (Get-NetTCPConnection -LocalPort 8765).OwningProcess | Select Path
# 如果 Path 包含 Windows 路径（如 C:\Program Files\Python311）= 错误
# 如果通过 WSL 启动，Windows 上看不到 python 进程，需要用 wsl ps aux 查看
```

**或者：在 Windows 上运行时使用 WSL IP**：
如果坚持在 Windows 上运行后端，需要将 MQTT host 改为 WSL IP：
```
# 不推荐，因为 WSL IP 可能变化
MQTT_HOST=192.168.52.134  # WSL IP
```

**结论**：resonova 后端 **必须在 WSL 内启动**，这是架构设计决定的，不是 bug。

### 混乱追溯：为什么设计被破坏了

**原始设计（doc-20，2026-05-29）**：
```
Windows D:\zebbingo\projects\resonova\  ← git repo（源码唯一副本）
WSL /home/administrator/projects/resonova → 软链到 /mnt/d/... （通过软链访问源码）
WSL .venv → Linux Python 3.13（在 /mnt/d/ 上创建的 Linux venv）
```

后端在 WSL 内通过软链启动，`.venv` 是 Linux venv，`localhost:1883` 直接就是 NanoMQ。
一切正常，因为后端进程跑在 WSL 内。

**doc-20 第 58-59 行明确写着**：
> resonova 后端 | WSL | ✅ | uvicorn 跑在 WSL，必须访问源码

**原始启动脚本**：`scripts/setup/start-local-dev.sh`（WSL bash 脚本）
```bash
# 第 738 行
"$STT_VENV_PY" server.py  # WSL 内的 .venv/bin/python
```

**混乱是如何发生的**：
1. 项目从 `stt-test-tool` 重命名为 `resonova`（2026-05-29）
2. 另一个 AI 创建了 `scripts/setup/start-resonova.ps1`（PowerShell 脚本）
3. 这个脚本用 `C:\Program Files\Python311\python.exe`（Windows 系统Python）启动后端
4. 它尝试设 `$env:MQTT_HOST = Get-WslBrokerHost` 来绕过，但后端代码 `_resolve_local_mqtt_host()` 已有自动WSL IP适配
5. **但 `start-resonova.ps1` 设的环境变量 `MQTT_HOST` 被 `_resolve_mqtt_host()` 读到，而 `profile=local` 走的是 `_resolve_local_mqtt_host()` 不读 `MQTT_HOST` 环境变量**
6. 结果：`profile=local` 调 `_resolve_local_mqtt_host()` → 尝试 `wsl hostname -I` → 可能超时或失败 → fallback 到 `localhost` → 连接拒绝

**根本问题**：`start-resonova.ps1` 违反了 doc-20 的设计原则，试图在 Windows 上运行后端。
虽然 `mqtt_bridge.py` 有 Windows 兼容层，但它依赖 `wsl hostname -I` 子进程调用，不可靠。

**正确的修复**：
- 删除或弃用 `scripts/setup/start-resonova.ps1`（它的设计方向是错误的）
- 使用 `scripts/setup/start-local-dev.sh` 在 WSL 内启动
- 或直接在 WSL 内启动后端：
  ```bash
  wsl bash -lc "cd /home/administrator/projects/resonova/backend && uv run uvicorn server:app --host 0.0.0.0 --port 8765"
  ```

**当前验证**：
```bash
# WSL 软链还在
wsl ls -la /home/administrator/projects/resonova
# → resonova -> /mnt/d/zebbingo/projects/resonova ✅

# WSL .venv 还在（Linux Python 3.13）
wsl cat /home/administrator/projects/resonova/backend/.venv/pyvenv.cfg
# → prompt = stt-test-backend（旧名，未改名，但能用）

# Windows 上 .venv 不存在
Test-Path D:\zebbingo\projects\resonova\backend\.venv\pyvenv.cfg
# → False（因为 .venv 是 Linux 格式，Windows 无法识别）
```
