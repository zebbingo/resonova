# MQTT 环境不匹配与前端音频播放修复

日期: 2026-06-04

## 问题总结

全链路测试（TTS→STT→LLM）通过后，在前端 UI 上操作时遇到三个阻塞性问题：

| # | 现象 | 根因 | 状态 |
|---|------|------|------|
| 1 | 选角色后 Intro timeout (30s)，bot_mqtt 无任何日志 | 前端 localStorage 缓存了旧的 `mqttEnv: 'prod'`，resonova 发布到 `prod/...`，bot_mqtt 订阅 `development/...` | ✅ 已修复 |
| 2 | 开场白显示"播放中"但无声音 | 浏览器自动播放策略阻止 `audio.play()`，代码仅 catch 打日志 | ✅ 已修复 |
| 3 | TTS 类型定义 `id: number` 与后端 `int\|str` 不匹配 | 前端 TypeScript 类型 handoff drift | ✅ 已修复 |

## 问题 1：MQTT 环境不匹配

### 现象

- 前端连接设备 → 显示"已连接"
- 选择角色 → 显示"Intro playing..."
- 30 秒后 → "Intro timeout (30s)"
- bot_mqtt 日志无任何 session/start 消息

### 诊断过程

1. 检查 bot_mqtt 进程 → 存活，MQTT 已连接
2. 检查 bot_mqtt 订阅主题 → `$share/sess-intake/development/+/request/session/+/start`
3. 用 Python paho-mqtt 订阅 `development/#` → 15 秒内零消息
4. 订阅 `#`（所有主题）→ 发现 `prod/sim-dev-*/meta/online` 消息
5. **结论**：resonova 发布到 `prod/...`，bot_mqtt 订阅 `development/...`

### 根因

前端 `DeviceCard.vue` 的 `loadBrokerConfig()` 从 localStorage 读取历史配置。之前测试时 localStorage 缓存了 `mqttEnv: 'prod'`，代码修改默认值为 `'development'` 后，localStorage 的旧值仍然覆盖新默认值。

```typescript
// 旧代码（有 bug）
mqttEnv.value = parsed.mqttEnv || 'development'
// parsed.mqttEnv = 'prod'（truthy），|| 不会触发 fallback
```

### 修复方案

**动态获取后端配置，不硬编码**：

1. 新增 `fetchBackendMqttDefaults()` — 从 `/api/debug/runtime-config` 获取后端实际的 MQTT env/host/port
2. `setLocalBrokerDefaults()` — 使用后端动态值
3. `loadBrokerConfig()` — local profile 强制使用后端值，忽略 localStorage

```typescript
// 后端 API 返回
{ mqtt: { env: "development", host: "localhost", port: 1883 } }

// 前端 onMounted
await fetchBackendMqttDefaults()  // 先获取后端配置
loadBrokerConfig()                // 再加载本地配置

// loadBrokerConfig 中
if (mqttProfile.value === 'local') {
  // local profile: 后端配置是唯一真相源
  mqttEnv.value = _backendMqttDefaults?.env || 'development'
  mqttHost.value = _backendMqttDefaults?.host || 'localhost'
  mqttPort.value = _backendMqttDefaults?.port || 1883
}
```

### 修改文件

- `frontend/src/components/DeviceCard.vue` — `fetchBackendMqttDefaults()`, `setLocalBrokerDefaults()`, `loadBrokerConfig()`

## 问题 2：浏览器自动播放阻止

### 现象

- Intro 状态显示"播放中"
- `audio_ready` 事件通过 WebSocket 到达前端
- 但浏览器不播放音频，无声音

### 根因

Chrome/Edge 等浏览器在没有用户交互（click/keydown/touchstart）的情况下阻止 `audio.play()`。原代码仅 catch 后打 warn 日志：

```typescript
audio.play().catch(() => {
  console.warn('[Audio] Autoplay blocked, URL:', payload.url)
})
```

### 修复方案

新增 `_unlockAndPlay()` 机制：自动播放被阻止时，将音频加入待播放队列，注册一次性交互监听器，用户下次点击/按键时自动播放。

```typescript
let _audioUnlockInstalled = false
const _pendingAudio: HTMLAudioElement[] = []

function _unlockAndPlay(audio: HTMLAudioElement) {
  _pendingAudio.push(audio)
  if (!_audioUnlockInstalled) {
    _audioUnlockInstalled = true
    const handler = () => {
      document.removeEventListener('click', handler)
      document.removeEventListener('keydown', handler)
      document.removeEventListener('touchstart', handler)
      _audioUnlockInstalled = false
      for (const a of _pendingAudio) {
        a.play().catch(() => {})
      }
      _pendingAudio.length = 0
    }
    document.addEventListener('click', handler, { once: true })
    document.addEventListener('keydown', handler, { once: true })
    document.addEventListener('touchstart', handler, { once: true })
  }
}
```

### 修改文件

- `frontend/src/composables/useMQTTSimulation.ts` — `_unlockAndPlay()` + `audio_ready` handler

## 问题 3：TTS 类型定义不匹配

### 现象

- 后端 `GenerateResponse.id` 类型为 `Optional[int | str]`（数据库 ID 或临时 UUID）
- 前端 `TTSGenerateResponse.id` 类型为 `number | null`
- `generatedAudioUrl(id: number)` 参数类型不支持 string

### 修复方案

```typescript
// types.ts
id: number | string | null  // 原 number | null

// api.ts
generatedAudioUrl(id: number | string)  // 原 number
```

### 修改文件

- `frontend/src/types.ts` — `TTSGenerateResponse.id`
- `frontend/src/api.ts` — `generatedAudioUrl()`

## 附带改进

### SimulationResult 增强（P1）

- 新增 `all_commands` 字段，保存原始 MQTT 命令数据用于调试
- 新增 `_extract_reply_text()` 统一函数，支持 `text`/`reply`/`cmd` 三个字段
- 两处调用点（`send_user_turn`/`run_session`）统一使用新函数

### E2E 断言改进（P2）

- STT 断言：从关键词模糊匹配 → 归一化文本覆盖率比较（≥50%）
- 移除硬编码的 `TTS_EXPECTED_STT_KEYWORDS` 常量
- 增加 `all_commands` 到结果展示

### 共享类型契约（P0）

- 新增 `scripts/gen_ts_types.py` — 从 Pydantic model 自动生成 TypeScript 类型
- 生成结果：`frontend/src/api-types.gen.ts`
- 用法：`python scripts/gen_ts_types.py`

### 重复路由清理

- `/api/sim-audio/{filename}` 存在两个定义（行 244 和行 2644），删除重复的行 2644

## 经验教训

1. **localStorage 是隐患** — 修改代码默认值不会覆盖已缓存的 localStorage。关键配置应从后端动态获取。
2. **浏览器自动播放策略** — 所有音频播放必须处理 autoplay blocked 场景，不能静默忽略。
3. **跨进程调试** — 当 A 发消息给 B 但 B 收不到时，先用独立订阅者验证 broker 是否收到消息，再逐层排查。
4. **类型 handoff drift** — 前后端类型定义应有单一真相源（后端 Pydantic），前端自动生成。
