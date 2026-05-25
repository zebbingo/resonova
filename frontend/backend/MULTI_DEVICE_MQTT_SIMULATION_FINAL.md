# STT 测试平台 - 多设备管理 + MQTT 模拟 最终方案

> **更新时间**: 2026-05-20  
> **状态**: ✅ 已完成，完美结合多设备管理和 MQTT 真实模拟

---

## 🎯 设计理念

### 核心思路

**两者结合，优势互补**：

```
DeviceManager（多设备管理器）
  ├─ DeviceCard #1（设备 1 - MQTT 模拟）
  │   ├─ SessionLog（会话日志）
  │   └─ MetricsPanel（性能指标）
  ├─ DeviceCard #2（设备 2 - MQTT 模拟）
  ├─ DeviceCard #3（设备 3 - MQTT 模拟）
  └─ DeviceCard #4（设备 4 - MQTT 模拟）
```

- **DeviceManager** - 负责设备的添加/删除、数量限制（最多4个）、展开/折叠
- **DeviceCard** - 负责单个设备的完整 MQTT 模拟功能
- **收缩时显示基本信息** - 角色、模式、在线状态

---

## 📁 文件结构

### 组件层级

```
App.vue
  └─ DeviceManager.vue          ← 多设备管理器（展开/折叠）
       ├─ DeviceCard.vue × N    ← N 个设备卡片（1-4个）
            ├─ SessionLog.vue   ← 会话日志
            └─ MetricsPanel.vue ← 性能指标
```

### 文件清单

| 文件 | 行数 | 职责 |
|------|------|------|
| `App.vue` | ~180 | 主应用，加载音频列表，展示使用说明 |
| `DeviceManager.vue` | ~240 | 多设备管理（添加/删除、展开/折叠、状态同步） |
| `DeviceCard.vue` | ~610 | 单个设备的 MQTT 模拟（角色/模式/内容选择） |
| `SessionLog.vue` | ~222 | MQTT 消息流日志展示 |
| `MetricsPanel.vue` | ~132 | STT 性能指标展示 |
| `useMQTTSimulation.ts` | ~213 | MQTT 模拟逻辑 composable |

---

## 🔧 核心功能

### 1. 多设备管理（DeviceManager）

#### 设备操作
- ✅ **添加设备** - 点击"➕ 添加设备"按钮（最多 4 个）
- ✅ **删除设备** - 点击设备头部的 ❌ 按钮（至少保留 1 个）
- ✅ **展开/折叠** - 点击设备头部切换显示/隐藏

#### 收缩时显示
当设备折叠时，显示基本信息：
```
▶ 设备 1    🎭 医生    💬 对话    ⚪ 离线    ❌
```

包含：
- 🎭 **角色名称** - 如"医生"、"霸王龙"等
- 📱 **模式** - 💬 对话 / 📖 故事 / 🎵 音乐
- 🟢 **在线状态** - 在线/离线
- ❌ **删除按钮** - 移除该设备

#### 状态同步
DeviceCard 通过 `@update-status` 事件向父组件发送状态更新：
```typescript
// DeviceCard 内部
watch(figurineId, (newVal) => {
  emit('updateStatus', { figurineId: newVal })
})

watch(() => state.isOnline, (newVal) => {
  emit('updateStatus', { isOnline: newVal })
})

// DeviceManager 接收
@update-status="updateDeviceStatus(device.id, $event)"
```

---

### 2. MQTT 设备模拟（DeviceCard）

#### 配置选项
1. **🎭 角色选择** - 从下拉列表选择 figurine
   - Doctor Emma（医生）
   - Tara the T-Rex（霸王龙）
   - 哪吒
   - Princess Serena（公主）

2. **📱 模式选择** - 三种模式切换
   - 💬 对话 - 使用预录制音频测试 STT
   - 📖 故事 - 播放故事音频
   - 🎵 音乐 - 播放音乐音频

3. **🎵 内容选择** - 根据模式动态加载
   - 对话模式：本地测试音频（model/testdata）
   - 故事模式：从数据库加载故事列表
   - 音乐模式：从数据库加载音乐列表

