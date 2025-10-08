# COCS 技术架构规格说明文档

## 1. 技术栈概览

### 1.1 核心技术
- **编程语言**：Python 3.8+
- **浏览器自动化**：Playwright
- **异步框架**：asyncio
- **Web框架**：FastAPI
- **AI服务**：Dify / Qwen
- **日志框架**：Loguru

### 1.2 依赖库
```
playwright==1.40.0          # 浏览器自动化
fastapi==0.104.1           # Web框架
uvicorn==0.24.0            # ASGI服务器
pydantic==2.5.0            # 数据验证
loguru==0.7.2              # 日志记录
python-dotenv==1.0.0       # 环境变量管理
httpx==0.25.0              # HTTP客户端
```

---

## 2. 整体架构设计

### 2.1 架构图

```
┌────────────────────────────────────────────────────────────────┐
│                        COCS 系统架构                            │
├────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────────┐      ┌──────────────┐      ┌─────────────┐  │
│  │   Browser    │      │   Message    │      │  AI Service │  │
│  │   Module     │◄────►│   Service    │◄────►│             │  │
│  │              │      │              │      │ - Dify      │  │
│  │ ┌──────────┐ │      │ ┌──────────┐ │      │ - Qwen      │  │
│  │ │Playwright│ │      │ │ FastAPI  │ │      │             │  │
│  │ └──────────┘ │      │ └──────────┘ │      └─────────────┘  │
│  │ ┌──────────┐ │      │ ┌──────────┐ │              ▲         │
│  │ │DOM Parser│ │      │ │ Message  │ │              │         │
│  │ └──────────┘ │      │ │ Handler  │ │              │         │
│  │ ┌──────────┐ │      │ └──────────┘ │              │         │
│  │ │  Page    │ │      └──────────────┘              │         │
│  │ │ Manager  │ │              │                      │         │
│  │ └──────────┘ │              ▼                      │         │
│  └──────────────┘      ┌──────────────┐              │         │
│         ▲              │ Notification │              │         │
│         │              │   Service    │              │         │
│         │              │              │              │         │
│         │              │ ┌──────────┐ │              │         │
│         │              │ │  WeChat  │ │              │         │
│         │              │ └──────────┘ │              │         │
│         │              │ ┌──────────┐ │              │         │
│         │              │ │  Email   │ │              │         │
│         │              │ └──────────┘ │              │         │
│         │              └──────────────┘              │         │
│         │                      │                      │         │
│         ▼                      ▼                      ▼         │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │              Data Persistence Layer                       │  │
│  │  ┌────────────────┐         ┌────────────────────────┐  │  │
│  │  │ last_messages  │         │   contact_states       │  │  │
│  │  │     .json      │         │       .json            │  │  │
│  │  └────────────────┘         └────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────────┘  │
│                                                                 │
└────────────────────────────────────────────────────────────────┘
```

### 2.2 模块职责

| 模块 | 职责 | 主要类 | 文件路径 |
|------|------|--------|----------|
| **浏览器模块** | 浏览器自动化、DOM操作 | `GoofishBrowser`, `GoofishDOMParser`, `PageManager`, `MessageMonitor` | `browser/` |
| **消息服务** | 消息接收、处理、路由 | `MessageService`, `Message`, `ChatSession` | `service/message_service.py` |
| **AI服务** | AI回复生成、置信度评估 | `DifyAIService`, `QwenAIService` | `service/ai_service.py` |
| **通知服务** | 人工介入通知 | `NotificationManager`, `WechatNotificationService`, `EmailNotificationService` | `service/notification_service.py` |
| **数据持久化** | 消息去重、状态保存 | `DataPersistence` | `browser/data_persistence.py` |
| **配置管理** | 环境变量、配置加载 | `Settings` | `config/settings.py` |

---

## 3. 核心模块设计

### 3.1 浏览器模块 (Browser Module)

#### 3.1.1 PageManager
**职责**：管理Playwright页面生命周期

```python
# browser/page_manager.py
class PageManager:
    def __init__(self, page):
        self.page = page
        self.dom_parser = None
        self.is_active = True

    async def ensure_active_page(self):
        """确保页面处于活跃状态"""
        if self.page.is_closed():
            logger.warning("页面已关闭，尝试重新获取")
            # 重新初始化逻辑
```

