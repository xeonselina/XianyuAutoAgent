"""
APScheduler 定时任务调度器
"""

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import logging
import atexit

logger = logging.getLogger(__name__)

# 全局调度器实例
scheduler = None


def init_scheduler(app):
    """
    初始化并启动定时调度器

    Args:
        app: Flask应用实例
    """
    global scheduler

    if scheduler is not None:
        logger.warning('调度器已经初始化')
        return

    # 创建后台调度器
    scheduler = BackgroundScheduler(daemon=True)

    # 添加定时发货任务 - 每5分钟执行一次
    try:
        from app.services.shipping.scheduler_shipping_task import process_scheduled_shipments

        scheduler.add_job(
            func=process_scheduled_shipments,
            trigger=IntervalTrigger(minutes=5),
            id='process_scheduled_shipments',
            name='处理预约发货任务',
            replace_existing=True,
            max_instances=1,  # 同时只允许一个实例运行
            misfire_grace_time=300  # 5分钟宽限时间
        )

        logger.info('已添加定时发货任务: 每5分钟执行一次')

    except Exception as e:
        logger.error(f'添加定时发货任务失败: {e}')

    # 启动调度器
    try:
        scheduler.start()
        logger.info('定时调度器已启动')

        # 注册关闭时停止调度器
        atexit.register(lambda: shutdown_scheduler())

    except Exception as e:
        logger.error(f'启动定时调度器失败: {e}')


def shutdown_scheduler():
    """关闭调度器"""
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info('定时调度器已关闭')


def get_scheduler():
    """获取调度器实例"""
    return scheduler
