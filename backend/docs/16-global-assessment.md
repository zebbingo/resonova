# 测试平台全局评估报告

> 评估范围：stt-test-tool + chatbot 两项目 | 评估时间：2026-05-27 15:30
> 基于：git 提交历史 + 文件系统扫描 + 代码审计

---

## 0. 评分总览

| 模块 | 完成度 | 稳定性 | 文档覆盖 | 备注 |
|:-----|:------:|:------:|:--------:|:-----|
| MQTT 设备模拟 | 85% | ⚠️ 中等 | ✅ 完整 | 核心链路通了，但边界情况多 |
| 语音指令拦截 | 80% | ✅ 好 | ✅ 完整 | 7 条指令全拦截，尚未合入 main |
| 音频处理管道 | 75% | ⚠️ 中等 | ✅ 完整 | format 规范已定，opencore 依赖待确认 |
| 会话生命周期 | 90% | ✅ 好 | ✅ 完整 | session/turn/状态机完整 |
| 多设备管理 | 60% | 🔴 较弱 | ⚠️ 部分 | 前端心跳未联调，老设备占坑已修复 |
| E2E 验证 | 50% | ⚠️ 中等 | ⚠️ 部分 | E2E 脚本刚加，未自动化 |
| 监控与归因 | 40% | 🔴 早期 | ✅ 完整方案 | hook 框架有了，前端展示未完工 |
| 部署上线 | 30% | 🔴 阻塞 | ✅ 完整 | main 分支无 intent 包 |
| 文档体系 | 85% | — | ✅ 完整 | 14 份文档覆盖 7 大类 |
| 代码整洁度 | 90% | — | — | 零 TODO/FIXME |

---

## 1. MQTT 设备模拟（85% ✅）

### 已完成
- DeviceFirmware 完整模拟 v1.6 协议（11 个上行 topic + 7 个下行）
- Session/Start → audible intro → 自动播放
- Audio turn (chunk/eos/done) 完整链路
- Session 心跳 / 设备心跳 / LWT
- OTA / state/desired 模拟
- 4 台并发控制
- 新设备连接自动触发 intro session
- intro 超时从 15s→90s + 前端事件推送
- 老设备自动驱逐（stale → idle → busy 三级）

### 待改进
| # | 项 | 优先级 |
|:-:|:---|:------:|
| 1 | 前端 keepalive 心跳（每 30s POST）→ 否则设备被后端回收 | P1 |
| 2 | send-turn API 前端还没接（需按钮 + WebSocket 事件处理） | P1 |
| 3 | 模拟 TTS 播放耗时（收到 eos 等几秒再发 done）→ 时序更真实 | P2 |

---

## 2. 语音指令拦截（80% ✅）

### 已完成
- CommandIntentRouter 526 行核心实现
- 7 条指令（next/prev/pause/resume/stop/vol+/vol-）完整路由
- KWS（音素级）+ 正则（ASR 后）双通道
- SessionMode 感知（DIALOGUE 全路由、STORY 透传）
- 环境变量三级覆写
- Hook 事件 5 个监控点
- 混合语句剥离（"你是谁 声音大一点"→ 剥离指令后转发 LLM）
- Smoke test 已通过（"Please skip to the next track."→ next）

### 阻塞项
| # | 项 | 状态 |
|:-:|:---|:----:|
| ⛔ | **main 分支没有 intent/ 包** | 从未合入，线上 0 部署 |
| ⛔ | **Docker CMD 只跑 bot_runner** | bot_mqtt 需额外部署 |
| ⛔ | **线上 .env 缺 ENABLE_DEVICE_VOICE_COMMANDS** | 配置文件未同步 |

---

## 3. 会话生命周期（90% ✅）

### 状态机覆盖

```
IDLE → SESSION_ACTIVE → CAPTURING → THINKING → PLAYING → DRAINING → DONE
                                                                      ↓
                                                                  ABORTED
```

全部 7 个状态 + 5 个转换，已在 `session_state.py` 中实现并通过测试。

### 归因管理
- Redis SETNX 原子认领 session
- Worker 心跳 + 6s takeover 超时
- $share 共享订阅（MQTT 层）+ Redis 锁（应用层）双重保障

