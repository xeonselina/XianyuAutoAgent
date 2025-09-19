from typing import Dict, List, Optional
from playwright.async_api import Page, ElementHandle
from loguru import logger
import json
import re
import time


class GoofishDOMParser:
    def __init__(self, page: Page):
        self.page = page

        # 基于实际HTML结构分析的选择器配置
        self.selectors = {
            # 登录检测 - 当这些元素存在时说明已登录
            'login_indicators': [
                'html.page-im',                       # HTML根元素包含page-im类
                '.conversation-item--JReyg97P',       # 联系人项目存在
                '.content-container--gIWgkNkm'        # 内容容器存在
            ],

            # 联系人列表容器
            'contact_list_container': [
                '.sidebar-container--VCaOz9df',       # 侧边栏容器
                '.content-container--gIWgkNkm'        # 内容容器
            ],

            # 联系人项目
            'contact_item': [
                '.conversation-item--JReyg97P'        # 单个联系人项目
            ],

            # 联系人名称（在联系人项目内部）
            'contact_name': [
                '.conversation-item--JReyg97P div:nth-child(1) div:nth-child(2) div:nth-child(2)',  # 联系人名称位置
                '.conversation-item--JReyg97P div div div div:nth-child(2) div:nth-child(2)'       # 备选位置
            ],

            # 新消息标记
            'new_message_indicators': [
                '.ant-badge',                         # Ant Design徽章
                '.ant-badge-count',                   # 徽章计数
                '.ant-badge-count-sm',                # 小尺寸徽章计数
                'sup.ant-scroll-number',              # 滚动数字
                'span.ant-badge.css-1js74qn'          # 具体的徽章类
            ],

            # 消息输入框
            'input_box': [
                'textarea[placeholder*="请输入"]',     # 消息输入框
                'textarea',                           # 通用文本域
                '[contenteditable="true"]'           # 可编辑内容区域
            ],

            # 发送按钮
            'send_button': [
                'button[class*="send"]',              # 包含send的按钮
                'button[aria-label*="发送"]',         # 带发送标签的按钮
                'button'                              # 通用按钮（在输入框附近）
            ]
        }
    
    async def find_element_by_selectors(self, selectors: List[str], timeout: int = 5000) -> Optional[ElementHandle]:
        """通过多个选择器查找元素"""
        import asyncio

        start_time = asyncio.get_event_loop().time()
        end_time = start_time + timeout / 1000  # 转换为秒

        logger.info(f"🔍 开始查找元素，选择器数量: {len(selectors)}, 超时: {timeout}ms")

        # 首先检查页面基本状态
        await self._debug_page_state()

        retry_count = 0
        while asyncio.get_event_loop().time() < end_time:
            retry_count += 1
            elapsed = int((asyncio.get_event_loop().time() - start_time) * 1000)
            logger.info(f"🔄 第{retry_count}次尝试 (已用时{elapsed}ms)")

            for i, selector in enumerate(selectors):
                try:
                    logger.info(f"📍 [{i+1}/{len(selectors)}] 尝试选择器: {selector}")

                    # 先用JavaScript检查元素是否存在
                    js_check = await self.page.evaluate(f"""
                        (selector) => {{
                            const elements = document.querySelectorAll(selector);
                            return {{
                                count: elements.length,
                                visible: elements.length > 0 ? elements[0].offsetParent !== null : false,
                                first_element_info: elements.length > 0 ? {{
                                    tagName: elements[0].tagName,
                                    className: elements[0].className.substring(0, 50),
                                    text: elements[0].textContent ? elements[0].textContent.substring(0, 30) : ''
                                }} : null
                            }};
                        }}
                    """, selector)

                    logger.info(f"   JS检查结果: 找到{js_check['count']}个元素, 可见:{js_check['visible']}")
                    if js_check['first_element_info']:
                        logger.info(f"   首个元素: {js_check['first_element_info']['tagName']}.{js_check['first_element_info']['className'][:20]}...")

                    # 如果JavaScript找到了元素，再用Playwright获取
                    if js_check['count'] > 0:
                        # 使用较短的超时进行单次查找，以便能够重试
                        # state='attached' 表示元素存在于DOM中即可，不需要可见
                        element = await self.page.wait_for_selector(selector, timeout=3000, state='attached')
                        if element:
                            logger.info(f"✅ 成功找到元素: {selector}")
                            logger.info(f"🎯 总共尝试了{retry_count}次，用时{elapsed}ms")
                            return element
                        else:
                            logger.warning(f"⚠️ JS找到了元素但Playwright未找到: {selector}")
                    else:
                        logger.debug(f"❌ JS未找到元素: {selector}")

                except Exception as e:
                    logger.warning(f"❌ 查找选择器 {selector} 时出错: {e}")
                    continue

            # 等待一段时间后重试
            remaining_time = int((end_time - asyncio.get_event_loop().time()) * 1000)
            if remaining_time > 2000:
                logger.info(f"⏳ 未找到任何元素，2秒后重试... (剩余时间: {remaining_time}ms)")
                await asyncio.sleep(2)
            else:
                logger.warning(f"⏰ 剩余时间不足，停止重试 (剩余: {remaining_time}ms)")
                break

        logger.error(f"🚫 查找超时：所有选择器都未找到元素")
        logger.error(f"📊 总共尝试了{retry_count}次，总用时{int((asyncio.get_event_loop().time() - start_time) * 1000)}ms")
        logger.error(f"📋 失败的选择器列表: {selectors}")
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

    async def _debug_page_state(self):
        """调试页面状态"""
        try:
            page_info = await self.page.evaluate("""
                () => {
                    return {
                        url: window.location.href,
                        title: document.title,
                        readyState: document.readyState,
                        totalElements: document.querySelectorAll('*').length,
                        antElements: document.querySelectorAll('[class*="ant"]').length,
                        conversationElements: document.querySelectorAll('[class*="conversation"]').length,
                        rcElements: document.querySelectorAll('[class*="rc-"]').length,
                        hasIframes: document.querySelectorAll('iframe').length,
                        viewportSize: {
                            width: window.innerWidth,
                            height: window.innerHeight
                        }
                    };
                }
            """)

            logger.info(f"📄 页面状态 - URL: {page_info['url'][:50]}...")
            logger.info(f"📄 标题: {page_info['title'][:30]}...")
            logger.info(f"📄 加载状态: {page_info['readyState']}")
            logger.info(f"📊 元素统计 - 总计:{page_info['totalElements']}, ant:{page_info['antElements']}, conversation:{page_info['conversationElements']}, rc:{page_info['rcElements']}")
            logger.info(f"📊 iframe数量: {page_info['hasIframes']}")
            logger.info(f"📊 视窗大小: {page_info['viewportSize']['width']}x{page_info['viewportSize']['height']}")

        except Exception as e:
            logger.warning(f"⚠️ 无法获取页面状态信息: {e}")

    async def check_login_status(self) -> bool:
        """检查是否已登录"""
        logger.info("🔐 检查登录状态...")

        try:
            # 检查HTML根元素是否包含page-im类
            html_element = await self.page.query_selector('html.page-im')
            if html_element:
                logger.info("✅ HTML包含page-im类，用户已登录")
                return True

            # 检查是否有联系人项目
            contact_items = await self.page.query_selector_all('.conversation-item--JReyg97P')
            if len(contact_items) > 0:
                logger.info(f"✅ 找到{len(contact_items)}个联系人项目，用户已登录")
                return True

            # 检查内容容器
            content_container = await self.page.query_selector('.content-container--gIWgkNkm')
            if content_container:
                logger.info("✅ 找到内容容器，用户已登录")
                return True

            logger.warning("❌ 未找到登录指标")
            return False

        except Exception as e:
            logger.error(f"检查登录状态时出错: {e}")
            return False

    async def get_contacts_with_new_messages(self) -> List[Dict]:
        """获取有新消息的联系人列表"""
        logger.info("🔍 获取有新消息的联系人...")

        contacts_with_new_messages = []

        try:
            # 获取所有联系人项目
            contact_items = await self.page.query_selector_all('.conversation-item--JReyg97P')
            logger.info(f"📋 找到{len(contact_items)}个联系人项目")

            for i, contact_item in enumerate(contact_items):
                try:
                    # 检查是否有新消息徽章
                    badge = await contact_item.query_selector('.ant-badge')
                    if not badge:
                        continue

                    # 获取徽章数字
                    badge_count_element = await contact_item.query_selector('.ant-badge-count, sup.ant-scroll-number')
                    badge_count = "1"  # 默认值
                    if badge_count_element:
                        badge_text = await badge_count_element.inner_text()
                        badge_count = badge_text.strip() if badge_text else "1"

                    # 获取联系人名称（查找包含名称的div）
                    name_divs = await contact_item.query_selector_all('div')
                    contact_name = "未知联系人"

                    for div in name_divs:
                        div_text = await div.inner_text()
                        # 跳过数字、时间等无关文本
                        if (div_text and
                            len(div_text.strip()) > 1 and
                            not div_text.strip().isdigit() and
                            '分钟前' not in div_text and
                            '小时前' not in div_text and
                            '天前' not in div_text and
                            '🧧' not in div_text):
                            contact_name = div_text.strip()
                            break

                    # 获取最后消息预览
                    last_message = ""
                    text_divs = await contact_item.query_selector_all('div')
                    for div in text_divs:
                        div_text = await div.inner_text()
                        if (div_text and
                            len(div_text.strip()) > 2 and
                            div_text.strip() != contact_name and
                            not div_text.strip().isdigit()):
                            # 取最长的文本作为消息预览
                            if len(div_text.strip()) > len(last_message):
                                last_message = div_text.strip()

                    contact_info = {
                        'name': contact_name,
                        'badge_count': badge_count,
                        'last_message': last_message,
                        'has_new_message': True
                    }

                    contacts_with_new_messages.append(contact_info)
                    logger.info(f"📨 {contact_name}: {badge_count}条新消息")

                except Exception as e:
                    logger.warning(f"解析联系人{i+1}时出错: {e}")
                    continue

            logger.info(f"✅ 共找到{len(contacts_with_new_messages)}个有新消息的联系人")
            return contacts_with_new_messages

        except Exception as e:
            logger.error(f"获取有新消息的联系人时出错: {e}")
            return []
    
    async def select_contact(self, contact_name: str) -> bool:
        """选择联系人进入聊天"""
        logger.info(f"🎯 选择联系人: {contact_name}")

        try:
            # 获取所有联系人项目
            contact_items = await self.page.query_selector_all('.conversation-item--JReyg97P')

            for i, contact_item in enumerate(contact_items):
                try:
                    # 获取联系人名称
                    item_text = await contact_item.inner_text()

                    # 检查是否包含目标联系人名称
                    if contact_name in item_text:
                        # 点击联系人项目
                        await contact_item.click()
                        logger.info(f"✅ 成功选择联系人: {contact_name}")

                        # 等待聊天界面加载
                        await self.page.wait_for_timeout(1000)
                        return True

                except Exception as e:
                    logger.warning(f"检查联系人{i+1}时出错: {e}")
                    continue

            logger.warning(f"❌ 未找到联系人: {contact_name}")
            return False

        except Exception as e:
            logger.error(f"选择联系人时出错: {e}")
            return False
    
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
    
    async def get_chat_messages(self, limit: int = 50) -> List[Dict]:
        """提取所有消息"""
        messages = []

        try:
            logger.info(f"🔍 开始提取消息，限制数量: {limit}")

            # 首先检查页面状态
            await self._debug_page_state()

            # 直接使用检测到的消息结构
            logger.info("📋 检测消息结构...")
            structure = await self.detect_message_structure()

            # 如果已有分析好的消息项，直接使用
            if structure['message_items']:
                logger.info(f"✅ 使用预分析的消息项，数量: {len(structure['message_items'])}")
                # 限制消息数量
                message_items = structure['message_items']
                if len(message_items) > limit:
                    message_items = message_items[-limit:]
                    logger.info(f"📊 限制消息数量为最新的 {limit} 条")

                for i, item in enumerate(message_items):
                    if item and item.get('text'):
                        messages.append(item)
                        logger.debug(f"📝 [{i+1}] 添加消息: {item.get('text', '')[:30]}...")
            else:
                logger.info("🔍 未找到预分析消息项，使用默认选择器查找...")
                # 如果没有预分析的消息项，使用默认选择器
                message_elements = await self.find_elements_by_selectors(self.selectors['message_item'])
                logger.info(f"📊 通过选择器找到 {len(message_elements)} 个消息元素")

                # 限制消息数量
                if len(message_elements) > limit:
                    message_elements = message_elements[-limit:]
                    logger.info(f"📊 限制元素数量为最新的 {limit} 个")

                for i, element in enumerate(message_elements):
                    logger.debug(f"🔍 [{i+1}/{len(message_elements)}] 分析消息元素...")
                    message_info = await self._analyze_message_item(element)
                    if message_info and message_info['text']:
                        messages.append(message_info)
                        logger.debug(f"✅ 提取消息: {message_info.get('text', '')[:30]}...")
                    else:
                        logger.debug(f"⚠️ 消息元素无有效内容")

            logger.info(f"✅ 成功提取到 {len(messages)} 条消息")

            # 统计消息类型
            received_count = sum(1 for msg in messages if msg.get('is_received', False))
            sent_count = sum(1 for msg in messages if msg.get('is_sent', False))
            logger.info(f"📊 消息统计 - 接收: {received_count}, 发送: {sent_count}, 其他: {len(messages) - received_count - sent_count}")

            return messages

        except Exception as e:
            logger.error(f"❌ 提取消息失败: {e}")
            import traceback
            logger.error(f"🔍 详细错误信息: {traceback.format_exc()}")
            return []
    
    async def has_input_box(self) -> bool:
        """检查是否有消息输入框"""
        try:
            input_element = await self.find_element_by_selectors(self.selectors['input_box'], timeout=2000)
            return input_element is not None
        except Exception:
            return False

    async def send_message(self, message: str) -> bool:
        """发送消息"""
        logger.info(f"📤 发送消息: {message[:30]}...")

        try:
            # 查找输入框
            input_element = await self.find_element_by_selectors(self.selectors['input_box'], timeout=5000)
            if not input_element:
                logger.error("❌ 找不到消息输入框")
                return False

            # 清空输入框并输入消息
            await input_element.click()
            await input_element.fill('')
            await input_element.type(message)

            # 查找并点击发送按钮
            send_button = await self.find_element_by_selectors(self.selectors['send_button'], timeout=2000)
            if send_button:
                await send_button.click()
                logger.info(f"✅ 消息已发送: {message}")
                return True
            else:
                # 如果找不到发送按钮，尝试按回车键
                await input_element.press('Enter')
                logger.info(f"✅ 消息已发送（回车键): {message}")
                return True

        except Exception as e:
            logger.error(f"❌ 发送消息失败: {e}")
            return False
    
    async def get_page_title(self) -> str:
        """获取页面标题"""
        try:
            title = await self.page.title()
            return title
        except Exception:
            return ""