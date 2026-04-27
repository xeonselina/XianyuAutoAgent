"""
历史消息解析器

解析闲鱼通过WebSocket返回的历史消息列表
"""

import re
from typing import List, Dict, Any, Optional
from loguru import logger
from .models import XianyuMessage, XianyuMessageType


class HistoryMessageParser:
    """
    闲鱼历史消息解析器

    解析 /r/MessageManager/listUserMessages 等API返回的历史消息
    """

    @staticmethod
    def is_history_message_response(message_data: Dict[str, Any]) -> bool:
        """
        判断是否是历史消息响应

        Args:
            message_data: WebSocket消息数据

        Returns:
            bool: 是否是历史消息响应
        """
        try:
            # 检查是否有正确的结构
            if not isinstance(message_data, dict):
                return False

            # 必须有code=200和body字段
            if message_data.get("code") != 200:
                return False

            body = message_data.get("body", {})
            if not isinstance(body, dict):
                return False

            # 检查是否包含userMessageModels字段
            if "userMessageModels" in body:
                return True

            return False

        except Exception as e:
            logger.debug(f"判断历史消息响应失败: {e}")
            return False

    @staticmethod
    def parse_history_messages(message_data: Dict[str, Any]) -> List[XianyuMessage]:
        """
        从WebSocket响应中解析历史消息列表

        Args:
            message_data: WebSocket消息数据

        Returns:
            List[XianyuMessage]: 解析出的消息列表
        """
        messages = []

        try:
            body = message_data.get("body", {})
            user_message_models = body.get("userMessageModels", [])

            logger.info(f"📜 解析历史消息: 找到 {len(user_message_models)} 条消息")

            for idx, model in enumerate(user_message_models):
                try:
                    msg = HistoryMessageParser._parse_single_message(model)
                    if msg:
                        messages.append(msg)
                        logger.debug(f"   [{idx+1}] {msg.content[:50]}... (sender={msg.user_id})")
                except Exception as e:
                    logger.warning(f"解析第 {idx+1} 条消息失败: {e}")
                    continue

            logger.info(f"✅ 成功解析 {len(messages)} 条历史消息")

            # 提取nextCursor用于加载更多
            next_cursor = body.get("nextCursor")
            if next_cursor:
                logger.debug(f"下一页游标: {next_cursor}")

            return messages

        except Exception as e:
            logger.error(f"解析历史消息列表失败: {e}", exc_info=True)
            return []

    @staticmethod
    def _parse_single_message(model: Dict[str, Any]) -> Optional[XianyuMessage]:
        """
        解析单条历史消息

        Args:
            model: userMessageModel对象

        Returns:
            Optional[XianyuMessage]: 解析出的消息，失败返回None
        """
        try:
            message = model.get("message", {})
            extension = message.get("extension", {})

            # 提取消息内容
            content = extension.get("reminderContent", "")
            if not content:
                # 尝试从searchableContent获取
                searchable = message.get("searchableContent", {})
                content = searchable.get("summary", "")

            # 提取发送者ID
            sender_id = extension.get("senderUserId", "")
            if not sender_id:
                # 尝试从sender字段获取
                sender = message.get("sender", {})
                sender_uid = sender.get("uid", "")
                if sender_uid:
                    sender_id = sender_uid.split("@")[0]

            # 提取会话ID
            cid = message.get("cid", "")
            chat_id = cid.split("@")[0] if cid else ""

            # 提取时间戳
            timestamp = message.get("createAt", 0)

            # 提取商品ID（从reminderUrl中解析）
            item_id = None
            reminder_url = extension.get("reminderUrl", "")
            if reminder_url:
                match = re.search(r'itemId=(\d+)', reminder_url)
                if match:
                    item_id = match.group(1)

            # 如果没有基本信息，跳过
            if not content or not chat_id:
                logger.debug(f"跳过空消息或无效消息")
                return None

            # 构造XianyuMessage对象
            xianyu_message = XianyuMessage(
                message_type=XianyuMessageType.CHAT,
                chat_id=chat_id,
                user_id=sender_id,
                content=content,
                item_id=item_id,
                timestamp=timestamp,
                raw_data=model,
                metadata={
                    "source": "history_api",
                    "message_id": message.get("messageId", ""),
                    "read_status": model.get("readStatus", 0),
                    "reminder_title": extension.get("reminderTitle", ""),
                    "session_type": extension.get("sessionType", ""),
                    "encrypted_uid": "",
                }
            )

            return xianyu_message

        except Exception as e:
            logger.debug(f"解析单条消息失败: {e}")
            return None

    @staticmethod
    def extract_item_id_from_url(url: str) -> Optional[str]:
        """
        从URL中提取商品ID

        Args:
            url: reminderUrl或其他包含itemId的URL

        Returns:
            Optional[str]: 商品ID，未找到返回None
        """
        try:
            match = re.search(r'itemId=(\d+)', url)
            if match:
                return match.group(1)
        except:
            pass
        return None
