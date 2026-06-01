# 生产部署架构现状报告

> 基于 chatbot 仓库 main 分支 + 完整源码分析 | 2026-05-26

---

## 总结一句话

**你们现在的架构实际上走了"路线 A+B 混合"——$share 发现 + Redis SETNX 认领。bot_mqtt 在生产是以独立进程跑的，但 Docker CMD 只配了 bot_runner。生产 broker（AWS IoT Core）支持 $share，所以不需要额外改架构。**

---

## 1. 生产到底怎么部署的

### Docker 层面

```dockerfile
# Dockerfile CMD:
CMD ["uv", "run", "src/bot_runner.py"]
```

**一个容器只跑一个进程——bot_runner.py**。它不是 monolith，它同时承担：
- HTTP API Server（FastAPI :7860）
- MQTTDeviceManager（后台协程管理设备在线/OTA）
- 按需 spawn 子进程（Daily WebRTC bot）

### bot_mqtt 怎么跑

**不在 Docker CMD 里。** bot_mqtt 是**独立启动的进程**（手动启动或编排系统拉起），可以有多个实例水平扩展：

```bash
# 每个 worker:
PYTHONPATH=... nohup python -m src.bot_mqtt &
```

### MQTT 统一用 AWS IoT Core

- **不是走 Rule→HTTP ingress**（那是 zebbingo-api 业务链路的做法）
- 语音走**原生 MQTT 长连接**，X.509 证书认证
- AWS IoT Core **支持 $share 共享订阅**（MQTT 5 特性）

---

## 2. 会话归属机制：$share + Redis 双重保障

你们不是"只靠 $share"，而是做了双重锁：

```
设备发 session/start
    │
    ▼
$share/sess-intake/...  ←  broker 层负载均衡
    │
    ▼
每个 worker 都收到
    │
    ▼
Redis SETNX sess:<session_id> = worker_id  ← 原子认领
    │
    ▼
成功 → 订阅 session 级 topic (Pin)
失败 → 清理本地状态 (Drop)
```

| 层 | 作用 | 失败兜底 |
|:---|:-----|:---------|
| **$share**（MQTT 层） | 避免所有 worker 都收到同一消息 | 如果 broker 不支持 → 后面 Redis 还能兜底 |
| **Redis SETNX**（应用层） | 原子性确定唯一 owner | 6s 超时接管（worker 挂了自动转移） |
| **Worker 心跳** | 每 TTL/3 刷新 | stale_threshold 超时后允许 takeover |

---

## 3. 每条路线对应的现状

| 路线 | 你问的"我们做了多少" | 现状 |
|:-----|:-------------------|:-----|
| **A) 单消费者** | 未落地作为兜底方案 | 实际上就是多 worker + Redis 锁，$share 不工作也能兜底 |
| **B) 外部分发** | 做了 Redis 层 | SessionAffinityManager 就是"外部分发层"——它把 $share 的职责在 Redis 上重做了一遍 |
| **C) Rule→HTTP** | 语音链路没走这条路 | 只有 zebbingo-api 走 HTTP ingress。语音走原生 MQTT 是对的，延迟更低 |
| **D) 静态路由** | 没做 | 也不需要——你们的架构本身就是动态竞争消费 |

---

## 4. 真正需要注意的点

| # | 问题 | 影响 |
|:-:|:-----|:-----|
| 1 | **Docker 镜像只包含 bot_runner** | 线上部署 bot_mqtt 需要单独拉起来（或加个 docker-compose 定义第二个 service） |
| 2 | **main 分支没有 intent/ 包** | 语音指令拦截（CommandIntentRouter）从未合入 main，线上 = 0 部署 |
| 3 | **connectBotMqtt.mdx 那条路的 $share 依赖** | 如果 AWS IoT Core 端配了 `MQTT_USE_SHARED_SUBSCRIPTION=false`，则 SessionAffinityManager 的 Redis 锁是唯一的归属保障——它本身够用，但需要确认线上参数 |

---

## 5. 对Resonova改进的建议（已做 + 待做）

### ✅ 已修
| 修复 | 说明 |
|:-----|:------|
| Intro 超时 15s→90s | 不会因 intro 太长导致音频在 guard 期间被丢弃 |
| 新增 intro_complete 事件 | 前端可以据此显示"intro 已结束，可以说话" |
| 新增 intro_timeout 警告 | 如果 intro 超时，前端会收到通知 |

### 🔲 待做（看你是否要）
| 改进 | 价值 |
|:-----|:------|
| 前端显示 intro 播放状态（进度条/指示灯） | 用户能直观看到"intro 还在播，别说话" |
| 前端用一个按钮分开"开始对话" 和"发送测试音频" | 让用户先等 intro 播完再主动触发发音频 |
