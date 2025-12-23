"""
传输层单元测试
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from transports import DirectWebSocketTransport, BrowserWebSocketTransport
from browser_controller import BrowserConfig


class TestDirectWebSocketTransport:
    """测试直接 WebSocket 传输"""

    def test_initialization(self):
        """测试初始化"""
        cookies_str = "unb=test_user; cookie2=test"
        transport = DirectWebSocketTransport(cookies_str)

        assert transport.cookies_str == cookies_str
        assert transport.myid == "test_user"
        assert transport._is_connected is False
        assert transport.ws is None

    def test_configuration_from_env(self):
        """测试从环境变量加载配置"""
        with patch.dict('os.environ', {
            'HEARTBEAT_INTERVAL': '20',
            'HEARTBEAT_TIMEOUT': '10',
            'TOKEN_REFRESH_INTERVAL': '7200'
        }):
            cookies_str = "unb=test_user; cookie2=test"
            transport = DirectWebSocketTransport(cookies_str)

            assert transport.heartbeat_interval == 20
            assert transport.heartbeat_timeout == 10
            assert transport.token_refresh_interval == 7200

    @pytest.mark.asyncio
    async def test_send_message_not_connected(self):
        """测试未连接时发送消息"""
        cookies_str = "unb=test_user; cookie2=test"
        transport = DirectWebSocketTransport(cookies_str)

        result = await transport.send_message("chat1", "user1", "你好")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_connected(self):
        """测试连接状态检查"""
        cookies_str = "unb=test_user; cookie2=test"
        transport = DirectWebSocketTransport(cookies_str)

        # 初始状态未连接
        assert await transport.is_connected() is False

        # 模拟连接
        transport._is_connected = True
        transport.ws = Mock()
        assert await transport.is_connected() is True

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """测试断开连接"""
        cookies_str = "unb=test_user; cookie2=test"
        transport = DirectWebSocketTransport(cookies_str)

        # 模拟已连接状态
        transport._is_connected = True
        mock_ws = AsyncMock()
        transport.ws = mock_ws
        transport.heartbeat_task = asyncio.create_task(asyncio.sleep(0))
        transport.token_refresh_task = asyncio.create_task(asyncio.sleep(0))

        await transport.disconnect()

        # 验证连接已关闭
        assert transport._is_connected is False
        mock_ws.close.assert_called_once()
        assert transport.ws is None


class TestBrowserWebSocketTransport:
    """测试浏览器 WebSocket 传输"""

    def test_initialization(self):
        """测试初始化"""
        cookies_str = "unb=test_user; cookie2=test"
        config = BrowserConfig()
        transport = BrowserWebSocketTransport(cookies_str, config)

        assert transport.cookies_str == cookies_str
        assert transport.browser_controller is not None
        assert transport.cdp_interceptor is None
        assert transport._is_connected is False

    def test_initialization_without_config(self):
        """测试无配置初始化"""
        cookies_str = "unb=test_user; cookie2=test"
        transport = BrowserWebSocketTransport(cookies_str)

        assert transport.browser_controller is not None

    @pytest.mark.asyncio
    async def test_disconnect(self):
        """测试断开连接"""
        cookies_str = "unb=test_user; cookie2=test"
        transport = BrowserWebSocketTransport(cookies_str)

        # 模拟已连接状态
        transport._is_connected = True
        transport.cdp_interceptor = AsyncMock()
        transport.browser_controller.close = AsyncMock()

        await transport.disconnect()

        # 验证连接已关闭
        assert transport._is_connected is False
        transport.cdp_interceptor.close.assert_called_once()
        transport.browser_controller.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_message_not_connected(self):
        """测试未连接时发送消息"""
        cookies_str = "unb=test_user; cookie2=test"
        transport = BrowserWebSocketTransport(cookies_str)

        result = await transport.send_message("chat1", "user1", "你好")
        assert result is False

    @pytest.mark.asyncio
    async def test_is_connected_all_components(self):
        """测试连接状态检查（所有组件）"""
        cookies_str = "unb=test_user; cookie2=test"
        transport = BrowserWebSocketTransport(cookies_str)

        # 初始状态未连接
        assert await transport.is_connected() is False

        # 模拟部分组件连接
        transport._is_connected = True
        assert await transport.is_connected() is False

        # 模拟浏览器运行
        transport.browser_controller.is_running = Mock(return_value=True)
        assert await transport.is_connected() is False

        # 模拟 CDP 连接
        mock_cdp = Mock()
        mock_cdp.is_connected = Mock(return_value=True)
        transport.cdp_interceptor = mock_cdp
        assert await transport.is_connected() is True


class TestTransportComparison:
    """测试两种传输模式的行为一致性"""

    @pytest.mark.asyncio
    async def test_both_implement_interface(self):
        """测试两种传输都实现了接口"""
        from messaging_core import MessageTransport

        cookies_str = "unb=test_user; cookie2=test"

        # DirectWebSocketTransport
        direct_transport = DirectWebSocketTransport(cookies_str)
        assert isinstance(direct_transport, MessageTransport)

        # BrowserWebSocketTransport
        browser_transport = BrowserWebSocketTransport(cookies_str)
        assert isinstance(browser_transport, MessageTransport)

    @pytest.mark.asyncio
    async def test_both_support_send_message(self):
        """测试两种传输都支持发送消息"""
        cookies_str = "unb=test_user; cookie2=test"

        # DirectWebSocketTransport
        direct_transport = DirectWebSocketTransport(cookies_str)
        assert hasattr(direct_transport, 'send_message')
        assert callable(direct_transport.send_message)

        # BrowserWebSocketTransport
        browser_transport = BrowserWebSocketTransport(cookies_str)
        assert hasattr(browser_transport, 'send_message')
        assert callable(browser_transport.send_message)

    @pytest.mark.asyncio
    async def test_both_support_lifecycle(self):
        """测试两种传输都支持生命周期管理"""
        cookies_str = "unb=test_user; cookie2=test"

        for TransportClass in [DirectWebSocketTransport, BrowserWebSocketTransport]:
            transport = TransportClass(cookies_str)

            # 检查生命周期方法
            assert hasattr(transport, 'connect')
            assert callable(transport.connect)

            assert hasattr(transport, 'disconnect')
            assert callable(transport.disconnect)

            assert hasattr(transport, 'is_connected')
            assert callable(transport.is_connected)

            assert hasattr(transport, 'start_receiving')
            assert callable(transport.start_receiving)


class TestBrowserConfig:
    """测试浏览器配置"""

    def test_default_configuration(self):
        """测试默认配置"""
        config = BrowserConfig()

        assert config.headless is False  # 默认显示浏览器
        assert config.user_data_dir == "./browser_data"
        assert config.viewport_width == 1280
        assert config.viewport_height == 720
        assert config.debug_port is None
        assert config.proxy is None

    def test_configuration_from_env(self):
        """测试从环境变量加载配置"""
        with patch.dict('os.environ', {
            'BROWSER_HEADLESS': 'true',
            'BROWSER_DEBUG_PORT': '9222',
            'BROWSER_USER_DATA_DIR': '/custom/path',
            'BROWSER_VIEWPORT_WIDTH': '1920',
            'BROWSER_VIEWPORT_HEIGHT': '1080',
            'BROWSER_PROXY': 'http://proxy:8080'
        }):
            config = BrowserConfig()

            assert config.headless is True
            assert config.debug_port == '9222'
            assert config.user_data_dir == '/custom/path'
            assert config.viewport_width == 1920
            assert config.viewport_height == 1080
            assert config.proxy == 'http://proxy:8080'

    def test_headless_parsing(self):
        """测试 headless 参数解析"""
        # true 值
        for value in ['true', 'True', 'TRUE']:
            with patch.dict('os.environ', {'BROWSER_HEADLESS': value}):
                config = BrowserConfig()
                assert config.headless is True

        # false 值
        for value in ['false', 'False', 'FALSE', '']:
            with patch.dict('os.environ', {'BROWSER_HEADLESS': value}):
                config = BrowserConfig()
                assert config.headless is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
