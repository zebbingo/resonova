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

# dtype-aware 安全转换（接收 float32 / float64 / int16 均可）
pcm_int16 = pcm_utils.to_int16_safe(data)

# Opus 编解码
opus_bytes = pcm_utils.encode_opus(pcm_int16)
pcm_int16 = pcm_utils.decode_opus(opus_bytes)

# WAV 写入前校验
pcm_utils.assert_wav_consistent(data, sr=16000)
```

## 4. 全链路数据流

```
WAV / mic (int16, 16kHz, mono)
  → _load_wav() / sf.read()
    → float32 [-1.0, 1.0]
  → start_turn(pcm_data) / 业务方
    → pcm_utils.to_int16_safe()  ← dtype-aware
    → encoder.encode(int16_bytes, frame_size)
    → Opus packet → MQTT publish

MQTT receive → Opus packet
  → decoder.decode() → int16 PCM
  → int16_to_float32()  ← 若 STT 需要 float
  → STT / ASR
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
