"""音频 PCM 格式转换 — 单一权威入口（Single Source of Truth）

遵循 docs/02-arch/13-audio-data-format-convention.md 规范。
所有 *32767/*32768、astype(np.int16)、/32768 的业务代码均必须调用本模块。

核心约定:
  - PCM: int16, 16kHz, mono, little-endian
  - float32[-1.0, 1.0] ↔ int16[-32768, 32767] 换算因子 32768.0
  - Opus 编码器输入始终为 int16 PCM bytes

代码审查红线:
  ❌ 业务代码禁止直接写 * 32767 / * 32768 / / 32768 / astype(np.int16)
  ✅ 必须调用本模块提供的函数
"""

import numpy as np

# ── 规范常量 ──────────────────────────────────────────────────────────
PCM_SR = 16000                     # 采样率 (Hz)
PCM_CHANNELS = 1                   # 声道数 (mono)
PCM_DTYPE = np.int16               # PCM 数据类型
PCM_MAX_INT16 = 32767              # int16 最大值
PCM_MIN_INT16 = -32768             # int16 最小值
PCM_SCALE_FACTOR = 32768.0         # float32↔int16 对称换算因子

# Opus 编码参数（opuslib_next 惰性导入）
OPUS_FRAME_SAMPLES = 960            # 16kHz × 60ms
OPUS_FRAME_MS = 60                  # 每帧时长 (ms)
_opus_application = None            # 第一次使用时惰性初始化
OPUS_FRAME_BYTES = OPUS_FRAME_SAMPLES * 2           # 每帧 PCM 字节数


def _get_opus_app() -> int:
    """惰性获取 opuslib_next.APPLICATION_AUDIO，避免模块级导入失败。"""
    global _opus_application
    if _opus_application is None:
        import opuslib_next  # noqa: PLC0415
        _opus_application = opuslib_next.APPLICATION_AUDIO
    return _opus_application


# ── 核心转换函数 ──────────────────────────────────────────────────────

def int16_to_float32(x) -> np.ndarray:
    """int16[-32768, 32767] → float32[-1.0, 1.0]

    规范依据: x.astype(np.float32) / 32768.0
    接受 numpy ndarray、list 或 Python int/float 标量。
    不强制输入为 int16 —— 如果输入已经是 float32，等价位浮点转换。
    """
    return np.asarray(x).astype(np.float32) / PCM_SCALE_FACTOR


def float32_to_int16(x) -> np.ndarray:
    """float32[-1.0, 1.0] → int16[-32768, 32767]

    规范依据: (x * 32768).clip(-32768, 32767).astype(np.int16)
    接受 numpy ndarray、list 或 Python float 标量。
    """
    return (np.asarray(x, dtype=np.float32) * PCM_SCALE_FACTOR).clip(PCM_MIN_INT16, PCM_MAX_INT16).astype(np.int16)


def to_int16_safe(x) -> np.ndarray:
    """Dtype-aware: 安全地将 float32/float64/int16/uint16/int32 统一转为 int16

    等效于旧版 start_turn() 中的 dtype-aware 逻辑：
      - float32/float64: 按规范 *32768 + clip 转换
      - int16/uint8/int8: 类型安全直接转换
      - int32/uint16/int64/int8/uint8: clip 至 int16 范围后转换（防止回绕）
      - Python 标量 / list / ndarray: 先规范化为 ndarray 再处理
    """
    arr = np.asarray(x)
    if arr.dtype in (np.float32, np.float64):
        return float32_to_int16(arr)
    if arr.dtype in (np.int16, np.uint8, np.int8):
        return arr.astype(np.int16)
    # int32 / uint16 / int64 等宽类型：clip 至 int16 范围防止回绕截断
    return arr.clip(PCM_MIN_INT16, PCM_MAX_INT16).astype(np.int16)


def encode_opus(pcm_int16: np.ndarray, frame_size: int = OPUS_FRAME_SAMPLES) -> bytes:
    """Opus 编码：int16 PCM ndarray → Opus packet bytes

    编码器输入始终为 int16 PCM bytes（np.asarray + .tobytes()）。
    首次调用时惰性加载 opuslib_next。
    """
    import opuslib_next  # noqa: PLC0415
    encoder = opuslib_next.Encoder(PCM_SR, PCM_CHANNELS, _get_opus_app())
    return encoder.encode(
        np.asarray(pcm_int16, dtype=np.int16).tobytes(),
        frame_size,
    )


def decode_opus(opus_bytes: bytes, frame_size: int = OPUS_FRAME_SAMPLES) -> np.ndarray:
    """Opus 解码：Opus packet bytes → int16 PCM ndarray

    首次调用时惰性加载 opuslib_next。
    """
    import opuslib_next  # noqa: PLC0415
    decoder = opuslib_next.Decoder(PCM_SR, PCM_CHANNELS)
    pcm_bytes = decoder.decode(opus_bytes, frame_size)
    return np.frombuffer(pcm_bytes, dtype=np.int16)


# ── WAV 一致性校验（写入前断言）────────────────────────────────────────

def assert_wav_consistent(data: np.ndarray, sr: int = PCM_SR):
    """WAV 写入前断言：确保 dtype/sr/声道/对齐符合规范

    在调用 sf.write() / wavfile.write() 前调用此函数。
    避免 header 与 payload 不一致导致的噪声或解码问题。
    """
    assert data.dtype == np.int16, (
        f"WAV 数据必须是 int16，当前 {data.dtype}"
    )
    assert sr == PCM_SR, (
        f"采样率必须是 {PCM_SR} Hz，当前 {sr} Hz"
    )
    if data.ndim == 2:
        assert data.shape[1] == PCM_CHANNELS, (
            f"声道数必须是 {PCM_CHANNELS} (mono)，当前 {data.shape[1]}"
        )
    assert data.nbytes % 2 == 0, (
        f"int16 数据必须是偶数字节，当前 {data.nbytes} bytes"
    )
