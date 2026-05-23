# XianyuAutoAgent 项目全面探索报告

**探索时间:** 2026年5月4日  
**项目路径:** /Users/jimmypan/git_repo/XianyuAutoAgent  
**探索深度:** Very Thorough

---

## 目录结构概览

```
XianyuAutoAgent/
├── ai_kefu/                    # 主要应用核心
│   ├── xianyu_interceptor/    # ⭐ 闲鱼消息拦截核心模块
│   ├── xianyu_provider/       # ⭐ 闲鱼API提供者（委托上游）
│   ├── api/                    # FastAPI 应用层
│   ├── services/               # 商业逻辑服务层
│   ├── tools/                  # 工具函数
│   ├── models/                 # 数据模型
│   ├── utils/                  # 工具函数
│   ├── config/                 # 配置管理
│   ├── agent/                  # AI Agent 实现
│   ├── llm/                    # LLM 集成
│   ├── prompts/                # 提示词模板
│   ├── storage/                # 数据存储层
│   └── docs/                   # 文档
├── InventoryManager/           # 库存管理系统（Flask）
├── cocs/                        # 浏览器自动化工具（COCS）
├── tools/                       # 工具集
└── docs/                        # 项目文档
```

---

## 核心架构分析

### 系统架构高层流程

```
Xianyu浏览器实例
    ↓
Playwright浏览器控制 (BrowserController)
    ↓
Chrome DevTools Protocol (CDPInterceptor)
    ↓
WebSocket 拦截和消息解码 (MessagingCore)
    ↓
HTTP POST → FastAPI /xianyu/inbound
    ↓
消息处理和业务逻辑 (XianyuInboundRequest)
    ↓
AI Agent 回复生成 (Claude API)
    ↓
BrowserTransport → 钉钉/Xianyu发送回复
```

---

## 📡 网络请求相关代码

### 1. HTTP 客户端 (`http_client.py`)

**文件:** `/ai_kefu/xianyu_interceptor/http_client.py`

**功能:** 与AI Agent服务通信的异步HTTP客户端

**关键特性:**
- 使用 `httpx` 库实现异步HTTP请求
- 重试机制（Tenacity库）：
  - 最多4次重试
  - 指数退避策略
  - 可重试错误类型：
    - 连接错误 (ConnectError)
    - 连接池超时 (PoolTimeout)
    - 读取超时 (ReadTimeout)
    - HTTP 500/502/503/504
- 请求和响应的详细日志记录
- 性能指标收集（响应时间、成功/失败率）

**关键代码片段:**
```python
class AgentClient:
    def __init__(self, config: AgentClientConfig):
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(timeout=config.timeout, connect=config.connect_timeout),
            follow_redirects=True
        )
    
    async def send_message(self, query: str, session_id=None, user_id=None, context=None):
        # POST to /chat/ endpoint with retry logic
        response = await self._send_with_retry(request)
    
    async def stream_message(self, query: str, ...):
        # Streaming mode with Server-Sent Events
        async with self.client.stream("POST", "/chat/stream", json=request.model_dump()) as response:
            async for line in response.aiter_lines():
                if line.startswith("data: "):
                    yield json.loads(line[6:])["text"]
```

### 2. WebSocket 拦截和消息处理

#### CDP 拦截器 (`cdp_interceptor.py`)

**文件:** `/ai_kefu/xianyu_interceptor/cdp_interceptor.py`

**功能:** 使用Chrome DevTools Protocol拦截WebSocket消息

**监控机制:**

1. **WebSocket 事件监听** (Network域)
   - `Network.webSocketCreated` - WebSocket创建时触发
   - `Network.webSocketFrameReceived` - 接收WebSocket帧
   - `Network.webSocketFrameSent` - 发送WebSocket帧
   - `Network.webSocketClosed` - WebSocket关闭

2. **底层网络拦截** (Fetch域)
   ```python
   await self.cdp_session.send("Fetch.enable", {
       "patterns": [
           {"urlPattern": "*wss://*", "requestStage": "Request"},
           {"urlPattern": "*ws://*", "requestStage": "Request"}
       ]
   })
   ```

