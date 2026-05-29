# 开发环境架构 — 前后端分离与跨平台协作

> 文档编号: 20 | 版本: v1.1 | 日期: 2026-05-29

本文档描述 VoicePipe 测试平台（stt-test-tool）的开发环境架构，重点说明前后端如何跨 Windows 和 WSL 协作。

---

## 1. 总体架构

```
Windows 11 (D: drive)                    WSL2 Ubuntu (192.168.52.134)
──────────────────────────              ──────────────────────────────

┌─ stt-test-tool-frontend/ ─┐          ┌─ stt-test-tool/ (软链) ─────┐
│                           │          │                              │
│  Vite Dev Server (:5173)  │  proxy   │  uvicorn server.py (:8765)   │
│                           │────/api──▶  FastAPI 后端                │
│  pnpm dev                 │────/ws───▶  WebSocket 事件总线          │
│  HMR 热更新               │          │                              │
│                           │          │  /home/administrator/        │
│  vite.config.ts           │          │    projects/stt-test-tool    │
│    ├── /api → WSL:8765    │          │       → 软链到 D: drive      │
│    └── /ws  → WSL:8765    │          │                              │
│                           │          │  chatbot_src                 │
│  node_modules/            │          │    → 软链到 WSL chatbot/src  │
│  dist/ (仅 production)    │          │                              │
└───────────────────────────┘          └──────────────────────────────┘
```

### 核心设计原则

- **一份源码**：后端代码 `stt-test-tool/` 只在 D: drive 上一份，WSL 通过软链访问
- **前后端分离**：前端源码和后端源码解耦，前端只通过 HTTP/WS 与后端通信
- **跨平台代理**：前端 Vite 开发服务器在 Windows 上运行，通过 proxy 转发到 WSL 后端
- **无需构建**：开发阶段前端不 build dist，直接用 Vite HMR

---

## 2. 目录结构和软链

| 路径 | 说明 | 类型 |
|------|------|------|
| `D:\zebbingo\projects\stt-test-tool\` | 后端 Python 代码（唯一源码） | git repo (master) |
| `D:\zebbingo\projects\stt-test-tool-frontend\` | 前端 Vue 3 代码 | git repo (main) |
| `WSL /home/.../stt-test-tool\` | **软链** → `D:\...\stt-test-tool\` | 软链 |
| `WSL /home/.../stt-test-tool/backend/chatbot_src\` | **软链** → `WSL /home/.../chatbot/src\` | 软链 |
| `D:\zebbingo\projects\chatbot\` | **软链** → `WSL /home/.../chatbot\` | 软链 |

> 软链使得 AI 工具从 Windows 路径也能访问 WSL 中的代码，维护一份代码即可。

### 何为需要软链

| 项目 | 运行位置 | 需要 WSL 软链？ | 原因 |
|------|---------|----------------|------|
| chatbot 后端 | WSL | ✅ | Python 进程跑在 WSL，必须访问源码 |
| chatbot 前端 | WSL | ✅ | Next.js 跑在 WSL，必须访问源码 |
| stt-test-tool 后端 | WSL | ✅ | uvicorn 跑在 WSL，必须访问源码 |
| stt-test-tool 前端 | **Windows** | ❌ | Vite 跑在 Windows，源码在 Windows 即可 |

---

## 3. 启动方式

### 3.1 后端（WSL）

```bash
# start-local-dev.sh start stt
# 在 WSL 上启动 uvicorn server.py，监听 :8765
# 同时启动 portproxy: 127.0.0.1:8765 → 192.168.52.134:8765
```

### 3.2 前端开发服务器（Windows）

```bash
# 在 Windows 终端（D: drive）
cd D:\zebbingo\projects\stt-test-tool-frontend
pnpm dev
# 启动 Vite 开发服务器，监听 :5173
```

### 3.3 前端代理配置（vite.config.ts）

```typescript
server: {
  port: 5173,
  proxy: {
    '/api': {
      target: 'http://192.168.52.134:8765',   // 转发到 WSL 后端
      changeOrigin: true,
    },
    '/ws': {
      target: 'ws://192.168.52.134:8765',      // WebSocket 转发
      ws: true,
    },
  },
}
```

### 3.4 Production 模式

构建后由后端 dist 目录直接提供静态文件：

```python
# server.py
_FRONTEND_DIST = Path(__file__).resolve().parent.parent.parent / "stt-test-tool-frontend" / "dist"

