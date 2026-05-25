#!/usr/bin/env python3
"""TTS 语音生成服务 — 基于 TTS 适配器架构。

对外接口保持不变（generate_speech, save_to_database 等），
内部使用 tts_adapter.MiniMaxAdapter 进行引擎调用。

如果以后需要切换 TTS 引擎：
  1. 在 tts_adapter.py 中注册新适配器
  2. 修改此处 DEFAULT_ENGINE 即可
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import time
import uuid
from pathlib import Path
from typing import Optional

from tts_adapter import (
    TTSAdapter,
    TTSAdapterError,
    create_adapter,
    get_voice_map,
    list_supported_engines,
)
from tts_types import (
    PRESET_DEFS,
    StandardTTSVoiceParams,
    get_preset_def,
    resolve_preset_id,
)


def _normalize_audio_path(path: str) -> Path:
    """将 Windows 盘符路径（D:\\...）转为当前平台可访问的 Path。"""
    p = Path(path)
    if p.exists() or not path:
        return p
    if len(path) >= 3 and path[1] == ':':
        drive = path[0].lower()
        rest = path[2:].replace('\\', '/')
        wsl_p = Path(f"/mnt/{drive}{rest}")
        if wsl_p.exists():
            return wsl_p
    return p


def _backfill_duration(audio_id: int, audio_path: str, mysql_config: dict) -> float:
    """如果 duration_sec 为 0，尝试用 ffprobe 计算并更新数据库。返回计算后的时长（可能仍为 0）。"""
    path_obj = _normalize_audio_path(audio_path)
    if not path_obj or not path_obj.exists():
        return 0.0
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path_obj)],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0 and result.stdout.strip():
            duration = round(float(result.stdout.strip()), 2)
            import pymysql
            conn = pymysql.connect(
                host=mysql_config.get("host", "localhost"),
                user=mysql_config.get("user", "root"),
                password=mysql_config.get("password", ""),
                database=mysql_config.get("database", "ZebbieDb"),
                charset="utf8mb4",
            )
            cur = conn.cursor()
            cur.execute(
                "UPDATE ZebGeneratedAudio SET DurationSec = %s WHERE Id = %s AND (DurationSec IS NULL OR DurationSec = 0)",
                (duration, audio_id),
            )
            conn.commit()
            cur.close()
            conn.close()
            return duration
    except Exception:
        pass
    return 0.0


# ═══════════════════════════════════════════════════════════════
# 全局配置
# ═══════════════════════════════════════════════════════════════

_DEFAULT_ENGINE = "minimax"
_TTS_ADAPTER: Optional[TTSAdapter] = None


def _get_adapter() -> TTSAdapter:
    """懒初始化 TTS 适配器。"""
    global _TTS_ADAPTER
    if _TTS_ADAPTER is None:
        _TTS_ADAPTER = create_adapter(_DEFAULT_ENGINE)
    return _TTS_ADAPTER


# ═══════════════════════════════════════════════════════════════
# 导出常量 — 从标准类型层派生，保持对 server.py 的兼容
# ═══════════════════════════════════════════════════════════════

# 儿童语音预设（8种）
CHILD_VOICE_PRESETS: dict[str, dict] = {
    pid: {
        "voice_id": "",  # 由适配器运行时解析
        "name": preset.name,
        "gender": preset.gender,
        "personality": preset.personality,
        "default_emotion": preset.default_emotion,
        "description": preset.description,
        "default_speed": preset.default_speed,
    }
    for pid, preset in PRESET_DEFS.items()
}

GENDER_OPTIONS = [
    {"id": "boy", "label": "👦 男孩"},
    {"id": "girl", "label": "👧 女孩"},
]

PERSONALITY_OPTIONS = [
    {"id": "lively", "label": "活泼"},
    {"id": "gentle", "label": "温柔"},
    {"id": "naughty", "label": "调皮"},
    {"id": "shy", "label": "害羞"},
    {"id": "cute", "label": "可爱"},
    {"id": "calm", "label": "冷静"},
]

EMOTION_OPTIONS = [
    {"id": "neutral", "label": "😐 中性"},
    {"id": "happy", "label": "😊 开心"},
    {"id": "sad", "label": "😢 悲伤"},
    {"id": "angry", "label": "😠 生气"},
    {"id": "surprised", "label": "😮 惊讶"},
    {"id": "fearful", "label": "😨 害怕"},
    {"id": "disgusted", "label": "🤢 厌恶"},
]

# ── 儿童常用短语库 ─────────────────────────────────────────────
CHILD_PHRASES = {
    "greeting": [
        "你好呀！", "早上好！", "今天天气真好！", "见到你真开心！", "嗨，我们来玩吧！",
    ],
    "question": [
        "这是什么呀？", "为什么天是蓝色的？", "我可以玩一下吗？",
        "你能给我讲个故事吗？", "这个怎么玩呀？",
    ],
    "emotion": [
        "我好开心啊！", "我有点难过...", "哇，太神奇了！",
        "我不喜欢这个...", "哈哈哈，真有趣！",
    ],
    "story_fragment": [
        "从前有一只小兔子...", "有一天，小明去了公园...",
        "森林里住着一只大熊...", "很久很久以前...", "在一个美丽的村庄里...",
    ],
    "daily": [
        "我要去上学啦！", "妈妈叫我吃饭了。", "我想看电视。",
        "我们一起玩游戏吧！", "我今天学到了新知识。",
    ],
}


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════


def generate_random_text(category: str = "mixed") -> str:
    """随机生成儿童语音文本。"""
    if category == "mixed":
        all_phrases = []
        for phrases in CHILD_PHRASES.values():
            all_phrases.extend(phrases)
        return random.choice(all_phrases)
    phrases = CHILD_PHRASES.get(category, CHILD_PHRASES["greeting"])
    return random.choice(phrases)


def generate_random_voice_params() -> dict:
    """随机生成语音参数组合。"""
    return {
        "gender": random.choice(["boy", "girl"]),
        "personality": random.choice(["lively", "gentle", "naughty", "shy", "cute"]),
        "tone": random.choice(["happy", "neutral", "surprised", "sad"]),
        "speed": round(random.uniform(0.8, 1.3), 2),
        "pitch": random.randint(-6, 6),
        "volume": round(random.uniform(0.8, 1.2), 2),
    }


def get_preset(gender: str, personality: str) -> Optional[dict]:
    """获取匹配的语音预设。"""
    preset_def = get_preset_def(gender, personality)
    if preset_def is None:
        return None
    return {
        "voice_id": "",  # 由适配器解析
        "name": preset_def.name,
        "gender": preset_def.gender,
        "personality": preset_def.personality,
        "default_emotion": preset_def.default_emotion,
        "description": preset_def.description,
        "default_speed": preset_def.default_speed,
    }


# ═══════════════════════════════════════════════════════════════
# 核心语音生成（使用适配器）
# ═══════════════════════════════════════════════════════════════


def generate_speech(
    text: str,
    gender: str = "girl",
    personality: str = "cute",
    tone: str = "happy",
    speed: float = 1.0,
    pitch: int = 0,
    volume: float = 1.0,
    language: str = "zh",
    voice_id: Optional[str] = None,
    cache_dir: Optional[Path] = None,
) -> dict:
    """生成语音并返回文件信息和参数。

    内部使用 TTS 适配器，不直接依赖任何具体引擎。
    """
    # 构建标准化参数
    params = StandardTTSVoiceParams(
        text=text,
        voice=resolve_preset_id(gender, personality),
        speed=speed,
        pitch=pitch,
        volume=volume,
        emotion=tone,
        gender=gender,
        personality=personality,
        language=language,
    )

    try:
        adapter = _get_adapter()
        audio_data = adapter.synthesize(params)
    except TTSAdapterError as e:
        return {
            "success": False,
            "error": str(e),
            "audio_data": None,
            "file_path": None,
            "file_size": 0,
            "duration_sec": 0,
            "voice_id": voice_id or "",
        }

    file_path = None
    file_size = len(audio_data)
    duration_sec = 0

    # 获取适配器解析的实际 voice_id（用于返回给调用方）
    resolved_voice_id = voice_id or ""

    # 保存到缓存目录
    if cache_dir:
        cache_dir = Path(cache_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        file_name = f"tts_{uuid.uuid4().hex[:12]}.mp3"
        file_path = cache_dir / file_name
        file_path.write_bytes(audio_data)

        # 尝试估算时长
        try:
            result = subprocess.run(
                ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
                 "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                duration_sec = round(float(result.stdout.strip()), 2)
        except Exception:
            pass

        # 如果有预设，从 VOICE_MAP 获取被适配的 voice_id
        try:
            voice_map = get_voice_map(_DEFAULT_ENGINE)
            resolved_voice_id = voice_map.get(params.voice, "")
        except Exception:
            pass

    return {
        "success": True,
        "error": None,
        "audio_data": audio_data,
        "file_path": str(file_path) if file_path else None,
        "file_size": file_size,
        "duration_sec": duration_sec,
        "voice_id": resolved_voice_id,
    }


# ═══════════════════════════════════════════════════════════════
# 数据库操作（保持不变）
# ═══════════════════════════════════════════════════════════════


def _create_mysql_connection(mysql_config: dict):
    """创建 MySQL 连接。"""
    import pymysql
    return pymysql.connect(
        host=mysql_config.get("host", "localhost"),
        user=mysql_config.get("user", "root"),
        password=mysql_config.get("password", ""),
        database=mysql_config.get("database", "ZebbieDb"),
        charset="utf8mb4",
    )


def save_to_database(
    mysql_config: dict,
    name: str,
    text: str,
    gender: str,
    personality: str,
    tone: str,
    speed: float,
    pitch: int,
    volume: float,
    voice_id: str,
    audio_path: str,
    file_size: int,
    duration_sec: float,
    params_json: str,
    figurine_id: str = "",
) -> Optional[int]:
    """将生成的语音记录持久化到 MySQL。"""
    import pymysql

    try:
        conn = _create_mysql_connection(mysql_config)
        cur = conn.cursor()

        cur.execute("""
            CREATE TABLE IF NOT EXISTS ZebGeneratedAudio (
                Id INT AUTO_INCREMENT PRIMARY KEY,
                Name VARCHAR(255) NOT NULL DEFAULT '' COMMENT '用户自定义名称',
                Text TEXT NOT NULL COMMENT '合成文本',
                Gender VARCHAR(20) DEFAULT '' COMMENT '性别: boy/girl/neutral',
                Personality VARCHAR(50) DEFAULT '' COMMENT '性格标签',
                Tone VARCHAR(50) DEFAULT '' COMMENT '情感/语气',
                Speed FLOAT DEFAULT 1.0 COMMENT '语速倍率 0.5-2.0',
                Pitch INT DEFAULT 0 COMMENT '音调 -12~12',
                Volume FLOAT DEFAULT 1.0 COMMENT '音量 0.1-10.0',
                TtsType VARCHAR(50) DEFAULT 'minimax' COMMENT 'TTS引擎',
                TtsVoiceId VARCHAR(255) DEFAULT '' COMMENT '音色ID',
                AudioPath VARCHAR(500) DEFAULT '' COMMENT '本地音频路径',
                DurationSec FLOAT DEFAULT 0 COMMENT '时长(秒)',
                FileSize INT DEFAULT 0 COMMENT '文件大小(字节)',
                ParamsJson TEXT COMMENT '完整生成参数字符串',
                CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
                IsDeleted TINYINT DEFAULT 0
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
        """)

        # ── 中间表方案：FigurineId 不侵入原表，通过中间表关联 ──
        cur.execute("""
            CREATE TABLE IF NOT EXISTS ZebFigurineAudioRef (
                Id INT AUTO_INCREMENT PRIMARY KEY,
                FigurineId VARCHAR(100) NOT NULL COMMENT '角色 ID',
                GeneratedAudioId INT NOT NULL COMMENT 'TTS 生成音频 ID',
                CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (GeneratedAudioId) REFERENCES ZebGeneratedAudio(Id),
                INDEX idx_figurine_id (FigurineId),
                INDEX idx_audio_id (GeneratedAudioId)
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                COMMENT='角色与 TTS 音频关联表（纯中间表，零侵入原表）'
        """)

        cur.execute("""
            INSERT INTO ZebGeneratedAudio
                (Name, Text, Gender, Personality, Tone, Speed, Pitch, Volume,
                 TtsType, TtsVoiceId, AudioPath, DurationSec, FileSize, ParamsJson)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            name, text, gender, personality, tone, speed, pitch, volume,
            "minimax", voice_id, audio_path, duration_sec, file_size, params_json,
        ))

        inserted_id = cur.lastrowid

        # 如果有关联角色，写入中间表
        if figurine_id and inserted_id:
            cur.execute("""
                INSERT INTO ZebFigurineAudioRef (FigurineId, GeneratedAudioId)
                VALUES (%s, %s)
            """, (figurine_id, inserted_id))

        conn.commit()
        cur.close()
        conn.close()
        return inserted_id
    except Exception as exc:
        print(f"[TTS] 持久化到数据库失败: {exc}")
        return None


