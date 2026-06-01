# Resonova - 多设备管理功能说明

## 🎯 核心设计理念

将原有的**单设备测试模式**升级为**多设备并行管理模式**，每个设备可以独立配置角色和模式，支持同时测试多个场景。

---

## 📋 功能对比

### 改造前（旧版）

```
┌─────────────────────────┐
│  模拟设备开关 (checkbox) │
│  ├─ 角色选择 (全局)      │
│  └─ 模式选择 (全局)      │
├─────────────────────────┤
│  音频列表                │
│  └─ 选择一个音频         │
├─────────────────────────┤
│  测试按钮                │
└─────────────────────────┘
        ↓
   单次测试结果
```

**限制**：
- ❌ 只能测试一个设备
- ❌ 切换配置需要重新选择
- ❌ 无法对比不同设备的表现

### 改造后（新版）

```
┌──────────────────────────────────────┐
│  设备 1 [▼] 医生 (Doctor) · 💬 对话  │
│  ├─ 🎭 角色: [下拉选择]              │
│  ├─ 📱 模式: [💬对话] [📖故事] [🎵音乐] │
│  ├─ 🎵 测试音频列表                  │
│  │  ├─ 📦 模型测试 (3个)            │
│  │  ├─ 🧪 项目测试 (5个)            │
│  │  └─ ▶️ 播放器 + 开始测试按钮      │
│  └─ 📊 测试结果 (实时显示)           │
├──────────────────────────────────────┤
│  设备 2 [▶] 霸王龙 (T-Rex) · 📖 故事 │
│  (折叠状态)                           │
├──────────────────────────────────────┤
│  [+ 添加设备] (最多4个)               │
└──────────────────────────────────────┘
```

**优势**：
- ✅ 支持 1-4 个设备同时测试
- ✅ 每个设备独立配置
- ✅ 展开/折叠节省空间
- ✅ 实时显示各设备测试结果
- ✅ 方便对比不同配置的效果

---

## 🏗️ 技术实现

### 1. 组件结构

```
App.vue (主应用)
├── DeviceManager.vue (设备管理器) ⭐ 新增
│   ├── 设备卡片 x N (可展开/折叠)
│   │   ├── 设备头部 (名称、角色、模式)
│   │   ├── 配置面板 (展开时显示)
│   │   │   ├── 角色选择器
│   │   │   ├── 模式按钮组
│   │   │   ├── 音频列表 (分组显示)
│   │   │   └── 测试按钮
│   │   └── 测试结果 (实时显示)
│   └── 添加设备按钮
└── 右侧结果展示区
    └── 所有设备的测试结果汇总
```

### 2. 数据流

```typescript
// 设备数据结构
interface Device {
  id: string              // device-1, device-2, ...
  name: string            // "设备 1", "设备 2", ...
  figurine_id: string     // "doctor", "trex", ...
  mode: 'chat' | 'story' | 'music'
  expanded: boolean       // 是否展开
  selectedAudio: AudioItem | null
}

// 测试结果存储
const testResults = ref<Record<string, SttResult | VadSttResult>>({})
// key: deviceId, value: 测试结果
```

### 3. 关键交互

#### 展开/折叠设备
```vue
<div class="device-header" @click="toggleExpand(device.id)">
  <span class="device-icon">{{ device.expanded ? '▼' : '▶' }}</span>
  <!-- ... -->
</div>
```

#### 选择音频
```vue
<div
  v-for="audio in group.items"
  :key="audio.id"
  class="audio-item"
  :class="{ active: device.selectedAudio?.id === audio.id }"
  @click="device.selectedAudio = audio"
>
  <!-- ... -->
</div>
```

#### 执行测试
```typescript
async function handleDeviceTest(deviceId: string, audioId: string) {
  const result = await runSttTranscribe(audioId, 'auto')
  testResults.value[deviceId] = result  // 按设备 ID 存储结果
}
```

---

## 🎨 UI 设计要点

