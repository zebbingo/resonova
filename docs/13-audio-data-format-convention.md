# 音频数据格式规范（AUDIO DATA FORMAT CONVENTION）

> 基于 XiaoZhi / 小智音频协议的补充约束，对齐换算因子并防止回退。

## 1. 核心换算约定

| 方向 | 公式 | 取值 |
|:----|:-----|:----:|
| float32[-1, 1] → int16[-32768, 32767] | `(x * 32768).clip(-32768, 32767).astype(np.int16)` | 对称满量程 |
| int16[-32768, 32767] → float32[-1, 0.99997] | `x.astype(np.float32) / 32768.0` | 对称满量程 |

**换算因子强制为 32768.0**（禁止使用 32767），配合 `.clip(-32768, 32767)` 保证：
- float32(1.0) → int16(32767) ← clip 保护
- float32(-1.0) → int16(-32768) ← 满量程
- 0 值映射不变

## 2. 统一常量

```python
PCM_SR = 16000             # 采样率 (Hz)
PCM_CHANNELS = 1            # 单声道
PCM_DTYPE = np.int16        # PCM 存储类型
PCM_SCALE_FACTOR = 32768.0  # 换算因子

OPUS_FRAME_SAMPLES = 960    # 帧大小 (samples) = 60ms @ 16kHz
OPUS_FRAME_MS = 60          # 帧时长
OPUS_FRAME_BYTES = 1920     # PCM 字节数 = 960 * 2
```

## 3. 权威转换入口

所有换算代码必须调用 `pcm_utils` 模块，禁止内联 `* 32767 / * 32768 / / 32768 / astype(np.int16)`。

```python
import pcm_utils

# float32 → int16
pcm_int16 = pcm_utils.float32_to_int16(data)

# int16 → float32
pcm_float = pcm_utils.int16_to_float32(data)

# dtype-aware 安全转换（接收 float32 / float64 / int16 / Python 标量 / list 均可）
pcm_int16 = pcm_utils.to_int16_safe(data)

# Opus 编解码
opus_bytes = pcm_utils.encode_opus(pcm_int16)
pcm_int16 = pcm_utils.decode_opus(opus_bytes)

# WAV 写入前校验
pcm_utils.assert_wav_consistent(data, sr=16000)
```

## 4. 部署架构与进程拓扑

整个语音链路涉及 **3 个独立进程**（分布在 WSL 中）：

```
┌─────────────────────────────────────────────────────────────────┐
│  stt-test-tool (模拟设备端)                                      │
│                                                                  │
│  Process 1: server.py (Uvicorn :8765)                           │
│    - HTTP API（角色列表、音频列表）                                │
│    - WebSocket（设备状态、session 监控）                           │
│    - 调用 mqtt_bridge.py 内部逻辑                                 │
│      └─ _load_wav() → float32                                    │
│      └─ DeviceFirmware.start_turn()                               │
│           → pcm_utils.to_int16_safe()                             │
│           → encoder.encode() → Opus packet                       │
│           → MQTT publish (prod/<device>/request/audio/.../)      │
└──────────────────────────┬──────────────────────────────────────┘
                           │ MQTT broker (Mosquitto :1883)
                           │
┌──────────────────────────▼──────────────────────────────────────┐
│  chatbot (服务端 — 两个独立进程)                                  │
│                                                                  │
│  Process 2: bot_runner.py (Uvicorn :7860)                      │
│    - HTTP API（会话管理、账户查询等）                              │
│    - MQTTDeviceManager 订阅:                                     │
│      └─ prod/+/meta/#          ← 设备上下线                      │
│      └─ prod/+/state/reported  ← 设备状态上报                    │
│      └─ prod/+/ota/reported    ← OTA 上报                        │
│    - 写入 ZebDeviceSerial（数据迁移修复后正常工作）                │
│                                                                  │
│  Process 3: bot_mqtt.py (独立启动)                              │
│    - MQTTInputTransport 订阅:                                    │
│      └─ $share/sess-intake/prod/+/request/session/+/start       │
│         (共享订阅，发现新 session)                                │
│      动态订阅（session 启动后）:                                   │
│      └─ prod/<device>/request/session/<sid>/+    ← 会话控制      │
│      └─ prod/<device>/request/audio/<sid>/#     ← 音频流         │
│      └─ prod/<device>/request/command/<sid>/#   ← 指令          │
│    - 处理 SESSION_START / CHUNK / EOS                            │
│    - ASR (STT) → LLM → TTS → MQTT response 回推                 │
└─────────────────────────────────────────────────────────────────┘
```

**关键结论：** `bot_mqtt.py` 必须作为独立的第三个进程启动，`bot_runner` 本身不处理音频。

### 全链路数据流（含格式细节）

```
模拟音频文件 (WAV int16 16kHz mono)
  → mqtt_bridge._load_wav()
    → sf.read() → float32 [-1.0, 1.0]                    ← 规范
  → DeviceFirmware.start_turn(pcm_data)
    → for each frame:
        → pcm_utils.to_int16_safe()                      ← dtype-aware
        → encoder.encode(int16_bytes, 960)
        → MQTT publish: prod/<dev>/request/audio/<sid>/chunk/<seq>

MQTT broker → bot_mqtt.MQTTInputTransport
  → decoder.decode() → int16 PCM
  → int16_to_float32()  (若 STT 需要 float)
  → ASR / LLM / TTS → MQTT response 回推
```