def query_generated_audio(
    mysql_config: dict,
    limit: int = 50,
    offset: int = 0,
    audio_id: Optional[int] = None,
    figurine_id: Optional[str] = None,
) -> list:
    """查询已生成的语音记录（通过 ZebFigurineAudioRef 中间表关联角色）。"""
    results = []
    try:
        conn = _create_mysql_connection(mysql_config)
        cur = conn.cursor()

        # 全部使用 LEFT JOIN 中间表，统一返回格式（含 figurine_id）
        base_cols = (
            "a.Id, a.Name, a.Text, a.Gender, a.Personality, a.Tone, "
            "a.Speed, a.Pitch, a.Volume, a.TtsType, a.TtsVoiceId, "
            "a.AudioPath, a.DurationSec, a.FileSize, a.ParamsJson, a.CreatedAt, "
            "COALESCE(r.FigurineId, '') AS FigurineId"
        )

        if audio_id:
            cur.execute(f"""
                SELECT {base_cols}
                FROM ZebGeneratedAudio a
                LEFT JOIN ZebFigurineAudioRef r ON r.GeneratedAudioId = a.Id
                WHERE a.Id = %s AND a.IsDeleted = 0
            """, (audio_id,))
        elif figurine_id:
            cur.execute(f"""
                SELECT {base_cols}
                FROM ZebGeneratedAudio a
                INNER JOIN ZebFigurineAudioRef r ON r.GeneratedAudioId = a.Id
                WHERE r.FigurineId = %s AND a.IsDeleted = 0
                ORDER BY a.CreatedAt DESC
                LIMIT %s OFFSET %s
            """, (figurine_id, limit, offset))
        else:
            cur.execute(f"""
                SELECT {base_cols}
                FROM ZebGeneratedAudio a
                LEFT JOIN ZebFigurineAudioRef r ON r.GeneratedAudioId = a.Id
                WHERE a.IsDeleted = 0
                ORDER BY a.CreatedAt DESC
                LIMIT %s OFFSET %s
            """, (limit, offset))

        for row in cur.fetchall():
            rec = {
                "id": row[0], "name": row[1], "text": row[2],
                "gender": row[3], "personality": row[4], "tone": row[5],
                "speed": row[6], "pitch": row[7], "volume": row[8],
                "tts_type": row[9], "tts_voice_id": row[10],
                "audio_path": row[11], "duration_sec": row[12],
                "file_size": row[13],
                "params_json": row[14],
                "created_at": row[15].isoformat() if row[15] else "",
                "figurine_id": row[16],
            }
            if not rec["duration_sec"] and rec["audio_path"]:
                rec["duration_sec"] = _backfill_duration(rec["id"], rec["audio_path"], mysql_config)
            results.append(rec)

        cur.close()
        conn.close()
    except Exception as exc:
        print(f"[TTS] 查询数据库失败: {exc}")
    return results


