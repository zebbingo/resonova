# ⚙️ 服务管理与 .env 配置管理

> 文档编号: 19 | 版本: v1.0 | 日期: 2026-05-28

本文档描述 VoicePipe 测试平台的服务管理（Service Manager）和 .env 配置管理功能。

---

## 1. 服务管理

测试平台提供了完整的服务生命周期管理 API 和 UI，支持启动/停止/重启 chatbot 和 stt 两个套件。

### 1.1 后端 API

#### GET /api/services

返回所有服务的运行状态：

```json
{
  "services": [
    {
      "id": "bot_runner",
      "name": "Bot 运行器",
      "running": true,
      "pid": 166960,
      "port": 7860,
      "suites": ["all", "chatbot"]
    },
    {
      "id": "mqtt_worker",
      "name": "MQTT 工作者",
      "running": true,
      "pid": 167005,
      "port": null,
      "suites": ["all", "chatbot"]
    },
    {
      "id": "stt_backend",
      "name": "STT 后端",
      "running": true,
      "pid": 172446,
      "port": 8765,
      "suites": ["all", "stt"]
    }
  ]
}
```

#### POST /api/services/start|stop|restart/{suite}

控制服务套件。`suite` 可选：`all`、`chatbot`、`stt`。

#### GET /api/services/annotations

返回服务注释信息（描述、环境变量说明、profile 配置）。

#### GET /api/services/log/{service_id}

获取服务日志（默认 200 行）。

#### GET /api/services/{service_id}/env

获取指定服务的环境变量详情。

#### POST /api/services/{service_id}/profiles

切换 MQTT broker profile。请求体：
```json
{"profile": "local"}
```

可选 profile：`local`（本地 Mosquitto）、`cloud`（AWS IoT Core）。

切换 profile 会自动更新环境变量并重启受影响的服务。

### 1.2 服务管理流程

```
前端 (ServiceManager.vue)
  │
  ├── GET /api/services          ← 轮询状态（5s）
  ├── POST /api/services/start   → 调用 start-local-dev.sh
  ├── POST /api/services/stop    → 调用 start-local-dev.sh
  ├── POST /api/services/restart → 先 stop 再 start
  │
  ├── GET /api/services/{id}/env      ← 环境变量详情
  └── POST /api/services/{id}/profiles → 切换 profile
       │
       ├── 1. 保存 profile 到 /tmp/start-local-dev/service_profiles.json
       ├── 2. 以 profile env 调用 start-local-dev.sh stop {suite}
       └── 3. 以 profile env 调用 start-local-dev.sh start {suite}
```

### 1.3 Profile 定义

当前支持一个 profile 组：`mqtt`

| Profile | Broker | 环境变量 |
|---------|--------|---------|
| **local** | WSL Mosquitto (127.0.0.1:1883) | `CHATBOT_MQTT_ENV=prod`, `CHATBOT_MQTT_HOST=127.0.0.1`, `CHATBOT_MQTT_PORT=1883` |
| **cloud** | AWS IoT Core (eu-west-2:8883) | `CHATBOT_MQTT_ENV=production`, `CHATBOT_MQTT_HOST=<endpoint>.iot.eu-west-2.amazonaws.com`, `CHATBOT_MQTT_PORT=8883` |

---

## 2. .env 配置管理（env_scanner）

### 2.1 设计理念

很多 .env 文件采用"注释/取消注释"的方式管理多环境配置：

```bash
# 本地开发
MQTT_HOST=127.0.0.1
# UAT 环境
# MQTT_HOST=server-sg.zebbingo.com
```

`env_scanner` 自动检测这种模式，识别出"同一个 key 出现多次 = 开关组"，并支持通过 API 切换。

### 2.2 后端 API

#### GET /api/env-config/files

列出所有已知的 .env 文件：

```json
{
  "files": [
    {"id": "chatbot", "path": "/home/administrator/projects/chatbot/.env", "exists": true, "label": "Chatbot 后端", "description": "Zebbingo Chatbot 主应用配置"},
    {"id": "stt-test-tool", "path": "/mnt/d/zebbingo/projects/stt-test-tool/.env", "exists": true, "label": "STT 测试平台", "description": "VoicePipe 测试平台后端配置"}
  ]
}
```

#### GET /api/env-config/scan/{file_id}

扫描指定 .env 文件的开关组：

```json
{
  "success": true,
  "file_id": "chatbot",
  "switch_groups": [
    {
      "key": "MQTT_HOST",
      "description": ["本地开发默认连 127.0.0.1:1883（WSL Mosquitto）", "UAT relay: 取消注释 server-sg.zebbingo.com 行"],
      "options": [
        {"value": "server-sg.zebbingo.com", "active": false, "line": 63},
        {"value": "127.0.0.1", "active": true, "line": 64}
      ],
      "has_active": true,
      "active_value": "127.0.0.1"
    }
  ]
}
```

