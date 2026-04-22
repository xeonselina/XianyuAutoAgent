#!/usr/bin/env python3
"""
闲鱼消息拦截器启动脚本

使用 xianyu_interceptor 拦截闲鱼消息并通过 POST /xianyu/inbound 转发给 AI API。
拦截器是纯传输层中继，不包含任何业务逻辑。
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from loguru import logger
from xianyu_interceptor import (
    initialize_interceptor,
    run_interceptor,
    setup_logging,
    config
)
from xianyu_interceptor.browser_controller import BrowserController
from xianyu_interceptor.cdp_interceptor import CDPInterceptor
from xianyu_interceptor.messaging_core import XianyuMessageCodec
from xianyu_interceptor.models import XianyuMessage, XianyuMessageType
from xianyu_interceptor.image_handler import get_image_handler
from xianyu_interceptor.history_message_parser import HistoryMessageParser
from xianyu_interceptor.browser_transport import BrowserTransport
from ai_kefu.config.settings import settings
import json


async def _save_history_messages_to_api(history_messages: list) -> None:
    """
    将解析出的历史消息通过 HTTP POST 到 /xianyu/history-inbound 保存到数据库。
    直接调用 conversation_store 依赖于 API 层的单例，所以改为 HTTP 调用。
    若无专用端点则降级为逐条调用 /xianyu/inbound（is_history=True 跳过 AI）。
    """
    import httpx
    inbound_url = f"{config.agent_service_url.rstrip('/')}/xianyu/inbound"

    seller_user_id = settings.seller_user_id

    for xianyu_message in history_messages:
        try:
            content = xianyu_message.content or ""
            if not content.strip():
                continue

            metadata = xianyu_message.metadata or {}
            encrypted_uid = xianyu_message.encrypted_uid or metadata.get("encrypted_uid") or None
            message_id = xianyu_message.message_id or metadata.get("message_id") or None

            # Auto-record UID mapping at interceptor level
            if xianyu_message.user_id and encrypted_uid:
                from xianyu_interceptor.uid_mapper import record_uid_mapping
                record_uid_mapping(xianyu_message.user_id, encrypted_uid)

            is_self_sent = (
                bool(seller_user_id)
                and str(xianyu_message.user_id).strip() == str(seller_user_id).strip()
            )

            payload = {
                "chat_id": xianyu_message.chat_id,
                "user_id": xianyu_message.user_id,
                "content": content,
                "item_id": xianyu_message.item_id,
                "user_nickname": xianyu_message.user_nickname or metadata.get("reminder_title"),
                "encrypted_uid": encrypted_uid,
                "is_self_sent": is_self_sent,
                "message_id": message_id,
                "item_title": metadata.get("item_title"),
                "item_price": None,
                "timestamp": xianyu_message.timestamp,
                "raw_data": None,
                "metadata": {
                    **metadata,
                    "source": "history_api",
                    "history_only": True,   # tells the API not to trigger AI reply
                },
            }

            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(inbound_url, json=payload)
                resp.raise_for_status()

        except Exception as e:
            logger.warning(f"保存历史消息失败 (chat_id={xianyu_message.chat_id}): {e}")


async def _push_cookies_to_api(browser_controller, agent_service_url: str) -> None:
    """
    Extract current browser cookies and push them to the FastAPI process
    so GoofishProvider can be re-initialized with valid credentials.
    """
    import httpx
    try:
        cookies_str = await browser_controller.extract_cookies()
        if not cookies_str:
            logger.warning("[cookie-push] No cookies extracted from browser, skipping")
            return
        url = f"{agent_service_url.rstrip('/')}/xianyu/update-cookies"
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"cookies_str": cookies_str})
            data = resp.json()
        if data.get("success"):
            logger.info(f"[cookie-push] GoofishProvider updated, user_id={data.get('user_id')}")
        else:
            logger.warning(f"[cookie-push] API rejected cookies: {data.get('message')}")
    except Exception as e:
        logger.warning(f"[cookie-push] Failed to push cookies to API: {e}")


async def main():
    """主函数"""
    # 设置日志
    setup_logging()

    logger.info("=" * 60)
    logger.info("闲鱼消息拦截器 (传输层中继)")
    logger.info("=" * 60)
    logger.info(f"AI 自动回复: {'启用' if config.enable_ai_reply else '禁用'}")
    logger.info(f"AI API 地址: {config.agent_service_url}")
    logger.info("=" * 60)

    # 初始化拦截器（返回 MessageHandler 薄中继）
    message_handler = await initialize_interceptor()

    # 初始化浏览器控制器
    logger.info("正在启动浏览器...")
    browser_controller = BrowserController()

    # 启动浏览器并加载闲鱼页面
    success = await browser_controller.launch(cookies_str=config.cookies_str)
    if not success:
        logger.error("浏览器启动失败")
        return

    # Push whatever cookies the browser has after launch (may already be valid)
    await _push_cookies_to_api(browser_controller, config.agent_service_url)

    # ============================================================
    # 【重要】自动获取卖家 user_id（用于区分消息方向）
    # seller_user_id 现在由 API 层的 settings 管理，
    # 但拦截器也需要它来设置 is_self_sent 字段。
    # 优先使用 settings.seller_user_id（来自 .env）；
    # 若未配置则尝试从 Cookie 中提取。
    # ============================================================
    seller_user_id = settings.seller_user_id
    if not seller_user_id:
        # 尝试从 Cookie 中提取 unb（淘宝/闲鱼的用户ID）
        from utils.xianyu_utils import trans_cookies
        cookies_dict = trans_cookies(config.cookies_str)
        unb = cookies_dict.get("unb", "")
        if unb:
            seller_user_id = unb
            logger.info(f"✅ 自动从 Cookie 提取卖家 user_id: {unb}")
        else:
            # 尝试从浏览器上下文的 cookies 中获取
            try:
                browser_cookies = await browser_controller.context.cookies()
                for cookie in browser_cookies:
                    if cookie.get("name") == "unb":
                        seller_user_id = cookie["value"]
                        logger.info(f"✅ 自动从浏览器 Cookie 提取卖家 user_id: {cookie['value']}")
                        break
            except Exception as e:
                logger.debug(f"从浏览器 Cookie 提取失败: {e}")

        if not seller_user_id:
            logger.warning(
                "⚠️ 未能自动获取卖家 user_id！请在 .env 中设置 SELLER_USER_ID。"
                "否则无法区分自己发的消息和用户发的消息。"
            )
    else:
        logger.info(f"卖家 user_id: {seller_user_id}")

    # ============================================================
    # 【重要】创建消息传输层 (BrowserTransport)
    # ============================================================
    browser_transport = BrowserTransport(seller_user_id=seller_user_id)
    message_handler.transport = browser_transport
    logger.info("✅ BrowserTransport 已创建并注入 message_handler")

    # 将 transport 注入到钉钉回复服务（session_mapper 不再由拦截器层管理）
    try:
        from ai_kefu.services.dingtalk_reply_handler import set_global_transport
        set_global_transport(browser_transport)
        logger.info("✅ 钉钉回复服务已注入 transport")
    except Exception as e:
        logger.warning(f"钉钉回复服务注入失败（不影响主流程）: {e}")

    # ============================================================
    # 【钉钉 Stream 模式】启动长连接客户端接收群消息
    # ============================================================
    try:
        from ai_kefu.services.dingtalk_stream_client import get_dingtalk_stream_service
        stream_service = get_dingtalk_stream_service()
        await stream_service.start()
    except Exception as e:
        logger.warning(f"钉钉 Stream 客户端启动失败（不影响主流程）: {e}")

    # ============================================================
    # 【重要】多页面 WebSocket 监听机制
    # ============================================================
    # 闲鱼的消息中心可能在以下情况下创建 WebSocket：
    # 1. 用户点击导航到新页面（如消息中心）
    # 2. 页面内部跳转/刷新
    # 3. 打开新的 Tab
    #
    # 因此必须监听：
    # - 所有已存在的页面（context.pages）
    # - 新打开的页面（context.on("page")）
    # - 页面导航事件（page.on("framenavigated")）
    #
    # 【警告】删除此机制会导致：
    # - 只能监听首页的 WebSocket（通常没有）
    # - 用户进入消息中心后无法检测到 WebSocket
    # - 无法拦截任何消息
    #
    # 参考：commit 7f54081 "稳定了 ws"
    # ============================================================

    # 用于存储所有页面的拦截器
    page_interceptors = {}
    active_cdp_interceptor = None

    # 初始化图片处理器
    image_handler = get_image_handler(save_dir=config.image_save_dir)

    # 设置消息回调
    async def on_message(message_data: dict):
        """
        处理拦截到的 WebSocket 消息

        【重要】WebSocket 消息需要解码和转换：
        1. 使用 XianyuMessageCodec.decode_message() 解码原始消息
        2. 使用 XianyuMessageCodec.extract_message_data() 提取标准化数据
        3. 转换为 XianyuMessage 对象
        4. 传递给 message_handler（薄中继，POST 到 /xianyu/inbound）
        """
        try:
            # 过滤心跳和系统消息，减少日志噪音
            # 心跳响应: {"headers":{...},"code":200} 且没有 body
            # 心跳请求已在 _on_console_api 中过滤
            if message_data.get("code") == 200 and "body" not in message_data:
                return  # 静默忽略心跳响应

            # ============================================================
            # 【调试】完整记录所有WebSocket消息，寻找历史消息
            # ============================================================
            message_str = json.dumps(message_data, ensure_ascii=False)

            # 检查消息中是否包含关键词（可能包含历史消息）
            history_keywords = [
                "conversation", "message", "history", "list",
                "sync", "query", "get", "load"
            ]

            # 检查lwp路径或body中是否包含历史消息相关的关键词
            lwp = message_data.get("lwp", "")
            body = message_data.get("body", {})
            body_str = json.dumps(body, ensure_ascii=False) if body else ""

            contains_history_keywords = any(
                keyword in lwp.lower() or keyword in body_str.lower()
                for keyword in history_keywords
            )

            if contains_history_keywords:
                logger.info(f"🔍 [历史调试] 可能包含历史消息的WebSocket消息:")
                logger.info(f"   lwp: {lwp}")
                if len(message_str) > 2000:
                    logger.info(f"   消息内容（前2000字符）: {message_str[:2000]}...")
                    logger.info(f"   消息长度: {len(message_str)} 字节")
                else:
                    logger.info(f"   完整消息: {message_str}")

            # ============================================================
            # 【历史消息处理】检查是否是历史消息API响应
            # ============================================================
            if HistoryMessageParser.is_history_message_response(message_data):
                logger.info(f"📜 检测到历史消息API响应，开始解析...")

                # 解析历史消息列表
                history_messages = HistoryMessageParser.parse_history_messages(message_data)

                if history_messages:
                    logger.info(f"✅ 解析到 {len(history_messages)} 条历史消息，正在保存到数据库...")

                    # ============================================================
                    # 【重要】历史消息只保存到数据库，不触发 AI 回复！
                    # 通过 /xianyu/inbound 发送，metadata 中携带 history_only=True，
                    # API 层收到后仅入库，不调用 AI Agent。
                    # ============================================================
                    saved_count = len(history_messages)
                    await _save_history_messages_to_api(history_messages)
                    logger.success(f"🎉 已转发 {saved_count} 条历史消息到 API 层入库")
                else:
                    logger.warning("未能从历史消息响应中解析到消息")

                # 历史消息已处理完成，不再继续解码流程
                return

            # 步骤 1: 解码消息
            # 只有 syncPushPackage 格式的消息（别人发给你的）才能被解码
            # 其他消息（响应、状态更新等）会被静默忽略
            decoded_message = XianyuMessageCodec.decode_message(message_data)
            if not decoded_message:
                # 记录被过滤的消息（如果包含历史关键词）
                if contains_history_keywords:
                    logger.info(f"   ⚠️ 此消息无法被decode_message解码（可能需要新的解码逻辑）")
                return  # 静默忽略非聊天消息

            # 🔬 解码成功后，先打印解码结果的分类信息
            msg_type = XianyuMessageCodec.classify_message(decoded_message)
            logger.info(f"🔬 [解码成功] 消息分类={msg_type.value}, 顶层键={list(decoded_message.keys())}")

            # 步骤 2: 提取标准化数据
            std_message = XianyuMessageCodec.extract_message_data(decoded_message)
            if not std_message:
                return  # 无法提取的消息（如订单消息）静默忽略

            # 🔬 打印提取结果
            logger.info(f"🔬 [提取结果] type={std_message.message_type.value}, user_id={std_message.user_id}, chat_id={std_message.chat_id}, content={std_message.content[:50] if std_message.content else 'None'}")

            # 步骤 3: 转换为 XianyuMessage 对象
            metadata = std_message.metadata or {}
            is_self_sent = (
                bool(seller_user_id) and
                std_message.user_id == seller_user_id
            )
            xianyu_message = XianyuMessage(
                message_type=XianyuMessageType(std_message.message_type.value),
                chat_id=std_message.chat_id,
                user_id=std_message.user_id,
                user_nickname=metadata.get("user_nickname") or metadata.get("reminder_title") or None,
                encrypted_uid=metadata.get("encrypted_uid") or None,
                content=std_message.content,
                item_id=std_message.item_id,
                item_title=metadata.get("item_title") or None,
                item_price=None,  # 闲鱼 WebSocket 不携带价格
                message_id=metadata.get("message_id") or None,
                is_self_sent=is_self_sent,
                timestamp=std_message.timestamp,
                raw_data=std_message.raw_data,
                metadata=metadata
            )

            # 【重要】处理图片消息
            if xianyu_message.content and "[图片]" in xianyu_message.content:
                logger.info(f"检测到图片消息 (chat_id={xianyu_message.chat_id}, user_id={xianyu_message.user_id})")

                # 调试：记录原始数据（可以根据需要启用）
                if logger.level("DEBUG").no >= logger._core.min_level:
                    logger.debug(f"图片消息原始数据: {json.dumps(std_message.raw_data, ensure_ascii=False, indent=2)}")

                # 下载并保存图片
                try:
                    saved_files = await image_handler.handle_image_message(
                        raw_data=std_message.raw_data,
                        chat_id=xianyu_message.chat_id,
                        user_id=xianyu_message.user_id,
                        timestamp=xianyu_message.timestamp
                    )

                    if saved_files:
                        # 将保存的文件路径添加到 metadata 中
                        xianyu_message.metadata["image_files"] = saved_files
                        logger.info(f"图片已保存: {saved_files}")
                    else:
                        logger.warning("未能从图片消息中提取或下载图片")
                except Exception as e:
                    logger.error(f"处理图片消息失败: {e}", exc_info=True)

            # 步骤 4: 传递给消息处理器（薄中继，POST 到 /xianyu/inbound）
            await message_handler.handle_message(xianyu_message)

        except Exception as e:
            logger.error(f"处理消息失败: {e}", exc_info=True)

    # 设置页面监控的辅助函数
    async def setup_page_monitoring(page, should_reload=False):
        """
        为指定页面设置 CDP 监控

        【重要】此函数为每个页面注入 WebSocket 拦截器
        - 创建独立的 CDP session
        - 注入 JavaScript 拦截代码
        - 监听 WebSocket 创建和消息事件
        """
        nonlocal active_cdp_interceptor
        try:
            page_url = page.url
            logger.info(f"📄 设置页面监控: {page_url[:80]}...")

            # 创建 CDP 会话
            cdp_session = await browser_controller.context.new_cdp_session(page)

            # 创建拦截器
            interceptor = CDPInterceptor(cdp_session)
            interceptor.message_callback = on_message

            # 设置监控
            if await interceptor.setup():
                await interceptor.inject_websocket_interceptor()

                # 保存拦截器
                page_id = id(page)
                page_interceptors[page_id] = {
                    'page': page,
                    'interceptor': interceptor,
                    'url': page_url
                }

                # 检查是否已检测到 WebSocket
                await asyncio.sleep(1)
                if interceptor.is_connected():
                    logger.info(f"✅ 在页面中检测到 WebSocket: {page_url[:80]}")
                    active_cdp_interceptor = interceptor
                    browser_transport.set_interceptor(interceptor)

        except Exception as e:
            logger.error(f"设置页面监控失败: {e}")

    # ============================================================
    # 步骤 1: 为所有已存在的页面设置监控
    # ============================================================
    # 【重要】不要只监听 browser_controller.page（首页）
    # 必须监听所有已打开的页面，因为：
    # - 用户可能已经打开了消息中心
    # - 浏览器可能有多个 Tab
    # ============================================================
    logger.info("正在设置 CDP 消息拦截...")
    all_existing_pages = browser_controller.context.pages
    logger.info(f"📋 发现 {len(all_existing_pages)} 个已存在的页面，开始设置监控...")
    for idx, page in enumerate(all_existing_pages):
        logger.info(f"   正在为页面 {idx+1} 设置监控: {page.url[:80]}")
        await setup_page_monitoring(page, should_reload=False)

    # ============================================================
    # 步骤 2: 监听所有新打开的页面
    # ============================================================
    # 【重要】当用户点击"消息中心"时，可能会：
    # - 在当前页面导航（触发 framenavigated）
    # - 打开新的 Tab（触发 context.on("page")）
    # - 打开 Popup 窗口（也会触发 context.on("page")）
    #
    # 【警告】删除此监听器会导致新页面无法检测 WebSocket
    # ============================================================
    async def on_new_page(page):
        logger.info(f"🆕 检测到新页面打开: {page.url[:80]}")
        await setup_page_monitoring(page, should_reload=False)

        # ============================================================
        # 步骤 3: 监听页面导航事件（刷新、跳转等）
        # ============================================================
        # 【重要】当页面内部跳转（如 SPA 路由）或刷新时：
        # - 旧的 WebSocket 拦截器会失效
        # - 需要重新注入拦截代码
        #
        # 【警告】删除此监听器会导致页面导航后无法检测 WebSocket
        # ============================================================
        async def on_navigation(frame):
            if frame == page.main_frame:  # 只监听主 frame
                logger.info(f"🔄 页面导航: {page.url[:80]}")
                # 页面导航后重新设置监控
                await asyncio.sleep(1)  # 等待页面稳定
                await setup_page_monitoring(page, should_reload=False)

        page.on("framenavigated", on_navigation)

    browser_controller.context.on("page", on_new_page)

    # ============================================================
    # 多页面监听机制设置完成
    # ============================================================

    logger.success("拦截器已启动！")
    logger.info("正在监听闲鱼消息...")
    logger.info("发送 '。' 可切换人工/自动模式")
    logger.info("按 Ctrl+C 停止")

    try:
        # ============================================================
        # 主循环：定期检查 WebSocket 连接状态
        # ============================================================
        # 【重要】为什么需要定期检查：
        # - WebSocket 可能在页面加载完成后才创建
        # - 某些情况下 CDP 事件可能丢失
        # - 提供兜底的检测机制
        # ============================================================
        check_interval = 5  # 每 5 秒检查一次
        last_check_time = 0
        websocket_detected = False

        # 定期刷新推送 cookie（每 30 分钟），防止服务端刷新 token 后 GoofishProvider 持有旧 cookie
        cookie_push_interval = 1800  # 30 分钟
        last_cookie_push_time = 0

        while True:
            await asyncio.sleep(1)

            import time
            current_time = time.time()

            # 定期刷新 cookie 推送（无论 WebSocket 是否已检测到）
            if current_time - last_cookie_push_time >= cookie_push_interval:
                last_cookie_push_time = current_time
                await _push_cookies_to_api(browser_controller, config.agent_service_url)

            # 定期检查所有页面的 WebSocket（仅在未检测到时）
            if not websocket_detected and (current_time - last_check_time) >= check_interval:
                last_check_time = current_time
                logger.debug("🔍 执行 WebSocket 主动检测...")

                # 【重要】遍历所有页面的拦截器，而不是单个
                # 因为 WebSocket 可能在任何一个页面中建立
                for page_id, info in page_interceptors.items():
                    interceptor = info['interceptor']
                    if await interceptor.check_websocket_in_page():
                        websocket_detected = True
                        active_cdp_interceptor = interceptor
                        browser_transport.set_interceptor(interceptor)
                        logger.info(f"✅ WebSocket 连接已建立（页面: {info['url'][:80]}），停止定期检测")
                        # Push freshest cookies — definitive login confirmation
                        await _push_cookies_to_api(browser_controller, config.agent_service_url)
                        break

    except KeyboardInterrupt:
        logger.info("\n收到停止信号，正在关闭...")
    finally:
        # 清理资源
        logger.info("正在清理资源...")
        for page_id, info in page_interceptors.items():
            await info['interceptor'].close()
        await browser_controller.close()
        logger.success("拦截器已停止")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序已退出")
    except Exception as e:
        logger.error(f"程序异常退出: {e}", exc_info=True)
        sys.exit(1)
