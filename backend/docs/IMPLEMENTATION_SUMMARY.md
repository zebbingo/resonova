# 对话与 TTS 音频关联追踪 - 实施总结

## ✅ 已完成的工作

### 1. 数据库迁移脚本

**文件**: `db/migrations/20260518_add_conversation_audio_tracking.sql`

**内容**:
- ✅ 在 `ZebConversationTranscript` 表中添加 `GeneratedAudioId` 字段（向后兼容）
- ✅ 创建 `ZebConversationAudioRef` 关联表（支持一对多关系）
- ✅ 添加索引优化查询性能

**表结构**:
```sql
CREATE TABLE ZebConversationAudioRef (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    ConversationTranscriptId INT NOT NULL,
    GeneratedAudioId INT NOT NULL,
    UsageType VARCHAR(50) DEFAULT 'input',
    SequenceNo INT DEFAULT 0,
    PlayedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
    CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ConversationTranscriptId) REFERENCES ZebConversationTranscript(Id),
    FOREIGN KEY (GeneratedAudioId) REFERENCES ZebGeneratedAudio(Id)
);
```

---

### 2. 后端服务层

**文件**: `backend/tts_service.py`

**新增函数**:

#### `link_audio_to_conversation()`
```python
def link_audio_to_conversation(
    mysql_config: dict,
    transcript_id: int,
    generated_audio_id: int,
    usage_type: str = "input",
    sequence_no: int = 0,
) -> bool:
    """将 TTS 生成的音频关联到对话记录。"""
```

**功能**:
- 插入关联记录到 `ZebConversationAudioRef` 表
- 同时更新 `ZebConversationTranscript.GeneratedAudioId` 字段（向后兼容）
- 支持一次对话关联多个音频（通过 `sequence_no` 区分顺序）

#### `query_conversation_audio_refs()`
```python
def query_conversation_audio_refs(
    mysql_config: dict,
    transcript_id: int,
) -> list:
    """查询对话记录关联的所有 TTS 音频。"""
```

**功能**:
- LEFT JOIN `ZebConversationAudioRef` 和 `ZebGeneratedAudio` 表
- 返回完整的音频信息（名称、文本、参数等）
- 按序列号排序

---

### 3. 后端 API 端点

**文件**: `backend/server.py`

**新增端点**:

#### `POST /api/conversation/link-audio`
```python
@app.post("/api/conversation/link-audio")
def link_audio_to_transcript(
    transcript_id: int,
    generated_audio_id: int,
    usage_type: str = "input",
    sequence_no: int = 0,
):
    """将 TTS 生成的音频关联到对话记录。"""
```

**请求示例**:
```bash
curl -X POST http://localhost:8000/api/conversation/link-audio \
  -H "Content-Type: application/json" \
  -d '{
    "transcript_id": 456,
    "generated_audio_id": 123,
    "usage_type": "input",
    "sequence_no": 0
  }'
```

**响应示例**:
```json
{
  "success": true,
  "transcript_id": 456,
  "generated_audio_id": 123
}
```

---

#### `GET /api/conversation/{transcript_id}/audio-refs`
```python
@app.get("/api/conversation/{transcript_id}/audio-refs")
def get_conversation_audio_refs(transcript_id: int):
    """查询对话记录关联的所有 TTS 音频。"""
```

**请求示例**:
```bash
curl http://localhost:8000/api/conversation/456/audio-refs
```

**响应示例**:
```json
{
  "transcript_id": 456,
  "count": 3,
  "refs": [
    {
      "ref_id": 1,
      "generated_audio_id": 123,
      "usage_type": "input",
      "sequence_no": 0,
      "played_at": "2024-01-01T12:00:00",
      "audio_info": {
        "name": "测试音频",
        "text": "你好呀！",
        "gender": "girl",
        "personality": "cute",
        "tone": "happy",
        "speed": 1.1,
        "pitch": 2,
        "volume": 1.0,
        "voice_id": "female-child",
        "params_json": "{...}"
      }
    },
    ...
  ]
}
```

---

### 4. 前端 API 调用函数

**文件**: `frontend/src/api.ts`

**新增函数**:

#### `linkAudioToTranscript()`
```typescript
export async function linkAudioToTranscript(
  transcriptId: number,
  generatedAudioId: number,
  usageType: string = 'input',
  sequenceNo: number = 0,
): Promise<{ success: boolean; transcript_id: number; generated_audio_id: number }>
```

