# Resonova

语音交互测试平台（STT 测试平台）。

## 项目结构

```
resonova/
├── backend/     Python FastAPI 后端 (uvicorn :8765)
├── frontend/    Vue 3 + Vite 前端 (pnpm dev :5173)
└── docs/        文档
```

**技术路线：**
- **前端：** Vue 3 + TypeScript + Vite（:5173）
- **后端：** Python FastAPI + uvicorn（:8765）
- **包管理：** uv（Python）/ pnpm（前端）
- **任务编排：** `just` — 全平台统一的命令管理工具（替代 Makefile）

> make 命令仍然兼容可用，但**新项目统一使用 `just`**。
> 安装 just：`winget install Casey.Just`（Windows） / `brew install just`（Mac） / `sudo apt install just`（Linux）

## 前置条件

- WSL Ubuntu 已安装并运行
- uv 已安装（`/usr/local/bin/uv`）
- just 已安装（推荐）

## 快速启动（WSL 内）

```bash
cd /home/administrator/projects/resonova/backend

# 首次：初始化环境
just init

# 启动开发服务器（热重载）
just start
```

后端运行在 **http://localhost:8765**

前端运行在（Windows 端）：
```bash
cd frontend
npm run dev
```

## 命令一览

```bash
just --list   # 查看所有可用命令
```

| 分类 | 命令（just） | 命令（make 兼容） | 说明 |
|---|---|---|---|
| **环境** | `just init` | `make init` | 一键初始化 |
| **服务器** | `just start` | `make start` | 开发模式启动（热重载） |
| | `just start-prod` | `make start-prod` | 生产模式启动 |
| **测试** | `just test` | `make test` | 运行测试 |
| | `just test-all` | `make test-all` | 运行全部测试 |
| **代码质量** | `just lint` | `make lint` | ruff 检查 |
| | `just format` | `make format` | 自动格式化 |
| | `just check` | `make check` | lint + format |
| **清理** | `just clean` | `make clean` | 清理缓存 |
| | `just clean-all` | `make clean-all` | 完全清理 |

## 任务编排工具说明

统一后端命令管理（启动、初始化、测试等），我们从 Makefile 切换到了 `just`。

| 方案 | 结论 |
|------|------|
| **Makefile** | ❌ **保留兼容** — Windows 不原生，语法啰嗦，但 WSL 内仍可用 |
| `[tool.uv] aliases` | ❌ **不存在** — uv 0.11.x 不支持 |
| `[tool.uv.scripts]` | ❌ **不存在** — 从未实现过 |
| **✅ just (justfile)** | ✅ **推荐** — 全平台原生，语法简洁 |

```bash
# 安装 just（一次性）
winget install Casey.Just       # Windows
brew install just               # Mac
sudo apt install just           # Ubuntu / WSL
```

## 常见问题

### 后端启动失败

```bash
just init           # 重新同步依赖
just clean-all && just init   # 完全重建
```

### just 未安装

```bash
sudo apt install just          # WSL / Ubuntu
winget install Casey.Just      # Windows
brew install just               # Mac
```

## 文档

详见 [docs/00-quickstart.md](docs/00-quickstart.md) 快速起步指南。
