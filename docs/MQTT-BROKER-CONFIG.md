# MQTT Broker 配置对比与集成指南

> 审计日期：2026-06-04
> 目标：确保 resonova（设备模拟器）和 chatbot（语音 AI 服务）连接同一个 broker，topic 完全对齐。

## 当前运行状态

```
┌─────────────────────────────────────────────────────────────┐
│                    NanoMQ (WSL :1883)                        │
│                    匿名认证，监听 0.0.0.0                     │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  resonova (server.py)          chatbot (bot_mqtt)           │
│  ┌──────────────────┐         ┌──────────────────┐         │
│  │ MQTT_HOST=localhost│        │ MQTT_HOST=127.0.0.1│        │
│  │ MQTT_ENV=development│      │ MQTT_ENV=development│      │
│  │ MQTT_USERNAME=(空) │        │ MQTT_USERNAME=chiptalk│     │
│  │ Profile: local     │        │ 共享订阅: sess-intake│      │
│  └──────────────────┘         └──────────────────┘         │
│                                                             │
│  发布: development/{dev}/request/session/{sid}/start        │
│  订阅: development/{dev}/response/#                         │
│                                                             │
│  订阅: $share/sess-intake/development/+/request/session/+/start │
│  发布: development/{dev}/response/audio/...                 │
└─────────────────────────────────────────────────────────────┘
```

## 环境变量对比

### 共用变量（两端都需要）

| 变量名 | Resonova 默认 | Chatbot 默认 | 当前值 | 说明 |
|--------|--------------|-------------|--------|------|
| `MQTT_HOST` | `localhost` | **无默认值** | `127.0.0.1` | ⚠️ chatbot 必须显式设置 |
| `MQTT_PORT` | `1883` | `1883` | `1883` | 一致 |
| `MQTT_ENV` | `development` | `development` | `development` | 决定 topic namespace |
| `MQTT_TLS` | `false` | `false` | `false` | 一致 |
| `MQTT_TLS_CA_CERT` | - | - | - | AWS IoT 时需要 |
| `MQTT_TLS_CLIENT_CERT` | - | - | - | AWS IoT 时需要 |
| `MQTT_TLS_CLIENT_KEY` | - | - | - | AWS IoT 时需要 |

### Resonova 独有

| 变量名 | 默认值 | 说明 |
|--------|--------|------|
| `MQTT_BROKER_PROFILE` | `local` | broker 类型：local / relay / aws_iot |
| `MQTT_RELAY_HOST` | - | relay profile 专用 |
| `MQTT_RELAY_PORT` | `1883` | relay profile 专用 |
| `MQTT_RELAY_ENV` | `development` | relay profile 专用 |

### Chatbot 独有

| 变量名 | 默认值 | 当前值 | 说明 |
|--------|--------|--------|------|
| `MQTT_USERNAME` | - | `chiptalk` | 认证用户名 |
| `MQTT_PASSWORD` | - | `Zebbingo2024!` | 认证密码 |
| `MQTT_CLIENT_ID` | 自动生成 | 模板 | 客户端 ID |
| `MQTT_USE_SHARED_SUBSCRIPTION` | `true` | `true` | 共享订阅 |
| `MQTT_SHARE_GROUP` | `sess-intake` | `sess-intake` | 共享组名 |
| `MQTT_TENANT` | `zebbingo` | `zebbingo` | 租户标识 |
| `MQTT_SESSION_TTL_SECONDS` | `300` | `300` | 会话超时 |

## Topic 对齐验证

| 方向 | Resonova | Chatbot | 匹配 |
|------|----------|---------|------|
| 上行 session/start | `development/{dev}/request/session/{sid}/start` | `$share/sess-intake/development/+/request/session/+/start` | ✅ |
| 上行 audio chunks | `development/{dev}/request/audio/{sid}/{turn}/chunk/{seq}` | `development/{dev}/request/audio/{sid}/#` | ✅ |
| 上行 meta/online | `development/{dev}/meta/online` | `development/+/meta/#` | ✅ |
| 下行 response/audio | `development/{dev}/response/audio/...` | 发布到此 topic | ✅ |
| 下行 response/command | `development/{dev}/response/command/...` | 发布到此 topic | ✅ |