def soft_delete_audio(mysql_config: dict, audio_id: int) -> bool:
    """软删除生成的语音记录。"""
    try:
        conn = _create_mysql_connection(mysql_config)
        cur = conn.cursor()
        cur.execute(
            "UPDATE ZebGeneratedAudio SET IsDeleted = 1 WHERE Id = %s",
            (audio_id,),
        )
        conn.commit()
        affected = cur.rowcount
        cur.close()
        conn.close()
        return affected > 0
    except Exception as exc:
        print(f"[TTS] 删除记录失败: {exc}")
        return False


# ═══════════════════════════════════════════════════════════════
# 高级功能：重生成、测试集、对话关联
# ═══════════════════════════════════════════════════════════════


def regenerate_from_params(
    mysql_config: dict,
    audio_id: int,
    cache_dir: Optional[Path] = None,
) -> dict:
    """从数据库中的参数重新生成音频。"""
    records = query_generated_audio(mysql_config=mysql_config, audio_id=audio_id)
    if not records:
        return {"success": False, "error": f"音频 ID {audio_id} 不存在"}

    record = records[0]
    params_str = record.get("params_json", "{}")
    try:
        saved_params = json.loads(params_str)
    except (json.JSONDecodeError, TypeError):
        saved_params = {}

    result = generate_speech(
        text=record["text"],
        gender=saved_params.get("gender", record["gender"]),
        personality=saved_params.get("personality", record["personality"]),
        tone=saved_params.get("tone", record["tone"]),
        speed=float(saved_params.get("speed", record["speed"])),
        pitch=int(saved_params.get("pitch", record["pitch"])),
        volume=float(saved_params.get("volume", record["volume"])),
        cache_dir=cache_dir,
    )

    result["original_params"] = saved_params
    return result