**关键方法**：
- `ensure_active_page()`: 检查并恢复页面状态
- `initialize_dom_parser()`: 初始化DOM解析器

#### 3.1.2 GoofishDOMParser
**职责**：DOM元素识别和消息提取

```python
# browser/dom_parser.py
class GoofishDOMParser:
    async def get_contacts_with_new_messages(self) -> List[Dict]:
        """获取有新消息标记的联系人"""
        # 查找带有新消息标记的联系人元素

    async def select_contact(self, contact_name: str) -> bool:
        """选择联系人进入聊天"""
        # 点击联系人进入聊天界面

    async def get_chat_messages(self, contact_name: str = None) -> List[Dict]:
        """提取聊天消息"""
        # 使用JavaScript提取消息
        # 重要：timestamp使用 new Date().toISOString()
```

**JavaScript消息提取**：
```javascript
// 在页面中执行的JavaScript代码
const messages = [];
document.querySelectorAll('.message-item').forEach(item => {
    messages.push({
        text: item.textContent,
        timestamp: new Date().toISOString(),  // ⚠️ 动态生成
        sender: isReceived ? contactName : 'self',
        is_received: isReceived
    });
});
return messages;
```

#### 3.1.3 MessageMonitor
**职责**：消息监控和去重

```python
# browser/message_monitor.py
class MessageMonitor:
    def __init__(self, page_manager, data_persistence: DataPersistence):
        self.page_manager = page_manager
        self.data_persistence = data_persistence
        self.is_running = False

    async def monitor_new_messages(self, callback: Callable):
        """监控新消息 - 串行处理"""
        while self.is_running:
            new_message = await self._wait_for_next_new_message()
            if new_message:
                await self._process_single_message(new_message)

    async def _wait_for_next_new_message(self):
        """等待下一条新消息"""
        # 1. 获取有新消息标记的联系人
        contacts_with_indicators = await self.check_for_new_message_indicators()

        # 2. 遍历联系人查找真正的新消息
        for contact in contacts_with_indicators:
            # 3. 进入联系人聊天
            await self.select_contact(contact['name'])

            # 4. 获取消息列表
            current_messages = await self.get_chat_messages(contact['name'])

            # 5. 使用DataPersistence查找新消息（去重）
            new_message = self.data_persistence.find_new_message_for_contact(
                contact['name'], current_messages
            )

            if new_message:
                # 6. 更新持久化记录
                self.data_persistence.update_last_processed_message(
                    contact['name'], new_message
                )
                return new_message
```

**设计要点**：
- 串行处理：一次只处理一条消息
- 持久化集成：依赖`DataPersistence`进行去重
- 错误恢复：页面异常时自动重连

### 3.2 数据持久化模块 (Data Persistence)

#### 3.2.1 DataPersistence类设计

```python
# browser/data_persistence.py
class DataPersistence:
    def __init__(self, data_dir: str = "./goofish_data"):
        self.data_dir = Path(data_dir)
        self.last_messages_file = self.data_dir / "last_messages.json"
        self.contact_states_file = self.data_dir / "contact_states.json"

        # 加载持久化数据
        self.last_processed_messages = self._load_last_messages()
        self.contact_states = self._load_contact_states()
```

#### 3.2.2 消息哈希生成算法

**核心实现**：
```python
def generate_message_hash(self, message: Dict) -> str:
    """
    生成消息的唯一哈希标识

    设计原则：
    1. 只使用稳定的字段（消息内容 + 发送者）
    2. 排除动态字段（timestamp）
    3. 使用MD5算法生成哈希
    """
    # ✅ 正确实现（已修复）
    content = f"{message.get('text', '')}{message.get('sender', '')}"
    return hashlib.md5(content.encode('utf-8')).hexdigest()

    # ❌ 错误实现（修复前）
    # content = f"{text}{timestamp}{sender}"  # timestamp不稳定
    # return hashlib.md5(content.encode('utf-8')).hexdigest()
```

**为什么排除timestamp**：
1. `dom_parser.py`中使用`new Date().toISOString()`动态生成时间戳
2. 同一条消息每次提取时timestamp都不同
3. 如果包含timestamp，哈希值每次都变化
4. 导致无法识别已处理消息，陷入无限循环

