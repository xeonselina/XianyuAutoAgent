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
        for selector in selectors:
            try:
                element = await self.page.wait_for_selector(selector, timeout=timeout)
                if element:
                    return element
            except:
                continue
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