### 1. 视觉层次

```
一级：设备卡片 (深色背景)
  二级：设备头部 (浅色悬停效果)
    三级：配置面板 (更深的背景色)
      四级：音频项 (边框分隔)
```

### 2. 颜色语义

- **蓝色** (`var(--accent)`) - 激活状态、选中项
- **绿色** (`var(--green)`) - 成功、RTF 指标
- **灰色** (`var(--text2)`) - 次要信息、标签
- **红色** (`var(--red)`) - 删除按钮、错误

### 3. 交互反馈

- **悬停**: 边框高亮 (`border-color: var(--accent)`)
- **点击**: 背景变化 (`background: var(--surface2)`)
- **激活**: 蓝色背景 (`background: var(--accent2)`)
- **过渡**: `transition: all 0.15s`

---

## 📊 使用场景示例

### 场景 1: 对比不同角色的识别效果

```
设备 1: 医生 + 对话模式 → 测试医疗术语音频
设备 2: 老师 + 对话模式 → 测试教学用语音频
设备 3: 霸王龙 + 故事模式 → 测试儿童故事音频

→ 同时查看三个设备的 RTF 和准确率
```

### 场景 2: 测试不同模式下的行为

```
设备 1: 医生 + 对话模式 → 测试问答交互
设备 2: 医生 + 故事模式 → 测试故事讲述
设备 3: 医生 + 音乐模式 → 测试音乐控制

→ 验证 CommandIntentRouter 是否正确路由
```

### 场景 3: 批量回归测试

```
设备 1-4: 分别加载不同的测试音频集
→ 快速验证 STT 模型在多语言、多场景下的表现
```

---

## 🔧 扩展方向

### 短期优化

1. **从 MySQL 动态加载角色**
   ```python
   # 后端 API
   @app.get("/api/figurines")
   def list_figurines():
       # 查询 ZebFigurineInfo 表
   ```

2. **保存设备配置到 localStorage**
   ```typescript
   // 自动恢复上次的设备配置
   watch(devices, (newVal) => {
     localStorage.setItem('devices', JSON.stringify(newVal))
   }, { deep: true })
   ```

3. **批量测试功能**
   ```typescript
   // 一键测试所有设备
   async function testAllDevices() {
     for (const device of devices.value) {
       if (device.selectedAudio) {
         await handleDeviceTest(device.id, device.selectedAudio.id)
       }
     }
   }
   ```

### 长期规划

1. **WebSocket 实时流式识别**
2. **MQTT 消息模拟发送**
3. **测试结果导出 (CSV/JSON)**
4. **性能图表可视化**
5. **设备配置文件导入/导出**

---

## 📝 开发注意事项

### 1. 响应式更新

Vue 3 的 `ref` 对于对象数组的深度监听：
```typescript
// ✅ 正确：直接修改对象属性
device.figurine_id = 'trex'

// ❌ 错误：替换整个数组（会丢失响应性）
devices.value = [...newDevices]
```

### 2. 类型安全

TypeScript 联合类型的使用：
```typescript
type DeviceMode = 'chat' | 'story' | 'music'

// 编译时检查
device.mode = 'invalid'  // ❌ TypeScript 报错
```

### 3. 性能优化

- **v-for key**: 使用稳定的 `device.id` 而非索引
- **条件渲染**: `v-if` vs `v-show` 的选择
- **计算属性**: `groupedAudios` 缓存分组结果

---

## 🎉 总结

多设备管理功能将 Resonova从**单一测试工具**升级为**并行测试工作台**，大幅提升了测试效率和灵活性。

**核心价值**：
- 🚀 **效率提升**: 同时测试多个场景，减少重复操作
- 🔍 **对比分析**: 直观对比不同配置的效果
- 🎯 **场景覆盖**: 更全面地测试各种设备组合
- 📊 **数据丰富**: 收集更多维度的测试数据

**下一步**：根据实际使用反馈，继续优化交互体验和扩展功能。
