# 对话与 TTS 音频关联追踪 - 使用指南

## 📋 功能概述

本功能支持在对话中追踪使用的 TTS 生成音频，实现完整的链路追溯和复现能力。

**核心能力**：
1. ✅ **多音频关联**：一次对话可以使用多个 TTS 生成的音频
2. ✅ **完整参数保存**：保存每个音频的生成参数（性别、性格、情感、语速等）
3. ✅ **一键复现**：通过种子重新生成相同的音频
4. ✅ **配置导出**：导出整个会话的配置，方便分享和迁移
5. ✅ **隐私保护**：生产环境自动禁用追踪功能，保护用户隐私

---

## 🔒 隐私保护说明

### 测试环境 vs 生产环境

| 环境 | 对话追踪 | 数据库表 | 用途 |
|------|---------|---------|------|
| **测试环境** | ✅ 启用 | 创建关联表 | 调试、测试、复现问题 |
| **生产环境** | ❌ 禁用 | 不创建关联表 | 保护用户隐私，符合 GDPR |

### 如何切换环境

**方法 1：环境变量**
```bash
# 测试环境（启用追踪）
export ENVIRONMENT=test
export ENABLE_CONVERSATION_TRACKING=true

# 生产环境（禁用追踪）
export ENVIRONMENT=production
export ENABLE_CONVERSATION_TRACKING=false
```

**方法 2：.env 文件**
```ini
# .env 文件
ENVIRONMENT=test
ENABLE_CONVERSATION_TRACKING=true
```

**方法 3：启动时指定**
```bash
# 测试环境
ENVIRONMENT=test ENABLE_CONVERSATION_TRACKING=true uv run python server.py

# 生产环境
ENVIRONMENT=production ENABLE_CONVERSATION_TRACKING=false uv run python server.py
```

### API 行为差异

**测试环境**：
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
  "refs": [...]
}
```

**生产环境**：
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

## 🗄️ 数据库结构

### 1. ZebConversationAudioRef（关联表）

```sql
CREATE TABLE ZebConversationAudioRef (
    Id INT AUTO_INCREMENT PRIMARY KEY,
    ConversationTranscriptId INT NOT NULL COMMENT '对话记录 ID',
    GeneratedAudioId INT NOT NULL COMMENT 'TTS 生成音频 ID',
    UsageType VARCHAR(50) DEFAULT 'input' COMMENT '使用类型: input/output/debug',
    SequenceNo INT DEFAULT 0 COMMENT '序列号（一次对话中多个音频的顺序）',
    PlayedAt DATETIME DEFAULT CURRENT_TIMESTAMP COMMENT '播放时间',
    CreatedAt DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (ConversationTranscriptId) REFERENCES ZebConversationTranscript(Id),
    FOREIGN KEY (GeneratedAudioId) REFERENCES ZebGeneratedAudio(Id)
);
```

### 2. 关系图

```
ZebChatSession (会话)
    ↓
ZebConversationTranscript (对话记录)
    ↓
ZebConversationAudioRef (关联表) ← 支持一对多
    ↓
ZebGeneratedAudio (TTS 生成音频)
    ↓
ParamsJson (完整参数，包含种子)
```

---

## 🔧 API 使用示例

### 1. 关联音频到对话记录

**场景**：用户使用 TTS 生成的音频与角色对话后，需要记录使用的音频 ID。

```python
# Python 示例
import requests

# 假设用户选择了 TTS 音频 ID 123 进行对话
transcript_id = 456  # 对话记录 ID
generated_audio_id = 123  # TTS 生成音频 ID

response = requests.post(
    "http://localhost:8000/api/conversation/link-audio",
    params={
        "transcript_id": transcript_id,
        "generated_audio_id": generated_audio_id,
        "usage_type": "input",  # input: 用户输入, output: 角色输出
        "sequence_no": 0,  # 序列号（如果一次对话使用多个音频）
    }
)

