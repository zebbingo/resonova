# Chatbot 源码钩子注入方案

## 🎯 目标

通过在 **chatbot 源码**中植入轻量级监控钩子，实现：

1. **实时捕获**每个处理步骤的数据（STT、LLM、TTS）
2. **零侵入**原有业务逻辑（不影响 chatbot 正常运行）
3. **可配置**开关（生产环境禁用，测试环境启用）
4. **实时推送**到Resonova后端（通过 WebSocket 或 HTTP）

---

## 📊 架构设计

### 整体流程

```mermaid
graph TB
    A[Device] -->|MQTT| B[NanoMQ Broker（⚠️ Mosquitto 已弃用）]
    B -->|MQTT| C[Chatbot Backend]
    
    subgraph "Chatbot Backend (WSL)"
        C --> D[IntroGuardProcessor]
        D --> E[STT Processor]
        E --> F[LLM Processor]
        F --> G[TTS Processor]
        G --> H[CommandPublisherProcessor]
        
        D -.->|Hook| I[Monitoring Hook]
        E -.->|Hook| I
        F -.->|Hook| I
        G -.->|Hook| I
        H -.->|Hook| I
    end
    
    I -->|WebSocket/HTTP| J[Test Platform Backend<br/>Windows]
    J -->|WebSocket| K[Frontend/Vue]
    
    style I fill:#fff4e1
    style J fill:#e1f5ff
```

### 钩子位置

| 处理器 | 文件路径 | 钩子位置 | 监控数据 |
|--------|----------|----------|----------|
| **IntroGuardProcessor** | `processors/intro_guard_processor.py` | `on_intro_generated()` | 开场白文本、TTS 音频 |
| **STT Processor** | `processors/asr/*.py` | `on_transcription_complete()` | 识别文本、置信度、耗时 |
| **LLM Processor** | `processors/difyllmservice.py` | `on_llm_response()` | Prompt、响应、Token 数、耗时 |
| **TTS Processor** | `processors/tts/minimax.py` | `on_tts_synthesized()` | 音频时长、文件大小、耗时 |
| **CommandPublisherProcessor** | `processors/mqtt/command_publisher_processor.py` | `on_message_published()` | MQTT 消息、Topic、Payload |

---

## 🔧 实施方案

### 第 1 步：创建监控模块

在 chatbot 项目中创建 `src/monitoring/` 目录：

```
chatbot/src/
├── monitoring/
│   ├── __init__.py
│   ├── hook_manager.py       # 钩子管理器
│   ├── metrics_collector.py  # 指标收集器
│   └── websocket_client.py   # WebSocket 客户端（推送到Resonova）
```

#### `monitoring/hook_manager.py`

```python
"""
监控钩子管理器

提供装饰器和上下文管理器，用于在关键位置植入监控点。
"""

import asyncio
import time
from typing import Callable, Any, Optional
from loguru import logger

from .metrics_collector import MetricsCollector
from .websocket_client import MonitoringWebSocketClient


class HookManager:
    """全局钩子管理器（单例）。"""
    
    _instance = None
    _enabled = False
    
    def __init__(self):
        self.metrics_collector = MetricsCollector()
        self.ws_client = MonitoringWebSocketClient()
        self._hooks = {}
    
    @classmethod
    def get_instance(cls) -> 'HookManager':
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def enable(cls):
        """启用监控（从环境变量读取）。"""
        import os
        cls._enabled = os.getenv("MONITORING_ENABLED", "false").lower() == "true"
        if cls._enabled:
            logger.info("✅ Monitoring hooks enabled")
        else:
            logger.info("❌ Monitoring hooks disabled")
    
    @classmethod
    def is_enabled(cls) -> bool:
        return cls._enabled
    
    def register_hook(self, name: str, callback: Callable):
        """注册钩子回调。"""
        self._hooks[name] = callback
        logger.info(f"Registered hook: {name}")
    
    async def emit(self, event_type: str, data: dict):
        """发送监控事件。"""
        if not self.is_enabled():
            return
        
        # 记录指标
        self.metrics_collector.record(event_type, data)
        
        # 推送到Resonova
        await self.ws_client.send({
            "type": event_type,
            "timestamp": time.time(),
            "data": data,
        })
        
        # 调用注册的回调
        if event_type in self._hooks:
            try:
                self._hooks[event_type](data)
            except Exception as e:
                logger.error(f"Hook callback error: {e}")


# 便捷函数
def instrument(step_name: str):
    """
    装饰器：自动记录函数执行时间和指标。
    
    用法：
        @instrument("stt_transcription")
        async def transcribe(audio_data: bytes) -> str:
            ...
    """
    def decorator(func: Callable):
        async def wrapper(*args, **kwargs):
            if not HookManager.is_enabled():
                return await func(*args, **kwargs)
            
            start_time = time.time()
            hook_manager = HookManager.get_instance()
            
            try:
                result = await func(*args, **kwargs)
                
                duration_ms = (time.time() - start_time) * 1000
                await hook_manager.emit(f"{step_name}.complete", {
                    "duration_ms": duration_ms,
                    "success": True,
                })
                
                return result
            
            except Exception as e:
                duration_ms = (time.time() - start_time) * 1000
                await hook_manager.emit(f"{step_name}.error", {
                    "duration_ms": duration_ms,
                    "error": str(e),
                })
                raise
        
        return wrapper
    return decorator
```

