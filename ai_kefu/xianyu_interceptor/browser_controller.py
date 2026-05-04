"""
浏览器控制器模块

使用 Playwright 管理 Chromium 浏览器实例，提供浏览器生命周期管理、
cookie 管理、崩溃恢复等功能。
"""

import os
import asyncio
from typing import Optional, Dict, List
from datetime import datetime
from loguru import logger
from playwright.async_api import async_playwright, Browser, BrowserContext, Page, Playwright
from utils.xianyu_utils import trans_cookies

try:
    from playwright_stealth import stealth_async
    _STEALTH_AVAILABLE = True
except ImportError:
    _STEALTH_AVAILABLE = False
    logger.warning("playwright-stealth 未安装，部分反检测功能不可用。建议运行: pip install playwright-stealth")

# 反检测启动参数
_STEALTH_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",  # 禁用自动化控制特征
    "--disable-dev-shm-usage",
    "--no-sandbox",
    "--disable-infobars",
    "--no-first-run",
    "--no-default-browser-check",
]


class BrowserConfig:
    """浏览器配置类"""

    def __init__(self):
        """从环境变量加载浏览器配置"""
        self.headless = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
        self.debug_port = os.getenv("BROWSER_DEBUG_PORT")
        # 持久化用户数据目录：保留 Cookie/登录状态，减少风控验证
        self.user_data_dir = os.path.abspath(os.getenv("BROWSER_USER_DATA_DIR", "./browser_data"))
        self.viewport_width = int(os.getenv("BROWSER_VIEWPORT_WIDTH", "1280"))
        self.viewport_height = int(os.getenv("BROWSER_VIEWPORT_HEIGHT", "720"))
        self.proxy = os.getenv("BROWSER_PROXY")  # 可选代理配置


