"""
钉钉 Stream 模式客户端。

使用 dingtalk-stream SDK 通过长连接接收钉钉群消息，
替代传统的 Outgoing Webhook（不需要公网回调地址）。

配置步骤：
1. 登录钉钉开发者后台 https://open-dev.dingtalk.com/
2. 创建「企业内部应用」→ 添加「机器人」能力
3. 在「开发管理」中获取 Client ID (AppKey) 和 Client Secret (AppSecret)
4. 将机器人添加到钉钉群中
5. 在 .env 中配置 DINGTALK_APP_KEY 和 DINGTALK_APP_SECRET

群里 @机器人 发送 #reply req_xxx 回复内容，即可触发回复流程。
"""

import asyncio
import logging
from typing import Optional

from ai_kefu.config.settings import settings
from ai_kefu.utils.logging import logger


class DingTalkStreamService:
    """
    钉钉 Stream 模式服务。

    通过长连接监听群消息，处理 #reply 指令。
    """

    def __init__(self):
        self._client = None
        self._task: Optional[asyncio.Task] = None

    def is_configured(self) -> bool:
        """检查 Stream 模式所需配置是否齐全。"""
        return bool(settings.dingtalk_app_key and settings.dingtalk_app_secret)

    async def start(self):
        """在后台启动 Stream 客户端。"""
        if not self.is_configured():
            logger.warning(
                "钉钉 Stream 模式未配置（DINGTALK_APP_KEY / DINGTALK_APP_SECRET），跳过启动"
            )
            return

        try:
            import dingtalk_stream
            from dingtalk_stream import AckMessage
        except ImportError:
            logger.error(
                "dingtalk-stream 包未安装，请执行: pip install dingtalk-stream"
            )
            return

        app_key = settings.dingtalk_app_key
        app_secret = settings.dingtalk_app_secret

        logger.info("正在启动钉钉 Stream 客户端...")

        # 创建凭据
        credential = dingtalk_stream.Credential(app_key, app_secret)

        # 创建客户端
        self._client = dingtalk_stream.DingTalkStreamClient(credential)

        # 注册机器人消息处理器
        handler = _ReplyHandler()
        self._client.register_callback_handler(
            dingtalk_stream.chatbot.ChatbotMessage.TOPIC,
            handler,
        )

        # 在后台任务中运行
        self._task = asyncio.create_task(self._run_forever())
        logger.info("✅ 钉钉 Stream 客户端已在后台启动")

    async def _run_forever(self):
        """持续运行 Stream 客户端，断线自动重连。"""
        try:
            import dingtalk_stream  # noqa: F811
        except ImportError:
            return

        while True:
            try:
                logger.info("钉钉 Stream 客户端连接中...")
                await self._client.start()
            except asyncio.CancelledError:
                logger.info("钉钉 Stream 客户端被取消")
                break
            except Exception as e:
                logger.error(f"钉钉 Stream 客户端异常: {e}，5 秒后重连...")
                await asyncio.sleep(5)

    async def stop(self):
        """停止 Stream 客户端。"""
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("钉钉 Stream 客户端已停止")


class _ReplyHandler:
    """
    处理 @机器人 的群消息。

    识别 #reply req_xxx 回复内容 格式的消息，
    转发到 dingtalk_reply_handler 进行处理。
    """

    def __init__(self):
        # dingtalk_stream 的 ChatbotHandler 需要 logger 属性
        self.logger = logging.getLogger("dingtalk_stream")

    async def process(self, callback):
        """
        处理钉钉推送的机器人消息。

        Args:
            callback: dingtalk_stream.CallbackMessage

        Returns:
            (status, message) 元组
        """
        try:
            import dingtalk_stream
            from dingtalk_stream import AckMessage
        except ImportError:
            return

        incoming_message = dingtalk_stream.ChatbotMessage.from_dict(callback.data)

        # 提取消息文本（@机器人 后的内容）
        text_content = ""
        if hasattr(incoming_message, "text") and incoming_message.text:
            text_content = incoming_message.text.content.strip() if hasattr(incoming_message.text, "content") else str(incoming_message.text).strip()

        if not text_content:
            logger.debug("收到空消息，忽略")
            return AckMessage.STATUS_OK, "OK"

        logger.info(f"收到钉钉 Stream 消息: {text_content[:200]}")

        # 调用已有的回复处理逻辑
        from ai_kefu.services.dingtalk_reply_handler import handle_dingtalk_reply
        feedback = await handle_dingtalk_reply(text_content)

        if feedback:
            # 回复到群里
            try:
                self.reply_text(feedback, incoming_message)
                logger.info(f"已回复到钉钉群: {feedback[:100]}")
            except Exception as e:
                logger.warning(f"回复到钉钉群失败: {e}")
                # 降级：通过 Incoming Webhook 发通知
                try:
                    from ai_kefu.services.dingtalk_notify import send_dingtalk_message
                    send_dingtalk_message(
                        title="回复结果",
                        content=feedback,
                    )
                except Exception as notify_err:
                    logger.error(f"降级通知也失败: {notify_err}")

        return AckMessage.STATUS_OK, "OK"

    def reply_text(self, text: str, incoming_message):
        """
        回复文本消息到钉钉群。

        使用 dingtalk-stream SDK 的 reply 能力。
        """
        import requests as req_lib

        # 通过 OpenAPI 回复消息
        # incoming_message 包含 session_webhook 可以直接回复
        webhook = getattr(incoming_message, "session_webhook", None)
        if not webhook:
            logger.warning("incoming_message 没有 session_webhook，无法直接回复")
            return

        payload = {
            "msgtype": "text",
            "text": {"content": text},
        }

        try:
            resp = req_lib.post(webhook, json=payload, timeout=5)
            result = resp.json()
            if resp.status_code == 200:
                logger.debug(f"钉钉 Stream 回复成功")
            else:
                logger.warning(f"钉钉 Stream 回复异常: {result}")
        except Exception as e:
            logger.error(f"钉钉 Stream 回复请求失败: {e}")


# ──────────────────────────────────────────────
# 全局单例
# ──────────────────────────────────────────────
_instance: Optional[DingTalkStreamService] = None


def get_dingtalk_stream_service() -> DingTalkStreamService:
    """获取全局 DingTalkStreamService 实例。"""
    global _instance
    if _instance is None:
        _instance = DingTalkStreamService()
    return _instance
