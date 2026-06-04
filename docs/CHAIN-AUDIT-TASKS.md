# Resonova 链路审计任务清单

> 审计方法：从用户操作出发，逐层追踪数据流，找到接线断点。
> 审计日期：2026-06-04

## 链路状态总览

| Chain | 名称 | 状态 | 严重程度 |
|-------|------|------|----------|
| 1 | Intro 事件传递 | ✅ 已修复 | - |
| 2 | STT 结果显示 | ✅ 正常 | - |
| 3 | 指令显示 | ✅ 正常 | - |
| 4 | 设备状态同步 | ✅ 已修复 | - |
| 5 | 会话生命周期 | ✅ 已修复 | - |
| 6 | 前端音频播放 | 🔴 完全缺失 | 致命 |

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

#### Task 6: 设备 WebSocket 连接时机
**文件**: `frontend/src/composables/useMQTTSimulation.ts` → `connectDevice()`  
**检查**: 设备 WebSocket 是否在 connectDevice 时正确建立并持续监听

### P2 — 音频播放（独立 feature）

#### Task 7: 后端音频数据转发
**文件**: `backend/scripts/device_firmware.py` + `backend/mqtt_bridge.py`  
**方案**: 
  - 方案 A: 前端通过 HTTP 获取音频文件（最简单，适合测试平台）
  - 方案 B: WebSocket 二进制帧传输（复杂，适合生产）
  - 方案 C: 保存为临时文件，返回 URL（推荐，平衡复杂度）

#### Task 8: 前端音频播放组件
**方案**: 新建 `AudioPlayer.vue`，使用 HTML5 Audio 或 Web Audio API

---

## 修复原则

1. **一个 Task 一个 PR**，每个 PR 有明确的测试验证步骤
2. **先修 P0 再修 P1**，P2 可以并行
3. **修一个验证一个**，不批量修改后一起测
