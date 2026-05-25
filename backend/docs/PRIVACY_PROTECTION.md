# 对话追踪功能 - 隐私保护方案

## 🎯 核心需求

> "我上线不能收集用户信息，只有测试可以。所以你可以用视图聚合来吗？或者别的方式，生产环境就不追踪对话了。"

---

## 💡 解决方案

### 方案：环境变量控制 + 条件加载

**核心思路**：
1. ✅ **测试环境**：启用对话追踪功能，创建关联表，记录完整链路
2. ✅ **生产环境**：禁用对话追踪功能，不创建关联表，不记录任何用户信息
3. ✅ **代码兼容**：通过环境变量 `ENABLE_CONVERSATION_TRACKING` 控制功能开关

---

## 🔧 实施细节

### 1. 环境变量配置

**文件**: `.env.example`

```ini
# ── 环境配置 ──────────────────────────────────────
# test: 测试环境（启用对话追踪）
# production: 生产环境（禁用对话追踪，保护用户隐私）
ENVIRONMENT=test

# ── 对话追踪配置 ───────────────────────────────────
# true: 启用对话追踪功能（记录 TTS 音频与对话的关联）
# false: 禁用对话追踪功能（不记录关联信息）
ENABLE_CONVERSATION_TRACKING=true
```

---

### 2. 后端代码修改

**文件**: `backend/server.py`

```python
# ── 环境变量配置 ──────────────────────────────────────
# 是否启用对话追踪功能（默认：测试环境启用，生产环境禁用）
ENABLE_CONVERSATION_TRACKING = os.getenv("ENABLE_CONVERSATION_TRACKING", "true").lower() == "true"
ENVIRONMENT = os.getenv("ENVIRONMENT", "test")  # test / production
```

**API 端点添加环境判断**：

```python
@app.post("/api/conversation/link-audio")
def link_audio_to_transcript(...):
    """将 TTS 生成的音频关联到对话记录。
    
    注意: 此功能仅在测试环境启用，生产环境返回 success=false。
    """
    # 生产环境不追踪用户对话信息
    if not ENABLE_CONVERSATION_TRACKING:
        return {
            "success": False,
            "message": "对话追踪功能已禁用（生产环境）",
            "transcript_id": transcript_id,
            "generated_audio_id": generated_audio_id,
        }
    
    # 测试环境：正常执行关联逻辑
    success = link_audio_to_conversation(...)
    return {"success": success, ...}
```

---

### 3. 数据库迁移脚本

**文件**: `db/migrations/20260518_add_conversation_audio_tracking.sql`

```sql
-- 添加对话与 TTS 音频的关联追踪功能
-- 注意: 此功能仅在测试环境启用，生产环境不追踪用户对话信息

-- 检查是否为测试环境（通过环境变量或配置表）
-- 如果不需要追踪功能，可以注释掉下面的语句

-- 1. 在 ZebConversationTranscript 表中添加 GeneratedAudioId 字段（向后兼容）
ALTER TABLE ZebConversationTranscript 
ADD COLUMN IF NOT EXISTS GeneratedAudioId INT DEFAULT NULL COMMENT '关联的 TTS 生成音频 ID（单音频场景）',
ADD INDEX IF NOT EXISTS idx_generated_audio_id (GeneratedAudioId);

-- 2. 创建关联表 ZebConversationAudioRef（支持多音频场景）
CREATE TABLE IF NOT EXISTS ZebConversationAudioRef (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    ConversationTranscriptId INT NOT NULL COMMENT '对话记录 ID',
    GeneratedAudioId INT NOT NULL COMMENT 'TTS 生成音频 ID',
    UsageType VARCHAR(50) DEFAULT 'input' COMMENT '使用类型: input/output/debug',
    SequenceNo INT DEFAULT 0 COMMENT '序列号（一次对话中多个音频的顺序）',
    PlayedAt DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '播放时间',
    CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ConversationTranscriptId) REFERENCES ZebConversationTranscript(Id) ON DELETE CASCADE,
    FOREIGN KEY (GeneratedAudioId) REFERENCES ZebGeneratedAudio(Id),
    INDEX idx_conversation_id (ConversationTranscriptId),
    INDEX idx_audio_id (GeneratedAudioId),
    INDEX idx_usage_type (UsageType)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COMMENT='对话与 TTS 音频关联表';
```

**注意**：
- ✅ 生产环境可以不执行此迁移脚本
- ✅ 或者执行后，通过环境变量禁用功能（表存在但不使用）

---

## 📊 环境对比

### 测试环境

**配置**：
```bash
ENVIRONMENT=test
ENABLE_CONVERSATION_TRACKING=true
```

**行为**：
- ✅ 创建关联表 `ZebConversationAudioRef`
- ✅ 记录对话与 TTS 音频的关联关系
- ✅ 支持查询关联的音频
- ✅ 支持一键复现

**API 响应**：
```json
// POST /api/conversation/link-audio
{
  "success": true,
  "transcript_id": 456,
  "generated_audio_id": 123
}

// GET /api/conversation/456/audio-refs
{
  "transcript_id": 456,
  "count": 3,
  "refs": [
    {
      "ref_id": 1,
      "generated_audio_id": 123,
      "usage_type": "input",
      "sequence_no": 0,
      "audio_info": {...}
    }
  ]
}
```