print(response.json())
# {"success": true, "transcript_id": 456, "generated_audio_id": 123}
```

**前端 TypeScript 示例**：

```typescript
import { linkAudioToTranscript } from './api'

// 用户选择 TTS 音频后进行对话
async function handleDialogue(transcriptId: number, audioId: number) {
  await linkAudioToTranscript(
    transcriptId,
    audioId,
    'input',  // 用户输入
    0         // 第一个音频
  )
  
  console.log('音频已关联到对话记录')
}
```

---

### 2. 查询对话记录关联的所有音频

**场景**：查看某次对话中使用了哪些 TTS 音频。

```python
# Python 示例
import requests

transcript_id = 456

response = requests.get(
    f"http://localhost:8000/api/conversation/{transcript_id}/audio-refs"
)

data = response.json()
print(f"关联了 {data['count']} 个音频")

for ref in data['refs']:
    print(f"  - 音频 ID: {ref['generated_audio_id']}")
    print(f"    类型: {ref['usage_type']}")
    print(f"    序列: {ref['sequence_no']}")
    if ref['audio_info']:
        print(f"    名称: {ref['audio_info']['name']}")
        print(f"    参数: gender={ref['audio_info']['gender']}, "
              f"personality={ref['audio_info']['personality']}")
```

**前端 TypeScript 示例**：

```typescript
import { fetchConversationAudioRefs } from './api'

async function showAudioRefs(transcriptId: number) {
  const result = await fetchConversationAudioRefs(transcriptId)
  
  console.log(`关联了 ${result.count} 个音频`)
  
  result.refs.forEach(ref => {
    console.log(`  - 音频 ID: ${ref.generated_audio_id}`)
    console.log(`    类型: ${ref.usage_type}`)
    console.log(`    序列: ${ref.sequence_no}`)
    
    if (ref.audio_info) {
      console.log(`    名称: ${ref.audio_info.name}`)
      console.log(`    文本: ${ref.audio_info.text}`)
      console.log(`    参数:`, {
        gender: ref.audio_info.gender,
        personality: ref.audio_info.personality,
        tone: ref.audio_info.tone,
        speed: ref.audio_info.speed,
        pitch: ref.audio_info.pitch,
        volume: ref.audio_info.volume,
      })
    }
  })
}
```

---

### 3. 复现音频

**场景**：发现某个音频识别效果不好，需要重新生成以确认问题。

```python
# Python 示例
import requests

audio_id = 123

response = requests.post(
    f"http://localhost:8000/api/tts/regenerate/{audio_id}"
)

result = response.json()
if result['success']:
    print(f"音频已重新生成: {result['file_path']}")
    print(f"原始参数:", result['original_params'])
else:
    print(f"复现失败: {result['error']}")
```

**前端 TypeScript 示例**：

```typescript
async function regenerateAudio(audioId: number) {
  const response = await fetch(`/api/tts/regenerate/${audioId}`, {
    method: 'POST',
  })
  
  const result = await response.json()
  
  if (result.success) {
    console.log('音频已重新生成:', result.file_path)
    console.log('原始参数:', result.original_params)
    
    // 播放新生成的音频
    playAudio(result.file_path)
  } else {
    console.error('复现失败:', result.error)
  }
}
```

---

### 4. 导出会话配置

**场景**：将整个会话的配置导出为 JSON，方便分享和迁移。

```python
# Python 示例
import requests
import json

session_id = "sess_001"

# 获取会话的所有对话记录
transcripts_response = requests.get(
    f"http://localhost:8000/api/chat/session/{session_id}/transcripts"
)
transcripts = transcripts_response.json()['transcripts']

# 构建配置
config = {
    "session_id": session_id,
    "transcripts": [],
    "tts_configs": {},
}

