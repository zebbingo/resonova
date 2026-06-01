# Resonova - 快速启动指南

## 🏗️ 架构

```
resonova/
├── backend/          # FastAPI 后端 (Python 3.13+)
│   ├── server.py         # API + WebSocket
│   ├── mqtt_bridge.py    # MQTT 设备模拟
│   └── start.py          # 启动脚本
└── frontend/         # Vue3 前端
    ├── src/
    └── package.json
```

## 🚀 启动步骤

### 1. 启动后端

```bash
cd backend
uv sync              # 安装依赖（首次运行）
uv run python start.py
```

后端运行在：**http://localhost:8765**

### 2. 启动前端

```bash
cd frontend
pnpm install         # 安装依赖（首次运行）
pnpm run dev
```

前端运行在：**http://localhost:5173**

### 3. 访问应用

打开浏览器访问：http://localhost:5173

## ✨ 功能演示

1. **添加设备** - 点击"➕ 添加设备"（最多4个）
2. **选择角色** - 从下拉框选择 figurine
3. **选择模式** - 💬对话 / 📖故事 / 🎵音乐
4. **启动模拟** - 点击"🟢 启动 MQTT 模拟"
5. **查看结果** - 实时日志 + 性能指标

## 🔧 常见问题

### 后端启动失败

**错误**: `ModuleNotFoundError: No module named 'xxx'`

**解决**: 
```bash
cd backend
uv sync --reinstall
```

### chatbot 依赖缺失

后端通过**软连接**引用 chatbot/src，确保 chatbot 项目已安装依赖：
```bash
cd ../chatbot
uv sync
```

**软连接优势**：
- ✅ 直接修改 chatbot 代码，backend 立即生效
- ✅ 无需复制文件，节省空间
- ✅ 保持代码同步，避免版本不一致

## 📁 项目结构

```
backend/
├── server.py           # FastAPI 主服务
│   ├── GET /api/figurines      # 角色列表
│   ├── GET /api/media/stories  # 故事列表
│   ├── GET /api/media/music    # 音乐列表
│   ├── POST /api/device/simulate  # 启动 MQTT 模拟
│   └── WS /ws/session/{id}     # WebSocket 实时推送
├── mqtt_bridge.py      # MQTT Bridge 实现
└── pyproject.toml      # Python 依赖

frontend/
├── src/
│   ├── components/
│   │   ├── DeviceManager.vue   # 多设备管理
│   │   ├── DeviceCard.vue      # 设备卡片
│   │   ├── SessionLog.vue      # 会话日志
│   │   └── MetricsPanel.vue    # 性能指标
│   ├── composables/
│   │   └── useMQTTSimulation.ts # MQTT 模拟逻辑
│   └── api.ts          # API 调用封装
└── package.json        # Node.js 依赖
```

## 📖 详细文档

- [多设备 MQTT 模拟方案](../MULTI_DEVICE_MQTT_SIMULATION_FINAL.md)
- [前端完善总结](../FRONTEND_COMPLETE_SUMMARY.md)
