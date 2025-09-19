import asyncio
import json
import os
from typing import Dict, List, Optional, Callable
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from loguru import logger
import time
from pathlib import Path
import hashlib
from .dom_parser import GoofishDOMParser


class GoofishBrowser:
    def __init__(self, headless: bool = False, data_dir: str = "./goofish_data"):
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.is_running = False
        self.message_callback: Optional[Callable] = None
        self.dom_parser: Optional[GoofishDOMParser] = None

        # 数据存储配置
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(exist_ok=True)
        self.last_messages_file = self.data_dir / "last_messages.json"
        self.contact_states_file = self.data_dir / "contact_states.json"
        
        # 加载持久化数据
        self.last_processed_messages = self._load_last_messages()
        self.contact_states = self._load_contact_states()

        # 页面状态跟踪
        self.current_url = None
        self.is_logged_in = False
        self.last_login_check = None
    
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

            # 设置页面和上下文监听器
            await self._setup_page_listeners()

            # 导航到咸鱼页面
            await self.page.goto('https://www.goofish.com', wait_until='domcontentloaded')
            logger.info("浏览器已启动，咸鱼页面已加载")

            # 初始化DOM解析器
            self.dom_parser = GoofishDOMParser(self.page)

            self.is_running = True
            return True
            
        except Exception as e:
            logger.error(f"启动浏览器失败: {e}")
            return False
    
    async def wait_for_login(self, timeout: int = 300000):
        """等待用户登录"""
        try:
            logger.info("🔐 ===== 开始等待用户登录 =====")
            logger.info(f"⏱️ 登录超时设置: {timeout/1000}秒")

            start_time = time.time()

            # 确保使用活跃页面
            logger.info("🔄 确保使用活跃页面...")
            await self.ensure_active_page()

            if not self.dom_parser:
                logger.error("❌ DOM解析器未初始化")
                return False

            # 检查初始页面状态
            initial_url = self.page.url
            logger.info(f"🌐 当前页面: {initial_url}")

            # 等待页面完全加载（包括JavaScript动态内容）
            logger.info("⏳ 等待页面完全加载...")

            try:
                await self.page.wait_for_load_state('networkidle', timeout=30000)
                logger.info("✅ 网络空闲状态已达到")
            except Exception as e:
                logger.warning(f"⚠️ 等待网络空闲超时: {e}")

            # 等待React/Vue等框架渲染完成
            logger.info("⏳ 等待动态内容加载...")
            await self.page.wait_for_timeout(3000)

            # 检查页面基本信息
            page_info = await self.page.evaluate("""
                () => ({
                    url: window.location.href,
                    title: document.title,
                    readyState: document.readyState,
                    hasLogin: !!document.querySelector('a[href*="login"], button[class*="login"], [class*="sign"]'),
                    hasUserInfo: !!document.querySelector('[class*="user"], [class*="avatar"], [class*="profile"]'),
                    totalElements: document.querySelectorAll('*').length
                })
            """)

            logger.info(f"📊 页面信息: 标题='{page_info['title'][:30]}...' 状态={page_info['readyState']}")
            logger.info(f"📊 登录状态检查: 有登录按钮={page_info['hasLogin']} 有用户信息={page_info['hasUserInfo']}")
            logger.info(f"📊 页面元素总数: {page_info['totalElements']}")

            # 多阶段登录检测
            login_detected = False
            detection_methods = []

            # 方法1: 等待关键元素出现
            logger.info("🎯 方法1: 等待关键元素出现...")
            try:
                await self.page.wait_for_selector(
                    '.conversation-list--jDBLEMex, .rc-virtual-list, ul.ant-list-items',
                    timeout=30000
                )
                logger.info("✅ 检测到关键元素已加载")
                detection_methods.append("关键元素检测")
                login_detected = True
            except Exception as e:
                logger.warning(f"⚠️ 等待关键元素超时: {e}")

            # 方法2: 使用DOM解析器检测消息容器
            if not login_detected:
                logger.info("🎯 方法2: 使用DOM解析器检测消息容器...")

                # 调用调试方法来获取详细信息
                await self._debug_element_detection()

                # 使用DOM解析器检测登录状态
                login_status = await self.dom_parser.check_login_status()

                if login_status:
                    logger.info("✅ DOM解析器检测到用户已登录")
                    detection_methods.append("DOM解析器检测")
                    login_detected = True

            # 方法3: 检查页面URL和用户相关元素
            if not login_detected:
                logger.info("🎯 方法3: 检查页面URL和用户相关元素...")

                user_indicators = await self.page.evaluate("""
                    () => {
                        const url = window.location.href;
                        const indicators = {
                            url_has_im: url.includes('im') || url.includes('chat') || url.includes('message'),
                            has_user_avatar: !!document.querySelector('[class*="avatar"], [class*="user-icon"]'),
                            has_user_name: !!document.querySelector('[class*="user-name"], [class*="nick"]'),
                            has_message_input: !!document.querySelector('textarea, input[placeholder*="消息"], input[placeholder*="message"]'),
                            has_conversation_list: !!document.querySelector('[class*="conversation"], [class*="chat-list"], [class*="contact"]'),
                            no_login_prompt: !document.querySelector('[class*="login"], [class*="sign-in"]')
                        };

                        indicators.score = Object.values(indicators).filter(Boolean).length;
                        return indicators;
                    }
                """)

                logger.info(f"📊 用户登录指标评分: {user_indicators['score']}/6")
                for key, value in user_indicators.items():
                    if key != 'score':
                        logger.info(f"  {key}: {value}")

                if user_indicators['score'] >= 3:
                    logger.info("✅ 基于用户指标判断已登录")
                    detection_methods.append("用户指标检测")
                    login_detected = True

            # 方法4: 等待页面稳定并再次检查
            if not login_detected:
                logger.info("🎯 方法4: 等待页面稳定并再次检查...")
                remaining_time = timeout - int((time.time() - start_time) * 1000)

                if remaining_time > 10000:  # 至少剩余10秒
                    logger.info(f"⏳ 等待页面稳定，剩余时间: {remaining_time/1000}秒")
                    await self.page.wait_for_timeout(5000)

                    # 最后一次尝试
                    final_check = await self.page.evaluate("""
                        () => {
                            const selectors = [
                                '.conversation-list--jDBLEMex',
                                '.rc-virtual-list',
                                'ul.ant-list-items',
                                '[class*="conversation"]',
                                '[class*="chat"]',
                                '[class*="message"]'
                            ];

                            for (let selector of selectors) {
                                if (document.querySelector(selector)) {
                                    return { found: true, selector: selector };
                                }
                            }
                            return { found: false, selector: null };
                        }
                    """)

                    if final_check['found']:
                        logger.info(f"✅ 最终检查找到元素: {final_check['selector']}")
                        detection_methods.append("最终检查")
                        login_detected = True

            # 总结登录检测结果
            elapsed_time = time.time() - start_time
            logger.info(f"⏱️ 登录检测耗时: {elapsed_time:.1f}秒")

            if login_detected:
                logger.info("🎉 用户登录检测成功!")
                logger.info(f"✅ 成功方法: {', '.join(detection_methods)}")

                # 记录登录状态
                self.is_logged_in = True
                self.last_login_check = time.time()

                return True
            else:
                logger.error("❌ 登录检测失败：未找到任何登录指标")
                logger.error(f"🕒 已尝试 {elapsed_time:.1f}秒，超时设置: {timeout/1000}秒")

                # 保存失败时的页面快照用于分析
                try:
                    html_content = await self.page.content()
                    timestamp = int(time.time())
                    fail_debug_file = f"./debug_pages/login_fail_{timestamp}.html"
                    with open(fail_debug_file, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    logger.info(f"📁 登录失败快照已保存: {fail_debug_file}")
                except Exception as e:
                    logger.warning(f"⚠️ 保存登录失败快照失败: {e}")

                return False

        except Exception as e:
            logger.error(f"❌ 等待登录过程中发生异常: {e}")
            import traceback
            logger.error(f"🔍 详细错误信息: {traceback.format_exc()}")
            return False

    async def _debug_element_detection(self):
        """调试元素检测问题"""
        try:
            logger.info("🔍 ===== 开始元素检测调试 =====")

            # 测试关键选择器
            selectors = [
                '.conversation-list--jDBLEMex',
                '.rc-virtual-list',
                'ul.ant-list-items',
                'li.ant-list-item',
                '.conversation-item--JReyg97P'
            ]

            # 基本页面信息
            logger.info(f"🌐 当前页面: {self.page.url}")
            logger.info(f"📄 页面标题: {await self.page.title()}")

            # 检查页面加载状态
            ready_state = await self.page.evaluate("document.readyState")
            logger.info(f"⏳ document.readyState: {ready_state}")

            # 检查网络状态
            network_state = await self.page.evaluate("""
                () => ({
                    online: navigator.onLine,
                    loading: document.readyState === 'loading',
                    interactive: document.readyState === 'interactive',
                    complete: document.readyState === 'complete'
                })
            """)
            logger.info(f"🌐 网络状态: {network_state}")

            # 详细统计元素
            stats = await self.page.evaluate("""
                () => {
                    const stats = {
                        total: document.querySelectorAll('*').length,
                        divs: document.querySelectorAll('div').length,
                        uls: document.querySelectorAll('ul').length,
                        lis: document.querySelectorAll('li').length,
                        ant_elements: document.querySelectorAll('[class*="ant"]').length,
                        conversation_elements: document.querySelectorAll('[class*="conversation"]').length,
                        rc_elements: document.querySelectorAll('[class*="rc-"]').length,
                        iframes: document.querySelectorAll('iframe').length,
                        scripts: document.querySelectorAll('script').length
                    };

                    // 检查常见的类名模式
                    const classPatterns = {};
                    const allElements = document.querySelectorAll('*');
                    for (let el of allElements) {
                        if (el.className && typeof el.className === 'string') {
                            const classes = el.className.split(' ');
                            for (let cls of classes) {
                                if (cls.includes('--')) {
                                    const prefix = cls.split('--')[0];
                                    classPatterns[prefix] = (classPatterns[prefix] || 0) + 1;
                                }
                            }
                        }
                    }

                    stats.commonClassPrefixes = Object.entries(classPatterns)
                        .sort((a, b) => b[1] - a[1])
                        .slice(0, 10)
                        .map(([prefix, count]) => `${prefix}(${count})`);

                    return stats;
                }
            """)
            logger.info(f"📊 元素统计: {stats}")

            # 检查视窗和滚动状态
            viewport_info = await self.page.evaluate("""
                () => ({
                    viewport: {
                        width: window.innerWidth,
                        height: window.innerHeight
                    },
                    scroll: {
                        x: window.scrollX,
                        y: window.scrollY,
                        maxX: document.documentElement.scrollWidth - window.innerWidth,
                        maxY: document.documentElement.scrollHeight - window.innerHeight
                    },
                    document: {
                        width: document.documentElement.scrollWidth,
                        height: document.documentElement.scrollHeight
                    }
                })
            """)
            logger.info(f"📱 视窗信息: {viewport_info}")

            # 测试每个选择器
            logger.info("🎯 开始测试各个选择器:")
            for i, selector in enumerate(selectors):
                logger.info(f"\n--- [{i+1}/{len(selectors)}] 测试选择器: {selector} ---")

                # JavaScript查询 - 详细版本
                js_result = await self.page.evaluate(f"""
                    (selector) => {{
                        const elements = document.querySelectorAll(selector);
                        const result = {{
                            count: elements.length,
                            elements_info: []
                        }};

                        // 分析前3个元素
                        for (let i = 0; i < Math.min(elements.length, 3); i++) {{
                            const el = elements[i];
                            const rect = el.getBoundingClientRect();
                            const styles = window.getComputedStyle(el);

                            result.elements_info.push({{
                                tagName: el.tagName,
                                className: el.className.substring(0, 80),
                                id: el.id,
                                visible: el.offsetParent !== null,
                                inViewport: rect.top >= 0 && rect.left >= 0 &&
                                           rect.bottom <= window.innerHeight &&
                                           rect.right <= window.innerWidth,
                                rect: {{
                                    top: Math.round(rect.top),
                                    left: Math.round(rect.left),
                                    width: Math.round(rect.width),
                                    height: Math.round(rect.height)
                                }},
                                styles: {{
                                    display: styles.display,
                                    visibility: styles.visibility,
                                    opacity: styles.opacity,
                                    position: styles.position,
                                    zIndex: styles.zIndex
                                }},
                                textLength: el.textContent ? el.textContent.length : 0,
                                textPreview: el.textContent ? el.textContent.substring(0, 50).replace(/\\s+/g, ' ').trim() : ''
                            }});
                        }}

                        return result;
                    }}
                """, selector)

                logger.info(f"  📊 JS查询结果: 找到 {js_result['count']} 个元素")

                for j, el_info in enumerate(js_result['elements_info']):
                    logger.info(f"    📌 元素 {j+1}:")
                    logger.info(f"       标签: {el_info['tagName']}")
                    logger.info(f"       类名: {el_info['className'][:50]}...")
                    logger.info(f"       可见: {el_info['visible']} | 视窗内: {el_info['inViewport']}")
                    logger.info(f"       位置: ({el_info['rect']['left']}, {el_info['rect']['top']}) 大小: {el_info['rect']['width']}x{el_info['rect']['height']}")
                    logger.info(f"       样式: display:{el_info['styles']['display']}, visibility:{el_info['styles']['visibility']}, opacity:{el_info['styles']['opacity']}")
                    if el_info['textPreview']:
                        logger.info(f"       文本: '{el_info['textPreview']}...' (长度:{el_info['textLength']})")

                # Playwright测试
                try:
                    pw_element = await self.page.query_selector(selector)
                    logger.info(f"  🎭 Playwright query_selector: {'✅ 成功' if pw_element else '❌ 返回None'}")
                except Exception as e:
                    logger.warning(f"  🎭 Playwright query_selector: ❌ 异常 - {e}")

                # wait_for_selector测试
                try:
                    pw_wait_element = await self.page.wait_for_selector(selector, timeout=1000, state='attached')
                    logger.info(f"  ⏳ wait_for_selector(attached): {'✅ 成功' if pw_wait_element else '❌ 返回None'}")
                except Exception as e:
                    logger.warning(f"  ⏳ wait_for_selector(attached): ❌ {type(e).__name__}")

                try:
                    pw_wait_visible = await self.page.wait_for_selector(selector, timeout=1000, state='visible')
                    logger.info(f"  👁️ wait_for_selector(visible): {'✅ 成功' if pw_wait_visible else '❌ 返回None'}")
                except Exception as e:
                    logger.warning(f"  👁️ wait_for_selector(visible): ❌ {type(e).__name__}")

            # 检查当前页面类型
            logger.info("\n🔍 页面类型分析:")
            page_analysis = await self.page.evaluate("""
                () => {
                    const url = window.location.href;
                    const pathname = window.location.pathname;

                    return {
                        url: url,
                        pathname: pathname,
                        isGoofish: url.includes('goofish.com'),
                        isTaobao: url.includes('taobao.com'),
                        hasIM: pathname.includes('im') || pathname.includes('chat') || pathname.includes('message'),
                        hasConversationElements: !!document.querySelector('[class*="conversation"]'),
                        hasMessageElements: !!document.querySelector('[class*="message"]'),
                        hasIMElements: !!document.querySelector('[class*="im-"]'),
                        hasListElements: !!document.querySelector('[class*="list"]'),
                        documentTitle: document.title,
                        bodyClasses: document.body ? document.body.className : ''
                    };
                }
            """)

            logger.info(f"  🌐 当前URL: {page_analysis['url']}")
            logger.info(f"  📁 路径: {page_analysis['pathname']}")
            logger.info(f"  🏷️ 站点: 咸鱼({page_analysis['isGoofish']}) | 淘宝({page_analysis['isTaobao']})")
            logger.info(f"  💬 IM页面: {page_analysis['hasIM']}")
            logger.info(f"  🎯 关键元素: 对话({page_analysis['hasConversationElements']}) | 消息({page_analysis['hasMessageElements']}) | IM({page_analysis['hasIMElements']})")

            # 保存调试快照
            timestamp = int(time.time())
            html_content = await self.page.content()
            debug_file = f"./debug_pages/debug_detection_{timestamp}.html"

            try:
                with open(debug_file, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                logger.info(f"📁 调试快照已保存: {debug_file} (大小: {len(html_content)} 字符)")
            except Exception as e:
                logger.warning(f"⚠️ 保存调试快照失败: {e}")

            logger.info("🔍 ===== 元素检测调试完成 =====\n")

        except Exception as e:
            logger.error(f"❌ 调试元素检测时出错: {e}")
            import traceback
            logger.error(f"🔍 详细错误: {traceback.format_exc()}")

    async def _setup_page_listeners(self):
        """设置页面监听器"""
        try:
            # 监听新页面创建
            self.context.on('page', self._on_new_page)
            logger.info("页面监听器已设置完成")
        except Exception as e:
            logger.error(f"设置页面监听器失败: {e}")

    async def _on_new_page(self, page):
        """当创建新页面时的处理"""
        try:
            logger.info(f"🆕 检测到新页面: {page.url}")

            # 切换到新页面
            await self._switch_to_active_page()

        except Exception as e:
            logger.error(f"处理新页面时出错: {e}")

    async def _switch_to_active_page(self):
        """切换到当前活跃的页面"""
        try:
            # 获取所有页面
            pages = self.context.pages
            if not pages:
                return

            # 找到最后创建的页面（通常是活跃页面）
            active_page = pages[-1]

            if active_page != self.page:
                old_url = self.page.url if self.page else "None"
                new_url = active_page.url

                logger.info(f"🔄 切换页面: {old_url} -> {new_url}")

                # 更新当前页面引用
                self.page = active_page

                # 重新初始化DOM解析器
                self.dom_parser = GoofishDOMParser(self.page)

                # 记录URL变化
                self.current_url = new_url

                # 如果是闲鱼相关页面，记录日志
                if 'goofish.com' in new_url or 'taobao.com' in new_url:
                    logger.info("检测到闲鱼页面")

        except Exception as e:
            logger.error(f"切换活跃页面时出错: {e}")

    async def ensure_active_page(self):
        """确保使用活跃页面进行操作"""
        try:
            await self._switch_to_active_page()
        except Exception as e:
            logger.error(f"确保活跃页面时出错: {e}")
    
    async def get_chat_messages(self) -> List[Dict]:
        """获取聊天消息"""
        try:
            # 确保使用活跃页面
            await self.ensure_active_page()
            if not self.dom_parser:
                logger.error("DOM解析器未初始化")
                return []

            # 使用DOM解析器提取消息
            messages = await self.dom_parser.extract_all_messages()

            # 只返回接收到的消息
            received_messages = []
            for message in messages:
                if message.get('is_received', False):
                    received_messages.append({
                        'text': message['text'],
                        'sender': message['sender'],
                        'timestamp': message['timestamp'],
                        'type': 'received'
                    })

            return received_messages

        except Exception as e:
            logger.error(f"获取聊天消息失败: {e}")
            return []
    
    async def send_message(self, message: str) -> bool:
        """发送消息"""
        try:
            if not self.dom_parser:
                logger.error("DOM解析器未初始化")
                return False

            # 查找输入框
            input_element = await self.dom_parser.find_element_by_selectors(
                self.dom_parser.selectors['input_box'],
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
            send_button = await self.dom_parser.find_element_by_selectors(
                self.dom_parser.selectors['send_button'],
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
    
    async def monitor_new_messages(self, callback: Callable[[Dict], None]):
        """监控新消息 - 使用持久化存储和新消息标记串行处理"""
        self.message_callback = callback

        logger.info("📱 ===== 开始监控新消息 =====")
        logger.info("📋 使用持久化存储和串行处理模式")

        monitor_start_time = time.time()
        message_count = 0
        error_count = 0

        while self.is_running:
            try:
                cycle_start_time = time.time()

                # 周期性状态报告
                if message_count % 50 == 0 and message_count > 0:
                    elapsed = time.time() - monitor_start_time
                    logger.info(f"📊 监控状态报告: 运行{elapsed/60:.1f}分钟, 处理{message_count}条消息, 错误{error_count}次")

                # 等待下一条新消息
                logger.debug("🔍 等待下一条新消息...")
                new_message = await self._wait_for_next_new_message()

                if new_message:
                    message_count += 1
                    wait_time = time.time() - cycle_start_time

                    logger.info(f"📨 [{message_count}] 检测到新消息 (等待耗时: {wait_time:.1f}秒)")
                    logger.info(f"📝 消息内容: {new_message.get('text', '')[:50]}...")
                    logger.info(f"👤 发送者: {new_message.get('sender', '未知')}")
                    logger.info(f"⏰ 时间戳: {new_message.get('timestamp', '未知')}")

                    # 串行处理这条消息
                    process_start_time = time.time()
                    await self._process_single_message(new_message)
                    process_time = time.time() - process_start_time

                    logger.info(f"✅ [{message_count}] 消息处理完毕 (处理耗时: {process_time:.1f}秒)")
                    logger.info(f"📊 总周期耗时: {time.time() - cycle_start_time:.1f}秒")
                else:
                    # 没有新消息，可能是正常的空闲周期
                    if wait_time > 30:  # 如果等待超过30秒，记录一下
                        logger.debug(f"⏳ 本轮未检测到新消息 (等待耗时: {wait_time:.1f}秒)")

            except KeyboardInterrupt:
                logger.info("⛔ 接收到中断信号，停止监控新消息")
                self.is_running = False
                break
            except Exception as e:
                error_count += 1
                logger.error(f"❌ [{error_count}] 监控消息失败: {e}")
                import traceback
                logger.error(f"🔍 详细错误信息: {traceback.format_exc()}")

                # 错误恢复策略
                if error_count % 5 == 0:
                    logger.warning(f"⚠️ 连续错误{error_count}次，尝试重新初始化页面...")
                    try:
                        await self.ensure_active_page()
                        logger.info("✅ 页面重新初始化完成")
                    except Exception as recovery_error:
                        logger.error(f"❌ 页面重新初始化失败: {recovery_error}")

                await asyncio.sleep(5)

        # 监控结束统计
        total_time = time.time() - monitor_start_time
        logger.info("📱 ===== 消息监控已停止 =====")
        logger.info(f"📊 最终统计: 运行时间{total_time/60:.1f}分钟, 处理消息{message_count}条, 错误{error_count}次")
        if message_count > 0:
            logger.info(f"📊 平均处理速度: {message_count/(total_time/60):.2f}条/分钟")
    
    async def _wait_for_next_new_message(self, poll_interval: float = 2.0) -> Optional[Dict]:
        """等待下一条新消息 - 结合新消息标记和持久化存储判断"""
        check_count = 0

        while self.is_running:
            try:
                check_count += 1

                # 每100次检查记录一次状态
                if check_count % 100 == 1:
                    logger.debug(f"🔍 消息检查周期 #{check_count}, 轮询间隔: {poll_interval}秒")

                # 1. 首先检查有新消息标记的联系人
                logger.debug("🎯 检查有新消息标记的联系人...")
                contacts_with_indicators = await self.check_for_new_message_indicators()

                if not contacts_with_indicators:
                    # 没有新消息标记，等待后继续
                    logger.debug(f"⏳ 未发现新消息标记，等待{poll_interval}秒后继续...")
                    await asyncio.sleep(poll_interval)
                    continue

                logger.info(f"🎉 发现 {len(contacts_with_indicators)} 个有新消息标记的联系人")

                # 2. 遍历有新消息标记的联系人，检查具体的新消息
                for i, contact in enumerate(contacts_with_indicators):
                    contact_name = contact['name']
                    logger.info(f"🔍 [{i+1}/{len(contacts_with_indicators)}] 检查联系人: {contact_name}")

                    # 进入该联系人的聊天
                    select_start_time = time.time()
                    if not await self.select_contact(contact_name):
                        logger.warning(f"❌ 无法进入联系人 {contact_name} 的聊天")
                        continue

                    select_time = time.time() - select_start_time
                    logger.debug(f"✅ 成功进入联系人 {contact_name} 的聊天 (耗时: {select_time:.1f}秒)")

                    # 获取该联系人的最新消息
                    get_messages_start_time = time.time()
                    current_messages = await self.get_chat_messages()
                    get_messages_time = time.time() - get_messages_start_time

                    logger.debug(f"📋 获取到 {len(current_messages)} 条聊天消息 (耗时: {get_messages_time:.1f}秒)")

                    # 找到真正的新消息
                    find_start_time = time.time()
                    new_message = self._find_new_message_for_contact(contact_name, current_messages)
                    find_time = time.time() - find_start_time

                    if new_message:
                        logger.info(f"🎉 在联系人 {contact_name} 中找到新消息!")
                        logger.info(f"📝 新消息内容: {new_message.get('text', '')[:50]}...")
                        logger.debug(f"⏱️ 查找耗时: {find_time:.1f}秒")

                        # 更新持久化存储
                        self._update_last_processed_message(contact_name, new_message)
                        logger.debug(f"💾 已更新联系人 {contact_name} 的消息记录")

                        return new_message
                    else:
                        logger.debug(f"⚠️ 联系人 {contact_name} 虽有标记但未找到真正新消息")

                # 所有有标记的联系人都检查完了，但没找到真正的新消息
                logger.debug(f"⚠️ 检查完所有有标记的联系人，但未找到真正新消息，可能是误报")
                logger.debug(f"⏳ 等待{poll_interval}秒后继续...")
                await asyncio.sleep(poll_interval)

            except KeyboardInterrupt:
                logger.info("⛔ 接收到中断信号，停止等待新消息")
                self.is_running = False
                raise
            except Exception as e:
                logger.error(f"❌ 等待新消息时出错: {e}")
                import traceback
                logger.error(f"🔍 详细错误信息: {traceback.format_exc()}")

                # 错误后延长等待时间
                error_wait_time = poll_interval * 2
                logger.warning(f"⏳ 出错后等待{error_wait_time}秒后重试...")
                await asyncio.sleep(error_wait_time)

        logger.debug("🔚 等待新消息循环结束")
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
    

    
    async def select_contact(self, contact_name: str) -> bool:
        """选择联系人进入聊天"""
        try:
            if not self.dom_parser:
                logger.error("DOM解析器未初始化")
                return False

            # 使用DOM解析器选择联系人
            success = await self.dom_parser.select_contact(contact_name)
            return success

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