3. **HTTP 响应监听** (用于历史消息API)
   - `Network.responseReceived` - 响应接收
   - `Network.loadingFinished` - 请求完成
   
4. **Console API 监听** (捕获JS日志)
   ```python
   self.cdp_session.on("Runtime.consoleAPICalled", self._on_console_api)
   ```

**闲鱼WebSocket检测:**
- URL模式识别：
  - `wss-goofish.dingtalk.com`
  - `msgacs.m.taobao.com`
  - `wss.goofish.com`

**关键代码:**
```python
async def _on_fetch_request_paused(self, params):
    url = params.get("request", {}).get("url", "")
    if url.startswith("wss://") or url.startswith("ws://"):
        logger.info(f"🚀 Fetch 域拦截到 WebSocket 请求: {url}")
        if any(domain in url for domain in ["wss-goofish.dingtalk.com", ...]):
            self.websocket_id = f"fetch_{request_id}"

async def _on_frame_received(self, params):
    payload = params.get("response", {}).get("payloadData")
    if payload:
        message_data = json.loads(payload)
        if self.message_callback:
            await asyncio.create_task(self._safe_callback(message_data))
```

#### 浏览器控制器 (`browser_controller.py`)

**文件:** `/ai_kefu/xianyu_interceptor/browser_controller.py`

**功能:** 使用Playwright管理Chromium浏览器实例

**关键特性:**

1. **反自动化特征注入:**
   ```javascript
   Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
   window.chrome = {runtime: {}};
   ```

2. **浏览器启动参数:**
   ```python
   launch_args = [
       "--disable-blink-features=AutomationControlled",
       "--disable-dev-shm-usage",
       "--no-sandbox"
   ]
   ```

3. **Cookie管理:**
   - Cookie注入：`await self._inject_cookies(cookies_str)`
   - Cookie提取：`await self.extract_cookies()`

4. **User-Agent设置:**
   ```
   Mozilla/5.0 (Windows NT 10.0; Win64; x64) 
   AppleWebKit/537.36 (KHTML, like Gecko) 
   Chrome/133.0.0.0 Safari/537.36
   ```

5. **Viewport配置:**
   - 宽度：1280px
   - 高度：720px
   - 可配置（通过环境变量）

6. **代理支持:**
   - 环境变量 `BROWSER_PROXY`

### 3. 消息编解码 (`messaging_core.py`)

**文件:** `/ai_kefu/xianyu_interceptor/messaging_core.py`

**功能:** WebSocket消息的编码解码和标准化

**关键操作:**
- 消息解码 (`decode_message()`)
- 消息分类 (`classify_message()`)
- 数据提取 (`extract_message_data()`)
- 支持的消息类型：
  - CHAT (聊天消息)
  - ORDER (订单消息)
  - SYSTEM (系统消息)

### 4. Xianyu API 提供者 (`goofish_provider.py`)

**文件:** `/ai_kefu/xianyu_provider/goofish_provider.py`

**功能:** 委托给上游 `cv-cat/XianYuApis` 的Xianyu API适配层

**关键HTTP API:**

1. **认证 (Token获取)**
   ```python
   def _sync_get_token(self) -> dict:
       # 委托给 XianyuApis.get_token()
   ```

2. **订单查询**
   ```python
   async def get_order_list(self) -> list[dict]:
       # 获取订单列表
   ```

3. **订单详情**
   ```python
   _ORDER_DETAIL_URL = "https://h5api.m.goofish.com/h5/mtop.taobao.idle.trade.order.detail/1.0/"
   ```

4. **WebSocket连接**
   ```python
   _WS_URL = "wss://wss-goofish.dingtalk.com/"
   ```

**Headers构造:**
```python
def get_ws_headers(self) -> dict[str, str]:
    return {
        "Cookie": get_session_cookies_str(self._apis.session),
        "Host": "wss-goofish.dingtalk.com",
        "Connection": "Upgrade",
        "Pragma": "no-cache",
        "Cache-Control": "no-cache",
        "User-Agent": _UA,
        "Origin": "https://www.goofish.com",
        "Accept-Encoding": "gzip, deflate, br, zstd",
        "Accept-Language": "zh-CN,zh;q=0.9",
    }
```