**哈希稳定性验证**：
```python
# 示例：同一条消息的哈希
message1 = {"text": "你好", "sender": "客户A", "timestamp": "2024-01-01T10:00:00Z"}
message2 = {"text": "你好", "sender": "客户A", "timestamp": "2024-01-01T10:00:05Z"}

# 使用新算法（只含text+sender）
hash1 = generate_message_hash(message1)  # abc123...
hash2 = generate_message_hash(message2)  # abc123...  ✅ 相同

# 使用旧算法（包含timestamp）
# hash1 = md5("你好2024-01-01T10:00:00Z客户A")  # abc123...
# hash2 = md5("你好2024-01-01T10:00:05Z客户A")  # def456...  ❌ 不同
```

#### 3.2.3 新消息查找算法（已优化 - 2024-10-08）

```python
def find_new_message_for_contact(self, contact_name: str, messages: list) -> Dict:
    """
    为特定联系人找到新消息

    简化逻辑（优化后）：
    1. 只处理有新消息标记的联系人
    2. 直接获取该联系人最新的接收消息
    3. 对比哈希值，如果不同则为新消息
    """
    if not messages:
        return None

    # 1. 获取最新的接收消息（从后往前找第一条接收消息）
    latest_received_message = None
    for message in reversed(messages):
        if message.get('type') == 'received':
            latest_received_message = message
            break

    if not latest_received_message:
        return None

    # 2. 获取该联系人上次处理的消息哈希
    last_message_hash = self.last_processed_messages.get(contact_name, "")

    # 3. 计算当前最新消息的哈希
    current_message_hash = self.generate_message_hash(latest_received_message)

    # 4. 对比哈希值
    if current_message_hash == last_message_hash:
        # 哈希相同，说明已经处理过
        logger.debug(f"联系人 {contact_name} 的最新消息已处理过，跳过")
        return None

    # 哈希不同，这是新消息
    logger.debug(f"找到联系人 {contact_name} 的新消息: {latest_received_message.get('text', '')[:30]}")
    return latest_received_message
```

**算法优化**：
- **时间复杂度**：O(1) （优化前：O(n)）
  - 只查找最新消息，不遍历全部
- **空间复杂度**：O(1)
- **核心改进**：
  - ✅ 直接获取最新接收消息
  - ✅ 简单的哈希对比
  - ✅ 避免遍历中间历史消息

**优化效果对比**：

| 指标 | 优化前 | 优化后 | 提升 |
|------|--------|--------|------|
| 时间复杂度 | O(n) | O(1) | 显著提升 |
| 逻辑清晰度 | 中等 | 高 | 更易维护 |
| 边界情况 | 可能处理中间消息 | 只处理最新消息 | 行为更明确 |
| 代码行数 | ~35行 | ~35行 | 逻辑简化 |

#### 3.2.4 持久化存储格式

**last_messages.json**：
```json
{
  "十一麻麻\n交易成功\n快给ta一个评价吧～\n09-30": "2dee425c0edd2d610dd759b7f048f731",
  "王中中\n订单已签收": "766fc05e1ce3db5a14270e218115dcd7",
  "客户A": "abc123def456789..."
}
```

**字段说明**：
- **Key**: 联系人名称（可能包含换行符）
- **Value**: 最后处理消息的MD5哈希值

**存储操作**：
```python
def update_last_processed_message(self, contact_name: str, message: Dict):
    """更新联系人最后处理的消息"""
    message_hash = self.generate_message_hash(message)
    self.last_processed_messages[contact_name] = message_hash

    # 立即保存到磁盘
    self._save_last_messages()

def _save_last_messages(self):
    """保存到JSON文件"""
    with open(self.last_messages_file, 'w', encoding='utf-8') as f:
        json.dump(self.last_processed_messages, f, ensure_ascii=False, indent=2)
```

### 3.3 消息服务模块 (Message Service)

#### 3.3.1 MessageService设计

