#!/usr/bin/env python3
"""
WebSocket 诊断脚本

帮助诊断闲鱼 WebSocket 连接的位置和创建时机
"""

import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from loguru import logger
from xianyu_interceptor import setup_logging, config
from xianyu_interceptor.browser_controller import BrowserController
from playwright.async_api import CDPSession


async def diagnose():
    """诊断函数"""
    setup_logging()

    logger.info("=" * 60)
    logger.info("WebSocket 诊断工具")
    logger.info("=" * 60)

    # 启动浏览器
    logger.info("正在启动浏览器...")
    browser_controller = BrowserController()
    success = await browser_controller.launch(cookies_str=config.cookies_str)

    if not success:
        logger.error("浏览器启动失败")
        return

    # 获取 CDP session
    cdp_session: CDPSession = await browser_controller.page.context.new_cdp_session(browser_controller.page)

    # 启用所有网络监控
    await cdp_session.send("Network.enable")
    await cdp_session.send("Page.enable")
    await cdp_session.send("Runtime.enable")

    # 记录所有 WebSocket 相关事件
    websocket_events = []

    async def on_ws_created(params):
        url = params.get("url", "")
        request_id = params.get("requestId", "")
        websocket_events.append(("created", url, request_id))
        logger.info(f"🔵 Network.webSocketCreated: {url}")

    async def on_ws_frame_received(params):
        request_id = params.get("requestId", "")
        response = params.get("response", {})
        payload = response.get("payloadData", "")[:100]
        websocket_events.append(("frame_received", request_id, payload))
        logger.info(f"📥 Network.webSocketFrameReceived: {request_id} - {payload}")

    async def on_ws_frame_sent(params):
        request_id = params.get("requestId", "")
        response = params.get("response", {})
        payload = response.get("payloadData", "")[:100]
        websocket_events.append(("frame_sent", request_id, payload))
        logger.info(f"📤 Network.webSocketFrameSent: {request_id} - {payload}")

    async def on_console(params):
        console_type = params.get("type", "")
        args = params.get("args", [])
        if args:
            first_arg = args[0].get("value", "")
            if "[WS_" in str(first_arg) or "WebSocket" in str(first_arg):
                logger.info(f"🟢 Console ({console_type}): {first_arg}")

    async def on_request(params):
        request = params.get("request", {})
        url = request.get("url", "")
        if "wss://" in url or "ws://" in url:
            logger.info(f"🟡 Network.requestWillBeSent: {url}")

    async def on_response(params):
        response = params.get("response", {})
        url = response.get("url", "")
        if "wss://" in url or "ws://" in url:
            logger.info(f"🟠 Network.responseReceived: {url}")

    async def on_frame_navigated(params):
        frame = params.get("frame", {})
        url = frame.get("url", "")
        frame_id = frame.get("id", "")
        logger.info(f"🔄 Page.frameNavigated: {url} (frameId: {frame_id})")

    # 注册事件监听器
    cdp_session.on("Network.webSocketCreated", on_ws_created)
    cdp_session.on("Network.webSocketFrameReceived", on_ws_frame_received)
    cdp_session.on("Network.webSocketFrameSent", on_ws_frame_sent)
    cdp_session.on("Runtime.consoleAPICalled", on_console)
    cdp_session.on("Network.requestWillBeSent", on_request)
    cdp_session.on("Network.responseReceived", on_response)
    cdp_session.on("Page.frameNavigated", on_frame_navigated)

    # 启用 Fetch 域
    try:
        await cdp_session.send("Fetch.enable", {
            "patterns": [
                {"urlPattern": "*", "requestStage": "Request"}
            ]
        })

        async def on_fetch_paused(params):
            request_id = params.get("requestId")
            request = params.get("request", {})
            url = request.get("url", "")
            resource_type = params.get("resourceType", "")

            if "wss://" in url or "ws://" in url:
                logger.info(f"🚀 Fetch.requestPaused: {url} (type: {resource_type})")

            # 继续请求
            try:
                await cdp_session.send("Fetch.continueRequest", {"requestId": request_id})
            except:
                pass

        cdp_session.on("Fetch.requestPaused", on_fetch_paused)
        logger.info("✅ Fetch 域已启用")
    except Exception as e:
        logger.warning(f"启用 Fetch 域失败: {e}")

    # 注入更详细的监控脚本
    monitor_js = """
    (function() {
        console.log('[DIAG] 开始监控 WebSocket');

        // 保存原始 WebSocket
        const OriginalWebSocket = window.WebSocket;
        let wsCount = 0;

        // 拦截 WebSocket 构造函数
        window.WebSocket = class extends OriginalWebSocket {
            constructor(...args) {
                const url = args[0];
                wsCount++;
                console.log(`[DIAG] WebSocket #${wsCount} 创建:`, url);
                console.log(`[DIAG] 调用栈:`, new Error().stack);

                super(...args);

                this.addEventListener('open', () => {
                    console.log(`[DIAG] WebSocket #${wsCount} 已连接:`, url);
                });

                this.addEventListener('message', (event) => {
                    console.log(`[DIAG] WebSocket #${wsCount} 收到消息:`, event.data.substring(0, 100));
                });

                this.addEventListener('error', (error) => {
                    console.log(`[DIAG] WebSocket #${wsCount} 错误:`, error);
                });

                this.addEventListener('close', () => {
                    console.log(`[DIAG] WebSocket #${wsCount} 已关闭`);
                });

                return this;
            }
        };

        // 定期检查是否有 WebSocket
        setInterval(() => {
            console.log(`[DIAG] WebSocket 计数: ${wsCount}`);
        }, 10000);

        console.log('[DIAG] WebSocket 监控已就绪');
    })();
    """

    await cdp_session.send("Runtime.evaluate", {"expression": monitor_js})
    logger.info("✅ 监控脚本已注入")

    logger.info("=" * 60)
    logger.info("🔔 请在浏览器中操作:")
    logger.info("   1. 点击进入消息中心")
    logger.info("   2. 打开一个聊天会话")
    logger.info("   3. 发送一条消息")
    logger.info("=" * 60)
    logger.info("观察日志输出，查找 WebSocket 创建和消息事件")
    logger.info("按 Ctrl+C 停止诊断")
    logger.info("=" * 60)

    try:
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n诊断结束")
        logger.info(f"捕获到 {len(websocket_events)} 个 WebSocket 事件")
        for event in websocket_events:
            logger.info(f"  - {event}")
    finally:
        await browser_controller.close()


if __name__ == "__main__":
    try:
        asyncio.run(diagnose())
    except KeyboardInterrupt:
        logger.info("诊断已取消")
    except Exception as e:
        logger.error(f"诊断异常: {e}", exc_info=True)
