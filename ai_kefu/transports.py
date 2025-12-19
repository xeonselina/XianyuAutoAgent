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
            # 启动浏览器
            if not await self.browser_controller.launch(self.cookies_str):
                return False

            # 获取 CDP 会话
            cdp_session = await self.browser_controller.get_cdp_session()

            # 创建 CDP 拦截器
            self.cdp_interceptor = CDPInterceptor(cdp_session)

            # 设置 CDP 监控
            if not await self.cdp_interceptor.setup():
                return False

            # 注入 WebSocket 拦截器
            await self.cdp_interceptor.inject_websocket_interceptor()

            # 等待 WebSocket 连接建立
            max_wait = 30  # 最多等待 30 秒
            for i in range(max_wait):
                await asyncio.sleep(1)
                if self.cdp_interceptor.is_connected():
                    break

            if not self.cdp_interceptor.is_connected():
                logger.error("超时：WebSocket 未建立连接")
                return False

            self._is_connected = True
            logger.info("浏览器 WebSocket 传输建立成功")
            return True

        except Exception as e:
            logger.error(f"浏览器 WebSocket 传输连接失败: {e}")
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