4. **▶️ 音频预览** - 点击播放按钮预览音频

#### MQTT 模拟流程
```
用户点击"🟢 启动 MQTT 模拟"
  ↓
调用 POST /api/device/simulate
  ↓
后端创建 MQTT Bridge
  ↓
按 v1.1 协议上传音频帧
  ↓
Chatbot 后端处理（STT/VAD/LLM/TTS）
  ↓
WebSocket 推送实时反馈
  ↓
前端显示日志和指标
```

#### 实时反馈
- **SessionLog** - MQTT 消息流日志
  - 上行消息（蓝色）- session/start, audio/chunk, eos
  - 下行消息（绿色）- session/end, stt/result
  - 时间戳精确到毫秒
  - Payload 截断显示

- **MetricsPanel** - STT 性能指标
  - 会话 ID
  - 音频时长
  - 模型加载耗时
  - 识别耗时
  - RTF（实时因子）

---

## 🎨 UI 设计

### 收缩状态（折叠）
```
┌──────────────────────────────────────────────┐
│ ▶ 设备 1    🎭 医生    💬 对话    ⚪ 离线  ❌ │
└──────────────────────────────────────────────┘

┌──────────────────────────────────────────────┐
│ ▶ 设备 2    🎭 霸王龙  📖 故事    ⚪ 离线  ❌ │
└──────────────────────────────────────────────┘
```

**特点**：
- 简洁明了，一目了然
- 显示关键信息（角色、模式、状态）
- 可快速查看所有设备的配置
- 点击头部展开查看详情

### 展开状态
```
┌──────────────────────────────────────────────┐
│ ▼ 设备 1                              ❌     │
├──────────────────────────────────────────────┤
│ [角色选择下拉框]                              │
│ [💬 对话] [📖 故事] [🎵 音乐]                │
│                                               │
│ 内容列表：                                    │
│   📦 模型测试                                 │
│     - 音频 1  [▶️]                           │
│     - 音频 2  [▶️]                           │
│                                               │
│ [🟢 启动 MQTT 模拟]                          │
│                                               │
│ 📋 会话日志                                   │
│   12:30:45.123 ↑ SESSION_START               │
│   12:30:45.456 ↑ AUDIO_CHUNK                 │
│   ...                                         │
│                                               │
│ 📊 性能指标                                   │
│   音频时长: 5.23s                             │
│   模型加载: 234.5ms                           │
│   识别耗时: 456.7ms                           │
│   RTF: 0.087                                  │
└──────────────────────────────────────────────┘
```

**特点**：
- 完整的配置界面
- 实时日志滚动
- 性能指标展示
- 所有功能可用

---

## 🔄 数据流向

### 状态同步流程

```
用户在 DeviceCard 中选择角色
  ↓
figurineId.value 变化
  ↓
watch 触发
  ↓
emit('updateStatus', { figurineId: 'doctor' })
  ↓
DeviceManager 接收事件
  ↓
updateDeviceStatus(device.id, { figurineId: 'doctor' })
  ↓
device.figurineId 更新
  ↓
收缩时显示 "🎭 医生"
```

### MQTT 模拟流程

```
用户点击"启动 MQTT 模拟"
  ↓
handleStart() 调用
  ↓
startSimulation({ deviceId, figurineId, mode, audioId })
  ↓
POST /api/device/simulate
  ↓
后端返回 session_id
  ↓
连接 WebSocket: ws://.../ws/session/{id}
  ↓
后端推送 MQTT 消息
  ↓
addLog() 添加到 logs 数组
  ↓
SessionLog 组件实时更新
  ↓
STT 结果到达
  ↓
sttResult.value 更新
  ↓
MetricsPanel 显示指标
  ↓
state.isOnline = false
  ↓
emit('updateStatus', { isOnline: false })
  ↓
DeviceManager 更新状态为"⚪ 离线"
```

---

## 💡 典型使用场景

### 场景 1：单设备测试
1. 保持默认的设备 1
2. 选择角色"医生"
3. 选择模式"对话"
4. 选择音频"测试音频 1"
5. 点击"启动 MQTT 模拟"
6. 查看日志和指标

