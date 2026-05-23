# XianyuAutoAgent 项目代码片段详解

---

## 目录
1. [HTTP 请求实现](#http-请求实现)
2. [WebSocket 拦截](#websocket-拦截)
3. [浏览器自动化](#浏览器自动化)
4. [认证和Cookie管理](#认证和cookie管理)
5. [API 集成](#api-集成)

---

## HTTP 请求实现

### 1. 异步HTTP客户端 - `http_client.py`

```python
from httpx import AsyncClient, Timeout, HTTPStatusError, ConnectError, PoolTimeout, ReadTimeout
from tenacity import retry, stop_after_attempt, wait_exponential

class AgentClient:
    """与AI Agent服务通信的异步HTTP客户端"""
    
    def __init__(self, config: AgentClientConfig):
        self.config = config
        base_url = config.base_url.rstrip("/")
        
        # 创建异步HTTP客户端，配置超时和重定向
        self.client = httpx.AsyncClient(
            base_url=base_url,
            timeout=httpx.Timeout(
                timeout=config.timeout,      # 总超时
                connect=config.connect_timeout  # 连接超时
            ),
            follow_redirects=True
        )
        self.metrics = HTTPClientMetrics()
    
    async def send_message(self, query: str, session_id=None, user_id=None, context=None):
        """同步模式：发送消息到AI Agent"""
        request = AgentChatRequest(
            query=query,
            session_id=session_id,
            user_id=user_id,
            context=context or {}
        )
        
        start_time = time.time()
        try:
            response = await self._send_with_retry(request)
            response_time = time.time() - start_time
            
            # 记录成功指标
            self.metrics.add_request(success=True, response_time=response_time)
            logger.info(f"Agent API success: session={session_id}, response_time={response_time:.2f}s")
            
            return response
        except Exception as e:
            response_time = time.time() - start_time
            error_type = type(e).__name__
            
            # 记录失败指标
            self.metrics.add_request(success=False, response_time=response_time, error=error_type)
            logger.error(f"Agent API failed: session={session_id}, error={error_type}")
            
            raise AgentAPIError(f"Agent API call failed: {str(e)}") from e
    
    @retry(
        retry=retry_if_exception(_is_retryable_error),  # 仅重试可重试错误
        stop=stop_after_attempt(4),                      # 最多4次
        wait=wait_exponential(multiplier=1, min=1, max=15),  # 指数退避
        before_sleep=before_sleep_log(_std_logger, logging.WARNING),
        reraise=True
    )
    async def _send_with_retry(self, request: AgentChatRequest):
        """带重试的请求发送"""
        try:
            # POST to /chat/ endpoint
            response = await self.client.post(
                "/chat/",
                json=request.model_dump(exclude_none=True)
            )
            
            # 检查HTTP状态码
            if response.status_code != 200:
                logger.error(f"Agent API returned {response.status_code}: {response.text[:500]}")
            
            response.raise_for_status()  # 如果不是200，抛出异常
            
            # 解析响应
            data = response.json()
            return AgentChatResponse(**data)
            
        except httpx.HTTPStatusError as e:
            status_code = e.response.status_code
            if _is_retryable_error(e):
                logger.warning(f"HTTP {status_code} (retryable), body={e.response.text[:300]}")
            else:
                logger.error(f"HTTP {status_code} (not retryable), body={e.response.text[:500]}")
            raise
        except httpx.HTTPError as e:
            logger.warning(f"HTTP error (will retry if applicable): {e}")
            raise
    
    async def stream_message(self, query: str, session_id=None, user_id=None, context=None):
        """流式模式：接收分块响应"""
        request = AgentChatRequest(
            query=query,
            session_id=session_id,
            user_id=user_id,
            context=context or {}
        )
        
        try:
            # 使用流式请求
            async with self.client.stream(
                "POST",
                "/chat/stream",
                json=request.model_dump(exclude_none=True)
            ) as response:
                response.raise_for_status()
                
                # 逐行读取Server-Sent Events格式
                async for line in response.aiter_lines():
                    if line.startswith("data: "):
                        import json
                        data = json.loads(line[6:])
                        if data.get("type") == "chunk":
                            yield data["text"]
                            
        except httpx.HTTPError as e:
            logger.error(f"Streaming error: {e}")
            raise AgentAPIError(f"Streaming failed: {str(e)}") from e
    
    async def health_check(self):
        """健康检查"""
        try:
            response = await self.client.get(self.config.health_check_path)
            is_healthy = response.status_code == 200
            
            self.metrics.is_healthy = is_healthy
            self.metrics.last_health_check = time.time()
            
            return is_healthy
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

def _is_retryable_error(exception: BaseException) -> bool:
    """判断异常是否可重试"""
    # 连接错误可重试
    if isinstance(exception, (
        httpx.ConnectError,      # 无法连接
        httpx.PoolTimeout,       # 连接池超时
        httpx.ReadTimeout        # 读取超时
    )):
        return True
    
    # 5xx错误可重试
    if isinstance(exception, httpx.HTTPStatusError):
        return exception.response.status_code in (500, 502, 503, 504)
    
    return False
```

---

## WebSocket 拦截

### 2. CDP拦截器 - `cdp_interceptor.py`

```python
from loguru import logger
from typing import Dict, Any, Optional, Callable

class CDPInterceptor:
    """使用Chrome DevTools Protocol拦截WebSocket消息"""
    
    def __init__(self, cdp_session):
        self.cdp_session = cdp_session
        self.websocket_id: Optional[str] = None
        self.message_callback: Optional[Callable] = None
        self._is_monitoring = False
        self._is_setup = False
    
    async def setup(self) -> bool:
        """设置CDP监控"""
        try:
            if self._is_setup:
                logger.debug("CDP monitoring already setup")
                return True
            
            logger.info("Setting up CDP WebSocket monitoring...")
            
            # ============================================================
            # 步骤1：启用Network域
            # ============================================================
            await self.cdp_session.send("Network.enable")
            logger.debug("Network domain enabled")
            
            # ============================================================
            # 步骤2：订阅WebSocket事件
            # ============================================================
            self.cdp_session.on("Network.webSocketCreated", self._on_websocket_created)
            self.cdp_session.on("Network.webSocketFrameReceived", self._on_frame_received)
            self.cdp_session.on("Network.webSocketFrameSent", self._on_frame_sent)
            self.cdp_session.on("Network.webSocketClosed", self._on_websocket_closed)
            logger.debug("WebSocket event listeners registered")
            
            # ============================================================
            # 步骤3：监听HTTP请求（用于WebSocket握手检测）
            # ============================================================
            async def on_request_will_be_sent(params):
                request = params.get("request", {})
                url = request.get("url", "")
                if "wss://" in url or "ws://" in url:
                    logger.info(f"🌐 WebSocket request detected: {url}")
            
            self.cdp_session.on("Network.requestWillBeSent", on_request_will_be_sent)
            logger.debug("HTTP request listener registered")
            
            # ============================================================
            # 步骤4：启用Fetch域进行底层网络拦截
            # ============================================================
            # Fetch域可以拦截所有网络请求，包括跨域iframe中的请求
            # 这比WebSocket事件更可靠
            try:
                await self.cdp_session.send("Fetch.enable", {
                    "patterns": [
                        {
                            "urlPattern": "*wss://*",  # 拦截所有WSS连接
                            "requestStage": "Request"
                        },
                        {
                            "urlPattern": "*ws://*",   # 拦截所有WS连接
                            "requestStage": "Request"
                        }
                    ]
                })
                logger.info("✅ Fetch domain enabled (low-level WebSocket interception)")
                
                # 监听Fetch请求暂停事件
                self.cdp_session.on("Fetch.requestPaused", self._on_fetch_request_paused)
                logger.debug("Fetch.requestPaused listener registered")
                
            except Exception as e:
                logger.warning(f"Failed to enable Fetch domain (non-critical): {e}")
            
            # ============================================================
            # 步骤5：监听HTTP响应（用于历史消息API）
            # ============================================================
            # 闲鱼在打开聊天窗口时会通过HTTP API加载历史消息
            self.cdp_session.on("Network.responseReceived", self._on_response_received)
            self.cdp_session.on("Network.loadingFinished", self._on_loading_finished)
            logger.info("✅ History message API listeners enabled")
            
            # 启用Runtime域（用于执行JavaScript）
            await self.cdp_session.send("Runtime.enable")
            
            self._is_monitoring = True
            self._is_setup = True
            logger.info("CDP monitoring setup completed successfully")
            return True
            
        except Exception as e:
            logger.error(f"CDP monitoring setup failed: {e}")
            return False
    
    async def _on_fetch_request_paused(self, params: Dict[str, Any]) -> None:
        """Fetch请求暂停事件处理（底层网络拦截）"""
        try:
            request_id = params.get("requestId")
            request = params.get("request", {})
            url = request.get("url", "")
            
            # 检查是否是WebSocket请求
            if url.startswith("wss://") or url.startswith("ws://"):
                logger.info(f"🚀 Fetch intercepted WebSocket: {url}")
                
                # 检查是否是闲鱼的WebSocket
                is_xianyu = any(domain in url for domain in [
                    "wss-goofish.dingtalk.com",
                    "msgacs.m.taobao.com",
                    "wss.goofish.com"
                ])
                
                if is_xianyu:
                    self.websocket_id = f"fetch_{request_id}"
                    logger.info(f"✅ Xianyu WebSocket detected: {url}")
            
            # 继续请求（不阻止）
            try:
                await self.cdp_session.send("Fetch.continueRequest", {
                    "requestId": request_id
                })
            except Exception as e:
                logger.debug(f"Failed to continue Fetch request: {e}")
                
        except Exception as e:
            logger.error(f"Failed to handle Fetch request pause event: {e}")
    
    async def _on_websocket_created(self, params: Dict[str, Any]) -> None:
        """WebSocket创建事件处理"""
        try:
            request_id = params.get("requestId")
            url = params.get("url")
            
            logger.debug(f"WebSocket created: {url}")
            
            # 检查是否是闲鱼的WebSocket
            is_xianyu = any(domain in url for domain in [
                "wss-goofish.dingtalk.com",
                "msgacs.m.taobao.com",
                "wss.goofish.com"
            ])
            
            if is_xianyu:
                self.websocket_id = request_id
                logger.info(f"✅ Xianyu WebSocket connection detected: {url}")
                logger.info(f"WebSocket ID: {self.websocket_id}")
            else:
                logger.debug(f"Non-Xianyu WebSocket, ignoring: {url}")
                
        except Exception as e:
            logger.error(f"Failed to handle WebSocket creation event: {e}")
    
    async def _on_frame_received(self, params: Dict[str, Any]) -> None:
        """WebSocket接收帧事件处理"""
        try:
            request_id = params.get("requestId")
            
            # 只处理Xianyu WebSocket
            if request_id != self.websocket_id:
                return
            
            response = params.get("response", {})
            payload = response.get("payloadData")
            
            if payload:
                # 解析消息
                try:
                    message_data = json.loads(payload)
                    logger.debug(f"WebSocket message received (via CDP)")
                    
                    # 调用回调函数
                    if self.message_callback:
                        await asyncio.create_task(self._safe_callback(message_data))
                        
                except json.JSONDecodeError:
                    logger.debug("Non-JSON WebSocket message")
                    
        except Exception as e:
            logger.error(f"Failed to handle WebSocket frame received event: {e}")
    
    async def _safe_callback(self, message_data: Dict[str, Any]):
        """安全调用回调函数"""
        try:
            if callable(self.message_callback):
                result = self.message_callback(message_data)
                if asyncio.iscoroutine(result):
                    await result
        except Exception as e:
            logger.error(f"Error in message callback: {e}")
```

### 3. 消息编解码 - `messaging_core.py`

```python
class XianyuMessageCodec:
    """WebSocket消息的编码解码和标准化"""
    
    @staticmethod
    def decode_message(message_data: dict) -> Optional[dict]:
        """解码WebSocket消息"""
        # 只有 syncPushPackage 格式的消息才能被解码
        # 其他消息（响应、状态更新等）会被静默忽略
        
        if not isinstance(message_data, dict):
            return None
        
        # 检查是否是syncPushPackage消息
        if message_data.get("lwp") != "syncPushPackage":
            return None
        
        body = message_data.get("body", {})
        if not body:
            return None
        
        # 解码消息内容（可能需要protobuf解码）
        try:
            decoded = _decode_protobuf(body)
            return decoded
        except Exception as e:
            logger.debug(f"Failed to decode message: {e}")
            return None
    
    @staticmethod
    def classify_message(decoded_message: dict) -> MessageType:
        """分类消息类型"""
        # 根据消息结构判断类型
        if "chatMessage" in decoded_message:
            return MessageType.CHAT
        elif "orderMessage" in decoded_message:
            return MessageType.ORDER
        elif "systemMessage" in decoded_message:
            return MessageType.SYSTEM
        else:
            return MessageType.UNKNOWN
    
    @staticmethod
    def extract_message_data(decoded_message: dict) -> Optional[StandardMessage]:
        """提取标准化的消息数据"""
        
        message_type = XianyuMessageCodec.classify_message(decoded_message)
        
        if message_type == MessageType.CHAT:
            # 提取聊天消息
            chat_msg = decoded_message.get("chatMessage", {})
            return StandardMessage(
                message_type=message_type,
                user_id=chat_msg.get("from_user_id"),
                chat_id=chat_msg.get("chat_id"),
                content=chat_msg.get("content"),
                timestamp=chat_msg.get("timestamp"),
                item_id=chat_msg.get("item_id"),
                metadata={
                    "message_id": chat_msg.get("message_id"),
                    "user_nickname": chat_msg.get("from_user_nickname"),
                    "encrypted_uid": chat_msg.get("encrypted_uid"),
                    "reminder_title": chat_msg.get("reminder_title"),
                    "item_title": chat_msg.get("item_title"),
                },
                raw_data=decoded_message
            )
        
        elif message_type == MessageType.ORDER:
            # 订单消息通常不需要AI回复
            return None
        
        else:
            return None
```

---

## 浏览器自动化

### 4. 浏览器控制器 - `browser_controller.py`

```python
from playwright.async_api import async_playwright, Browser, BrowserContext, Page

class BrowserController:
    """使用Playwright管理Chromium浏览器实例"""
    
    def __init__(self, config: Optional[BrowserConfig] = None):
        self.config = config or BrowserConfig()
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._is_running = False
    
    async def launch(self, cookies_str: Optional[str] = None) -> bool:
        """启动浏览器并加载闲鱼页面"""
        try:
            logger.info("Starting browser...")
            
            # 启动Playwright
            self.playwright = await async_playwright().start()
            
            # 配置浏览器启动参数（隐藏自动化特征）
            launch_args = [
                "--disable-blink-features=AutomationControlled",  # 禁用自动化控制特征
                "--disable-dev-shm-usage",                         # 解决共享内存不足问题
                "--no-sandbox",                                    # 在某些环境下需要
            ]
            
            if self.config.debug_port:
                launch_args.append(f"--remote-debugging-port={self.config.debug_port}")
            
            # 启动Chromium浏览器
            self.browser = await self.playwright.chromium.launch(
                headless=self.config.headless,
                args=launch_args
            )
            logger.info(f"Browser launched (headless={self.config.headless})")
            
            # ============================================================
            # 创建浏览器上下文（隔离的浏览会话）
            # ============================================================
            context_options = {
                "viewport": {
                    "width": self.config.viewport_width,
                    "height": self.config.viewport_height
                },
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                             "AppleWebKit/537.36 (KHTML, like Gecko) "
                             "Chrome/133.0.0.0 Safari/537.36"
            }
            
            # 添加代理配置（如果有）
            if self.config.proxy:
                context_options["proxy"] = {"server": self.config.proxy}
            
            self.context = await self.browser.new_context(**context_options)
            logger.info(f"Browser context created (viewport={self.config.viewport_width}x{self.config.viewport_height})")
            
            # ============================================================
            # 注入脚本以隐藏自动化特征
            # ============================================================
            await self._inject_stealth_scripts()
            
            # ============================================================
            # 注入Cookie
            # ============================================================
            if cookies_str:
                await self._inject_cookies(cookies_str)
                logger.info("Cookies injected")
            
            # ============================================================
            # 创建新页面
            # ============================================================
            self.page = await self.context.new_page()
            logger.info("Page created")
            
            # ============================================================
            # 导航到闲鱼首页
            # ============================================================
            logger.info("Navigating to Xianyu...")
            await self.page.goto("https://www.goofish.com/", wait_until="networkidle")
            logger.info("Page loaded")
            
            await asyncio.sleep(2)
            
            self._is_running = True
            logger.info("Browser started successfully")
            logger.info("=" * 60)
            logger.info("🔔 Please click the Message Center in the browser")
            logger.info("   WebSocket connection will be established on the new page")
            logger.info("=" * 60)
            
            return True
            
        except Exception as e:
            logger.error(f"Browser startup failed: {e}")
            await self.close()
            return False
    
    async def _inject_stealth_scripts(self) -> None:
        """注入脚本以隐藏浏览器自动化特征"""
        stealth_js = """
        // ========== 隐身脚本 ==========
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        
        // 伪装Chrome对象
        window.chrome = {
            runtime: {}
        };
        
        // 伪装permissions查询
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
        
        // 伪装plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [
                {name: "Chrome PDF Plugin", description: "Portable Document Format"},
                {name: "Chrome PDF Viewer", description: "Portable Document Format"},
            ]
        });
        """
        
        try:
            await self.context.add_init_script(stealth_js)
            logger.debug("Stealth scripts injected")
        except Exception as e:
            logger.warning(f"Failed to inject stealth scripts: {e}")
    
    async def _inject_cookies(self, cookies_str: str) -> None:
        """注入Cookie到浏览器"""
        try:
            # 转换Cookie字符串为列表格式
            from utils.xianyu_utils import trans_cookies
            cookies_list = trans_cookies(cookies_str)
            
            # 添加Cookie到上下文
            await self.context.add_cookies(cookies_list)
            logger.info(f"Injected {len(cookies_list)} cookies")
            
        except Exception as e:
            logger.warning(f"Failed to inject cookies: {e}")
    
    async def extract_cookies(self) -> Optional[str]:
        """从浏览器提取Cookie"""
        try:
            if not self.context:
                return None
            
            # 获取所有Cookie
            cookies = await self.context.cookies()
            
            # 转换为字符串格式
            from utils.xianyu_utils import get_session_cookies_str
            cookies_str = get_session_cookies_str(cookies)
            
            logger.info(f"Extracted {len(cookies)} cookies")
            return cookies_str
            
        except Exception as e:
            logger.error(f"Failed to extract cookies: {e}")
            return None
    
    async def close(self) -> None:
        """关闭浏览器"""
        try:
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
            if self.playwright:
                await self.playwright.stop()
            
            self._is_running = False
            logger.info("Browser closed")
            
        except Exception as e:
            logger.error(f"Failed to close browser: {e}")
```

---

## 认证和Cookie管理

### 5. Xianyu Provider - `goofish_provider.py`

```python
from typing import Any, Dict, Optional
import asyncio

class GoofishProvider(XianyuProvider):
    """
    基于cv-cat/XianYuApis的Xianyu API适配层
    
    所有HTTP API调用委托给上游XianyuApis实例
    """
    
    def __init__(self, cookies_str: str) -> None:
        """初始化Provider"""
        self._cookies_str = cookies_str
        
        # 转换Cookie字符串为字典
        cookies_dict: dict[str, str] = trans_cookies(cookies_str)
        
        # 从Cookie中提取用户ID
        self._my_user_id_val: str = cookies_dict.get("unb", "")
        
        # 生成设备ID
        self._device_id_val: str = _upstream_generate_device_id(self._my_user_id_val)
        
        # 创建上游XianyuApis实例（管理session和cookie刷新）
        self._apis = XianyuApis(cookies_dict, self._device_id_val)
    
    @property
    def my_user_id(self) -> str:
        """获取卖家user_id"""
        return self._my_user_id_val
    
    @property
    def device_id(self) -> str:
        """获取设备ID"""
        return self._device_id_val
    
    @property
    def ws_url(self) -> str:
        """获取WebSocket连接URL"""
        return "wss://wss-goofish.dingtalk.com/"
    
    def get_ws_headers(self) -> dict[str, str]:
        """
        构造WebSocket握手headers
        使用上游session中的最新cookie
        """
        return {
            "Cookie": get_session_cookies_str(self._apis.session),
            "Host": "wss-goofish.dingtalk.com",
            "Connection": "Upgrade",
            "Pragma": "no-cache",
            "Cache-Control": "no-cache",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                         "AppleWebKit/537.36 (KHTML, like Gecko) "
                         "Chrome/146.0.0.0 Safari/537.36",
            "Origin": "https://www.goofish.com",
            "Accept-Encoding": "gzip, deflate, br, zstd",
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
    
    def _sync_get_token(self) -> dict[str, Any]:
        """同步获取token（委托给上游）"""
        try:
            token_result = self._apis.get_token()
            return {
                "success": True,
                "token": token_result.get("token"),
                "expires_at": token_result.get("expires_at")
            }
        except Exception as e:
            logger.error(f"Failed to get token: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_token(self) -> dict[str, Any]:
        """异步获取token"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_get_token)
    
    def _sync_get_order_list(self) -> list[dict]:
        """同步获取订单列表（委托给上游）"""
        try:
            orders = self._apis.get_order_list()
            return [{
                "order_id": order.get("order_id"),
                "item_id": order.get("item_id"),
                "item_title": order.get("item_title"),
                "item_price": order.get("price"),
                "status": order.get("status"),
                "created_at": order.get("created_at")
            } for order in orders]
        except Exception as e:
            logger.error(f"Failed to get order list: {e}")
            return []
    
    async def get_order_list(self) -> list[dict]:
        """异步获取订单列表"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_get_order_list)
    
    def _sync_get_order_detail(self, order_id: str) -> dict:
        """同步获取订单详情"""
        try:
            # 直接使用上游的session和签名函数
            detail = self._apis.get_order_detail(order_id)
            return {
                "success": True,
                "data": detail
            }
        except Exception as e:
            logger.error(f"Failed to get order detail: {e}")
            return {"success": False, "error": str(e)}
    
    async def get_order_detail(self, order_id: str) -> dict:
        """异步获取订单详情"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._sync_get_order_detail, order_id)
```

---

## API 集成

### 6. Xianyu消息入站端点 - `routes/xianyu.py`

```python
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime

router = APIRouter()

# ──────────────────────────────────────────────────────────────
# 数据模型
# ──────────────────────────────────────────────────────────────

class XianyuInboundRequest(BaseModel):
    """从拦截器POSTed的解码消息"""
    chat_id: str                    # 聊天ID
    user_id: str                    # 用户ID
    content: Optional[str] = None   # 消息内容
    item_id: Optional[str] = None   # 商品ID
    user_nickname: Optional[str] = None
    encrypted_uid: Optional[str] = None  # 加密UID
    is_self_sent: bool = False      # 是否自己发送
    message_id: Optional[str] = None
    item_title: Optional[str] = None
    item_price: Optional[str] = None
    timestamp: Optional[int] = None
    raw_data: Optional[dict] = None
    metadata: Optional[dict] = Field(default_factory=dict)

class XianyuInboundResponse(BaseModel):
    """返回给拦截器的响应"""
    reply: Optional[str] = None

# ──────────────────────────────────────────────────────────────
# Cookie更新端点
# ──────────────────────────────────────────────────────────────

@router.post("/update-cookies", response_model=UpdateCookiesResponse)
async def update_cookies(req: UpdateCookiesRequest):
    """
    更新浏览器cookies端点
    由run_xianyu.py在检测到WebSocket后调用
    """
    if not req.cookies_str or req.cookies_str.strip() == "your_cookies_here":
        return UpdateCookiesResponse(
            success=False,
            message="Empty or placeholder cookies"
        )
    
    try:
        # 重新初始化GoofishProvider
        from ai_kefu.xianyu_provider import init_provider
        from ai_kefu.xianyu_provider.goofish_provider import GoofishProvider
        
        provider = GoofishProvider(cookies_str=req.cookies_str)
        init_provider(provider)  # 全局初始化
        
        user_id = provider.my_user_id
        settings.xianyu_cookie = req.cookies_str
        
        logger.info(f"[update-cookies] GoofishProvider re-initialized, user_id={user_id}")
        return UpdateCookiesResponse(
            success=True,
            message="Provider re-initialized",
            user_id=user_id
        )
        
    except Exception as e:
        logger.error(f"[update-cookies] Failed: {e}", exc_info=True)
        return UpdateCookiesResponse(
            success=False,
            message=str(e)
        )

# ──────────────────────────────────────────────────────────────
# 消息入站端点
# ──────────────────────────────────────────────────────────────

@router.post("/inbound", response_model=XianyuInboundResponse)
async def xianyu_inbound(
    req: XianyuInboundRequest,
    conversation_store = Depends(get_conversation_store),
    ignore_patterns = Depends(get_ignore_pattern_store),
    manual_mode = Depends(get_manual_mode_manager)
):
    """
    接收并处理来自拦截器的消息
    
    业务逻辑：
    1. 消息方向检测（卖家 vs 买家）
    2. 忽略模式过滤
    3. 手动模式检查
    4. AI抑制（卖家密钥）
    5. 订单检测
    6. AI Agent调用
    7. 数据库记录
    """
    
    try:
        # ============================================================
        # 步骤1：识别消息方向
        # ============================================================
        is_seller_message = req.is_self_sent
        
        if is_seller_message:
            logger.info(f"[inbound] Seller message: {req.content[:50] if req.content else 'None'}")
            # 卖家的消息不需要回复
            await _log_message(
                req, MessageType.SELLER_MESSAGE, conversation_store
            )
            return XianyuInboundResponse(reply=None)
        
        logger.info(f"[inbound] Buyer message from {req.user_id}: {req.content[:50] if req.content else 'None'}")
        
        # ============================================================
        # 步骤2：检查忽略模式
        # ============================================================
        if ignore_patterns.should_ignore(req.content):
            logger.info(f"[inbound] Message ignored by ignore pattern")
            await _log_message(
                req, MessageType.IGNORED, conversation_store
            )
            return XianyuInboundResponse(reply=None)
        
        # ============================================================
        # 步骤3：检查手动模式
        # ============================================================
        if _is_toggle_keyword(req.content):
            manual_mode.toggle()
            is_manual = manual_mode.is_enabled()
            logger.info(f"[inbound] Manual mode toggled: {is_manual}")
            return XianyuInboundResponse(reply=None)
        
        if manual_mode.is_enabled():
            logger.info(f"[inbound] Manual mode enabled, skipping AI reply")
            await _log_message(
                req, MessageType.MANUAL_MODE_ACTIVE, conversation_store
            )
            return XianyuInboundResponse(reply=None)
        
        # ============================================================
        # 步骤4：检查AI抑制密钥
        # ============================================================
        if _is_suppress_keyword(req.content):
            logger.info(f"[inbound] AI suppressed by keyword")
            await _log_message(
                req, MessageType.AI_SUPPRESSED, conversation_store
            )
            return XianyuInboundResponse(reply=None)
        
        # ============================================================
        # 步骤5：检查订单消息
        # ============================================================
        if _is_order_placed_message(req.content):
            logger.info(f"[inbound] Order placed: {req.content}")
            
            # 异步记录订单详情（不等待）
            asyncio.create_task(
                _record_order_detail(req, req.raw_data, conversation_store)
            )
            
            # 返回订单确认回复
            reply = "感谢下单！我会尽快为你发货。"
            await _log_message(
                req, MessageType.ORDER_CONFIRMATION, conversation_store,
                agent_response=reply
            )
            return XianyuInboundResponse(reply=reply)
        
        # ============================================================
        # 步骤6：调用AI Agent生成回复
        # ============================================================
        logger.info(f"[inbound] Calling AI Agent for chat_id={req.chat_id}")
        
        # 构造Agent请求
        agent_context = {
            "item_id": req.item_id,
            "item_title": req.item_title,
            "item_price": req.item_price,
            "user_nickname": req.user_nickname
        }
        
        # 调用Chat API
        from ai_kefu.api.routes.chat import _call_agent
        agent_response = await _call_agent(
            query=req.content,
            session_id=f"{req.chat_id}:{req.user_id}",
            user_id=req.user_id,
            context=agent_context
        )
        
        logger.info(f"[inbound] Agent response: {agent_response[:50] if agent_response else 'None'}")
        
        # ============================================================
        # 步骤7：记录到数据库
        # ============================================================
        await _log_message(
            req, MessageType.CHAT_WITH_AI_RESPONSE, conversation_store,
            agent_response=agent_response,
            session_id=f"{req.chat_id}:{req.user_id}"
        )
        
        return XianyuInboundResponse(reply=agent_response)
        
    except Exception as e:
        logger.error(f"[inbound] Error processing message: {e}", exc_info=True)
        return XianyuInboundResponse(reply=None)

# ──────────────────────────────────────────────────────────────
# 辅助函数
# ──────────────────────────────────────────────────────────────

async def _log_message(
    req: XianyuInboundRequest,
    message_type: MessageType,
    conversation_store: ConversationStore,
    agent_response: Optional[str] = None,
    session_id: Optional[str] = None
):
    """记录消息到数据库"""
    try:
        context = {
            "item_title": req.item_title,
            "item_price": req.item_price,
            "message_id": req.message_id,
            "is_self_sent": req.is_self_sent,
            "encrypted_uid": req.encrypted_uid,
        }
        
        conversation_msg = ConversationMessage(
            chat_id=req.chat_id,
            user_id=req.user_id,
            user_nickname=req.user_nickname,
            seller_id=None,
            item_id=req.item_id,
            message_id=req.message_id,
            message_content=agent_response if agent_response else req.content,
            message_type=message_type,
            session_id=session_id,
            agent_response=agent_response,
            context=context,
            created_at=datetime.now(),
        )
        
        await asyncio.to_thread(conversation_store.save_message, conversation_msg)
        logger.debug(f"Message logged: chat_id={req.chat_id}, type={message_type}")
        
    except Exception as e:
        logger.error(f"Failed to log message: {e}", exc_info=True)
```

---

## 总结

这个项目使用了现代化的异步Python技术栈：

- **Playwright** + **CDP** 用于浏览器自动化和WebSocket拦截
- **httpx** 用于异步HTTP通信，带重试和超时机制
- **FastAPI** 用于异步Web服务
- **Pydantic** 用于数据验证
- **Tenacity** 用于重试逻辑

所有的HTTP/WebSocket通信都支持错误重试、超时管理和详细的日志记录。

