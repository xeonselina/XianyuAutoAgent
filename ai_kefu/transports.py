"""
消息传输实现模块

提供不同的消息传输实现：
- DirectWebSocketTransport: 直接 WebSocket 连接（传统模式）
- BrowserWebSocketTransport: 浏览器中介的 WebSocket（新模式）
"""

import asyncio
import json
import time
import os
import websockets
from typing import Optional, Callable, Dict, Any
from loguru import logger

from messaging_core import MessageTransport
from browser_controller import BrowserController, BrowserConfig
from cdp_interceptor import CDPInterceptor
from XianyuApis import XianyuApis
from utils.xianyu_utils import generate_mid, trans_cookies, generate_device_id


class DirectWebSocketTransport(MessageTransport):
    """
    直接 WebSocket 传输（传统模式）

    直接建立到闲鱼服务器的 WebSocket 连接，保留原有的心跳和 token 刷新逻辑。
    """

    def __init__(self, cookies_str: str):
        """
        初始化直接 WebSocket 传输

        Args:
            cookies_str: Cookie 字符串
        """
        self.cookies_str = cookies_str
        self.cookies = trans_cookies(cookies_str)
        self.xianyu = XianyuApis()
        self.xianyu.session.cookies.update(self.cookies)

        self.myid = self.cookies['unb']
        self.device_id = generate_device_id(self.myid)
        self.base_url = 'wss://wss-goofish.dingtalk.com/'

        self.ws: Optional[websockets.WebSocketClientProtocol] = None
        self._is_connected = False
        self._message_callback: Optional[Callable] = None

        # 心跳配置
        self.heartbeat_interval = int(os.getenv("HEARTBEAT_INTERVAL", "15"))
        self.heartbeat_timeout = int(os.getenv("HEARTBEAT_TIMEOUT", "5"))
        self.last_heartbeat_time = 0
        self.last_heartbeat_response = 0
        self.heartbeat_task: Optional[asyncio.Task] = None

        # Token 配置
        self.token_refresh_interval = int(os.getenv("TOKEN_REFRESH_INTERVAL", "3600"))
        self.token_retry_interval = int(os.getenv("TOKEN_RETRY_INTERVAL", "300"))
        self.last_token_refresh_time = 0
        self.current_token: Optional[str] = None
        self.token_refresh_task: Optional[asyncio.Task] = None

        self._receive_task: Optional[asyncio.Task] = None
        self._connection_restart_flag = False

    async def connect(self) -> bool:
        """建立 WebSocket 连接"""
        try:
            # 获取 token
            if not await self._refresh_token():
                return False

            headers = {
                "Cookie": self.cookies_str,
                "Host": "wss-goofish.dingtalk.com",
                "Connection": "Upgrade",
                "Pragma": "no-cache",
                "Cache-Control": "no-cache",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
                "Origin": "https://www.goofish.com",
                "Accept-Encoding": "gzip, deflate, br, zstd",
                "Accept-Language": "zh-CN,zh;q=0.9",
            }

            self.ws = await websockets.connect(self.base_url, extra_headers=headers)
            await self._init_connection()

            self._is_connected = True

            # 初始化心跳
            self.last_heartbeat_time = time.time()
            self.last_heartbeat_response = time.time()

            logger.info("WebSocket 连接建立成功")
            return True

        except Exception as e:
            logger.error(f"WebSocket 连接失败: {e}")
            return False

    async def disconnect(self) -> None:
        """断开连接"""
        try:
            self._is_connected = False

            # 取消后台任务
            if self.heartbeat_task:
                self.heartbeat_task.cancel()
            if self.token_refresh_task:
                self.token_refresh_task.cancel()
            if self._receive_task:
                self._receive_task.cancel()

            if self.ws:
                await self.ws.close()
                self.ws = None

            logger.info("WebSocket 连接已关闭")

        except Exception as e:
            logger.error(f"断开连接时出错: {e}")

    async def send_message(self, chat_id: str, user_id: str, content: str) -> bool:
        """发送消息"""
        try:
            if not self.ws or not self._is_connected:
                logger.error("WebSocket 未连接")
                return False

            from messaging_core import XianyuMessageCodec
            message = XianyuMessageCodec.encode_message(chat_id, user_id, self.myid, content)
            await self.ws.send(json.dumps(message))

            logger.debug(f"消息已发送: {content[:50]}...")
            return True

        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False

    async def start_receiving(self, message_callback: Callable[[Dict[str, Any]], None]) -> None:
        """开始接收消息"""
        self._message_callback = message_callback

        # 启动心跳任务
        self.heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        # 启动 token 刷新任务
        self.token_refresh_task = asyncio.create_task(self._token_refresh_loop())

        # 启动接收任务
        self._receive_task = asyncio.create_task(self._receive_loop())

    async def _receive_loop(self) -> None:
        """接收消息循环"""
        try:
            async for message in self.ws:
                try:
                    if self._connection_restart_flag:
                        logger.info("检测到连接重启标志")
                        break

                    message_data = json.loads(message)

                    # 处理心跳响应
                    if await self._handle_heartbeat_response(message_data):
                        continue

                    # 发送 ACK
                    await self._send_ack(message_data)

                    # 调用回调
                    if self._message_callback:
                        if asyncio.iscoroutinefunction(self._message_callback):
                            await self._message_callback(message_data)
                        else:
                            self._message_callback(message_data)

                except json.JSONDecodeError:
                    logger.error("消息解析失败")
                except Exception as e:
                    logger.error(f"处理消息时出错: {e}")

        except websockets.exceptions.ConnectionClosed:
            logger.warning("WebSocket 连接已关闭")
            self._is_connected = False
        except Exception as e:
            logger.error(f"接收循环出错: {e}")
            self._is_connected = False

    async def _init_connection(self) -> None:
        """初始化连接"""
        msg = {
            "lwp": "/reg",
            "headers": {
                "cache-header": "app-key token ua wv",
                "app-key": "444e9908a51d1cb236a27862abc769c9",
                "token": self.current_token,
                "ua": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36 DingTalk(2.1.5) OS(Windows/10) Browser(Chrome/133.0.0.0) DingWeb/2.1.5 IMPaaS DingWeb/2.1.5",
                "dt": "j",
                "wv": "im:3,au:3,sy:6",
                "sync": "0,0;0;0;",
                "did": self.device_id,
                "mid": generate_mid()
            }
        }
        await self.ws.send(json.dumps(msg))
        await asyncio.sleep(1)

        msg = {
            "lwp": "/r/SyncStatus/ackDiff",
            "headers": {"mid": "5701741704675979 0"},
            "body": [{
                "pipeline": "sync",
                "tooLong2Tag": "PNM,1",
                "channel": "sync",
                "topic": "sync",
                "highPts": 0,
                "pts": int(time.time() * 1000) * 1000,
                "seq": 0,
                "timestamp": int(time.time() * 1000)
            }]
        }
        await self.ws.send(json.dumps(msg))

    async def _send_ack(self, message_data: Dict[str, Any]) -> None:
        """发送 ACK 响应"""
        try:
            if "headers" in message_data and "mid" in message_data["headers"]:
                ack = {
                    "code": 200,
                    "headers": {
                        "mid": message_data["headers"]["mid"],
                        "sid": message_data["headers"].get("sid", "")
                    }
                }
                for key in ["app-key", "ua", "dt"]:
                    if key in message_data["headers"]:
                        ack["headers"][key] = message_data["headers"][key]
                await self.ws.send(json.dumps(ack))
        except Exception:
            pass

    async def _heartbeat_loop(self) -> None:
        """心跳循环"""
        while self._is_connected:
            try:
                current_time = time.time()

                if current_time - self.last_heartbeat_time >= self.heartbeat_interval:
                    await self._send_heartbeat()

                if (current_time - self.last_heartbeat_response) > (self.heartbeat_interval + self.heartbeat_timeout):
                    logger.warning("心跳响应超时")
                    break

                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"心跳循环出错: {e}")
                break

    async def _send_heartbeat(self) -> None:
        """发送心跳"""
        try:
            heartbeat_msg = {
                "lwp": "/!",
                "headers": {"mid": generate_mid()}
            }
            await self.ws.send(json.dumps(heartbeat_msg))
            self.last_heartbeat_time = time.time()
        except Exception as e:
            logger.error(f"发送心跳失败: {e}")

    async def _handle_heartbeat_response(self, message_data: Dict[str, Any]) -> bool:
        """处理心跳响应"""
        try:
            if (isinstance(message_data, dict) and
                "headers" in message_data and
                "mid" in message_data["headers"] and
                "code" in message_data and
                message_data["code"] == 200):
                self.last_heartbeat_response = time.time()
                return True
        except Exception:
            pass
        return False

    async def _refresh_token(self) -> bool:
        """刷新 token"""
        try:
            token_result = self.xianyu.get_token(self.device_id)
            if 'data' in token_result and 'accessToken' in token_result['data']:
                self.current_token = token_result['data']['accessToken']
                self.last_token_refresh_time = time.time()
                logger.info("Token 刷新成功")
                return True
            else:
                logger.error(f"Token 刷新失败: {token_result}")
                return False
        except Exception as e:
            logger.error(f"Token 刷新异常: {e}")
            return False

    async def _token_refresh_loop(self) -> None:
        """Token 刷新循环"""
        while self._is_connected:
            try:
                current_time = time.time()

                if current_time - self.last_token_refresh_time >= self.token_refresh_interval:
                    if await self._refresh_token():
                        self._connection_restart_flag = True
                        if self.ws:
                            await self.ws.close()
                        break
                    else:
                        await asyncio.sleep(self.token_retry_interval)
                        continue

                await asyncio.sleep(60)

            except Exception as e:
                logger.error(f"Token 刷新循环出错: {e}")
                await asyncio.sleep(60)

    async def is_connected(self) -> bool:
        """检查连接状态"""
        return self._is_connected and self.ws is not None