**上游常量:**
```python
_APP_KEY = "34839810"
_APP_CONFIG_APP_KEY = "444e9908a51d1cb236a27862abc769c9"
_UA = "Mozilla/5.0 ... Chrome/146.0.0.0 Safari/537.36"
_UA_DINGTALK = "... DingTalk(2.1.5) ..."
```

---

## 🌐 浏览器自动化工具分析

### 使用的工具

| 工具 | 用途 | 版本 | 状态 |
|------|------|------|------|
| **Playwright** | 主要浏览器自动化 | 异步API | ✅ 主要使用 |
| **Chrome DevTools Protocol (CDP)** | 网络拦截和WebSocket监控 | 通过Playwright | ✅ 主要使用 |
| **Chromium (via Playwright)** | 浏览器引擎 | 最新 | ✅ 主要使用 |
| **Puppeteer** | - | - | ❌ 未使用 |
| **Selenium** | - | - | ❌ 未使用 |

### Playwright 集成

**核心文件:**
- `/ai_kefu/xianyu_interceptor/browser_controller.py` - 浏览器生命周期管理
- `/cocs/browser/goofish_browser.py` - 闲鱼浏览器集成
- `/cocs/browser/page_manager.py` - 页面管理

**关键操作:**

1. **浏览器启动:**
   ```python
   self.playwright = await async_playwright().start()
   self.browser = await self.playwright.chromium.launch(
       headless=config.headless,
       args=launch_args
   )
   ```

2. **页面创建:**
   ```python
   self.context = await self.browser.new_context(**context_options)
   self.page = await self.context.new_page()
   await self.page.goto("https://www.goofish.com/", wait_until="networkidle")
   ```

3. **CDP会话创建:**
   ```python
   cdp_session = await browser_controller.context.new_cdp_session(page)
   interceptor = CDPInterceptor(cdp_session)
   await interceptor.setup()  # 启用Network和Fetch域
   ```

4. **事件监听:**
   ```python
   browser_controller.context.on("page", on_new_page)  # 新页面
   page.on("framenavigated", on_navigation)              # 页面导航
   ```

---

## 🔐 登录/认证相关代码

### Cookie 管理

**来源:**
- 环境变量 `XIANYU_COOKIE` (`.env`文件)
- 浏览器Cookie提取 (自动化登录后)

**关键文件:**
- `/ai_kefu/xianyu_interceptor/browser_controller.py` - Cookie注入和提取
- `/ai_kefu/xianyu_provider/goofish_provider.py` - Cookie转换

**Cookie操作:**

1. **Cookie注入到浏览器:**
   ```python
   async def _inject_cookies(self, cookies_str: str) -> None:
       cookies_list = trans_cookies(cookies_str)  # 转换为列表
       await self.context.add_cookies(cookies_list)
   ```

2. **从浏览器提取Cookie:**
   ```python
   async def extract_cookies(self) -> Optional[str]:
       cookies = await self.context.cookies()
       # 转换为字符串格式
       return get_session_cookies_str(session)
   ```

3. **Cookie推送到API:**
   ```python
   async def _push_cookies_to_api(browser_controller, agent_service_url: str) -> None:
       cookies_str = await browser_controller.extract_cookies()
       resp = await client.post(
           f"{agent_service_url}/xianyu/update-cookies",
           json={"cookies_str": cookies_str}
       )
   ```

### Token管理

**关键端点:**

1. **Token获取** (来自GoofishProvider)
   ```python
   def _sync_get_token(self) -> dict[str, Any]:
       # 委托给上游 XianyuApis.get_token()
   ```

2. **Token更新** (自动)
   ```python
   # 通过 GoofishProvider session 自动刷新
   # session 维护 Cookie 和 Token
   ```

### 用户身份识别

