#!/usr/bin/env python3
"""
咸鱼AI客服主程序

功能：
1. 启动浏览器，打开咸鱼页面
2. 监控客户消息
3. 使用AI生成回复
4. 自动发送回复或通知人工介入
"""

import asyncio
import signal
import sys
from typing import Optional

from config.settings import get_settings
from utils.logger import setup_logger, get_logger
from browser.goofish_browser import GoofishBrowser
from browser.dom_parser import GoofishDOMParser
from service.message_service import MessageService
from service.ai_service import DifyAIService, QwenAIService
from service.notification_service import WechatNotificationService, EmailNotificationService, NotificationManager


class GoofishAIBot:
    """咸鱼AI客服机器人"""
    
    def __init__(self):
        self.settings = get_settings()
        self.logger = get_logger("GoofishAIBot")
        
        # 核心组件
        self.browser: Optional[GoofishBrowser] = None
        self.dom_parser: Optional[GoofishDOMParser] = None
        self.message_service: Optional[MessageService] = None
        self.ai_service = None
        self.notification_manager: Optional[NotificationManager] = None
        
        # 运行状态
        self.is_running = False
        self.tasks = []
    
    async def initialize(self):
        """初始化所有组件"""
        try:
            self.logger.info("开始初始化咸鱼AI客服系统...")
            
            # 验证配置
            if not self.settings.validate_config():
                self.logger.error("配置验证失败")
                return False
            
            # 初始化浏览器
            await self._init_browser()
            
            # 初始化AI服务
            await self._init_ai_service()
            
            # 初始化消息服务
            await self._init_message_service()
            
            # 初始化通知服务
            await self._init_notification_service()
            
            self.logger.info("系统初始化完成")
            return True
            
        except Exception as e:
            self.logger.error(f"初始化失败: {e}")
            return False
    
    async def _init_browser(self):
        """初始化浏览器"""
        self.logger.info("初始化浏览器...")
        
        self.browser = GoofishBrowser(headless=self.settings.browser.headless)
        
        # 启动浏览器
        success = await self.browser.start()
        if not success:
            raise Exception("浏览器启动失败")
        
        # 等待用户登录
        self.logger.info("请在浏览器中登录咸鱼账号...")
        login_success = await self.browser.wait_for_login(
            timeout=self.settings.browser.login_timeout
        )
        
        if not login_success:
            raise Exception("等待登录超时")
        
        # 初始化DOM解析器
        self.dom_parser = GoofishDOMParser(self.browser.page)
        
        self.logger.info("浏览器初始化完成")
    
    async def _init_ai_service(self):
        """初始化AI服务"""
        self.logger.info(f"初始化AI服务: {self.settings.ai.ai_service_type}")
        
        if self.settings.ai.ai_service_type == "dify":
            self.ai_service = DifyAIService(
                dify_api_url=self.settings.ai.dify_api_url,
                api_key=self.settings.ai.dify_api_key
            )
        elif self.settings.ai.ai_service_type == "qwen":
            self.ai_service = QwenAIService(
                api_key=self.settings.ai.qwen_api_key,
                model_name=self.settings.ai.qwen_model_name
            )
        else:
            raise Exception(f"不支持的AI服务类型: {self.settings.ai.ai_service_type}")
        
        self.logger.info("AI服务初始化完成")
    
    async def _init_message_service(self):
        """初始化消息服务"""
        self.logger.info("初始化消息服务...")
        
        self.message_service = MessageService()
        
        # 设置依赖服务
        self.message_service.set_ai_service(self.ai_service)
        self.message_service.set_browser_service(self.browser)
        
        self.logger.info("消息服务初始化完成")
    
    async def _init_notification_service(self):
        """初始化通知服务"""
        self.logger.info("初始化通知服务...")
        
        self.notification_manager = NotificationManager()
        
        if not self.settings.notification.enable_notifications:
            self.notification_manager.disable()
            self.logger.info("通知服务已禁用")
            return
        
        # 添加微信通知
        if self.settings.notification.wechat_webhook_url:
            wechat_service = WechatNotificationService(
                webhook_url=self.settings.notification.wechat_webhook_url
            )
            self.notification_manager.add_service(wechat_service)
        
        # 添加邮件通知
        if self.settings.notification.email_smtp_server:
            email_service = EmailNotificationService(
                smtp_server=self.settings.notification.email_smtp_server,
                smtp_port=self.settings.notification.email_smtp_port,
                username=self.settings.notification.email_username,
                password=self.settings.notification.email_password,
                recipients=self.settings.notification.email_recipients
            )
            self.notification_manager.add_service(email_service)
        
        # 设置到消息服务
        self.message_service.set_notification_service(self.notification_manager)
        
        self.logger.info("通知服务初始化完成")
    
    async def start(self):
        """启动机器人"""
        try:
            if not await self.initialize():
                return False
            
            self.is_running = True
            
            # 启动消息监控任务
            monitor_task = asyncio.create_task(self._monitor_messages())
            self.tasks.append(monitor_task)
            
            # 启动消息服务器任务
            server_task = asyncio.create_task(
                self.message_service.start_server(
                    host=self.settings.server.host,
                    port=self.settings.server.port
                )
            )
            self.tasks.append(server_task)
            
            self.logger.info("咸鱼AI客服系统启动成功")
            
            # 发送启动通知
            if self.notification_manager:
                await self.notification_manager.send_system_alert(
                    "系统启动",
                    "咸鱼AI客服系统已成功启动，开始监控消息"
                )
            
            # 等待所有任务完成
            await asyncio.gather(*self.tasks, return_exceptions=True)
            
        except Exception as e:
            self.logger.error(f"启动失败: {e}")
            return False
        
        return True
    
    async def _monitor_messages(self):
        """监控消息"""
        self.logger.info("开始监控咸鱼消息...")
        
        async def message_callback(message):
            """新消息回调"""
            try:
                # 发送消息到消息服务
                message_data = {
                    'text': message.get('text', ''),
                    'sender': message.get('sender', ''),
                    'timestamp': message.get('timestamp', ''),
                    'type': 'received'
                }
                
                await self.message_service.process_incoming_message(message_data)
                
            except Exception as e:
                self.logger.error(f"处理新消息失败: {e}")
        
        # 开始监控
        await self.browser.monitor_new_messages(message_callback)
    
    async def stop(self):
        """停止机器人"""
        self.logger.info("正在停止咸鱼AI客服系统...")
        
        self.is_running = False
        
        # 取消所有任务
        for task in self.tasks:
            if not task.done():
                task.cancel()
        
        # 清理资源
        if self.browser:
            await self.browser.close()
        
        if self.message_service:
            await self.message_service.shutdown()
        
        if self.ai_service and hasattr(self.ai_service, 'close'):
            await self.ai_service.close()
        
        if self.notification_manager:
            await self.notification_manager.close()
        
        self.logger.info("系统已停止")
    
    def setup_signal_handlers(self):
        """设置信号处理器"""
        def signal_handler(signum, frame):
            self.logger.info(f"收到信号 {signum}，准备停止...")
            # 创建新的事件循环来运行stop()
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            loop.run_until_complete(self.stop())
            loop.close()
            sys.exit(0)
        
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)


async def main():
    """主函数"""
    # 设置日志
    settings = get_settings()
    setup_logger(
        log_level=settings.log.level,
        log_file=settings.log.log_file
    )
    
    logger = get_logger("Main")
    logger.info("启动咸鱼AI客服系统")
    
    # 创建并启动机器人
    bot = GoofishAIBot()
    bot.setup_signal_handlers()
    
    try:
        await bot.start()
    except KeyboardInterrupt:
        logger.info("收到中断信号")
    except Exception as e:
        logger.error(f"系统运行异常: {e}")
    finally:
        await bot.stop()


if __name__ == "__main__":
    # Windows系统兼容性设置
    if sys.platform.startswith('win'):
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    asyncio.run(main())