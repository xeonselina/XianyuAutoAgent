import base64
import json
import asyncio
import time
import os
from loguru import logger
from dotenv import load_dotenv
from XianyuApis import XianyuApis
import sys
from typing import Optional

from utils.xianyu_utils import trans_cookies, decrypt
from XianyuAgent import XianyuReplyBot
from context_manager import ChatContextManager
from messaging_core import MessageTransport, XianyuMessageCodec, MessageType, Message
from transports import DirectWebSocketTransport, BrowserWebSocketTransport
from browser_controller import BrowserConfig


class XianyuLive:
    def __init__(self, cookies_str: str, transport: MessageTransport, bot: XianyuReplyBot):
        """
        初始化闲鱼客服系统

        Args:
            cookies_str: Cookie 字符串
            transport: 消息传输实现
            bot: AI 回复机器人
        """
        self.xianyu = XianyuApis()
        self.cookies_str = cookies_str
        self.cookies = trans_cookies(cookies_str)
        self.xianyu.session.cookies.update(self.cookies)
        self.myid = self.cookies['unb']
        self.context_manager = ChatContextManager()

        # 注入传输层和 AI 机器人
        self.transport = transport
        self.bot = bot

        # 人工接管相关配置
        self.manual_mode_conversations = set()  # 存储处于人工接管模式的会话ID
        self.manual_mode_timeout = int(os.getenv("MANUAL_MODE_TIMEOUT", "3600"))  # 人工接管超时时间，默认1小时
        self.manual_mode_timestamps = {}  # 记录进入人工模式的时间

        # 消息过期时间配置
        self.message_expire_time = int(os.getenv("MESSAGE_EXPIRE_TIME", "300000"))  # 消息过期时间，默认5分钟

        # 人工接管关键词，从环境变量读取
        self.toggle_keywords = os.getenv("TOGGLE_KEYWORDS", "。")

    def is_chat_message(self, message):
        """判断是否为用户聊天消息"""
        try:
            return (
                isinstance(message, dict) 
                and "1" in message 
                and isinstance(message["1"], dict)  # 确保是字典类型
                and "10" in message["1"]
                and isinstance(message["1"]["10"], dict)  # 确保是字典类型
                and "reminderContent" in message["1"]["10"]
            )
        except Exception:
            return False

    def is_sync_package(self, message_data):
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

    def is_typing_status(self, message):
        """判断是否为用户正在输入状态消息"""
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

    def is_system_message(self, message):
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

    def check_toggle_keywords(self, message):
        """检查消息是否包含切换关键词"""
        message_stripped = message.strip()
        return message_stripped in self.toggle_keywords

    def is_manual_mode(self, chat_id):
        """检查特定会话是否处于人工接管模式"""
        if chat_id not in self.manual_mode_conversations:
            return False
        
        # 检查是否超时
        current_time = time.time()
        if chat_id in self.manual_mode_timestamps:
            if current_time - self.manual_mode_timestamps[chat_id] > self.manual_mode_timeout:
                # 超时，自动退出人工模式
                self.exit_manual_mode(chat_id)
                return False
        
        return True

    def enter_manual_mode(self, chat_id):
        """进入人工接管模式"""
        self.manual_mode_conversations.add(chat_id)
        self.manual_mode_timestamps[chat_id] = time.time()

    def exit_manual_mode(self, chat_id):
        """退出人工接管模式"""
        self.manual_mode_conversations.discard(chat_id)
        if chat_id in self.manual_mode_timestamps:
            del self.manual_mode_timestamps[chat_id]

    def toggle_manual_mode(self, chat_id):
        """切换人工接管模式"""
        if self.is_manual_mode(chat_id):
            self.exit_manual_mode(chat_id)
            return "auto"
        else:
            self.enter_manual_mode(chat_id)
            return "manual"

    async def handle_message(self, message_data: dict) -> None:
        """
        处理接收到的消息

        Args:
            message_data: 原始消息数据
        """
        try:
            # 使用消息编解码器解码消息
            decoded_message = XianyuMessageCodec.decode_message(message_data)
            if not decoded_message:
                # 检查是否为订单消息 (需要特殊处理因为不会被 decode_message 解析)
                if self.is_sync_package(message_data):
                    sync_data = message_data["body"]["syncPushPackage"]["data"][0]
                    if "data" in sync_data:
                        try:
                            data = sync_data["data"]
                            try:
                                data_decoded = base64.b64decode(data).decode("utf-8")
                                message = json.loads(data_decoded)
                                return
                            except Exception:
                                decrypted_data = decrypt(data)
                                message = json.loads(decrypted_data)

                                # 处理订单消息
                                if '3' in message and 'redReminder' in message['3']:
                                    user_id = message['1'].split('@')[0]
                                    user_url = f'https://www.goofish.com/personal?userId={user_id}'
                                    reminder = message['3']['redReminder']
                                    if reminder == '等待买家付款':
                                        logger.info(f'等待买家 {user_url} 付款')
                                    elif reminder == '交易关闭':
                                        logger.info(f'买家 {user_url} 交易关闭')
                                    elif reminder == '等待卖家发货':
                                        logger.info(f'交易成功 {user_url} 等待卖家发货')
                                    return
                        except Exception:
                            pass
                return

            # 提取标准化消息
            std_message = XianyuMessageCodec.extract_message_data(decoded_message)
            if not std_message:
                return

            # 处理不同类型的消息
            if std_message.message_type == MessageType.TYPING:
                logger.debug("用户正在输入")
                return
            elif std_message.message_type == MessageType.SYSTEM:
                logger.debug("系统消息，跳过处理")
                return
            elif std_message.message_type == MessageType.ORDER:
                logger.info(f"订单消息: {std_message.content}")
                return
            elif std_message.message_type != MessageType.CHAT:
                logger.debug(f"其他类型消息: {std_message.message_type}")
                return

            # 处理聊天消息
            chat_id = std_message.chat_id
            user_id = std_message.user_id
            content = std_message.content
            item_id = std_message.item_id

            if not item_id:
                logger.warning("无法获取商品ID")
                return

            # 时效性验证（过滤5分钟前消息）
            if std_message.timestamp and (time.time() * 1000 - std_message.timestamp) > self.message_expire_time:
                logger.debug("过期消息丢弃")
                return

            # 检查是否为卖家（自己）发送的控制命令
            if user_id == self.myid:
                logger.debug("检测到卖家消息，检查是否为控制命令")

                # 检查切换命令
                if self.check_toggle_keywords(content):
                    mode = self.toggle_manual_mode(chat_id)
                    if mode == "manual":
                        logger.info(f"🔴 已接管会话 {chat_id} (商品: {item_id})")
                    else:
                        logger.info(f"🟢 已恢复会话 {chat_id} 的自动回复 (商品: {item_id})")
                    return

                # 记录卖家人工回复
                self.context_manager.add_message_by_chat(chat_id, self.myid, item_id, "assistant", content)
                logger.info(f"卖家人工回复 (会话: {chat_id}, 商品: {item_id}): {content}")
                return

            logger.info(f"用户 ID: {user_id}, 商品: {item_id}, 会话: {chat_id}, 消息: {content}")

            # 添加用户消息到上下文
            self.context_manager.add_message_by_chat(chat_id, user_id, item_id, "user", content)

            # 如果当前会话处于人工接管模式，不进行自动回复
            if self.is_manual_mode(chat_id):
                logger.info(f"🔴 会话 {chat_id} 处于人工接管模式，跳过自动回复")
                return

            # 从数据库中获取商品信息，如果不存在则从API获取并保存
            item_info = self.context_manager.get_item_info(item_id)
            if not item_info:
                logger.info(f"从API获取商品信息: {item_id}")
                api_result = self.xianyu.get_item_info(item_id)
                if 'data' in api_result and 'itemDO' in api_result['data']:
                    item_info = api_result['data']['itemDO']
                    # 保存商品信息到数据库
                    self.context_manager.save_item_info(item_id, item_info)
                else:
                    logger.warning(f"获取商品信息失败: {api_result}")
                    return
            else:
                logger.info(f"从数据库获取商品信息: {item_id}")

            item_description = f"{item_info['desc']};当前商品售卖价格为:{str(item_info['soldPrice'])}"

            # 获取完整的对话上下文
            context = self.context_manager.get_context_by_chat(chat_id)

            # 生成回复
            bot_reply = self.bot.generate_reply(
                content,
                item_description,
                context=context
            )

            # 检查是否为价格意图，如果是则增加议价次数
            if self.bot.last_intent == "price":
                self.context_manager.increment_bargain_count_by_chat(chat_id)
                bargain_count = self.context_manager.get_bargain_count_by_chat(chat_id)
                logger.info(f"用户 {user_id} 对商品 {item_id} 的议价次数: {bargain_count}")

            # 添加机器人回复到上下文
            self.context_manager.add_message_by_chat(chat_id, self.myid, item_id, "assistant", bot_reply)

            logger.info(f"机器人回复: {bot_reply}")

            # 通过传输层发送回复
            await self.transport.send_message(chat_id, user_id, bot_reply)

        except Exception as e:
            logger.error(f"处理消息时发生错误: {str(e)}")
            import traceback
            logger.debug(f"错误堆栈: {traceback.format_exc()}")

    async def run(self) -> None:
        """
        启动客服系统主循环（支持自动重连）
        """
        reconnect_delay = 30  # 重连延迟（秒）

        while True:
            try:
                # 建立传输连接
                logger.info("正在建立连接...")
                if not await self.transport.connect():
                    logger.error(f"连接失败，{reconnect_delay}秒后重试...")
                    await asyncio.sleep(reconnect_delay)
                    continue

                logger.info("连接建立成功，开始接收消息...")

                # 开始接收消息
                await self.transport.start_receiving(self.handle_message)

                # 保持运行，定期检查连接状态
                while await self.transport.is_connected():
                    await asyncio.sleep(1)

                logger.warning("传输连接已断开")

            except KeyboardInterrupt:
                logger.info("收到中断信号，正在关闭...")
                break

            except Exception as e:
                logger.error(f"运行时错误: {e}")
                import traceback
                logger.debug(f"错误堆栈: {traceback.format_exc()}")

            finally:
                # 断开连接
                try:
                    await self.transport.disconnect()
                except Exception as e:
                    logger.error(f"断开连接时出错: {e}")

            # 等待后重连
            logger.info(f"等待 {reconnect_delay} 秒后重连...")
            await asyncio.sleep(reconnect_delay)


