from typing import Dict, List, Optional
from playwright.async_api import Page, ElementHandle
from loguru import logger
import json
import re
import time


class GoofishDOMParser:
    def __init__(self, page: Page):
        self.page = page
        
        # 咸鱼页面常见的选择器模式
        self.selectors = {
            # 消息列表容器
            'message_container': [
                'ul.ant-list-items'
            ],
            'message_item': [
                'li.ant-list-item'
            ],
            'sender_name': [
                'a[href*="personal?userId="]'
            ],
            'input_box': [
                'textarea[placeholder*="请输入消息"]'
            ],
            'send_button': [
                'button span'
            ],
            'unread_message': [
                '.ant-scroll-number-only-unit.current'
            ]
        }
    
    async def find_element_by_selectors(self, selectors: List[str], timeout: int = 5000) -> Optional[ElementHandle]:
        """通过多个选择器查找元素"""
        import asyncio

        start_time = asyncio.get_event_loop().time()
        end_time = start_time + timeout / 1000  # 转换为秒

        while asyncio.get_event_loop().time() < end_time:
            for selector in selectors:
                try:
                    logger.info(f"尝试查找选择器: {selector}")

                    # 首先使用 JavaScript 检查元素是否存在
                    element_exists = await self.page.evaluate(f"!!document.querySelector('{selector}')")
                    logger.info(f"JavaScript检查结果: {selector} 存在={element_exists}")

                    # 调试信息：检查当前页面URL和基本信息
                    current_url = self.page.url
                    page_title = await self.page.title()
                    logger.info(f"当前页面: URL={current_url}, Title={page_title}")

                    # 检查是否有iframe
                    iframe_count = await self.page.evaluate("document.querySelectorAll('iframe').length")
                    logger.info(f"页面中iframe数量: {iframe_count}")

                    # 检查页面中是否有任何ant相关的元素
                    ant_elements = await self.page.evaluate("document.querySelectorAll('[class*=\"ant\"]').length")
                    logger.info(f"页面中ant-相关元素数量: {ant_elements}")

                    # 检查iframe中是否有目标元素
                    if iframe_count > 0:
                        iframe_has_element = await self.page.evaluate(f"""
                            (() => {{
                                const iframes = document.querySelectorAll('iframe');
                                for (let iframe of iframes) {{
                                    try {{
                                        const doc = iframe.contentDocument || iframe.contentWindow.document;
                                        if (doc && doc.querySelector('{selector}')) {{
                                            return true;
                                        }}
                                    }} catch (e) {{
                                        // 跨域iframe无法访问
                                    }}
                                }}
                                return false;
                            }})()
                        """)
                        logger.info(f"iframe中是否有目标元素: {iframe_has_element}")

                        if iframe_has_element:
                            # 尝试切换到iframe并查找元素
                            frames = self.page.frames
                            for frame in frames:
                                if frame.name != "":  # 不是主框架
                                    try:
                                        element = await frame.query_selector(selector)
                                        if element:
                                            logger.info(f"在iframe中找到元素: {selector}")
                                            return element
                                    except Exception as e:
                                        logger.info(f"iframe查找失败: {e}")

                    # 检查是否需要导航到聊天页面
                    is_homepage = current_url == "https://www.goofish.com/"
                    if is_homepage:
                        logger.info("当前在首页，消息容器应该在聊天页面中")
                        # 可以在这里添加导航到聊天页面的逻辑

                    if element_exists:
                        # 如果元素存在，尝试获取元素句柄
                        try:
                            element = await self.page.query_selector(selector)
                            if element:
                                logger.info(f"成功找到元素: {selector}")
                                return element
                        except Exception as e2:
                            logger.warning(f"获取元素句柄失败: {e2}")

                    # 备用方法：使用 wait_for_selector
                    element = await self.page.wait_for_selector(selector, timeout=1000, state='attached')
                    if element:
                        logger.info(f"通过wait_for_selector找到元素: {selector}")
                        return element

                except Exception as e:
                    logger.info(f"查找选择器 {selector} 时出错: {e}, 继续重试...")
                    continue

            # 等待一段时间后重试
            logger.info("未找到任何元素，2秒后重试...")
            await asyncio.sleep(2)

        logger.error(f"超时：所有选择器都未找到元素: {selectors}")
        return None
    
    async def find_elements_by_selectors(self, selectors: List[str]) -> List[ElementHandle]:
        """通过多个选择器查找所有匹配的元素"""
        all_elements = []
        for selector in selectors:
            try:
                elements = await self.page.query_selector_all(selector)
                all_elements.extend(elements)
            except:
                continue
        return all_elements
    
    async def detect_message_structure(self) -> Dict:
        """自动检测消息结构"""
        logger.info("开始检测咸鱼页面消息结构...")
        
        structure = {
            'message_container': None,
            'message_items': [],
            'input_box': None,
            'send_button': None
        }
        
        # 检测消息容器
        container = await self.find_element_by_selectors(self.selectors['message_container'])
        if container:
            structure['message_container'] = await self._get_element_selector(container)
            logger.info(f"找到消息容器: {structure['message_container']}")
        
        # 检测消息项
        message_items = await self.find_elements_by_selectors(self.selectors['message_item'])
        for item in message_items:  # 只检测前5个
            item_info = await self._analyze_message_item(item)
            if item_info:
                structure['message_items'].append(item_info)
        
        # 检测输入框
        input_box = await self.find_element_by_selectors(self.selectors['input_box'])
        if input_box:
            structure['input_box'] = await self._get_element_selector(input_box)
            logger.info(f"找到输入框: {structure['input_box']}")
        
        # 检测发送按钮
        send_button = await self.find_element_by_selectors(self.selectors['send_button'])
        if send_button:
            structure['send_button'] = await self._get_element_selector(send_button)
            logger.info(f"找到发送按钮: {structure['send_button']}")
        
        return structure
    
    async def _analyze_message_item(self, element: ElementHandle) -> Optional[Dict]:
        """分析消息项结构"""
        try:
            # 直接获取元素文本内容
            text_content = await element.inner_text()
            
            if not text_content or len(text_content.strip()) == 0:
                return None
            
            # 判断消息方向（发送/接收）
            style = await element.get_attribute('style') or ''
            is_received = 'ltr' in style
            is_sent = 'rtl' in style
            
            # 获取类名
            class_names = await element.get_attribute('class') or ''
            
            # 获取时间戳（简化处理）
            timestamp = ""
            
            # 获取发送者信息
            sender_element = None
            for selector in self.selectors['sender_name']:
                try:
                    sender_element = await element.query_selector(selector)
                    if sender_element:
                        break
                except:
                    continue
            
            sender = ""
            if sender_element:
                sender = await sender_element.inner_text()
            
            return {
                'text': text_content.strip(),
                'timestamp': timestamp.strip(),
                'sender': sender.strip(),
                'is_received': is_received,
                'is_sent': is_sent
            }
            
        except Exception as e:
            logger.warning(f"分析消息项失败: {e}")
            return None
    
    async def _get_element_selector(self, element: ElementHandle) -> str:
        """获取元素的选择器"""
        try:
            # 尝试获取元素的唯一选择器
            element_info = await element.evaluate('''
                (el) => {
                    const getSelector = (element) => {
                        if (element.id) return `#${element.id}`;
                        if (element.className) {
                            const classes = element.className.split(' ').filter(c => c.length > 0);
                            if (classes.length > 0) return `.${classes.join('.')}`;
                        }
                        return element.tagName.toLowerCase();
                    };
                    return getSelector(el);
                }
            ''')
            return element_info
        except:
            return 'unknown'
    
    async def extract_all_messages(self, limit: int = 50) -> List[Dict]:
        """提取所有消息"""
        messages = []
        
        try:
            # 直接使用检测到的消息结构
            structure = await self.detect_message_structure()
            
            # 如果已有分析好的消息项，直接使用
            if structure['message_items']:
                # 限制消息数量
                message_items = structure['message_items']
                if len(message_items) > limit:
                    message_items = message_items[-limit:]
                
                for item in message_items:
                    if item and item.get('text'):
                        messages.append(item)
            else:
                # 如果没有预分析的消息项，使用默认选择器
                message_elements = await self.find_elements_by_selectors(self.selectors['message_item'])
                
                # 限制消息数量
                if len(message_elements) > limit:
                    message_elements = message_elements[-limit:]
                
                for element in message_elements:
                    message_info = await self._analyze_message_item(element)
                    if message_info and message_info['text']:
                        messages.append(message_info)
            
            logger.info(f"提取到 {len(messages)} 条消息")
            return messages
            
        except Exception as e:
            logger.error(f"提取消息失败: {e}")
            return []
    
    async def save_page_structure(self, filename: str = 'goofish_structure.json'):
        """保存页面结构到文件"""
        try:
            structure = await self.detect_message_structure()
            
            data = {
                'detected_structure': structure,
                'timestamp': str(time.time())
            }
            
            with open(filename, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            
            logger.info(f"页面结构已保存到: {filename}")
            
        except Exception as e:
            logger.error(f"保存页面结构失败: {e}")
    
    async def is_message_received(self, element: ElementHandle) -> bool:
        """判断消息是否为接收到的消息"""
        try:
            class_names = await element.get_attribute('class') or ''
            
            # 常见的接收消息标识
            received_indicators = ['received', 'incoming', 'left', 'other', 'customer']
            
            return any(indicator in class_names.lower() for indicator in received_indicators)
            
        except Exception as e:
            logger.warning(f"判断消息方向失败: {e}")
            return False