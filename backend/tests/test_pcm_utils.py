"""测试音频 PCM 转换 — 3 条硬断言 + 边界值 + Round-trip 精度

防护类型: #3 — 单元测试硬断言
"""

import sys
from pathlib import Path

# 将 backend/ 加入 path 以便导入 pcm_utils
_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

import numpy as np
import pytest
from pcm_utils import (
    int16_to_float32,
    float32_to_int16,
    to_int16_safe,
    encode_opus,
    decode_opus,
    assert_wav_consistent,
    PCM_SCALE_FACTOR,
    PCM_MIN_INT16,
    PCM_MAX_INT16,
    PCM_SR,
    OPUS_FRAME_SAMPLES,
)


class TestPcmConvert:
    """硬断言 1: 边界值正确性"""

    def test_float32_1dot0_clips_to_32767(self):
        assert float32_to_int16(np.float32(1.0)) == PCM_MAX_INT16

    def test_float32_neg1_clips_to_neg32768(self):
        assert float32_to_int16(np.float32(-1.0)) == PCM_MIN_INT16

    def test_float32_0_to_0(self):
        assert float32_to_int16(np.float32(0.0)) == 0

    def test_int16_neg32768_to_neg1(self):
        assert int16_to_float32(np.int16(PCM_MIN_INT16)) == pytest.approx(-1.0)

    def test_int16_32767_to_float_below_1(self):
        assert int16_to_float32(np.int16(PCM_MAX_INT16)) < 1.0

    def test_int16_to_float32_accepts_scalar_and_list(self):
        scalar = int16_to_float32(PCM_MAX_INT16)
        values = int16_to_float32([PCM_MIN_INT16, 0, PCM_MAX_INT16])

        assert scalar == pytest.approx(PCM_MAX_INT16 / PCM_SCALE_FACTOR)
        assert values.dtype == np.float32
        assert np.allclose(values, np.array([-1.0, 0.0, PCM_MAX_INT16 / PCM_SCALE_FACTOR], dtype=np.float32))

    def test_float32_to_int16_accepts_scalar_and_list(self):
        scalar = float32_to_int16(1.0)
        values = float32_to_int16([1.0, 0.0, -1.0])

        assert scalar == PCM_MAX_INT16
        assert values.dtype == np.int16
        assert np.array_equal(values, np.array([PCM_MAX_INT16, 0, PCM_MIN_INT16], dtype=np.int16))

    def test_to_int16_safe_float32(self):
        result = to_int16_safe(np.array([0.5, -0.5], dtype=np.float32))
        assert result.dtype == np.int16
        assert result[0] > 0 and result[1] < 0

    def test_to_int16_safe_accepts_python_sequences(self):
        scalar_float = to_int16_safe(0.5)
        scalar_int = to_int16_safe(PCM_MAX_INT16)
        float_values = to_int16_safe([0.5, -0.5])
        int_values = to_int16_safe([PCM_MIN_INT16, 0, PCM_MAX_INT16])

        assert int(scalar_float) == 16384
        assert int(scalar_int) == PCM_MAX_INT16
        assert float_values.dtype == np.int16
        assert np.array_equal(int_values, np.array([PCM_MIN_INT16, 0, PCM_MAX_INT16], dtype=np.int16))

    def test_to_int16_safe_int16(self):
        orig = np.array([-100, 200], dtype=np.int16)
        result = to_int16_safe(orig)
        assert result.dtype == np.int16
        assert np.array_equal(result, orig)

    def test_to_int16_safe_int32_clips(self):
        """int32 超出 int16 范围的值应被 clip 而非回绕"""
        orig = np.array([-100000, 0, 200, 50000, 32768], dtype=np.int32)
        result = to_int16_safe(orig)
        assert result.dtype == np.int16
        assert result[0] == PCM_MIN_INT16  # -100000 → -32768
        assert result[2] == 200            # 200 → 200 (in range)
        assert result[3] == PCM_MAX_INT16  # 50000 → 32767
        assert result[4] == PCM_MAX_INT16  # 32768 → 32767

    def test_to_int16_safe_uint16_clips(self):
        """uint16 > 32767 应 clip 而非回绕"""
        orig = np.array([0, 32767, 32768, 65535], dtype=np.uint16)
        result = to_int16_safe(orig)
        assert result.dtype == np.int16
        assert result[0] == 0
        assert result[1] == 32767
        assert result[2] == 32767  # 32768 → clip to 32767
        assert result[3] == 32767  # 65535 → clip to 32767

    def test_to_int16_safe_empty(self):
        """空数组应正常返回"""
        result = to_int16_safe(np.array([], dtype=np.float32))
        assert result.dtype == np.int16
        assert len(result) == 0

    # ── 硬断言 2: Round-trip 精度 ≤ 1/32768 ─────────────────────

    def test_roundtrip_precision(self):
        """float32 → int16 → float32 往返误差 ≤ 1/32768"""
        rng = np.random.default_rng(42)
        original = rng.uniform(-1.0, 1.0, 5000).astype(np.float32)
        recovered = int16_to_float32(float32_to_int16(original))
        max_err = float(np.max(np.abs(original.astype(np.float64) - recovered.astype(np.float64))))
        assert max_err <= 1.0 / PCM_SCALE_FACTOR, f"最大误差 {max_err:.7f} > 1/32768"

    def test_roundtrip_array(self):
        arr = np.linspace(-1.0, 1.0, 1000, dtype=np.float32)
        recovered = int16_to_float32(float32_to_int16(arr))
        errors = np.abs(arr.astype(np.float64) - recovered.astype(np.float64))
        assert np.all(errors <= 1.0 / PCM_SCALE_FACTOR)

    # ── 硬断言 3: Opus 编码/解码 round-trip ──────────────────────

    def test_opus_roundtrip(self):
        pcm = np.array([0, 100, -200, 32767, -32768, 0], dtype=np.int16)
        opus = encode_opus(pcm, frame_size=960)
        assert isinstance(opus, bytes)
        assert len(opus) > 0
        decoded = decode_opus(opus, frame_size=960)
        assert decoded.dtype == np.int16
        assert len(decoded) == 960

    # ── WAV 一致性校验 ────────────────────────────────────────────

    def test_assert_wav_consistent_ok(self):
        data = np.zeros(960, dtype=np.int16)
        assert_wav_consistent(data, PCM_SR)

    def test_assert_wav_consistent_bad_dtype(self):
        with pytest.raises(AssertionError, match="int16"):
            assert_wav_consistent(np.zeros(960, dtype=np.float32), PCM_SR)

    def test_assert_wav_consistent_bad_sr(self):
        with pytest.raises(AssertionError, match="16000"):
            assert_wav_consistent(np.zeros(960, dtype=np.int16), 44100)

    def test_assert_wav_consistent_stereo(self):
        with pytest.raises(AssertionError, match="mono"):
            assert_wav_consistent(np.zeros((960, 2), dtype=np.int16), PCM_SR)
