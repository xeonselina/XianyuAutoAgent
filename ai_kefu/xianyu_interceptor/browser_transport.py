"""
浏览器传输层 — 通过 CDP 拦截器发送闲鱼消息。

将 CDPInterceptor 的底层 send_message(raw_dict) 接口
包装为 MessageTransport 的高级接口 send_message(chat_id, user_id, content)。

使用方法：
    transport = BrowserTransport(config.seller_user_id)
    transport.set_interceptor(active_cdp_interceptor)
    await transport.send_message(chat_id, user_id, "你好")
"""

from typing import Optional

from loguru import logger

from .messaging_core import MessageTransport, XianyuMessageCodec


class BrowserTransport(MessageTransport):
    """
    通过浏览器 CDP 拦截器发送消息的 Transport 实现。

    内部持有对 CDPInterceptor 的引用（可延迟设置），
    使用 XianyuMessageCodec 编码消息为闲鱼协议格式后发送。
    """

    def __init__(self, seller_user_id: str):
        """
        Args:
            seller_user_id: 卖家（自己）的用户 ID，用于消息编码。
        """
        self._seller_user_id = seller_user_id
        self._interceptor = None  # CDPInterceptor, 延迟注入

    def set_interceptor(self, interceptor) -> None:
        """
        注入 CDP 拦截器实例。

        在 run_xianyu.py 中检测到活跃的 WebSocket 连接后调用。

        Args:
            interceptor: CDPInterceptor 实例
        """
        self._interceptor = interceptor
        logger.info("BrowserTransport: CDP 拦截器已注入")

    # ------------------------------------------------------------------
    # MessageTransport 接口实现
    # ------------------------------------------------------------------

    async def connect(self) -> bool:
        """BrowserTransport 不需要主动连接（由浏览器管理）。"""
        return self._interceptor is not None

    async def disconnect(self) -> None:
        """BrowserTransport 不需要主动断开（由浏览器管理）。"""
        self._interceptor = None

    async def send_message(self, chat_id: str, user_id: str, content: str) -> bool:
        """
        发送消息到闲鱼用户。

        Args:
            chat_id: 会话 ID
            user_id: 目标用户 ID
            content: 消息内容

        Returns:
            bool: 发送是否成功
        """
        if not self._interceptor:
            logger.error("BrowserTransport: CDP 拦截器未设置，无法发送消息")
            return False

        if not self._seller_user_id:
            logger.error("BrowserTransport: seller_user_id 未配置，无法编码消息")
            return False

        try:
            # 使用 XianyuMessageCodec 编码为闲鱼协议格式
            message_data = XianyuMessageCodec.encode_message(
                chat_id=chat_id,
                user_id=user_id,
                my_id=self._seller_user_id,
                content=content,
            )

            # 通过 CDP 拦截器发送
            success = await self._interceptor.send_message(message_data)

            if success:
                logger.info(
                    f"BrowserTransport: 消息已发送 chat_id={chat_id}, "
                    f"content={content[:80]}..."
                )
            else:
                logger.warning(
                    f"BrowserTransport: 消息发送失败 chat_id={chat_id}"
                )

            return success

        except Exception as e:
            logger.error(f"BrowserTransport: 发送消息异常: {e}", exc_info=True)
            return False

    async def start_receiving(self, message_callback) -> None:
        """接收消息由 CDPInterceptor 直接处理，此方法无需实现。"""
        pass

    async def is_connected(self) -> bool:
        """检查 CDP 拦截器是否已连接。"""
        if self._interceptor is None:
            return False
        return self._interceptor.is_connected()
