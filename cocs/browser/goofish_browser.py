from typing import Dict, List, Callable
from loguru import logger
from .page_manager import PageManager
from .data_persistence import DataPersistence
from .message_monitor import MessageMonitor


class GoofishBrowser:
    """咸鱼浏览器主类 - 整合各个模块提供统一API"""

    def __init__(self, headless: bool = False, data_dir: str = "./goofish_data", viewport_width: int = 1000, viewport_height: int = 800, user_agent: str = None):
        self.headless = headless

        # 初始化各个模块
        self.page_manager = PageManager(
            headless=headless,
            viewport_width=viewport_width,
            viewport_height=viewport_height,
            user_agent=user_agent
        )
        self.data_persistence = DataPersistence(data_dir=data_dir)
        self.message_monitor = MessageMonitor(self.page_manager, self.data_persistence)

        # 状态标记
        self.is_running = False

    async def start(self) -> bool:
        """启动浏览器并打开咸鱼页面"""
        success = await self.page_manager.start()
        if success:
            self.is_running = True
        return success

    async def wait_for_login(self, timeout: int = 300000) -> bool:
        """等待用户登录"""
        return await self.page_manager.wait_for_login(timeout)

    async def get_chat_messages(self) -> List[Dict]:
        """获取聊天消息"""
        return await self.message_monitor.get_chat_messages()

    async def send_message(self, message: str) -> bool:
        """发送消息"""
        try:
            if not self.page_manager.dom_parser:
                logger.error("DOM解析器未初始化")
                return False

            # 查找输入框
            input_element = await self.page_manager.dom_parser.find_element_by_selectors(
                self.page_manager.dom_parser.selectors['input_box'],
                timeout=5000
            )

            if not input_element:
                logger.error("找不到消息输入框")
                return False

            # 清空输入框并输入消息
            await input_element.click()
            await input_element.fill('')
            await input_element.type(message)

            # 查找并点击发送按钮
            send_button = await self.page_manager.dom_parser.find_element_by_selectors(
                self.page_manager.dom_parser.selectors['send_button'],
                timeout=2000
            )

            if send_button:
                await send_button.click()
                logger.info(f"消息已发送: {message}")
                return True
            else:
                # 如果找不到发送按钮，尝试按回车键
                await input_element.press('Enter')
                logger.info(f"消息已发送（回车键): {message}")
                return True

        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False

    async def select_contact(self, contact_name: str) -> bool:
        """选择联系人进入聊天"""
        return await self.message_monitor.select_contact(contact_name)

    async def monitor_new_messages(self, callback: Callable[[Dict], None]):
        """监控新消息"""
        await self.message_monitor.monitor_new_messages(callback)

    def stop_monitoring(self):
        """停止监控"""
        self.message_monitor.stop_monitoring()

    async def check_for_new_message_indicators(self) -> List[Dict]:
        """检查有新消息标记的联系人"""
        return await self.message_monitor.check_for_new_message_indicators()

    def reset_message_history(self, contact_name: str = None):
        """重置消息历史记录"""
        self.data_persistence.reset_message_history(contact_name)

    def get_message_stats(self) -> Dict:
        """获取消息处理统计信息"""
        return self.data_persistence.get_message_stats()

    async def close(self):
        """关闭浏览器并保存数据"""
        self.is_running = False

        # 停止监控
        self.stop_monitoring()

        # 保存持久化数据
        self.data_persistence.save_all()

        # 关闭浏览器
        await self.page_manager.close()

    # 兼容性属性和方法
    @property
    def page(self):
        """兼容性属性：获取当前页面"""
        return self.page_manager.page

    @property
    def dom_parser(self):
        """兼容性属性：获取DOM解析器"""
        return self.page_manager.dom_parser

    @property
    def is_logged_in(self):
        """兼容性属性：获取登录状态"""
        return self.page_manager.is_logged_in

    async def ensure_active_page(self):
        """兼容性方法：确保活跃页面"""
        await self.page_manager.ensure_active_page()