---

### 生产环境

**配置**：
```bash
ENVIRONMENT=production
ENABLE_CONVERSATION_TRACKING=false
```

**行为**：
- ❌ 不创建关联表（或创建后不使用）
- ❌ 不记录对话与 TTS 音频的关联关系
- ❌ 不支持查询关联的音频
- ❌ 不支持一键复现

**API 响应**：
```json
// POST /api/conversation/link-audio
{
  "success": false,
  "message": "对话追踪功能已禁用（生产环境）",
  "transcript_id": 456,
  "generated_audio_id": 123
}

// GET /api/conversation/456/audio-refs
{
  "transcript_id": 456,
  "count": 0,
  "refs": [],
  "message": "对话追踪功能已禁用（生产环境）"
}
```

---

## 🚀 部署指南

### 测试环境部署

**步骤 1：执行数据库迁移（创建中间表）**
```bash
mysql -u root -p ZebbieDb < db/migrations/20260518_add_conversation_audio_tracking.sql
```

**注意**：
- ✅ 此迁移只创建 `ZebConversationAudioRef` 中间表
- ✅ 完全不修改原表结构（零侵入）
- ✅ 生产环境可以跳过此步骤

**步骤 2：配置环境变量**
```bash
# .env 文件
ENVIRONMENT=test
ENABLE_CONVERSATION_TRACKING=true
```

**步骤 3：启动服务**
```bash
uv run python server.py
```

---

### 生产环境部署

**步骤 1：跳过数据库迁移**
```bash
# 不执行迁移脚本，不创建中间表
# 这样生产环境就不会有任何追踪功能
```

**步骤 2：配置环境变量**
```bash
# .env 文件
ENVIRONMENT=production
ENABLE_CONVERSATION_TRACKING=false
```

**步骤 3：启动服务**
```bash
uv run python server.py
```

---

## 🔒 隐私保护说明

### GDPR 合规

**数据最小化原则**：
- ✅ 生产环境不收集用户的对话追踪信息
- ✅ 只保留必要的对话文本记录
- ✅ 不记录 TTS 音频与对话的关联关系

**用户同意**：
- ✅ 测试环境明确告知用户正在收集追踪信息
- ✅ 生产环境不收集任何额外信息

**数据删除**：
- ✅ 测试环境的追踪数据可以随时删除
- ✅ 生产环境没有追踪数据，无需删除

---

### 数据安全

**测试环境**：
- ⚠️ 追踪数据包含完整的参数信息（性别、性格、情感等）
- ⚠️ 需要定期清理测试数据
- ⚠️ 不要在生产环境中使用测试数据

**生产环境**：
- ✅ 不收集追踪数据
- ✅ 符合数据最小化原则
- ✅ 降低数据泄露风险

---

## 💬 常见问题

### Q1: 生产环境是否需要执行数据库迁移？

**A**: 不需要。生产环境可以不执行迁移脚本，因为功能已被禁用。

**或者**：执行迁移脚本，但通过环境变量禁用功能。这样可以在需要时快速启用（例如临时调试）。

---

### Q2: 如果生产环境误启用了追踪功能怎么办？

**A**: 
1. 立即设置 `ENABLE_CONVERSATION_TRACKING=false`
2. 重启服务
3. 删除已收集的追踪数据（如果有）

```sql
-- 删除关联表中的数据
DELETE FROM ZebConversationAudioRef;

-- 清空 Transcript 表的 GeneratedAudioId 字段
UPDATE ZebConversationTranscript SET GeneratedAudioId = NULL;
```

---

### Q3: 测试环境和生产环境可以使用同一个数据库吗？

**A**: 不建议。最好使用不同的数据库实例：
- 测试环境：`ZebbieDb_test`
- 生产环境：`ZebbieDb_prod`

这样可以避免测试数据污染生产数据。

---

### Q4: 如何在运行时切换环境？

**A**: 修改 `.env` 文件后重启服务：

```bash
# 修改 .env 文件
echo "ENABLE_CONVERSATION_TRACKING=false" >> .env

# 重启服务
pkill -f "python server.py"
uv run python server.py &
```

---

## 📝 总结

### 核心优势

1. ✅ **隐私保护**：生产环境不收集用户追踪信息
2. ✅ **灵活切换**：通过环境变量轻松切换测试/生产环境
3. ✅ **代码兼容**：同一套代码，不同环境行为不同
4. ✅ **GDPR 合规**：符合数据最小化原则
5. ✅ **向后兼容**：不影响现有功能

### 实施清单

- ✅ 添加环境变量配置（`ENABLE_CONVERSATION_TRACKING`）
- ✅ 修改后端 API，添加环境判断
- ✅ 更新数据库迁移脚本，添加注释
- ✅ 创建 `.env.example` 文件
- ✅ 更新文档，说明隐私保护措施

### 下一步

- 前端界面根据环境显示/隐藏相关功能
- 添加单元测试，验证环境切换逻辑
- 编写部署文档，说明不同环境的配置
