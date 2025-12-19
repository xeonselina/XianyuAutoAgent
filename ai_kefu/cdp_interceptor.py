"""
CDP 拦截器模块

使用 Chrome DevTools Protocol 拦截和注入 WebSocket 消息。
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

    async def setup(self) -> bool:
        """
        设置 CDP 监控

        Returns:
            bool: 设置是否成功
        """
        try:
            logger.info("正在设置 CDP WebSocket 监控...")

            # 启用 Network 域
            await self.cdp_session.send("Network.enable")

            # 订阅 WebSocket 事件
            self.cdp_session.on("Network.webSocketCreated", self._on_websocket_created)
            self.cdp_session.on("Network.webSocketFrameReceived", self._on_frame_received)
            self.cdp_session.on("Network.webSocketFrameSent", self._on_frame_sent)
            self.cdp_session.on("Network.webSocketClosed", self._on_websocket_closed)

            # 启用 Runtime 域（用于执行 JavaScript）
            await self.cdp_session.send("Runtime.enable")

            # 启用 Console 域（用于监控控制台日志）
            await self.cdp_session.send("Runtime.consoleAPICalled")

            self._is_monitoring = True
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

    async def _on_websocket_created(self, params: Dict[str, Any]) -> None:
        """
        WebSocket 创建事件处理

        Args:
            params: 事件参数
        """
        try:
            request_id = params.get("requestId")
            url = params.get("url")

            # 检查是否是闲鱼的 WebSocket
            if "wss-goofish.dingtalk.com" in url or "wss://wss-goofish.dingtalk.com" in url:
                self.websocket_id = request_id
                logger.info(f"检测到闲鱼 WebSocket 连接: {url}")
                logger.info(f"WebSocket ID: {self.websocket_id}")

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

            # 构造 JavaScript 代码来发送消息
            # 注意：这里使用了一个技巧，通过查找页面上的 WebSocket 实例
            js_code = f"""
            (function() {{
                // 查找 WebSocket 实例
                const wsSend = WebSocket.prototype.send;
                let wsInstance = null;

                // 劫持 send 方法来获取实例（如果还没有）
                if (!window.__xianyuWebSocket) {{
                    WebSocket.prototype.send = function(...args) {{
                        window.__xianyuWebSocket = this;
                        WebSocket.prototype.send = wsSend;
                        return wsSend.apply(this, args);
                    }};
                }}

                // 使用已保存的实例发送
                if (window.__xianyuWebSocket && window.__xianyuWebSocket.readyState === 1) {{
                    window.__xianyuWebSocket.send({json.dumps(message_json)});
                    return true;
                }}
                return false;
            }})();
            """

            # 执行 JavaScript
            result = await self.cdp_session.send("Runtime.evaluate", {
                "expression": js_code,
                "returnByValue": True
            })

            if result.get("result", {}).get("value"):
                logger.debug("消息发送成功 (通过 CDP)")
                return True
            else:
                logger.error("消息发送失败: WebSocket 未就绪")
                return False

        except Exception as e:
            logger.error(f"通过 CDP 发送消息失败: {e}")
            return False

    async def inject_websocket_interceptor(self) -> bool:
        """
        注入 WebSocket 拦截器（备用方案）

        这个方法会在页面中注入 JavaScript 来拦截 WebSocket 实例。

        Returns:
            bool: 注入是否成功
        """
        try:
            js_code = """
            (function() {
                if (window.__wsInterceptorInjected) return;

                const originalWebSocket = window.WebSocket;

                window.WebSocket = function(...args) {
                    const ws = new originalWebSocket(...args);
                    window.__xianyuWebSocket = ws;
                    console.log('WebSocket 实例已捕获');
                    return ws;
                };

                window.WebSocket.prototype = originalWebSocket.prototype;
                window.__wsInterceptorInjected = true;
            })();
            """

            await self.cdp_session.send("Runtime.evaluate", {
                "expression": js_code
            })

            logger.info("WebSocket 拦截器注入成功")
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

    async def close(self) -> None:
        """关闭 CDP 拦截器"""
        try:
            self._is_monitoring = False
            logger.info("CDP 拦截器已关闭")
        except Exception as e:
            logger.error(f"关闭 CDP 拦截器失败: {e}")