for transcript in transcripts:
    transcript_data = {
        "role": transcript["role"],
        "text": transcript["text"],
        "timestamp": transcript["timestamp"],
    }
    
    # 获取关联的音频
    refs_response = requests.get(
        f"http://localhost:8000/api/conversation/{transcript['id']}/audio-refs"
    )
    refs = refs_response.json()['refs']
    
    if refs:
        transcript_data["audio_refs"] = []
        for ref in refs:
            transcript_data["audio_refs"].append({
                "generated_audio_id": ref["generated_audio_id"],
                "usage_type": ref["usage_type"],
                "sequence_no": ref["sequence_no"],
            })
            
            # 提取 TTS 配置
            audio_id = ref["generated_audio_id"]
            if audio_id not in config["tts_configs"] and ref["audio_info"]:
                config["tts_configs"][audio_id] = {
                    "name": ref["audio_info"]["name"],
                    "text": ref["audio_info"]["text"],
                    "gender": ref["audio_info"]["gender"],
                    "personality": ref["audio_info"]["personality"],
                    "tone": ref["audio_info"]["tone"],
                    "speed": ref["audio_info"]["speed"],
                    "pitch": ref["audio_info"]["pitch"],
                    "volume": ref["audio_info"]["volume"],
                    "params_json": ref["audio_info"]["params_json"],
                }
    
    config["transcripts"].append(transcript_data)

# 保存为 JSON 文件
with open(f"session_{session_id}_config.json", "w", encoding="utf-8") as f:
    json.dump(config, f, ensure_ascii=False, indent=2)

print(f"配置已导出到 session_{session_id}_config.json")
```

---

## 💡 使用场景示例

### 场景 1：单次对话使用单个音频

```
用户操作流程：
1. 用户在 TTS 生成器中生成音频（ID: 123）
2. 用户点击"播放并发送"按钮
3. 系统播放音频并进行 STT 识别
4. STT 识别后创建对话记录（ID: 456）
5. 系统自动关联音频到对话记录

代码流程：
```typescript
// 1. 生成音频
const generateResult = await generateTTS({
  text: "你好呀！",
  gender: "girl",
  personality: "cute",
  save_to_db: true,
})

// 2. 播放并发送
await playAndSend(generateResult.id)

// 3. STT 识别后创建对话记录
const transcript = await createTranscript({
  session_id: "sess_001",
  role: "user",
  text: recognized_text,
})

// 4. 关联音频到对话记录
await linkAudioToTranscript(
  transcript.id,
  generateResult.id,
  'input',
  0
)
```

---

### 场景 2：单次对话使用多个音频

```
用户操作流程：
1. 用户连续播放 3 个 TTS 生成的音频
2. 系统合并识别结果，创建一条对话记录
3. 系统关联所有 3 个音频到该对话记录

代码流程：
```typescript
// 1. 生成多个音频
const audioIds = [123, 124, 125]

// 2. 依次播放
for (let i = 0; i < audioIds.length; i++) {
  await playAudio(audioIds[i])
}

// 3. 合并识别结果，创建对话记录
const transcript = await createTranscript({
  session_id: "sess_001",
  role: "user",
  text: merged_text,
})

// 4. 关联所有音频到对话记录
for (let i = 0; i < audioIds.length; i++) {
  await linkAudioToTranscript(
    transcript.id,
    audioIds[i],
    'input',
    i  // 序列号
  )
}
```

---

### 场景 3：复现有问题的对话

```
用户操作流程：
1. 用户发现某次对话的识别效果不好
2. 用户查看对话记录关联的音频
3. 用户点击"复现"按钮重新生成音频
4. 系统使用相同的种子重新生成音频
5. 用户对比两次识别结果

代码流程：
```typescript
// 1. 查询对话记录关联的音频
const refs = await fetchConversationAudioRefs(transcriptId)

// 2. 对每个音频进行复现
for (const ref of refs.refs) {
  const result = await regenerateAudio(ref.generated_audio_id)
  
  if (result.success) {
    console.log(`音频 ${ref.generated_audio_id} 已复现`)
    console.log(`原始参数:`, result.original_params)
    
    // 重新进行 STT 识别
    const sttResult = await runSttTranscribe(result.file_path, 'zh-CN')
    console.log(`识别结果: ${sttResult.text}`)
  }
}
```