## 认证问题

**当前 NanoMQ 是匿名模式**，chatbot 发送的 `chiptalk/Zebbingo2024!` 被忽略。

**如果切换到需要认证的 broker（如 EMQX、AWS IoT）：**
- Resonova 的 `local` profile 会发送空凭据 → rc=7
- 需要切换到 `relay` 或 `aws_iot` profile，并配置相应凭据

## 未来集成点：服务管理环境变量模块

### 1. 集中式 Broker 配置

```
服务管理模块
├── MQTT_HOST          → 所有服务共用
├── MQTT_PORT          → 所有服务共用
├── MQTT_ENV           → 决定 topic namespace
├── MQTT_TLS_*         → TLS 证书路径
└── MQTT_CREDENTIALS   → 认证信息（username/password）
```

### 2. Profile 切换（Resonova 独有）

```
MQTT_BROKER_PROFILE=local     → 本地开发（匿名 NanoMQ）
MQTT_BROKER_PROFILE=relay     → 远程 relay broker
MQTT_BROKER_PROFILE=aws_iot   → AWS IoT Core（TLS + 证书）
```

### 3. 注入式配置（未来）

将来可以通过服务管理模块统一注入：
```yaml
# service-config.yaml
mqtt:
  broker:
    host: "${MQTT_HOST}"
    port: "${MQTT_PORT}"
    env: "${MQTT_ENV}"
    profile: "${MQTT_BROKER_PROFILE}"
  auth:
    username: "${MQTT_USERNAME}"
    password: "${MQTT_PASSWORD}"
  tls:
    enabled: "${MQTT_TLS}"
    ca_cert: "${MQTT_TLS_CA_CERT}"
    client_cert: "${MQTT_TLS_CLIENT_CERT}"
    client_key: "${MQTT_TLS_CLIENT_KEY}"
```

### 4. 多设备测试场景

```
设备 A (resonova) ──┐
                    ├── NanoMQ ──── chatbot
设备 B (resonova) ──┘
```

- 每个设备有独立的 `device_id`，topic 自然隔离
- chatbot 通过共享订阅 `$share/sess-intake/` 分发到不同 worker
- 环境变量模块需要确保所有实例使用相同的 `MQTT_ENV`

## 常见问题

### Intro 音频超时 (30s timeout)

**症状**：前端连接设备后，等待开场白音频超时。

**根因**：前端 localStorage 缓存了旧的 `mqttEnv` 配置（如 `prod`），导致主题不匹配。

**诊断**：
```bash
# 检查后端实际配置
curl http://localhost:8765/api/debug/runtime-config | jq .mqtt

# 检查 bot_mqtt 日志
tail -f /home/administrator/projects/chatbot/output/log/bot_mqtt-*.log | grep session.*start
```

**解决方案**：前端从后端 `/api/debug/runtime-config` API 动态获取 MQTT 配置，不依赖 localStorage 缓存。

**关键代码** (`DeviceCard.vue`)：
```typescript
// 在 onMounted 中调用
await fetchBackendMqttDefaults()
loadBrokerConfig()

// local profile 始终使用后端配置
if (mqttProfile.value === 'local') {
  mqttEnv.value = _backendMqttDefaults?.env || 'development'
  mqttHost.value = _backendMqttDefaults?.host || 'localhost'
  mqttPort.value = _backendMqttDefaults?.port || 1883
}
```

**经验教训**：
- 不要在前端硬编码环境变量默认值
- 对于 local profile，始终使用后端配置
- localStorage 缓存可能导致配置漂移，需要有覆盖机制
