#!/usr/bin/env python3
"""STT 测试平台后端 — 直接复用现有 asr_factory 做语音识别"""

import asyncio
import base64
import json
import logging
import os
import re
import queue
import sys
import subprocess
import threading
import time
import uuid
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse


import soundfile as sf
import uvicorn
import numpy as np
import pcm_utils
import env_scanner
from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ── YAML 驱动的指令规则引擎 ─────────────────────────────
from command_engine import get_engine, reload_engine, RuleMatch

# ── 指令使用统计收集器 ─────────────────────────────
from command_stats import get_collector as _command_stats_collector

# ── 环境变量配置 ──────────────────────────────────────
# ⚠️ 测试平台所有配置仅从 stt-test-tool/.env 读取
# 严禁回退到 chatbot/.env，防止连错库、读错配置
_ENV_FILE = Path(__file__).parent.parent / ".env"
if _ENV_FILE.exists():
    load_dotenv(str(_ENV_FILE), override=True)
    print(f"[Config] 加载配置: {_ENV_FILE}")
else:
    print(f"[Config] [x] 未找到配置文件: {_ENV_FILE}")
    print("[Config] 使用环境变量默认值（仅用于本地快速启动）")

# 是否启用对话追踪功能（默认：测试环境启用，生产环境禁用）
ENABLE_CONVERSATION_TRACKING = os.getenv("ENABLE_CONVERSATION_TRACKING", "true").lower() == "true"
ENVIRONMENT = os.getenv("ENVIRONMENT", "test")  # test / production

# ── MQTT 设备模拟 ──────────────────────────────────────
from mqtt_bridge import simulation_manager, SimulationManager, _resolve_local_mqtt_host, _resolve_mqtt_host, _resolve_mqtt_port

# ── Language 枚举（独立，不依赖 chatbot 项目） ──────────────
from enum import Enum


class Language(Enum):
    ZH = "zh"
    EN = "en"
    JA = "ja"
    KO = "ko"
    YUE = "yue"
    ZH_HK = "zh-hk"


def load_offline_recognizer_from_cache(*args, **kwargs):
    return _get_asr_factory().load_offline_recognizer_from_cache(*args, **kwargs)

# ── 配置审计 ──────────────────────────────────────────
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 所有外部服务配置仅来自 stt-test-tool/.env，无回退
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_USER = os.getenv("MYSQL_USER", "chatbot")
MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "chatbot123")
MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "ZebbieDb")
AWS_REGION = os.getenv("AWS_REGION", "eu-west-2")
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")


def _read_int_env(name: str, default: int) -> int:
    raw = os.getenv(name, str(default))
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


MQTT_BROKER_PROFILE = os.getenv("MQTT_BROKER_PROFILE", "local")
MQTT_HOST = os.getenv("MQTT_HOST", "localhost")
MQTT_PORT = _read_int_env("MQTT_PORT", 1883)
MQTT_ENV = os.getenv("MQTT_ENV", "development")
MQTT_TLS = str(os.getenv("MQTT_TLS", "false")).strip().lower() in {"1", "true", "yes", "on"}

# 启动配置审计：明确告知当前加载了什么配置
logger.info("╔══════════════════════════════════════╗")
logger.info("║      VoicePipe 测试平台 · 配置审计     ║")
logger.info("╠══════════════════════════════════════╣")
logger.info("║ ENVIRONMENT             = %-12s ║", ENVIRONMENT)
logger.info("║ .env 路径               = %-12s ║", _ENV_FILE)
logger.info("╠──────────────────────────────────────╣")
logger.info("║ MySQL: %s@%s/%-12s ║", MYSQL_USER, MYSQL_HOST, MYSQL_DATABASE)
logger.info("║ MQTT:  profile=%s %s:%s (env=%s tls=%s) ║", MQTT_BROKER_PROFILE, MQTT_HOST, MQTT_PORT, MQTT_ENV, MQTT_TLS)
logger.info("║ AWS:   %s/%-20s ║", AWS_REGION, MYSQL_DATABASE)
logger.info("║ MiniMax: %s...%-10s        ║", str(os.getenv("MINIMAX_API_KEY", ""))[:16], str(os.getenv("MINIMAX_API_KEY", ""))[-8:])
logger.info("╚══════════════════════════════════════╝")

# ── MySQL 配置（供各模块共享） ──────────────────────────────
MYSQL_CONFIG = {
    "host": MYSQL_HOST,
    "user": MYSQL_USER,
    "password": MYSQL_PASSWORD,
    "database": MYSQL_DATABASE,
}


def _build_runtime_config_snapshot() -> dict:
    """Build a safe runtime snapshot for debugging environment mismatch issues."""
    return {
        "environment": ENVIRONMENT,
        "conversation_tracking_enabled": ENABLE_CONVERSATION_TRACKING,
        "mqtt": {
            "profile": MQTT_BROKER_PROFILE,
            "host": MQTT_HOST,
            "port": MQTT_PORT,
            "env": MQTT_ENV,
            "tls": MQTT_TLS,
        },
        "mysql": {
            "host": MYSQL_HOST,
            "database": MYSQL_DATABASE,
            "user": MYSQL_USER,
        },
        "env_file": {
            "path": str(_ENV_FILE),
            "exists": _ENV_FILE.exists(),
        },
        "paths": {
            "frontend_dist_exists": _FRONTEND_DIST.exists(),
            "audio_cache": str(CACHE_DIR),
        },
    }

# ── TTS 语音生成 ──────────────────────────────────────────
from tts_service import (  # noqa: E402
    CHILD_VOICE_PRESETS,
    GENDER_OPTIONS,
    PERSONALITY_OPTIONS,
    EMOTION_OPTIONS,
    generate_speech,
    save_to_database,
    query_generated_audio,
    soft_delete_audio,
    generate_random_text,
    generate_random_voice_params,
    generate_test_set_for_figurine,
    regenerate_from_params,
    link_audio_to_conversation,
    query_conversation_audio_refs,
)

# ── 应用 ──────────────────────────────────────────────────
app = FastAPI(title="STT Test Platform", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup_init():
    """Initialize runtime components on app startup."""
    # 初始化 YAML 驱动的指令规则引擎
    try:
        count = get_engine().load()
        logger.info("CommandRuleEngine initialized: %d rules loaded", count)
    except Exception as exc:
        logger.warning("CommandRuleEngine init failed (non-fatal): %s", exc)

    snapshot = _build_runtime_config_snapshot()
    logger.info(
        "Runtime config loaded: env=%s mysql=%s/%s env_file=%s frontend_dist_exists=%s",
        snapshot["environment"],
        snapshot["mysql"]["host"],
        snapshot["mysql"]["database"],
        snapshot["env_file"]["exists"],
        snapshot["paths"]["frontend_dist_exists"],
    )

    simulation_manager._profile_switcher = _switch_mqtt_profile


@app.get("/api/debug/runtime-config", include_in_schema=False)
def runtime_config():
    """Return a sanitized snapshot of the backend runtime configuration."""
    return _build_runtime_config_snapshot()

# ── 路径常量（通过环境变量配置，不依赖 chatbot 项目路径） ──
MODEL_NAME = os.getenv("STT_MODEL_NAME", "sherpa-onnx-sense-voice-zh-en-ja-ko-yue-2024-07-17")
MODEL_DIR = Path(os.getenv("STT_MODEL_DIR", "models")) / MODEL_NAME
TEST_WAVS_DIR = MODEL_DIR / "test_wavs"
CACHE_DIR = Path(__file__).parent / "audio_cache"


def _normalize_audio_path(path: str) -> Path:
    """将 audio_path 转为当前平台可访问的 Path。

    支持双向转换：
    - WSL 上：D:\\... → /mnt/d/...
    - Windows 上：/mnt/d/... → D:\\...
    """
    p = Path(path)
    if p.exists():
        return p
    # WSL 路径转 Windows：/mnt/d/... → D:\...
    if path.startswith("/mnt/") and len(path) > 6 and path[5].isalpha():
        drive = path[5].upper()
        rest = path[6:].replace('/', '\\')
        win_path = Path(f"{drive}:{rest}")
        if win_path.exists():
            return win_path
    # Windows 路径转 WSL：D:\... → /mnt/d/...
    if len(path) >= 3 and path[1] == ':':
        drive = path[0].lower()
        rest = path[2:].replace('\\', '/')
        wsl_path = Path(f"/mnt/{drive}{rest}")
        if wsl_path.exists():
            return wsl_path
    return p

# ── 前端静态文件 ────────────────────────────────────────────
_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"
if _FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")), name="frontend_assets")
    logger.info(f"Frontend dist mounted: {_FRONTEND_DIST}")

CACHE_DIR.mkdir(exist_ok=True)

# ── 模拟音频文件服务（DeviceFirmware 解码后的 WAV）─────────
_AUDIO_CACHE_DIR = Path(__file__).resolve().parent / ".audio_cache"
_AUDIO_CACHE_DIR.mkdir(parents=True, exist_ok=True)

@app.get("/api/sim-audio/{filename}")
def serve_sim_audio(filename: str):
    """Serve decoded audio files from DeviceFirmware."""
    from fastapi.responses import FileResponse
    filepath = _AUDIO_CACHE_DIR / filename
    if not filepath.exists():
        return {"error": f"Audio file not found: {filename}"}
    return FileResponse(filepath, media_type="audio/wav")

# 语言映射
LANG_MAP: dict[str, Optional[Language]] = {
    "zh": Language.ZH,
    "en": Language.EN,
    "ja": Language.JA,
    "ko": Language.KO,
    "yue": Language.YUE,
    "auto": None,
}

# ── S3 客户端（懒加载 + 线程安全）───────────────────────────

_S3_CLIENT_LOCK = threading.Lock()
_S3_CLIENT = None


def _get_s3_client():
    global _S3_CLIENT
    if _S3_CLIENT is None:
        with _S3_CLIENT_LOCK:
            if _S3_CLIENT is None:
                import boto3

                _S3_CLIENT = boto3.client(
                    "s3",
                    region_name=AWS_REGION,
                    aws_access_key_id=AWS_ACCESS_KEY_ID,
                    aws_secret_access_key=AWS_SECRET_ACCESS_KEY,
                )
    return _S3_CLIENT


# ── MySQL 查询 ────────────────────────────────────────────


def _query_db_audios():
    """查询数据库中带真实音频的记录（ZebMedia + ZebFigurineIntroductions）。"""
    import pymysql

    results = []
    try:
        conn = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
        )
        cur = conn.cursor()

        # 1) ZebMedia — 歌曲/故事（有公开 S3 URL）
        try:
            cur.execute("""
                SELECT Id, MediaName, MediaFile, TotalSecond, MediaType, MediaText
                FROM ZebMedia
                WHERE MediaFile IS NOT NULL AND MediaFile != ''
                ORDER BY TotalSecond DESC
                LIMIT 50
            """)
            for row in cur.fetchall():
                media_id, name, media_file_json, total_sec, media_type, media_text = row
                if not media_file_json:
                    continue
                try:
                    files = json.loads(media_file_json) if isinstance(media_file_json, str) else media_file_json
                    if isinstance(files, list) and len(files) > 0:
                        url = files[0].get("url", "")
                        if url and url.startswith("http"):
                            lang = "en"  # 大部分是英文歌曲
                            media_name = files[0].get("name", name or f"media_{media_id}")
                            cache_key = f"media_{media_id}"
                            cache_file = CACHE_DIR / f"{cache_key}.mp3"
                            results.append({
                                "id": f"media/media_{media_id}",
                                "name": f"🎵 {name or media_name}",
                                "language": lang,
                                "size": 0,
                                "duration": round(total_sec, 1) if total_sec else 0,
                                "sample_rate": 0,
                                "path": str(cache_file),
                                "source": "realtime",
                                "figurine_id": "",
                                "url": url,
                                "cached": cache_file.exists(),
                                "media_type": "song" if media_type == 1 else f"type_{media_type}",
                            })
                except (json.JSONDecodeError, TypeError, IndexError):
                    pass
        except Exception as exc:
            print(f"[DB] ZebMedia 查询失败: {exc}")

        # 2) ZebFigurineIntroductions — 台词开场白文本（仅当有音频 URL 列时）
        try:
            # 先探测是否有音频列
            cur.execute("DESCRIBE ZebFigurineIntroductions")
            cols = [r[0] for r in cur.fetchall()]
            audio_cols = [c for c in cols if "audio" in c.lower() and "url" in c.lower()]
            if audio_cols:
                select_cols = ", ".join(audio_cols)
                cur.execute(f"""
                    SELECT figurine_id, long_introduction_text_1, short_introduction_text_1,
                           {select_cols}
                    FROM ZebFigurineIntroductions
                    WHERE {' OR '.join(f'{c} IS NOT NULL' for c in audio_cols)}
                    LIMIT 20
                """)
                for row in cur.fetchall():
                    figurine_id, long_text, short_text = row[0], row[1], row[2]
                    audio_data = dict(zip(audio_cols, row[3:]))
                    # 处理每个音频字段
                    for col, ref in audio_data.items():
                        if ref and isinstance(ref, str) and ref.strip():
                            type_part = "long" if "long" in col else "short"
                            num_part = col.split("_")[-2] if "_audio_" in col else "1"
                            display_text = (long_text or short_text or "")[:30]
                            cache_key = f"intro_{figurine_id}_{type_part}_{num_part}"
                            cache_file = CACHE_DIR / f"{cache_key}.mp3"
                            results.append({
                                "id": f"intro/{figurine_id}/{type_part}/{num_part}",
                                "name": f"[{figurine_id}] {type_part}_#{num_part} · {display_text}",
                                "language": "zh",
                                "size": 0,
                                "duration": 0,
                                "sample_rate": 0,
                                "path": str(cache_file),
                                "source": "realtime",
                                "figurine_id": figurine_id,
                                "url": ref,
                                "cached": cache_file.exists(),
                                "media_type": "introduction",
                            })
        except Exception as exc:
            print(f"[DB] ZebFigurineIntroductions 查询失败: {exc}")

        cur.close()
        conn.close()
    except Exception as exc:
        print(f"[DB] MySQL 连接失败: {exc}")
    return results


# ── 角色(Figurine) 查询 ──────────────────────────────────


def _query_db_figurines():
    """查询所有可用角色。"""
    import pymysql

    results = []
    try:
        conn = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
        )
        cur = conn.cursor()
        cur.execute("""
            SELECT FigurineId, Name, CharacterName, StudioAppName, TtsType, Id
            FROM ZebFigurineInfo
            WHERE IsDelete = 0
            ORDER BY CharacterName, Name
        """)
        for row in cur.fetchall():
            figurine_id, name, character_name, studio_app_name, tts_type, db_id = row
            results.append({
                "figurine_id": figurine_id,
                "name": name or figurine_id,
                "character_name": character_name or name or figurine_id,
                "studio_app_name": studio_app_name or "",
                "tts_type": tts_type or "",
                "id": db_id,
            })
        cur.close()
        conn.close()
    except Exception as exc:
        print(f"[DB] ZebFigurineInfo 查询失败: {exc}")
    return results


def _query_db_figurines_with_media_counts():
    """查询所有角色及其故事/音乐数量（高效版本，一次查询）。"""
    import pymysql

    results = []
    try:
        conn = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
        )
        cur = conn.cursor()
        
        # 查询角色基本信息
        cur.execute("""
            SELECT FigurineId, Name, CharacterName, StudioAppName, TtsType, Id
            FROM ZebFigurineInfo
            WHERE IsDelete = 0
            ORDER BY CharacterName, Name
        """)
        
        figurines = []
        for row in cur.fetchall():
            figurine_id, name, character_name, studio_app_name, tts_type, db_id = row
            figurines.append({
                "figurine_id": figurine_id,
                "name": name or figurine_id,
                "character_name": character_name or name or figurine_id,
                "studio_app_name": studio_app_name or "",
                "tts_type": tts_type or "",
                "id": db_id,
                "story_count": 0,
                "music_count": 0,
            })
        
        # 批量查询每个角色的故事和音乐数量
        figurine_ids = [f["figurine_id"] for f in figurines]
        if figurine_ids:
            placeholders = ",".join(["%s"] * len(figurine_ids))
            
            # 查询开场白配置状态（按 CharacterName 匹配）
            cur.execute(f"""
                SELECT f.FigurineId
                FROM ZebFigurineIntroductions i
                JOIN ZebFigurineInfo f ON f.CharacterName = i.figurine_id
                WHERE f.FigurineId IN ({placeholders})
            """, figurine_ids)
            intro_set = {row[0] for row in cur.fetchall()}
            
            # 查询故事数量 (MediaType = 0)
            cur.execute(f"""
                SELECT p.FigurineId, COUNT(DISTINCT m.Id) as story_count
                FROM ZebMedia m
                JOIN ZebAlbumTrack t ON t.MediaId = m.Id
                JOIN ZebContentPackage p ON p.AlbumId = t.AlbumId
                WHERE p.FigurineId IN ({placeholders})
                  AND p.IsDelete = 0
                  AND m.MediaType = 0
                  AND m.MediaFile IS NOT NULL AND m.MediaFile != ''
                GROUP BY p.FigurineId
            """, figurine_ids)
            
            story_counts = {row[0]: row[1] for row in cur.fetchall()}
            
            # 查询音乐数量 (MediaType = 1)
            cur.execute(f"""
                SELECT p.FigurineId, COUNT(DISTINCT m.Id) as music_count
                FROM ZebMedia m
                JOIN ZebAlbumTrack t ON t.MediaId = m.Id
                JOIN ZebContentPackage p ON p.AlbumId = t.AlbumId
                WHERE p.FigurineId IN ({placeholders})
                  AND p.IsDelete = 0
                  AND m.MediaType = 1
                  AND m.MediaFile IS NOT NULL AND m.MediaFile != ''
                GROUP BY p.FigurineId
            """, figurine_ids)
            
            music_counts = {row[0]: row[1] for row in cur.fetchall()}
            
            # 合并数据
            for fig in figurines:
                fig["story_count"] = story_counts.get(fig["figurine_id"], 0)
                fig["music_count"] = music_counts.get(fig["figurine_id"], 0)
                fig["has_intro"] = fig["figurine_id"] in intro_set
        
        cur.close()
        conn.close()
        results = figurines
    except Exception as exc:
        print(f"[DB] 角色媒体数量查询失败: {exc}")
    return results


