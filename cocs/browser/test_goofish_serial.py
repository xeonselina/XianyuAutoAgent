#!/usr/bin/env python3
"""
测试咸鱼浏览器串行消息处理功能
"""

import asyncio
import time
from goofish_browser import GoofishBrowser
from loguru import logger


async def message_handler(message: dict):
    """消息处理回调函数 - 模拟耗时处理"""
    logger.info(f"🔄 开始处理消息: {message.get('text', '')[:50]}")
    logger.info(f"📝 消息详情: 发送者={message.get('sender', 'Unknown')}, 时间={message.get('timestamp', 'Unknown')}")
    
    # 模拟消息处理耗时（例如调用AI、数据库操作等）
    processing_time = 3  # 3秒处理时间
    logger.info(f"⏳ 模拟处理耗时: {processing_time}秒")
    await asyncio.sleep(processing_time)
    
    # 模拟处理结果
    response = f"已收到您的消息: {message.get('text', '')[:20]}..., 正在为您处理中"
    logger.info(f"✅ 消息处理完成，准备回复: {response}")
    
    # 这里可以调用 browser.send_message(response) 来回复


async def main():
    # 创建浏览器实例，指定数据存储目录
    browser = GoofishBrowser(headless=False, data_dir="./test_goofish_data")
    
    try:
        logger.info("🚀 启动咸鱼浏览器...")
        if not await browser.start():
            logger.error("❌ 浏览器启动失败")
            return
        
        logger.info("⏳ 等待用户登录...")
        if not await browser.wait_for_login():
            logger.error("❌ 用户登录超时")
            return
        
        logger.info("✅ 用户已登录，开始监控新消息")
        
        # 显示当前消息统计
        stats = browser.get_message_stats()
        logger.info(f"📊 消息统计: {stats}")
        
        # 可选：重置特定联系人的消息历史（用于测试）
        # browser.reset_message_history("测试联系人")
        
        logger.info("🔍 开始串行监控新消息...")
        logger.info("💡 提示：")
        logger.info("   - 每条新消息会被串行处理，确保处理完一条再处理下一条")
        logger.info("   - 使用持久化存储，程序重启后不会重复处理已处理的消息")
        logger.info("   - 结合新消息标记和消息内容双重判断，确保准确性")
        logger.info("   - 按 Ctrl+C 停止监控")
        
        # 开始监控新消息（这是一个阻塞调用，会持续运行直到程序停止）
        await browser.monitor_new_messages(message_handler)
        
    except KeyboardInterrupt:
        logger.info("🛑 用户中断，准备关闭...")
    except Exception as e:
        logger.error(f"❌ 程序异常: {e}")
    finally:
        logger.info("🔄 正在关闭浏览器...")
        await browser.close()
        logger.info("✅ 程序已退出")


if __name__ == "__main__":
    # 配置日志
    logger.add("goofish_test.log", rotation="1 MB", level="DEBUG")
    
    # 运行主程序
    asyncio.run(main())