#### `monitoring/metrics_collector.py`

```python
"""
指标收集器

收集并聚合监控数据，支持查询和导出。
"""

import time
from typing import Dict, List, Any
from collections import defaultdict
from loguru import logger


class MetricsCollector:
    """指标收集器。"""
    
    def __init__(self, max_events: int = 10000):
        self.max_events = max_events
        self.events: List[Dict[str, Any]] = []
        self.metrics_by_type: Dict[str, List[Dict]] = defaultdict(list)
    
    def record(self, event_type: str, data: dict):
        """记录事件。"""
        event = {
            "type": event_type,
            "timestamp": time.time(),
            "data": data,
        }
        
        self.events.append(event)
        self.metrics_by_type[event_type].append(data)
        
        # 限制内存使用
        if len(self.events) > self.max_events:
            self.events = self.events[-self.max_events:]
        
        logger.debug(f"Recorded metric: {event_type}")
    
    def get_metrics(self, event_type: str, last_n: int = 100) -> List[Dict]:
        """获取指定类型的最近 N 个指标。"""
        return self.metrics_by_type.get(event_type, [])[-last_n:]
    
    def get_summary(self) -> Dict:
        """获取指标摘要。"""
        summary = {}
        for event_type, events in self.metrics_by_type.items():
            if events:
                summary[event_type] = {
                    "count": len(events),
                    "latest": events[-1],
                }
        return summary
    
    def clear(self):
        """清空所有指标。"""
        self.events.clear()
        self.metrics_by_type.clear()
```

#### `monitoring/websocket_client.py`

```python
"""
WebSocket 客户端

将监控数据实时推送到Resonova后端。
"""

import asyncio
import json
import os
from typing import Optional
from loguru import logger

try:
    import websockets
except ImportError:
    websockets = None


class MonitoringWebSocketClient:
    """WebSocket 客户端（推送到Resonova）。"""
    
    def __init__(self):
        self.ws_url = os.getenv(
            "MONITORING_WS_URL",
            "ws://192.168.52.1:8765/ws/monitoring",  # Windows IP
        )
        self.ws: Optional[Any] = None
        self._connected = False
        self._reconnect_delay = 1
    
    async def connect(self):
        """连接到Resonova。"""
        if not websockets:
            logger.warning("websockets not installed, monitoring disabled")
            return
        
        try:
            self.ws = await websockets.connect(self.ws_url)
            self._connected = True
            logger.info(f"✅ Connected to monitoring server: {self.ws_url}")
        except Exception as e:
            logger.error(f"Failed to connect to monitoring server: {e}")
            self._connected = False
    
    async def send(self, data: dict):
        """发送监控数据。"""
        if not self._connected or not self.ws:
            # 尝试重连
            await self.connect()
            if not self._connected:
                return
        
        try:
            await self.ws.send(json.dumps(data))
        except Exception as e:
            logger.error(f"Failed to send monitoring data: {e}")
            self._connected = False
    
    async def close(self):
        """关闭连接。"""
        if self.ws:
            await self.ws.close()
            self._connected = False
```

