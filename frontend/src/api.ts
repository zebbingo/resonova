import type {
  AudioListResponse,
  SttResult,
  VadSttResult,
  FigurineConfig,
  StoryItem,
  MusicItem,
  TTSOptionsResponse,
  TTSGenerateResponse,
  TTSBatchResponse,
  TTSListResponse,
  TTSGenerateRequest,
  TTSBatchRequest,
  GeneratedVoice,
} from './types'

const BASE = ''

// ── 测试音频 ─────────────────────────────────────────────

export async function fetchTestAudios(): Promise<AudioListResponse> {
  const res = await fetch(`${BASE}/api/test-audios`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function runSttTranscribe(audioId: string, language: string): Promise<SttResult> {
  const res = await fetch(`${BASE}/api/stt/transcribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ audio_id: audioId, language }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export async function runVadTranscribe(audioId: string, language: string): Promise<VadSttResult> {
  const res = await fetch(`${BASE}/api/stt/vad-transcribe`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ audio_id: audioId, language }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export function audioUrl(audioId: string): string {
  return `${BASE}/api/audio/${audioId}`
}

// ── 角色(Figurine) ──────────────────────────────────────

export interface FigurinesResponse {
  figurines: FigurineConfig[]
  total: number
}

export async function fetchFigurines(): Promise<FigurinesResponse> {
  const res = await fetch(`${BASE}/api/figurines`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ── 故事/音乐 ───────────────────────────────────────────

export interface StoriesResponse {
  stories: (StoryItem & { figurine_id?: string; track_no?: number })[]
  total: number
}

export async function fetchStories(figurineId?: string): Promise<StoriesResponse> {
  const params = figurineId ? `?figurine_id=${encodeURIComponent(figurineId)}` : ''
  const res = await fetch(`${BASE}/api/media/stories${params}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

export interface MusicResponse {
  music: (MusicItem & { figurine_id?: string; track_no?: number })[]
  total: number
}

export async function fetchMusic(figurineId?: string): Promise<MusicResponse> {
  const params = figurineId ? `?figurine_id=${encodeURIComponent(figurineId)}` : ''
  const res = await fetch(`${BASE}/api/media/music${params}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/** 获取音频播放 URL（后端代理 S3/HTTP 流式播放） */
export function mediaStreamUrl(mediaId: string): string {
  return `${BASE}/api/media/stream/${mediaId}`
}

// ── TTS 语音生成 ─────────────────────────────────────────

/** 获取 TTS 参数选项 */
export async function fetchTTSOptions(): Promise<TTSOptionsResponse> {
  const res = await fetch(`${BASE}/api/tts/options`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/** 生成单条语音 */
export async function generateTTS(req: TTSGenerateRequest): Promise<TTSGenerateResponse> {
  const res = await fetch(`${BASE}/api/tts/generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/** 批量生成语音（复用参数配置，多条文本） */
export async function batchGenerateTTS(req: TTSBatchRequest): Promise<TTSBatchResponse> {
  const res = await fetch(`${BASE}/api/tts/batch-generate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(req),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/** 获取已生成语音列表 */
export async function fetchGeneratedVoices(limit = 50, offset = 0): Promise<TTSListResponse> {
  const res = await fetch(`${BASE}/api/tts/generated?limit=${limit}&offset=${offset}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/** 获取单条已生成语音详情 */
export async function fetchGeneratedVoiceDetail(id: number): Promise<GeneratedVoice> {
  const res = await fetch(`${BASE}/api/tts/generated/${id}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/** 删除已生成语音 */
export async function deleteGeneratedVoice(id: number): Promise<{ success: boolean; id: number }> {
  const res = await fetch(`${BASE}/api/tts/generated/${id}`, { method: 'DELETE' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/** 获取已生成语音的播放 URL */
export function generatedAudioUrl(id: number): string {
  return `${BASE}/api/tts/audio/${id}`
}

/** 将中文文本翻译为英文 */
export interface TranslateResult {
  success: boolean
  original: string
  translated: string
  error?: string
}

export async function translateText(text: string): Promise<TranslateResult> {
  const res = await fetch(`${BASE}/api/tts/translate`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/** 发送已生成语音到 chatbot 进行 STT 识别 */
export interface SendToChatbotResult {
  success: boolean
  error?: string
  audio_id?: number
  transcription?: string
  language?: string
}

export async function sendToChatbot(audioId: number): Promise<SendToChatbotResult> {
  const res = await fetch(`${BASE}/api/tts/send-to-chatbot/${audioId}`, { method: 'POST' })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ── 角色 TTS 音频 ──────────────────────────────────────────

/** 获取指定角色的所有 TTS 生成音频 */
export async function fetchFigurineTTSAudios(figurineId: string): Promise<{
  records: GeneratedVoice[]
  total: number
}> {
  const res = await fetch(`${BASE}/api/figurine/${encodeURIComponent(figurineId)}/tts-audios`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

// ── 对话与 TTS 音频关联管理 ────────────────────────────────

/** 将 TTS 音频关联到对话记录 */
export async function linkAudioToTranscript(
  transcriptId: number,
  generatedAudioId: number,
  usageType: string = 'input',
  sequenceNo: number = 0,
): Promise<{ success: boolean; transcript_id: number; generated_audio_id: number }> {
  const res = await fetch(`${BASE}/api/conversation/link-audio`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      transcript_id: transcriptId,
      generated_audio_id: generatedAudioId,
      usage_type: usageType,
      sequence_no: sequenceNo,
    }),
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}

/** 查询对话记录关联的所有 TTS 音频 */
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
): Promise<{ transcript_id: number; count: number; refs: AudioRef[] }> {
  const res = await fetch(`${BASE}/api/conversation/${transcriptId}/audio-refs`)
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return res.json()
}
