# TTS 语音生成功能优化总结（完整版）

## 📋 改进内容

### 1. ✅ 添加随机生成功能 ⭐⭐⭐⭐⭐

#### 后端新增功能

**随机文本生成器** (`tts_service.py`)
- `generate_random_text(category)` - 从儿童常用短语库中随机选择文本
- 支持 5 种文本类别：greeting, question, emotion, story_fragment, daily
- `category="mixed"` 时从所有类别中随机选择

**随机参数生成器** (`tts_service.py`)
- `generate_random_voice_params()` - 随机生成语音参数组合
- 随机选择：性别、性格、情感、语速、音调、音量

**可复现的随机生成器** (`tts_service.py`) ⭐ **新增**
- `generate_with_seed(seed, category)` - 使用种子生成可复现的随机参数和文本
- **确保相同种子生成完全相同的音频**
- 保存种子信息到数据库，方便后续复现

**新增 API 端点** (`server.py`)

1. **`POST /api/tts/random`** - 随机生成单条语音
   ```python
   {
     "category": "mixed",  # 文本类别
     "save_to_db": true,
     "figurine_id": ""     # 可选，关联角色
   }
   ```

2. **`POST /api/tts/random-batch`** - 批量随机生成
   ```python
   {
     "count": 10,          # 生成数量
     "category": "mixed",
     "save_to_db": true,
     "figurine_id": ""
   }
   ```

3. **`POST /api/tts/test-set/{figurine_id}`** - 为角色生成测试集
   ```python
   # 自动生成 6 种性别 x 性格组合，每种生成多条变体
   POST /api/tts/test-set/fig_001?count_per_variant=3
   ```

4. **`POST /api/tts/regenerate/{audio_id}`** - 重新生成音频（用于复现）⭐ **新增**
   ```python
   # 如果原始记录包含种子，将使用相同种子重新生成
   POST /api/tts/regenerate/123
   ```

5. **`GET /api/tts/export-params/{audio_id}`** - 导出参数配置 ⭐ **新增**
   ```python
   # 导出完整参数配置（JSON 格式）
   GET /api/tts/export-params/123
   
   # 返回：
   {
     "audio_id": 123,
     "name": "测试音频",
     "text": "你好呀！",
     "gender": "girl",
     "personality": "cute",
     "tone": "happy",
     "speed": 1.1,
     "pitch": 2,
     "volume": 1.0,
     "voice_id": "female-child",
     "figurine_id": "fig_001",
     "duration_sec": 2.5,
     "file_size": 45000,
     "created_at": "2024-01-01T12:00:00",
     "params_json": "{...}"  # 包含种子等元数据
   }
   ```

6. **`POST /api/tts/import-params`** - 导入参数配置 ⭐ **新增**
   ```python
   # 从导出的 JSON 配置中恢复参数，重新生成音频
   POST /api/tts/import-params
   Body: { ...导出的配置... }
   ```

---

### 2. ✅ 角色关联 (figurine_id)

#### 数据库表结构更新
- ✅ `ZebGeneratedAudio` 表添加 `FigurineId` 字段
- ✅ 所有生成 API 支持 `figurine_id` 参数
- ✅ 查询 API 支持按角色筛选：`GET /api/tts/generated?figurine_id=xxx`

#### 代码修改
```python
# tts_service.py - save_to_database 函数
def save_to_database(
    ...,
    figurine_id: str = "",  # 新增参数
) -> Optional[int]:
    ...
    cur.execute("""
        INSERT INTO ZebGeneratedAudio (..., FigurineId, ...)
        VALUES (..., %s, ...)
    """, (..., figurine_id, ...))
```

```python
# server.py - 查询 API
@app.get("/api/tts/generated")
def tts_list_generated(limit: int = 50, offset: int = 0, figurine_id: str = ""):
    records = query_generated_audio(
        mysql_config=MYSQL_CONFIG,
        limit=limit,
        offset=offset,
        figurine_id=figurine_id if figurine_id else None,
    )
```

---

### 3. ✅ 一键生成测试音频集

#### 功能说明
- ✅ 为指定角色自动生成 **6 种性别 x 性格组合**
- ✅ 每种组合生成多条变体（带随机性）
- ✅ 自动关联到角色，方便测试