if _FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=str(_FRONTEND_DIST / "assets")))
```

```bash
# 构建前端
cd D:\zebbingo\projects\stt-test-tool-frontend
pnpm build
# 输出到 dist/

# 然后直接访问 http://localhost:8765/
# 后端会直接返回 dist/index.html（SPA 兜底路由）
```

---

## 4. 数据流

### 4.1 开发模式

```
浏览器 (:5173)                            WSL (:8765)
    │                                        │
    ├── GET /api/figurines ──proxy──▶  FastAPI 查询 MySQL
    │               ◀── JSON ──────────┘
    │
    ├── POST /api/device/connect ──proxy──▶  MQTT 连接
    │                    ◀── 设备信息 ───────┘
    │
    ├── WS /ws/device/xxx ──proxy──▶  WebSocket 事件流
    │       ◀── 实时推送（角色选择/开场白/对话）──
    │
    └── HMR 热更新（源码变更时自动刷新）
```

### 4.2 Production 模式

```
浏览器 (:8765)
    │
    ├── GET / → server.py 返回 dist/index.html
    ├── GET /assets/* → dist/assets/ 静态文件
    ├── GET /api/* → FastAPI 业务路由
    ├── WS /ws/* → WebSocket
    └── 其他路由 → SPA 兜底路由返回 index.html
```

---

## 5. 跨平台注意事项

| 问题 | 方案 |
|------|------|
| WSL 访问 Windows 文件系统性能差 | 后端 .venv 在 D: drive 上（需迁移到 WSL 本地优化） |
| Windows 无法直接运行 Python 后端 | 全程通过 WSL 运行，Vite proxy 转发 |
| 端口转发 | `start-local-dev.sh` 设置 `portproxy` 使 Windows 通过 `127.0.0.1:8765` 访问 WSL |
| 文件编码 | Windows 用 UTF-8，WSL 原生 UTF-8，无兼容问题 |
| 包管理器 | 前端统一使用 **pnpm**（9.x），WSL 和 Windows 均可运行 |
| 路径分隔符 | Python 代码使用 `Path()` 跨平台兼容 |

---

## 6. 端口映射

| 服务 | WSL 端口 | Windows 端口 | 说明 |
|------|---------|-------------|------|
| stt-test-tool 后端 | :8765 | :8765 (portproxy) | FastAPI + uvicorn |
| stt-test-tool 前端 | — | :5173 | Vite 开发服务器 |
| chatbot 后端 | :7860 | :7860 (portproxy) | bot_runner |
| chatbot 前端 | :3000 | :3000 (portproxy) | Next.js |
| MQTT Broker | :1883 | — | NanoMQ（仅 WSL，2026-04-21 替代 Mosquitto） |

---

## 7. 前端清理记录

### 7.1 问题：WSL 上存在前端源码副本

早期前后端没有分离，前端源码在 WSL 上也有一份副本（/home/administrator/projects/stt-test-tool-frontend），且与 D: drive 上的 git repo 版本不一致。

### 7.2 解决

1. 对比两个副本的差异（6 个文件不同，D: drive 版本更新）
2. 备份 WSL 副本 → `stt-test-tool-frontend.bak.20260529_114653/`
3. 删除 WSL 副本（前端不在 WSL 上运行）
4. 统一包管理器为 pnpm（从备份恢复 `.npmrc` + `pnpm-lock.yaml`）
5. 修复 TypeScript 类型错误（`?.` 可选链保护）
6. 验证 `pnpm build` 通过

### 7.3 清理后状态

```
WSL /home/.../projects/             Windows D:\zebbingo\projects\
├── chatbot/          ← REAL       ├── stt-test-tool/          ← git (master)
├── stt-test-tool/    ← SYMLINK    ├── stt-test-tool-frontend/ ← git (main), pnpm
└── .bak.*/           ← 备份       ├── chatbot → SYMLINK to WSL

