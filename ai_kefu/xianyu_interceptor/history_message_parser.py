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
            import json as _json

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

            # ============================================================
            # 🎯 [UID追踪] 判断是否是目标用户 TB_28060346
            # ============================================================
            is_target_user = ("TB_28060346" in str(sender_id)) or ("28060346" in str(sender_id))
            target_marker = "🎯🎯🎯 [目标用户TB_28060346] " if is_target_user else ""

            if is_target_user:
                logger.info(f"{target_marker}📜 发现目标用户的历史消息! content={content[:80] if content else ''}")

            # 🔬 完整打印 model 对象顶层键
            logger.info(f"{target_marker}🔬 [历史消息model顶层键]: {list(model.keys())}")
            # 🔬 完整打印 message 对象所有键
            logger.info(f"{target_marker}🔬 [message对象所有键]: {list(message.keys())}")

            # 🔬 完整打印 message 对象（不截断，最多10000字符）
            try:
                msg_dump = _json.dumps(message, ensure_ascii=False, default=str)
                if is_target_user or len(msg_dump) < 3000:
                    # 目标用户完整打印
                    logger.info(f"{target_marker}🔬 [message完整JSON] (长度={len(msg_dump)}): {msg_dump[:10000]}")
                else:
                    logger.info(f"🔬 [message完整JSON] (长度={len(msg_dump)}): {msg_dump[:3000]}")
            except Exception:
                pass

            # 逐个打印 message 中的所有顶层字段
            for msg_key in message:
                val = message[msg_key]
                if isinstance(val, dict):
                    try:
                        val_str = _json.dumps(val, ensure_ascii=False, default=str)
                        logger.info(f"{target_marker}🔬   message['{msg_key}'] (dict, {len(val)}键): {val_str[:1500]}")
                    except:
                        logger.info(f"{target_marker}🔬   message['{msg_key}'] (dict keys): {list(val.keys())}")
                elif isinstance(val, list):
                    logger.info(f"{target_marker}🔬   message['{msg_key}'] (list, {len(val)}项): {str(val)[:500]}")
                elif isinstance(val, str) and len(val) > 200:
                    logger.info(f"{target_marker}🔬   message['{msg_key}'] (str): {val[:200]}...")
                else:
                    logger.info(f"{target_marker}🔬   message['{msg_key}']: {val}")

            # ============================================================
            # 提取闲鱼加密 UID - 全面搜索策略
            # ============================================================
            encrypted_uid = ""

            # 方法1: sender 对象
            sender_obj = message.get("sender", {})
            if isinstance(sender_obj, dict) and sender_obj:
                logger.info(f"{target_marker}🔬 [sender对象完整内容]: {_json.dumps(sender_obj, ensure_ascii=False, default=str)}")
                for uid_field in ["encryptedUid", "encrypted_uid", "encryptUid",
                                  "encryptedUserId", "senderEncryptedUid", "buyerEncryptedUid"]:
                    uid = sender_obj.get(uid_field, "")
                    if uid:
                        encrypted_uid = uid
                        logger.info(f"{target_marker}   ✅ 从 sender['{uid_field}'] 提取到: {encrypted_uid}")
                        break
                if not encrypted_uid:
                    # 遍历所有值，看看有没有类似 base64 编码的加密 UID
                    for k, v in sender_obj.items():
                        if isinstance(v, str) and len(v) > 10 and ("==" in v or "+" in v or "/" in v):
                            logger.info(f"{target_marker}   🔍 sender['{k}'] 可能是加密UID: {v[:50]}")

            # 方法2: 检查 message 的其他对象字段
            if not encrypted_uid:
                for top_key in ["sender", "receiver", "from", "to", "user", "buyer", "seller"]:
                    obj = message.get(top_key, {})
                    if isinstance(obj, dict) and obj:
                        for uid_field in ["encryptedUid", "encrypted_uid", "encryptUid",
                                          "encryptedUserId", "senderEncryptedUid", "buyerEncryptedUid"]:
                            uid = obj.get(uid_field, "")
                            if uid:
                                encrypted_uid = uid
                                logger.info(f"{target_marker}   ✅ 从 message['{top_key}']['{uid_field}'] 提取到: {encrypted_uid}")
                                break
                        if encrypted_uid:
                            break

            # 方法3: 检查 extension 对象
            if not encrypted_uid and isinstance(extension, dict):
                for uid_field in ["encryptedUid", "encrypted_uid", "encryptUid",
                                  "senderEncryptedUid", "buyerEncryptedUid"]:
                    uid = extension.get(uid_field, "")
                    if uid:
                        encrypted_uid = uid
                        logger.info(f"{target_marker}   ✅ 从 extension['{uid_field}'] 提取到: {encrypted_uid}")
                        break

            # 方法4: 递归搜索整个 message 对象
            if not encrypted_uid:
                def _find_uid_fields(obj, path=""):
                    results = []
                    if isinstance(obj, dict):
                        for k, v in obj.items():
                            k_lower = str(k).lower()
                            if any(kw in k_lower for kw in ["encrypt", "uid", "buyer", "sender"]):
                                results.append((f"{path}.{k}" if path else k, v))
                            results.extend(_find_uid_fields(v, f"{path}.{k}" if path else k))
                    elif isinstance(obj, list):
                        for i, item in enumerate(obj):
                            results.extend(_find_uid_fields(item, f"{path}[{i}]"))
                    return results

                uid_fields = _find_uid_fields(message)
                if uid_fields:
                    logger.info(f"{target_marker}🔬 [递归搜索message] 找到 {len(uid_fields)} 个相关字段:")
                    for field_path, field_val in uid_fields:
                        logger.info(f"{target_marker}🔬   {field_path} = {str(field_val)[:200]}")
                else:
                    logger.info(f"{target_marker}🔬 [递归搜索message] 未找到包含encrypt/uid/buyer/sender的字段")

                # 方法5: 在 model 顶层也搜索
                uid_fields_model = _find_uid_fields(model)
                if uid_fields_model and uid_fields_model != uid_fields:
                    extra = [f for f in uid_fields_model if f not in uid_fields]
                    if extra:
                        logger.info(f"{target_marker}🔬 [递归搜索model] 额外找到 {len(extra)} 个字段:")
                        for field_path, field_val in extra:
                            logger.info(f"{target_marker}🔬   {field_path} = {str(field_val)[:200]}")

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
                    "encrypted_uid": encrypted_uid,
                    "sender_fields": list(sender_obj.keys()) if isinstance(sender_obj, dict) else [],
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