```python
# service/message_service.py
class MessageService:
    def __init__(self):
        self.app = FastAPI()
        self.messages: Dict[str, Message] = {}
        self.chat_sessions: Dict[str, ChatSession] = {}
        self.ai_service = None
        self.browser_service = None
        self.ai_processing_lock = asyncio.Lock()  # 串行处理锁

    async def process_incoming_message(self, message_data: dict):
        """处理传入消息"""
        # 1. 创建消息对象
        message = Message(
            id=str(uuid.uuid4()),
            text=message_data.get('text'),
            sender=message_data.get('sender'),
            timestamp=message_data.get('timestamp'),
            chat_id=f"chat_{sender}_{date}"
        )

        # 2. 保存消息
        self.messages[message.id] = message

        # 3. 更新会话
        await self._update_chat_session(message.chat_id, message.sender)

        # 4. 自动触发AI处理（异步非阻塞）
        # 使用asyncio.create_task确保不会阻塞消息接收
        asyncio.create_task(self._handle_message_async(message))

        return message

    async def _handle_message_async(self, message: Message):
        """异步处理消息 - 确保串行"""
        async with self.ai_processing_lock:  # 🔒 锁保证串行
            await self._process_with_ai(message)

    async def _process_with_ai(self, message: Message):
        """AI处理流程"""
        # 1. 获取聊天历史
        chat_history = await self._get_chat_history(message.chat_id, limit=10)

        # 2. 调用AI服务
        ai_result = await self.ai_service.process_message(
            message.text,
            chat_history=chat_history,
            sender=message.sender
        )

        # 3. 保存AI响应
        message.ai_response = ai_result.get('response')
        message.confidence_score = ai_result.get('confidence_score', 0.0)
        message.require_human = ai_result.get('require_human', False)
        message.processed = True

        # 4. 置信度判断
        if message.confidence_score >= 0.7 and not message.require_human:
            # 自动发送
            await self.browser_service.send_message(message.ai_response)
        else:
            # 通知人工
            await self.notification_service.notify_human_required(message)
```

**设计要点**：
- 使用`asyncio.Lock`确保AI处理串行化
- 消息存储在内存中（可扩展为数据库）
- 支持HTTP API访问

#### 3.3.2 FastAPI路由设计

```python
@app.post("/messages")
async def receive_message(message_data: dict):
    """接收新消息"""
    message = await message_service.process_incoming_message(message_data)
    # process_incoming_message已自动触发AI处理，无需再次调用_handle_message_async
    return {"status": "success", "message_id": message.id}

@app.get("/messages/{chat_id}")
async def get_chat_messages(chat_id: str, limit: int = 50):
    """获取聊天记录"""
    messages = [msg for msg in message_service.messages.values()
                if msg.chat_id == chat_id]
    messages.sort(key=lambda x: x.timestamp)
    return messages[-limit:]

@app.get("/chats")
async def get_chat_sessions():
    """获取所有聊天会话"""
    return list(message_service.chat_sessions.values())
```

### 3.4 AI服务模块 (AI Service)

#### 3.4.1 AI服务抽象接口

```python
# service/ai_service.py
class BaseAIService(ABC):
    @abstractmethod
    async def process_message(self, message: str, chat_history: List[Dict],
                              sender: str) -> Dict:
        """
        处理消息并返回AI响应

        返回格式：
        {
            "response": "AI生成的回复",
            "confidence_score": 0.85,
            "require_human": False
        }
        """
        pass
```

#### 3.4.2 Dify AI服务实现

```python
class DifyAIService(BaseAIService):
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url
        self.api_key = api_key
        self.client = httpx.AsyncClient()

    async def process_message(self, message: str, chat_history: List[Dict],
                              sender: str) -> Dict:
        # 1. 构建上下文
        context = self._build_context(chat_history, sender)

        # 2. 调用Dify API
        response = await self._call_dify_api(message, context)

        # 3. 解析响应
        return self._parse_dify_response(response)

    async def _call_dify_api(self, message: str, context: str):
        """调用Dify API"""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "query": message,
            "inputs": {"context": context},
            "response_mode": "blocking"
        }

        response = await self.client.post(
            f"{self.api_url}/chat-messages",
            json=payload,
            headers=headers
        )

        return response.json()
```

#### 3.4.3 Qwen AI服务实现

```python
class QwenAIService(BaseAIService):
    def __init__(self, api_key: str, model_name: str = "qwen-turbo"):
        self.api_key = api_key
        self.model_name = model_name
        self.client = httpx.AsyncClient()

    async def process_message(self, message: str, chat_history: List[Dict],
                              sender: str) -> Dict:
        # 1. 构建消息列表
        messages = self._build_messages(chat_history, message, sender)

        # 2. 调用Qwen API
        response = await self._call_qwen_api(messages)

        # 3. 解析响应
        return self._parse_qwen_response(response)

    def _build_messages(self, chat_history: List[Dict],
                        current_message: str, sender: str):
        """构建Qwen消息格式"""
        messages = [
            {"role": "system", "content": "你是一个专业的客服助手..."}
        ]

        # 添加历史消息
        for msg in chat_history:
            role = "user" if msg['type'] == 'received' else "assistant"
            messages.append({"role": role, "content": msg['text']})

        # 添加当前消息
        messages.append({"role": "user", "content": current_message})

        return messages
```