---

## 8. 后端清理记录

### 8.1 问题：代码冗余和 git 混乱

测试平台前后端分离过程中，后端代码产生了多处副本和 git 追踪垃圾：

| 问题 | 数量 |
|------|------|
| 设备身份 JSON 被 git 追踪 | 71 个自动生成文件 |
| 遗留脚本（chatbot 有副本） | 7 个 |
| 过时辅助文件 | 3 个 |
| frontend/backend/ 重复后端代码 | 7 个 .py + 229MB .venv |
| root 级别空 .venv | 1 个（0 字节） |

### 8.2 差异分析方式

每个待清理文件都做了内容级对比：

1. **对比 `stt-test-tool/backend/scripts/` vs `chatbot/scripts/`** — 确认 6 个脚本完全一致（chatbot 有副本）
2. **对比 `stt-test-tool/backend/` vs `stt-test-tool-frontend/backend/`** — 确认内容完全一致（diff 为 IDENTICAL）
3. **检查 `db/migrations/` 归属** — 确认是测试平台独有，非 chatbot 副本
4. **检查 71 个 JSON 内容** — 确认都是 5 行自动生成，无手工数据
5. **回溯 git 历史** — 确认哪些文件已被旧 commit 追踪

### 8.3 处理清单

| 操作 | 数量 | 备份位置 |
|------|------|---------|
| `git rm --cached` 设备 JSON | 71 | 磁盘保留，git 不再追踪 |
| `git rm` 遗留脚本 | 7 | `stt-test-tool.cleanup-bak.20260529/scripts/` |
| `git rm` 辅助文件 | 3 | `stt-test-tool.cleanup-bak.20260529/backend/` |
| 删除 frontend/backend/ 重复 .py | 7 | `stt-test-tool.cleanup-bak.20260529/frontend-backend.tar` |
| 删除 frontend/backend/.venv | 229MB | 已删除不备份（可从 dep 重建） |
| 删除 frontend/backend/ 剩余重复文件 | 15 项（md/json/缓存/egg-info） | `stt-test-tool.cleanup-bak.20260529/frontend-backend-2/` |
| 删除 root 空 .venv | 0 字节 | 无备份 |
| 追踪有用工具脚本 | 5 个新增 | 新增至 git |

### 8.4 保留清单（未动）

| 文件 | 原因 |
|------|------|
| `_check_mysql.py` | 测试平台独有 MySQL 诊断工具 |
| `verify_aws_iot.py` | 测试平台独有 AWS IoT 验证工具 |
| `db/migrations/` | 测试平台自己的数据库迁移（2 个 SQL） |
| `grant_*.sql`、`grant_remote.sh` | 数据库授权脚本 |
| `run_migration.py`、`run_figurine_audio_migration.py` | 迁移执行器 |
| `backend/.venv` | 正在使用（168MB） |

### 8.5 清理后状态

```
git tracked: 65 files (从 132 减少)
git dirty:  0 files
remote:     origin/master (已推送)
backup:     /home/administrator/projects/stt-test-tool.cleanup-bak.20260529/
```

### 8.6 项目历史提交记录

```
29fdab2  chore: track check_logs.sh utility
3750b4b  chore: track useful scripts, remove empty root .venv
7ad3c1c  cleanup: remove legacy scripts, device JSONs, duplicate backend
0231a0c  docs: add dev environment architecture (doc 20)
56e3f82  docs: add architecture docs + service management documentation
da682ce  fix: MQTT device simulation improvements
b72b85e  feat: env scanner + service management API
```
