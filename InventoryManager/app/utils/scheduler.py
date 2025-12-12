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
    import os

    global scheduler

    if scheduler is not None:
        logger.warning('调度器已经初始化')
        return

    # 在多worker环境下，只在第一个worker中运行定时任务
    # 通过环境变量标记
    worker_id = os.environ.get('GUNICORN_WORKER_ID')
    if worker_id:
        logger.info(f'当前Worker ID: {worker_id}')
        # 只在worker 0或未设置worker_id时运行调度器
        # 由于gunicorn不自动设置这个变量，我们用进程ID来判断
        pass

    # 检查是否已经有其他进程启动了调度器
    # 使用文件锁机制确保只有一个调度器运行
    import fcntl
    lock_file_path = '/tmp/inventory_scheduler.lock'

    try:
        lock_file = open(lock_file_path, 'w')
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

        logger.info(f'获取调度器锁成功，进程 {os.getpid()} 将启动调度器')

        # 创建后台调度器
        scheduler = BackgroundScheduler(daemon=True)

        # 添加定时发货任务 - 每5分钟执行一次
        try:
            from app.services.shipping.scheduler_shipping_task import process_scheduled_shipments

            # 包装任务函数，确保在应用上下文中运行
            def run_with_app_context():
                with app.app_context():
                    logger.info(f'[Worker {os.getpid()}] 开始执行定时发货任务')
                    try:
                        return process_scheduled_shipments()
                    except Exception as e:
                        logger.error(f'[Worker {os.getpid()}] 定时发货任务执行失败: {e}', exc_info=True)
                        return {'total': 0, 'success': 0, 'failed': 0, 'error': str(e)}

            scheduler.add_job(
                func=run_with_app_context,
                trigger=IntervalTrigger(minutes=1),
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

    except BlockingIOError:
        # 无法获取锁，说明其他进程已经启动了调度器
        logger.info(f'进程 {os.getpid()} 无法获取调度器锁，跳过调度器初始化（其他worker已启动）')
        return
    except Exception as e:
        logger.error(f'初始化调度器时发生错误: {e}')


def shutdown_scheduler():
    """关闭调度器"""
    global scheduler
    if scheduler:
        scheduler.shutdown(wait=False)
        logger.info('定时调度器已关闭')


def get_scheduler():
    """获取调度器实例"""
    return scheduler


def run_task_now(task_name):
    """
    立即运行指定的定时任务

    Args:
        task_name: 任务名称

    Returns:
        bool: 是否成功执行
    """
    global scheduler
    if not scheduler:
        logger.error('调度器未初始化')
        return False

    try:
        # 根据任务名称查找并立即执行任务
        job = scheduler.get_job(task_name)
        if job:
            job.modify(next_run_time=None)  # 立即执行
            logger.info(f'任务 {task_name} 已被触发执行')
            return True
        else:
            logger.warning(f'找不到任务: {task_name}')
            return False
    except Exception as e:
        logger.error(f'执行任务 {task_name} 失败: {e}')
        return False


def get_scheduler_status():
    """
    获取调度器状态

    Returns:
        dict: 调度器状态信息
    """
    global scheduler
    if not scheduler:
        return {
            'running': False,
            'jobs': []
        }

    try:
        jobs = []
        for job in scheduler.get_jobs():
            jobs.append({
                'id': job.id,
                'name': job.name,
                'next_run_time': job.next_run_time.isoformat() if job.next_run_time else None
            })

        return {
            'running': scheduler.running,
            'jobs': jobs
        }
    except Exception as e:
        logger.error(f'获取调度器状态失败: {e}')
        return {
            'running': False,
            'jobs': [],
            'error': str(e)
        }
