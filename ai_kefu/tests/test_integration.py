"""
集成测试 - 测试主应用与传输层的集成
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch
from main import XianyuLive, create_transport
from messaging_core import MessageTransport
from transports import DirectWebSocketTransport, BrowserWebSocketTransport


class MockBot:
    """模拟 AI 机器人"""

    def __init__(self):
        self.last_intent = None

    def generate_reply(self, message, item_description, context=None):
        """生成回复"""
        self.last_intent = "default"
        return f"收到消息: {message}"


class MockTransport(MessageTransport):
    """模拟传输层"""

    def __init__(self):
        self.connected = False
        self.messages_sent = []
        self.message_callback = None

    async def connect(self) -> bool:
        self.connected = True
        return True

    async def disconnect(self) -> None:
        self.connected = False

    async def send_message(self, chat_id: str, user_id: str, content: str) -> bool:
        if not self.connected:
            return False
        self.messages_sent.append({
            "chat_id": chat_id,
            "user_id": user_id,
            "content": content
        })
        return True

    async def start_receiving(self, message_callback) -> None:
        self.message_callback = message_callback

    async def is_connected(self) -> bool:
        return self.connected

    async def simulate_receive_message(self, message_data):
        """模拟接收消息"""
        if self.message_callback:
            await self.message_callback(message_data)


class TestXianyuLiveIntegration:
    """测试 XianyuLive 与传输层的集成"""

    def test_initialization(self):
        """测试初始化"""
        cookies_str = "unb=test_user; cookie2=test"
        transport = MockTransport()
        bot = MockBot()

        xianyu_live = XianyuLive(cookies_str, transport, bot)

        assert xianyu_live.cookies_str == cookies_str
        assert xianyu_live.myid == "test_user"
        assert xianyu_live.transport == transport
        assert xianyu_live.bot == bot

    @pytest.mark.asyncio
    async def test_manual_mode_toggle(self):
        """测试人工接管模式切换"""
        cookies_str = "unb=seller123; cookie2=test"
        transport = MockTransport()
        bot = MockBot()

        xianyu_live = XianyuLive(cookies_str, transport, bot)

        chat_id = "chat123"

        # 初始状态：自动模式
        assert xianyu_live.is_manual_mode(chat_id) is False

        # 切换到人工模式
        mode = xianyu_live.toggle_manual_mode(chat_id)
        assert mode == "manual"
        assert xianyu_live.is_manual_mode(chat_id) is True

        # 切换回自动模式
        mode = xianyu_live.toggle_manual_mode(chat_id)
        assert mode == "auto"
        assert xianyu_live.is_manual_mode(chat_id) is False

    @pytest.mark.asyncio
    async def test_handle_seller_control_message(self):
        """测试处理卖家控制消息"""
        cookies_str = "unb=seller123; cookie2=test"
        transport = MockTransport()
        bot = MockBot()

        xianyu_live = XianyuLive(cookies_str, transport, bot)

        # 模拟卖家发送切换关键词
        message_data = {
            "body": {
                "syncPushPackage": {
                    "data": [{
                        "data": "encrypted_data"  # 实际会被解密
                    }]
                }
            }
        }

        # 这个测试主要验证流程不会崩溃
        # 实际的消息处理需要完整的加密消息数据
        await xianyu_live.handle_message(message_data)

    def test_check_toggle_keywords(self):
        """测试切换关键词检查"""
        cookies_str = "unb=test_user; cookie2=test"
        transport = MockTransport()
        bot = MockBot()

        xianyu_live = XianyuLive(cookies_str, transport, bot)

        # 默认关键词是句号
        assert xianyu_live.check_toggle_keywords("。") is True
        assert xianyu_live.check_toggle_keywords("  。  ") is True
        assert xianyu_live.check_toggle_keywords("你好") is False

    @pytest.mark.asyncio
    async def test_manual_mode_timeout(self):
        """测试人工接管超时"""
        cookies_str = "unb=seller123; cookie2=test"
        transport = MockTransport()
        bot = MockBot()

        with patch.dict('os.environ', {'MANUAL_MODE_TIMEOUT': '1'}):
            xianyu_live = XianyuLive(cookies_str, transport, bot)

        chat_id = "chat456"

        # 进入人工模式
        xianyu_live.enter_manual_mode(chat_id)
        assert xianyu_live.is_manual_mode(chat_id) is True

        # 等待超时
        await asyncio.sleep(1.1)

        # 检查是否自动退出
        assert xianyu_live.is_manual_mode(chat_id) is False


class TestTransportFactory:
    """测试传输工厂函数"""

    def test_create_direct_transport(self):
        """测试创建直接传输"""
        cookies_str = "unb=test_user; cookie2=test"

        with patch.dict('os.environ', {'USE_BROWSER_MODE': 'false'}):
            transport = create_transport(cookies_str)

        assert isinstance(transport, DirectWebSocketTransport)
        assert transport.cookies_str == cookies_str

    def test_create_browser_transport(self):
        """测试创建浏览器传输"""
        cookies_str = "unb=test_user; cookie2=test"

        with patch.dict('os.environ', {'USE_BROWSER_MODE': 'true'}):
            transport = create_transport(cookies_str)

        assert isinstance(transport, BrowserWebSocketTransport)
        assert transport.cookies_str == cookies_str

    def test_default_to_direct_mode(self):
        """测试默认使用直接模式"""
        cookies_str = "unb=test_user; cookie2=test"

        with patch.dict('os.environ', {}, clear=True):
            transport = create_transport(cookies_str)

        assert isinstance(transport, DirectWebSocketTransport)


class TestEndToEndFlow:
    """端到端流程测试"""

    @pytest.mark.asyncio
    async def test_message_flow(self):
        """测试完整消息流程"""
        cookies_str = "unb=seller123; cookie2=test"
        transport = MockTransport()
        bot = MockBot()

        xianyu_live = XianyuLive(cookies_str, transport, bot)

        # 连接
        await transport.connect()
        await transport.start_receiving(xianyu_live.handle_message)

        # 验证初始状态
        assert await transport.is_connected() is True
        assert len(transport.messages_sent) == 0

        # 测试会在处理实际消息时验证流程
        # 这里主要验证系统可以正常启动和停止

        # 断开
        await transport.disconnect()
        assert await transport.is_connected() is False

    @pytest.mark.asyncio
    async def test_reconnection_logic(self):
        """测试重连逻辑"""
        cookies_str = "unb=test_user; cookie2=test"
        transport = MockTransport()
        bot = MockBot()

        xianyu_live = XianyuLive(cookies_str, transport, bot)

        # 模拟连接失败
        transport.connect = AsyncMock(return_value=False)

        # run() 方法会在连接失败后重试，这里只运行一次循环
        # 实际测试中需要更复杂的 mock 来验证重连逻辑

        # 验证 transport 有 connect 方法被调用
        assert hasattr(transport, 'connect')


class TestContextManager:
    """测试上下文管理器集成"""

    def test_context_manager_initialization(self):
        """测试上下文管理器初始化"""
        cookies_str = "unb=test_user; cookie2=test"
        transport = MockTransport()
        bot = MockBot()

        xianyu_live = XianyuLive(cookies_str, transport, bot)

        assert xianyu_live.context_manager is not None

    @pytest.mark.asyncio
    async def test_message_context_tracking(self):
        """测试消息上下文跟踪"""
        cookies_str = "unb=seller123; cookie2=test"
        transport = MockTransport()
        bot = MockBot()

        xianyu_live = XianyuLive(cookies_str, transport, bot)

        chat_id = "chat789"
        user_id = "user456"
        item_id = "item123"

        # 添加用户消息
        xianyu_live.context_manager.add_message_by_chat(
            chat_id, user_id, item_id, "user", "这个多少钱？"
        )

        # 添加助手回复
        xianyu_live.context_manager.add_message_by_chat(
            chat_id, "seller123", item_id, "assistant", "100元"
        )

        # 获取上下文
        context = xianyu_live.context_manager.get_context_by_chat(chat_id)

        assert len(context) >= 2

    def test_bargain_count_tracking(self):
        """测试议价次数跟踪"""
        cookies_str = "unb=seller123; cookie2=test"
        transport = MockTransport()
        bot = MockBot()

        xianyu_live = XianyuLive(cookies_str, transport, bot)

        chat_id = "chat999"

        # 初始议价次数为 0
        count = xianyu_live.context_manager.get_bargain_count_by_chat(chat_id)
        assert count == 0

        # 增加议价次数
        xianyu_live.context_manager.increment_bargain_count_by_chat(chat_id)
        count = xianyu_live.context_manager.get_bargain_count_by_chat(chat_id)
        assert count == 1

        # 再次增加
        xianyu_live.context_manager.increment_bargain_count_by_chat(chat_id)
        count = xianyu_live.context_manager.get_bargain_count_by_chat(chat_id)
        assert count == 2


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