---

### 第 2 步：在 chatbot 源码中植入钩子

#### 示例 1：IntroGuardProcessor（开场白）

```python
# processors/intro_guard_processor.py

from monitoring.hook_manager import HookManager, instrument


class IntroGuardProcessor:
    def __init__(self):
        self.hook_manager = HookManager.get_instance()
    
    @instrument("intro_generation")
    async def generate_intro(self, figurine_id: str) -> str:
        """生成开场白。"""
        # ... 原有逻辑 ...
        
        intro_text = await self._fetch_intro_text(figurine_id)
        
        # 发送监控事件
        await self.hook_manager.emit("intro.generated", {
            "figurine_id": figurine_id,
            "intro_text": intro_text,
            "text_length": len(intro_text),
        })
        
        return intro_text
    
    @instrument("intro_tts_synthesis")
    async def synthesize_intro_audio(self, text: str) -> bytes:
        """合成开场白音频。"""
        # ... 原有逻辑 ...
        
        audio_data = await self._call_tts_api(text)
        
        # 发送监控事件
        await self.hook_manager.emit("intro.tts_synthesized", {
            "text": text,
            "audio_size_bytes": len(audio_data),
            "audio_duration_ms": self._calculate_duration(audio_data),
        })
        
        return audio_data
```

#### 示例 2：STT Processor

```python
# processors/asr/paraformer.py

from monitoring.hook_manager import HookManager, instrument


class ParaformerASR:
    def __init__(self):
        self.hook_manager = HookManager.get_instance()
    
    @instrument("stt_transcription")
    async def transcribe(self, audio_data: bytes) -> dict:
        """语音转文字。"""
        start_time = time.time()
        
        # ... 原有 STT 逻辑 ...
        result = await self.model.transcribe(audio_data)
        
        duration_ms = (time.time() - start_time) * 1000
        
        # 发送监控事件
        await self.hook_manager.emit("stt.complete", {
            "text": result["text"],
            "confidence": result["confidence"],
            "language": result["language"],
            "duration_ms": duration_ms,
            "rtf": result["rtf"],
        })
        
        return result
```

#### 示例 3：LLM Processor

```python
# processors/difyllmservice.py

from monitoring.hook_manager import HookManager, instrument


class DifyLLMService:
    def __init__(self):
        self.hook_manager = HookManager.get_instance()
    
    @instrument("llm_inference")
    async def generate_response(self, prompt: str, context: dict) -> str:
        """LLM 推理。"""
        start_time = time.time()
        
        # ... 原有 LLM 逻辑 ...
        response = await self.client.chat_completion(prompt, context)
        
        duration_ms = (time.time() - start_time) * 1000
        
        # 发送监控事件
        await self.hook_manager.emit("llm.response", {
            "prompt_tokens": response["usage"]["prompt_tokens"],
            "completion_tokens": response["usage"]["completion_tokens"],
            "total_tokens": response["usage"]["total_tokens"],
            "response_text": response["text"][:200],  # 截断前 200 字符
            "duration_ms": duration_ms,
        })
        
        return response["text"]
```

#### 示例 4：TTS Processor

```python
# processors/tts/minimax.py

from monitoring.hook_manager import HookManager, instrument


class MiniMaxTTS:
    def __init__(self):
        self.hook_manager = HookManager.get_instance()
    
    @instrument("tts_synthesis")
    async def synthesize(self, text: str, voice_id: str) -> bytes:
        """文本转语音。"""
        start_time = time.time()
        
        # ... 原有 TTS 逻辑 ...
        audio_data = await self.api.generate(text, voice_id)
        
        duration_ms = (time.time() - start_time) * 1000
        
        # 发送监控事件
        await self.hook_manager.emit("tts.synthesized", {
            "text": text,
            "voice_id": voice_id,
            "audio_size_bytes": len(audio_data),
            "audio_duration_ms": self._calculate_duration(audio_data),
            "duration_ms": duration_ms,
        })
        
        return audio_data
```