**关键字段:**
- `unb` (Cookie中的淘宝/闲鱼用户ID)
- `user_id` (消息中的用户ID)
- `encrypted_uid` (加密用户ID，用于隐私保护)

**身份提取流程:**
```python
# 从Cookie提取
cookies_dict = trans_cookies(config.cookies_str)
unb = cookies_dict.get("unb", "")  # 卖家user_id

# 从消息提取
xianyu_message.user_id  # 消息发送者ID
xianyu_message.encrypted_uid  # 加密的UID

# UID映射记录
record_uid_mapping(user_id, encrypted_uid)  # 维护映射表
```

---

## 📝 Xianyu API 交互代码

### 主要API端点

**文件:** `/ai_kefu/api/routes/xianyu.py`

#### 1. 消息入站端点

**POST /xianyu/inbound**

```python
class XianyuInboundRequest(BaseModel):
    chat_id: str                    # 聊天ID
    user_id: str                    # 用户ID
    content: Optional[str]          # 消息内容
    item_id: Optional[str]          # 商品ID
    user_nickname: Optional[str]    # 用户昵称
    encrypted_uid: Optional[str]    # 加密UID
    is_self_sent: bool              # 是否自己发送
    message_id: Optional[str]       # 消息ID
    item_title: Optional[str]       # 商品标题
    item_price: Optional[str]       # 商品价格
    timestamp: Optional[int]        # 时间戳
    raw_data: Optional[dict]        # 原始数据
    metadata: Optional[dict]        # 元数据

async def xianyu_inbound(req: XianyuInboundRequest) -> XianyuInboundResponse:
    # 业务逻辑：
    # 1. 消息方向检测（卖家 vs 买家）
    # 2. 忽略模式过滤
    # 3. 手动模式切换检查
    # 4. AI抑制（卖家密钥）
    # 5. 订单检测 → 租赁摘要 + 订单记录
    # 6. AI Agent调用
    # 7. 对话日志记录到MySQL
    
    return XianyuInboundResponse(reply=agent_reply)
```

#### 2. Cookie更新端点

**POST /xianyu/update-cookies**

```python
async def update_cookies(req: UpdateCookiesRequest):
    """
    浏览器cookie更新端点
    由 run_xianyu.py 在检测到WebSocket后调用
    """
    provider = GoofishProvider(cookies_str=req.cookies_str)
    init_provider(provider)  # 重新初始化提供者
    return UpdateCookiesResponse(success=True, user_id=provider.my_user_id)
```

### Xianyu API工具函数

**文件:** `/ai_kefu/tools/xianyu.py`

关键函数包括：
- `get_order_list()` - 获取订单列表
- `get_order_detail(order_id)` - 获取订单详情
- `get_item_info(item_id)` - 获取商品信息
- `get_chat_history(chat_id)` - 获取聊天历史

### 历史消息处理

**文件:** `/ai_kefu/xianyu_interceptor/history_message_parser.py`

```python
class HistoryMessageParser:
    @staticmethod
    def is_history_message_response(message_data: dict) -> bool:
        # 判断是否是历史消息API响应
        
    @staticmethod
    def parse_history_messages(message_data: dict) -> List[XianyuMessage]:
        # 从API响应中解析历史消息列表
```

**历史消息保存流程:**
```
历史消息API响应 → 解析 → POST /xianyu/inbound (metadata.history_only=True) 
  → API层识别并仅入库，不触发AI回复
```

---

## 🔄 主要数据流程

### 消息处理流程

```
1. 浏览器WebSocket消息接收
   ↓
2. CDP拦截器捕获 (Network.webSocketFrameReceived)
   ↓
3. 消息编解码 (XianyuMessageCodec)
   ↓
4. 消息分类 (CHAT/ORDER/SYSTEM)
   ↓
5. 标准数据提取
   ↓
6. XianyuMessage对象构造
   ↓
7. HTTP POST → /xianyu/inbound
   ↓
8. 业务逻辑处理：
   - 忽略模式检查
   - 手动模式检查
   - 订单检测
   - AI回复生成
   ↓
9. 数据库记录 (ConversationStore)
   ↓
10. 回复发送 (BrowserTransport → 钉钉/闲鱼)
```

