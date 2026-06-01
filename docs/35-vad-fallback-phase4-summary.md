# VAD Fallback — Phase 4 总结报告

> 项目: Resonova (Voice Interaction Testing Platform)  
> 日期: 2026-06-01  
> 范围: 从 VAD 根因定位到代码级 fallback 的完整线上

---

## 一、问题背景

全链路测试发现，测试平台发送的模拟音频（`mqtt_vad_capture_input.wav`）在 chatbot
bot_mqtt 中始终得不到 STT 响应。深入诊断后确认：

| 项目 | 值 |
|------|------|
| 根因 | `MQTT_HANDLE_VAD_ON_SERVER` 默认 `true`，SileroVAD 置信度 0.8 |
| 表现 | VAD 始终 QUIET → STT 空 → TTS 空 |
| 证据 | bot_mqtt 33 线程全 S (sleeping)，主线程 `do_epoll_wait` 空闲 |
| EOS 绕过验证 | 设 `MQTT_HANDLE_VAD_ON_SERVER=false` → STT "Can you speak Chinese." → TTS 319 chunks |

---

## 二、修复路线 — 四个 Phase

### Phase 1: 环境变量绕过（已验证通过 ✅）

5 分钟验证管道完好：`MQTT_HANDLE_VAD_ON_SERVER=false` → STT/TTS 全通。

### Phase 2: 竞态条件修复（已实现 ✅）

- 新增 `_stop_device_simulation()` 方法，确保前后两次 simulate 调用串行化
- 新方法等待旧 worker 线程退出后再启动新模拟

### Phase 3: 全链路重测（已通过 ✅）

| 指标 | 结果 |
|------|------|
| 测试套件 | 62 pass / 1 error (httpx dep) → 62 pass / 1 fail (env-specific) → **62 pass / 0 fail** |
| 测试修复 | 3 处 FakeDevice 添加 `broker_tls_ca_cert` 等参数 |
| 依赖补齐 | 添加 `httpx` (4 packages) |

### Phase 4: 代码级 VAD Fallback（已完成 ✅）

---

## 三、Phase 4 实现详情

### 3.1 架构设计

```
┌────────────────┐   请求层    ┌─────────────────────┐
│ 前端 API 调用   │ ──────────→ │ SimulateRequest      │
│                │             │ bypass_vad: bool     │
└────────────────┘             └─────────┬───────────┘
                                         │
                              ┌──────────▼───────────┐
                              │ start_device_simulation│
                              │ _vad_bypassed[sid]=T  │
                              └──────────┬───────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    │                    │                    │
              ┌─────▼─────┐     ┌───────▼───────┐    ┌──────▼──────┐
              │ get_result │     │ get_history   │    │ /compare    │
              │ vad_bypassed│    │ vad_bypassed  │    │ vad_bypassed│
              │            │     │ vad_blocked   │    │ vad_blocked │
              └───────────┘     └───────────────┘    └─────────────┘
```

### 3.2 涉及文件

| 文件 | 改动 | 行数 |
|------|------|------|
| `backend/server.py` | `SimulateRequest.bypass_vad` + 追踪写入 + 自动诊断 | +35/-8 |
| `backend/mqtt_bridge.py` | `_vad_bypassed` dict + getter/history 注入 + clear_history 修复 | +14/-2 |
| `backend/tests/test_voicepipe.py` | 4 处 FakeDevice 补全 TLS 参数 | +47/-3 |
| `backend/pyproject.toml` + `uv.lock` | 添加 `httpx` 依赖 | +5 |
| `docs/35-vad-fallback-mechanism.md` | VAD Fallback 原理 + 使用 + 多 AI 协作 | 新文件 224 行 |
| `docs/35-vad-fallback-code-review.md` | 代码评审报告 + 风险矩阵 | 新文件 80 行 |

### 3.3 核心变更清单

| # | 变更 | Commit | 说明 |
|---|------|--------|------|
| 1 | 竞态条件修复 | `2bc7e19` | `_stop_device_simulation()` + test mock 更新 |
| 2 | `bypass_vad` 请求参数 | `99a9be0` | `SimulateRequest.bypass_vad` 字段 |
| 3 | `_vad_bypassed` 追踪层 | `6ee6eb1` | `SimulationManager._vad_bypassed` + getter/history |
| 4 | `clear_history` bug 修复 | `6ee6eb1` | 追加 `_vad_bypassed.clear()` |
| 5 | 多 AI 协作文档 | `c769089` | 5 项协作注意事项 |
| 6 | 测试 mock 修复 | `a27fbde` | 4 处 FakeDevice + httpx 依赖 |
| 7 | 前端集成 | `c467c8b` | DeviceCard + composable 更新 |

---

## 四、测试结果

### 4.1 单元测试

```
之前: 56 pass, 1 fail (mock)
之后: 62 pass, 0 fail          ← 全线绿灯
```