---

## 🎯 最佳实践

### 1. 及时关联音频

**建议**：在创建对话记录后立即关联音频，避免遗漏。

```typescript
// ✅ 推荐做法
async function handleDialogue(audioId: number, text: string) {
  // 1. 创建对话记录
  const transcript = await createTranscript({ text })
  
  // 2. 立即关联音频
  await linkAudioToTranscript(transcript.id, audioId, 'input', 0)
  
  // 3. 其他操作...
}

// ❌ 不推荐做法
async function handleDialogue(audioId: number, text: string) {
  const transcript = await createTranscript({ text })
  
  // ... 很多其他操作 ...
  
  // 最后才关联，容易遗漏
  await linkAudioToTranscript(transcript.id, audioId, 'input', 0)
}
```

---

### 2. 合理使用序列号

**建议**：如果一次对话使用多个音频，使用序列号标记顺序。

```typescript
// ✅ 推荐做法
const audioIds = [123, 124, 125]
for (let i = 0; i < audioIds.length; i++) {
  await linkAudioToTranscript(
    transcriptId,
    audioIds[i],
    'input',
    i  // 序列号：0, 1, 2
  )
}

// ❌ 不推荐做法
const audioIds = [123, 124, 125]
for (const audioId of audioIds) {
  await linkAudioToTranscript(
    transcriptId,
    audioId,
    'input',
    0  // 所有音频都是 0，无法区分顺序
  )
}
```

---

### 3. 区分使用类型

**建议**：根据音频的使用场景设置 `usage_type`。

```typescript
// 用户输入的音频
await linkAudioToTranscript(transcriptId, audioId, 'input', 0)

// 角色输出的音频
await linkAudioToTranscript(transcriptId, audioId, 'output', 0)

// 调试用的音频
await linkAudioToTranscript(transcriptId, audioId, 'debug', 0)
```

---

## 📊 数据流向图

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
│ - Personality: cute │
│ - ParamsJson: {...} │
└──────────┬──────────┘
           │ 关联
           ▼
┌─────────────────────┐
│ ZebConversation     │
│ AudioRef            │
│ - TranscriptId: 456 │
│ - AudioId: 123      │
│ - UsageType: input  │
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

## 🔍 常见问题

### Q1: 如何查看某次对话使用了哪些音频？

**A**: 调用 `GET /api/conversation/{transcript_id}/audio-refs` 接口。

### Q2: 如何复现某个音频？

**A**: 调用 `POST /api/tts/regenerate/{audio_id}` 接口，系统会使用相同的种子重新生成。

### Q3: 如何导出整个会话的配置？

**A**: 参考上面的"导出会话配置"示例，遍历所有对话记录和关联的音频，构建 JSON 配置。

### Q4: 关联表会不会影响性能？

**A**: 不会。关联表有索引（`idx_conversation_id`, `idx_audio_id`），查询速度很快。而且通常一次对话只关联 1-3 个音频，数据量很小。

### Q5: 如果删除对话记录，关联记录会自动删除吗？

**A**: 会的。关联表设置了 `ON DELETE CASCADE`，删除对话记录时会自动删除关联记录。

---

## 📝 总结

本功能实现了完整的对话与 TTS 音频关联追踪链路：

1. ✅ **多音频关联**：支持一次对话使用多个音频
2. ✅ **完整参数保存**：保存所有生成参数，包括随机种子
3. ✅ **一键复现**：通过种子重新生成相同的音频
4. ✅ **配置导出**：导出整个会话的配置，方便分享和迁移

**核心价值**：
- 🎯 **问题追踪**：当发现某个音频识别效果不好时，可以快速定位到当时的参数配置
- 🎯 **A/B 测试**：对比不同参数组合的效果
- 🎯 **知识积累**：积累优秀的参数配置，形成最佳实践
- 🎯 **团队协作**：分享优秀的测试配置