### 拦截器启动流程

```
run_xianyu.py main()
  ↓
1. 初始化拦截器 (initialize_interceptor)
  ↓
2. 启动浏览器 (BrowserController.launch)
  ↓
3. 等待API就绪 (_wait_for_api_ready)
  ↓
4. 推送初始Cookie (_push_cookies_to_api)
  ↓
5. 为所有页面设置CDP监控 (setup_page_monitoring)
  ↓
6. 监听新页面 (context.on("page"))
  ↓
7. 监听页面导航 (page.on("framenavigated"))
  ↓
8. 主循环：定期检查WebSocket连接状态
  ↓
9. 消息回调处理 (on_message)
```

---

## 📁 关键文件列表

### xianyu_interceptor 模块

| 文件 | 大小 | 功能 | 关键性 |
|------|------|------|--------|
| `__init__.py` | 2KB | 模块初始化 | 🟡 |
| `browser_transport.py` | 3.9KB | 浏览器传输层 | 🟢 |
| `browser_controller.py` | 14.4KB | 浏览器控制 | 🟢 |
| `cdp_interceptor.py` | 49.3KB | WebSocket拦截 | 🟢 |
| `http_client.py` | 8KB | HTTP客户端 | 🟢 |
| `conversation_store.py` | 55KB | 消息存储 | 🟢 |
| `messaging_core.py` | 14.3KB | 消息编解码 | 🟢 |
| `message_handler.py` | 6.4KB | 消息处理 | 🟢 |
| `session_mapper.py` | 8.2KB | 会话映射 | 🟡 |
| `history_message_parser.py` | 5.9KB | 历史消息解析 | 🟡 |
| `uid_mapper.py` | 2KB | UID映射 | 🟡 |
| `config.py` | 1.8KB | 配置 | 🟡 |
| `models.py` | 4.2KB | 数据模型 | 🟡 |
| `exceptions.py` | 1.4KB | 异常定义 | 🟡 |
| `image_handler.py` | 8.9KB | 图片处理 | 🟡 |
| `logging_setup.py` | 3.6KB | 日志设置 | 🟡 |

### xianyu_provider 模块

| 文件 | 大小 | 功能 | 关键性 |
|------|------|------|--------|
| `base.py` | 9.3KB | 基础提供者ABC | 🟢 |
| `goofish_provider.py` | 38.7KB | Xianyu API适配层 | 🟢 |
| `upstream/` | - | cv-cat/XianYuApis子模块 | 🟢 |

### API 路由

| 文件 | 大小 | 功能 | 关键性 |
|------|------|------|--------|
| `routes/xianyu.py` | 32.2KB | Xianyu消息入站 | 🟢 |
| `routes/chat.py` | 7.9KB | AI聊天 | 🟢 |
| `routes/conversations.py` | 16.7KB | 对话管理 | 🟢 |
| `routes/dingtalk.py` | 3.8KB | 钉钉集成 | 🟡 |

### 核心启动文件

| 文件 | 大小 | 功能 | 关键性 |
|------|------|------|--------|
| `run_xianyu.py` | 14.6KB | 拦截器启动脚本 | 🟢 |
| `api/main.py` | 3.6KB | FastAPI应用 | 🟢 |

---

## 🔍 环境变量和配置

### 拦截器配置 (config.py)

```python
# 浏览器配置
BROWSER_HEADLESS = "false"              # 是否无头模式
BROWSER_DEBUG_PORT = None               # 调试端口
BROWSER_USER_DATA_DIR = "./browser_data"
BROWSER_VIEWPORT_WIDTH = "1280"
BROWSER_VIEWPORT_HEIGHT = "720"
BROWSER_PROXY = None                    # 代理

# API配置
AGENT_SERVICE_URL = "http://localhost:8000"
ENABLE_AI_REPLY = "true"

# Xianyu配置
XIANYU_COOKIE = "your_cookies_here"    # 从.env读取
```

