#!/usr/bin/env python3
"""TTS 适配器层 — 抽象适配器基类 + MiniMax 具体实现。

架构说明：
    StandardTTSVoiceParams (标准化参数，引擎无关)
        ↓
    TTSAdapter.synthesize()     (抽象接口)
        ↓
    MiniMaxAdapter._build_request()  (引擎特定映射)
        ↓
    MiniMax API

添加新引擎的步骤：
    1. 继承 TTSAdapter 实现 synthesize()
    2. 在 VOICE_MAP 中为每个标准音色添加映射
    3. 在 create_adapter() 中注册新引擎
"""

from __future__ import annotations

import json
import os
import re
import ssl
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, Optional

from dotenv import load_dotenv
from tts_types import (
    PRESET_DEFS,
    StandardTTSVoiceParams,
    get_preset_def,
    resolve_preset_id,
)


# ═══════════════════════════════════════════════════════════════
# 翻译工具 — 用于中文输入 → 英文语音的跨语言合成
# ═══════════════════════════════════════════════════════════════


def _has_chinese(text: str) -> bool:
    """检测文本是否包含中文字符。"""
    return bool(re.search(r'[\u4e00-\u9fff]', text))


def _translate_to_english(text: str) -> str:
    """将中文文本翻译为英文。

    使用 deep-translator (Google Translate 后端)。
    如果翻译失败或文本不包含中文，返回原文。
    """
    if not _has_chinese(text):
        return text  # 已经是英文，无需翻译
    try:
        from deep_translator import GoogleTranslator
        translated = GoogleTranslator(source='zh-CN', target='en').translate(text)
        if translated and translated.strip():
            return translated
    except Exception as exc:
        print(f"[TTS] 翻译失败 (fallback to original): {exc}")
    return text  # 翻译失败，返回原文


# ═══════════════════════════════════════════════════════════════
# 抽象适配器基类
# ═══════════════════════════════════════════════════════════════


class TTSAdapterError(Exception):
    """TTS 适配层异常。"""


class TTSAdapter(ABC):
    """TTS 适配器抽象基类。

    所有具体 TTS 引擎适配器必须实现此接口。
    """

    @abstractmethod
    def synthesize(self, params: StandardTTSVoiceParams) -> bytes:
        """合成语音，返回音频二进制数据。

        Args:
            params: 标准化 TTS 参数

        Returns:
            音频二进制数据 (MP3/WAV 等)

        Raises:
            TTSAdapterError: 合成失败时抛出
        """
        ...

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """返回引擎名称（如 'minimax', 'azure'）。"""

    @classmethod
    @abstractmethod
    def list_engine_voices(cls) -> dict[str, str]:
        """返回此引擎支持的所有音色映射：{preset_id: engine_voice_id}。"""


# ═══════════════════════════════════════════════════════════════
# MiniMax 适配器
# ═══════════════════════════════════════════════════════════════


def _load_minimax_credentials() -> tuple[str, str]:
    """从 chatbot .env 加载 MiniMax API Key 和 Group ID。

    使用 override=True 确保不会被 stt-test-tool/.env 中的占位值覆盖。
    """
    env_path = Path(__file__).resolve().parent.parent.parent / "chatbot" / ".env"
    load_dotenv(str(env_path), override=True)
    api_key = os.getenv("MINIMAX_API_KEY", "")
    group_id = os.getenv("MINIMAX_GROUP_ID", "")
    return api_key, group_id