class BrowserController:
    """
    浏览器控制器

    管理 Chromium 浏览器实例的生命周期，包括启动、关闭、崩溃恢复等。
    使用持久化 Context 保留 Cookie/登录状态，降低被风控的概率。
    """

    def __init__(self, config: Optional[BrowserConfig] = None):
        """
        初始化浏览器控制器

        Args:
            config: 浏览器配置，如果为 None 则使用默认配置
        """
        self.config = config or BrowserConfig()
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self._is_running = False
        self._crash_count = 0
        self._max_crashes = 5  # 最大崩溃次数

    async def launch(self, cookies_str: Optional[str] = None) -> bool:
        """
        启动浏览器并加载闲鱼页面

        Args:
            cookies_str: Cookie 字符串（首次登录后会自动保存，后续可留空）

        Returns:
            bool: 启动是否成功
        """
        try:
            logger.info("正在启动浏览器...")
            os.makedirs(self.config.user_data_dir, exist_ok=True)
            logger.info(f"浏览器数据目录（Cookie 持久化）: {self.config.user_data_dir}")

            # 启动 Playwright
            self.playwright = await async_playwright().start()

            launch_args = list(_STEALTH_LAUNCH_ARGS)
            if self.config.debug_port:
                launch_args.append(f"--remote-debugging-port={self.config.debug_port}")

            # 使用持久化 Context：Cookie / localStorage / 登录状态跨次保留
            # 不手动指定 user_agent，让 Chromium 使用自身真实 UA（避免 UA 与平台特征不匹配）
            ctx_kwargs = dict(
                headless=self.config.headless,
                args=launch_args,
                viewport={
                    "width": self.config.viewport_width,
                    "height": self.config.viewport_height,
                },
                locale="zh-CN",
                timezone_id="Asia/Shanghai",
            )
            if self.config.proxy:
                ctx_kwargs["proxy"] = {"server": self.config.proxy}

            self.context = await self.playwright.chromium.launch_persistent_context(
                self.config.user_data_dir, **ctx_kwargs
            )

            # 注入反检测脚本（在页面导航前生效）
            await self._inject_stealth_scripts()

            # 注入 cookies（仅首次或强制刷新时需要）
            if cookies_str:
                await self._inject_cookies(cookies_str)

            # 复用已有页面或新建
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()

            # 监听新页面，确保也注入反检测脚本
            self.context.on("page", self._on_new_page)

            # 导航到闲鱼首页
            logger.info("正在导航到闲鱼首页...")
            await self.page.goto("https://www.goofish.com/", wait_until="networkidle")

            # 等待页面加载
            await asyncio.sleep(2)

            self._is_running = True
            logger.info("浏览器启动成功")
            logger.info("=" * 60)
            logger.info("🔔 请在浏览器中点击进入消息中心（或聊天页面）")
            logger.info("   WebSocket 连接将在新页面中建立")
            logger.info("=" * 60)
            return True

        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            await self.close()
            return False

    async def _on_new_page(self, page: Page) -> None:
        """新页面创建时也注入反检测脚本"""
        try:
            if _STEALTH_AVAILABLE:
                await stealth_async(page)
            await page.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined,
                    configurable: true
                });
            """)
        except Exception as e:
            logger.warning(f"新页面反检测注入失败: {e}")

    async def _inject_stealth_scripts(self) -> None:
        """
        注入脚本以隐藏浏览器自动化特征，并注入 WebSocket 拦截器
        """
        try:
            # playwright-stealth 统一处理多项指纹（如果已安装）
            if _STEALTH_AVAILABLE and self.page:
                await stealth_async(self.page)
                logger.info("playwright-stealth 注入成功")

            # 隐藏 webdriver 特征 + WebSocket 拦截的 JavaScript 代码
            stealth_js = """
            // ========== 隐身脚本 ==========
            Object.defineProperty(navigator, 'webdriver', {
                get: () => undefined
            });

            // 伪装 Chrome 对象
            window.chrome = {
                runtime: {}
            };

            // 伪装 permissions
            const originalQuery = window.navigator.permissions.query;
            window.navigator.permissions.query = (parameters) => (
                parameters.name === 'notifications' ?
                    Promise.resolve({ state: Notification.permission }) :
                    originalQuery(parameters)
            );

            // 伪装 plugins
            Object.defineProperty(navigator, 'plugins', {
                get: () => [1, 2, 3, 4, 5]
            });

            // 伪装 languages
            Object.defineProperty(navigator, 'languages', {
                get: () => ['zh-CN', 'zh', 'en-US', 'en']
            });

            // ========== WebSocket 拦截器 ==========
            (function() {
                // 使用 Symbol 作为主要存储方式（更隐蔽）
                const wsSymbol = Symbol.for('_ws_');
                const wsArraySymbol = Symbol.for('_ws_array_');  // 保存所有 WebSocket
                const injectedSymbol = Symbol.for('_inj_');

                if (window[injectedSymbol]) return;

                // 初始化 WebSocket 数组
                if (!window[wsArraySymbol]) {
                    window[wsArraySymbol] = [];
                }

                const OriginalWebSocket = window.WebSocket;

                window.WebSocket = class extends OriginalWebSocket {
                    constructor(...args) {
                        super(...args);
                        const url = args[0];

                        // 闲鱼可能使用多个 WebSocket 服务器
                        const isXianyuWs = url && (
                            url.includes('wss-goofish.dingtalk.com') ||
                            url.includes('msgacs.m.taobao.com') ||
                            url.includes('wss.goofish.com')
                        );

                        if (isXianyuWs) {
                            // 保存到数组中
                            window[wsArraySymbol].push({
                                ws: this,
                                url: url,
                                createdAt: Date.now()
                            });

                            // 优先保存 dingtalk 的 WebSocket（用于发送消息）
                            if (url.includes('wss-goofish.dingtalk.com')) {
                                window[wsSymbol] = this;
                                window.__xianyuWebSocket = this;
                                console.log('[WS_PRIMARY]', url);  // 标记为主 WebSocket
                            } else if (!window[wsSymbol]) {
                                // 如果还没有主 WebSocket，使用当前的
                                window[wsSymbol] = this;
                                window.__xianyuWebSocket = this;
                            }

                            console.log('[WS_CREATED]', url);

                            // 拦截消息接收：使用 addEventListener 确保捕获所有消息
                            // （闲鱼使用 ws.addEventListener('message', fn) 而非 ws.onmessage = fn，
                            //   Object.defineProperty 无法拦截 addEventListener 方式）
                            this.addEventListener('message', function(event) {
                                console.log('[WS_MESSAGE_RECEIVED]', event.data);
                            });

                            // 拦截 send（发送消息）
                            const originalSend = this.send;
                            this.send = function(data) {
                                console.log('[WS_MESSAGE_SENT]', data);
                                return originalSend.call(this, data);
                            };

                            this.addEventListener('open', () => {
                                console.log('[WS_OPENED]', url);
                            });

                            this.addEventListener('close', (event) => {
                                console.log('[WS_CLOSED]', url, 'code=' + event.code);
                            });
                        }

                        return this;
                    }
                };

                // 双重标记
                window[injectedSymbol] = true;
                window.__wsInterceptorInjected = true;  // 向后兼容检测代码
                console.log('[WS_INTERCEPTOR_READY]');
            })();
            """

            await self.context.add_init_script(stealth_js)
            logger.info("隐身脚本和 WebSocket 拦截器注入成功")

        except Exception as e:
            logger.error(f"脚本注入失败: {e}")

    async def _inject_cookies(self, cookies_str: str) -> None:
        """
        注入 cookies 到浏览器上下文

        Args:
            cookies_str: Cookie 字符串
        """
        try:
            cookies_dict = trans_cookies(cookies_str)

            # 转换为 Playwright cookies 格式
            cookies = []
            for name, value in cookies_dict.items():
                cookies.append({
                    "name": name,
                    "value": value,
                    "domain": ".goofish.com",
                    "path": "/"
                })

            await self.context.add_cookies(cookies)
            logger.info("Cookies 注入成功")

        except Exception as e:
            logger.error(f"Cookies 注入失败: {e}")

    async def extract_cookies(self) -> Optional[str]:
        """
        从浏览器提取 cookies

        Returns:
            Optional[str]: Cookie 字符串，失败返回 None
        """
        try:
            if not self.context:
                return None

            cookies = await self.context.cookies()
            cookies_str = "; ".join([f"{cookie['name']}={cookie['value']}" for cookie in cookies])
            return cookies_str

        except Exception as e:
            logger.error(f"提取 cookies 失败: {e}")
            return None

    async def ensure_alive(self) -> bool:
        """
        确保浏览器进程存活，如果崩溃则重启

        Returns:
            bool: 浏览器是否存活
        """
        try:
            if not self._is_running or not self.context:
                return False

            # 持久化 context 没有独立的 browser 对象，通过 context 判断是否存活
            try:
                # 尝试访问 context 属性来检测是否崩溃
                _ = self.context.pages
            except Exception:
                logger.warning("检测到浏览器崩溃")
                self._crash_count += 1

                if self._crash_count >= self._max_crashes:
                    logger.error(f"浏览器崩溃次数过多 ({self._crash_count})，停止重启")
                    return False

                logger.info(f"尝试重启浏览器 (崩溃次数: {self._crash_count})")
                await self.close()
                await asyncio.sleep(2)
                return await self.launch()  # 持久化模式下 Cookie 已保存，无需重传

            return True

        except Exception as e:
            logger.error(f"检查浏览器状态失败: {e}")
            return False

    async def close(self) -> None:
        """优雅地关闭浏览器（持久化 context 会自动保存 Cookie/登录态）"""
        try:
            logger.info("正在关闭浏览器...")

            self._is_running = False

            # 持久化 context 直接关闭即可，内部会保存所有状态
            if self.context:
                await self.context.close()
                self.context = None

            # 持久化模式下没有独立 browser 对象，但 playwright 需要停止
            self.browser = None

            if self.playwright:
                await self.playwright.stop()
                self.playwright = None

            logger.info("浏览器已关闭")

        except Exception as e:
            logger.error(f"关闭浏览器时出错: {e}")

    async def capture_screenshot(self, name: str = "error") -> Optional[str]:
        """
        捕获屏幕截图

        Args:
            name: 截图文件名前缀

        Returns:
            Optional[str]: 截图文件路径，失败返回 None
        """
        try:
            if not self.page:
                return None

            # 创建调试目录
            debug_dir = "./debug_screenshots"
            os.makedirs(debug_dir, exist_ok=True)

            # 生成文件名
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{debug_dir}/{name}_{timestamp}.png"

            # 截图
            await self.page.screenshot(path=filename)
            logger.info(f"截图已保存: {filename}")
            return filename

        except Exception as e:
            logger.error(f"截图失败: {e}")
            return None

    async def get_cdp_session(self):
        """
        获取 Chrome DevTools Protocol 会话

        Returns:
            CDP 会话对象
        """
        if not self.page:
            raise RuntimeError("页面未初始化")

        return await self.page.context.new_cdp_session(self.page)

    def is_running(self) -> bool:
        """
        检查浏览器是否正在运行

        Returns:
            bool: 是否正在运行
        """
        return self._is_running and self.browser is not None and self.browser.is_connected()