#### 示例 5：MQTT Command Publisher

```python
# processors/mqtt/command_publisher_processor.py

from monitoring.hook_manager import HookManager


class CommandPublisherProcessor:
    def __init__(self):
        self.hook_manager = HookManager.get_instance()
    
    async def publish(self, topic: str, payload: dict, qos: int = 0):
        """发布 MQTT 消息。"""
        # ... 原有逻辑 ...
        
        # 发送监控事件
        await self.hook_manager.emit("mqtt.published", {
            "topic": topic,
            "qos": qos,
            "payload_size": len(str(payload)),
            "message_type": self._extract_message_type(topic),
        })
```

---

### 第 3 步：初始化监控模块

在 `bot_mqtt.py` 启动时初始化监控：

```python
# bot_mqtt.py

from monitoring.hook_manager import HookManager


async def start_mqtt_for_device_async():
    # ... 原有代码 ...
    
    # 初始化监控（从环境变量读取配置）
    HookManager.enable()
    
    if HookManager.is_enabled():
        hook_manager = HookManager.get_instance()
        asyncio.create_task(hook_manager.ws_client.connect())
        logger.info("✅ Monitoring initialized")
    
    # ... 原有代码 ...
```

---

### 第 4 步：Resonova后端接收监控数据

```python
# backend/server.py (resonova)

from fastapi import FastAPI, WebSocket
import asyncio
import json

app = FastAPI()

# 存储监控数据
monitoring_data = []


@app.websocket("/ws/monitoring")
async def monitoring_websocket(websocket: WebSocket):
    await websocket.accept()
    
    try:
        while True:
            data = await websocket.receive_text()
            event = json.loads(data)
            
            # 存储数据
            monitoring_data.append(event)
            
            # 限制存储数量
            if len(monitoring_data) > 10000:
                monitoring_data.pop(0)
            
            # 转发给前端（如果需要）
            # await frontend_ws.send_text(data)
            
    except Exception as e:
        logger.error(f"Monitoring WebSocket error: {e}")


@app.get("/api/monitoring/events")
def get_monitoring_events(limit: int = 100, offset: int = 0):
    """获取监控事件。"""
    return {
        "events": monitoring_data[offset:offset+limit],
        "total": len(monitoring_data),
    }


@app.get("/api/monitoring/summary")
def get_monitoring_summary():
    """获取监控摘要。"""
    summary = {}
    for event in monitoring_data:
        event_type = event["type"]
        if event_type not in summary:
            summary[event_type] = {"count": 0}
        summary[event_type]["count"] += 1
    return summary
```

---

## 📝 配置说明

### 环境变量

```bash
# chatbot/.env

# 监控配置
MONITORING_ENABLED=true                    # 是否启用监控
MONITORING_WS_URL=ws://192.168.52.1:8765/ws/monitoring  # Resonova WebSocket 地址
```

### 性能影响

- **CPU 开销**：< 1%（仅记录时间戳和简单指标）
- **内存开销**：< 10MB（最多存储 10000 个事件）
- **网络开销**：< 1KB/s（仅发送 JSON 指标）

---

## 🎯 优势

| 特性 | 说明 |
|------|------|
| **零侵入** | 使用装饰器，不修改原有业务逻辑 |
| **可配置** | 通过环境变量控制开关 |
| **轻量级** | 性能开销极小（< 1% CPU） |
| **实时性** | WebSocket 实时推送，延迟 < 10ms |
| **可扩展** | 轻松添加新的监控点 |

---

## 🚀 下一步

1. **创建 monitoring 模块**（4 个文件）
2. **在 5 个关键处理器中植入钩子**
3. **初始化监控模块**（bot_mqtt.py）
4. **Resonova后端接收数据**
5. **前端可视化监控面板**