---

## 4. 多设备管理（60% ⚠️）

### 问题
| # | 问题 | 说明 |
|:-:|:-----|:------|
| 1 | **前端无 keepalive** → 刷新页面后设备变孤魂，占满 4 个槽位 | 刚修了后端驱动驱逐，但前端还没发心跳 |
| 2 | **前端无 intro 状态显示** → 用户不知道 intro 播完了没 | 后端 `intro_complete` 事件已有，前端没处理 |
| 3 | **send-turn 无独立按钮** → 必须走到旧 simulate 流程 | 新 API 已加，前端按钮待加 |

---

## 5. 文档体系（85% ✅）

### chatbot 文档（13 份）

| 楼层 | 覆盖内容 | 完整度 |
|:-----|:---------|:------:|
| 01-env | 部署、WSL、MySQL、Migration、Release SOP | ✅ 完整 |
| 02-api | HTTP / MQTT 测试指南 | ✅ 完整 |
| 03-mqtt | v1.6 规范、实现总结 | ✅ 完整 |
| 04-moderation | 审核框架、并行审核、受限词 | ✅ 完整 |
| 05-timing | 计时框架、阈值逻辑、OpenAI 审核 | ✅ 完整 |
| 06-conversation | 对话约束、摘要、回合策略 | ✅ 完整 |
| 07-features | 家长控制、语言管理、Gen1 协议 | ✅ 完整 |

### stt-test-tool 文档（14 份）

| 文档 | 状态 |
|:-----|:----:|
| 13-audio-data-format-convention | ✅ 音频规范 |
| 14-sim-vs-real-gap-analysis | ✅ 差距分析 |
| 15-production-architecture | ✅ 部署架构 |
| MQTT_SIMULATION | ✅ 完整功能说明 |
| REAL_DIALOGUE_MODE | ⏳ 方案中 |
| HOOK_INJECTION_PLAN | ⏳ 方案中 |
| PRIVACY_PROTECTION | ⏳ 方案中 |
| MONITORING_STATUS | ✅ 已完成 |
| HOOK_IMPLEMENTATION_COMPLETE | ✅ 已完成 |
| IMPLEMENTATION_SUMMARY | ✅ 已完成 |
| CONVERSATION_AUDIO_TRACKING | ✅ 已完成 |
| MONITORING_CONFIG | ✅ 配置说明 |
| 17-command-management-loop | ✅ 指令管理闭环 |
| 02-14-voice-system-architecture | ✅ 语音架构总览 |

---

## 6. 代码整洁度（90% ✅）

| 项目 | 情况 |
|:-----|:------|
| TODO 残留 | stt-test-tool backend/ 下 **0 个** |
| TODO 残留 | chatbot src/ 下 voice 相关 **0 个** |
| 唯一 TODO | `model_moderation_service.py:240`（与 voice 无关） |
| 未跟踪文件 | db/ 子模块 2 个 migration SQL 尚未入库 |
| 废弃文件 | scripts/devices/ 下有约 35 个旧设备 JSON，可清理 |

---

## 7. 现在最该做的事（按优先级排序）

| P | 做什么 | 为什么 |
|:-:|:-------|:-------|
| **P0** | **前端加 keepalive + intro 状态监听 + send-turn 按钮** | 不改前端，intro 和 send-turn 新功能用户无法使用 |
| **P1** | **合入语音指令到 main 分支** | 所有 MQTT 模拟、拦截验证都是为上线铺垫，不合并等于白测 |
| **P1** | **拆出 bot_mqtt 的 docker-compose service 定义** | 线上没有 bot_mqtt 进程，语音指令拦截无法运行 |
| **P2** | **E2E 测试自动化** | e2e_verify.py 已写但需要集成到 CI 每次提交自动跑 |
| **P2** | **清理 scripts/devices/ 下的旧设备配置** | 75 个 JSON 中约一半是开发过程中产生的，可归档 |
| **P3** | **前端设备音量/LED/NFC 可视化** | 让硬件指令的响应在前端可见 |
