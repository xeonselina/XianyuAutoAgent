"""
消息核心模块单元测试
"""

import pytest
import json
import base64
from messaging_core import (
    MessageType,
    Message,
    XianyuMessageCodec,
    MessageRouter,
    MessageTransport
)


class TestMessageType:
    """测试消息类型枚举"""

    def test_message_types(self):
        """测试所有消息类型定义"""
        assert MessageType.CHAT.value == "chat"
        assert MessageType.TYPING.value == "typing"
        assert MessageType.SYSTEM.value == "system"
        assert MessageType.ORDER.value == "order"
        assert MessageType.UNKNOWN.value == "unknown"


class TestMessage:
    """测试消息数据类"""

    def test_message_creation(self):
        """测试消息对象创建"""
        msg = Message(
            message_type=MessageType.CHAT,
            chat_id="12345",
            user_id="67890",
            item_id="item123",
            content="你好",
            timestamp=1234567890,
            raw_data={"test": "data"}
        )

        assert msg.message_type == MessageType.CHAT
        assert msg.chat_id == "12345"
        assert msg.user_id == "67890"
        assert msg.item_id == "item123"
        assert msg.content == "你好"
        assert msg.timestamp == 1234567890
        assert msg.raw_data == {"test": "data"}

    def test_message_optional_fields(self):
        """测试消息可选字段"""
        msg = Message(
            message_type=MessageType.SYSTEM,
            chat_id="",
            user_id=""
        )

        assert msg.item_id is None
        assert msg.content is None
        assert msg.timestamp is None
        assert msg.raw_data is None
        assert msg.metadata is None


class TestXianyuMessageCodec:
    """测试闲鱼消息编解码器"""

    def test_encode_message(self):
        """测试消息编码"""
        message = XianyuMessageCodec.encode_message(
            chat_id="test_chat",
            user_id="user123",
            my_id="seller456",
            content="测试消息"
        )

        assert message["lwp"] == "/r/MessageSend/sendByReceiverScope"
        assert "headers" in message
        assert "mid" in message["headers"]
        assert "body" in message
        assert len(message["body"]) == 2

        # 验证接收者
        receivers = message["body"][1]["actualReceivers"]
        assert "user123@goofish" in receivers
        assert "seller456@goofish" in receivers

        # 验证会话 ID
        assert message["body"][0]["cid"] == "test_chat@goofish"

    def test_encode_message_content(self):
        """测试消息内容编码"""
        content = "你好，世界！"
        message = XianyuMessageCodec.encode_message(
            chat_id="chat1",
            user_id="user1",
            my_id="seller1",
            content=content
        )

        # 解码 base64 内容
        encoded_data = message["body"][0]["content"]["custom"]["data"]
        decoded_bytes = base64.b64decode(encoded_data)
        decoded_str = decoded_bytes.decode('utf-8')
        decoded_json = json.loads(decoded_str)

        assert decoded_json["contentType"] == 1
        assert decoded_json["text"]["text"] == content

    def test_is_chat_message(self):
        """测试聊天消息识别"""
        # 有效的聊天消息
        valid_chat = {
            "1": {
                "10": {
                    "reminderContent": "你好"
                }
            }
        }
        assert XianyuMessageCodec._is_chat_message(valid_chat) is True

        # 无效的消息
        invalid_messages = [
            {},
            {"1": {}},
            {"1": {"10": {}}},
            {"1": []},
            None,
            "not a dict"
        ]
        for msg in invalid_messages:
            assert XianyuMessageCodec._is_chat_message(msg) is False

    def test_is_typing_status(self):
        """测试正在输入状态识别"""
        # 有效的输入状态消息
        valid_typing = {
            "1": [
                {
                    "1": "user123@goofish"
                }
            ]
        }
        assert XianyuMessageCodec._is_typing_status(valid_typing) is True

        # 无效的消息
        invalid_messages = [
            {},
            {"1": {}},
            {"1": []},
            {"1": [{"1": "no-goofish"}]},
            None
        ]
        for msg in invalid_messages:
            assert XianyuMessageCodec._is_typing_status(msg) is False

    def test_is_system_message(self):
        """测试系统消息识别"""
        # 有效的系统消息
        valid_system = {
            "3": {
                "needPush": "false"
            }
        }
        assert XianyuMessageCodec._is_system_message(valid_system) is True

        # 无效的消息
        invalid_messages = [
            {},
            {"3": {}},
            {"3": {"needPush": "true"}},
            None
        ]
        for msg in invalid_messages:
            assert XianyuMessageCodec._is_system_message(msg) is False

    def test_is_order_message(self):
        """测试订单消息识别"""
        # 有效的订单消息
        valid_order = {
            "3": {
                "redReminder": "等待买家付款"
            }
        }
        assert XianyuMessageCodec._is_order_message(valid_order) is True

        # 无效的消息
        invalid_messages = [
            {},
            {"3": {}},
            None
        ]
        for msg in invalid_messages:
            assert XianyuMessageCodec._is_order_message(msg) is False

    def test_classify_message(self):
        """测试消息分类"""
        # 聊天消息
        chat_msg = {
            "1": {
                "10": {
                    "reminderContent": "你好"
                }
            }
        }
        assert XianyuMessageCodec.classify_message(chat_msg) == MessageType.CHAT

        # 正在输入
        typing_msg = {
            "1": [
                {
                    "1": "user@goofish"
                }
            ]
        }
        assert XianyuMessageCodec.classify_message(typing_msg) == MessageType.TYPING

        # 系统消息
        system_msg = {
            "3": {
                "needPush": "false"
            }
        }
        assert XianyuMessageCodec.classify_message(system_msg) == MessageType.SYSTEM

        # 订单消息
        order_msg = {
            "3": {
                "redReminder": "等待买家付款"
            }
        }
        assert XianyuMessageCodec.classify_message(order_msg) == MessageType.ORDER

        # 未知消息
        unknown_msg = {"unknown": "data"}
        assert XianyuMessageCodec.classify_message(unknown_msg) == MessageType.UNKNOWN

    def test_extract_message_data_chat(self):
        """测试提取聊天消息数据"""
        raw_message = {
            "1": {
                "2": "chat123@goofish",
                "5": "1234567890000",
                "10": {
                    "senderUserId": "user456",
                    "reminderContent": "这个多少钱？",
                    "reminderUrl": "https://example.com?itemId=item789&other=param"
                }
            }
        }

        message = XianyuMessageCodec.extract_message_data(raw_message)

        assert message is not None
        assert message.message_type == MessageType.CHAT
        assert message.chat_id == "chat123"
        assert message.user_id == "user456"
        assert message.content == "这个多少钱？"
        assert message.item_id == "item789"
        assert message.timestamp == 1234567890000

    def test_extract_message_data_order(self):
        """测试提取订单消息数据"""
        raw_message = {
            "1": "user123@goofish",
            "3": {
                "redReminder": "等待买家付款"
            }
        }

        message = XianyuMessageCodec.extract_message_data(raw_message)

        assert message is not None
        assert message.message_type == MessageType.ORDER
        assert message.user_id == "user123"
        assert message.content == "等待买家付款"
        assert message.metadata["red_reminder"] == "等待买家付款"