#### 实现细节
```python
# tts_service.py - generate_test_set_for_figurine
variants = [
    {"gender": "boy", "personality": "lively", "tone": "happy"},
    {"gender": "boy", "personality": "gentle", "tone": "neutral"},
    {"gender": "boy", "personality": "naughty", "tone": "surprised"},
    {"gender": "girl", "personality": "cute", "tone": "happy"},
    {"gender": "girl", "personality": "lively", "tone": "happy"},
    {"gender": "girl", "personality": "gentle", "tone": "neutral"},
]

for variant_idx, variant in enumerate(variants):
    for i in range(count_per_variant):
        # 为每条音频生成唯一种子（确保可复现）
        seed = base_seed + variant_idx * 100 + i
        generated = generate_with_seed(seed=seed, category="mixed")
        
        # 保存完整参数（包括种子）
        params_json_str = json.dumps({
            **final_params,
            "text": text,
            "seed": seed,
            "category": "mixed",
            "base_seed": base_seed,
            "variant_index": variant_idx,
            "item_index": i,
        }, ensure_ascii=False)
```

---

### 4. ✅ 存储方案决策

#### MySQL vs MongoDB 对比

| 维度 | MySQL | MongoDB |
|------|-------|---------|
| **结构化数据** | ✅ 适合（固定字段） | ⚠️ 可以但不必要 |
| **关联查询** | ✅ 强（JOIN figurine_id） | ❌ 弱（需要应用层关联） |
| **事务支持** | ✅ 完整 ACID | ⚠️ 有限支持 |
| **现有架构** | ✅ 已有 `ZebGeneratedAudio` 表 | ❌ 需要新建集合 |
| **Resonova定位** | ✅ 测试元数据管理 | ❌ 过度设计 |

#### 💡 **结论：继续使用 MySQL**

**理由**：
1. ✅ TTS 生成音频的元数据是**高度结构化**的（文本、参数、时长等）
2. ✅ 需要与 `figurine_id` 建立**外键关联**，方便按角色筛选
3. ✅ Resonova的核心是**测试管理**，不是海量日志存储
4. ✅ 保持与现有音频系统（开场白、故事/音乐）的一致性

---

### 5. ✅ 参数持久化与复现 ⭐⭐⭐⭐⭐

#### 核心需求
> "批量和随机每一次测试的那种参数都要保存，以便于下次复现，假如有问题"

#### 实现方案

**1. 保存完整参数到数据库**
```python
# 每次生成时，保存以下信息到 ParamsJson 字段：
{
    "gender": "girl",
    "personality": "cute",
    "tone": "happy",
    "speed": 1.1,
    "pitch": 2,
    "volume": 1.0,
    "seed": 1234567890,           # 随机种子（用于复现）
    "category": "mixed",           # 文本类别
    "base_seed": 1234567800,       # 基础种子（批量生成时使用）
    "variant_index": 0,            # 变体索引
    "item_index": 0,               # 项目索引
    "generated_at": 1234567890.5,  # 生成时间戳
    "figurine_id": "fig_001"       # 关联的角色 ID
}
```

**2. 可复现的随机生成**
```python
# tts_service.py - generate_with_seed
def generate_with_seed(seed: int, category: str = "mixed") -> dict:
    """使用种子生成可复现的随机参数和文本。"""
    rng = random.Random(seed)  # 创建独立的随机数生成器
    
    # 随机选择文本
    if category == "mixed":
        all_phrases = []
        for phrases in CHILD_PHRASES.values():
            all_phrases.extend(phrases)
        text = rng.choice(all_phrases)
    else:
        phrases = CHILD_PHRASES.get(category, CHILD_PHRASES["greeting"])
        text = rng.choice(phrases)
    
    # 随机生成参数
    gender = rng.choice(["boy", "girl"])
    personality = rng.choice(["lively", "gentle", "naughty", "shy", "cute"])
    tone = rng.choice(["happy", "neutral", "surprised", "sad"])
    speed = round(rng.uniform(0.8, 1.3), 2)
    pitch = rng.randint(-6, 6)
    volume = round(rng.uniform(0.8, 1.2), 2)
    
    return {
        "text": text,
        "params": {...},
        "seed": seed,
        "category": category,
    }
```