### 场景 2：多设备对比
1. 点击"➕ 添加设备"创建 4 个设备
2. 设备 1：医生 + 对话
3. 设备 2：霸王龙 + 对话
4. 设备 3：哪吒 + 故事
5. 设备 4：公主 + 音乐
6. 同时启动 4 个设备的模拟
7. 对比不同角色的 RTF 和识别精度

### 场景 3：问题复现
1. 固定配置：角色=医生，模式=对话，音频=特定ID
2. 多次运行模拟
3. 观察日志中的 MQTT 消息流
4. 记录性能指标
5. 精确复现线上问题

### 场景 4：快速切换
1. 展开设备 1，配置并启动
2. 折叠设备 1（显示"🎭 医生 🟢 在线"）
3. 展开设备 2，配置另一个角色
4. 快速在多个设备间切换查看

---

## 🛠️ 技术实现细节

### Vue 3 Composition API

```typescript
// 响应式状态
const devices = ref<Device[]>([...])
const figurineId = ref('doctor')
const mode = ref<'dialogue' | 'story' | 'music'>('dialogue')

// Composable
const { startSimulation, stopSimulation, state, logs } = useMQTTSimulation()

// Watch 监听
watch(figurineId, (newVal) => {
  emit('updateStatus', { figurineId: newVal })
})

// Computed
const groupedAudios = computed(() => {...})
```

### 父子组件通信

```typescript
// 子组件（DeviceCard）
const emit = defineEmits<{
  updateStatus: [status: { figurineId?: string; mode?: string; isOnline?: boolean }]
}>()

emit('updateStatus', { figurineId: 'doctor' })

// 父组件（DeviceManager）
<DeviceCard @update-status="updateDeviceStatus(device.id, $event)" />
```

### 条件渲染

```vue
<!-- 收缩时显示摘要 -->
<div v-if="!device.expanded" class="device-summary">
  <span>🎭 {{ getFigurineName(device.figurineId) }}</span>
  <span>{{ getModeName(device.mode) }}</span>
  <span :class="{ online: device.isOnline }">
    {{ device.isOnline ? '🟢 在线' : '⚪ 离线' }}
  </span>
</div>

<!-- 展开时显示完整内容 -->
<div v-show="device.expanded" class="device-content">
  <DeviceCard ... />
</div>
```

---

## ✅ 完成检查清单

- [x] DeviceManager 支持添加/删除设备（1-4个）
- [x] DeviceManager 支持展开/折叠
- [x] 收缩时显示角色、模式、在线状态
- [x] DeviceCard 集成 MQTT 模拟功能
- [x] DeviceCard 支持角色/模式/内容选择
- [x] DeviceCard 支持音频预览
- [x] SessionLog 实时显示 MQTT 消息流
- [x] MetricsPanel 显示 STT 性能指标
- [x] 父子组件状态同步（@update-status）
- [x] watch 监听状态变化并通知父组件
- [x] UI 样式美观，交互流畅

---

## 🚀 启动命令

```bash
cd d:\zebbingo\projects\stt-test-tool\frontend
pnpm install
pnpm run dev
```

访问：http://localhost:5173

---

## 📝 待完成的后端工作

需要实现以下 API 端点：

1. **POST /api/device/simulate** - MQTT Bridge 入口
2. **WebSocket /ws/session/{id}** - 实时反馈推送
3. **GET /api/figurines** - 角色列表
4. **GET /api/media/stories** - 故事列表
5. **GET /api/media/music** - 音乐列表

详见：`d:\zebbingo\docs\03-plan\STT测试平台-MQTT真实模拟实施方案.md`

---

## 🎉 总结

这个方案完美结合了：
- ✅ **多设备管理** - 添加/删除、展开/折叠、最多4个设备
- ✅ **MQTT 真实模拟** - 完整的 v1.1 协议、走真实生产链路
- ✅ **状态同步** - 收缩时显示关键信息，一目了然
- ✅ **实时反馈** - WebSocket 推送日志和指标
- ✅ **用户体验** - 简洁美观，交互流畅

**核心价值**：既能管理多个设备，又能进行真实的 MQTT 模拟测试，收缩时还能快速查看所有设备的状态！
