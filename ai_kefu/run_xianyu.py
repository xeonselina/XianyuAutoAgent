#!/usr/bin/env python3
"""
闲鱼消息拦截器启动脚本

使用 xianyu_interceptor 拦截闲鱼消息并可选地调用后端 AI Agent API
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


async def main():
    """主函数"""
    # 设置日志
    setup_logging()

    logger.info("=" * 60)
    logger.info("闲鱼消息拦截器")
    logger.info("=" * 60)
    logger.info(f"AI 自动回复: {'启用' if config.enable_ai_reply else '禁用'}")
    logger.info(f"对话记录: 将保存到 MySQL" if config.mysql_user else "对话记录: 未配置")
    logger.info("=" * 60)

    # 初始化拦截器组件
    agent_client, session_mapper, manual_mode_manager, conversation_store, message_handler = \
        await initialize_interceptor()

    # 初始化浏览器控制器
    logger.info("正在启动浏览器...")
    browser_controller = BrowserController()

    # 启动浏览器并加载闲鱼页面
    success = await browser_controller.launch(cookies_str=config.cookies_str)
    if not success:
        logger.error("浏览器启动失败")
        return

    # 获取 CDP session
    cdp_session = await browser_controller.page.context.new_cdp_session(browser_controller.page)

    # 初始化 CDP 拦截器
    logger.info("正在设置 CDP 消息拦截...")
    cdp_interceptor = CDPInterceptor(cdp_session=cdp_session)

    # 设置消息回调
    async def on_message(message_data: dict):
        """处理拦截到的消息"""
        try:
            # 这里需要根据实际消息格式转换为 XianyuMessage
            # 暂时简单处理
            await message_handler.handle_message(message_data)
        except Exception as e:
            logger.error(f"处理消息失败: {e}", exc_info=True)

    cdp_interceptor.message_callback = on_message

    # 设置 CDP 监控
    await cdp_interceptor.setup()

    logger.success("拦截器已启动！")
    logger.info("正在监听闲鱼消息...")
    logger.info("发送 '。' 可切换人工/自动模式")
    logger.info("按 Ctrl+C 停止")

    try:
        # 保持运行
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        logger.info("\n收到停止信号，正在关闭...")
    finally:
        # 清理资源
        logger.info("正在清理资源...")
        await cdp_interceptor.close()
        await browser_controller.close()
        if conversation_store:
            conversation_store.close()
        logger.success("拦截器已停止")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("程序已退出")
    except Exception as e:
        logger.error(f"程序异常退出: {e}", exc_info=True)
        sys.exit(1)