class BrowserWebSocketTransport(MessageTransport):
    """
    浏览器 WebSocket 传输（新模式）

    通过浏览器和 CDP 拦截 WebSocket 消息。
    """

    def __init__(self, cookies_str: str, config: Optional[BrowserConfig] = None):
        """
        初始化浏览器 WebSocket 传输

        Args:
            cookies_str: Cookie 字符串
            config: 浏览器配置
        """
        self.cookies_str = cookies_str
        self.browser_controller = BrowserController(config)
        self.cdp_interceptor: Optional[CDPInterceptor] = None
        self._is_connected = False
        self._message_callback: Optional[Callable] = None

    async def connect(self) -> bool:
        """建立连接"""
        try:
            # 启动浏览器（打开首页）
            if not await self.browser_controller.launch(self.cookies_str):
                return False

            context = self.browser_controller.context

            # 用于存储所有页面的拦截器
            self.page_interceptors = {}

            # 设置页面监控的辅助函数
            async def setup_page_monitoring(page, should_reload=False):
                """为指定页面设置 CDP 监控"""
                try:
                    page_url = page.url
                    logger.info(f"📄 设置页面监控: {page_url[:80]}...")

                    # 创建 CDP 会话
                    cdp_session = await context.new_cdp_session(page)

                    # 创建拦截器
                    interceptor = CDPInterceptor(cdp_session)

                    # 设置监控
                    if await interceptor.setup():
                        await interceptor.inject_websocket_interceptor()

                        # 保存拦截器
                        page_id = id(page)
                        self.page_interceptors[page_id] = {
                            'page': page,
                            'interceptor': interceptor,
                            'url': page_url
                        }

                        # 【已禁用】不自动刷新页面，避免触发风控
                        # 用户需要手动点击进入消息中心以建立 WebSocket 连接
                        # if should_reload:
                        #     logger.info("🔄 刷新页面以重新建立 WebSocket 连接...")
                        #     try:
                        #         await page.reload(wait_until="networkidle", timeout=10000)
                        #         await asyncio.sleep(2)  # 等待页面稳定
                        #     except Exception as e:
                        #         logger.warning(f"页面刷新失败（可能已关闭）: {e}")
                        #         return

                        # 检查是否已检测到 WebSocket
                        await asyncio.sleep(1)
                        if interceptor.is_connected():
                            logger.info(f"✅ 在页面中检测到 WebSocket: {page_url[:80]}")
                            self.cdp_interceptor = interceptor
                            self.browser_controller.page = page

                except Exception as e:
                    logger.error(f"设置页面监控失败: {e}")

            # 为所有已存在的页面设置监控（而不仅仅是首页）
            all_existing_pages = context.pages
            logger.info(f"📋 发现 {len(all_existing_pages)} 个已存在的页面，开始设置监控...")
            for idx, page in enumerate(all_existing_pages):
                logger.info(f"   正在为页面 {idx+1} 设置监控: {page.url[:80]}")
                await setup_page_monitoring(page, should_reload=False)

            # 监听所有新打开的页面
            async def on_new_page(page):
                logger.info(f"🆕 检测到新页面打开: {page.url[:80]}")
                # 新页面需要刷新以重新触发 WebSocket
                await setup_page_monitoring(page, should_reload=True)

                # 监听页面导航事件（刷新、跳转等）
                async def on_navigation(frame):
                    if frame == page.main_frame:  # 只监听主 frame
                        logger.info(f"🔄 页面导航: {page.url[:80]}")
                        # 页面导航后重新设置监控（导航本身已经刷新了，不需要再刷新）
                        await asyncio.sleep(1)  # 等待页面稳定
                        await setup_page_monitoring(page, should_reload=False)

                page.on("framenavigated", on_navigation)

            context.on("page", on_new_page)

            # 监听所有页面的 popup 事件
            async def on_popup(popup):
                logger.info(f"🪟 检测到弹出窗口: {popup.url[:80] if popup.url else 'about:blank'}")
                await setup_page_monitoring(popup, should_reload=True)

            for page in context.pages:
                page.on("popup", on_popup)

            # 每当有新页面时，也为它添加 popup 监听
            original_on_new_page = on_new_page
            async def on_new_page_with_popup(page):
                await original_on_new_page(page)
                page.on("popup", on_popup)

            context.on("page", on_new_page_with_popup)

            logger.info("📡 已启动全局页面监控（包括刷新检测和弹窗检测）")

            # 等待 WebSocket 连接建立
            logger.info("=" * 60)
            logger.info("💡 提示：请在浏览器中点击进入消息中心或任意聊天")
            logger.info("   系统会自动监控所有页面（包括刷新后的页面和弹窗）")
            logger.info("=" * 60)

            max_wait = 120  # 最多等待 2 分钟
            for i in range(max_wait):
                await asyncio.sleep(1)

                # 检查所有拦截器，看是否有已连接的
                for page_id, page_data in self.page_interceptors.items():
                    interceptor = page_data['interceptor']

                    # 被动检测：通过事件
                    if interceptor.is_connected():
                        self.cdp_interceptor = interceptor
                        self.browser_controller.page = page_data['page']
                        logger.info(f"✅ WebSocket 连接已建立（等待 {i+1} 秒）")
                        logger.info(f"   活动页面: {page_data['url'][:80]}")
                        break

                    # 主动检测：每5秒检查一次页面中的 WebSocket
                    if (i + 1) % 5 == 0:
                        try:
                            if await interceptor.check_websocket_in_page():
                                self.cdp_interceptor = interceptor
                                self.browser_controller.page = page_data['page']
                                logger.info(f"✅ WebSocket 连接已建立（主动检测，等待 {i+1} 秒）")
                                logger.info(f"   活动页面: {page_data['url'][:80]}")
                                break
                        except Exception as e:
                            logger.debug(f"主动检测出错: {e}")

                if self.cdp_interceptor and self.cdp_interceptor.is_connected():
                    break

                if (i + 1) % 10 == 0:
                    logger.info(f"⏳ 仍在等待 WebSocket 连接... ({i+1}/{max_wait}秒)")
                    logger.info(f"   已监控 {len(self.page_interceptors)} 个页面")
                    logger.info(f"   💡 提示: 主动检测每 5 秒运行一次")

            if not self.cdp_interceptor or not self.cdp_interceptor.is_connected():
                logger.error("❌ 超时：WebSocket 未建立连接")
                logger.error("请检查：")
                logger.error("  1. 浏览器是否已登录")
                logger.error("  2. 是否已点击进入消息中心或聊天页面")
                logger.error("  3. 如果已进入，尝试刷新页面（F5）")
                return False

            self._is_connected = True
            logger.info("=" * 60)
            logger.info("🎉 浏览器 WebSocket 传输建立成功！")
            logger.info("=" * 60)
            return True

        except Exception as e:
            logger.error(f"浏览器 WebSocket 传输连接失败: {e}")
            import traceback
            logger.debug(f"错误堆栈: {traceback.format_exc()}")
            return False

    async def disconnect(self) -> None:
        """断开连接"""
        try:
            if self.cdp_interceptor:
                await self.cdp_interceptor.close()

            await self.browser_controller.close()
            self._is_connected = False

            logger.info("浏览器 WebSocket 传输已关闭")

        except Exception as e:
            logger.error(f"断开连接时出错: {e}")

    async def send_message(self, chat_id: str, user_id: str, content: str) -> bool:
        """发送消息"""
        try:
            if not self.cdp_interceptor or not self._is_connected:
                logger.error("CDP 拦截器未连接")
                return False

            # 获取 myid (从 cookies 中提取)
            cookies = trans_cookies(self.cookies_str)
            myid = cookies.get('unb', '')

            from messaging_core import XianyuMessageCodec
            message = XianyuMessageCodec.encode_message(chat_id, user_id, myid, content)

            return await self.cdp_interceptor.send_message(message)

        except Exception as e:
            logger.error(f"发送消息失败: {e}")
            return False

    async def start_receiving(self, message_callback: Callable[[Dict[str, Any]], None]) -> None:
        """开始接收消息"""
        self._message_callback = message_callback

        # 设置 CDP 拦截器的回调
        if self.cdp_interceptor:
            self.cdp_interceptor.set_message_callback(message_callback)

    async def is_connected(self) -> bool:
        """检查连接状态"""
        return (self._is_connected and
                self.browser_controller.is_running() and
                self.cdp_interceptor and
                self.cdp_interceptor.is_connected())
