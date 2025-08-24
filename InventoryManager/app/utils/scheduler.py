"""
应用定时调度器
"""

import schedule
import time
import threading
import logging
from datetime import datetime
from flask import current_app

from app.utils.scheduler_tasks import update_rental_tracking_status, update_device_statuses

logger = logging.getLogger(__name__)


class AppScheduler:
    """应用定时调度器"""
    
    def __init__(self, app=None):
        """初始化调度器"""
        self.is_running = False
        self.scheduler_thread = None
        self.app = app
        self.jobs_setup = False
        if app is not None:
            self.setup_jobs()
    
    def setup_jobs(self):
        """设置定时任务"""
        try:
            if self.jobs_setup:
                return
            
            # 每小时执行一次快递状态更新
            schedule.every().hour.do(self._safe_run, update_rental_tracking_status, "更新快递状态")
            
            # 每分钟执行一次设备状态更新
            schedule.every().minute.do(self._safe_run, update_device_statuses, "更新设备状态")
            
            # 也可以设置其他定时任务
            # schedule.every().day.at("02:00").do(self._safe_run, some_daily_task, "每日任务")
            # schedule.every().monday.at("09:00").do(self._safe_run, weekly_task, "每周任务")
            
            self.jobs_setup = True
            logger.info("定时任务设置完成")
            
        except Exception as e:
            logger.error(f"设置定时任务失败: {e}")
    
    def _safe_run(self, func, task_name):
        """安全执行任务，捕获异常"""
        try:
            logger.info(f"开始执行定时任务: {task_name}")
            start_time = datetime.now()
            
            # 在Flask应用上下文中执行任务
            if self.app:
                with self.app.app_context():
                    func()
            else:
                # 尝试使用current_app（如果可用）
                try:
                    with current_app.app_context():
                        func()
                except RuntimeError:
                    # 如果没有应用上下文，直接执行（可能会失败）
                    logger.warning(f"任务 '{task_name}' 在没有Flask应用上下文的情况下执行")
                    func()
            
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            logger.info(f"定时任务 '{task_name}' 执行完成，耗时: {duration:.2f} 秒")
            
        except Exception as e:
            logger.error(f"定时任务 '{task_name}' 执行失败: {e}", exc_info=True)
    
    def start(self):
        """启动定时调度器"""
        if self.is_running:
            logger.warning("定时调度器已在运行中")
            return
        
        self.is_running = True
        
        def run_scheduler():
            logger.info("定时调度器启动")
            while self.is_running:
                try:
                    schedule.run_pending()
                    time.sleep(60)  # 每分钟检查一次
                except Exception as e:
                    logger.error(f"调度器运行异常: {e}")
                    time.sleep(60)
            logger.info("定时调度器已停止")
        
        self.scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        self.scheduler_thread.start()
        logger.info("定时调度器线程已启动")
    
    def stop(self):
        """停止定时调度器"""
        if not self.is_running:
            return
        
        self.is_running = False
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=5)
        logger.info("定时调度器已停止")
    
    def get_scheduled_jobs(self):
        """获取已计划的任务列表"""
        jobs = []
        for job in schedule.jobs:
            jobs.append({
                'job_id': id(job),
                'next_run': job.next_run.isoformat() if job.next_run else None,
                'interval': str(job.interval),
                'unit': job.unit,
                'job_func': job.job_func.__name__ if hasattr(job.job_func, '__name__') else str(job.job_func)
            })
        return jobs
    
    def run_job_immediately(self, job_name: str):
        """立即执行指定的任务"""
        if job_name == "update_tracking":
            self._safe_run(update_rental_tracking_status, "立即更新快递状态")
            return True
        elif job_name == "update_device_status":
            self._safe_run(update_device_statuses, "立即更新设备状态")
            return True
        else:
            logger.warning(f"未知的任务名称: {job_name}")
            return False


# 全局调度器实例
app_scheduler = None


def init_scheduler(app=None):
    """初始化并启动调度器"""
    global app_scheduler
    
    if app_scheduler is None:
        app_scheduler = AppScheduler(app)
    else:
        # 更新应用引用
        app_scheduler.app = app
        if not hasattr(app_scheduler, 'jobs_setup') or not app_scheduler.jobs_setup:
            app_scheduler.setup_jobs()
    
    app_scheduler.start()


def stop_scheduler():
    """停止调度器"""
    if app_scheduler:
        app_scheduler.stop()


def get_scheduler_status():
    """获取调度器状态"""
    if app_scheduler:
        return {
            'is_running': app_scheduler.is_running,
            'scheduled_jobs': app_scheduler.get_scheduled_jobs()
        }
    else:
        return {
            'is_running': False,
            'scheduled_jobs': []
        }


def run_task_now(task_name: str):
    """立即执行任务"""
    if app_scheduler:
        return app_scheduler.run_job_immediately(task_name)
    else:
        logger.warning("调度器未初始化，无法执行任务")
        return False