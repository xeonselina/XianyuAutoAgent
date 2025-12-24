"""
消息核心模块 - 闲鱼消息处理的抽象层

提供传输无关的消息处理接口，支持多种传输实现（直接 WebSocket、浏览器 CDP）。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, Any, Optional, Callable, List, Protocol
from enum import Enum
import asyncio
from loguru import logger


class MessageType(Enum):
    """消息类型枚举"""
    CHAT = "chat"  # 用户聊天消息
    TYPING = "typing"  # 正在输入状态
    SYSTEM = "system"  # 系统消息
    ORDER = "order"  # 订单消息
    UNKNOWN = "unknown"  # 未知消息


@dataclass
class Message:
    """
    标准化消息数据类

    Attributes:
        message_type: 消息类型
        chat_id: 会话 ID
        user_id: 用户 ID
        item_id: 商品 ID
        content: 消息内容
        timestamp: 时间戳
        raw_data: 原始消息数据
        metadata: 额外元数据
    """
    message_type: MessageType
    chat_id: str
    user_id: str
    item_id: Optional[str] = None
    content: Optional[str] = None
    timestamp: Optional[int] = None
    raw_data: Optional[Dict[str, Any]] = None
    metadata: Optional[Dict[str, Any]] = None


class MessageHandler(Protocol):
    """
    消息处理器协议接口

    实现此协议的类可以注册为消息处理器。
    """

    async def handle_message(self, message: Message) -> None:
        """
        处理消息

        Args:
            message: 标准化的消息对象
        """
        ...


class MessageTransport(ABC):
    """
    消息传输抽象基类

    定义消息收发的统一接口，具体传输实现（WebSocket、Browser CDP）
    需要继承此类并实现所有抽象方法。
    """

    @abstractmethod
    async def connect(self) -> bool:
        """
        建立连接

        Returns:
            bool: 连接是否成功
        """
        pass

    @abstractmethod
    async def disconnect(self) -> None:
        """优雅地断开连接"""
        pass

    @abstractmethod
    async def send_message(self, chat_id: str, user_id: str, content: str) -> bool:
        """
        发送消息

        Args:
            chat_id: 会话 ID
            user_id: 目标用户 ID
            content: 消息内容

        Returns:
            bool: 发送是否成功
        """
        pass

    @abstractmethod
    async def start_receiving(self, message_callback: Callable[[Dict[str, Any]], None]) -> None:
        """
        开始接收消息

        Args:
            message_callback: 收到消息时的回调函数
        """
        pass

    @abstractmethod
    async def is_connected(self) -> bool:
        """
        检查连接状态

        Returns:
            bool: 是否已连接
        """
        pass


class XianyuMessageCodec:
    """
    闲鱼消息编解码器

    负责闲鱼特定的消息格式编码、解码和分类。
    """

    @staticmethod
    def encode_message(chat_id: str, user_id: str, my_id: str, content: str) -> Dict[str, Any]:
        """
        编码出站消息为闲鱼协议格式

        Args:
            chat_id: 会话 ID
            user_id: 目标用户 ID
            my_id: 当前用户（卖家）ID
            content: 消息文本

        Returns:
            Dict: 闲鱼协议格式的消息
        """
        import base64
        import json
        from utils.xianyu_utils import generate_mid, generate_uuid

        # 构造消息内容
        text_data = {
            "contentType": 1,
            "text": {
                "text": content
            }
        }
        text_base64 = str(base64.b64encode(json.dumps(text_data).encode('utf-8')), 'utf-8')

        # 构造完整消息
        message = {
            "lwp": "/r/MessageSend/sendByReceiverScope",
            "headers": {
                "mid": generate_mid()
            },
            "body": [
                {
                    "uuid": generate_uuid(),
                    "cid": f"{chat_id}@goofish",
                    "conversationType": 1,
                    "content": {
                        "contentType": 101,
                        "custom": {
                            "type": 1,
                            "data": text_base64
                        }
                    },
                    "redPointPolicy": 0,
                    "extension": {
                        "extJson": "{}"
                    },
                    "ctx": {
                        "appVersion": "1.0",
                        "platform": "web"
                    },
                    "mtags": {},
                    "msgReadStatusSetting": 1
                },
                {
                    "actualReceivers": [
                        f"{user_id}@goofish",
                        f"{my_id}@goofish"
                    ]
                }
            ]
        }

        return message

    @staticmethod
    def decode_message(raw_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        解码入站消息

        Args:
            raw_data: 原始消息数据

        Returns:
            Optional[Dict]: 解码后的消息，解码失败返回 None
        """
        import base64
        import json
        from utils.xianyu_utils import decrypt

        try:
            # 检查是否为同步包消息
            if not XianyuMessageCodec._is_sync_package(raw_data):
                return None

            sync_data = raw_data["body"]["syncPushPackage"]["data"][0]

            if "data" not in sync_data:
                return None

            # 尝试解密数据
            data = sync_data["data"]
            try:
                # 尝试直接解码 base64
                decoded = base64.b64decode(data).decode("utf-8")
                message = json.loads(decoded)
                return None  # 无需解密的消息通常不是聊天消息
            except Exception:
                # 需要解密
                decrypted_data = decrypt(data)
                message = json.loads(decrypted_data)
                return message

        except Exception as e:
            logger.error(f"消息解码失败: {e}")
            return None

    @staticmethod
    def classify_message(message: Dict[str, Any]) -> MessageType:
        """
        分类消息类型

        Args:
            message: 解码后的消息

        Returns:
            MessageType: 消息类型
        """
        if XianyuMessageCodec._is_chat_message(message):
            return MessageType.CHAT
        elif XianyuMessageCodec._is_typing_status(message):
            return MessageType.TYPING
        elif XianyuMessageCodec._is_system_message(message):
            return MessageType.SYSTEM
        elif XianyuMessageCodec._is_order_message(message):
            return MessageType.ORDER
        else:
            return MessageType.UNKNOWN

    @staticmethod
    def extract_message_data(message: Dict[str, Any]) -> Optional[Message]:
        """
        从原始消息中提取标准化数据

        Args:
            message: 解码后的消息

        Returns:
            Optional[Message]: 标准化消息对象，提取失败返回 None
        """
        try:
            message_type = XianyuMessageCodec.classify_message(message)

            if message_type == MessageType.CHAT:
                # 提取聊天消息数据
                chat_id = message["1"]["2"].split('@')[0]
                user_id = message["1"]["10"]["senderUserId"]
                content = message["1"]["10"]["reminderContent"]
                timestamp = int(message["1"]["5"])

                # 提取商品 ID
                url_info = message["1"]["10"]["reminderUrl"]
                item_id = url_info.split("itemId=")[1].split("&")[0] if "itemId=" in url_info else None

                return Message(
                    message_type=message_type,
                    chat_id=chat_id,
                    user_id=user_id,
                    item_id=item_id,
                    content=content,
                    timestamp=timestamp,
                    raw_data=message
                )
            elif message_type == MessageType.ORDER:
                # 提取订单消息数据
                user_id = message['1'].split('@')[0]
                red_reminder = message['3']['redReminder']

                return Message(
                    message_type=message_type,
                    chat_id="",  # 订单消息没有 chat_id
                    user_id=user_id,
                    content=red_reminder,
                    raw_data=message,
                    metadata={"red_reminder": red_reminder}
                )
            else:
                # 其他类型消息
                return Message(
                    message_type=message_type,
                    chat_id="",
                    user_id="",
                    raw_data=message
                )

        except Exception as e:
            logger.error(f"提取消息数据失败: {e}")
            return None

    @staticmethod
    def _is_sync_package(message_data: Dict[str, Any]) -> bool:
        """判断是否为同步包消息"""
        try:
            return (
                isinstance(message_data, dict)
                and "body" in message_data
                and "syncPushPackage" in message_data["body"]
                and "data" in message_data["body"]["syncPushPackage"]
                and len(message_data["body"]["syncPushPackage"]["data"]) > 0
            )
        except Exception:
            return False

    @staticmethod
    def _is_chat_message(message: Dict[str, Any]) -> bool:
        """判断是否为用户聊天消息"""
        try:
            return (
                isinstance(message, dict)
                and "1" in message
                and isinstance(message["1"], dict)
                and "10" in message["1"]
                and isinstance(message["1"]["10"], dict)
                and "reminderContent" in message["1"]["10"]
            )
        except Exception:
            return False

    @staticmethod
    def _is_typing_status(message: Dict[str, Any]) -> bool:
        """判断是否为正在输入状态消息"""
        try:
            return (
                isinstance(message, dict)
                and "1" in message
                and isinstance(message["1"], list)
                and len(message["1"]) > 0
                and isinstance(message["1"][0], dict)
                and "1" in message["1"][0]
                and isinstance(message["1"][0]["1"], str)
                and "@goofish" in message["1"][0]["1"]
            )
        except Exception:
            return False

    @staticmethod
    def _is_system_message(message: Dict[str, Any]) -> bool:
        """判断是否为系统消息"""
        try:
            return (
                isinstance(message, dict)
                and "3" in message
                and isinstance(message["3"], dict)
                and "needPush" in message["3"]
                and message["3"]["needPush"] == "false"
            )
        except Exception:
            return False

    @staticmethod
    def _is_order_message(message: Dict[str, Any]) -> bool:
        """判断是否为订单消息"""
        try:
            return (
                isinstance(message, dict)
                and "3" in message
                and isinstance(message["3"], dict)
                and "redReminder" in message["3"]
            )
        except Exception:
            return False