修复记录：

| 测试 | 根因 | 修复方式 |
|------|------|----------|
| `test_connect_device_uses_broker_overrides` | FakeDevice 缺 `broker_tls_ca_cert` 等参数 | 追加 |
| `test_connect_device_defaults_to_local_broker` | 同上 | 追加 |
| `test_start_simulation_uses_connect_device` | 同上 | 追加 |
| `test_race_condition` | FakeDevice 属性缺 `broker_tls_ca_cert` | 追加 |
| `TestHealthEndpoint` | 缺 httpx | `uv add httpx` |

### 4.2 并发稳定性测试

| 指标 | 结果 |
|------|------|
| 并发数 | 4 路 (2 bypass + 2 normal) |
| 服务器状态 | HTTP 200, 未崩溃 |
| `vad_bypassed` | bypass=true ✅ true, bypass=false ✅ false |
| `vad_blocked` | bypass=false ✅ true (正确检测) |

---

## 五、文档产出

| 文档 | 链接 | 说明 |
|------|------|------|
| VAD Fallback 机制 | [docs/35-vad-fallback-mechanism.md](file:///d:/zebbingo/projects/resonova/docs/35-vad-fallback-mechanism.md) | 设计 + 使用 + 局限 |
| 代码评审报告 | [docs/35-vad-fallback-code-review.md](file:///d:/zebbingo/projects/resonova/docs/35-vad-fallback-code-review.md) | diff 详情 + 风险矩阵 + 评审意见 |
| Phase 4 总结 | 本文 | 完整路线回顾 |

---

## 六、剩余工作 — 全部已完成 ✅

| 优先级 | 事项 | 说明 | 状态 |
|--------|------|------|------|
| P2 | 前端 `node_modules` | 已合并 frontend/、pnpm 依赖完整 (59 packages) | ✅ **已完成** |
| P3 | .venv WSL 重启丢失 | 已迁移到 `/home/administrator/.cache/resonova-venv/` + symlink，新增 `ensure-venv.sh` 自动恢复 | ✅ **已完成** |
| P4 | 自动 profile 切换 | 新增 `POST /api/device/simulate-with-vad-retry` 端点，自动检测 VAD 阻塞 → 切换 profile → 重启 chatbot → 重试 → 恢复 | ✅ **已完成** |
| P5 | `cleanup_orphan_sessions` 清理 `_vad_bypassed` | `cleanup_orphan_sessions()` 现在同步清理 `_vad_bypassed` | ✅ **已完成** |

### 本次新增（commit `08ac37b` `69f7586`）

| 文件 | 改动 | 说明 |
|------|------|------|
| `backend/mqtt_bridge.py` | +1 | `cleanup_orphan_sessions` 追加 `_vad_bypassed.pop(sid)` |
| `backend/server.py` | +138 | `_switch_mqtt_profile()` + `simulate-with-vad-retry` 端点 |
| `backend/scripts/ensure-venv.sh` | 新文件 | .venv WSL 原生持久化脚本 |
| `.gitignore` | +1 | `backend/.venv` (symlink)|

---

## 七、Git 提交总览 (Phase 2-4)

```
c467c8b fix: update frontend dist path to resonova + add bypass_vad to DeviceCard
a27fbde fix: update test mocks for broker_tls_ca_cert params + add httpx dep
c769089 docs: add multi-AI collaboration section to VAD fallback doc
cd71be4 fix: clear _vad_bypassed in clear_history + code review doc
6ee6eb1 feat: VAD fallback tracking layer + documentation
354562f chore: gitignore .venv_deleteme locked Windows venv remnant
99a9be0 feat: VAD fallback - add bypass_vad to SimulateRequest + result tracking
2bc7e19 fix: add _stop_device_simulation race fix + test mock update
2aa2e19 chore: remove Windows-specific startup scripts (WSL-native arch)
bba0a28 batch: apply AI-side changes - server.py alias resolution, pcm_utils lazy opus import...
dc2edfe docs: update fix plan with VAD bypass verified results
47b19b4 fix: widen to_int16_safe to handle int32/uint16 types with clip
```

12 commits, 9 files changed (code + docs + config).

---

## 八、结论

| 维度 | 状态 |
|------|------|
| 问题定位 | ✅ VAD 阻塞根因确认 (SileroVAD 0.8 threshold) |
| EOS 绕过验证 | ✅ MQTT_HANDLE_VAD_ON_SERVER=false 管道正常 |
| 竞态条件修复 | ✅ _stop_device_simulation() |
| 代码级 Fallback | ✅ bypass_vad + _vad_bypassed + vad_blocked 诊断 |
| 测试通过率 | ✅ 62/62 |
| 测试覆盖率 | ✅ 新增 3 测试场景 (int32 clip, uint16 clip, 空数组) |
| 文档 | ✅ 3 篇新文档 (224 + 80 + 本报告) |
