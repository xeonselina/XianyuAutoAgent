import asyncio
import json
import os
from typing import Dict, List, Optional, Callable
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from loguru import logger
import time
from pathlib import Path
import hashlib


class GoofishBrowser:
    def __init__(self, headless: bool = False, data_dir: str = "./goofish_data"):
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_running = False
        self.message_callback: Optional[Callable] = None
        
        # 数据存储配置
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.last_messages_file = self.data_dir / "last_messages.json"
        self.contact_states_file = self.data_dir / "contact_states.json"
        
        # 加载持久化数据
        self.last_processed_messages = self._load_last_messages()
        self.contact_states = self._load_contact_states()
    
    def _load_last_messages(self) -> Dict[str, str]:
        """加载最后处理的消息记录"""
        try:
            if self.last_messages_file.exists():
                with open(self.last_messages_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"已加载最后处理的消息记录: {len(data)} 个联系人")
                return data
        except Exception as e:
            logger.error(f"加载消息记录失败: {e}")
        return {}
    
    def _save_last_messages(self):
        """保存最后处理的消息记录"""
        try:
            with open(self.last_messages_file, 'w', encoding='utf-8') as f:
                json.dump(self.last_processed_messages, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存消息记录失败: {e}")
    
    def _load_contact_states(self) -> Dict[str, Dict]:
        """加载联系人状态记录"""
        try:
            if self.contact_states_file.exists():
                with open(self.contact_states_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                logger.info(f"已加载联系人状态记录: {len(data)} 个联系人")
                return data
        except Exception as e:
            logger.error(f"加载联系人状态失败: {e}")
        return {}
    
    def _save_contact_states(self):
        """保存联系人状态记录"""
        try:
            with open(self.contact_states_file, 'w', encoding='utf-8') as f:
                json.dump(self.contact_states, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"保存联系人状态失败: {e}")
    
    def _generate_message_hash(self, message: Dict) -> str:
        """生成消息的唯一哈希标识"""
        # 使用消息内容、时间戳、发送者生成唯一标识
        content = f"{message.get('text', '')}{message.get('timestamp', '')}{message.get('sender', '')}"
        return hashlib.md5(content.encode('utf-8')).hexdigest()
        
    async def start(self):
        """启动浏览器并打开咸鱼页面"""
        try:
            playwright = await async_playwright().start()
            self.browser = await playwright.chromium.launch(
                headless=self.headless,
                args=['--no-sandbox', '--disable-setuid-sandbox']
            )
            
            self.context = await self.browser.new_context(
                viewport={'width': 1920, 'height': 1080},
                user_agent='Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            )
            
            self.page = await self.context.new_page()
            
            # 导航到咸鱼页面
            await self.page.goto('https://www.goofish.com', wait_until='domcontentloaded')
            logger.info("浏览器已启动，咸鱼页面已加载")
            
            self.is_running = True
            return True
            
        except Exception as e:
            logger.error(f"启动浏览器失败: {e}")
            return False
    
    async def wait_for_login(self, timeout: int = 300000):
        """等待用户登录"""
        try:
            logger.info("等待用户登录...")
            
            # 等待登录完成的标志，比如用户头像或者聊天界面出现
            await self.page.wait_for_selector('.message-list, .chat-container, .user-avatar', timeout=timeout)
            
            logger.info("检测到用户已登录")
            return True
            
        except Exception as e:
            logger.error(f"等待登录超时或失败: {e}")
            return False
    
    async def get_chat_messages(self) -> List[Dict]:
        """获取聊天消息"""
        try:
            # 这里需要根据实际的咸鱼页面DOM结构来调整选择器
            messages = []
            
            # 等待消息容器加载
            await self.page.wait_for_selector('.message-list, .chat-list', timeout=5000)
            
            # 获取所有消息元素
            message_elements = await self.page.query_selector_all('.message-item, .chat-message')
            
            for element in message_elements:
                try:
                    # 获取消息文本
                    text_element = await element.query_selector('.message-text, .text-content')
                    text = await text_element.inner_text() if text_element else ""
                    
                    # 获取发送者信息
                    sender_element = await element.query_selector('.sender-name, .user-name')
                    sender = await sender_element.inner_text() if sender_element else ""
                    
                    # 获取时间戳
                    time_element = await element.query_selector('.message-time, .timestamp')
                    timestamp = await time_element.inner_text() if time_element else ""
                    
                    # 判断是否是收到的消息（非自己发送）
                    is_received = await element.evaluate('el => el.classList.contains("received") || el.classList.contains("incoming")')
                    
                    if text and is_received:
                        messages.append({
                            'text': text,
                            'sender': sender,
                            'timestamp': timestamp,
                            'type': 'received'
                        })
                        
                except Exception as e:
                    logger.warning(f"解析消息元素失败: {e}")
                    continue
            
            return messages
            
        except Exception as e:
            logger.error(f"获取聊天消息失败: {e}")
            return []
    
    async def send_message(self, message: str) -> bool:
        """发送消息"""
        try:
            # 查找输入框
            input_selector = 'textarea[placeholder*="输入"], input[placeholder*="消息"], .message-input textarea, .chat-input textarea'
            input_element = await self.page.wait_for_selector(input_selector, timeout=5000)
            
            if not input_element:
                logger.error("找不到消息输入框")
                return False
            
            # 清空输入框并输入消息
            await input_element.click()
            await input_element.fill('')
            await input_element.type(message)
            
            # 查找并点击发送按钮
            send_selectors = [
                'button[title*="发送"]',
                'button:has-text("发送")',
                '.send-button',
                '.message-send-btn',
                'button[data-testid="send"]'
            ]
            
            send_button = None
            for selector in send_selectors:
                try:
                    send_button = await self.page.query_selector(selector)
                    if send_button:
                        break
                except:
                    continue
            
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
    
    async def monitor_new_messages(self, callback: Callable[[Dict], None]):
        """监控新消息 - 使用持久化存储和新消息标记串行处理"""
        self.message_callback = callback
        
        logger.info("开始监控新消息，使用持久化存储和串行处理模式")
        
        while self.is_running:
            try:
                # 等待下一条新消息
                new_message = await self._wait_for_next_new_message()
                
                if new_message:
                    # 串行处理这条消息
                    logger.info(f"检测到新消息，开始处理: {new_message.get('text', '')[:50]}...")
                    await self._process_single_message(new_message)
                    logger.info(f"消息处理完毕")
                
            except Exception as e:
                logger.error(f"监控消息失败: {e}")
                await asyncio.sleep(5)
        
        logger.info("消息监控已停止")
    
    async def _wait_for_next_new_message(self, poll_interval: float = 2.0) -> Optional[Dict]:
        """等待下一条新消息 - 结合新消息标记和持久化存储判断"""
        while self.is_running:
            try:
                # 1. 首先检查有新消息标记的联系人
                contacts_with_indicators = await self.check_for_new_message_indicators()
                
                if not contacts_with_indicators:
                    # 没有新消息标记，等待后继续
                    await asyncio.sleep(poll_interval)
                    continue
                
                # 2. 遍历有新消息标记的联系人，检查具体的新消息
                for contact in contacts_with_indicators:
                    contact_name = contact['name']
                    
                    # 进入该联系人的聊天
                    if not await self.select_contact(contact_name):
                        logger.warning(f"无法进入联系人 {contact_name} 的聊天")
                        continue
                    
                    # 获取该联系人的最新消息
                    current_messages = await self.get_chat_messages()
                    
                    # 找到真正的新消息
                    new_message = self._find_new_message_for_contact(contact_name, current_messages)
                    
                    if new_message:
                        # 更新持久化存储
                        self._update_last_processed_message(contact_name, new_message)
                        return new_message
                
                # 所有有标记的联系人都检查完了，但没找到真正的新消息
                # 可能是误报，等待后继续
                await asyncio.sleep(poll_interval)
                
            except Exception as e:
                logger.error(f"等待新消息时出错: {e}")
                await asyncio.sleep(poll_interval * 2)
        
        return None
    
    def _find_new_message_for_contact(self, contact_name: str, messages: List[Dict]) -> Optional[Dict]:
        """为特定联系人找到新消息"""
        try:
            if not messages:
                return None
            
            # 获取该联系人最后处理的消息哈希
            last_message_hash = self.last_processed_messages.get(contact_name, "")
            
            # 从最新消息开始检查
            for message in reversed(messages):
                message_hash = self._generate_message_hash(message)
                
                # 如果找到了之前处理过的消息，说明后面的都是新消息
                if message_hash == last_message_hash:
                    break
                
                # 这是一条新消息
                if message.get('type') == 'received':  # 只处理收到的消息
                    logger.debug(f"找到联系人 {contact_name} 的新消息: {message.get('text', '')[:30]}")
                    return message
            
            # 如果没有找到之前的消息标记，可能是首次处理该联系人
            # 只处理最新的一条收到的消息
            for message in reversed(messages):
                if message.get('type') == 'received':
                    if not last_message_hash:  # 首次处理
                        logger.debug(f"首次处理联系人 {contact_name}，获取最新消息: {message.get('text', '')[:30]}")
                        return message
                    break
            
            return None
            
        except Exception as e:
            logger.error(f"查找联系人 {contact_name} 新消息时出错: {e}")
            return None
    
    def _update_last_processed_message(self, contact_name: str, message: Dict):
        """更新联系人最后处理的消息"""
        try:
            message_hash = self._generate_message_hash(message)
            self.last_processed_messages[contact_name] = message_hash
            
            # 立即保存到磁盘
            self._save_last_messages()
            
            logger.debug(f"更新联系人 {contact_name} 最后处理的消息: {message_hash[:8]}...")
            
        except Exception as e:
            logger.error(f"更新最后处理消息时出错: {e}")
    
    async def _process_single_message(self, message: Dict):
        """处理单条消息 - 确保完全处理完毕再返回"""
        try:
            if not self.message_callback:
                logger.warning("没有设置消息处理回调函数")
                return
            
            logger.debug(f"开始处理消息: {message}")
            
            # 调用回调函数处理消息
            if asyncio.iscoroutinefunction(self.message_callback):
                await self.message_callback(message)
            else:
                # 对于同步回调函数，在线程池中执行以避免阻塞
                await asyncio.get_event_loop().run_in_executor(None, self.message_callback, message)
            
            logger.debug(f"消息处理成功: {message.get('text', '')[:50]}...")
            
        except Exception as e:
            logger.error(f"处理单条消息失败: {e}")
            logger.error(f"消息内容: {message}")
            # 不重新抛出异常，继续处理下一条消息
    
    async def check_for_new_message_indicators(self) -> List[Dict]:
        """检查有新消息标记的联系人"""
        try:
            contacts_with_new_messages = []
            
            # 等待联系人列表加载
            await self.page.wait_for_selector('.contact-list, .chat-list-item', timeout=5000)
            
            contact_elements = await self.page.query_selector_all('.contact-item, .chat-list-item')
            
            for element in contact_elements:
                try:
                    # 获取联系人名称
                    name_element = await element.query_selector('.contact-name, .user-name')
                    name = await name_element.inner_text() if name_element else ""
                    
                    if not name:
                        continue
                    
                    # 检查新消息标记 - 通常是红点、数字徽章或特殊样式
                    has_new_message_indicator = await self._check_new_message_indicator(element)
                    
                    if has_new_message_indicator:
                        # 获取更多信息
                        avatar_element = await element.query_selector('.avatar img, .user-avatar img')
                        avatar = await avatar_element.get_attribute('src') if avatar_element else ""
                        
                        last_message_element = await element.query_selector('.last-message, .recent-message')
                        last_message = await last_message_element.inner_text() if last_message_element else ""
                        
                        contacts_with_new_messages.append({
                            'name': name,
                            'avatar': avatar,
                            'last_message': last_message,
                            'has_new_message_indicator': True
                        })
                        logger.debug(f"联系人 {name} 有新消息标记")
                        
                except Exception as e:
                    logger.warning(f"检查联系人新消息标记失败: {e}")
                    continue
            
            return contacts_with_new_messages
            
        except Exception as e:
            logger.error(f"检查新消息标记失败: {e}")
            return []
    
    async def _check_new_message_indicator(self, contact_element) -> bool:
        """检查单个联系人是否有新消息标记"""
        try:
            # 常见的新消息标记选择器
            indicator_selectors = [
                '.unread-badge',          # 未读徽章
                '.message-count',         # 消息计数
                '.red-dot',               # 红点
                '.new-message-indicator', # 新消息指示器
                '[class*="unread"]',      # 包含unread的class
                '[class*="new"]',         # 包含new的class
                '.badge',                 # 通用徽章
                '.notification-dot'       # 通知点
            ]
            
            for selector in indicator_selectors:
                try:
                    indicator = await contact_element.query_selector(selector)
                    if indicator:
                        # 检查是否可见
                        is_visible = await indicator.is_visible()
                        if is_visible:
                            logger.debug(f"找到新消息标记: {selector}")
                            return True
                except:
                    continue
            
            # 检查样式类是否包含新消息相关的标记
            class_name = await contact_element.get_attribute('class') or ""
            new_message_classes = ['unread', 'new-message', 'has-new', 'notification']
            
            for cls in new_message_classes:
                if cls in class_name.lower():
                    logger.debug(f"通过class检测到新消息: {cls}")
                    return True
            
            return False
            
        except Exception as e:
            logger.warning(f"检查新消息标记时出错: {e}")
            return False

    async def get_contact_list(self) -> List[Dict]:
        """获取联系人列表"""
        try:
            contacts = []
            
            # 等待联系人列表加载
            await self.page.wait_for_selector('.contact-list, .chat-list-item', timeout=5000)
            
            contact_elements = await self.page.query_selector_all('.contact-item, .chat-list-item')
            
            for element in contact_elements:
                try:
                    name_element = await element.query_selector('.contact-name, .user-name')
                    name = await name_element.inner_text() if name_element else ""
                    
                    avatar_element = await element.query_selector('.avatar img, .user-avatar img')
                    avatar = await avatar_element.get_attribute('src') if avatar_element else ""
                    
                    last_message_element = await element.query_selector('.last-message, .recent-message')
                    last_message = await last_message_element.inner_text() if last_message_element else ""
                    
                    # 检查是否有新消息标记
                    has_new_message_indicator = await self._check_new_message_indicator(element)
                    
                    if name:
                        contacts.append({
                            'name': name,
                            'avatar': avatar,
                            'last_message': last_message,
                            'has_new_message_indicator': has_new_message_indicator
                        })
                        
                except Exception as e:
                    logger.warning(f"解析联系人元素失败: {e}")
                    continue
            
            return contacts
            
        except Exception as e:
            logger.error(f"获取联系人列表失败: {e}")
            return []
    
    async def select_contact(self, contact_name: str) -> bool:
        """选择联系人进入聊天"""
        try:
            contact_elements = await self.page.query_selector_all('.contact-item, .chat-list-item')
            
            for element in contact_elements:
                name_element = await element.query_selector('.contact-name, .user-name')
                if name_element:
                    name = await name_element.inner_text()
                    if contact_name in name:
                        await element.click()
                        logger.info(f"已选择联系人: {contact_name}")
                        await asyncio.sleep(1)  # 等待聊天界面加载
                        return True
            
            logger.warning(f"未找到联系人: {contact_name}")
            return False
            
        except Exception as e:
            logger.error(f"选择联系人失败: {e}")
            return False
    
    async def close(self):
        """关闭浏览器"""
        self.is_running = False
        
        try:
            # 保存持久化数据
            self._save_last_messages()
            self._save_contact_states()
            logger.info("已保存持久化数据")
            
            if self.page:
                await self.page.close()
            if self.context:
                await self.context.close()
            if self.browser:
                await self.browser.close()
                
            logger.info("浏览器已关闭")
            
        except Exception as e:
            logger.error(f"关闭浏览器失败: {e}")
    
    def reset_message_history(self, contact_name: str = None):
        """重置消息历史记录（用于测试或重新开始）"""
        if contact_name:
            # 重置特定联系人的消息历史
            if contact_name in self.last_processed_messages:
                del self.last_processed_messages[contact_name]
                self._save_last_messages()
                logger.info(f"已重置联系人 {contact_name} 的消息历史")
        else:
            # 重置所有消息历史
            self.last_processed_messages.clear()
            self._save_last_messages()
            logger.info("已重置所有消息历史")
    
    def get_message_stats(self) -> Dict:
        """获取消息处理统计信息"""
        return {
            'total_contacts': len(self.last_processed_messages),
            'contacts_with_history': list(self.last_processed_messages.keys()),
            'data_dir': str(self.data_dir),
            'last_messages_file': str(self.last_messages_file),
            'contact_states_file': str(self.contact_states_file)
        }