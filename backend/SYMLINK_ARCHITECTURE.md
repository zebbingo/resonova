# STT 测试平台 - 软连接架构说明

## 🎯 设计目标

通过 **Windows 软连接（Symbolic Link）** 实现 backend 直接引用 chatbot/src，达到：
- ✅ 代码实时同步 - 修改 chatbot 立即生效
- ✅ 节省磁盘空间 - 无需复制文件
- ✅ 简化开发流程 - 无需手动同步代码

## 📁 目录结构

```
stt-test-tool/
├── backend/
│   ├── chatbot_src/          ← 软连接（symlink）
│   │   └── (指向 ../../chatbot/src)
│   ├── server.py
│   ├── mqtt_bridge.py
│   ├── start.py
│   └── pyproject.toml
├── frontend/
│   └── src/
└── QUICKSTART.md
```

## 🔗 软连接详情

### 创建命令

```powershell
cd d:\zebbingo\projects\stt-test-tool\backend
New-Item -ItemType SymbolicLink -Path chatbot_src -Target ..\..\chatbot\src
```

### 验证软连接

```powershell
# 查看软连接
ls chatbot_src

# 检查类型
Get-Item chatbot_src | Select-Object LinkType, Target
```

输出示例：
```
LinkType   Target
--------   ------
SymbolicLink D:\zebbingo\projects\chatbot\src
```

## 💻 代码使用

### server.py

```python
from pathlib import Path
import sys

# backend/server.py -> backend/chatbot_src (symlink)
_CHATBOT_SRC = Path(__file__).resolve().parent / "chatbot_src"
sys.path.insert(0, str(_CHATBOT_SRC))

# 现在可以直接导入 chatbot 模块
from libs.paths import models_dir
from processors.asr.asr_factory import load_offline_recognizer_from_cache
```

### start.py

```python
from pathlib import Path
import sys

# backend/start.py -> backend/chatbot_src (symlink)
_CHATBOT_SRC = Path(__file__).resolve().parent / "chatbot_src"
sys.path.insert(0, str(_CHATBOT_SRC))
```

## ✨ 优势对比

### ❌ 之前的方式（硬编码路径）

```python
# 需要计算相对路径
_CHATBOT_SRC = Path(__file__).resolve().parent.parent / "chatbot" / "src"
```

**问题**：
- 路径计算复杂，容易出错
- 移动文件后需要修改路径
- 不同操作系统路径分隔符不同

### ✅ 现在的方式（软连接）

```python
# 直接使用当前目录下的软连接
_CHATBOT_SRC = Path(__file__).resolve().parent / "chatbot_src"
```

**优势**：
- 路径简单清晰
- 不受文件位置影响
- 跨平台兼容（Windows/Linux/macOS）
- IDE 可以正确识别和跳转

## 🔧 维护指南

### 如果软连接损坏

```powershell
# 删除旧连接
Remove-Item chatbot_src

# 重新创建
New-Item -ItemType SymbolicLink -Path chatbot_src -Target ..\..\chatbot\src
```

### 如果需要更新 chatbot 路径

只需修改软连接的 target：

```powershell
# 删除旧连接
Remove-Item chatbot_src

# 创建新连接（指向新路径）
New-Item -ItemType SymbolicLink -Path chatbot_src -Target ..\..\new-chatbot-path\src
```

**无需修改 Python 代码！**

## 🚀 启动流程

1. **确保 chatbot 依赖已安装**
   ```bash
   cd ../chatbot
   uv sync
   ```

2. **启动后端**
   ```bash
   cd backend
   uv run python start.py
   ```

3. **启动前端**
   ```bash
   cd ../frontend
   pnpm run dev
   ```

## 📝 注意事项

### Windows 权限

创建软连接可能需要管理员权限：
```powershell
# 以管理员身份运行 PowerShell
Start-Process powershell -Verb RunAs
```

或者启用开发者模式：
```
设置 > 更新和安全 > 开发者选项 > 启用"开发人员模式"
```

### Git 忽略

软连接不会被 Git 跟踪，需要在 `.gitignore` 中添加：
```gitignore
# backend/.gitignore
chatbot_src/
```

### IDE 配置

大多数现代 IDE（VS Code、PyCharm）会自动识别软连接，但可能需要：
- 重启 IDE
- 刷新项目文件列表
- 重新索引项目

## 🎉 总结

通过软连接架构：
- ✅ **开发效率提升** - 修改 chatbot 代码立即在 backend 生效
- ✅ **代码维护简化** - 无需手动同步或复制文件
- ✅ **架构清晰** - backend 和 chatbot 保持独立，又紧密集成
- ✅ **易于调试** - IDE 可以正确跳转到 chatbot 源码

这就是为什么我们采用类似母项目的**前后端分离 + 软连接引用**架构！