class MessageRouter:
    """
    消息路由器

    负责注册消息处理器并将消息分发给相应的处理器。
    """

    def __init__(self):
        """初始化消息路由器"""
        self._handlers: Dict[MessageType, List[MessageHandler]] = {
            message_type: [] for message_type in MessageType
        }
        self._global_handlers: List[MessageHandler] = []

    def register_handler(self, message_type: MessageType, handler: MessageHandler) -> None:
        """
        注册消息处理器

        Args:
            message_type: 要处理的消息类型
            handler: 处理器实例
        """
        if message_type not in self._handlers:
            self._handlers[message_type] = []
        self._handlers[message_type].append(handler)
        logger.debug(f"已注册 {message_type.value} 类型消息处理器: {handler.__class__.__name__}")

    def register_global_handler(self, handler: MessageHandler) -> None:
        """
        注册全局处理器（接收所有类型消息）

        Args:
            handler: 处理器实例
        """
        self._global_handlers.append(handler)
        logger.debug(f"已注册全局消息处理器: {handler.__class__.__name__}")

    async def dispatch(self, message: Message) -> None:
        """
        分发消息到已注册的处理器

        Args:
            message: 要分发的消息
        """
        try:
            # 调用特定类型的处理器
            handlers = self._handlers.get(message.message_type, [])
            for handler in handlers:
                try:
                    await handler.handle_message(message)
                except Exception as e:
                    logger.error(f"处理器 {handler.__class__.__name__} 处理消息失败: {e}")

            # 调用全局处理器
            for handler in self._global_handlers:
                try:
                    await handler.handle_message(message)
                except Exception as e:
                    logger.error(f"全局处理器 {handler.__class__.__name__} 处理消息失败: {e}")

        except Exception as e:
            logger.error(f"消息分发失败: {e}")