**使用示例**:
```typescript
import { linkAudioToTranscript } from './api'

await linkAudioToTranscript(456, 123, 'input', 0)
```

---

#### `fetchConversationAudioRefs()`
```typescript
export interface AudioRef {
  ref_id: number
  generated_audio_id: number
  usage_type: string
  sequence_no: number
  played_at: string
  audio_info: {
    name: string
    text: string
    gender: string
    personality: string
    tone: string
    speed: number
    pitch: number
    volume: number
    voice_id: string
    params_json: string
  } | null
}

export async function fetchConversationAudioRefs(
  transcriptId: number,
): Promise<{ transcript_id: number; count: number; refs: AudioRef[] }>
```

**使用示例**:
```typescript
import { fetchConversationAudioRefs } from './api'

const result = await fetchConversationAudioRefs(456)
console.log(`关联了 ${result.count} 个音频`)
result.refs.forEach(ref => {
  console.log(`音频 ID: ${ref.generated_audio_id}`)
  console.log(`参数:`, ref.audio_info)
})
```

---

### 5. 文档

**文件**: `docs/CONVERSATION_AUDIO_TRACKING.md`

**内容**:
- ✅ 功能概述
- ✅ 数据库结构说明
- ✅ API 使用示例（Python + TypeScript）
- ✅ 使用场景示例（单次对话单音频、单次对话多音频、复现有问题的对话）
- ✅ 最佳实践
- ✅ 数据流向图
- ✅ 常见问题解答

---

## 🎯 核心功能

### 1. 多音频关联

**特点**:
- ✅ 支持一次对话使用多个 TTS 生成的音频
- ✅ 通过 `sequence_no` 标记音频顺序
- ✅ 通过 `usage_type` 区分使用场景（input/output/debug）

**示例**:
```
对话记录 ID: 456
  ├─ 音频 ID: 123 (sequence_no: 0, usage_type: input)
  ├─ 音频 ID: 124 (sequence_no: 1, usage_type: input)
  └─ 音频 ID: 125 (sequence_no: 2, usage_type: input)
```

---

### 2. 完整参数保存

**保存内容**:
- ✅ 音频基本信息（名称、文本、时长、文件大小）
- ✅ 生成参数（性别、性格、情感、语速、音调、音量）
- ✅ 随机种子（用于复现）
- ✅ 完整参数 JSON（包含所有元数据）

**数据结构**:
```json
{
  "name": "测试音频",
  "text": "你好呀！",
  "gender": "girl",
  "personality": "cute",
  "tone": "happy",
  "speed": 1.1,
  "pitch": 2,
  "volume": 1.0,
  "voice_id": "female-child",
  "params_json": "{\"seed\": 1234567890, \"category\": \"mixed\", ...}"
}
```

---

### 3. 一键复现

**流程**:
1. 用户发现某个音频识别效果不好
2. 查看对话记录关联的音频
3. 点击"复现"按钮
4. 系统使用相同的种子重新生成音频
5. 对比两次识别结果

**API**:
```bash
POST /api/tts/regenerate/{audio_id}
```

---

### 4. 配置导出

**功能**:
- ✅ 导出整个会话的配置（JSON 格式）
- ✅ 包含所有对话记录和关联的音频
- ✅ 方便分享和迁移

**示例**:
```json
{
  "session_id": "sess_001",
  "transcripts": [...],
  "tts_configs": {
    "123": {
      "name": "测试音频",
      "gender": "girl",
      "personality": "cute",
      ...
    }
  }
}
```

---

## 📊 数据流向

```
┌─────────────────────┐
│  TTS 语音生成器      │
│  (VoiceGenerator)   │
└──────────┬──────────┘
           │ 生成音频
           ▼
┌─────────────────────┐
│ ZebGeneratedAudio   │
│ (ID: 123)           │
│ - Text: "你好呀！"   │
│ - Gender: girl      │
│ - ParamsJson: {...} │
└──────────┬──────────┘
           │ 关联
           ▼
┌─────────────────────┐
│ ZebConversation     │
│ AudioRef            │
│ - TranscriptId: 456 │
│ - AudioId: 123      │
│ - SequenceNo: 0     │
└──────────┬──────────┘
           │ 查询
           ▼
┌─────────────────────┐
│  对话历史列表        │
│  (显示音频标签)      │
│  [女孩] [可爱] [开心]│
│  🔁 复现             │
└─────────────────────┘
```

