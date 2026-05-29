#!/usr/bin/env python3
"""TTS 标准化参数类型定义 — 引擎无关的抽象参数层。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


# ── 标准化情感标签 ──────────────────────────────────────────────
STANDARD_EMOTIONS = [
    "neutral", "happy", "sad", "angry",
    "surprised", "fearful", "disgusted",
]

# ── 标准化性别标签 ──────────────────────────────────────────────
STANDARD_GENDERS = ["boy", "girl", "neutral"]

# ── 标准化性格标签 ──────────────────────────────────────────────
STANDARD_PERSONALITIES = [
    "lively", "gentle", "naughty", "shy", "cute", "calm",
]


@dataclass
class StandardTTSVoiceParams:
    """引擎无关的标准化 TTS 语音参数。

    所有参数在引擎之间通过 Adapter 进行映射和校验。
    前端 / 业务代码只与标准化参数交互，不直接依赖任何引擎。
    """

    text: str = ""
    voice: str = "girl_cute"       # 标准化音色标识（见 PRESET_VOICE_MAP）
    speed: float = 1.0             # 0.5 ~ 2.0
    pitch: int = 0                 # -12 ~ 12 (半音)
    volume: float = 1.0            # 0.0 ~ 1.0 (归一化，引擎适配层做范围映射)
    emotion: str = "happy"         # 标准化情感标签
    gender: str = "girl"           # boy / girl
    personality: str = "cute"      # 性格标签
    language: str = "zh"           # 输出语种: zh / en

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "voice": self.voice,
            "speed": self.speed,
            "pitch": self.pitch,
            "volume": self.volume,
            "emotion": self.emotion,
            "gender": self.gender,
            "personality": self.personality,
            "language": self.language,
        }


@dataclass
class VoicePresetDef:
    """音色预设定义（引擎无关）。"""
    preset_id: str
    name: str
    gender: str
    personality: str
    description: str
    default_emotion: str = "happy"
    default_speed: float = 1.0


# ── 引擎无关的音色预设注册表 ─────────────────────────────────────
# 这里定义的是"标准化音色"，每个 preset_id 对应一个或多个
# 适配器中的具体 voice_id（见相应适配器的 VOICE_MAP）。
PRESET_DEFS: dict[str, VoicePresetDef] = {
    "boy_lively": VoicePresetDef(
        preset_id="boy_lively", name="活泼小男孩",
        gender="boy", personality="lively",
        description="精力充沛、爱笑的小男孩",
        default_emotion="happy", default_speed=1.1,
    ),
    "boy_gentle": VoicePresetDef(
        preset_id="boy_gentle", name="温柔小男孩",
        gender="boy", personality="gentle",
        description="安静温柔的小男孩",
        default_emotion="neutral", default_speed=0.9,
    ),
    "boy_naughty": VoicePresetDef(
        preset_id="boy_naughty", name="调皮小男孩",
        gender="boy", personality="naughty",
        description="古灵精怪、爱搞怪的小男孩",
        default_emotion="surprised", default_speed=1.2,
    ),
    "boy_shy": VoicePresetDef(
        preset_id="boy_shy", name="害羞小男孩",
        gender="boy", personality="shy",
        description="轻声细语、腼腆的小男孩",
        default_emotion="neutral", default_speed=0.8,
    ),
    "girl_cute": VoicePresetDef(
        preset_id="girl_cute", name="可爱小女生",
        gender="girl", personality="cute",
        description="甜美可爱的小女生",
        default_emotion="happy", default_speed=1.0,
    ),
    "girl_lively": VoicePresetDef(
        preset_id="girl_lively", name="活泼小女生",
        gender="girl", personality="lively",
        description="开朗活泼、爱说话的小女生",
        default_emotion="happy", default_speed=1.15,
    ),
    "girl_gentle": VoicePresetDef(
        preset_id="girl_gentle", name="温柔小女生",
        gender="girl", personality="gentle",
        description="文静温柔的小女生",
        default_emotion="neutral", default_speed=0.85,
    ),
    "girl_naughty": VoicePresetDef(
        preset_id="girl_naughty", name="俏皮小女生",
        gender="girl", personality="naughty",
        description="俏皮机灵的小女生",
        default_emotion="surprised", default_speed=1.1,
    ),
}


def resolve_preset_id(gender: str, personality: str) -> str:
    """根据性别+性格解析标准化音色标识。"""
    return f"{gender}_{personality}"


def get_preset_def(gender: str, personality: str) -> Optional[VoicePresetDef]:
    """获取匹配的音色预设定义。"""
    return PRESET_DEFS.get(resolve_preset_id(gender, personality))
