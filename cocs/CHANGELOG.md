# COCS 更新日志

## [未发布] - 2024-10-08

### 🐛 Bug修复
- **修复消息重复处理问题** (`browser/data_persistence.py`)
  - 问题：系统陷入无限循环，反复处理同一条消息
  - 根本原因：消息哈希包含动态生成的timestamp，导致每次哈希值都不同
  - 修复方案：修改`generate_message_hash()`方法，只使用消息内容和发送者生成哈希，排除不稳定的timestamp字段
  - 影响文件：`browser/data_persistence.py:62-67`
  - 相关Issue：日志显示在"十一麻麻"联系人上无限循环

### ⚡ 性能优化
- **简化消息去重逻辑** (`browser/data_persistence.py:69-116`)
  - 优化：简化`find_new_message_for_contact()`方法的处理逻辑
  - **旧逻辑**：遍历所有消息，逐条对比哈希，找到第一条新消息
  - **新逻辑**：直接获取最新接收消息，对比哈希值，判断是否为新消息
  - **优势**：
    - ✅ 逻辑更清晰直接
    - ✅ 性能更优（O(n) → O(1)，不需遍历所有消息）
    - ✅ 只处理有新消息标记的联系人
    - ✅ 避免处理中间历史消息

### 🔧 修复
- **修复Ctrl+C无法停止程序的问题** (`main.py:252-280`)
  - 问题：按Ctrl+C后程序无法正常退出
  - 根本原因：信号处理器中尝试创建异步任务，但signal handler运行在主线程中，与async事件循环不在同一上下文
  - 修复方案：
    - 在signal handler中直接调用`loop.stop()`停止事件循环
    - 移除异步清理任务的创建逻辑
    - 如果优雅退出失败，则调用`sys.exit(0)`强制退出
  - 影响文件：`main.py:252-280`

### 📚 文档更新
- **新增功能规格说明文档** (`FUNCTIONAL_SPEC.md`)
  - 项目概述和核心价值
  - 详细功能需求（消息监控、智能回复、置信度评估）
  - 用户场景和业务流程
  - **消息去重机制详细说明**（包含修复前后对比）
  - 数据模型和配置说明
  - 性能指标和安全考虑

- **新增技术架构规格说明文档** (`TECHNICAL_SPEC.md`)
  - 技术栈和整体架构设计
  - 核心模块详细设计（浏览器、消息服务、AI服务等）
  - **数据持久化模块深度解析**
  - **消息哈希生成算法说明**
  - **消息去重数据流图**
  - 接口设计（内部接口和HTTP API）
  - 错误处理和恢复机制
  - 部署架构和监控方案
  - 技术债务和改进计划

- **更新主README** (`README.md`)
  - 添加"文档"章节
  - 添加核心文档和技术文档的导航链接
  - 链接到功能规格、技术规格和消息去重机制说明

### 🔧 数据迁移
- **清空消息历史记录** (`goofish_data/last_messages.json`)
  - 清空旧的哈希值记录（因包含timestamp，与新算法不兼容）
  - 系统将使用新的哈希算法重新建立消息记录

### 📝 技术细节

#### 消息去重逻辑优化

**优化前的逻辑流程**:
```python
# 遍历所有消息，逐条对比
for message in reversed(messages):
    current_hash = generate_hash(message)

    # 找到上次处理的消息，停止
    if current_hash == last_hash:
        break

    # 找到新消息
    if message.type == "received":
        return message  # 可能返回中间的消息
```

**优化后的逻辑流程**:
```python
# 直接获取最新的接收消息
latest_message = get_latest_received_message(messages)

# 对比哈希值
current_hash = generate_hash(latest_message)

if current_hash == last_hash:
    return None  # 已处理，跳过

return latest_message  # 新消息，处理
```

**核心改进**:
1. **只处理最新消息**：不再遍历中间历史消息
2. **严格遵循新消息标记**：有标记才检查，无标记直接跳过
3. **算法复杂度优化**：从O(n)降为O(1)

#### 消息哈希生成算法变更

**修复前（错误实现）**:
```python
# ❌ 包含了动态变化的timestamp
content = f"{message.get('text', '')}{message.get('timestamp', '')}{message.get('sender', '')}"
return hashlib.md5(content.encode('utf-8')).hexdigest()
```

**修复后（正确实现）**:
```python
# ✅ 只使用稳定的字段
content = f"{message.get('text', '')}{message.get('sender', '')}"
return hashlib.md5(content.encode('utf-8')).hexdigest()
```

**修复原因**:
- `dom_parser.py`中使用`new Date().toISOString()`动态生成timestamp
- 同一条消息每次提取时timestamp都不同
- 导致哈希值每次都变化，无法识别已处理消息
- 系统误认为总是"新消息"，陷入无限循环

#### 数据流说明

```
提取消息（每次timestamp不同）
   ↓
生成哈希（旧算法 → 每次不同 ❌）
         （新算法 → 始终相同 ✅）
   ↓
对比数据库
   ↓
判断是否新消息
```

### 🎯 影响范围
- **核心功能**：消息去重机制
- **受影响文件**：
  - `browser/data_persistence.py` - 哈希生成逻辑
  - `goofish_data/last_messages.json` - 持久化数据
- **测试建议**：
  1. 清空持久化数据后重启系统
  2. 观察是否还会重复处理消息
  3. 验证不同联系人的消息正确去重

### 📊 文档结构

新增文档结构如下：
```
cocs/
├── README.md                  # 主文档（已更新）
├── FUNCTIONAL_SPEC.md         # 功能规格说明（新增）
├── TECHNICAL_SPEC.md          # 技术架构规格说明（新增）
├── CHANGELOG.md               # 更新日志（本文档，新增）
├── COCS_Function_Call_Flow.md # 函数调用流程
└── browser/
    └── README_serial_processing.md # 串行处理说明
```

### 🔗 相关文档链接
- [功能规格说明](./FUNCTIONAL_SPEC.md)
- [技术架构规格说明](./TECHNICAL_SPEC.md)
- [消息去重机制详解](./FUNCTIONAL_SPEC.md#44-消息去重详细机制)
- [消息哈希算法说明](./TECHNICAL_SPEC.md#422-消息哈希生成算法)

---

## 历史版本

### [0.1.0] - 2024-09 (初始版本)
- 基础浏览器自动化功能
- AI消息处理集成
- 通知服务实现
- 串行消息处理机制