# ── 故事/音乐 查询 ────────────────────────────────────────


def _query_db_media_by_type(media_type: int, figurine_id: str = None):
    """按媒体类型（0=故事, 1=音乐）查询可播放的媒体列表。
    
    通过 ContentPackage → Album → AlbumTrack → Media 链路关联到角色。
    """
    import pymysql

    results = []
    try:
        conn = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
        )
        cur = conn.cursor()

        if figurine_id:
            cur.execute("""
                SELECT m.Id, m.MediaName, m.TotalSecond, m.MediaFile, m.MediaText,
                       p.FigurineId, a.AlbumName, t.TrackNo
                FROM ZebMedia m
                JOIN ZebAlbumTrack t ON t.MediaId = m.Id
                JOIN ZebAlbum a ON a.Id = t.AlbumId
                JOIN ZebContentPackage p ON p.AlbumId = t.AlbumId
                WHERE p.FigurineId = %s
                  AND p.IsDelete = 0
                  AND m.MediaType = %s
                  AND m.MediaFile IS NOT NULL AND m.MediaFile != ''
                ORDER BY t.TrackNo
            """, (figurine_id, media_type))
        else:
            cur.execute("""
                SELECT m.Id, m.MediaName, m.TotalSecond, m.MediaFile, m.MediaText,
                       p.FigurineId, a.AlbumName, t.TrackNo
                FROM ZebMedia m
                JOIN ZebAlbumTrack t ON t.MediaId = m.Id
                JOIN ZebAlbum a ON a.Id = t.AlbumId
                JOIN ZebContentPackage p ON p.AlbumId = t.AlbumId
                WHERE p.IsDelete = 0
                  AND m.MediaType = %s
                  AND m.MediaFile IS NOT NULL AND m.MediaFile != ''
                ORDER BY p.FigurineId, t.TrackNo
            """, (media_type,))

        for row in cur.fetchall():
            media_id, media_name, total_sec, media_file_json, media_text, \
                fig_id, album_name, track_no = row
            if not media_file_json:
                continue
            try:
                files = json.loads(media_file_json) if isinstance(media_file_json, str) else media_file_json
                if isinstance(files, list) and len(files) > 0:
                    url = files[0].get("url", "")
                    # 只返回有实际音频 URL 的记录
                    if url:
                        media_name_display = files[0].get("name", media_name or f"media_{media_id}")
                        results.append({
                            "id": str(media_id),
                            "title": media_name_display,
                            "artist": album_name or "",
                            "duration": round(total_sec, 1) if total_sec else 0,
                            "figurine_id": fig_id or "",
                            "track_no": track_no,
                            "audio_url": url,
                            "description": (media_text or "")[:200],
                        })
            except (json.JSONDecodeError, TypeError, IndexError):
                pass

        cur.close()
        conn.close()
    except Exception as exc:
        print(f"[DB] 媒体查询失败 (type={media_type}): {exc}")
    return results


# ── S3 下载 ───────────────────────────────────────────────


def _parse_s3_ref(ref: str) -> tuple[str, str] | None:
    """解析 s3://bucket/key 返回 (bucket, key)。"""
    if not ref or not isinstance(ref, str):
        return None
    if ref.startswith("s3://"):
        parsed = urlparse(ref)
        bucket = parsed.netloc
        key = parsed.path.lstrip("/")
        if bucket and key:
            return bucket, key
    return None


def _convert_to_wav(src: Path, dst: Path):
    """用 ffmpeg 将 .mp3 转为 16kHz 单声道 .wav"""
    if dst.exists():
        return
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(src), "-ar", "16000", "-ac", "1", str(dst)],
            capture_output=True, timeout=30,
        )
    except Exception:
        pass


def _ensure_audio_cached(audio_id: str) -> Path | None:
    """确保数据库音频已下载到本地缓存，返回缓存的 WAV 路径。"""
    # 从缓存目录查找已有文件
    safe_id = audio_id.replace("/", "_").replace(":", "_")
    cache_mp3 = CACHE_DIR / f"{safe_id}.mp3"
    cache_wav = CACHE_DIR / f"{safe_id}.wav"

    if cache_wav.exists():
        return cache_wav
    if cache_mp3.exists():
        _convert_to_wav(cache_mp3, cache_wav)
        return cache_wav if cache_wav.exists() else cache_mp3

    # 从所有数据源中查找 URL
    all_items = _scan_db_audios()
    url = None
    for item in all_items:
        if item["id"] == audio_id:
            url = item.get("url")
            break

    if not url:
        return None

    import urllib.request

    try:
        # 下载到缓存
        if url.startswith("s3://"):
            parsed = _parse_s3_ref(url)
            if parsed:
                bucket, key = parsed
                _get_s3_client().download_file(bucket, key, str(cache_mp3))
        elif url.startswith("http"):
            urllib.request.urlretrieve(url, str(cache_mp3))
        else:
            return None

        if cache_mp3.exists() and cache_mp3.stat().st_size > 0:
            _convert_to_wav(cache_mp3, cache_wav)
            return cache_wav if cache_wav.exists() else cache_mp3
    except Exception as exc:
        print(f"[Cache] 下载失败 {url}: {exc}")
        return None


# ── 扫描本地测试音频 ──────────────────────────────────────


def _scan_wavs(directory: Path, prefix: str) -> list[dict]:
    results = []
    if not directory.exists():
        return results
    for f in sorted(directory.glob("*.wav")):
        try:
            data, sr = sf.read(f)
            duration = len(data) / sr if sr > 0 else 0
            size = f.stat().st_size
            results.append({
                "id": f"{prefix}/{f.name}",
                "name": f.name,
                "language": f.stem,
                "size": size,
                "duration": round(duration, 2),
                "sample_rate": sr,
                "path": str(f),
                "source": prefix,
                "figurine_id": "",
            })
        except Exception:
            pass
    return results


def _scan_db_audios() -> list[dict]:
    """查询数据库中带音频的记录。"""
    return _query_db_audios()


# ── API: 测试音频列表 ─────────────────────────────────────


@app.get("/api/test-audios")
def list_test_audios():
    audios = []
    # 暂时注释掉本地 WAV 扫描，只返回数据库音频
    # audios += _scan_wavs(TEST_WAVS_DIR, "model")
    # 3) 数据库中的真实音频
    audios += _scan_db_audios()

    return {"audios": audios, "total": len(audios)}


# ── API: 角色列表 ─────────────────────────────────────────


def _query_db_figurine_tts_audios(figurine_id: str) -> list:
    """查询指定角色关联的 TTS 生成音频列表。"""
    return query_generated_audio(
        mysql_config=MYSQL_CONFIG,
        figurine_id=figurine_id,
    )


def _resolve_figurine_tts_audio_path(audio_db_id: int) -> str | None:
    """从 ZebGeneratedAudio 表中解析 TTS 音频的本地文件路径。"""
    records = query_generated_audio(
        mysql_config=MYSQL_CONFIG,
        audio_id=audio_db_id,
    )
    if records:
        path_obj = _normalize_audio_path(records[0].get("audio_path", ""))
        if path_obj and path_obj.exists():
            return str(path_obj)
    return None


@app.get("/api/figurine/{figurine_id}/tts-audios")
def list_figurine_tts_audios(figurine_id: str):
    """获取指定角色的所有 TTS 生成音频。

    从 ZebGeneratedAudio 表中查询关联到该角色的所有 TTS 音频记录，
    供前端在设备卡片的对话模式下选择使用。
    """
    records = _query_db_figurine_tts_audios(figurine_id)
    return {
        "records": records,
        "total": len(records),
    }


@app.get("/api/figurines")
def list_figurines():
    """获取所有可用角色（带媒体数量统计）。"""
    figurines = _query_db_figurines_with_media_counts()
    return {"figurines": figurines, "total": len(figurines)}


# ── API: 媒体（故事/音乐）列表 ────────────────────────────


@app.get("/api/media/stories")
def list_stories(figurine_id: str = None):
    """获取故事列表。可选参数 figurine_id 过滤到特定角色。
    
    返回格式适配前端 StoryItem 接口：
      { id, title, description, duration, audio_url }
    """
    items = _query_db_media_by_type(0, figurine_id)
    return {
        "stories": [
            {
                "id": item["id"],
                "title": item["title"],
                "description": item.get("description", ""),
                "duration": item["duration"],
                "audio_url": item["audio_url"],
                "figurine_id": item.get("figurine_id", ""),
                "track_no": item.get("track_no"),
            }
            for item in items
        ],
        "total": len(items),
    }


@app.get("/api/media/music")
def list_music(figurine_id: str = None):
    """获取音乐列表。可选参数 figurine_id 过滤到特定角色。
    
    返回格式适配前端 MusicItem 接口：
      { id, title, artist, duration, audio_url }
    """
    items = _query_db_media_by_type(1, figurine_id)
    return {
        "music": [
            {
                "id": item["id"],
                "title": item["title"],
                "artist": item.get("artist", ""),
                "duration": item["duration"],
                "audio_url": item["audio_url"],
                "figurine_id": item.get("figurine_id", ""),
                "track_no": item.get("track_no"),
            }
            for item in items
        ],
        "total": len(items),
    }


# ── API: 音频流播放 ───────────────────────────────────────


