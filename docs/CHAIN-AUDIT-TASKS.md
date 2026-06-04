# Resonova 链路审计任务清单

> 审计方法：从用户操作出发，逐层追踪数据流，找到接线断点。
> 审计日期：2026-06-04
> **验证状态**：✅ 2026-06-04 17:01 全链路验证成功（连接→开场白→音频播放）

## 今日解决的问题

| # | 问题 | 根因 | 修复方法 | 验证 |
|---|------|------|----------|------|
| 1 | rc=7 无限断连 | WSL IP 不被识别为本地 broker | `_is_local_or_private_host()` + 空凭据 | ✅ |
| 2 | Intro 事件不到前端 | 只发 session 队列 | 同时 `_emit_device()` | ✅ |
| 3 | 前端不识别事件 | switch 缺少 case | 新增 intro/device_state/audio_ready | ✅ |
| 4 | Intro EOS 不发射 | turn_id="0" 只设标志 | 添加 `_on_mqtt_event` | ✅ |
| 5 | 音频无法播放 | Opus 存内存不转发 | 解码→WAV→HTTP→前端播放 | ✅ |

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