### 3.5 通知服务模块 (Notification Service)

#### 3.5.1 通知管理器

```python
# service/notification_service.py
class NotificationManager:
    def __init__(self):
        self.notification_services = []

    def add_service(self, service):
        """添加通知服务"""
        self.notification_services.append(service)

    async def notify_human_required(self, message: Message):
        """通知所有渠道"""
        tasks = []
        for service in self.notification_services:
            tasks.append(service.send_notification(message))

        await asyncio.gather(*tasks, return_exceptions=True)
```

#### 3.5.2 微信通知服务

```python
class WechatNotificationService:
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.client = httpx.AsyncClient()

    async def send_notification(self, message: Message):
        """发送微信通知"""
        content = f"""
        【需要人工介入】
        客户：{message.sender}
        消息：{message.text}
        AI建议：{message.ai_response}
        置信度：{message.confidence_score:.2f}
        """

        payload = {
            "msgtype": "text",
            "text": {"content": content}
        }

        await self.client.post(self.webhook_url, json=payload)
```

---

## 4. 数据流设计

### 4.1 消息处理数据流

```
┌─────────┐     ┌──────────┐     ┌──────────┐     ┌──────────┐
│ 咸鱼页面 │────►│ Browser  │────►│ Message  │────►│   AI     │
│         │     │ Module   │     │ Service  │     │ Service  │
└─────────┘     └──────────┘     └──────────┘     └──────────┘
                     │                  │                │
                     │ 消息去重          │ 消息路由        │ AI处理
                     ▼                  ▼                ▼
              ┌──────────┐        ┌──────────┐    ┌──────────┐
              │  Data    │        │  HTTP    │    │ Response │
              │Persistence│       │   API    │    │  ≥0.7?   │
              └──────────┘        └──────────┘    └──────────┘
                                                        │
                                        ┌───────────────┴────────────┐
                                        │                            │
                                       YES                          NO
                                        │                            │
                                        ▼                            ▼
                                  ┌──────────┐              ┌──────────┐
                                  │ Browser  │              │Notification│
                                  │send_msg()│              │ Service   │
                                  └──────────┘              └──────────┘
```

### 4.2 消息去重数据流（已优化 - 2024-10-08）

```
1. 提取消息
   咸鱼页面 ──JavaScript──> [{text, sender, timestamp}, ...]
                           (timestamp = new Date())

2. 遍历有新消息标记的联系人
   for contact in contacts_with_new_messages:
       ├─> 进入聊天界面
       ├─> 提取消息列表: messages = [msg1, msg2, msg3, ...]
       └─> 调用去重逻辑

3. 消息去重判断（优化后）
   DataPersistence.find_new_message_for_contact(contact_name, messages)
   │
   ├─> 获取最新接收消息
   │   latest_msg = get_latest_received_message(messages)
   │   # 从后往前找第一条接收消息
   │
   ├─> 获取已保存哈希
   │   last_hash = db.get(contact_name)
   │
   ├─> 计算当前消息哈希
   │   current_hash = generate_hash(latest_msg)  # hash(text + sender)
   │
   ├─> 对比哈希值
   │   if current_hash == last_hash:
   │       return None  # 已处理，跳过
   │   else:
   │       return latest_msg  # 新消息
   │
   └─> 返回新消息或None

4. 更新持久化
   if new_message:
       new_hash = generate_hash(new_message)
       db.save(contact_name, new_hash)
       disk.write("last_messages.json", db)
```

**优化要点**：
- ✅ 从O(n)遍历优化为O(1)直接获取
- ✅ 只处理有新消息标记的联系人
- ✅ 只关注最新消息，避免处理历史消息

---

## 5. 接口设计

### 5.1 内部接口

#### 5.1.1 浏览器模块接口