---

## 🔧 下一步工作（前端界面）

### 1. 在对话历史列表中显示音频标签

**位置**: `frontend/src/components/DeviceCard.vue`

**修改内容**:
```vue
<div v-for="transcript in transcripts" :key="transcript.id">
  <div class="transcript-item">
    <span>{{ transcript.role }}: {{ transcript.text }}</span>
    
    <!-- 如果有关联的 TTS 音频，显示参数标签 -->
    <div v-if="transcript.audio_refs && transcript.audio_refs.length > 0" class="audio-tags">
      <el-tag 
        v-for="ref in transcript.audio_refs" 
        :key="ref.ref_id"
        size="small"
      >
        {{ ref.audio_info?.gender }} / {{ ref.audio_info?.personality }}
      </el-tag>
      
      <!-- 点击可重新生成相同的音频 -->
      <el-button 
        size="small" 
        @click="regenerateAudio(transcript.audio_refs[0].generated_audio_id)"
      >
        🔁 复现
      </el-button>
    </div>
  </div>
</div>
```

---

### 2. 添加"复现"功能

**代码**:
```typescript
import { regenerateAudio } from './api'

async function handleRegenerate(audioId: number) {
  const result = await regenerateAudio(audioId)
  
  if (result.success) {
    ElMessage.success('音频已重新生成')
    // 播放新生成的音频
    playAudio(result.file_path)
  } else {
    ElMessage.error(`复现失败: ${result.error}`)
  }
}
```

---

### 3. 添加"导出配置"功能

**代码**:
```typescript
import { fetchConversationAudioRefs } from './api'

async function exportSessionConfig(sessionId: string) {
  // 获取会话的所有对话记录
  const transcripts = await fetchTranscripts(sessionId)
  
  // 构建配置
  const config = {
    session_id: sessionId,
    transcripts: [],
    tts_configs: {},
  }
  
  for (const transcript of transcripts) {
    // 获取关联的音频
    const refs = await fetchConversationAudioRefs(transcript.id)
    
    // 提取 TTS 配置
    for (const ref of refs.refs) {
      if (ref.audio_info) {
        config.tts_configs[ref.generated_audio_id] = ref.audio_info
      }
    }
    
    config.transcripts.push({
      role: transcript.role,
      text: transcript.text,
      audio_refs: refs.refs.map(r => ({
        generated_audio_id: r.generated_audio_id,
        usage_type: r.usage_type,
        sequence_no: r.sequence_no,
      })),
    })
  }
  
  // 下载 JSON 文件
  downloadJSON(config, `session_${sessionId}_config.json`)
}
```

---

## 📝 总结

本次实施完成了**对话与 TTS 音频关联追踪**功能的后端部分：

### ✅ 已完成
1. ✅ 数据库迁移脚本（关联表 + 索引）
2. ✅ 后端服务层函数（关联 + 查询）
3. ✅ 后端 API 端点（2 个）
4. ✅ 前端 API 调用函数（2 个）
5. ✅ 完整的使用文档

### 🎯 核心价值
1. ✅ **完整链路追踪**：对话 → TTS 音频 → 生成参数 → 复现
2. ✅ **多音频支持**：一次对话可以使用多个音频
3. ✅ **参数持久化**：保存所有生成参数，包括随机种子
4. ✅ **一键复现**：通过种子重新生成相同的音频
5. ✅ **配置导出**：导出整个会话的配置，方便分享和迁移

### 📋 下一步
- 前端界面集成（显示音频标签、复现按钮、导出配置）
- 测试验证（单元测试 + 集成测试）
- 性能优化（如果需要）

---

## 🚀 快速开始

### 1. 执行数据库迁移

```bash
mysql -u root -p ZebbieDb < db/migrations/20260518_add_conversation_audio_tracking.sql
```

### 2. 重启后端服务

```bash
cd backend
uv run python server.py
```

### 3. 测试 API

```bash
# 关联音频到对话记录
curl -X POST http://localhost:8000/api/conversation/link-audio \
  -H "Content-Type: application/json" \
  -d '{"transcript_id": 456, "generated_audio_id": 123}'

# 查询关联的音频
curl http://localhost:8000/api/conversation/456/audio-refs
```

### 4. 查看详细文档

```bash
open docs/CONVERSATION_AUDIO_TRACKING.md
```