### API配置 (config/settings.py)

```python
seller_user_id = "xxx"                  # 卖家ID（用于识别自己的消息）
xianyu_cookie = "..."                   # Xianyu cookies
toggle_keywords = "。"                   # 切换手动模式的关键词
suppress_keywords = "..."               # AI抑制关键词
model_name = "claude-3-5-sonnet"        # 使用的LLM模型
api_port = 8000                         # API端口
```

---

## 🚨 网络请求模式总结

### HTTP 请求

| 方向 | URL | 方法 | 目的 | 频率 |
|------|-----|------|------|------|
| 拦截器 → API | `/health` | GET | 健康检查 | 每3秒（启动时） |
| 拦截器 → API | `/xianyu/inbound` | POST | 转发消息 | 实时 |
| 拦截器 → API | `/xianyu/update-cookies` | POST | 更新Cookie | 登录后 + 30分钟 |
| API → GoofishProvider | Taobao API | POST | 订单/商品查询 | 按需 |

### WebSocket 连接

| 服务器 | URL | 握手头 | 消息格式 |
|--------|-----|--------|---------|
| Xianyu | `wss://wss-goofish.dingtalk.com/` | 含Cookie | 二进制/JSON |
| Dingtalk | TBD | 含Token | JSON |

### Cookie 使用

| 字段 | 来源 | 用途 | 敏感度 |
|------|------|------|--------|
| `unb` | 登录时 | 用户身份 | 🔴 |
| `tb_token` | 登录时 | 请求签名 | 🔴 |
| 其他淘宝Cookie | 登录时 | 会话维持 | 🔴 |

---

## ⚙️ 部署和运行

### 启动拦截器

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
python run_xianyu.py
```

### 启动API服务

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
uvicorn api.main:app --host 0.0.0.0 --port 8000
```

### Docker部署

```bash
cd /Users/jimmypan/git_repo/XianyuAutoAgent/ai_kefu
docker build -f docker/Dockerfile -t xianyu-agent:latest .
docker run -e XIANYU_COOKIE="..." -p 8000:8000 xianyu-agent:latest
```

---

## 📊 文件统计

```
Python文件总数: 16,892
主要模块：
  - xianyu_interceptor: ~24个文件（核心）
  - xianyu_provider: ~6个文件
  - api/routes: ~12个文件
  - services: ~15个文件
  - tools: ~10个文件
  - models: ~15个文件
  
代码行数估计: 50,000+ 行
```

---

## 🎯 关键发现

### 1. ✅ 已使用的技术
- **Playwright** - 主要浏览器自动化框架
- **Chrome DevTools Protocol** - WebSocket网络拦截
- **FastAPI** - 异步Web框架
- **httpx** - 异步HTTP客户端
- **Websockets** - WebSocket库
- **Claude API** - 大语言模型

### 2. ❌ 未使用的技术
- Selenium - 被Playwright取代
- Puppeteer - 被Playwright取代
- 同步requests库 - 改用异步httpx

### 3. 🔐 安全特性
- Cookie安全管理（加密存储建议）
- 浏览器自动化特征隐藏
- UID加密映射
- 手动/自动模式切换

### 4. 🚀 性能优化
- 异步/并发处理
- HTTP重试和断路器
- WebSocket多页面监听
- Cookie定期刷新（防止过期）

### 5. ⚠️ 注意事项
- WebSocket可能在多个页面中创建
- 需要持续监听新页面和页面导航
- 历史消息需要特殊处理（仅入库，不触发AI）
- Cookie需要定期刷新（30分钟）

---

## 📞 相关资源

### 上游项目
- **XianYuApis**: https://github.com/cv-cat/XianYuApis
- 提供基础的Xianyu API实现
- 负责请求签名和Cookie管理

### 文档位置
- `/ai_kefu/CODEBASE_EXPLORATION.md`
- `/ai_kefu/README.md`
- `/ai_kefu/ARCHITECTURE_SUMMARY.md`

---

**报告完成时间:** 2026年5月4日