```python
# GoofishBrowser
class GoofishBrowser:
    async def start() -> None
    async def wait_for_login() -> None
    async def monitor_new_messages(callback: Callable) -> None
    async def send_message(text: str) -> bool
    async def get_chat_messages() -> List[Dict]
    async def close() -> None
```

#### 5.1.2 数据持久化接口

```python
# DataPersistence
class DataPersistence:
    def generate_message_hash(message: Dict) -> str
    def find_new_message_for_contact(contact_name: str, messages: List[Dict]) -> Dict
    def update_last_processed_message(contact_name: str, message: Dict) -> None
    def reset_message_history(contact_name: str = None) -> None
    def get_message_stats() -> Dict
```

#### 5.1.3 AI服务接口

```python
# BaseAIService
class BaseAIService:
    async def process_message(
        message: str,
        chat_history: List[Dict],
        sender: str
    ) -> Dict[str, Any]:
        """
        返回：
        {
            "response": str,
            "confidence_score": float,
            "require_human": bool
        }
        """
```

### 5.2 外部HTTP API

#### 5.2.1 消息接口

**POST /messages**
```json
// Request
{
    "text": "消息内容",
    "sender": "客户名称",
    "timestamp": "2024-01-01T10:00:00Z"
}

// Response
{
    "status": "success",
    "message_id": "uuid-xxx"
}
```

**GET /messages/{chat_id}?limit=50**
```json
// Response
[
    {
        "id": "uuid-1",
        "text": "消息内容",
        "sender": "客户A",
        "timestamp": "2024-01-01T10:00:00Z",
        "message_type": "received",
        "ai_response": "AI回复",
        "confidence_score": 0.85
    }
]
```

#### 5.2.2 会话接口

**GET /chats**
```json
// Response
[
    {
        "chat_id": "chat_客户A_20240101",
        "contact_name": "客户A",
        "last_message_time": "2024-01-01T10:00:00Z",
        "message_count": 15,
        "active": true
    }
]
```

---

## 6. 错误处理和恢复机制

### 6.1 浏览器错误处理

```python
# 页面关闭错误
async def ensure_active_page(self):
    if self.page.is_closed():
        logger.warning("页面已关闭，尝试重新获取")
        # 重新初始化DOM解析器
        if self.page and not self.page.is_closed():
            self.dom_parser = GoofishDOMParser(self.page)
        else:
            raise PageClosedError("无法恢复页面")

# 重试机制
for retry in range(3):
    try:
        result = await operation()
        break
    except Exception as e:
        if retry == 2:
            raise
        logger.warning(f"操作失败，重试 {retry + 1}/3")
        await asyncio.sleep(2)
```

### 6.2 消息处理错误

```python
# 消息处理异常不影响后续消息
async def _process_single_message(self, message: Dict):
    try:
        await self.message_callback(message)
    except Exception as e:
        logger.error(f"处理消息失败: {e}")
        # 不重新抛出，继续处理下一条
```

### 6.3 AI服务降级

```python
async def _process_with_ai(self, message: Message):
    try:
        ai_result = await self.ai_service.process_message(...)
    except AIServiceError as e:
        logger.error(f"AI服务失败: {e}")
        # 降级：直接通知人工
        message.require_human = True
        message.processed = True
        await self.notification_service.notify_human_required(message)
```

### 6.4 持久化错误处理

```python
def _save_last_messages(self):
    try:
        with open(self.last_messages_file, 'w', encoding='utf-8') as f:
            json.dump(self.last_processed_messages, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存消息记录失败: {e}")
        # 备份到临时文件
        backup_file = self.last_messages_file.with_suffix('.json.bak')
        with open(backup_file, 'w', encoding='utf-8') as f:
            json.dump(self.last_processed_messages, f, ensure_ascii=False, indent=2)
```

---

## 7. 性能优化

### 7.1 异步并发
- **消息监控**：异步轮询，不阻塞主线程
- **AI调用**：异步HTTP请求
- **通知发送**：多渠道并发发送

### 7.2 缓存策略
- **DOM解析结果**：缓存联系人列表（5秒有效期）
- **聊天历史**：内存缓存最近消息
- **AI响应**：相似问题缓存（待实现）

### 7.3 资源管理
```python
# 限制消息提取数量
async def get_chat_messages(self, limit: int = 50):
    # 只提取最近50条消息

# 定期清理内存
if len(self.messages) > 10000:
    # 清理旧消息，只保留最近1000条
    self._cleanup_old_messages()
```

