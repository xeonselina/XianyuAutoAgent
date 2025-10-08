from typing import Dict, List, Optional
from playwright.async_api import Page, ElementHandle
from loguru import logger


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

            # 活跃/当前打开的联系人项目
            'active_contact_item': [
                '.conversation-item--JReyg97P[class*="active"]',
                '.conversation-item--JReyg97P[class*="selected"]'
            ],

            # 带有新消息徽章的联系人项目
            'contact_item_with_badge': [
                '.conversation-item--JReyg97P:has(.ant-badge-count-sm)'
            ],

            # 联系人名称（在联系人项目内部）
            'contact_name': [
                '.conversation-item--JReyg97P div:nth-child(1) div:nth-child(2) div:nth-child(2)',  # 联系人名称位置
                '.conversation-item--JReyg97P div div div div:nth-child(2) div:nth-child(2)'       # 备选位置
            ],

            # 新消息标记
            'new_message_indicators': [
                '.ant-badge-count-sm'
            ],

            # 徽章计数元素
            'badge_count': [
                '.ant-badge-count',
                'sup.ant-scroll-number'
            ],

            # 需要排除的徽章包装器（父元素有此class的徽章不计入新消息）
            'badge_exclude_wrapper': [
                'span.ant-badge.ant-badge-not-a-wrapper.css-1u3we3n'
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
            ],

            # 消息项目
            'message_item': [
                '.message-item',                      # 消息项目
                '.chat-message',                      # 聊天消息
                '[class*="message"]',                 # 包含message的类
                '[class*="chat"]'                     # 包含chat的类
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
        """获取有新消息的联系人列表

        新消息只会出现在两种情况：
        1. 当前打开的联系人 (活跃聊天窗口) - 可能有新消息但没有徽章
        2. 未打开但有新消息标记 (badge) 的联系人

        只查找这两种情况，不遍历所有联系人
        """
        logger.info("🔍 获取有新消息的联系人...")

        contacts_with_new_messages = []

        try:
            # 检查页面状态
            if self.page.is_closed():
                logger.error("❌ 页面已关闭，无法获取联系人")
                return []

            # 方法1: 找到当前打开的联系人 (使用配置的选择器)
            active_selector = ', '.join(self.selectors['active_contact_item'])
            active_contact = await self.page.query_selector(active_selector)
            if active_contact:
                try:
                    # 获取联系人名称
                    name_divs = await active_contact.query_selector_all('div')
                    contact_name = "未知联系人"

                    for div in name_divs:
                        div_text = await div.inner_text()
                        if (div_text and
                            len(div_text.strip()) > 1 and
                            not div_text.strip().isdigit() and
                            '分钟前' not in div_text and
                            '小时前' not in div_text and
                            '天前' not in div_text and
                            '🧧' not in div_text):
                            contact_name = div_text.strip()
                            break

                    if contact_name not in ['消息通知', '消息助手', '系统通知', '系统消息', '通知消息', '未知联系人']:
                        logger.info(f"📱 当前打开的联系人: {contact_name}")
                        contacts_with_new_messages.append({
                            'name': contact_name,
                            'badge_count': '0',
                            'last_message': '',
                            'has_new_message': True,
                            'is_active': True
                        })
                except Exception as e:
                    logger.warning(f"解析当前打开的联系人时出错: {e}")

            # 方法2: 只查找带有徽章的联系人项目 (使用配置的选择器)
            # 这样避免遍历所有联系人，只处理有新消息的
            badge_selector = ', '.join(self.selectors['contact_item_with_badge'])
            contact_items_with_badge = await self.page.query_selector_all(badge_selector)
            logger.info(f"📋 找到{len(contact_items_with_badge)}个带有新消息标记的联系人")

            for i, contact_item in enumerate(contact_items_with_badge):
                try:
                    # 检查页面是否还有效
                    if self.page.is_closed():
                        logger.error("❌ 页面在处理联系人时被关闭")
                        break

                    # 检查徽章是否应该被排除（父元素有排除的class）
                    badge_count_selector = ', '.join(self.selectors['badge_count'])
                    badge_count_element = await contact_item.query_selector(badge_count_selector)

                    if badge_count_element:
                        # 检查徽章的父元素是否包含排除的class
                        should_exclude = await badge_count_element.evaluate("""
                            (element) => {
                                const excludeClasses = ['ant-badge-not-a-wrapper'];
                                let parent = element.parentElement;
                                while (parent) {
                                    const classList = Array.from(parent.classList || []);
                                    for (const excludeClass of excludeClasses) {
                                        if (classList.some(cls => cls.includes(excludeClass))) {
                                            return true;
                                        }
                                    }
                                    parent = parent.parentElement;
                                    // 只检查3层父元素
                                    if (parent && parent.classList && parent.classList.contains('conversation-item--JReyg97P')) {
                                        break;
                                    }
                                }
                                return false;
                            }
                        """)

                        if should_exclude:
                            logger.debug(f"⏭️ 跳过徽章（父元素包含排除的class）")
                            continue

                        badge_text = await badge_count_element.inner_text()
                        badge_count = badge_text.strip() if badge_text else "1"
                    else:
                        badge_count = "1"  # 默认值

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

                    # 跳过特殊的系统联系人
                    if contact_name in ['消息通知', '消息助手', '系统通知', '系统消息', '通知消息']:
                        logger.debug(f"⏭️ 跳过系统联系人: {contact_name}")
                        continue

                    # 检查是否已经添加过（可能是当前打开的联系人）
                    if any(c['name'] == contact_name for c in contacts_with_new_messages):
                        logger.debug(f"⏭️ 跳过已添加的联系人: {contact_name}")
                        continue

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
                        'has_new_message': True,
                        'is_active': False
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
            # 检查页面状态
            if self.page.is_closed():
                logger.error("❌ 页面已关闭，无法选择联系人")
                return False

            # 获取所有联系人项目
            contact_items = await self.page.query_selector_all('.conversation-item--JReyg97P')

            if not contact_items:
                logger.warning("❌ 未找到任何联系人项目")
                return False

            for i, contact_item in enumerate(contact_items):
                try:
                    # 检查页面和元素是否还有效
                    if self.page.is_closed():
                        logger.error("❌ 页面在处理过程中被关闭")
                        return False

                    # 获取联系人名称
                    item_text = await contact_item.inner_text()

                    # 检查是否包含目标联系人名称
                    if contact_name in item_text:
                        # 点击联系人项目
                        await contact_item.click()
                        logger.info(f"✅ 成功选择联系人: {contact_name}")

                        # 等待聊天界面加载，但要检查页面是否还有效
                        if not self.page.is_closed():
                            await self.page.wait_for_timeout(1500)
                        return True

                except Exception as e:
                    logger.warning(f"检查联系人{i+1}时出错: {e}")
                    # 如果是页面关闭错误，直接返回
                    if "closed" in str(e).lower():
                        logger.error("❌ 页面已关闭，停止处理")
                        return False
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

    async def _get_current_contact_name(self) -> str:
        """获取当前聊天的联系人名称"""
        try:
            # 尝试从页面中找到当前聊天联系人的名称
            # 通常在聊天头部或者标题栏中
            contact_name = await self.page.evaluate("""
                () => {
                    // 尝试多种可能的联系人名称位置
                    const selectors = [
                        // 聊天头部标题
                        '.chat-header .contact-name',
                        '.chat-title',
                        '[class*="chat-header"] [class*="name"]',
                        '[class*="conversation-header"] [class*="name"]',
                        // 通用标题选择器
                        'h1', 'h2', 'h3',
                        // 可能的联系人名称容器
                        '[class*="contact"][class*="name"]',
                        '[class*="user"][class*="name"]'
                    ];

                    for (const selector of selectors) {
                        const elements = document.querySelectorAll(selector);
                        for (const element of elements) {
                            const text = element.textContent && element.textContent.trim();
                            if (text &&
                                text.length > 0 &&
                                text.length < 50 &&
                                !text.includes('请输入') &&
                                !text.includes('发送') &&
                                !text.includes('分钟前') &&
                                !text.includes('小时前') &&
                                !text.includes('天前') &&
                                !text.match(/^\\d+$/)) {  // 不是纯数字
                                return text;
                            }
                        }
                    }

                    // 如果上述方法都没找到，尝试从页面URL或其他位置推断
                    // 这里可以根据具体的咸鱼页面结构来调整
                    return '未知联系人';
                }
            """)

            if contact_name and contact_name != '未知联系人':
                logger.debug(f"✅ 成功获取当前联系人名称: {contact_name}")
                return contact_name
            else:
                logger.warning("⚠️ 无法确定当前联系人名称，使用默认值")
                return '未知联系人'

        except Exception as e:
            logger.error(f"❌ 获取当前联系人名称失败: {e}")
            return '未知联系人'
    
    async def get_chat_messages(self, limit: int = 50, contact_name: str = None) -> List[Dict]:
        """提取所有消息"""
        messages = []

        try:
            logger.info(f"🔍 开始提取消息，限制数量: {limit}")

            # 首先检查页面状态
            await self._debug_page_state()

            # 获取当前聊天联系人名称
            if contact_name:
                current_contact_name = contact_name
                logger.info(f"📋 使用传入的联系人名称: {current_contact_name}")
            else:
                current_contact_name = await self._get_current_contact_name()
                logger.info(f"📋 从页面获取的联系人名称: {current_contact_name}")

            # 使用JavaScript直接提取消息
            logger.info("📋 使用JavaScript提取消息...")
            messages_data = await self.page.evaluate(f"""
                (contactName) => {{
                    const messages = [];

                    // 尝试多种可能的消息容器选择器
                    const messageContainers = [
                        '.message-item',
                        '.chat-message',
                        '[class*="message"]',
                        '[class*="chat"]'
                    ];

                    let messageElements = [];
                    for (const selector of messageContainers) {{
                        const elements = document.querySelectorAll(selector);
                        if (elements.length > 0) {{
                            messageElements = Array.from(elements);
                            break;
                        }}
                    }}

                    // 如果没找到具体的消息元素，尝试找包含文本的div
                    if (messageElements.length === 0) {{
                        const allDivs = document.querySelectorAll('div');
                        messageElements = Array.from(allDivs).filter(div => {{
                            const text = div.textContent && div.textContent.trim();
                            return text && text.length > 2 && text.length < 1000;
                        }});
                    }}

                    messageElements.forEach((element, index) => {{
                        const text = element.textContent && element.textContent.trim();
                        if (text && text.length > 0) {{
                            // 简单判断是接收还是发送的消息
                            const className = element.className || '';
                            const isReceived = className.includes('received') ||
                                             className.includes('incoming') ||
                                             !className.includes('sent') && !className.includes('outgoing');

                            messages.push({{
                                text: text,
                                timestamp: new Date().toISOString(),
                                sender: isReceived ? contactName : 'self',
                                is_received: isReceived,
                                is_sent: !isReceived,
                                type: isReceived ? 'received' : 'sent'
                            }});
                        }}
                    }});

                    return messages;
                }}
            """, current_contact_name)

            if messages_data:
                # 限制消息数量
                if len(messages_data) > limit:
                    messages_data = messages_data[-limit:]
                    logger.info(f"📊 限制消息数量为最新的 {limit} 条")

                for msg in messages_data:
                    if msg.get('text'):
                        messages.append(msg)
                        logger.debug(f"📝 添加消息: {msg.get('text', '')[:30]}...")
            else:
                logger.warning("🔍 未能提取到任何消息")

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