#### POST /api/env-config/switch

切换选项（注释旧值，取消注释新值）：

```json
{"file_id": "chatbot", "key": "MQTT_HOST", "target_value": "server-sg.zebbingo.com"}
```

返回：
```json
{
  "success": true,
  "file": "/home/administrator/projects/chatbot/.env",
  "key": "MQTT_HOST",
  "active_value": "server-sg.zebbingo.com",
  "changes": [
    {"line": 63, "action": "uncommented", "value": "server-sg.zebbingo.com"},
    {"line": 64, "action": "commented_out", "value": "127.0.0.1"}
  ]
}
```

### 2.3 扫描发现的开关组

以 `chatbot/.env` 为例，扫描到 **11 个开关组**：

| Key | 本地（当前） | 云端/备选 |
|-----|------------|----------|
| MQTT_HOST | 127.0.0.1 | server-sg.zebbingo.com |
| MQTT_ENV | development | prod |
| DB_SECRET_SOURCE | local | aws |
| MYSQL_HOST | localhost | zebbingo-uat-database-1...rds.amazonaws.com |
| MYSQL_USER | chatbot | admin |
| MYSQL_PASSWORD | chatbot123 | (空) |
| MONGODB_URI | mongodb://localhost/chatbot | mongodb://docdb...amazonaws.com |
| MQTT_TLS_CA_CERT | /mnt/c/Zebbingo/iot/AmazonRootCA1.pem | C:\Zebbingo\iot\AmazonRootCA1.pem |
| MQTT_TLS_CLIENT_CERT | /mnt/c/...zebbingo-development-device.cert.pem | C:\Zebbingo\iot\server-cert.sg.pem.crt |
| MQTT_TLS_CLIENT_KEY | /mnt/c/...zebbingo-development-device.private.key | C:\Zebbingo\iot\server-private.key |
| DB_PASSWORD | UMxaJUq4tQMWis!h | difyai123456 |

### 2.4 env_scanner 核心逻辑

```python
def scan_env_file(path):
    # 1. 逐行扫描，用 regex 匹配 KEY=VALUE 或 # KEY=VALUE
    # 2. 收集每组前的注释块作为 description
    # 3. 检测行内注释（# 后面的文字）作为 option.comment
    # 4. 同一 key 出现多次 → switch_group
    # 5. 只出现一次 → single_var

def switch_env_option(path, key, target_value):
    # 1. 找到 key 对应的所有行
    # 2. 注释掉所有非目标行
    # 3. 取消注释目标行
    # 4. 写回文件
```

---

## 3. 架构关系

```
┌─────────────────────────────────────────────────────┐
│                  前端 (Vue 3)                        │
│                                                      │
│  ServiceManager.vue  ──────────┬───────── .env 面板  │
│       │                       │                      │
│       ▼                       ▼                      │
│  服务启停                 切换环境变量                 │
└───────┼───────────────────────┼──────────────────────┘
        │                       │
        ▼                       ▼
┌──────────────────────────────────────────────────────┐
│                后端 (FastAPI server.py)                │
│                                                       │
│  /api/services/*                                      │
│      → _run_svc_script() → start-local-dev.sh         │
│                                                       │
│  /api/env-config/*                                    │
│      → env_scanner.scan_env_file()                    │
│      → env_scanner.switch_env_option()                │
│      → 直接修改 .env 文件                              │
│                                                       │
│  /api/services/{id}/profiles                           │
│      → 保存 profile 状态                               │
│      → 注入 env 调用 start-local-dev.sh restart        │
└──────────────────────────────────────────────────────┘
```

---

## 4. 使用场景

### 场景 1: 本地 ↔ 云端 MQTT 切换

1. 打开测试平台 → 服务管理 → 展开 `.env 配置管理`
2. 在 `MQTT_HOST` 组中点 `server-sg.zebbingo.com`
3. 后端自动修改 `chatbot/.env`（注释掉 `127.0.0.1`，取消注释远程地址）
4. 手动重启 chatbot 套件

### 场景 2: 本地 ↔ RDS 数据库切换

1. 在 `.env 配置管理` 中切换 `MYSQL_HOST`、`MYSQL_USER`、`MYSQL_PASSWORD`
2. 同时切换 `DB_SECRET_SOURCE`
3. 重启服务后生效

### 场景 3: 通过 UI 查看/重启服务

1. 服务管理页面自动轮询服务状态（每 5 秒）
2. 展开卡片可查看日志
3. 点"重启"一键重启套件