---

## 8. 部署架构

### 8.1 单机部署

```
┌─────────────────────────────┐
│         Server              │
│                             │
│  ┌───────────────────────┐  │
│  │  COCS Application     │  │
│  │  - Python Process     │  │
│  │  - Playwright Browser │  │
│  │  - FastAPI Server     │  │
│  └───────────────────────┘  │
│                             │
│  ┌───────────────────────┐  │
│  │  Data Storage         │  │
│  │  - last_messages.json │  │
│  │  - contact_states.json│  │
│  └───────────────────────┘  │
└─────────────────────────────┘
          │
          │ HTTPS
          ▼
┌─────────────────────────────┐
│  External Services          │
│  - Dify/Qwen AI API         │
│  - WeChat Webhook           │
│  - Email SMTP               │
└─────────────────────────────┘
```

### 8.2 容器化部署

```dockerfile
# Dockerfile
FROM python:3.9-slim

WORKDIR /app

# 安装依赖
COPY requirements.txt .
RUN pip install -r requirements.txt
RUN playwright install chromium

# 复制代码
COPY . .

# 启动应用
CMD ["python", "main.py"]
```

```yaml
# docker-compose.yml
version: '3.8'

services:
  cocs:
    build: .
    environment:
      - AI_SERVICE_TYPE=${AI_SERVICE_TYPE}
      - DIFY_API_KEY=${DIFY_API_KEY}
      - WECHAT_WEBHOOK_URL=${WECHAT_WEBHOOK_URL}
    volumes:
      - ./goofish_data:/app/goofish_data
      - ./logs:/app/logs
    ports:
      - "8000:8000"
    restart: unless-stopped
```

### 8.3 高可用部署（未来规划）

```
               ┌─────────────┐
               │  Load       │
               │  Balancer   │
               └─────────────┘
                      │
        ┌─────────────┼─────────────┐
        ▼             ▼             ▼
   ┌─────────┐   ┌─────────┐   ┌─────────┐
   │ COCS-1  │   │ COCS-2  │   │ COCS-3  │
   └─────────┘   └─────────┘   └─────────┘
        │             │             │
        └─────────────┼─────────────┘
                      ▼
              ┌─────────────┐
              │   Redis     │
              │(Shared State)│
              └─────────────┘
```

---

## 9. 监控和日志

### 9.1 日志级别

```python
# 配置日志
from loguru import logger

logger.add(
    "logs/goofish_ai.log",
    rotation="500 MB",      # 文件大小轮转
    retention="10 days",    # 保留10天
    level="INFO",
    format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}"
)
```

### 9.2 关键监控指标

- **消息处理速度**：消息/分钟
- **AI响应时间**：平均耗时
- **置信度分布**：高/低置信度占比
- **错误率**：处理失败比例
- **系统资源**：CPU、内存使用率

### 9.3 日志示例

```
2024-01-01 10:00:36.779 | INFO     | browser.message_monitor:_wait_for_next_new_message:145 - 🎉 发现 13 个有新消息标记的联系人
2024-01-01 10:00:36.933 | INFO     | browser.message_monitor:_wait_for_next_new_message:150 - 🔍 [1/13] 检查联系人: 十一麻麻
2024-01-01 10:00:38.497 | INFO     | browser.message_monitor:monitor_new_messages:48 - 📨 [40] 检测到新消息 (等待耗时: 1.9秒)
2024-01-01 10:00:38.498 | INFO     | service.message_service:process_incoming_message:135 - 收到新消息: 我去看一下 (来自: 十一麻麻)
```

---

## 10. 安全考虑

### 10.1 数据安全
- **敏感信息加密**：API密钥使用环境变量
- **通信加密**：HTTPS传输
- **本地数据保护**：消息文件权限控制

### 10.2 访问控制
```python
# API认证（待实现）
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer

security = HTTPBearer()

@app.post("/messages")
async def receive_message(
    message_data: dict,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    if credentials.credentials != VALID_TOKEN:
        raise HTTPException(status_code=401, detail="Unauthorized")
    # 处理消息...
```

### 10.3 限流保护
```python
# 使用slowapi限流（待实现）
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/messages")
@limiter.limit("100/minute")
async def receive_message(request: Request):
    # 处理消息...
```

---

## 11. 测试策略