class MiniMaxAdapter(TTSAdapter):
    """MiniMax TTS 适配器。

    将 StandardTTSVoiceParams 映射为 MiniMax API 请求参数。
    """

    MODEL = "speech-2.6-turbo"
    API_URL = "https://api.minimax.chat/v1/t2a_v2"

    # ══════════════════════════════════════════════════════════
    # 音色映射表：标准化 preset_id → MiniMax 实际 voice_id
    #
    # MiniMax 官方支持的中文儿童音色（2026-05）:
    #   clever_boy     - 聪明男童
    #   cute_boy       - 可爱男童
    #   lovely_girl    - 萌萌女童
    #   pure-hearted_boy - 清澈邻家弟弟
    #   innocent_boy   - 纯真学弟
    #   female-tianmei - 甜美女生（chatbot 项目已验证）
    #   male-qn-qingse - 青涩男生（测试脚本已验证）
    #
    # MiniMax 官方支持的英文音色（取自 system-voice-id 文档）:
    #   Cute_Elf                  - 可爱精灵（适合儿童）
    #   Sweet_Girl                - 甜美女孩
    #   Attractive_Girl           - 有魅力的女孩
    #   English_Whispering_girl   - 耳语女孩
    #   English_Graceful_Lady     - 优雅女士
    #   English_Gentle-voiced_man - 温柔男性
    #   Rudolph                   - 鲁道夫（角色音）
    # ══════════════════════════════════════════════════════════
    VOICE_MAP: dict[str, str] = {
        "boy_lively": "clever_boy",          # 聪明男童 → 活泼
        "boy_gentle": "pure-hearted_boy",     # 清澈邻家弟弟 → 温柔
        "boy_naughty": "cute_boy",            # 可爱男童 → 调皮
        "boy_shy": "innocent_boy",            # 纯真学弟 → 害羞
        "girl_cute": "lovely_girl",           # 萌萌女童 → 可爱
        "girl_lively": "female-tianmei",      # 甜美女生 → 活泼
        "girl_gentle": "lovely_girl",         # 萌萌女童 → 温柔
        "girl_naughty": "female-tianmei",     # 甜美女生 → 俏皮
    }

    # 英文音色映射（语言= en 时使用）
    # 注意：英文 voice_id 大小写敏感，需精确匹配 MiniMax 系统音色 ID
    EN_VOICE_MAP: dict[str, str] = {
        "boy_lively": "Cute_Elf",                # 可爱精灵 → 活泼男童
        "boy_gentle": "English_Gentle-voiced_man",  # 温柔男性 → 温柔男童
        "boy_naughty": "Rudolph",                # 鲁道夫 → 调皮男童
        "boy_shy": "English_Whispering_girl",    # 耳语 → 害羞
        "girl_cute": "Sweet_Girl",               # 甜美女孩 → 可爱女童
        "girl_lively": "Attractive_Girl",         # 有魅力女孩 → 活泼女童
        "girl_gentle": "English_Graceful_Lady",   # 优雅女士 → 温柔女童
        "girl_naughty": "Cute_Elf",               # 可爱精灵 → 俏皮女童
    }

    def __init__(self):
        self._api_key, self._group_id = _load_minimax_credentials()
        if not self._api_key or not self._group_id:
            raise TTSAdapterError(
                "MiniMax API Key 或 Group ID 未配置，请检查 chatbot/.env"
            )

    @property
    def engine_name(self) -> str:
        return "minimax"

    @classmethod
    def list_engine_voices(cls) -> dict[str, str]:
        return dict(cls.VOICE_MAP)

    def get_voice_id(self, preset_id: str, fallback_gender: str = "girl", use_en: bool = False) -> str:
        """根据预设 ID 获取 MiniMax voice_id。

        Args:
            preset_id: 标准化音色标识（如 'girl_cute'）
            fallback_gender: 兜底性别
            use_en: 是否使用英文音色
        """
        voice_map = self.EN_VOICE_MAP if use_en else self.VOICE_MAP
        voice_id = voice_map.get(preset_id)
        if voice_id:
            return voice_id
        # 兜底
        if use_en:
            return "Sweet_Girl" if fallback_gender == "girl" else "Cute_Elf"
        if fallback_gender == "boy":
            return "male-qn-qingse"
        return "female-tianmei"

    def _normalize_params(self, params: StandardTTSVoiceParams) -> dict:
        """将标准化参数映射为 MiniMax API 的 voice_setting。"""
        is_en = params.language == "en"
        preset_id = resolve_preset_id(params.gender, params.personality)
        voice_id = self.get_voice_id(preset_id, params.gender, use_en=is_en)

        # MiniMax volume: 0.1~10.0，标准化 volume: 0.0~1.0
        minimax_volume = max(0.1, min(10.0, params.volume * 10.0))

        return {
            "voice_id": voice_id,
            "speed": max(0.5, min(2.0, params.speed)),
            "volume": minimax_volume,
            "pitch": max(-12, min(12, params.pitch)),
            "emotion": params.emotion,
        }

    def synthesize(self, params: StandardTTSVoiceParams) -> bytes:
        """调用 MiniMax TTS API 合成语音。

        支持跨语言合成：
        当 language='en' 且文本包含中文时，自动翻译为英文再合成。
        """
        # 跨语言翻译：中文输入 → 英文语音
        text = params.text
        if params.language == "en" and _has_chinese(text):
            translated = _translate_to_english(text)
            if translated != text:
                print(f"[TTS] 中文→英文翻译: '{text[:40]}...' → '{translated[:40]}...'")
                text = translated

        voice_settings = self._normalize_params(params)

        request_data = {
            "model": self.MODEL,
            "text": text,
            "stream": False,
            "voice_setting": voice_settings,
            "audio_setting": {
                "sample_rate": 24000,
                "format": "mp3",
                "channel": 1,
            },
        }

        url = f"{self.API_URL}?GroupId={self._group_id}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        ctx = ssl.create_default_context()
        req = urllib.request.Request(
            url,
            data=json.dumps(request_data, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=60, context=ctx) as resp:
                resp_data = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="replace")
            raise TTSAdapterError(
                f"MiniMax API HTTP {e.code}: {error_body[:500]}"
            )
        except urllib.error.URLError as e:
            raise TTSAdapterError(f"MiniMax API 网络错误: {e.reason}")
        except json.JSONDecodeError as e:
            raise TTSAdapterError(f"MiniMax API 响应解析失败: {e}")
        except Exception as e:
            raise TTSAdapterError(f"MiniMax API 调用异常: {e}")

        base_resp = resp_data.get("base_resp", {})
        if base_resp.get("status_code", 0) != 0:
            err_msg = base_resp.get("status_msg", "未知错误")
            raise TTSAdapterError(
                f"MiniMax API 错误 (code={base_resp.get('status_code')}): {err_msg}"
            )

        audio_hex = resp_data.get("data", {}).get("audio", "")
        if not audio_hex:
            raise TTSAdapterError("MiniMax 返回的音频数据为空")

        try:
            return bytes.fromhex(audio_hex)
        except ValueError as e:
            raise TTSAdapterError(f"音频数据解码失败: {e}")