class TestMessageRouter:
    """测试消息路由器"""

    def test_router_creation(self):
        """测试路由器创建"""
        router = MessageRouter()
        assert router is not None

    @pytest.mark.asyncio
    async def test_register_handler(self):
        """测试注册消息处理器"""
        router = MessageRouter()
        received_messages = []

        class TestHandler:
            async def handle_message(self, message: Message):
                received_messages.append(message)

        handler = TestHandler()
        router.register_handler(MessageType.CHAT, handler)

        # 分发聊天消息
        chat_message = Message(
            message_type=MessageType.CHAT,
            chat_id="chat1",
            user_id="user1",
            content="测试"
        )
        await router.dispatch(chat_message)

        assert len(received_messages) == 1
        assert received_messages[0] == chat_message

    @pytest.mark.asyncio
    async def test_register_global_handler(self):
        """测试注册全局处理器"""
        router = MessageRouter()
        received_messages = []

        class GlobalHandler:
            async def handle_message(self, message: Message):
                received_messages.append(message)

        handler = GlobalHandler()
        router.register_global_handler(handler)

        # 分发不同类型的消息
        messages = [
            Message(MessageType.CHAT, "chat1", "user1", content="聊天"),
            Message(MessageType.SYSTEM, "", ""),
            Message(MessageType.ORDER, "", "user2", content="订单")
        ]

        for msg in messages:
            await router.dispatch(msg)

        # 全局处理器应该接收所有消息
        assert len(received_messages) == 3

    @pytest.mark.asyncio
    async def test_multiple_handlers(self):
        """测试多个处理器"""
        router = MessageRouter()
        handler1_messages = []
        handler2_messages = []

        class Handler1:
            async def handle_message(self, message: Message):
                handler1_messages.append(message)

        class Handler2:
            async def handle_message(self, message: Message):
                handler2_messages.append(message)

        router.register_handler(MessageType.CHAT, Handler1())
        router.register_handler(MessageType.CHAT, Handler2())

        message = Message(MessageType.CHAT, "chat1", "user1", content="测试")
        await router.dispatch(message)

        # 两个处理器都应该收到消息
        assert len(handler1_messages) == 1
        assert len(handler2_messages) == 1

    @pytest.mark.asyncio
    async def test_handler_error_isolation(self):
        """测试处理器错误隔离"""
        router = MessageRouter()
        handler2_messages = []

        class ErrorHandler:
            async def handle_message(self, message: Message):
                raise Exception("处理器错误")

        class NormalHandler:
            async def handle_message(self, message: Message):
                handler2_messages.append(message)

        router.register_handler(MessageType.CHAT, ErrorHandler())
        router.register_handler(MessageType.CHAT, NormalHandler())

        message = Message(MessageType.CHAT, "chat1", "user1", content="测试")
        await router.dispatch(message)

        # 第一个处理器出错，第二个处理器应该仍然能收到消息
        assert len(handler2_messages) == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