### 11.1 单元测试
```python
# tests/test_data_persistence.py
def test_message_hash_generation():
    dp = DataPersistence()

    msg1 = {"text": "你好", "sender": "客户A", "timestamp": "2024-01-01T10:00:00Z"}
    msg2 = {"text": "你好", "sender": "客户A", "timestamp": "2024-01-01T10:00:05Z"}

    hash1 = dp.generate_message_hash(msg1)
    hash2 = dp.generate_message_hash(msg2)

    assert hash1 == hash2, "相同消息应该生成相同哈希"
```

### 11.2 集成测试
```python
# tests/test_message_flow.py
async def test_message_deduplication():
    """测试消息去重功能"""
    # 1. 发送消息
    message = {"text": "测试", "sender": "测试客户"}

    # 2. 第一次处理
    result1 = await monitor._wait_for_next_new_message()
    assert result1 is not None

    # 3. 第二次检查（应该被去重）
    result2 = await monitor._wait_for_next_new_message()
    assert result2 is None or result2['text'] != "测试"
```

---

## 12. 技术债务和改进计划

### 12.1 当前技术债务
- [ ] 消息存储使用内存，未持久化到数据库
- [ ] 缺少API认证和授权机制
- [ ] 日志未脱敏处理
- [ ] 缺少性能监控和告警

### 12.2 改进计划

**短期（1-3个月）**：
- [ ] 引入PostgreSQL/MongoDB存储消息
- [ ] 添加JWT认证
- [ ] 实现Prometheus监控
- [ ] 优化AI响应缓存

**中期（3-6个月）**：
- [ ] 微服务拆分
- [ ] Redis集群共享状态
- [ ] 分布式链路追踪
- [ ] 自动化测试覆盖率>80%

**长期（6-12个月）**：
- [ ] Kubernetes部署
- [ ] 多租户支持
- [ ] 实时数据分析
- [ ] 机器学习优化

---

## 附录

### A. 项目结构
```
cocs/
├── browser/                    # 浏览器模块
│   ├── goofish_browser.py     # 浏览器操作
│   ├── dom_parser.py          # DOM解析
│   ├── page_manager.py        # 页面管理
│   ├── message_monitor.py     # 消息监控
│   └── data_persistence.py    # 数据持久化
├── service/                    # 服务模块
│   ├── message_service.py     # 消息服务
│   ├── ai_service.py          # AI服务
│   └── notification_service.py # 通知服务
├── config/                     # 配置模块
│   └── settings.py            # 配置管理
├── utils/                      # 工具模块
│   └── logger.py              # 日志工具
├── goofish_data/              # 数据存储
│   ├── last_messages.json     # 消息记录
│   └── contact_states.json    # 联系人状态
├── logs/                       # 日志目录
├── main.py                     # 程序入口
├── requirements.txt            # 依赖列表
├── .env.example               # 配置模板
├── FUNCTIONAL_SPEC.md         # 功能规格
└── TECHNICAL_SPEC.md          # 技术规格（本文档）
```

### B. 关键文件说明

| 文件 | 行数 | 关键功能 |
|------|------|----------|
| `browser/data_persistence.py` | 147 | 消息去重核心逻辑 |
| `browser/message_monitor.py` | 309 | 消息监控主流程 |
| `browser/dom_parser.py` | 600+ | DOM解析和消息提取 |
| `service/message_service.py` | 264 | 消息处理和路由 |
| `service/ai_service.py` | 400+ | AI服务集成 |
| `main.py` | 250+ | 系统启动和协调 |

### C. 修复记录

**Issue #001: 消息重复处理问题**
- **发现时间**: 2024-10-08
- **问题描述**: 系统陷入无限循环，反复处理同一条消息
- **根本原因**: 消息哈希包含动态生成的timestamp，导致哈希值每次不同
- **修复方案**: 修改`generate_message_hash()`，只使用`text + sender`生成哈希
- **修复文件**: `browser/data_persistence.py:62-67`
- **影响范围**: 消息去重机制
- **验证方法**: 清空`last_messages.json`，重启系统验证不再重复处理

### D. 参考资料
- [Playwright文档](https://playwright.dev/python/)
- [FastAPI文档](https://fastapi.tiangolo.com/)
- [Dify API文档](https://docs.dify.ai/)
- [阿里云Qwen文档](https://help.aliyun.com/zh/dashscope/)