def _resolve_media_url(media_id: str) -> str | None:
    """从 ZebMedia 表中解析音频 URL。"""
    import pymysql

    try:
        conn = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
        )
        cur = conn.cursor()
        cur.execute(
            "SELECT MediaFile FROM ZebMedia WHERE Id = %s",
            (media_id,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if not row or not row[0]:
            return None
        files = json.loads(row[0]) if isinstance(row[0], str) else row[0]
        if isinstance(files, list) and len(files) > 0:
            url = files[0].get("url", "")
            return url if url else None
    except Exception as exc:
        print(f"[DB] 解析媒体 URL 失败 (media_id={media_id}): {exc}")
    return None


@app.get("/api/media/stream/{media_id}")
def stream_media(media_id: str):
    """流式播放指定媒体的音频（从 S3/HTTP 代理）。"""
    url = _resolve_media_url(media_id)
    if not url:
        return {"error": "media not found or no audio URL"}

    # 本地缓存文件
    safe_id = f"media_{media_id}"
    cache_mp3 = CACHE_DIR / f"{safe_id}.mp3"
    cache_wav = CACHE_DIR / f"{safe_id}.wav"

    # 已缓存则直接返回
    if cache_wav.exists():
        return FileResponse(str(cache_wav), media_type="audio/wav")
    if cache_mp3.exists():
        return FileResponse(str(cache_mp3), media_type="audio/mpeg")

    # 懒加载：下载到缓存后再播放
    import urllib.request

    try:
        print(f"[Stream] 开始下载音频: {url[:80]}...")
        if url.startswith("s3://"):
            parsed = _parse_s3_ref(url)
            if parsed:
                bucket, key = parsed
                _get_s3_client().download_file(bucket, key, str(cache_mp3))
        elif url.startswith("http"):
            urllib.request.urlretrieve(url, str(cache_mp3))
        else:
            return {"error": f"unsupported URL scheme: {url[:30]}"}

        if cache_mp3.exists() and cache_mp3.stat().st_size > 0:
            print(f"[Stream] 下载完成，转换格式...")
            _convert_to_wav(cache_mp3, cache_wav)
            if cache_wav.exists():
                print(f"[Stream] 转换完成，返回 WAV")
                return FileResponse(str(cache_wav), media_type="audio/wav")
            return FileResponse(str(cache_mp3), media_type="audio/mpeg")
    except Exception as exc:
        print(f"[Stream] 下载失败 {url}: {exc}")
        return {"error": f"failed to fetch audio: {exc}"}

    return {"error": "download failed"}


# ── API: 提供音频文件 ─────────────────────────────────────


@app.get("/api/audio/{audio_id:path}")
def serve_audio(audio_id: str):
    parts = audio_id.split("/", 1)
    if len(parts) != 2:
        return {"error": "invalid audio_id"}
    prefix, name = parts

    # 数据库音频（media/intro — 按需下载缓存）
    if prefix in ("media", "intro"):
        cache_path = _ensure_audio_cached(audio_id)
        if cache_path and cache_path.exists():
            return FileResponse(str(cache_path), media_type="audio/wav")
        # 尝试找缓存中的 mp3
        safe_id = audio_id.replace("/", "_").replace(":", "_")
        for f in CACHE_DIR.glob(f"{safe_id}.*"):
            return FileResponse(str(f), media_type="audio/mpeg")
        return {"error": "audio not cached", "detail": "选择后点击测试自动缓存下载"}

    # 本地 WAV
    base_map = {
        "model": TEST_WAVS_DIR,
    }
    base_dir = base_map.get(prefix)
    if base_dir is None:
        return {"error": f"unknown prefix: {prefix}"}
    file_path = base_dir / name
    if not file_path.exists():
        return {"error": "file not found"}
    return FileResponse(str(file_path), media_type="audio/wav")


# ── STT 识别（核心）—— 暂时禁用 ────────────────────────────────
# NOTE: _recognize_from_file 函数体已被整体注释，避免 import 时执行。
#       如需启用，取消注释整个函数体，并确保 chatbot_src 的 asr_factory 已导入。

def _recognize_from_file(wav_path: Path, lang):
    """STT 识别 — 使用 asr_factory 的缓存识别器"""
    data, sr = sf.read(str(wav_path))
    if len(data.shape) > 1:
        data = data.mean(axis=1)

    duration = len(data) / sr
    if sr != 16000:
        from scipy import signal

        ratio = 16000 / sr
        new_len = int(len(data) * ratio)
        data = signal.resample(data, new_len)
        sr = 16000

    t0 = time.time()
    recognizer = load_offline_recognizer_from_cache(
        asr_model=MODEL_NAME, samplerate=16000, language=lang
    )
    load_ms = (time.time() - t0) * 1000

    t1 = time.time()
    s = recognizer.create_stream()
    s.accept_waveform(sr, data.astype("float32"))
    recognizer.decode_stream(s)
    transcribe_ms = (time.time() - t1) * 1000

    text = s.result.text if s.result else ""

    return {
        "text": text,
        "duration_sec": round(duration, 2),
        "load_ms": round(load_ms, 1),
        "transcribe_ms": round(transcribe_ms, 1),
        "rtf": round(transcribe_ms / 1000 / duration, 3) if duration > 0 else 0,
    }


class TranscribeRequest(BaseModel):
    audio_id: Optional[str] = None
    audio_b64: Optional[str] = None
    language: str = "auto"


@app.post("/api/stt/transcribe")
def stt_transcribe(req: TranscribeRequest):
    lang = LANG_MAP.get(req.language)
    wav_path = None

    if req.audio_id:
        parts = req.audio_id.split("/", 1)
        if len(parts) != 2:
            return {"error": "invalid audio_id"}
        prefix, name = parts

        # DB / media / intro 音频：先缓存下载
        if prefix in ("db", "media", "intro"):
            cache_path = _ensure_audio_cached(req.audio_id)
            if cache_path and cache_path.exists():
                wav_path = cache_path
            else:
                return {"error": "failed to download audio from S3"}
        else:
            base_map = {
                "model": TEST_WAVS_DIR,
            }
            base_dir = base_map.get(prefix)
            if not base_dir:
                return {"error": f"unknown prefix: {prefix}"}
            candidate = base_dir / name
            if candidate.exists():
                wav_path = candidate

        if not wav_path:
            return {"error": "audio file not found"}
        result = _recognize_from_file(wav_path, lang)  # type: ignore
        result["audio_id"] = req.audio_id
        return result

    elif req.audio_b64:
        raw = base64.b64decode(req.audio_b64)
        tmp = Path("/tmp/stt_test_upload.wav")
        tmp.write_bytes(raw)
        result = _recognize_from_file(tmp, lang)  # type: ignore
        tmp.unlink(missing_ok=True)
        return result

    return {"error": "provide audio_id or audio_b64"}


# ── MQTT 设备模拟 API 模型 ────────────────────────────────


class SimulateRequest(BaseModel):
    """启动 MQTT 设备模拟的请求参数。"""
    device_id: str = "sim-dev-001"
    figurine_id: str = "doctor"
    mode: str = "dialogue"           # "dialogue" | "story" | "music"
    audio_id: str = ""               # 要模拟的音频 ID
    nfc_id: str = "sim-nfc"          # 模拟 NFC 标签 ID
    subscribe_response: bool = True   # 是否订阅服务端下行响应（默认开启全链路等待）
    speed: float = 0                  # 0=最快, 1.0=实时
    mqtt_profile: str | None = None
    mqtt_env: str | None = None
    mqtt_host: str | None = None
    mqtt_port: int | None = None
    mqtt_tls: bool | None = None
    mqtt_tls_ca_cert: str | None = None
    mqtt_tls_client_cert: str | None = None
    mqtt_tls_client_key: str | None = None
    mqtt_tls_insecure: bool | None = None
    bypass_vad: bool = False
    auto_switch_vad_profile: bool = False


class SimulateResponse(BaseModel):
    """模拟启动响应。"""
    session_id: str
    status: str
    websocket_url: str
    device_id: str
    figurine_id: str
    mode: str


# ── VAD + STT 管道测试 ────────────────────────────────────


class VadTranscribeRequest(BaseModel):
    audio_id: str
    language: str = "auto"


@app.post("/api/stt/vad-transcribe")
def stt_vad_transcribe(req: VadTranscribeRequest):
    wav_path = None
    parts = req.audio_id.split("/", 1)
    if len(parts) != 2:
        return {"error": "invalid audio_id"}
    prefix, name = parts

    # DB / media / intro 音频：先缓存下载
    if prefix in ("db", "media", "intro"):
        cache_path = _ensure_audio_cached(req.audio_id)
        if cache_path and cache_path.exists():
            wav_path = cache_path
    else:
        base_map = {
            "model": TEST_WAVS_DIR,
        }
        base_dir = base_map.get(prefix)
        if base_dir:
            candidate = base_dir / name
            if candidate.exists():
                wav_path = candidate

    if not wav_path:
        return {"error": "file not found"}

    data, sr = sf.read(str(wav_path))
    if len(data.shape) > 1:
        data = data.mean(axis=1)
    if sr != 16000:
        from scipy import signal
        ratio = 16000 / sr
        new_len = int(len(data) * ratio)
        data = signal.resample(data, new_len)
        sr = 16000

    total_duration = len(data) / sr
    lang = LANG_MAP.get(req.language)

    # 简单能量阈值 VAD
    feed_ms = 30
    chunk_size = int(sr * feed_ms / 1000)
    threshold = 0.02
    segments = []
    in_speech = False
    segment_start = 0
    min_speech_ms = 200
    stop_secs = 1.0
    silence_patience = int(stop_secs * 1000 / feed_ms)
    silence_frames = 0
    total_chunks = len(data) // chunk_size

    for i in range(total_chunks):
        chunk = data[i * chunk_size: (i + 1) * chunk_size]
        energy = (chunk ** 2).mean()
        is_active = energy > threshold

        if is_active:
            if not in_speech:
                segment_start = i * feed_ms / 1000
                in_speech = True
            silence_frames = 0
        else:
            if in_speech:
                silence_frames += 1
                if silence_frames >= silence_patience:
                    seg_end = i * feed_ms / 1000
                    seg_duration = seg_end - segment_start
                    if seg_duration >= min_speech_ms / 1000:
                        start_s = int(segment_start * sr)
                        end_s = int(seg_end * sr)
                        seg_audio = data[start_s:end_s]

                        t0 = time.time()
                        recog = load_offline_recognizer_from_cache(
                            asr_model=MODEL_NAME, samplerate=16000, language=lang
                        )
                        stream = recog.create_stream()
                        stream.accept_waveform(sr, seg_audio.astype("float32"))
                        recog.decode_stream(stream)
                        transcribe_ms = (time.time() - t0) * 1000

                        segments.append({
                            "index": len(segments) + 1,
                            "start_sec": round(segment_start, 2),
                            "end_sec": round(seg_end, 2),
                            "duration_sec": round(seg_duration, 2),
                            "text": stream.result.text if stream.result else "",
                            "transcribe_ms": round(transcribe_ms, 1),
                        })
                    in_speech = False
                    silence_frames = 0

    if in_speech:
        seg_end = total_chunks * feed_ms / 1000
        seg_duration = seg_end - segment_start
        if seg_duration >= min_speech_ms / 1000:
            start_s = int(segment_start * sr)
            seg_audio = data[start_s:]
            t0 = time.time()
            recog = load_offline_recognizer_from_cache(
                asr_model=MODEL_NAME, samplerate=16000, language=lang
            )
            stream = recog.create_stream()
            stream.accept_waveform(sr, seg_audio.astype("float32"))
            recog.decode_stream(stream)
            transcribe_ms = (time.time() - t0) * 1000
            segments.append({
                "index": len(segments) + 1,
                "start_sec": round(segment_start, 2),
                "end_sec": round(seg_end, 2),
                "duration_sec": round(seg_duration, 2),
                "text": stream.result.text if stream.result else "",
                "transcribe_ms": round(transcribe_ms, 1),
            })

    return {
        "audio_id": req.audio_id,
        "total_duration_sec": round(total_duration, 2),
        "segments": segments,
        "segment_count": len(segments),
    }


# ── API: 缓存状态 ─────────────────────────────────────────


@app.get("/api/cache/status")
def cache_status():
    total = 0
    cached = 0
    for f in CACHE_DIR.glob("db_*"):
        total += 1
        if f.stat().st_size > 0:
            cached += 1
    return {
        "cache_dir": str(CACHE_DIR),
        "total_files": total,
        "size_mb": round(sum(f.stat().st_size for f in CACHE_DIR.glob("*") if f.is_file()) / 1024 / 1024, 2),
    }


# ── 设备模拟辅助: 解析 audio_id 为本地 WAV 路径 ────────────


def _resolve_audio_for_sim(audio_id: str) -> Path | None:
    """根据 audio_id 返回本地缓存的 WAV 路径。

    支持以下格式：
      media/media_123 / intro/t-rex/long/1  → 从 S3/HTTP 缓存
      tts/{db_id}                            → 从 ZebGeneratedAudio 表读取本地路径
      /abs/path/to/file.mp3                  → 直接返回本地路径
      /mnt/d/path/to/file.mp3                → WSL 路径自动转换为 Windows 路径
    """
    if not audio_id:
        return None

    # WSL 路径转换：/mnt/d/... → D:\...
    if audio_id.startswith("/mnt/") and len(audio_id) > 6 and audio_id[5].isalpha():
        parts = audio_id[6:].lstrip("/").split("/")
        drive = audio_id[5].upper()
        win_path = Path(f"{drive}:\\" + "\\".join(parts))
        if win_path.exists():
            return win_path
        # 也尝试原始路径（可能是 Linux 环境）

    # 直接路径（以 / 或盘符开头）
    if audio_id.startswith("/") or (len(audio_id) > 2 and audio_id[1] == ":"):
        p = Path(audio_id)
        return p if p.exists() else None

    parts = audio_id.split("/", 1)
    if len(parts) != 2:
        # 兼容裸数字 ID：当作 tts/{id}
        if audio_id.isdigit():
            prefix, name = "tts", audio_id
        else:
            return None
    else:
        prefix, name = parts

    # TTS 生成音频：tts/{db_id} → 从数据库查本地路径
    if prefix == "tts":
        try:
            db_id = int(name)
            path_str = _resolve_figurine_tts_audio_path(db_id)
            if path_str:
                src = Path(path_str)
                if src.suffix.lower() in (".mp3",):
                    wav_path = CACHE_DIR / f"{src.stem}_sim.wav"
                    _convert_to_wav(src, wav_path)
                    return wav_path if wav_path.exists() else src
                return src
        except (ValueError, TypeError):
            pass
        return None

    # 数据库音频（需要缓存下载）
    if prefix in ("media", "intro"):
        return _ensure_audio_cached(audio_id)

    return None


# ══════════════════════════════════════════════════════════
# API: voice command diagnostics
# ══════════════════════════════════════════════════════════


class TestCommandRequest(BaseModel):
    """Check whether a command text can be matched by the router."""

    text: str
    mode: str = "dialogue"  # dialogue | story | spark | song | unknown


@app.post("/api/device/test-command")
def test_voice_command(req: TestCommandRequest):
    """Verify whether a text command would be matched by the router.

    Uses the YAML-driven CommandRuleEngine (from commands.yaml) instead of
    the previously hardcoded _DIAGNOSTIC_RULES list.
    """
    text = req.text.strip()
    if not text:
        return {"error": "text is required"}

    pass_through_mode = req.mode in ("story", "spark", "song")
    engine = get_engine()
    matches = engine.match(text, req.mode)

    matched_rules = [
        {"intent": m.intent, "command": m.command, "rule_id": m.rule_id}
        for m in matches
    ]

    note = (
        "pass-through modes (story/spark/song) forward all text to LLM; "
        "commands are handled by the device locally"
        if pass_through_mode
        else "in dialogue mode, matched commands emit MqttCommandFrame and are "
             "stripped from the transcription sent to LLM"
    )

    return {
        "matched": len(matched_rules) > 0,
        "command_text": text,
        "session_mode": req.mode,
        "pass_through": pass_through_mode,
        "rules_matched": matched_rules,
        "engine": "yaml",
        "rules_loaded": engine.rule_count,
        "note": note,
    }


class VerifyCommandsResponse(BaseModel):
    """指令校验响应模型。"""
    voicepipe_commands: list[str] = []
    chatbot_commands: list[str] = []
    commands_only_in_voicepipe: list[str] = []
    commands_only_in_chatbot: list[str] = []
    commands_in_both: list[str] = []
    voicepipe_yaml_path: str = ""
    chatbot_yaml_path: str = ""
    chatbot_yaml_exists: bool = False
    voicepipe_yaml_exists: bool = False
    recommendations: list[str] = []


@app.get("/api/device/verify-commands")
def verify_commands() -> VerifyCommandsResponse:
    """对比 VoicePipe 与 chatbot 的两套指令规则，报告差异。

    读取:
      - VoicePipe: COMMANDS_YAML_PATH (测试平台自身 commands.yaml)
      - Chatbot:   CHATBOT_VOICE_COMMANDS_YAML_PATH (真实 bot 的 voice_commands.yaml)

    对比两套规则中定义的 command 名称，帮助发现 drifting 风险。
    """
    voicepipe_cmds: set[str] = set()
    chatbot_cmds: set[str] = set()
    voicepipe_exists = COMMANDS_YAML_PATH.exists()
    chatbot_exists = CHATBOT_VOICE_COMMANDS_YAML_PATH.exists()

    # ── 提取 VoicePipe 指令 ──
    if voicepipe_exists:
        try:
            vp_data = yaml.safe_load(COMMANDS_YAML_PATH.read_text(encoding="utf-8"))
            if vp_data:
                for kw in vp_data.get("kws_keywords", []):
                    if isinstance(kw, dict) and kw.get("command"):
                        voicepipe_cmds.add(kw["command"])
                for ci in vp_data.get("command_intents", []):
                    if isinstance(ci, dict) and ci.get("command"):
                        voicepipe_cmds.add(ci["command"])
                for cr in vp_data.get("command_rules", []):
                    if isinstance(cr, dict) and cr.get("command"):
                        voicepipe_cmds.add(cr["command"])
        except Exception as exc:
            logger.warning("Failed to parse VoicePipe commands.yaml: %s", exc)

    # ── 提取 Chatbot 指令 ──
    if chatbot_exists:
        try:
            cb_data = yaml.safe_load(CHATBOT_VOICE_COMMANDS_YAML_PATH.read_text(encoding="utf-8"))
            if cb_data:
                for intent in cb_data.get("intents", []):
                    if isinstance(intent, dict) and intent.get("command"):
                        chatbot_cmds.add(intent["command"])
        except Exception as exc:
            logger.warning("Failed to parse chatbot voice_commands.yaml: %s", exc)

    # ── 计算差异 ──
    both = voicepipe_cmds & chatbot_cmds
    only_vp = voicepipe_cmds - chatbot_cmds
    only_cb = chatbot_cmds - voicepipe_cmds

    # ── 生成建议 ──
    recommendations: list[str] = []
    if only_vp:
        recommendations.append(
            f"{len(only_vp)} 条指令仅在 VoicePipe 中定义，chatbot 未覆盖: "
            + ", ".join(sorted(only_vp))
        )
    if only_cb:
        recommendations.append(
            f"{len(only_cb)} 条指令仅在 chatbot 中定义，VoicePipe 未覆盖: "
            + ", ".join(sorted(only_cb))
        )
    if not chatbot_exists:
        recommendations.append(
            f"Chatbot voice_commands.yaml 不存在于 {CHATBOT_VOICE_COMMANDS_YAML_PATH}，"
            "请设置 VOICE_COMMANDS_YAML_PATH 环境变量或确保 chatbot 项目已就绪"
        )
    if not both:
        recommendations.append("两套规则无交集！VoicePipe 测试可能无法反映真实 chatbot 行为")
    elif len(both) == len(chatbot_cmds) and not only_cb:
        recommendations.append("✅ VoicePipe 已覆盖 chatbot 所有指令")
    else:
        recommendations.append(
            f"VoicePipe 覆盖了 chatbot {len(both)}/{len(chatbot_cmds)} 条指令"
        )
    if not recommendations:
        recommendations.append("两套规则均已加载且无差异")

    return VerifyCommandsResponse(
        voicepipe_commands=sorted(voicepipe_cmds),
        chatbot_commands=sorted(chatbot_cmds),
        commands_only_in_voicepipe=sorted(only_vp),
        commands_only_in_chatbot=sorted(only_cb),
        commands_in_both=sorted(both),
        voicepipe_yaml_path=str(COMMANDS_YAML_PATH),
        chatbot_yaml_path=str(CHATBOT_VOICE_COMMANDS_YAML_PATH),
        chatbot_yaml_exists=chatbot_exists,
        voicepipe_yaml_exists=voicepipe_exists,
        recommendations=recommendations,
    )


class PipelineHealthResponse(BaseModel):
    """全链路健康检查响应模型。"""
    overall: str = "unknown"  # healthy | degraded | unhealthy
    nodes: dict = {}
    checks: list[dict] = []
    checked_at: float = 0.0


@app.get("/api/device/pipeline-health")
def pipeline_health() -> PipelineHealthResponse:
    """检查全链路各节点健康状态。

    检查节点:
      - MQTT Broker (NanoMQ:1883)
      - bot_mqtt Worker (WSL 进程)
      - Chatbot API (端口 7860)

    返回整体状态:
      healthy   — 所有节点正常
      degraded  — 部分节点异常但核心链路可用
      unhealthy — MQTT Broker 不可达（核心链路断开）
    """
    import socket
    import subprocess

    checks: list[dict] = []
    now = time.time()
    mqtt_host = _resolve_local_mqtt_host() if MQTT_BROKER_PROFILE == "local" else _resolve_mqtt_host()
    mqtt_port = MQTT_PORT

    # ── 1. MQTT Broker 连通性 ──
    mqtt_ok = False
    mqtt_detail = ""
    t0 = time.time()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        result = sock.connect_ex((mqtt_host, mqtt_port))
        sock.close()
        if result == 0:
            mqtt_ok = True
            mqtt_detail = f"{mqtt_host}:{mqtt_port} reachable"
        else:
            mqtt_detail = f"{mqtt_host}:{mqtt_port} connection refused (errno={result})"
    except Exception as exc:
        mqtt_detail = f"{mqtt_host}:{mqtt_port} error: {exc}"
    checks.append({
        "node": "mqtt_broker",
        "healthy": mqtt_ok,
        "detail": mqtt_detail,
        "latency_ms": round((time.time() - t0) * 1000),
    })

    # ── 2. bot_mqtt Worker ──
    bot_ok = False
    bot_detail = ""
    _in_wsl = os.path.exists("/proc/sys/fs/binfmt_misc/WSLInterop") if sys.platform == "linux" else False
    t0 = time.time()
    try:
        if sys.platform == "win32":
            # Running on Windows → use wsl.exe to reach WSL
            result = subprocess.run(
                ["wsl", "bash", "-c", "pgrep -f bot_mqtt > /dev/null && echo OK || echo NOT_FOUND"],
                capture_output=True, text=True, timeout=5,
            )
        elif _in_wsl:
            # Already inside WSL → run pgrep directly
            result = subprocess.run(
                ["pgrep", "-f", "bot_mqtt"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                result = subprocess.CompletedProcess(args=[], returncode=0, stdout="OK")
            else:
                result = subprocess.CompletedProcess(args=[], returncode=1, stdout="NOT_FOUND")
        else:
            # Native Linux — try pgrep directly
            result = subprocess.run(
                ["pgrep", "-f", "bot_mqtt"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                result = subprocess.CompletedProcess(args=[], returncode=0, stdout="OK")
            else:
                result = subprocess.CompletedProcess(args=[], returncode=1, stdout="NOT_FOUND")
        if result.returncode == 0 and "OK" in result.stdout:
            bot_ok = True
            bot_detail = "bot_mqtt process running" + (" (WSL)" if sys.platform == "win32" else "")
        elif "NOT_FOUND" in (result.stdout or ""):
            bot_detail = "bot_mqtt process NOT found"
        else:
            bot_detail = f"check failed: {result.stderr.strip() or 'unknown'}"
    except FileNotFoundError:
        bot_detail = "wsl command not available (not on Windows?)"
    except subprocess.TimeoutExpired:
        bot_detail = "check timed out after 5s"
    except Exception as exc:
        bot_detail = f"check error: {exc}"
    checks.append({
        "node": "bot_mqtt_worker",
        "healthy": bot_ok,
        "detail": bot_detail,
        "latency_ms": round((time.time() - t0) * 1000),
    })

    # ── 3. Chatbot API ──
    api_ok = False
    api_detail = ""
    api_url = os.getenv("CHATBOT_API_URL", "http://127.0.0.1:7860")
    t0 = time.time()
    try:
        import urllib.request
        req = urllib.request.Request(api_url + "/", method="GET")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if 200 <= resp.status < 400:
                api_ok = True
                api_detail = f"{api_url} HTTP {resp.status}"
            else:
                api_detail = f"{api_url} HTTP {resp.status}"
    except Exception as exc:
        api_detail = f"{api_url} unreachable: {exc}"
    checks.append({
        "node": "chatbot_api",
        "healthy": api_ok,
        "detail": api_detail,
        "latency_ms": round((time.time() - t0) * 1000),
    })

    # ── 计算整体状态 ──
    if mqtt_ok and bot_ok and api_ok:
        overall = "healthy"
    elif mqtt_ok:
        overall = "degraded"
    else:
        overall = "unhealthy"

    return PipelineHealthResponse(
        overall=overall,
        nodes={
            "mqtt_broker": {"host": mqtt_host, "port": mqtt_port},
            "bot_mqtt_worker": {"host": "WSL", "pid_check": bot_ok},
            "chatbot_api": {"url": api_url},
        },
        checks=checks,
        checked_at=now,
    )


# ── API: 设备模拟 ────────────────────────────────────────


class DeviceConnectRequest(BaseModel):
    device_id: str = "sim-dev-001"
    figurine_id: str = "doctor"
    mode: str = "dialogue"
    nfc_id: str = "sim-nfc"
    mqtt_profile: str | None = None
    mqtt_env: str | None = None
    mqtt_host: str | None = None
    mqtt_port: int | None = None
    mqtt_tls: bool | None = None
    mqtt_tls_ca_cert: str | None = None
    mqtt_tls_client_cert: str | None = None
    mqtt_tls_client_key: str | None = None
    mqtt_tls_insecure: bool | None = None


@app.post("/api/device/connect")
def connect_device(req: DeviceConnectRequest):
    """连接设备（power_on）。设备上线后等待选择角色，不自动触发开场白。"""
    try:
        result = simulation_manager.connect_device(
            device_id=req.device_id,
            figurine_id=req.figurine_id,
            mode=req.mode,
            nfc_id=req.nfc_id,
            mqtt_profile=req.mqtt_profile,
            mqtt_env=req.mqtt_env,
            mqtt_host=req.mqtt_host,
            mqtt_port=req.mqtt_port,
            mqtt_tls=req.mqtt_tls,
            mqtt_tls_ca_cert=req.mqtt_tls_ca_cert,
            mqtt_tls_client_cert=req.mqtt_tls_client_cert,
            mqtt_tls_client_key=req.mqtt_tls_client_key,
            mqtt_tls_insecure=req.mqtt_tls_insecure,
            skip_auto_intro=True,
        )
        return result
    except ConnectionError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"连接失败: {exc}"}


@app.post("/api/device/disconnect/{device_id}")
def disconnect_device(device_id: str):
    """断开设备（power_off）。"""
    return simulation_manager.disconnect_device(device_id)


class StartSessionRequest(BaseModel):
    device_id: str
    figurine_id: str = "doctor"
    mode: str = "dialogue"
    nfc_id: str = "sim-nfc"


@app.post("/api/device/start-session")
def start_session(req: StartSessionRequest):
    """选择角色并触发 session/start + 开场白。模拟真实设备的 NFC 碰触流程。

    等开场白完成后再返回（最多 30s），确保后续 simulate 不会冲突。
    """
    try:
        dev = simulation_manager._devices.get(req.device_id)
        if not dev or not dev.is_connected:
            return {"error": f"设备 {req.device_id} 未连接，请先连接设备"}
        # 更新角色信息
        dev.figurine_id = req.figurine_id
        dev.mode = req.mode
        dev.nfc_id = req.nfc_id
        # 同步触发开场白并等待完成
        try:
            sid = dev.start_session_and_await_intro()
        except Exception as exc:
            logger.warning("start_session_and_await_intro failed: %s", exc)
            sid = dev.session_id or ""
        session_id = sid or dev.session_id or ""
        return {"device_id": req.device_id, "figurine_id": req.figurine_id,
                "session_id": session_id, "status": "session_started",
                "intro_completed": True}
    except Exception as exc:
        return {"error": f"启动会话失败: {exc}"}


@app.get("/api/device/list")
def list_devices():
    """返回所有活跃设备列表，供前端轮询刷新设备状态。

    返回格式:
      {
        "devices": [
          {
            "device_id": "...",
            "connected": true/false,
            "simulating": true/false,
            "mqtt_profile": "local",
            "figurine_id": "doctor",
            "mode": "dialogue",
            "last_seen_sec": 5,
            "is_stale": false,
          },
          ...
        ],
        "count": 1,
        "max_devices": 4,
      }
    """
    active = simulation_manager.get_active_sessions()
    devices_list = []
    for d in active:
        status = simulation_manager.get_device_status(d["device_id"])
        if status:
            devices_list.append({
                "device_id": status["device_id"],
                "connected": status["connected"],
                "simulating": status.get("simulating", False),
                "mqtt_profile": status.get("mqtt_profile", "local"),
                "figurine_id": d.get("figurine_id", ""),
                "mode": d.get("mode", ""),
                "last_seen_sec": status.get("last_seen_sec", 0),
                "is_stale": status.get("is_stale", False),
            })

    return {
        "devices": devices_list,
        "count": len(devices_list),
        "max_devices": SimulationManager.MAX_DEVICES,
    }


@app.get("/api/device/status/{device_id}")
def device_status(device_id: str):
    """查询单个设备的连接和模拟状态。"""
    status = simulation_manager.get_device_status(device_id)
    if status is None:
        return {"error": "device not found", "device_id": device_id}
    return status


@app.post("/api/device/keepalive/{device_id}")
def device_keepalive(device_id: str):
    """前端定期调用此接口更新设备活跃时间，避免被后端作为过期设备回收。"""
    dev = simulation_manager.devices.get(device_id)
    if dev is None:
        return {"error": "device not found", "device_id": device_id}
    dev.touch_seen()
    return {"device_id": device_id, "status": "alive"}


@app.websocket("/ws/device/{device_id}")
async def ws_device_events(websocket: WebSocket, device_id: str):
    """WebSocket 实时推送设备级事件。

    与旧版不同：
      - 前端 WS 断开后不再马上销毁设备（避免页面刷新丢设备）
      - 设备由 keepalive 超时 + cleanup 线程接管过期回收
      - 如再次连接同一 device_id，WS 队列自动重建
    """
    await websocket.accept()

    # 如果 device_id 对应的后端设备不存在，3s 后关闭 WS
    dev = simulation_manager.devices.get(device_id)
    if dev is None:
        await asyncio.sleep(3)
        await websocket.close(code=4004, reason="device_not_found")
        return

    event_queue = simulation_manager.event_bus.create_queue(device_id)
    dev.touch_seen()

    try:
        while True:
            events = []
            while True:
                try:
                    events.append(event_queue.get_nowait())
                except queue.Empty:
                    break
            for event in events:
                try:
                    translated = _translate_ws_event(event)
                    await websocket.send_json(translated)
                except Exception:
                    pass
            await asyncio.sleep(0.05)
    except WebSocketDisconnect:
        logger.info("Device %s WebSocket disconnected (device stays alive)", device_id)
    finally:
        simulation_manager.event_bus.remove_queue(device_id)


# ── 系统级事件 WebSocket（设备回收通知等）────────────────────
_system_ws_clients: list[WebSocket] = []


@app.websocket("/ws/system")
async def ws_system_events(websocket: WebSocket):
    """系统级事件广播（设备被回收、资源耗尽等）。

    前端应在应用启动时连接此端点，接收 device_evicted 等通知。
    """
    await websocket.accept()
    _system_ws_clients.append(websocket)
    queue_key = f"_system_ws_{id(websocket)}"
    event_queue = simulation_manager.event_bus.create_queue(queue_key)
    # 别名到 _system 频道 —— 接收全局系统事件
    simulation_manager.event_bus.alias_queue("_system", queue_key)

    try:
        while True:
            events = []
            while True:
                try:
                    events.append(event_queue.get_nowait())
                except queue.Empty:
                    break
            for event in events:
                try:
                    await websocket.send_json(event)
                except Exception:
                    pass
            await asyncio.sleep(0.5)
    except WebSocketDisconnect:
        pass
    finally:
        simulation_manager.event_bus.remove_queue(queue_key)
        if websocket in _system_ws_clients:
            _system_ws_clients.remove(websocket)


@app.post("/api/device/simulate")
def start_device_simulation(req: SimulateRequest):
    """启动 MQTT 设备模拟。

    后端将加载指定音频，通过真实 MQTT 协议发送到 chatbot 后端，
    模拟真实设备的会话生命周期。

    如果设备已连接且有活跃 session，走 send_user_turn 路径（真实 DeviceFirmware）。
    否则走旧的 start_simulation 路径（兼容未 connect 的场景）。
    """
    if not req.audio_id:
        return {"error": "audio_id is required"}

    try:
        # 检查是否已有连接的设备 + 活跃 session → 走 send_user_turn
        dev = simulation_manager._devices.get(req.device_id)
        if dev and dev.is_connected and (dev.session_id or (dev._fw and dev._fw.session_id)):
            result = simulation_manager.send_user_turn(
                device_id=req.device_id,
                audio_id=req.audio_id,
                resolve_audio=_resolve_audio_for_sim,
            )
            return result

        session_id = simulation_manager.start_simulation(
            device_id=req.device_id,
            figurine_id=req.figurine_id,
            mode=req.mode,
            audio_id=req.audio_id,
            resolve_audio=_resolve_audio_for_sim,
            nfc_id=req.nfc_id,
            subscribe_response=req.subscribe_response,
            speed=req.speed,
            mqtt_profile=req.mqtt_profile,
            mqtt_env=req.mqtt_env,
            mqtt_host=req.mqtt_host,
            mqtt_port=req.mqtt_port,
            mqtt_tls=req.mqtt_tls,
            mqtt_tls_ca_cert=req.mqtt_tls_ca_cert,
            mqtt_tls_client_cert=req.mqtt_tls_client_cert,
            mqtt_tls_client_key=req.mqtt_tls_client_key,
            mqtt_tls_insecure=req.mqtt_tls_insecure,
        )

        if req.bypass_vad:
            simulation_manager._vad_bypassed[session_id] = True

    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"启动模拟失败: {exc}"}

    resp = {
        "session_id": session_id,
        "status": "started",
        "websocket_url": f"/ws/session/{session_id}",
        "device_id": req.device_id,
        "figurine_id": req.figurine_id,
        "mode": req.mode,
        "bypass_vad": req.bypass_vad,
    }
    return resp


def _switch_mqtt_profile(target_profile: str) -> dict:
    """Switch the mqtt profile group and restart affected services.

    Returns the previous profile name so it can be restored later.
    """
    group = "mqtt"
    profiles = _load_active_profiles()
    previous = profiles.get(group, "local")

    if previous == target_profile:
        return {"previous": previous, "switched": False}

    group_def = _PROFILE_GROUPS.get(group)
    if not group_def or target_profile not in group_def["available"]:
        return {"previous": previous, "switched": False, "error": f"invalid profile: {target_profile}"}

    profiles[group] = target_profile
    _save_active_profiles(profiles)

    restart_suites = set()
    for sid, g in _SERVICE_PROFILE_GROUP.items():
        if g == group:
            for suite_name in _SERVICE_INFO[sid]["suites"]:
                restart_suites.add(suite_name)

    errors = []
    for suite in restart_suites:
        stop_result = _run_svc_script("stop", suite)
        if not stop_result.get("success"):
            errors.append(f"stop {suite} failed: {stop_result.get('stderr', '')[:100]}")
        start_result = _run_svc_script("start", suite)
        if not start_result.get("success"):
            errors.append(f"start {suite} failed: {start_result.get('stderr', '')[:100]}")

    return {"previous": previous, "switched": True, "errors": errors}


@app.post("/api/device/simulate-with-vad-retry")
def start_device_simulation_with_vad_retry(req: SimulateRequest):
    """启动 MQTT 设备模拟，自动检测 VAD 阻塞并重试。

    流程：
    1. 先以当前 profile 运行模拟
    2. 等待结果（最长 wait_seconds）
    3. 如果检测到 VAD 阻塞（stt_text 空 + tts 无响应）：
       a. 切换 MQTT profile 到 local（EOS 模式，VAD off）
       b. 重启 chatbot 服务
       c. 以 bypass_vad=true 重试
       d. 恢复原始 profile + 重启服务
    4. 返回两次运行的结果
    """
    if not req.audio_id:
        return {"error": "audio_id is required"}

    result = {"first_run": None, "second_run": None, "vad_auto_retried": False}

    # First run with current profile
    session_id = simulation_manager.start_simulation(
        device_id=req.device_id,
        figurine_id=req.figurine_id,
        mode=req.mode,
        audio_id=req.audio_id,
        resolve_audio=_resolve_audio_for_sim,
        nfc_id=req.nfc_id,
        subscribe_response=req.subscribe_response,
        speed=req.speed,
        mqtt_profile=req.mqtt_profile,
        mqtt_env=req.mqtt_env,
        mqtt_host=req.mqtt_host,
        mqtt_port=req.mqtt_port,
        mqtt_tls=req.mqtt_tls,
        mqtt_tls_ca_cert=req.mqtt_tls_ca_cert,
        mqtt_tls_client_cert=req.mqtt_tls_client_cert,
        mqtt_tls_client_key=req.mqtt_tls_client_key,
        mqtt_tls_insecure=req.mqtt_tls_insecure,
    )
    result["first_run"] = {"session_id": session_id, "status": "started"}

    # Wait briefly and check for VAD blocking
    import time
    for _ in range(30):
        time.sleep(1)
        r = simulation_manager.get_result(session_id)
        if r and r.get("status") in ("completed", "error"):
            stt = (r.get("stt_text") or "").strip()
            tts = r.get("tts_response_count", 0)
            result["first_run"]["status"] = r.get("status")
            if not stt and not tts:
                result["vad_auto_retried"] = True
                break
            result["first_run"]["stt_text"] = stt
            result["first_run"]["tts_chunks"] = r.get("tts_chunks")
            return result

    if not result["vad_auto_retried"]:
        return result

    # VAD blocked — switch to EOS mode and retry
    switch_result = _switch_mqtt_profile("local")
    if switch_result.get("errors"):
        return {"error": "profile switch failed", "detail": switch_result["errors"]}

    try:
        req.bypass_vad = True
        session_id2 = simulation_manager.start_simulation(
            device_id=req.device_id,
            figurine_id=req.figurine_id,
            mode=req.mode,
            audio_id=req.audio_id,
            resolve_audio=_resolve_audio_for_sim,
            nfc_id=req.nfc_id,
            subscribe_response=req.subscribe_response,
            speed=req.speed,
            mqtt_profile=req.mqtt_profile,
            mqtt_env=req.mqtt_env,
            mqtt_host=req.mqtt_host,
            mqtt_port=req.mqtt_port,
            mqtt_tls=req.mqtt_tls,
            mqtt_tls_ca_cert=req.mqtt_tls_ca_cert,
            mqtt_tls_client_cert=req.mqtt_tls_client_cert,
            mqtt_tls_client_key=req.mqtt_tls_client_key,
            mqtt_tls_insecure=req.mqtt_tls_insecure,
        )
        simulation_manager._vad_bypassed[session_id2] = True
        result["second_run"] = {"session_id": session_id2, "status": "started", "bypass_vad": True}

        for _ in range(30):
            time.sleep(1)
            r2 = simulation_manager.get_result(session_id2)
            if r2 and r2.get("status") in ("completed", "error"):
                result["second_run"]["status"] = r2.get("status")
                result["second_run"]["stt_text"] = r2.get("stt_text", "")
                result["second_run"]["tts_chunks"] = r2.get("tts_chunks")
                break
    finally:
        _switch_mqtt_profile(switch_result.get("previous", "local"))

    return result


@app.post("/api/device/stop/{session_id}")
def stop_device_simulation(session_id: str):
    """停止指定 session 的 MQTT 模拟。"""
    stopped = simulation_manager.stop_simulation(session_id)
    return {"session_id": session_id, "stopped": stopped}


@app.post("/api/device/send-turn")
def send_device_turn(req: SimulateRequest):
    """向已连接的设备发送一段用户音频（使用已有 session）。

    设备必须先 connect，intro 播放完毕后再调用此接口。
    每调一次发一个 turn，session 保持活性。
    """
    if not req.audio_id:
        return {"error": "audio_id is required"}

    try:
        result = simulation_manager.send_user_turn(
            device_id=req.device_id,
            audio_id=req.audio_id,
            resolve_audio=_resolve_audio_for_sim,
        )
        return result
    except ValueError as exc:
        return {"error": str(exc)}
    except Exception as exc:
        return {"error": f"发送音频失败: {exc}"}


@app.get("/api/device/status")
def device_simulation_status():
    """查询当前模拟状态。"""
    return {
        "active_count": simulation_manager.get_active_count(),
        "max_devices": SimulationManager.MAX_DEVICES,
        "active_sessions": simulation_manager.get_active_sessions(),
    }


@app.post("/api/device/cleanup-orphans")
def cleanup_orphan_sessions(max_age_seconds: float = 300):
    """清理原生会话结果（超过指定秒数未完成的 pending session）。"""
    count = simulation_manager.cleanup_orphan_sessions(max_age_seconds=max_age_seconds)
    return {"cleaned": count}


@app.get("/api/device/events/{session_id_or_device}")
def poll_session_events(session_id_or_device: str):
    """轮询获取 session/device 的事件（用于不支持 WebSocket 的前端）。

    - 优先按 session_id 精确匹配
    - 按别名解析（preliminary_id → real_session_id）
    - 最后按 device_id 读取（_emit_session 同时发布到 device_id）
    """
    event_bus = simulation_manager.event_bus
    found_q = None

    # 1. Direct match
    found_q = event_bus._queues.get(session_id_or_device)

    # 2. Alias resolution (preliminary_id → real_session_id)
    if found_q is None:
        resolved = simulation_manager._resolve_session_id(session_id_or_device)
        if resolved != session_id_or_device:
            found_q = event_bus._queues.get(resolved)

    # 3. Device ID match — scan device list
    if found_q is None:
        for did, dev in simulation_manager._devices.items():
            q = event_bus._queues.get(dev.device_id)
            if q is not None and q.qsize() > 0:
                found_q = q
                break

    if found_q is None:
        return {"events": []}
    events = []
    while True:
        try:
            events.append(found_q.get_nowait())
        except queue.Empty:
            break
    return {"events": events, "count": len(events)}


# ── API: 测试结果查询 ────────────────────────────────────


@app.get("/api/device/result/{session_id}")
def get_device_result(session_id: str):
    """查询指定 session 的完整测试结果。

    包含：
    - 输入音频信息（时长、chunk数）
    - 发送耗时
    - 后端 STT 识别文本
    - 后端 TTS 响应统计
    - 所有后端响应记录
    """
    result = simulation_manager.get_result(session_id)
    if result is None:
        return {"error": "session not found", "session_id": session_id}
    return {
        "session_id": session_id,
        "result": result,
    }


@app.get("/api/device/history")
def get_device_history(limit: int = 50, offset: int = 0):
    """获取历史测试结果列表（按时间倒序）。

    每条记录包含摘要信息（不含详细响应日志）。
    """
    records = simulation_manager.get_history(limit=limit, offset=offset)
    total = simulation_manager.get_history_count()

    # 摘要版本（去掉详细的 backend_responses）
    summary = []
    for r in records:
        stt_text = r.get("stt_text", "") or ""
        vad_bypassed = r.get("vad_bypassed", False)
        vad_blocked = False
        if not stt_text.strip() and not vad_bypassed and r.get("tts_response_count", 0) == 0:
            vad_blocked = True
        summary.append({
            "session_id": r.get("session_id"),
            "device_id": r.get("device_id"),
            "figurine_id": r.get("figurine_id"),
            "mode": r.get("mode"),
            "audio_id": r.get("audio_id"),
            "status": r.get("status"),
            "audio_duration_sec": r.get("audio_duration_sec"),
            "total_chunks": r.get("total_chunks"),
            "send_duration_sec": r.get("send_duration_sec"),
            "stt_text": stt_text[:100],
            "tts_response_count": r.get("tts_response_count"),
            "tts_chunks": r.get("tts_chunks"),
            "started_at": r.get("started_at"),
            "error": r.get("error", ""),
            "vad_bypassed": vad_bypassed,
            "vad_blocked": vad_blocked,
        })

    return {
        "records": summary,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@app.delete("/api/device/history")
def clear_device_history():
    """清空所有历史测试记录。"""
    simulation_manager.clear_history()
    return {"status": "cleared"}


@app.get("/api/device/compare")
def compare_device_simulations(session_ids: str = ""):
    """对比多个测试结果。

    参数: session_ids — 逗号分隔的 session_id 列表
    返回: 结果对比表，每个 session 一行
    """
    ids = [s.strip() for s in session_ids.split(",") if s.strip()]
    if not ids:
        return {"error": "provide at least one session_id via ?session_ids=id1,id2"}

    rows = []
    for sid in ids:
        result = simulation_manager.get_result(sid)
        if result is None:
            continue
        stt_text = result.get("stt_text", "") or ""
        rows.append({
            "session_id": sid,
            "device_id": result.get("device_id"),
            "figurine_id": result.get("figurine_id"),
            "mode": result.get("mode"),
            "audio_duration_sec": result.get("audio_duration_sec"),
            "send_duration_sec": result.get("send_duration_sec"),
            "stt_text": stt_text,
            "stt_language": result.get("stt_language", ""),
            "tts_response_count": result.get("tts_response_count"),
            "tts_chunks": result.get("tts_chunks"),
            "status": result.get("status"),
            "error": result.get("error", ""),
            "vad_bypassed": result.get("vad_bypassed", False),
            "vad_blocked": (not stt_text and not result.get("vad_bypassed") and not result.get("tts_response_count")),
        })

    return {
        "rows": rows,
        "count": len(rows),
    }


# ── WebSocket: 实时会话日志 ───────────────────────────────


def _extract_short_topic(topic: str) -> str:
    """从完整 MQTT 主题路径中提取短名称。

    完整路径示例：
      development/sim-dev-xxx/request/session/{sessionId}/start  →  session/start
      development/sim-dev-xxx/request/audio/{sessionId}/{turnId}/start  →  audio/start
      development/sim-dev-xxx/request/audio/{sessionId}/{turnId}/chunk/{seq}  →  audio/chunk
      development/sim-dev-xxx/request/audio/{sessionId}/{turnId}/eos  →  audio/eos
      development/sim-dev-xxx/request/session/{sessionId}/end  →  session/end
    """
    parts = topic.split("/")
    try:
        req_idx = parts.index("request")
        after_req = parts[req_idx + 1:]
        if len(after_req) < 2:
            return topic
        req_type = after_req[0]  # session 或 audio
        action = after_req[-1]
        # chunk 主题最后一段是数字序号，所以动作是倒数第二段
        if action.isdigit() and len(after_req) >= 3:
            action = after_req[-2]
        return f"{req_type}/{action}"
    except ValueError:
        return topic


_SHORT_TOPIC_TO_MESSAGE_TYPE = {
    "session/start": "session_start",
    "audio/start": "audio_start",
    "audio/chunk": "chunk",
    "audio/eos": "eos",
    "session/end": "session_end",
    "session/hb": "session_hb",
    "audio/abort": "abort",
    "audio/done": "done",
    "audio/introeos": "introeos",
    "audio/vadeos": "vadeos",
}


def _translate_ws_event(event: dict) -> dict:
    """将后端 WebSocket 事件格式翻译为前端预期的格式。

    v1.6 翻译映射:
      mqtt_publish          → mqtt_message  （前端日志用）
      mqtt_response_vadeos  → stt_result    （前端 STT 展示 + 指标用）
      session_closed        → session_complete（前端关闭会话用）

    以下事件由 DeviceFirmware 发出，名称与前端约定一致，显式透传:
      stt_inference         → stt_inference  （前端 Pipeline/STT 面板用）
      tts_synthesis         → tts_synthesis  （前端 Pipeline/TTS 面板用）
      llm_inference         → llm_inference  （前端 Pipeline/LLM 面板用）
      introeos              → introeos       （前端 Intro 完成信号）

    额外字段:
      short_topic           — 从完整 MQTT 路径提取的短名称
      message_type          — 根据 short_topic 映射的消息类型
    """
    ev_type = event.get("type")
    if ev_type == "mqtt_publish":
        translated = dict(event)
        translated["type"] = "mqtt_message"
        raw_topic = event.get("topic", "")
        translated["short_topic"] = _extract_short_topic(raw_topic)
        translated["message_type"] = _SHORT_TOPIC_TO_MESSAGE_TYPE.get(
            translated["short_topic"], "other"
        )
        return translated
    elif ev_type == "mqtt_response_vadeos":
        translated = dict(event)
        translated["type"] = "stt_result"
        return translated
    elif ev_type == "session_closed":
        translated = dict(event)
        translated["type"] = "session_complete"
        return translated
    # ── Pipeline 关键事件：DeviceFirmware 发出，前端约定同名处理，显式透传 ──
    elif ev_type in ("stt_inference", "tts_synthesis", "llm_inference", "llm_text", "introeos",
                     "audio_ready", "device_state", "device_error"):
        return event
    return event


@app.websocket("/ws/session/{session_id}")
async def ws_session_events(websocket: WebSocket, session_id: str):
    """WebSocket 实时推送 MQTT 模拟事件。

    消息类型（JSON）：
      mqtt_connecting / mqtt_connected / mqtt_disconnected  — 连接状态
      mqtt_subscribe            — 已订阅 response 主题
      mqtt_publish              — 上行消息（session/start, chunk, eos 等）
      mqtt_response_vadeos     — 后端 STT 结果（含 text, confidence, language）
      mqtt_response            — 后端 TTS 响应（audio_start, audio_eos 等）
      mqtt_response_raw        — 后端原始响应
      session_status            — 模拟状态变更（status, stats）
      session_closed            — 会话结束
    """
    await websocket.accept()

    # 创建事件队列
    event_queue: queue.Queue = simulation_manager.event_bus.create_queue(session_id)

    try:
        while True:
            # 从队列中取出所有可用事件
            events = []
            while True:
                try:
                    events.append(event_queue.get_nowait())
                except queue.Empty:
                    break

            # 批量推送（先翻译事件格式）
            for event in events:
                try:
                    await websocket.send_json(_translate_ws_event(event))
                except Exception:
                    pass

            # 检查 session 是否已关闭（用原始事件检查）
            if any(e.get("type") == "session_closed" for e in events):
                await asyncio.sleep(0.2)  # 等最后一点事件
                # 再拉一次
                try:
                    while True:
                        event = event_queue.get_nowait()
                        await websocket.send_json(_translate_ws_event(event))
                except queue.Empty:
                    pass
                break

            await asyncio.sleep(0.05)

    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        simulation_manager.event_bus.remove_queue(session_id)


# ══════════════════════════════════════════════════════════
# TTS 语音生成 API
# ══════════════════════════════════════════════════════════


class TTSRequest(BaseModel):
    """语音生成请求参数。"""
    text: str
    name: str = ""
    gender: str = "girl"
    personality: str = "cute"
    tone: str = "happy"
    speed: float = 1.0
    pitch: int = 0
    volume: float = 1.0
    language: str = "zh"  # 输出语种: zh(中文) / en(English)
    save_to_db: bool = True
    figurine_id: str = ""  # 关联的角色 ID


class TTSBatchRequest(BaseModel):
    """批量语音生成请求。复用同一套参数生成多条语音。"""
    name_template: str = "语音_{index}"
    texts: list[str]
    gender: str = "girl"
    personality: str = "cute"
    tone: str = "happy"
    speed: float = 1.0
    pitch: int = 0
    volume: float = 1.0
    language: str = "zh"  # 输出语种: zh(中文) / en(English)
    save_to_db: bool = True
    figurine_id: str = ""  # 关联的角色 ID


@app.get("/api/tts/options")
def tts_options():
    """获取 TTS 语音生成的可选参数列表（供前端下拉框使用）。"""
    return {
        "genders": GENDER_OPTIONS,
        "personalities": PERSONALITY_OPTIONS,
        "emotions": EMOTION_OPTIONS,
        "presets": [
            {
                "id": pid,
                "name": preset["name"],
                "gender": preset["gender"],
                "personality": preset["personality"],
                "description": preset["description"],
                "default_speed": preset["default_speed"],
                "default_emotion": preset["default_emotion"],
            }
            for pid, preset in CHILD_VOICE_PRESETS.items()
        ],
        "languages": [
            {"id": "zh", "label": "中文"},
            {"id": "en", "label": "English"},
        ],
        "speed_range": {"min": 0.5, "max": 2.0, "step": 0.05},
        "pitch_range": {"min": -12, "max": 12, "step": 1},
        "volume_range": {"min": 0.1, "max": 2.0, "step": 0.1},
    }


class GenerateResponse(BaseModel):
    success: bool
    id: Optional[int | str] = None  # 支持数据库 ID (int) 或临时令牌 (str)
    name: str = ""
    text: str = ""
    gender: str = ""
    personality: str = ""
    tone: str = ""
    speed: float = 1.0
    pitch: int = 0
    volume: float = 1.0
    voice_id: str = ""
    audio_path: str = ""
    duration_sec: float = 0
    file_size: int = 0
    created_at: str = ""
    params_json: str = ""
    error: str = ""


@app.post("/api/tts/generate")
def tts_generate(req: TTSRequest):
    """生成语音。

    调用 MiniMax TTS API 将文本转为语音，保存到本地缓存目录，
    并可选择持久化到数据库。
    """
    if not req.text or not req.text.strip():
        return GenerateResponse(success=False, error="文本不能为空")

    result = generate_speech(
        text=req.text.strip(),
        gender=req.gender,
        personality=req.personality,
        tone=req.tone,
        speed=req.speed,
        pitch=req.pitch,
        volume=req.volume,
        language=req.language,
        cache_dir=CACHE_DIR if req.save_to_db else None,
    )

    if not result["success"]:
        return GenerateResponse(success=False, error=result["error"])

    # 自动生成名称
    name = req.name.strip() or f"语音_{result['voice_id']}_{int(time.time())}"

    params_json_str = json.dumps({
        "gender": req.gender,
        "personality": req.personality,
        "tone": req.tone,
        "speed": req.speed,
        "pitch": req.pitch,
        "volume": req.volume,
        "language": req.language,
        "voice_id": result["voice_id"],
        "text": req.text.strip(),
    }, ensure_ascii=False)

    db_id = None
    created_at = ""
    temp_file_token = None  # 临时文件令牌（用于未保存的音频）
    
    if req.save_to_db:
        db_id = save_to_database(
            mysql_config=MYSQL_CONFIG,
            name=name,
            text=req.text.strip(),
            gender=req.gender,
            personality=req.personality,
            tone=req.tone,
            speed=req.speed,
            pitch=req.pitch,
            volume=req.volume,
            voice_id=result["voice_id"],
            audio_path=result.get("file_path", ""),
            file_size=result["file_size"],
            duration_sec=result["duration_sec"],
            params_json=params_json_str,
            figurine_id=req.figurine_id,  # 传递角色 ID
        )
        if db_id:
            from datetime import datetime
            created_at = datetime.now().isoformat()
    else:
        # 不保存数据库时，生成一个临时令牌用于访问文件
        temp_file_token = str(uuid.uuid4())
        # 将令牌和文件路径映射存储到内存中（简单实现）
        if not hasattr(tts_serve_audio, 'temp_files'):
            tts_serve_audio.temp_files = {}
        tts_serve_audio.temp_files[temp_file_token] = result.get("file_path", "")

    return GenerateResponse(
        success=True,
        id=db_id or temp_file_token,  # 如果未保存数据库，使用临时令牌
        name=name,
        text=req.text.strip(),
        gender=req.gender,
        personality=req.personality,
        tone=req.tone,
        speed=req.speed,
        pitch=req.pitch,
        volume=req.volume,
        voice_id=result["voice_id"],
        audio_path=result.get("file_path") or "",
        duration_sec=result["duration_sec"],
        file_size=result["file_size"],
        created_at=created_at,
        params_json=params_json_str,
        error="",
    )


@app.post("/api/tts/batch-generate")
def tts_batch_generate(req: TTSBatchRequest):
    """批量生成多条语音（复用同一参数配置）。"""
    if not req.texts:
        return {"success": False, "error": "texts 列表不能为空", "results": []}

    results = []
    for i, text in enumerate(req.texts):
        if not text.strip():
            continue
        name = req.name_template.replace("{index}", str(i + 1))
        single_req = TTSRequest(
            text=text.strip(),
            name=name,
            gender=req.gender,
            personality=req.personality,
            tone=req.tone,
            speed=req.speed,
            pitch=req.pitch,
            volume=req.volume,
            language=req.language,
            save_to_db=req.save_to_db,
        )
        res = tts_generate(single_req)
        results.append(res)

    success_count = sum(1 for r in results if r.success)
    return {
        "success": success_count > 0,
        "total": len(results),
        "success_count": success_count,
        "results": results,
    }


@app.get("/api/tts/generated")
def tts_list_generated(limit: int = 50, offset: int = 0, figurine_id: str = ""):
    """获取已生成的语音列表（按时间倒序）。
    
    Args:
        limit: 返回数量限制
        offset: 偏移量
        figurine_id: 角色 ID（可选，用于筛选）
    """
    records = query_generated_audio(
        mysql_config=MYSQL_CONFIG,
        limit=limit,
        offset=offset,
        figurine_id=figurine_id if figurine_id else None,
    )
    return {
        "records": records,
        "total": len(records),
    }


@app.get("/api/tts/generated/{audio_id}")
def tts_get_generated(audio_id: int):
    """获取单条生成语音的详细信息。"""
    records = query_generated_audio(mysql_config=MYSQL_CONFIG, audio_id=audio_id)
    if not records:
        return {"error": "not found"}
    return records[0]


@app.get("/api/tts/audio/{audio_id}")
def tts_serve_audio(audio_id: str):
    """提供生成语音的音频文件下载/播放。
    
    支持两种模式：
    1. 通过数据库 ID 查询（已保存到数据库的音频）
    2. 通过临时令牌访问（未保存的临时音频）
    """
    # 尝试作为临时令牌处理
    if hasattr(tts_serve_audio, 'temp_files') and audio_id in tts_serve_audio.temp_files:
        file_path = tts_serve_audio.temp_files[audio_id]
        if Path(file_path).exists():
            return FileResponse(file_path, media_type="audio/mpeg")
        else:
            return {"error": "临时音频文件已被清理"}
    
    # 尝试作为数据库 ID 查询
    try:
        db_id = int(audio_id)
        records = query_generated_audio(mysql_config=MYSQL_CONFIG, audio_id=db_id)
        if records:
            audio_path = _normalize_audio_path(records[0].get("audio_path", ""))
            if audio_path and audio_path.exists():
                return FileResponse(str(audio_path), media_type="audio/mpeg")
    except (ValueError, TypeError):
        pass

    return {"error": "音频不存在"}



@app.delete("/api/tts/generated/{audio_id}")
def tts_delete_generated(audio_id: int):
    """删除一条生成语音记录（软删除）。"""
    ok = soft_delete_audio(mysql_config=MYSQL_CONFIG, audio_id=audio_id)
    return {"success": ok, "id": audio_id}


@app.post("/api/tts/random")
def tts_generate_random(
    category: str = "mixed",
    save_to_db: bool = True,
    figurine_id: str = "",
):
    """随机生成一条测试语音。
    
    Args:
        category: 文本类别 (greeting/question/emotion/story_fragment/daily/mixed)
        save_to_db: 是否保存到数据库
        figurine_id: 关联的角色 ID
    """
    text = generate_random_text(category)
    params = generate_random_voice_params()
    
    req = TTSRequest(
        text=text,
        name=f"随机_{category}_{int(time.time())}",
        save_to_db=save_to_db,
        figurine_id=figurine_id,
        **params,
    )
    
    return tts_generate(req)


@app.post("/api/tts/random-batch")
def tts_generate_random_batch(
    count: int = 10,
    category: str = "mixed",
    save_to_db: bool = True,
    figurine_id: str = "",
):
    """批量随机生成测试语音。
    
    Args:
        count: 生成数量
        category: 文本类别
        save_to_db: 是否保存到数据库
        figurine_id: 关联的角色 ID
    """
    results = []
    for i in range(count):
        text = generate_random_text(category)
        params = generate_random_voice_params()
        
        req = TTSRequest(
            text=text,
            name=f"随机批量_{i+1}_{int(time.time())}",
            save_to_db=save_to_db,
            figurine_id=figurine_id,
            **params,
        )
        res = tts_generate(req)
        results.append(res)
    
    success_count = sum(1 for r in results if r.success)
    return {
        "success": success_count > 0,
        "total": len(results),
        "success_count": success_count,
        "results": results,
    }


@app.post("/api/tts/test-set/{figurine_id}")
def tts_generate_test_set(
    figurine_id: str,
    count_per_variant: int = 3,
):
    """为指定角色生成测试音频集。
    
    自动生成多个性别 x 性格组合的变体，用于 STT 识别测试。
    
    Args:
        figurine_id: 角色 ID
        count_per_variant: 每个变体生成的数量
    """
    results = generate_test_set_for_figurine(
        mysql_config=MYSQL_CONFIG,
        figurine_id=figurine_id,
        count_per_variant=count_per_variant,
        cache_dir=CACHE_DIR,
    )
    
    success_count = sum(1 for r in results if r.get("success"))
    return {
        "success": success_count > 0,
        "figurine_id": figurine_id,
        "total": len(results),
        "success_count": success_count,
        "results": results,
    }


@app.post("/api/tts/regenerate/{audio_id}")
def tts_regenerate(audio_id: int):
    """从数据库中的参数重新生成音频（用于复现）。
    
    如果原始记录包含种子信息，将使用相同的种子重新生成，
    确保生成的音频与原始音频完全一致。
    
    Args:
        audio_id: 音频 ID
    """
    result = regenerate_from_params(
        mysql_config=MYSQL_CONFIG,
        audio_id=audio_id,
        cache_dir=CACHE_DIR,
    )
    
    if not result["success"]:
        return {"success": False, "error": result.get("error")}
    
    return {
        "success": True,
        "audio_id": audio_id,
        "file_path": result.get("file_path"),
        "original_params": result.get("original_params"),
    }


@app.get("/api/tts/export-params/{audio_id}")
def tts_export_params(audio_id: int):
    """导出音频的完整参数配置（JSON 格式）。
    
    用于保存和分享测试配置，方便后续复现或导入。
    
    Args:
        audio_id: 音频 ID
    """
    records = query_generated_audio(
        mysql_config=MYSQL_CONFIG,
        audio_id=audio_id,
    )
    
    if not records:
        return {"error": f"音频 ID {audio_id} 不存在"}
    
    record = records[0]
    
    # 构建完整的参数配置
    config = {
        "audio_id": record["id"],
        "name": record["name"],
        "text": record["text"],
        "gender": record["gender"],
        "personality": record["personality"],
        "tone": record["tone"],
        "speed": record["speed"],
        "pitch": record["pitch"],
        "volume": record["volume"],
        "voice_id": record["tts_voice_id"],
        "figurine_id": record.get("figurine_id", ""),
        "duration_sec": record["duration_sec"],
        "file_size": record["file_size"],
        "created_at": record["created_at"],
        "params_json": record.get("params_json", ""),
    }
    
    return config


@app.post("/api/tts/import-params")
def tts_import_params(config: dict):
    """导入参数配置并生成音频。
    
    从导出的 JSON 配置中恢复参数，重新生成音频。
    
    Args:
        config: 包含所有参数的字典
    """
    text = config.get("text", "")
    if not text:
        return {"success": False, "error": "文本不能为空"}
    
    req = TTSRequest(
        text=text,
        name=config.get("name", f"导入_{int(time.time())}"),
        gender=config.get("gender", "girl"),
        personality=config.get("personality", "cute"),
        tone=config.get("tone", "happy"),
        speed=float(config.get("speed", 1.0)),
        pitch=int(config.get("pitch", 0)),
        volume=float(config.get("volume", 1.0)),
        save_to_db=True,
        figurine_id=config.get("figurine_id", ""),
    )
    
    return tts_generate(req)


# ── 发送生成语音到 chatbot 进行 STT 识别 ─────────────────────

@app.post("/api/tts/send-to-chatbot/{audio_id}")
def tts_send_to_chatbot(audio_id: int):
    """将已生成的 TTS 语音发送给 chatbot 后端进行 STT 识别。

    流程：
      1. 从数据库查询音频文件路径
      2. 读取 MP3 文件，转为 16kHz 单声道 WAV
      3. 调用 chatbot 的 /api/stt/transcribe 接口
      4. 返回识别结果

    Args:
        audio_id: 已生成语音的数据库 ID
    """
    records = query_generated_audio(mysql_config=MYSQL_CONFIG, audio_id=audio_id)
    if not records:
        return {"success": False, "error": f"音频 ID {audio_id} 不存在"}

    audio_path = str(_normalize_audio_path(records[0].get("audio_path", "")))
    if not audio_path or not Path(audio_path).exists():
        return {"success": False, "error": f"音频文件不存在: {audio_path}"}

    # 转为 16kHz mono WAV
    safe_name = Path(audio_path).stem
    wav_path = CACHE_DIR / f"{safe_name}_16k_mono.wav"
    _convert_to_wav(Path(audio_path), wav_path)

    if not wav_path.exists():
        return {"success": False, "error": "音频转换失败"}

    # 读取 PCM 数据
    import soundfile as sf
    data, sr = sf.read(str(wav_path))
    pcm_bytes = pcm_utils.float32_to_int16(data).tobytes()
    audio_b64 = base64.b64encode(pcm_bytes).decode()

    # 调用 chatbot STT
    import urllib.request
    chatbot_url = os.getenv("CHATBOT_API_URL", "http://127.0.0.1:7860")
    payload = json.dumps({"audio_b64": audio_b64, "sample_rate": sr}).encode()
    req = urllib.request.Request(
        f"{chatbot_url}/api/stt/transcribe",
        data=payload,
        headers={"Content-Type": "application/json"},
    )
    try:
        resp = urllib.request.urlopen(req, timeout=60)
        result = json.loads(resp.read())
        return {
            "success": True,
            "audio_id": audio_id,
            "transcription": result.get("text", ""),
            "language": result.get("language"),
            "audio_file": str(audio_path),
        }
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        return {"success": False, "error": f"chatbot 返回 {e.code}: {body}"}
    except Exception as e:
        return {"success": False, "error": f"请求 chatbot 失败: {e}"}


# ── TTS 翻译 ──────────────────────────────────────────────────────


@app.post("/api/tts/translate")
async def translate_text(data: dict):
    """将中文文本翻译为英文（复用 tts_adapter 的翻译功能）。"""
    text = data.get("text", "")
    if not text:
        return {"success": False, "error": "文本为空"}
    from tts_adapter import _translate_to_english
    translated = _translate_to_english(text)
    return {
        "success": True,
        "original": text,
        "translated": translated,
    }


# ── 对话与 TTS 音频关联管理 ───────────────────────────────────────

@app.post("/api/conversation/link-audio")
def link_audio_to_transcript(
    transcript_id: int,
    generated_audio_id: int,
    usage_type: str = "input",
    sequence_no: int = 0,
):
    """将 TTS 生成的音频关联到对话记录。
    
    注意: 此功能仅在测试环境启用，生产环境返回 success=false。
    
    Args:
        transcript_id: 对话记录 ID
        generated_audio_id: TTS 生成音频 ID
        usage_type: 使用类型 (input/output/debug)
        sequence_no: 序列号（一次对话中多个音频的顺序）
    """
    # 生产环境不追踪用户对话信息
    if not ENABLE_CONVERSATION_TRACKING:
        return {
            "success": False,
            "message": "对话追踪功能已禁用（生产环境）",
            "transcript_id": transcript_id,
            "generated_audio_id": generated_audio_id,
        }
    
    success = link_audio_to_conversation(
        mysql_config=MYSQL_CONFIG,
        transcript_id=transcript_id,
        generated_audio_id=generated_audio_id,
        usage_type=usage_type,
        sequence_no=sequence_no,
    )
    
    return {
        "success": success,
        "transcript_id": transcript_id,
        "generated_audio_id": generated_audio_id,
    }


@app.get("/api/conversation/{transcript_id}/audio-refs")
def get_conversation_audio_refs(transcript_id: int):
    """查询对话记录关联的所有 TTS 音频。
    
    注意: 此功能仅在测试环境启用，生产环境返回空列表。
    
    Args:
        transcript_id: 对话记录 ID
    """
    # 生产环境不追踪用户对话信息
    if not ENABLE_CONVERSATION_TRACKING:
        return {
            "transcript_id": transcript_id,
            "count": 0,
            "refs": [],
            "message": "对话追踪功能已禁用（生产环境）",
        }
    
    refs = query_conversation_audio_refs(
        mysql_config=MYSQL_CONFIG,
        transcript_id=transcript_id,
    )
    
    return {
        "transcript_id": transcript_id,
        "count": len(refs),
        "refs": refs,
    }


# ── API: 角色的对话历史与关联音频 ─────────────────────────


@app.get("/api/figurines/{figurine_id}/conversation-history")
def get_figurine_conversation_history(figurine_id: str):
    """查询某个角色的所有对话历史及其关联的 TTS 音频。
    
    Args:
        figurine_id: 角色 ID
    
    Returns:
        对话历史列表，每条包含对话记录和关联的音频信息
    """
    import pymysql
    
    results = []
    try:
        conn = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
        )
        cur = conn.cursor()
        
        # 查询该角色的所有对话记录
        cur.execute("""
            SELECT t.transcript_id, t.conversation_id, t.sequence_num, 
                   t.role, t.content, t.message_type, t.created_at
            FROM ZebConversationTranscript t
            WHERE t.conversation_id LIKE %s
            ORDER BY t.created_at DESC
        """, (f"{figurine_id}-%",))
        
        transcripts = []
        for row in cur.fetchall():
            transcripts.append({
                "transcript_id": row[0],
                "conversation_id": row[1],
                "sequence_num": row[2],
                "role": row[3],
                "content": row[4],
                "message_type": row[5],
                "created_at": row[6].isoformat() if row[6] else "",
            })
        
        # 为每个对话记录查询关联的音频
        for transcript in transcripts:
            transcript_id = transcript["transcript_id"]
            
            # 查询关联的音频
            cur.execute("""
                SELECT r.Id, r.GeneratedAudioId, r.UsageType, r.SequenceNo,
                       g.Name, g.Text, g.Gender, g.Personality, g.Tone,
                       g.Speed, g.Pitch, g.Volume, g.TtsVoiceId, g.ParamsJson,
                       g.AudioPath, g.DurationSec
                FROM ZebConversationAudioRef r
                LEFT JOIN ZebGeneratedAudio g ON r.GeneratedAudioId = g.Id
                WHERE r.TranscriptId = %s
                ORDER BY r.SequenceNo ASC
            """, (transcript_id,))
            
            audio_refs = []
            for row in cur.fetchall():
                audio_refs.append({
                    "ref_id": row[0],
                    "generated_audio_id": row[1],
                    "usage_type": row[2],
                    "sequence_no": row[3],
                    "audio_info": {
                        "name": row[4],
                        "text": row[5],
                        "gender": row[6],
                        "personality": row[7],
                        "tone": row[8],
                        "speed": row[9],
                        "pitch": row[10],
                        "volume": row[11],
                        "voice_id": row[12],
                        "params_json": row[13],
                        "audio_path": row[14],
                        "duration_sec": row[15],
                    } if row[4] else None,
                })
            
            transcript["audio_refs"] = audio_refs
            results.append(transcript)
        
        cur.close()
        conn.close()
        
    except Exception as exc:
        print(f"[API] 查询角色对话历史失败: {exc}")
        return {
            "figurine_id": figurine_id,
            "conversations": [],
            "total": 0,
            "error": str(exc),
        }
    
    return {
        "figurine_id": figurine_id,
        "conversations": results,
        "total": len(results),
    }


@app.get("/api/figurines/{figurine_id}/generated-audios")
def get_figurine_generated_audios(figurine_id: str):
    """查询某个角色关联的所有 TTS 生成音频（用于选择）。
    
    Args:
        figurine_id: 角色 ID
    
    Returns:
        生成的音频列表
    """
    import pymysql
    
    results = []
    try:
        conn = pymysql.connect(
            host=MYSQL_HOST,
            user=MYSQL_USER,
            password=MYSQL_PASSWORD,
            database=MYSQL_DATABASE,
            charset="utf8mb4",
        )
        cur = conn.cursor()
        
        # 查询该角色的所有生成音频
        cur.execute("""
            SELECT Id, Name, Text, Gender, Personality, Tone,
                   Speed, Pitch, Volume, TtsVoiceId, ParamsJson,
                   AudioPath, DurationSec, CreatedAt
            FROM ZebGeneratedAudio
            WHERE FigurineId = %s OR Name LIKE %s
            ORDER BY CreatedAt DESC
        """, (figurine_id, f"%{figurine_id}%"))
        
        for row in cur.fetchall():
            results.append({
                "id": row[0],
                "name": row[1],
                "text": row[2],
                "gender": row[3],
                "personality": row[4],
                "tone": row[5],
                "speed": row[6],
                "pitch": row[7],
                "volume": row[8],
                "voice_id": row[9],
                "params_json": row[10],
                "audio_path": row[11],
                "duration_sec": row[12],
                "created_at": row[13].isoformat() if row[13] else "",
            })
        
        cur.close()
        conn.close()
        
    except Exception as exc:
        print(f"[API] 查询角色生成音频失败: {exc}")
        return {
            "figurine_id": figurine_id,
            "audios": [],
            "total": 0,
            "error": str(exc),
        }
    
    return {
        "figurine_id": figurine_id,
        "audios": results,
        "total": len(results),
    }


# ── 指令 YAML 配置管理 ────────────────────────────────────────

COMMANDS_YAML_PATH = Path(__file__).resolve().parent / "commands.yaml"
VOICE_COMMANDS_YAML_ENV = "VOICE_COMMANDS_YAML_PATH"
CHATBOT_VOICE_COMMANDS_YAML_PATH = Path(
    os.getenv(
        VOICE_COMMANDS_YAML_ENV,
        str(Path(__file__).resolve().parents[2] / "chatbot" / "src" / "processors" / "intent" / "definitions" / "voice_commands.yaml"),
    )
).expanduser().resolve()
import yaml

@app.get("/api/commands")
def list_commands():
    """读取指令 YAML 配置，返回完整的指令数据。"""
    if not COMMANDS_YAML_PATH.exists():
        return {
            "kws_keywords": [],
            "command_intents": [],
            "mqtt_commands": [],
            "command_filters": [],
        }
    with open(COMMANDS_YAML_PATH, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data if data else {
        "kws_keywords": [],
        "command_intents": [],
        "mqtt_commands": [],
        "command_filters": [],
    }


class SaveCommandsRequest(BaseModel):
    kws_keywords: list = []
    command_intents: list = []
    mqtt_commands: list = []
    command_filters: list = []


class ChatbotVoiceCommandsPayload(BaseModel):
    content: str = ""


def _read_chatbot_voice_commands_yaml() -> str:
    if not CHATBOT_VOICE_COMMANDS_YAML_PATH.exists():
        return ""
    return CHATBOT_VOICE_COMMANDS_YAML_PATH.read_text(encoding="utf-8")


def _write_chatbot_voice_commands_yaml(content: str) -> Path:
    CHATBOT_VOICE_COMMANDS_YAML_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHATBOT_VOICE_COMMANDS_YAML_PATH.write_text(content, encoding="utf-8")
    return CHATBOT_VOICE_COMMANDS_YAML_PATH


@app.post("/api/commands/save")
def save_commands(req: SaveCommandsRequest):
    """保存指令 YAML 配置，保存后自动触发热重载。"""
    data = {
        "kws_keywords": req.kws_keywords,
        "command_intents": req.command_intents,
        "mqtt_commands": req.mqtt_commands,
        "command_filters": req.command_filters,
    }
    with open(COMMANDS_YAML_PATH, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    # ── 自动热重载指令规则引擎 ──
    try:
        rule_count = reload_engine(str(COMMANDS_YAML_PATH))
        logger.info("Command rules reloaded after save: %d rules", rule_count)
    except Exception as exc:
        logger.warning("Command rules reload after save failed: %s", exc)

    return {
        "success": True,
        "path": str(COMMANDS_YAML_PATH),
        "rules_reloaded": True,
    }


@app.post("/api/commands/reload")
def reload_command_rules():
    """手动触发指令规则引擎重载（从 commands.yaml 重新加载）。"""
    try:
        rule_count = reload_engine(str(COMMANDS_YAML_PATH))
        return {
            "success": True,
            "rules_loaded": rule_count,
            "load_count": get_engine().load_count,
        }
    except Exception as exc:
        logger.error("Command rules reload failed: %s", exc)
        return {"success": False, "error": str(exc)}


@app.get("/api/commands/stats")
def get_command_stats():
    """获取指令使用统计。

    从监控事件中收集的统计数据，包括：
    - total_matches: 总匹配次数
    - rules: 每个指令规则的命中次数
    - by_mode: 按会话模式分组的统计
    """
    try:
        return _command_stats_collector().get_summary()
    except Exception as exc:
        logger.error("Command stats error: %s", exc, exc_info=True)
        return {"success": False, "error": str(exc)}


@app.get("/api/command-config/chatbot")
def get_chatbot_command_config():
    """Read the chatbot voice command YAML as a raw editable config file."""
    return {
        "path": str(CHATBOT_VOICE_COMMANDS_YAML_PATH),
        "exists": CHATBOT_VOICE_COMMANDS_YAML_PATH.exists(),
        "content": _read_chatbot_voice_commands_yaml(),
    }


@app.put("/api/command-config/chatbot")
def replace_chatbot_command_config(payload: ChatbotVoiceCommandsPayload):
    """Replace the chatbot voice command YAML with raw file contents."""
    path = _write_chatbot_voice_commands_yaml(payload.content)
    return {"success": True, "path": str(path)}


@app.get("/api/command-config/chatbot/export")
def export_chatbot_command_config():
    """Export the chatbot voice command YAML as a download-friendly response."""
    content = _read_chatbot_voice_commands_yaml()
    filename = CHATBOT_VOICE_COMMANDS_YAML_PATH.name
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        "X-Config-Path": str(CHATBOT_VOICE_COMMANDS_YAML_PATH),
    }
    return Response(content=content, media_type="text/yaml; charset=utf-8", headers=headers)


# ── 监控 WebSocket 端点 ──────────────────────────────────────
# 用于接收 chatbot 源码中植入的监控钩子数据

monitoring_source: Optional[WebSocket] = None  # chatbot 连接（发送方）
monitoring_clients: list[WebSocket] = []  # 前端客户端（接收方）

@app.websocket("/ws/test")
async def websocket_test(websocket: WebSocket):
    """Simple test WebSocket endpoint"""
    print(f"Test WS: Connection attempt from {websocket.client}")
    await websocket.accept()
    print("Test WS: Accepted!")
    try:
        while True:
            data = await websocket.receive_text()
            await websocket.send_text(f"Echo: {data}")
    except Exception as e:
        print(f"Test WS Error: {e}")

@app.websocket("/ws/monitoring")
async def websocket_monitoring(websocket: WebSocket):
    """Monitoring endpoint - receives events from chatbot"""
    print(f"MONITORING: Connection from {websocket.client}")
    await websocket.accept()
    print("MONITORING: Accepted!")
    try:
        while True:
            data = await websocket.receive_text()
            print(f"MONITORING: Received {len(data)} bytes")
            
            # 解析 JSON 事件
            try:
                import json
                raw_event = json.loads(data)
                
                # 转发 llm_text 事件给 device_firmware（通过 EventBus + 直接注入）
                event_type = raw_event.get("type", "")
                if event_type == "llm_text":
                    text = raw_event.get("text", "")
                    chunk = raw_event.get("chunk", True)
                    session_id = raw_event.get("session_id", "")
                    # Inject into ALL active device firmwares (session_id may be absent)
                    for dev in simulation_manager._devices.values():
                        if dev._fw and dev._simulating:
                            dev._fw.collect_llm_text(text, chunk)
                            if session_id:
                                simulation_manager.event_bus.publish(session_id, {
                                    "type": "llm_text",
                                    "text": text,
                                    "chunk": chunk,
                                    "session_id": session_id,
                                })
                
                # 评估和转换事件
                transformed_event = _evaluate_and_transform_event(raw_event)
                
                # 广播给所有前端客户端
                if monitoring_clients:
                    event_json = json.dumps(transformed_event, ensure_ascii=False)
                    disconnected = []
                    for client in monitoring_clients:
                        try:
                            await client.send_text(event_json)
                        except Exception as e:
                            print(f"Failed to send to client: {e}")
                            disconnected.append(client)
                    
                    # 移除断开的客户端
                    for client in disconnected:
                        if client in monitoring_clients:
                            monitoring_clients.remove(client)
                    
                    print(f"MONITORING: Broadcasted event to {len(monitoring_clients)} clients")
                else:
                    print("MONITORING: No frontend clients connected")
                    
            except json.JSONDecodeError as e:
                print(f"MONITORING: Invalid JSON: {e}")
            except Exception as e:
                print(f"MONITORING: Error processing event: {e}")
                
    except Exception as e:
        print(f"MONITORING Error: {e}")


def _evaluate_and_transform_event(raw_event: dict) -> dict:
    """
    评估和转换 chatbot 监控事件
    
    处理流程：
    1. 验证事件格式
    2. 计算测试指标（RTF、延迟等）
    3. 添加元数据（测试会话 ID、时间戳格式化等）
    4. 标记异常状态
    
    Args:
        raw_event: chatbot 发送的原始事件
        
    Returns:
        转换后的事件，适合前端展示
    """
    event_type = raw_event.get("type", "unknown")
    
    # 基础转换：添加服务器时间戳
    transformed = {
        **raw_event,
        "received_at": time.time(),
        "source": "chatbot",
    }
    
    # 根据事件类型进行特定处理
    if event_type == "stt_inference":
        transformed = _transform_stt_event(transformed)
    elif event_type == "llm_inference":
        transformed = _transform_llm_event(transformed)
    elif event_type == "llm_text":
        pass  # LLM text chunk — forwarded to device_firmware via EventBus
    elif event_type == "tts_synthesis":
        transformed = _transform_tts_event(transformed)
    elif event_type == "intro_start" or event_type == "intro_end":
        transformed = _transform_intro_event(transformed)
    elif event_type == "moderation_complete":
        transformed = _transform_moderation_event(transformed)
    elif event_type == "output_moderation_complete":
        transformed = _transform_output_moderation_event(transformed)
    elif event_type == "vad_speech_started" or event_type == "vad_speech_stopped":
        transformed = _transform_vad_event(transformed)
    elif event_type == "kws_match":
        transformed = _transform_kws_event(transformed)
        try: _command_stats_collector().record_event(transformed)
        except: pass
    elif event_type == "command_detected":
        transformed = _transform_command_detected_event(transformed)
        try: _command_stats_collector().record_event(transformed)
        except: pass
    elif event_type == "command_forwarded":
        transformed = _transform_command_forwarded_event(transformed)
        try: _command_stats_collector().record_event(transformed)
        except: pass
    elif event_type == "mqtt_publish":
        transformed = _transform_mqtt_event(transformed)
    
    return transformed


def _transform_stt_event(event: dict) -> dict:
    """转换 STT 推理事件，计算 RTF 等指标"""
    duration_ms = event.get("duration_ms", 0)
    text_length = event.get("text_length", 0)
    
    # 计算字符/秒速率
    chars_per_sec = (text_length / (duration_ms / 1000)) if duration_ms > 0 else 0
    
    return {
        **event,
        "metrics": {
            "chars_per_sec": round(chars_per_sec, 2),
            "is_fast": chars_per_sec > 50,  # 超过 50 字符/秒为快速
        }
    }


def _transform_llm_event(event: dict) -> dict:
    """转换 LLM 推理事件"""
    duration_ms = event.get("duration_ms", 0)
    token_count = event.get("token_count", 0)
    
    # 计算 tokens/秒
    tokens_per_sec = (token_count / (duration_ms / 1000)) if duration_ms > 0 else 0
    
    return {
        **event,
        "metrics": {
            "tokens_per_sec": round(tokens_per_sec, 2),
        }
    }


def _transform_tts_event(event: dict) -> dict:
    """转换 TTS 合成事件"""
    duration_ms = event.get("duration_ms", 0)
    audio_duration_sec = event.get("audio_duration_sec", 0)
    
    # 计算 RTF (Real Time Factor)
    rtf = (duration_ms / 1000) / audio_duration_sec if audio_duration_sec > 0 else 0
    
    return {
        **event,
        "metrics": {
            "rtf": round(rtf, 3),
            "is_realtime": rtf < 1.0,  # RTF < 1.0 表示实时
        }
    }


def _transform_intro_event(event: dict) -> dict:
    """转换 Intro 事件"""
    # Intro 事件通常不需要额外计算，直接透传
    return event


def _transform_moderation_event(event: dict) -> dict:
    """转换用户输入内容审核事件"""
    duration_ms = event.get("duration_ms", 0)
    flagged = event.get("flagged", False)
    block_reasons = event.get("block_reasons", [])
    
    return {
        **event,
        "metrics": {
            "duration_ms": round(duration_ms, 2),
            "flagged": flagged,
            "block_reasons_count": len(block_reasons),
            "is_blocked": bool(block_reasons),
        }
    }


def _transform_output_moderation_event(event: dict) -> dict:
    """转换 Bot 输出内容审核事件"""
    flagged = event.get("flagged", False)
    source = event.get("source", "none")
    
    return {
        **event,
        "metrics": {
            "flagged": flagged,
            "source": source,
            "is_blocked": flagged,
        }
    }


def _transform_vad_event(event: dict) -> dict:
    """转换 VAD 语音检测事件"""
    event_type = event.get("type", "")
    
    return {
        **event,
        "metrics": {
            "is_start": event_type == "vad_speech_started",
            "is_stop": event_type == "vad_speech_stopped",
        }
    }


def _transform_kws_event(event: dict) -> dict:
    """转换 KWS 关键词匹配事件"""
    keyword = event.get("keyword", "")
    command = event.get("command", "")
    turn_id = event.get("turn_id", "")
    
    return {
        **event,
        "metrics": {
            "keyword": keyword,
            "command": command,
            "turn_id": turn_id,
            "mode": event.get("mode", "both"),
        }
    }


def _transform_command_detected_event(event: dict) -> dict:
    """转换指令拦截检测事件"""
    intent = event.get("intent", "")
    command = event.get("command", "")
    original_text = event.get("original_text", "")
    session_mode = event.get("session_mode", "")
    
    return {
        **event,
        "metrics": {
            "intent": intent,
            "command": command,
            "original_text": original_text,
            "session_mode": session_mode,
            "matched": True,
        }
    }


def _transform_command_forwarded_event(event: dict) -> dict:
    """转换指令拦截后文本转发事件"""
    return {
        **event,
        "metrics": {
            "cleaned_text": event.get("cleaned_text", ""),
            "original_text": event.get("original_text", ""),
            "is_stripped": event.get("cleaned_text", "") != event.get("original_text", ""),
        }
    }


def _transform_mqtt_event(event: dict) -> dict:
    """转换 MQTT 发布事件"""
    topic = event.get("topic", "")
    
    # 提取短名称和消息类型（复用现有的逻辑）
    short_topic = _extract_short_topic(topic)
    message_type = _SHORT_TOPIC_TO_MESSAGE_TYPE.get(short_topic, "other")
    
    return {
        **event,
        "short_topic": short_topic,
        "message_type": message_type,
    }


async def broadcast_monitoring_event(event: dict):
    """广播监控事件到所有前端客户端"""
    if not monitoring_clients:
        return
    
    message = json.dumps(event)
    disconnected = []
    
    for client in monitoring_clients:
        try:
            await client.send_text(message)
        except Exception as e:
            logger.error(f"Failed to send monitoring event: {e}")
            disconnected.append(client)
    
    # 清理断开的连接
    for client in disconnected:
        if client in monitoring_clients:
            monitoring_clients.remove(client)


@app.websocket("/ws/monitoring/events")
async def websocket_monitoring_events(websocket: WebSocket):
    """
    WebSocket 端点：向前端推送监控事件
    
    使用方式：
    1. 前端连接到 ws://localhost:8765/ws/monitoring/events
    2. 后端接收到 chatbot 的事件后，会广播给所有连接的前端客户端
    """
    await websocket.accept()
    monitoring_clients.append(websocket)
    logger.info(f"Frontend monitoring client connected. Total clients: {len(monitoring_clients)}")
    
    try:
        while True:
            # 保持连接，等待接收断开信号
            await websocket.receive_text()
    except WebSocketDisconnect:
        monitoring_clients.remove(websocket)
        logger.info(f"Frontend monitoring client disconnected. Total clients: {len(monitoring_clients)}")
    except Exception as e:
        if websocket in monitoring_clients:
            monitoring_clients.remove(websocket)
        logger.error(f"Frontend monitoring WebSocket error: {e}")


# ── 服务管理 ──────────────────────────────────────

_SERVICE_SCRIPT = "/mnt/d/zebbingo/scripts/start-local-dev.sh"

_SERVICE_INFO = {
    "bot_runner": {"name": "Bot 运行器", "display_name": "bot_runner", "port": 7860, "log": "/tmp/start-local-dev/logs/bot_runner.log", "suites": ["all", "chatbot"]},
    "stt_backend": {"name": "STT 后端", "display_name": "stt backend", "port": 8765, "log": "/tmp/start-local-dev/logs/stt_backend.log", "suites": ["all", "stt"]},
    "frontend_dev": {"name": "前端开发服务器", "display_name": "frontend dev", "port": 5173, "log": "/tmp/start-local-dev/logs/frontend_dev.log", "suites": ["all", "chatbot"]},
    "mqtt_worker": {"name": "MQTT 工作者", "display_name": "mqtt worker", "port": None, "log": "/tmp/start-local-dev/logs/mqtt_worker.log", "suites": ["all", "chatbot"]},
}

# ── 服务注释与环境变量说明 ──────────────────────────

_SERVICE_ANNOTATIONS = {
    "bot_runner": {
        "description": "Chatbot 主应用后端，处理设备语音会话全链路（STT→LLM→TTS），监听端口 :7860",
        "sensitive_env": [],
        "env_vars": [
            {"key": "CHATBOT_MQTT_ENV", "description": "MQTT 环境标识", "default": "prod"},
            {"key": "CHATBOT_MQTT_HOST", "description": "MQTT Broker 地址（127.0.0.1 = 本地 NanoMQ）", "default": "127.0.0.1"},
            {"key": "CHATBOT_MQTT_PORT", "description": "MQTT Broker 端口", "default": "1883"},
            {"key": "BOT_RUNNER_PORT", "description": "服务监听端口", "default": "7860"},
        ],
    },
    "stt_backend": {
        "description": "STT 测试平台 — ASR 离线识别 + TTS 语音生成 + MQTT 设备模拟，监听端口 :8765",
        "sensitive_env": [],
        "env_vars": [
            {"key": "STT_PORT", "description": "后端监听端口", "default": "8765"},
            {"key": "MYSQL_HOST", "description": "MySQL 数据库地址", "default": "localhost"},
            {"key": "MYSQL_USER", "description": "数据库用户", "default": "chatbot"},
            {"key": "MYSQL_DATABASE", "description": "数据库名", "default": "ZebbieDb"},
            {"key": "AWS_REGION", "description": "AWS 区域", "default": "eu-west-2"},
        ],
    },
    "frontend_dev": {
        "description": "Chatbot Vue 3 前端开发服务器（Vite HMR），监听端口 :5173",
        "sensitive_env": [],
        "env_vars": [
            {"key": "FRONTEND_PORT", "description": "前端开发服务器端口", "default": "5173"},
        ],
    },
    "mqtt_worker": {
        "description": "MQTT 工作者 — 通过 MQTT broker 与设备交互：角色选择、开场白播放、对话通信",
        "sensitive_env": [],
        "env_vars": [
            {"key": "MQTT_ENV", "description": "MQTT 环境标识", "default": "prod"},
            {"key": "MQTT_HOST", "description": "MQTT Broker 地址", "default": "127.0.0.1"},
            {"key": "MQTT_PORT", "description": "MQTT Broker 端口", "default": "1883"},
            {"key": "CHATBOT_MQTT_HANDLE_VAD_ON_SERVER", "description": "服务端 VAD 开关；本地测试默认关闭以便模拟音频走 EOS 触发", "default": "false"},
        ],
    },
}

# ── 服务环境配置（profile）定义 ──────────────────────────
# 每个服务可拥有多个预定义的配置模板（profile），
# 切换 profile 会更新对应服务的环境变量并重启服务。

_PROFILES_FILE = "/tmp/start-local-dev/service_profiles.json"

# 哪些服务支持 profile 切换（服务ID → profile 组名）
_SERVICE_PROFILE_GROUP = {
    "bot_runner": "mqtt",
    "mqtt_worker": "mqtt",
}

# 所有可用的 profile 组
_PROFILE_GROUPS = {
    "mqtt": {
        "label": "MQTT Broker",
        "description": "切换 MQTT 消息代理（影响 bot_runner + mqtt_worker）",
        "available": {
            "local": {
                "label": "本地 NanoMQ",
                "description": "使用 WSL 中的 NanoMQ broker\n地址: 127.0.0.1:1883\n认证: chiptalk / Zebbingo2024!",
                "env": {
                    "CHATBOT_MQTT_ENV": "prod",
                    "CHATBOT_MQTT_HOST": "127.0.0.1",
                    "CHATBOT_MQTT_PORT": "1883",
                    "CHATBOT_MQTT_HANDLE_VAD_ON_SERVER": "false",
                },
            },
            "cloud": {
                "label": "AWS IoT Core",
                "description": "使用 AWS IoT Core 云端 broker\n区域: eu-west-2\n端口: 8883 (TLS)\n认证: X.509 设备证书",
                "env": {
                    "CHATBOT_MQTT_ENV": "production",
                    "CHATBOT_MQTT_HOST": "<endpoint>.iot.eu-west-2.amazonaws.com",
                    "CHATBOT_MQTT_PORT": "8883",
                    "CHATBOT_MQTT_HANDLE_VAD_ON_SERVER": "true",
                },
            },
        },
    },
}


def _load_active_profiles() -> dict:
    """加载已保存的 profile 选择状态。"""
    try:
        with open(_PROFILES_FILE) as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_active_profiles(profiles: dict):
    """保存 profile 选择状态。"""
    Path(_PROFILES_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(_PROFILES_FILE, "w") as f:
        json.dump(profiles, f, indent=2)


def _get_active_profile(service_id: str) -> str:
    """获取指定服务的当前 profile 名称，默认 'local'。"""
    profiles = _load_active_profiles()
    group = _SERVICE_PROFILE_GROUP.get(service_id)
    if group:
        return profiles.get(group, "local")
    return ""


def _get_profile_env_vars(service_id: str) -> dict:
    """获取指定服务当前 profile 的环境变量覆盖。"""
    group = _SERVICE_PROFILE_GROUP.get(service_id)
    if not group:
        return {}
    active = _get_active_profile(service_id)
    group_def = _PROFILE_GROUPS.get(group)
    if not group_def:
        return {}
    profile = group_def["available"].get(active)
    if not profile:
        return {}
    return profile["env"]

_VALID_SUITES = ["all", "chatbot", "stt"]


def _run_svc_script(action: str, suite: str = "all") -> dict:
    """Run start-local-dev.sh and return result."""
    # 加载当前 profile 环境变量，注入到脚本执行环境
    env = os.environ.copy()
    active_profiles = _load_active_profiles()
    for group_name, profile_name in active_profiles.items():
        group_def = _PROFILE_GROUPS.get(group_name)
        if group_def:
            profile = group_def["available"].get(profile_name)
            if profile:
                env.update(profile["env"])
    try:
        result = subprocess.run(
            ["bash", _SERVICE_SCRIPT, action, suite],
            capture_output=True, text=True, timeout=120,
            env=env,
        )
        return {
            "success": result.returncode == 0,
            "returncode": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
    except subprocess.TimeoutExpired:
        return {"success": False, "error": "Command timed out after 120s"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


def _parse_svc_status() -> list[dict]:
    """Fetch and parse status of all managed services."""
    result = _run_svc_script("status", "all")
    services = [
        {"id": sid, "name": info["name"], "running": False, "pid": None,
         "port": info["port"], "suites": info["suites"], "log": info["log"]}
        for sid, info in _SERVICE_INFO.items()
    ]

    if not result.get("success"):
        return services

    for line in result.get("stdout", "").split("\n"):
        line = line.strip()
        # [INFO] bot_runner: running on :7860 (pid 12345)
        # [INFO] mqtt worker: running (pid 12348)
        m = re.match(r'\[INFO\]\s+(.+?):\s+running\s+(?:on\s+:\d+\s+)?\(pid\s+(\d+)\)', line)
        if m:
            display = m.group(1)
            pid = int(m.group(2))
            for svc in services:
                if _SERVICE_INFO[svc["id"]]["display_name"] == display:
                    svc["running"] = True
                    svc["pid"] = pid

    return services


@app.get("/api/services")
def api_get_services():
    """获取所有托管服务的运行状态。"""
    return {"services": _parse_svc_status()}


@app.post("/api/services/start/{suite}")
def api_start_service(suite: str):
    """启动指定服务套件。"""
    if suite not in _VALID_SUITES:
        return {"success": False, "error": f"无效套件: {suite}，有效值: {', '.join(_VALID_SUITES)}"}
    result = _run_svc_script("start", suite)
    services = _parse_svc_status()
    if result.get("success"):
        return {"success": True, "message": f"已启动 {suite} 套件", "services": services}
    return {"success": False, "error": result.get("stderr", result.get("stdout", "未知错误")), "services": services}


@app.post("/api/services/stop/{suite}")
def api_stop_service(suite: str):
    """停止指定服务套件。"""
    if suite not in _VALID_SUITES:
        return {"success": False, "error": f"无效套件: {suite}，有效值: {', '.join(_VALID_SUITES)}"}
    result = _run_svc_script("stop", suite)
    services = _parse_svc_status()
    if result.get("success"):
        return {"success": True, "message": f"已停止 {suite} 套件", "services": services}
    return {"success": False, "error": result.get("stderr", result.get("stdout", "未知错误")), "services": services}


@app.post("/api/services/restart/{suite}")
def api_restart_service(suite: str):
    """重启指定服务套件。"""
    if suite not in _VALID_SUITES:
        return {"success": False, "error": f"无效套件: {suite}，有效值: {', '.join(_VALID_SUITES)}"}
    result = _run_svc_script("restart", suite)
    services = _parse_svc_status()
    if result.get("success"):
        return {"success": True, "message": f"已重启 {suite} 套件", "services": services}
    return {"success": False, "error": result.get("stderr", result.get("stdout", "未知错误")), "services": services}


@app.get("/api/services/log/{service_id}")
def api_get_service_log(service_id: str, lines: int = 200):
    """获取指定服务的日志（最后 N 行）。"""
    if service_id not in _SERVICE_INFO:
        return {"success": False, "error": f"无效服务: {service_id}"}

    log_path = _SERVICE_INFO[service_id]["log"]
    try:
        result = subprocess.run(
            ["tail", "-n", str(lines), log_path],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return {"success": True, "log": result.stdout}
        return {"success": True, "log": f"[日志文件不存在或为空: {log_path}]"}
    except Exception as exc:
        return {"success": False, "error": str(exc)}


# ── 服务: 环境变量与 Profile ──────────────────────────


@app.get("/api/services/annotations")
def api_get_service_annotations():
    """获取所有服务的注释/说明和环境变量定义。"""
    current_profiles = _load_active_profiles()
    result = {}
    for sid, info in _SERVICE_INFO.items():
        ann = _SERVICE_ANNOTATIONS.get(sid, {})
        group_name = _SERVICE_PROFILE_GROUP.get(sid)
        profile_info = None
        if group_name:
            group_def = _PROFILE_GROUPS.get(group_name)
            active = current_profiles.get(group_name, "local")
            profile_info = {
                "group": group_name,
                "group_label": group_def["label"] if group_def else group_name,
                "group_description": group_def["description"] if group_def else "",
                "active": active,
                "available": list(group_def["available"].keys()) if group_def else [],
                "available_labels": {
                    k: v["label"] for k, v in group_def["available"].items()
                } if group_def else {},
                "available_descriptions": {
                    k: v["description"] for k, v in group_def["available"].items()
                } if group_def else {},
            }
        result[sid] = {
            "name": info["name"],
            "description": ann.get("description", ""),
            "env_vars": ann.get("env_vars", []),
            "sensitive_env": ann.get("sensitive_env", []),
            "profile": profile_info,
        }
    return result


@app.get("/api/services/{service_id}/env")
def api_get_service_env(service_id: str):
    """获取指定服务的运行时环境变量（当前 profile 生效的值）。"""
    if service_id not in _SERVICE_INFO:
        return {"success": False, "error": f"无效服务: {service_id}"}

    ann = _SERVICE_ANNOTATIONS.get(service_id, {})
    env_vars = list(ann.get("env_vars", []))

    # 获取 profile 覆盖值
    profile_overrides = _get_profile_env_vars(service_id)

    # 填充当前运行时值（优先 profile 覆盖，次优先环境中实际值，最后默认值）
    for var in env_vars:
        key = var["key"]
        if key in profile_overrides:
            var["current"] = profile_overrides[key]
            var["source"] = "profile"
        else:
            actual = os.getenv(key)
            if actual:
                var["current"] = actual
                var["source"] = "env"
            else:
                var["current"] = var.get("default", "")
                var["source"] = "default"

    return {
        "success": True,
        "service_id": service_id,
        "env_vars": env_vars,
    }


@app.post("/api/services/{service_id}/profiles")
def api_set_service_profile(service_id: str, body: dict):
    """切换指定服务的 profile（配置模板）。

    请求体: {"profile": "local"} 或 {"profile": "cloud"}
    会更新 profile 状态，然后重启关联的服务。
    """
    profile_name = body.get("profile", "")
    if service_id not in _SERVICE_INFO:
        return {"success": False, "error": f"无效服务: {service_id}"}
    if service_id not in _SERVICE_PROFILE_GROUP:
        return {"success": False, "error": f"服务 {service_id} 不支持 profile 切换"}

    group = _SERVICE_PROFILE_GROUP[service_id]
    group_def = _PROFILE_GROUPS.get(group)
    if not group_def:
        return {"success": False, "error": f"未找到 profile 组: {group}"}
    if profile_name not in group_def["available"]:
        valid = ", ".join(group_def["available"].keys())
        return {"success": False, "error": f"无效 profile: {profile_name}，可选: {valid}"}

    # 保存 profile 状态
    profiles = _load_active_profiles()
    profiles[group] = profile_name
    _save_active_profiles(profiles)

    profile_label = group_def["available"][profile_name]["label"]

    # 重启关联的服务
    restart_suites = set()
    affected_services = []
    for sid, g in _SERVICE_PROFILE_GROUP.items():
        if g == group:
            affected_services.append(sid)
            for suite_name in _SERVICE_INFO[sid]["suites"]:
                restart_suites.add(suite_name)

    # 先停止再启动关联套件
    errors = []
    for suite in restart_suites:
        stop_result = _run_svc_script("stop", suite)
        if not stop_result.get("success"):
            errors.append(f"停止 {suite} 失败: {stop_result.get('stderr', '')}")
        start_result = _run_svc_script("start", suite)
        if not start_result.get("success"):
            errors.append(f"启动 {suite} 失败: {start_result.get('stderr', '')}")

    services = _parse_svc_status()

    return {
        "success": len(errors) == 0,
        "message": f"已切换 {profile_label} profile，已重启受影响的服务",
        "profile": profile_name,
        "profile_label": profile_label,
        "affected_services": affected_services,
        "errors": errors if errors else None,
        "services": services,
    }


# ── .env 配置文件管理 ───────────────────────────
# 使用 env_scanner 动态检测 .env 文件中的开关组
# 通过"注释/取消注释"切换同一 key 的不同值，不破坏其他项目

_KNOWN_ENV_FILES = {
    "chatbot": str(Path("/home/administrator/projects/chatbot") / ".env"),
    "stt-test-tool": str(Path(__file__).resolve().parent.parent / ".env"),
}

_ENV_FILE_LABELS = {
    "chatbot": {
        "label": "Chatbot 后端",
        "description": "Zebbingo Chatbot 主应用 — MQTT / 数据库 / Redis / AWS 配置",
    },
    "stt-test-tool": {
        "label": "STT 测试平台",
        "description": "VoicePipe 测试平台后端 — MQTT / 数据库 / TTS API 配置",
    },
}


@app.get("/api/env-config/files")
def api_env_list_files():
    """列出所有已知的 .env 文件及其状态。"""
    files = []
    for file_id, path in _KNOWN_ENV_FILES.items():
        p = Path(path)
        info = _ENV_FILE_LABELS.get(file_id, {})
        files.append({
            "id": file_id,
            "path": path,
            "exists": p.exists(),
            "label": info.get("label", file_id),
            "description": info.get("description", ""),
        })
    return {"files": files}


@app.get("/api/env-config/scan/{file_id}")
def api_env_scan(file_id: str):
    """扫描指定 .env 文件的开关组（switch groups）。"""
    path = _KNOWN_ENV_FILES.get(file_id)
    if not path:
        return {"success": False, "error": f"未知文件: {file_id}"}

    raw = env_scanner.scan_env_file(path)
    if "error" in raw:
        return {"success": False, "error": raw["error"]}

    groups = []
    for key, group in raw.get("switch_groups", {}).items():
        options = []
        for opt in group["options"]:
            options.append({
                "value": opt["value"],
                "active": opt["active"],
                "line": opt["line_index"],
                "comment": opt.get("comment", ""),
            })
        groups.append({
            "key": key,
            "description": group.get("description", []),
            "options": options,
            "has_active": group["has_active"],
            "active_value": next((o["value"] for o in options if o["active"]), None),
        })

    return {
        "success": True,
        "file": path,
        "file_id": file_id,
        "file_label": _ENV_FILE_LABELS.get(file_id, {}).get("label", file_id),
        "switch_groups": groups,
        "single_var_count": raw.get("single_var_count", 0),
        "total_lines": raw.get("total_lines", 0),
    }


class EnvSwitchRequest(BaseModel):
    file_id: str
    key: str
    target_value: str


@app.post("/api/env-config/switch")
def api_env_switch(req: EnvSwitchRequest):
    """切换指定环境变量的激活选项（注释旧值，取消注释新值）。"""
    path = _KNOWN_ENV_FILES.get(req.file_id)
    if not path:
        return {"success": False, "error": f"未知文件: {req.file_id}"}

    result = env_scanner.switch_env_option(path, req.key, req.target_value)
    return result


@app.get("/{full_path:path}", include_in_schema=False)
async def serve_spa(full_path: str):
    """所有非 API 路由返回前端 index.html（SPA 模式）。"""
    if full_path.startswith("api/") or full_path.startswith("ws/"):
        from fastapi.responses import JSONResponse
        return JSONResponse({"error": "not found"}, status_code=404)
    index_path = _FRONTEND_DIST / "index.html"
    if index_path.exists():
        return HTMLResponse(content=index_path.read_text(encoding="utf-8"))
    return HTMLResponse("<h1>Frontend not built. Run: cd frontend && pnpm run build</h1>", status_code=200)


# ── 启动 ──────────────────────────────────────────────────

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8765)
