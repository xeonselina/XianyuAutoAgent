"""
CDP 拦截器模块

使用 Chrome DevTools Protocol 拦截和注入 WebSocket 消息。

【重要】此模块是闲鱼消息拦截的核心组件
- 使用 CDP 监听 WebSocket 创建和消息事件
- 注入 JavaScript 代码拦截浏览器中的 WebSocket
- 支持多种拦截方式：CDP Network 事件、Fetch 域、JavaScript 注入

【注意】闲鱼的 WebSocket 可能在以下位置创建：
- 主窗口
- 跨域 iframe（JavaScript 无法访问，只能通过 CDP）
- 新打开的页面或 Tab

参考：commit 7f54081 "稳定了 ws"
"""

import json
import asyncio
from typing import Optional, Callable, Dict, Any
from loguru import logger


class CDPInterceptor:
    """
    CDP WebSocket 拦截器

    通过 Chrome DevTools Protocol 监控和拦截 WebSocket 通信。
    """

    def __init__(self, cdp_session):
        """
        初始化 CDP 拦截器

        Args:
            cdp_session: Chrome DevTools Protocol 会话
        """
        self.cdp_session = cdp_session
        self.websocket_id: Optional[str] = None
        self.message_callback: Optional[Callable[[Dict[str, Any]], None]] = None
        self._is_monitoring = False
        self._is_setup = False  # 防止重复设置监听器
        self._pending_history_requests: Dict[str, Dict[str, Any]] = {}  # 跟踪历史消息API请求

    async def setup(self) -> bool:
        """
        设置 CDP 监控

        Returns:
            bool: 设置是否成功
        """
        try:
            # 防止重复设置
            if self._is_setup:
                logger.debug("CDP 监控已经设置过，跳过重复设置")
                return True

            logger.info("正在设置 CDP WebSocket 监控...")

            # 启用 Network 域
            await self.cdp_session.send("Network.enable")
            logger.debug("Network 域已启用")

            # 订阅 WebSocket 事件
            self.cdp_session.on("Network.webSocketCreated", self._on_websocket_created)
            self.cdp_session.on("Network.webSocketFrameReceived", self._on_frame_received)
            self.cdp_session.on("Network.webSocketFrameSent", self._on_frame_sent)
            self.cdp_session.on("Network.webSocketClosed", self._on_websocket_closed)
            logger.debug("WebSocket 事件监听器已注册")

            # ============================================================
            # 【重要】监听网络请求（用于调试和兜底检测）
            # ============================================================
            # Network.requestWillBeSent 可以捕获 WebSocket 握手请求
            # 即使 webSocketCreated 事件没有触发，这个事件也能提供线索
            # ============================================================
            async def on_request_will_be_sent(params):
                request = params.get("request", {})
                url = request.get("url", "")
                if "wss://" in url or "ws://" in url:
                    logger.info(f"🌐 检测到 WebSocket 请求: {url}")

            self.cdp_session.on("Network.requestWillBeSent", on_request_will_be_sent)
            logger.debug("网络请求监听器已注册（用于 WebSocket 调试）")

            # ============================================================
            # 【重要】启用 Fetch 域进行更底层的网络拦截
            # ============================================================
            # Fetch 域可以拦截所有网络请求，包括跨域 iframe 中的请求
            # 这是检测 WebSocket 的最可靠方式之一
            #
            # 为什么需要 Fetch 域：
            # - Network.webSocketCreated 可能不触发（浏览器版本差异）
            # - JavaScript 注入无法访问跨域 iframe
            # - Fetch 域在更底层工作，更可靠
            #
            # 【注意】这不会阻止请求，只是观察
            # ============================================================
            try:
                await self.cdp_session.send("Fetch.enable", {
                    "patterns": [
                        {
                            "urlPattern": "*wss://*",  # 拦截所有 WSS 连接
                            "requestStage": "Request"
                        },
                        {
                            "urlPattern": "*ws://*",   # 拦截所有 WS 连接
                            "requestStage": "Request"
                        }
                    ]
                })
                logger.info("✅ Fetch 域已启用（底层 WebSocket 拦截）")

                # 监听 Fetch 请求暂停事件
                self.cdp_session.on("Fetch.requestPaused", self._on_fetch_request_paused)
                logger.debug("Fetch.requestPaused 监听器已注册")

            except Exception as e:
                logger.warning(f"启用 Fetch 域失败（非致命错误）: {e}")

            # 监听控制台输出（捕获 JavaScript 的 console.log）
            self.cdp_session.on("Runtime.consoleAPICalled", self._on_console_api)
            logger.debug("Console API 监听器已注册")

            # ============================================================
            # 【重要】监听HTTP响应，捕获历史消息API
            # ============================================================
            # 闲鱼在打开聊天窗口时会通过HTTP API加载历史消息
            # 我们需要监听这些API响应并提取历史消息
            # ============================================================
            self.cdp_session.on("Network.responseReceived", self._on_response_received)
            self.cdp_session.on("Network.loadingFinished", self._on_loading_finished)
            logger.info("✅ 历史消息API监听器已启用（调试模式）")

            # 启用 Runtime 域（用于执行 JavaScript）
            await self.cdp_session.send("Runtime.enable")
            logger.debug("Runtime 域已启用")

            self._is_monitoring = True
            self._is_setup = True  # 标记已设置完成
            logger.info("CDP 监控设置成功")
            return True

        except Exception as e:
            logger.error(f"CDP 监控设置失败: {e}")
            return False

    def set_message_callback(self, callback: Callable[[Dict[str, Any]], None]) -> None:
        """
        设置消息回调函数

        Args:
            callback: 收到 WebSocket 消息时调用的回调函数
        """
        self.message_callback = callback

    async def _on_fetch_request_paused(self, params: Dict[str, Any]) -> None:
        """
        Fetch 请求暂停事件处理（底层网络拦截）

        这个方法会拦截所有 WebSocket 握手请求，即使在跨域 iframe 中也能捕获。

        Args:
            params: 事件参数
        """
        try:
            request_id = params.get("requestId")
            request = params.get("request", {})
            url = request.get("url", "")
            resource_type = params.get("resourceType", "")

            # 检查是否是 WebSocket 请求
            if url.startswith("wss://") or url.startswith("ws://"):
                logger.info(f"🚀 Fetch 域拦截到 WebSocket 请求: {url}")
                logger.debug(f"   资源类型: {resource_type}")
                logger.debug(f"   请求 ID: {request_id}")

                # 检查是否是闲鱼的 WebSocket
                is_xianyu = any(domain in url for domain in [
                    "wss-goofish.dingtalk.com",
                    "msgacs.m.taobao.com",
                    "wss.goofish.com"
                ])
                if is_xianyu:
                    self.websocket_id = f"fetch_{request_id}"
                    logger.info(f"✅ 通过 Fetch 域检测到闲鱼 WebSocket: {url}")

            # 继续请求（不阻止）
            try:
                await self.cdp_session.send("Fetch.continueRequest", {
                    "requestId": request_id
                })
            except Exception as e:
                logger.debug(f"继续 Fetch 请求失败: {e}")

        except Exception as e:
            logger.error(f"处理 Fetch 请求暂停事件失败: {e}")

    async def _on_websocket_created(self, params: Dict[str, Any]) -> None:
        """
        WebSocket 创建事件处理

        Args:
            params: 事件参数
        """
        try:
            request_id = params.get("requestId")
            url = params.get("url")

            logger.debug(f"捕获到 WebSocket 创建: {url}")

            # 检查是否是闲鱼的 WebSocket
            is_xianyu = any(domain in url for domain in [
                "wss-goofish.dingtalk.com",
                "msgacs.m.taobao.com",
                "wss.goofish.com"
            ])
            if is_xianyu:
                self.websocket_id = request_id
                logger.info(f"✅ 检测到闲鱼 WebSocket 连接: {url}")
                logger.info(f"WebSocket ID: {self.websocket_id}")
            else:
                logger.debug(f"非闲鱼 WebSocket，忽略: {url}")

        except Exception as e:
            logger.error(f"处理 WebSocket 创建事件失败: {e}")

    async def _on_frame_received(self, params: Dict[str, Any]) -> None:
        """
        WebSocket 接收帧事件处理

        Args:
            params: 事件参数
        """
        try:
            request_id = params.get("requestId")

            # 只处理闲鱼的 WebSocket
            if request_id != self.websocket_id:
                return

            response = params.get("response", {})
            payload = response.get("payloadData")

            if payload:
                # 解析消息
                try:
                    message_data = json.loads(payload)
                    logger.debug(f"收到 WebSocket 消息 (通过 CDP)")

                    # 调用回调函数
                    if self.message_callback:
                        await asyncio.create_task(self._safe_callback(message_data))

                except json.JSONDecodeError:
                    logger.debug("非 JSON 格式的 WebSocket 消息")

        except Exception as e:
            logger.error(f"处理 WebSocket 接收帧失败: {e}")

    async def _on_frame_sent(self, params: Dict[str, Any]) -> None:
        """
        WebSocket 发送帧事件处理（用于调试）

        Args:
            params: 事件参数
        """
        try:
            request_id = params.get("requestId")

            if request_id == self.websocket_id:
                response = params.get("response", {})
                payload = response.get("payloadData")
                logger.debug(f"发送 WebSocket 消息 (通过 CDP)")

        except Exception as e:
            logger.debug(f"处理 WebSocket 发送帧失败: {e}")

    async def _on_console_api(self, params: Dict[str, Any]) -> None:
        """
        Console API 事件处理（捕获 JavaScript console.log）

        Args:
            params: 事件参数
        """
        try:
            console_type = params.get("type", "")
            args = params.get("args", [])

            # 处理 console.error
            if console_type == "error" and len(args) > 0:
                first_arg = args[0].get("value", "")
                if first_arg == "[CDP_SEND_ERROR]" and len(args) > 1:
                    error_msg = args[1].get("value", "") if len(args) > 1 else ""
                    logger.error(f"❌ CDP发送错误: {error_msg}")
                return

            if console_type == "log" and len(args) > 0:
                first_arg = args[0].get("value", "")
                # ============================================================
                # 【重要】确保 first_arg 是字符串
                # ============================================================
                # console.log 的参数可能是数字、对象等，不一定是字符串
                # 如果不转换，调用 .startswith() 会报错
                # ============================================================
                first_arg_str = str(first_arg) if first_arg is not None else ""

                # 检测 WebSocket 拦截器输出
                if first_arg_str == "[WS_INTERCEPTOR_READY]":
                    logger.info("✅ JavaScript WebSocket 拦截器就绪（主窗口）")
                elif first_arg_str == "[WS_PRIMARY]" and len(args) > 1:
                    url = args[1].get("value", "")
                    logger.info(f"⭐ 主 WebSocket 已设置: {url}")
                elif first_arg_str == "[WS_CREATED]" and len(args) > 1:
                    url = args[1].get("value", "")
                    logger.info(f"📡 JavaScript 检测到 WebSocket 创建（主窗口）: {url}")

                    # 如果是闲鱼的 WebSocket，标记为已连接
                    is_xianyu = any(domain in url for domain in [
                        "wss-goofish.dingtalk.com",
                        "msgacs.m.taobao.com",
                        "wss.goofish.com"
                    ])
                    if is_xianyu:
                        self.websocket_id = "from_javascript"
                        logger.info(f"✅ 通过 JavaScript 检测到闲鱼 WebSocket: {url}")
                elif first_arg_str == "[WS_OPENED]" and len(args) > 1:
                    url = args[1].get("value", "")
                    logger.info(f"🔗 WebSocket 已连接（主窗口）: {url}")
                elif first_arg_str == "[WS_MESSAGE_RECEIVED]" and len(args) > 1:
                    # 接收到 WebSocket 消息
                    message_data_str = args[1].get("value", "")

                    # 判断是否为心跳或系统消息
                    is_heartbeat = False
                    try:
                        msg_data = json.loads(message_data_str)
                        # 心跳响应: {"headers":{...},"code":200}
                        # 或者只有 code 和 headers 的消息
                        if msg_data.get("code") == 200 and "body" not in msg_data:
                            is_heartbeat = True
                    except:
                        pass

                    # 检查是否是历史消息相关的关键API响应
                    is_history_api = False
                    history_api_keywords = [
                        "MessageManager/listUserMessages",
                        "Message/query",
                        "Message/getHistory",
                        "Conversation/getByCids",
                        "Conversation/listTop",
                        "Conversation/list"
                    ]

                    for keyword in history_api_keywords:
                        if keyword in message_data_str:
                            is_history_api = True
                            break

                    if is_heartbeat:
                        logger.debug(f"📥 心跳响应: {message_data_str[:80]}...")
                    elif is_history_api:
                        # 完整记录历史消息API响应
                        logger.info(f"📜 [历史API响应] 检测到历史消息相关的WebSocket响应:")
                        if len(message_data_str) > 5000:
                            logger.info(f"   消息长度: {len(message_data_str)} 字节")
                            logger.info(f"   前5000字符: {message_data_str[:5000]}")
                            logger.info(f"   ... (已截断)")
                        else:
                            logger.info(f"   完整消息: {message_data_str}")
                    else:
                        logger.info(f"📥 收到消息: {message_data_str[:100]}...")

                    # 解析并调用回调
                    try:
                        message_data = json.loads(message_data_str)
                        if self.message_callback:
                            await self._safe_callback(message_data)
                    except json.JSONDecodeError:
                        logger.debug("非 JSON 格式的 WebSocket 消息")
                elif first_arg_str == "[WS_MESSAGE_SENT]" and len(args) > 1:
                    # 发送的 WebSocket 消息
                    message_data_str = args[1].get("value", "")

                    # 判断是否为心跳或 ACK 消息
                    is_system_msg = False
                    is_history_api_request = False

                    try:
                        msg_data = json.loads(message_data_str)
                        # 心跳: {"lwp":"/!","headers":{...}}
                        # ACK: {"type":"ACK","protocol":"HEARTBEAT_ACCS_H5",...}
                        if msg_data.get("lwp") == "/!" or msg_data.get("type") == "ACK":
                            is_system_msg = True

                        # 检查是否是历史消息API请求
                        lwp = msg_data.get("lwp", "")
                        for keyword in history_api_keywords:
                            if keyword in lwp:
                                is_history_api_request = True
                                break
                    except:
                        pass

                    if is_system_msg:
                        logger.debug(f"📤 系统消息: {message_data_str[:80]}...")
                    elif is_history_api_request:
                        # 完整记录历史消息API请求
                        logger.info(f"📤 [历史API请求] 发送历史消息查询请求:")
                        if len(message_data_str) > 2000:
                            logger.info(f"   消息长度: {len(message_data_str)} 字节")
                            logger.info(f"   前2000字符: {message_data_str[:2000]}")
                        else:
                            logger.info(f"   完整请求: {message_data_str}")
                    else:
                        logger.debug(f"📤 发送消息: {message_data_str[:100]}...")
                elif first_arg_str.startswith("[CDP_SEND_"):
                    # CDP 发送调试信息
                    if len(args) > 1:
                        logger.debug(f"🔧 {first_arg_str}: {args[1].get('value', '')}")
                    else:
                        logger.debug(f"🔧 {first_arg_str}")
                elif first_arg_str == "[WS_CREATED_IN_IFRAME]" and len(args) > 2:
                    iframe_name = args[1].get("value", "")
                    url = args[2].get("value", "")
                    logger.info(f"📡 JavaScript 检测到 WebSocket 创建（iframe: {iframe_name}）: {url}")

                    # 如果是闲鱼的 WebSocket，标记为已连接
                    is_xianyu = any(domain in url for domain in [
                        "wss-goofish.dingtalk.com",
                        "msgacs.m.taobao.com",
                        "wss.goofish.com"
                    ])
                    if is_xianyu:
                        self.websocket_id = f"from_javascript_iframe_{iframe_name}"
                        logger.info(f"✅ 通过 JavaScript 在 iframe 中检测到闲鱼 WebSocket: {url}")
                elif first_arg_str == "[WS_OPENED_IN_IFRAME]" and len(args) > 2:
                    iframe_name = args[1].get("value", "")
                    url = args[2].get("value", "")
                    logger.info(f"🔗 WebSocket 已连接（iframe: {iframe_name}）: {url}")
                else:
                    # 其他 console.log
                    logger.debug(f"Console: {first_arg_str}")

        except Exception as e:
            logger.error(f"处理 Console API 事件失败: {e}")

    async def _on_websocket_closed(self, params: Dict[str, Any]) -> None:
        """
        WebSocket 关闭事件处理

        Args:
            params: 事件参数
        """
        try:
            request_id = params.get("requestId")

            if request_id == self.websocket_id:
                logger.warning("WebSocket 连接已关闭")
                self.websocket_id = None

        except Exception as e:
            logger.error(f"处理 WebSocket 关闭事件失败: {e}")

    async def _safe_callback(self, message_data: Dict[str, Any]) -> None:
        """
        安全地调用回调函数

        Args:
            message_data: 消息数据
        """
        try:
            if self.message_callback:
                # 如果回调是协程函数
                if asyncio.iscoroutinefunction(self.message_callback):
                    await self.message_callback(message_data)
                else:
                    self.message_callback(message_data)
        except Exception as e:
            logger.error(f"消息回调执行失败: {e}")

    async def send_message(self, message_data: Dict[str, Any]) -> bool:
        """
        通过浏览器的 WebSocket 连接发送消息

        Args:
            message_data: 要发送的消息数据

        Returns:
            bool: 发送是否成功
        """
        try:
            if not self.websocket_id:
                logger.error("WebSocket 未连接")
                return False

            # 将消息转换为 JSON 字符串
            message_json = json.dumps(message_data, ensure_ascii=False)
            logger.debug(f"准备发送消息: {message_json[:200]}...")

            # 构造 JavaScript 代码来发送消息
            # 使用 Symbol 访问保存的 WebSocket 实例
            js_code = f"""
            (function() {{
                try {{
                    // 使用 Symbol 获取 WebSocket 实例
                    const wsSymbol = Symbol.for('_ws_');
                    const wsArraySymbol = Symbol.for('_ws_array_');
                    const wsInstance = window[wsSymbol];
                    const wsArray = window[wsArraySymbol] || [];

                    console.log('[CDP_SEND_DEBUG] WebSocket实例存在:', !!wsInstance);
                    console.log('[CDP_SEND_DEBUG] WebSocket数组长度:', wsArray.length);

                    if (wsInstance) {{
                        console.log('[CDP_SEND_DEBUG] 主WebSocket readyState:', wsInstance.readyState);
                        console.log('[CDP_SEND_DEBUG] 主WebSocket URL:', wsInstance.url);
                    }}

                    // 列出所有 WebSocket
                    wsArray.forEach((item, idx) => {{
                        console.log('[CDP_SEND_DEBUG] WS[' + idx + '] URL:', item.url);
                        console.log('[CDP_SEND_DEBUG] WS[' + idx + '] readyState:', item.ws.readyState);
                    }});

                    // 使用已保存的实例发送
                    if (wsInstance && wsInstance.readyState === 1) {{
                        const messageToSend = {json.dumps(message_json)};
                        console.log('[CDP_SEND_DEBUG] 准备发送消息:', messageToSend.substring(0, 100));
                        wsInstance.send(messageToSend);
                        console.log('[CDP_SEND_DEBUG] 消息已通过主WebSocket发送');
                        return {{ success: true, message: 'sent_via_primary', url: wsInstance.url }};
                    }}

                    return {{
                        success: false,
                        message: wsInstance ? 'readyState=' + wsInstance.readyState : 'no instance'
                    }};
                }} catch(e) {{
                    console.error('[CDP_SEND_ERROR]', e);
                    return {{ success: false, message: e.toString() }};
                }}
            }})();
            """

            # 执行 JavaScript
            result = await self.cdp_session.send("Runtime.evaluate", {
                "expression": js_code,
                "returnByValue": True
            })

            # 检查返回结果
            js_result = result.get("result", {}).get("value", {})

            if isinstance(js_result, dict) and js_result.get("success"):
                ws_url = js_result.get('url', 'unknown')
                logger.info(f"✅ 消息发送成功 (通过 CDP): {js_result.get('message')}")
                logger.info(f"   使用的 WebSocket: {ws_url}")
                return True
            else:
                error_msg = js_result.get("message", "unknown") if isinstance(js_result, dict) else str(js_result)
                logger.error(f"❌ 消息发送失败: {error_msg}")
                return False

        except Exception as e:
            logger.error(f"通过 CDP 发送消息失败: {e}")
            return False

    async def inject_websocket_interceptor(self) -> bool:
        """
        注入 WebSocket 拦截器（JavaScript 方式）

        【重要】此方法在页面中注入 JavaScript 代码来拦截 WebSocket
        - 拦截 window.WebSocket 构造函数
        - 监听 WebSocket 的创建、连接、消息事件
        - 通过 console.log 将事件传递给 CDP

        为什么需要这个：
        - CDP 事件可能丢失或延迟
        - JavaScript 可以拦截 onmessage 和 send 方法
        - 提供额外的调试信息

        【注意】无法访问跨域 iframe，但 CDP 可以

        Returns:
            bool: 注入是否成功
        """
        try:
            # 使用更隐蔽的 JavaScript 注入方式
            # - 主要使用 Symbol 存储（难以被检测）
            # - 同时设置旧变量名（用于检测代码向后兼容）
            # - 拦截消息收发
            js_code = """
(function() {
    // 使用 Symbol 作为主要存储方式（更隐蔽）
    const wsSymbol = Symbol.for('_ws_');
    const injectedSymbol = Symbol.for('_inj_');

    if (window[injectedSymbol]) return;

    const OriginalWebSocket = window.WebSocket;

    window.WebSocket = class extends OriginalWebSocket {
        constructor(...args) {
            super(...args);
            const url = args[0];

            // 保存 WebSocket 实例（双重存储：Symbol + 旧变量名）
            window[wsSymbol] = this;
            window.__xianyuWebSocket = this;  // 向后兼容检测代码

            // 闲鱼可能使用多个 WebSocket 服务器
            const isXianyuWs = url && (
                url.includes('wss-goofish.dingtalk.com') ||
                url.includes('msgacs.m.taobao.com') ||
                url.includes('wss.goofish.com')
            );

            if (isXianyuWs) {
                console.log('[WS_CREATED]', url);

                // 拦截消息接收：使用 addEventListener 确保捕获所有消息
                // （闲鱼使用 ws.addEventListener('message', fn) 而非 ws.onmessage = fn，
                //   Object.defineProperty 无法拦截 addEventListener 方式）
                this.addEventListener('message', function(event) {
                    console.log('[WS_MESSAGE_RECEIVED]', event.data);
                });

                // 同时也拦截 onmessage setter，兼容两种注册方式
                Object.defineProperty(this, 'onmessage', {
                    set: function(handler) {
                        this._onmessageHandler = handler;
                        OriginalWebSocket.prototype.__lookupSetter__('onmessage') &&
                            OriginalWebSocket.prototype.__lookupSetter__('onmessage').call(this, handler);
                    },
                    get: function() {
                        return this._onmessageHandler;
                    }
                });

                // 拦截 send（发送消息）
                const originalSend = this.send;
                this.send = function(data) {
                    console.log('[WS_MESSAGE_SENT]', data);
                    return originalSend.call(this, data);
                };

                this.addEventListener('open', () => {
                    console.log('[WS_OPENED]', url);
                });

                this.addEventListener('close', (event) => {
                    console.log('[WS_CLOSED]', url, 'code=' + event.code, 'reason=' + event.reason);
                });

                this.addEventListener('error', (event) => {
                    console.log('[WS_ERROR]', url);
                });
            }

            return this;
        }
    };

    // 双重标记
    window[injectedSymbol] = true;
    window.__wsInterceptorInjected = true;  // 向后兼容检测代码
    console.log('[WS_INTERCEPTOR_READY]');
})();
            """

            # 使用 Page.addScriptToEvaluateOnNewDocument 确保脚本在页面加载前执行
            # 这样可以捕获页面加载时创建的 WebSocket
            await self.cdp_session.send("Page.enable")
            result = await self.cdp_session.send("Page.addScriptToEvaluateOnNewDocument", {
                "source": js_code
            })
            logger.debug(f"addScriptToEvaluateOnNewDocument 返回: {result}")

            # 同时也在当前页面立即执行一次（处理已加载的页面）
            try:
                eval_result = await self.cdp_session.send("Runtime.evaluate", {
                    "expression": js_code
                })

                # 检查是否有执行错误
                if "exceptionDetails" in eval_result:
                    logger.error(f"❌ JavaScript 注入失败: {eval_result['exceptionDetails']}")
                    return False

                logger.debug(f"Runtime.evaluate 执行结果: {eval_result}")

                # 在所有 iframe 中也注入拦截器
                inject_in_iframes_code = """
(function() {
    const iframes = document.querySelectorAll('iframe');
    let injectedCount = 0;

    for (let i = 0; i < iframes.length; i++) {
        try {
            const iframe = iframes[i];
            const iframeWin = iframe.contentWindow;

            if (iframeWin && !iframeWin.__wsInterceptorInjected) {
                const originalWebSocket = iframeWin.WebSocket;

                iframeWin.WebSocket = function(...args) {
                    const ws = new originalWebSocket(...args);
                    const url = args[0];

                    iframeWin.__xianyuWebSocket = ws;
                    console.log('[WS_CREATED_IN_IFRAME]', iframe.name || iframe.id || `iframe_${i}`, url);

                    ws.addEventListener('open', () => {
                        console.log('[WS_OPENED_IN_IFRAME]', iframe.name || iframe.id || `iframe_${i}`, url);
                    });

                    return ws;
                };

                iframeWin.WebSocket.prototype = originalWebSocket.prototype;
                iframeWin.__wsInterceptorInjected = true;
                injectedCount++;
            }
        } catch(e) {
            // 跨域 iframe 无法访问
        }
    }

    return { iframeCount: iframes.length, injectedCount: injectedCount };
})();
                """

                iframe_inject_result = await self.cdp_session.send("Runtime.evaluate", {
                    "expression": inject_in_iframes_code,
                    "returnByValue": True
                })
                iframe_data = iframe_inject_result.get("result", {}).get("value", {})
                if iframe_data.get("iframeCount", 0) > 0:
                    logger.info(f"📝 在 {iframe_data.get('injectedCount', 0)}/{iframe_data.get('iframeCount', 0)} 个 iframe 中注入拦截器")

                # 验证注入是否成功
                verify_code = """
(function() {
    return {
        interceptorInjected: window.__wsInterceptorInjected || false,
        xianyuWsExists: !!window.__xianyuWebSocket,
        webSocketConstructor: typeof window.WebSocket === 'function'
    };
})();
                """
                verify_result = await self.cdp_session.send("Runtime.evaluate", {
                    "expression": verify_code,
                    "returnByValue": True
                })
                verify_data = verify_result.get("result", {}).get("value", {})
                logger.info(f"📝 主窗口拦截器验证: {verify_data}")

            except Exception as e:
                logger.warning(f"在当前页面执行拦截器失败: {e}")

            logger.info("✅ WebSocket 拦截器注入成功")
            return True

        except Exception as e:
            logger.error(f"注入 WebSocket 拦截器失败: {e}")
            return False

    def is_connected(self) -> bool:
        """
        检查 WebSocket 是否已连接

        Returns:
            bool: 是否已连接
        """
        return self.websocket_id is not None

    async def check_websocket_in_page(self) -> bool:
        """
        主动检查页面中是否存在 WebSocket 连接

        Returns:
            bool: 是否检测到 WebSocket
        """
        try:
            # 执行 JavaScript 检查页面中的 WebSocket（包括 iframe）
            js_code = """
(function() {
    const result = {
        found: false,
        injectorPresent: window.__wsInterceptorInjected || false,
        xianyuWsExists: !!window.__xianyuWebSocket,
        performanceEntries: [],
        debugInfo: {
            iframeCount: 0,
            iframeResults: []
        }
    };

    // 辅助函数：在指定窗口中查找 WebSocket
    function findWebSocketInWindow(win, frameName) {
        const frameResult = {
            frameName: frameName,
            injectorPresent: false,
            xianyuWsExists: false,
            wsEntries: [],
            windowWs: []
        };

        try {
            // 检查注入的变量
            frameResult.injectorPresent = win.__wsInterceptorInjected || false;
            frameResult.xianyuWsExists = !!win.__xianyuWebSocket;

            if (win.__xianyuWebSocket && win.__xianyuWebSocket.readyState !== undefined) {
                return {
                    found: true,
                    url: win.__xianyuWebSocket.url,
                    readyState: win.__xianyuWebSocket.readyState,
                    method: 'injected',
                    frameName: frameName
                };
            }

            // 检查性能 API
            try {
                const entries = win.performance.getEntriesByType('resource');
                for (const entry of entries) {
                    if (entry.name.includes('wss://') || entry.name.includes('ws://')) {
                        frameResult.wsEntries.push(entry.name);
                    }
                }

                if (frameResult.wsEntries.length > 0) {
                    return {
                        found: true,
                        url: frameResult.wsEntries[0],
                        readyState: -1,
                        method: 'performance',
                        frameName: frameName
                    };
                }
            } catch(e) {
                // 性能 API 可能不可用
            }

            // 扫描 window 对象
            for (const key in win) {
                try {
                    if (win[key] instanceof WebSocket) {
                        frameResult.windowWs.push({
                            key: key,
                            url: win[key].url,
                            readyState: win[key].readyState
                        });
                    }
                } catch(e) {
                    // 忽略
                }
            }

            if (frameResult.windowWs.length > 0) {
                return {
                    found: true,
                    url: frameResult.windowWs[0].url,
                    readyState: frameResult.windowWs[0].readyState,
                    method: 'window_scan',
                    frameName: frameName
                };
            }
        } catch(e) {
            frameResult.error = e.message;
        }

        return frameResult;
    }

    // 检查主窗口
    const mainResult = findWebSocketInWindow(window, 'main');
    if (mainResult.found) {
        return mainResult;
    }
    result.debugInfo.mainFrame = mainResult;

    // 检查所有 iframe
    const iframes = document.querySelectorAll('iframe');
    result.debugInfo.iframeCount = iframes.length;

    for (let i = 0; i < iframes.length; i++) {
        try {
            const iframe = iframes[i];
            const iframeName = iframe.name || iframe.id || `iframe_${i}`;
            const iframeWin = iframe.contentWindow;

            if (iframeWin) {
                const iframeResult = findWebSocketInWindow(iframeWin, iframeName);
                if (iframeResult.found) {
                    return iframeResult;
                }
                result.debugInfo.iframeResults.push(iframeResult);
            }
        } catch(e) {
            // 跨域 iframe 无法访问
            result.debugInfo.iframeResults.push({
                frameName: `iframe_${i}`,
                error: 'Cross-origin or access denied'
            });
        }
    }

    // 收集主窗口的性能数据（向后兼容）
    const entries = performance.getEntriesByType('resource');
    result.debugInfo.totalResources = entries.length;

    for (const entry of entries) {
        if (entry.name.includes('wss://') || entry.name.includes('ws://')) {
            result.performanceEntries.push(entry.name);
        }
    }

    return result;
})();
            """

            result = await self.cdp_session.send("Runtime.evaluate", {
                "expression": js_code,
                "returnByValue": True
            })

            # 获取 JavaScript 返回的结果
            js_result = result.get("result", {}).get("value", {})

            # 记录详细的诊断信息
            debug_info = js_result.get('debugInfo', {})
            iframe_count = debug_info.get('iframeCount', 0)

            logger.debug(f"🔍 WebSocket 主动检测结果:")
            logger.debug(f"   - 主窗口拦截器是否注入: {js_result.get('injectorPresent', False)}")
            logger.debug(f"   - 主窗口 __xianyuWebSocket 是否存在: {js_result.get('xianyuWsExists', False)}")
            logger.debug(f"   - 页面中 iframe 数量: {iframe_count}")

            # 如果有 iframe，显示 iframe 的检测结果
            if iframe_count > 0:
                iframe_results = debug_info.get('iframeResults', [])
                logger.debug(f"   - iframe 检测结果:")
                for iframe_result in iframe_results:
                    frame_name = iframe_result.get('frameName', 'unknown')
                    if 'error' in iframe_result:
                        logger.debug(f"     * {frame_name}: {iframe_result['error']}")
                    else:
                        injected = iframe_result.get('injectorPresent', False)
                        has_ws = iframe_result.get('xianyuWsExists', False)
                        ws_count = len(iframe_result.get('wsEntries', []))
                        logger.debug(f"     * {frame_name}: 注入={injected}, WS变量={has_ws}, 性能API找到={ws_count}个")

            logger.debug(f"   - Performance API 发现的 WS: {js_result.get('performanceEntries', [])}")
            logger.debug(f"   - 总资源数: {debug_info.get('totalResources', 0)}")

            if js_result.get("found"):
                url = js_result.get("url", "")
                method = js_result.get("method", "unknown")
                ready_state = js_result.get("readyState", -1)
                frame_name = js_result.get("frameName", "unknown")

                logger.info(f"🔍 主动检测到 WebSocket: {url}")
                logger.info(f"   检测方法: {method}")
                logger.info(f"   所在框架: {frame_name}")
                logger.info(f"   连接状态: {ready_state} (0=CONNECTING, 1=OPEN, 2=CLOSING, 3=CLOSED)")

                # 如果是闲鱼的 WebSocket，标记为已连接
                is_xianyu = any(domain in url for domain in [
                    "wss-goofish.dingtalk.com",
                    "msgacs.m.taobao.com",
                    "wss.goofish.com"
                ])
                if is_xianyu:
                    self.websocket_id = f"detected_{method}"
                    logger.info(f"✅ 主动检测成功: {url}")
                    return True
                else:
                    logger.debug(f"检测到 WebSocket 但不是闲鱼的: {url}")
            else:
                logger.debug("❌ 未检测到任何 WebSocket 连接")

            return False

        except Exception as e:
            logger.error(f"主动检测 WebSocket 失败: {e}")
            import traceback
            logger.debug(f"错误堆栈: {traceback.format_exc()}")
            return False

    async def _on_response_received(self, params: Dict[str, Any]) -> None:
        """
        HTTP响应接收事件处理（调试模式）

        监听所有闲鱼相关的API响应，用于分析历史消息API的格式

        Args:
            params: 响应事件参数
        """
        try:
            response = params.get("response", {})
            url = response.get("url", "")
            request_id = params.get("requestId")

            # 只处理闲鱼的API
            if "goofish.com" not in url and "taobao.com" not in url:
                return

            # 检查是否是消息相关API
            is_message_api = any(keyword in url.lower() for keyword in [
                "message",
                "conversation",
                "chat",
                "idlemessage",
                "history",
                "query",
                "list",
                "sync"
            ])

            if is_message_api:
                logger.info(f"🔍 [调试] 检测到闲鱼消息相关API:")
                logger.info(f"   URL: {url}")
                logger.info(f"   状态码: {response.get('status')}")
                logger.info(f"   Content-Type: {response.get('mimeType')}")

                # 保存请求ID，等待响应体加载完成
                import time
                self._pending_history_requests[request_id] = {
                    "url": url,
                    "timestamp": time.time(),
                    "status": response.get("status"),
                    "mime_type": response.get("mimeType")
                }

        except Exception as e:
            logger.error(f"处理响应接收事件失败: {e}")

    async def _on_loading_finished(self, params: Dict[str, Any]) -> None:
        """
        资源加载完成事件处理（调试模式）

        获取响应体并记录，用于分析历史消息API的数据格式

        Args:
            params: 加载完成事件参数
        """
        try:
            request_id = params.get("requestId")

            # 检查是否是我们关注的消息API
            if request_id not in self._pending_history_requests:
                return

            request_info = self._pending_history_requests.pop(request_id)
            logger.info(f"📥 [调试] 正在获取API响应体...")
            logger.info(f"   URL: {request_info['url'][:100]}")

            try:
                # 获取响应体
                response_body = await self.cdp_session.send(
                    "Network.getResponseBody",
                    {"requestId": request_id}
                )

                body_text = response_body.get("body", "")
                if not body_text:
                    logger.warning(f"   响应体为空")
                    return

                # 记录响应体（限制长度避免日志过大）
                logger.info(f"📄 [调试] API响应内容:")
                logger.info(f"   长度: {len(body_text)} 字节")

                # 尝试解析JSON
                try:
                    import json
                    response_json = json.loads(body_text)

                    # 美化输出JSON（限制深度和长度）
                    json_preview = json.dumps(response_json, ensure_ascii=False, indent=2)
                    if len(json_preview) > 3000:
                        json_preview = json_preview[:3000] + "\n... (响应太长，已截断)"

                    logger.info(f"   JSON内容:")
                    for line in json_preview.split('\n'):
                        logger.info(f"   {line}")

                    # 尝试识别消息数据结构
                    self._analyze_message_structure(response_json, request_info["url"])

                except json.JSONDecodeError:
                    logger.info(f"   响应不是JSON格式")
                    # 显示前500个字符
                    preview = body_text[:500]
                    if len(body_text) > 500:
                        preview += "... (已截断)"
                    logger.info(f"   内容: {preview}")

            except Exception as get_error:
                logger.warning(f"   获取响应体失败: {get_error}")

        except Exception as e:
            logger.error(f"处理加载完成事件失败: {e}")

    def _analyze_message_structure(self, data: Dict[str, Any], url: str) -> None:
        """
        分析消息数据结构（调试辅助）

        Args:
            data: API响应数据
            url: API URL
        """
        try:
            logger.info(f"🔬 [调试] 数据结构分析:")

            # 分析顶层字段
            logger.info(f"   顶层字段: {list(data.keys())}")

            # 常见的消息列表字段名
            possible_message_fields = [
                "messages", "messageList", "conversationMessages",
                "chatMessages", "historyMessages", "data", "sessions",
                "conversations", "list", "items", "records"
            ]

            # 递归查找可能包含消息的字段
            def find_message_arrays(obj, path="", depth=0, max_depth=5):
                if depth > max_depth:
                    return

                if isinstance(obj, dict):
                    for key, value in obj.items():
                        current_path = f"{path}.{key}" if path else key

                        # 检查是否是消息相关字段
                        if any(field in key.lower() for field in possible_message_fields):
                            if isinstance(value, list) and len(value) > 0:
                                logger.info(f"   ✅ 发现可能的消息列表: {current_path}")
                                logger.info(f"      - 长度: {len(value)}")
                                if isinstance(value[0], dict):
                                    logger.info(f"      - 第一项字段: {list(value[0].keys())}")
                                    # 记录第一项的样本数据（用于判断是否是历史消息）
                                    import json
                                    sample = json.dumps(value[0], ensure_ascii=False, indent=6)
                                    if len(sample) > 500:
                                        sample = sample[:500] + "..."
                                    logger.info(f"      - 第一项样本数据:")
                                    for line in sample.split('\n'):
                                        logger.info(f"         {line}")

                        # 递归搜索
                        find_message_arrays(value, current_path, depth + 1)

                elif isinstance(obj, list) and len(obj) > 0:
                    # 检查列表的第一项
                    if isinstance(obj[0], dict):
                        # 检查是否包含消息特征字段
                        message_indicators = ["content", "text", "message", "senderId", "userId", "msg", "chat"]
                        first_item_keys = list(obj[0].keys())
                        matches = [key for key in first_item_keys if any(ind in key.lower() for ind in message_indicators)]

                        if matches:
                            logger.info(f"   ✅ 发现可能的消息列表: {path}")
                            logger.info(f"      - 长度: {len(obj)}")
                            logger.info(f"      - 第一项字段: {first_item_keys}")
                            logger.info(f"      - 匹配的消息字段: {matches}")
                            # 记录第一项的样本数据
                            import json
                            sample = json.dumps(obj[0], ensure_ascii=False, indent=6)
                            if len(sample) > 500:
                                sample = sample[:500] + "..."
                            logger.info(f"      - 第一项样本数据:")
                            for line in sample.split('\n'):
                                logger.info(f"         {line}")

            find_message_arrays(data)

        except Exception as e:
            logger.debug(f"分析数据结构失败: {e}")

    async def close(self) -> None:
        """关闭 CDP 拦截器"""
        try:
            self._is_monitoring = False
            logger.info("CDP 拦截器已关闭")
        except Exception as e:
            logger.error(f"关闭 CDP 拦截器失败: {e}")