### 启动命令速查

```bash
# WSL — Process 1：stt-test-tool 后端
export PYTHONPATH="/home/administrator/chatbot-test/.venv/lib/python3.13/site-packages"
cd /home/administrator/projects/stt-test-tool/backend
nohup .venv/bin/python server.py &

# WSL — Process 2：bot_runner（设备管理 + HTTP）
cd /home/administrator/projects/chatbot
PYTHONPATH="/home/administrator/projects/chatbot/src" nohup .venv/bin/python -m src.bot_runner &

# WSL — Process 3：bot_mqtt（音频处理，核心）
cd /home/administrator/projects/chatbot
PYTHONPATH="/home/administrator/projects/chatbot/src" ZEBBIE_STUDIO_API_KEY="app-tfUY8CMnMpSlSeyuSN7kCz6b" nohup .venv/bin/python -m src.bot_mqtt &

# Windows — 前端
cd d:\zebbingo\projects\stt-test-tool-frontend
nohup .\node_modules\.bin\vite --host
```

## 5. 代码审查红线

| 红线 | 说明 |
|:----|:-----|
| ❌ `* 32767` | 禁止使用 32767 作为换算因子 |
| ❌ `* 32768` | 业务代码禁止直接写换算 |
| ❌ `/ 32768` | 业务代码禁止直接写换算 |
| ❌ `astype(np.int16)` | 无 clip 保护的强制类型转换 |
| ❌ `frame.tobytes()` 前无 dtype 校验 | Opus 编码器要求 int16 输入 |

**均必须通过 `pcm_utils` 模块转发。**

## 6. 防护 checklist（测试层）

以下测试已在 `test_pcm_utils.py` 中覆盖：

- [x] float32(1.0) → int16 == 32767（clip）
- [x] float32(-1.0) → int16 == -32768
- [x] int16(-32768) → float32 ≈ -1.0
- [x] Round-trip 精度 ≤ 1/32768
- [x] Opus 编解码 round-trip
- [x] WAV 一致性断言（bad dtype / sr / channels）

## 7. 集成测试验证结果（2026-05-25）

### 7.1 全链路测试时序

```
[设备端]     [MQTT]          [bot_mqtt]            [ASR/LLM/TTS]
  │            │                │                      │
  ├─ session/start ───────────► │                      │
  │            │                ├─ 角色查询 ZebFigurineInfo
  │            │                ├─ StudioApiKey 验证    │
  │            │                ├─ 订阅 session/audio/# │
  │            │                │                      │
  ├─ audio/1/start ──────────► │                      │
  ├─ audio/1/chunk/1~27 ────► │                      │
  ├─ audio/1/eos ───────────► │                      │
  │            │                ├──► STT 识别           │
  │            │                │   "Please skip..."    │
  │            │                ├──► CommandIntentRouter │
  │            │                │   → "next" 命令       │
  │            │                ├──► LLM → TTS          │
  │◄── response/audio/ ────────┤                      │
  │◄── response/command/ ──────┤                      │
  │            │                │                      │
  ├─ session/end ────────────► │                      │
```

### 7.2 实测性能指标

| 阶段 | 耗时 | 说明 |
|:----|:----:|:-----|
| 音频输入（1.61s WAV）→ Opus 编码 | 即时 | pcm_utils 格式正确 |
| MQTT 传输 27 chunks | < 200ms | Opus 帧大小 60ms |
| STT 识别（Sherpa ONNX） | ~1.6s | 句尾 VAD 超时自动截断 |
| LLM + TTS 合成 | ~4s | 含 moderation |
| 总耗时（1.61s 音频） | **16.62s** | ~10x 实时 |

### 7.3 修复内容汇总

| 问题 | 症状 | 根因 | 修复方式 |
|:----|:----|:-----|:---------|
| DB write error | `sqlalchemy.exc.OperationalError: Field 'DeviceId' doesn't have a default value` | ZebDeviceSerial 表中 DeviceId / IsDelete / DeviceMac 为 NOT NULL 无默认值 | `ALTER TABLE MODIFY COLUMN ... DEFAULT 0/'')` |
| Studio API key 500 | `500: Studio API key not configured` | roman_centurion / gladiator_maximus 从 MongoDB 导入时缺 StudioAppId / StudioApiKey | ① 数据库补全数据 ② 代码层加 `ZEBBIE_STUDIO_API_KEY` 环境变量兜底 |
| session_id 竞态 | `AttributeError: 'ConnectedDevice' object has no attribute 'session_id'` | MQTT 回调线程访问 `_fw.session_id` 时竞态，`_fw` 状态不一致 | `ConnectedDevice` 加缓存 `self.session_id`，回调读缓存 |

### 7.4 已知约束

- **角色 Studio 配置缺失无报警流程**：新增 figurine 后需手动补 `ZebFigurineInfo.StudioApiKey`，否则降级到 `ZEBBIE_STUDIO_API_KEY` 环境变量。建议以后在 admin 页面加校验。
- **chatbot .venv 损坏后恢复**：35f9e79 后 `chatbot/.venv/lib/` 丢失。stt-test-tool 需引入 chatbot-test 或其他完整 venv 的 site-packages。
- **shared subscription 依赖**：`bot_mqtt` 使用 `$share/sess-intake/` 共享订阅，确保 Mosquitto 配置允许共享订阅。
