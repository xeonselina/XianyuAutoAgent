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


class BrowserConfig:
    """浏览器配置类"""

    def __init__(self):
        """从环境变量加载浏览器配置"""
        self.headless = os.getenv("BROWSER_HEADLESS", "false").lower() == "true"
        self.debug_port = os.getenv("BROWSER_DEBUG_PORT")
        self.user_data_dir = os.getenv("BROWSER_USER_DATA_DIR", "./browser_data")
        self.viewport_width = int(os.getenv("BROWSER_VIEWPORT_WIDTH", "1280"))
        self.viewport_height = int(os.getenv("BROWSER_VIEWPORT_HEIGHT", "720"))
        self.proxy = os.getenv("BROWSER_PROXY")  # 可选代理配置


class BrowserController:
    """
    浏览器控制器

    管理 Chromium 浏览器实例的生命周期，包括启动、关闭、崩溃恢复等。
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
            cookies_str: Cookie 字符串

        Returns:
            bool: 启动是否成功
        """
        try:
            logger.info("正在启动浏览器...")

            # 启动 Playwright
            self.playwright = await async_playwright().start()

            # 配置浏览器启动参数
            launch_args = []
            if self.config.debug_port:
                launch_args.append(f"--remote-debugging-port={self.config.debug_port}")

            # 启动浏览器
            self.browser = await self.playwright.chromium.launch(
                headless=self.config.headless,
                args=launch_args
            )

            # 创建浏览器上下文
            context_options = {
                "viewport": {
                    "width": self.config.viewport_width,
                    "height": self.config.viewport_height
                },
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36"
            }

            # 添加代理配置（如果有）
            if self.config.proxy:
                context_options["proxy"] = {"server": self.config.proxy}

            self.context = await self.browser.new_context(**context_options)

            # 注入 cookies
            if cookies_str:
                await self._inject_cookies(cookies_str)

            # 创建新页面
            self.page = await self.context.new_page()

            # 导航到闲鱼
            logger.info("正在导航到闲鱼...")
            await self.page.goto("https://www.goofish.com/", wait_until="networkidle")

            self._is_running = True
            logger.info("浏览器启动成功")
            return True

        except Exception as e:
            logger.error(f"浏览器启动失败: {e}")
            await self.close()
            return False

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
            if not self._is_running or not self.browser:
                return False

            # 检查浏览器是否仍然连接
            if not self.browser.is_connected():
                logger.warning("检测到浏览器崩溃")
                self._crash_count += 1

                if self._crash_count >= self._max_crashes:
                    logger.error(f"浏览器崩溃次数过多 ({self._crash_count})，停止重启")
                    return False

                logger.info(f"尝试重启浏览器 (崩溃次数: {self._crash_count})")

                # 提取 cookies 并重启
                cookies_str = await self.extract_cookies()
                await self.close()
                await asyncio.sleep(2)  # 等待 2 秒
                return await self.launch(cookies_str)

            return True

        except Exception as e:
            logger.error(f"检查浏览器状态失败: {e}")
            return False

    async def close(self) -> None:
        """优雅地关闭浏览器"""
        try:
            logger.info("正在关闭浏览器...")

            self._is_running = False

            if self.page:
                await self.page.close()
                self.page = None

            if self.context:
                await self.context.close()
                self.context = None

            if self.browser:
                await self.browser.close()
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