def create_transport(cookies_str: str) -> MessageTransport:
    """
    创建消息传输实例（工厂函数）

    根据环境变量 USE_BROWSER_MODE 决定使用哪种传输模式。

    Args:
        cookies_str: Cookie 字符串

    Returns:
        MessageTransport: 传输实例
    """
    use_browser_mode = os.getenv("USE_BROWSER_MODE", "false").lower() == "true"

    if use_browser_mode:
        logger.info("使用浏览器模式 (BrowserWebSocketTransport)")

        # 创建浏览器配置
        browser_config = BrowserConfig()

        # 创建浏览器传输
        transport = BrowserWebSocketTransport(cookies_str, browser_config)
    else:
        logger.info("使用直接模式 (DirectWebSocketTransport)")

        # 创建直接 WebSocket 传输
        transport = DirectWebSocketTransport(cookies_str)

    return transport


if __name__ == '__main__':
    # 加载环境变量
    load_dotenv()

    # 配置日志级别
    log_level = os.getenv("LOG_LEVEL", "DEBUG").upper()
    logger.remove()  # 移除默认handler

    # 确保日志目录存在
    os.makedirs("logs", exist_ok=True)

    # 终端输出（彩色）
    logger.add(
        sys.stderr,
        level=log_level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>"
    )

    # 文件输出（保留历史日志）
    logger.add(
        "logs/xianyu_{time:YYYY-MM-DD}.log",  # 按日期分割日志文件
        level=log_level,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level: <8} | {name}:{function}:{line} - {message}",
        rotation="00:00",  # 每天午夜轮换
        retention="30 days",  # 保留30天
        encoding="utf-8",
        enqueue=True  # 异步写入，避免阻塞
    )

    logger.info(f"日志级别设置为: {log_level}")
    logger.info(f"日志文件保存在: logs/ 目录")

    # 获取 Cookie
    cookies_str = os.getenv("COOKIES_STR")
    if not cookies_str:
        logger.error("未设置 COOKIES_STR 环境变量")
        sys.exit(1)

    # 创建 AI 机器人
    bot = XianyuReplyBot()

    # 创建传输层
    transport = create_transport(cookies_str)

    # 创建客服系统实例
    xianyuLive = XianyuLive(cookies_str, transport, bot)

    # 运行客服系统
    asyncio.run(xianyuLive.run())
