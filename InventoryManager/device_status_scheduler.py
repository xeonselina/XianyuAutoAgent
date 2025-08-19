#!/usr/bin/env python3
"""
设备状态自动更新定时任务
按分钟执行，自动更新设备状态
"""

import time
import schedule
import logging
from datetime import datetime
import sys
import os

# 添加项目路径到Python路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 加载 .env 文件
from dotenv import load_dotenv
load_dotenv()

# 设置默认环境变量（如果 .env 中没有设置）
os.environ.setdefault('DATABASE_URL', 'mysql+pymysql://root:123456@localhost:3306/testdb')
os.environ.setdefault('APP_PORT', '5001')

from app import create_app, db
from app.services.device_status_service import DeviceStatusService

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('device_status_scheduler.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def update_device_statuses():
    """更新设备状态的任务"""
    try:
        logger.info("开始执行设备状态更新任务")
        
        # 创建Flask应用上下文
        app = create_app()
        with app.app_context():
            # 调用状态更新服务
            DeviceStatusService.update_device_statuses()
            
        logger.info("设备状态更新任务执行完成")
        
    except Exception as e:
        logger.error(f"设备状态更新任务执行失败: {e}")
        # 添加更详细的错误信息
        if "Access denied" in str(e):
            logger.error("数据库连接失败，请检查数据库配置和权限")
        elif "Connection refused" in str(e):
            logger.error("数据库服务未启动，请检查MySQL是否运行")
        else:
            logger.error(f"未知错误: {type(e).__name__}: {e}")


def test_database_connection():
    """测试数据库连接"""
    try:
        logger.info("测试数据库连接...")
        app = create_app()
        with app.app_context():
            # 尝试执行一个简单的查询
            from app.models.device import Device
            device_count = Device.query.count()
            logger.info(f"数据库连接成功，当前设备数量: {device_count}")
            return True
    except Exception as e:
        logger.error(f"数据库连接测试失败: {e}")
        return False

def main():
    """主函数"""
    logger.info("设备状态自动更新定时任务启动")
    
    # 启动时测试数据库连接
    if not test_database_connection():
        logger.error("数据库连接失败，定时任务无法启动")
        return
    
    # 设置定时任务：每分钟执行一次
    schedule.every().minute.do(update_device_statuses)
    
    # 启动时立即执行一次状态更新
    logger.info("启动时立即执行一次状态更新")
    update_device_statuses()
    
    try:
        while True:
            # 运行定时任务
            schedule.run_pending()
            
            # 等待1秒
            time.sleep(1)
            
    except KeyboardInterrupt:
        logger.info("收到中断信号，正在停止定时任务...")
    except Exception as e:
        logger.error(f"定时任务运行异常: {e}")
    finally:
        logger.info("设备状态自动更新定时任务已停止")


if __name__ == '__main__':
    main()
