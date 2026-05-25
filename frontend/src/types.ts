/** 单个测试音频文件信息 */
export interface AudioItem {
  id: string
  name: string
  language: string
  size: number
  duration: number
  sample_rate: number
  path: string
  source: string        // "model" | "testdata" | "realtime"
  figurine_id?: string
  cached?: boolean
}

/** 角色/figurine 配置 */
export interface FigurineConfig {
  figurine_id: string
  name: string
  character_name: string
  studio_app_name?: string
  tts_type?: string
}

/** 故事内容 */
export interface StoryItem {
  id: string
  title: string
  description: string
  duration: number
  audio_url?: string
}

/** 音乐内容 */
export interface MusicItem {
  id: string
  title: string
  artist: string
  duration: number
  audio_url?: string
}

/** 简单 STT 识别结果 */
export interface SttResult {
  text: string
  duration_sec: number
  load_ms: number
  transcribe_ms: number
  rtf: number
  audio_id?: string
  error?: string
}

/** VAD 切割后的一个语音段 */
export interface VadSegment {
  index: number
  start_sec: number
  end_sec: number
  duration_sec: number
  text: string
  transcribe_ms: number
}

/** VAD + STT 管道测试结果 */
export interface VadSttResult {
  audio_id: string
  total_duration_sec: number
  segments: VadSegment[]
  segment_count: number
  error?: string
}

/** API 响应的包装 */
export interface AudioListResponse {
  audios: AudioItem[]
  total: number
}

// ── TTS 语音生成 ─────────────────────────────────────────

/** TTS 参数选项（前端下拉框用） */
export interface TTSPreset {
  id: string
  name: string
  gender: string
  personality: string
  description: string
  default_speed: number
  default_emotion: string
}

export interface TTSOptionItem {
  id: string
  label: string
}

export interface TTSRange {
  min: number
  max: number
  step: number
}

export interface TTSParams {
  gender: string
  personality: string
  tone: string
  speed: number
  pitch: number
  volume: number
  voice_id: string
  text: string
}

/** TTS 选项响应 */
export interface TTSOptionsResponse {
  genders: TTSOptionItem[]
  personalities: TTSOptionItem[]
  emotions: TTSOptionItem[]
  presets: TTSPreset[]
  languages: TTSOptionItem[]
  speed_range: TTSRange
  pitch_range: TTSRange
  volume_range: TTSRange
}

/** 单条生成语音记录 */
export interface GeneratedVoice {
  id: number
  name: string
  text: string
  gender: string
  personality: string
  tone: string
  speed: number
  pitch: number
  volume: number
  tts_type: string
  tts_voice_id: string
  audio_path: string
  duration_sec: number
  file_size: number
  params_json: string
  created_at: string
}

/** TTS 生成请求 */
export interface TTSGenerateRequest {
  text: string
  name: string
  gender: string
  personality: string
  tone: string
  speed: number
  pitch: number
  volume: number
  language: string
  save_to_db: boolean
  figurine_id?: string
}

/** TTS 生成响应（含生成单条的结果） */
export interface TTSGenerateResponse {
  success: boolean
  id: number | null
  name: string
  text: string
  gender: string
  personality: string
  tone: string
  speed: number
  pitch: number
  volume: number
  voice_id: string
  audio_path: string
  duration_sec: number
  file_size: number
  created_at: string
  params_json: string
  error: string
}

/** 批量生成请求 */
export interface TTSBatchRequest {
  name_template: string
  texts: string[]
  gender: string
  personality: string
  tone: string
  speed: number
  pitch: number
  volume: number
  language: string
  save_to_db: boolean
}

/** 批量生成响应 */
export interface TTSBatchResponse {
  success: boolean
  total: number
  success_count: number
  results: TTSGenerateResponse[]
}

/** 已生成语音列表响应 */
export interface TTSListResponse {
  records: GeneratedVoice[]
  total: number
}