def generate_test_set_for_figurine(
    mysql_config: dict,
    figurine_id: str,
    count_per_variant: int = 3,
    cache_dir: Optional[Path] = None,
) -> list:
    """为指定角色生成测试音频集。"""
    results = []

    variants = [
        {"gender": "boy", "personality": "lively", "tone": "happy"},
        {"gender": "boy", "personality": "gentle", "tone": "neutral"},
        {"gender": "boy", "personality": "naughty", "tone": "surprised"},
        {"gender": "girl", "personality": "cute", "tone": "happy"},
        {"gender": "girl", "personality": "lively", "tone": "happy"},
        {"gender": "girl", "personality": "gentle", "tone": "neutral"},
    ]

    for variant in variants:
        for i in range(count_per_variant):
            text = generate_random_text("mixed")
            params = generate_random_voice_params()

            final_params = {
                **variant,
                "speed": round(params["speed"], 2),
                "pitch": params["pitch"],
                "volume": round(params["volume"], 2),
            }

            name = f"{figurine_id}_test_{variant['gender']}_{variant['personality']}_{i+1}"

            result = generate_speech(
                text=text,
                gender=final_params["gender"],
                personality=final_params["personality"],
                tone=final_params["tone"],
                speed=final_params["speed"],
                pitch=final_params["pitch"],
                volume=final_params["volume"],
                cache_dir=cache_dir,
            )

            if result["success"]:
                params_json_str = json.dumps({**final_params, "text": text}, ensure_ascii=False)
                db_id = save_to_database(
                    mysql_config=mysql_config,
                    name=name, text=text,
                    gender=final_params["gender"],
                    personality=final_params["personality"],
                    tone=final_params["tone"],
                    speed=final_params["speed"],
                    pitch=final_params["pitch"],
                    volume=final_params["volume"],
                    voice_id=result["voice_id"],
                    audio_path=result.get("file_path", ""),
                    file_size=result["file_size"],
                    duration_sec=result["duration_sec"],
                    params_json=params_json_str,
                    figurine_id=figurine_id,
                )
                results.append({"success": True, "id": db_id, "name": name, "variant": variant, "index": i + 1})
            else:
                results.append({"success": False, "error": result["error"], "name": name, "variant": variant, "index": i + 1})

    return results