**3. 重新生成音频（复现）**
```python
# tts_service.py - regenerate_from_params
def regenerate_from_params(mysql_config: dict, audio_id: int, cache_dir: Path = None) -> dict:
    """从数据库中的参数重新生成音频（用于复现）。"""
    # 查询原始记录
    records = query_generated_audio(mysql_config=mysql_config, audio_id=audio_id)
    record = records[0]
    
    # 解析参数 JSON
    params_json = json.loads(record.get("params_json", "{}"))
    
    # 如果有种子，使用种子重新生成（确保完全一致）
    seed = params_json.get("seed")
    if seed is not None:
        generated = generate_with_seed(seed=seed, category=params_json.get("category", "mixed"))
        text = generated["text"]
        final_params = generated["params"]
    
    # 重新生成音频
    result = generate_speech(text=text, **final_params, cache_dir=cache_dir)
    
    return {
        "success": result["success"],
        "audio_data": result.get("audio_data"),
        "file_path": result.get("file_path"),
        "original_params": {...},
        "error": result.get("error"),
    }
```

**4. 导出/导入参数配置**
```python
# server.py - 导出 API
@app.get("/api/tts/export-params/{audio_id}")
def tts_export_params(audio_id: int):
    """导出音频的完整参数配置（JSON 格式）。"""
    records = query_generated_audio(mysql_config=MYSQL_CONFIG, audio_id=audio_id)
    record = records[0]
    
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

# server.py - 导入 API
@app.post("/api/tts/import-params")
def tts_import_params(config: dict):
    """导入参数配置并生成音频。"""
    req = TTSRequest(
        text=config.get("text", ""),
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
```

---

## 🎯 使用场景示例

### 场景 1：快速生成测试音频
```bash
# 随机生成 10 条测试音频
curl -X POST http://localhost:8000/api/tts/random-batch \
  -H "Content-Type: application/json" \
  -d '{"count": 10, "category": "mixed", "save_to_db": true}'
```

### 场景 2：为角色生成测试集
```bash
# 为 Cleopatra 角色生成测试集（6 种组合 x 3 条变体 = 18 条音频）
curl -X POST http://localhost:8000/api/tts/test-set/fig_cleopatra?count_per_variant=3
```

### 场景 3：复现有问题的音频
```bash
# 假设音频 ID 123 有问题，重新生成以确认问题
curl -X POST http://localhost:8000/api/tts/regenerate/123

# 如果生成的音频仍然有问题，说明是参数问题；如果正常，说明是临时故障
```

### 场景 4：导出/分享测试配置
```bash
# 导出音频 123 的完整参数配置
curl http://localhost:8000/api/tts/export-params/123 > config_123.json

# 分享给同事，同事可以导入并重新生成
curl -X POST http://localhost:8000/api/tts/import-params \
  -H "Content-Type: application/json" \
  -d @config_123.json
```

---

## 📊 数据库表结构

```sql
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
    FigurineId VARCHAR(255) DEFAULT '' COMMENT '关联的角色ID',
    ParamsJson TEXT COMMENT '完整生成参数字符串（包含种子等元数据）',
    CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
    IsDeleted TINYINT DEFAULT 0
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
```

---

## 🔧 技术要点

### 1. 随机种子的作用
- **确保可复现性**：相同种子生成完全相同的随机序列
- **调试友好**：发现问题后，可以通过种子重新生成相同的音频
- **批量生成一致性**：批量生成时，每条音频都有唯一的种子

### 2. 参数持久化的重要性
- **问题追踪**：当发现某个音频识别效果不好时，可以查看当时的参数配置
- **A/B 测试**：对比不同参数组合的效果
- **知识积累**：积累优秀的参数配置，形成最佳实践

### 3. 导出/导入的价值
- **团队协作**：分享优秀的测试配置
- **跨环境迁移**：在不同环境之间迁移测试数据
- **版本控制**：将配置文件纳入版本控制，跟踪变化

---

## ✅ 总结

本次优化完成了以下核心功能：

1. ✅ **随机生成功能** - 快速生成测试音频，无需手动输入文本和参数
2. ✅ **角色关联** - 生成的音频可以关联到具体角色，方便按角色筛选
3. ✅ **一键生成测试集** - 为角色自动生成多种变体的测试音频
4. ✅ **参数持久化** - 保存每次生成的完整参数，包括随机种子
5. ✅ **复现功能** - 通过种子重新生成相同的音频，方便调试和问题追踪
6. ✅ **导出/导入** - 支持参数配置的导出和导入，方便团队协作

**存储方案**：继续使用 MySQL，因为 TTS 生成音频的元数据是高度结构化的，且需要与角色建立关联。

**下一步建议**：
- 前端添加"随机生成"按钮和"复现"功能
- 前端添加"导出配置"和"导入配置"功能
- 考虑将音频上传到 S3（长期优化）
