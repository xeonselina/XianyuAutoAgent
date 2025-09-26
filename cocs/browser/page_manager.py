import asyncio
import time
from typing import Optional
from playwright.async_api import async_playwright, Browser, Page, BrowserContext
from loguru import logger
from .dom_parser import GoofishDOMParser


class PageManager:
    """页面管理器 - 负责浏览器页面的生命周期管理"""

    def __init__(self, headless: bool = False):
        self.headless = headless
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.dom_parser: Optional[GoofishDOMParser] = None

        # 页面状态跟踪
        self.current_url = None
        self.is_logged_in = False
        self.last_login_check = None

    async def start(self) -> bool:
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

            return True

        except Exception as e:
            logger.error(f"启动浏览器失败: {e}")
            return False

    async def wait_for_login(self, timeout: int = 300000) -> bool:
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
                    ', '.join(self.dom_parser.selectors['contact_list_container']),
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

                    # 使用DOM解析器的选择器进行最终检查
                    login_selectors = self.dom_parser.selectors['login_indicators'] + self.dom_parser.selectors['contact_list_container']
                    final_check = await self.page.evaluate("""
                        (selectors) => {
                            for (let selector of selectors) {
                                if (document.querySelector(selector)) {
                                    return { found: true, selector: selector };
                                }
                            }
                            return { found: false, selector: null };
                        }
                    """, login_selectors)

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
            # 检查当前页面是否还有效
            if not self.page or self.page.is_closed():
                logger.warning("📄 检测到页面已关闭，尝试重新获取页面")
                await self._switch_to_active_page()
                return

            # 检查页面是否可访问
            try:
                await self.page.evaluate("document.readyState")
            except Exception:
                logger.warning("📄 当前页面不可访问，切换到活跃页面")
                await self._switch_to_active_page()

        except Exception as e:
            logger.error(f"确保活跃页面时出错: {e}")

    async def close(self):
        """关闭浏览器"""
        try:
            logger.info("开始关闭浏览器...")

            # 关闭页面
            if self.page and not self.page.is_closed():
                try:
                    await asyncio.wait_for(self.page.close(), timeout=5.0)
                    logger.debug("页面已关闭")
                except asyncio.TimeoutError:
                    logger.warning("关闭页面超时，继续关闭浏览器")
                except Exception as e:
                    logger.warning(f"关闭页面失败: {e}")

            # 关闭上下文
            if self.context:
                try:
                    await asyncio.wait_for(self.context.close(), timeout=5.0)
                    logger.debug("浏览器上下文已关闭")
                except asyncio.TimeoutError:
                    logger.warning("关闭浏览器上下文超时，继续关闭浏览器")
                except Exception as e:
                    logger.warning(f"关闭浏览器上下文失败: {e}")

            # 关闭浏览器
            if self.browser:
                try:
                    await asyncio.wait_for(self.browser.close(), timeout=10.0)
                    logger.debug("浏览器已关闭")
                except asyncio.TimeoutError:
                    logger.warning("关闭浏览器超时，强制退出")
                except Exception as e:
                    logger.warning(f"关闭浏览器失败: {e}")

            logger.info("浏览器关闭完成")

        except Exception as e:
            logger.error(f"关闭浏览器时出现异常: {e}")
        finally:
            # 清理引用
            self.page = None
            self.context = None
            self.browser = None
            self.dom_parser = None