def link_audio_to_conversation(
    mysql_config: dict,
    transcript_id: int,
    generated_audio_id: int,
    usage_type: str = "input",
    sequence_no: int = 0,
) -> bool:
    """将 TTS 生成的音频关联到对话记录。
    
    使用纯中间表设计，完全不修改原表结构（零侵入）。
    注意：需要先执行数据库迁移脚本创建 ZebConversationAudioRef 表。
    """
    try:
        conn = _create_mysql_connection(mysql_config)
        cur = conn.cursor()

        # 插入关联记录到中间表
        cur.execute("""
            INSERT INTO ZebConversationAudioRef
                (TranscriptId, GeneratedAudioId, UsageType, SequenceNo)
            VALUES (%s, %s, %s, %s)
        """, (transcript_id, generated_audio_id, usage_type, sequence_no))

        conn.commit()
        cur.close()
        conn.close()
        return True
    except Exception as exc:
        print(f"[TTS] 关联音频到对话记录失败: {exc}")
        return False


def query_conversation_audio_refs(
    mysql_config: dict,
    transcript_id: int,
) -> list:
    """查询对话记录关联的所有 TTS 音频引用。"""
    results = []
    try:
        conn = _create_mysql_connection(mysql_config)
        cur = conn.cursor()
        cur.execute("""
            SELECT r.Id, r.TranscriptId, r.GeneratedAudioId, r.UsageType,
                   r.SequenceNo, r.CreatedAt,
                   a.Name, a.Text, a.TtsType, a.TtsVoiceId,
                   a.AudioPath, a.DurationSec
            FROM ZebConversationAudioRef r
            LEFT JOIN ZebGeneratedAudio a ON r.GeneratedAudioId = a.Id
            WHERE r.TranscriptId = %s
            ORDER BY r.SequenceNo ASC, r.CreatedAt ASC
        """, (transcript_id,))
        for row in cur.fetchall():
            results.append({
                "id": row[0], "transcript_id": row[1],
                "generated_audio_id": row[2], "usage_type": row[3],
                "sequence_no": row[4],
                "created_at": row[5].isoformat() if row[5] else "",
                "audio_name": row[6], "audio_text": row[7],
                "tts_type": row[8], "tts_voice_id": row[9],
                "audio_path": row[10], "duration_sec": row[11],
            })
        cur.close()
        conn.close()
    except Exception as exc:
        print(f"[TTS] 查询对话音频引用失败: {exc}")
    return results