# ═══════════════════════════════════════════════════════════════
# 适配器工厂 & 注册表
# ═══════════════════════════════════════════════════════════════

_ADAPTER_REGISTRY: dict[str, type[TTSAdapter]] = {
    "minimax": MiniMaxAdapter,
}

# 默认引擎
_DEFAULT_ENGINE = "minimax"


def register_adapter(engine: str, adapter_cls: type[TTSAdapter]) -> None:
    """注册一个新的 TTS 适配器。"""
    _ADAPTER_REGISTRY[engine] = adapter_cls


def create_adapter(engine: Optional[str] = None) -> TTSAdapter:
    """创建 TTS 适配器实例。

    Args:
        engine: 引擎名称，None 则使用默认引擎 ('minimax')

    Returns:
        TTSAdapter 实例

    Raises:
        TTSAdapterError: 引擎未注册或初始化失败
    """
    engine = engine or _DEFAULT_ENGINE
    cls = _ADAPTER_REGISTRY.get(engine)
    if cls is None:
        raise TTSAdapterError(
            f"不支持的 TTS 引擎: '{engine}'，"
            f"可用引擎: {list(_ADAPTER_REGISTRY.keys())}"
        )
    try:
        return cls()
    except Exception as e:
        raise TTSAdapterError(f"初始化 TTS 引擎 '{engine}' 失败: {e}")


def list_supported_engines() -> list[str]:
    """列出所有已注册的 TTS 引擎。"""
    return list(_ADAPTER_REGISTRY.keys())


def get_voice_map(engine: str) -> dict[str, str]:
    """获取指定引擎的音色映射表。"""
    cls = _ADAPTER_REGISTRY.get(engine)
    if cls is None:
        return {}
    return cls.list_engine_voices()
