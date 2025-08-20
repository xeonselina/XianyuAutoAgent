"""
库存管理服务主应用
"""

import os
import threading
import time
import atexit
import signal
from flask import Flask
from app import create_app, db
from app.models import Device, Rental, AuditLog
from app.services.device_status_service import DeviceStatusService
from datetime import datetime, date, timedelta
import uuid

# 创建应用实例
app = create_app()

# 设置环境变量
os.environ.setdefault('FLASK_ENV', 'development')


# ===================== 内置调度器（随应用启动/停止） =====================
_scheduler_thread = None
_scheduler_stop_event = threading.Event()


def _scheduler_loop(app_instance: "Flask", interval_seconds: int) -> None:
    """后台循环：按固定间隔执行设备状态更新。"""
    try:
        app_instance.logger.info(f"内置调度器启动，间隔 {interval_seconds}s")
        while not _scheduler_stop_event.is_set():
            started_at = time.time()
            try:
                with app_instance.app_context():
                    DeviceStatusService.update_device_statuses()
            except Exception as exc:  # 不中断主循环
                app_instance.logger.error(f"内置调度器执行失败: {exc}")
            # 精确等待剩余时间，避免漂移
            elapsed = time.time() - started_at
            wait_seconds = max(0.0, interval_seconds - elapsed)
            _scheduler_stop_event.wait(wait_seconds)
    finally:
        try:
            app_instance.logger.info("内置调度器已停止")
        except Exception:
            pass


def start_embedded_scheduler() -> None:
    """按需启动内置调度器，避免热重载重复启动。"""
    global _scheduler_thread
    if os.getenv('SCHEDULER_ENABLED', 'true').lower() not in ('1', 'true', 'yes', 'on'):
        return
    # 避免 Flask debug 热重载导致的两次启动
    if os.getenv('WERKZEUG_RUN_MAIN') not in ('true', 'True', '1', 'yes') and app.debug:
        return
    if _scheduler_thread and _scheduler_thread.is_alive():
        return
    _scheduler_stop_event.clear()
    interval = int(os.getenv('SCHEDULER_INTERVAL_SECONDS', '60'))
    _scheduler_thread = threading.Thread(
        target=_scheduler_loop, args=(app, interval), daemon=True
    )
    _scheduler_thread.start()


def stop_embedded_scheduler(*_args) -> None:
    """停止内置调度器（应用退出时调用）。"""
    if not _scheduler_thread:
        return
    _scheduler_stop_event.set()
    # 最多等待2秒结束
    try:
        _scheduler_thread.join(timeout=2.0)
    except Exception:
        pass


# 应用退出时清理
atexit.register(stop_embedded_scheduler)
try:
    signal.signal(signal.SIGTERM, stop_embedded_scheduler)
    signal.signal(signal.SIGINT, stop_embedded_scheduler)
except Exception:
    # 某些平台（如 Windows）可能不支持全部信号
    pass


@app.shell_context_processor
def make_shell_context():
    """为Flask shell提供上下文"""
    return {
        'db': db,
        'Device': Device,
        'Rental': Rental,
        'AuditLog': AuditLog
    }


## init_db 逻辑已移至独立脚本 init_db.py，避免与运行主进程混合


@app.cli.command()
def reset_db():
    """重置数据库"""
    try:
        confirm = input("确定要删除所有数据吗？(yes/no): ")
        if confirm.lower() != 'yes':
            print("操作已取消")
            return
        
        # 删除所有表
        db.drop_all()
        print("所有表已删除")
        
        # 重新创建表
        db.create_all()
        print("数据库表重新创建成功")
        
    except Exception as e:
        print(f"重置数据库失败: {e}")


## seed 数据同样在 init_db.py 中统一处理


@app.cli.command()
def list_devices():
    """列出所有设备"""
    try:
        devices = Device.query.all()
        if not devices:
            print("没有找到设备")
            return
        
        print(f"找到 {len(devices)} 个设备:")
        print("-" * 80)
        for device in devices:
            print(f"ID: {device.id}")
            print(f"名称: {device.name}")
            print(f"序列号: {device.serial_number}")
            print(f"状态: {device.status}")
            print(f"位置: {device.location}")
            print(f"创建时间: {device.created_at}")
            print("-" * 80)
            
    except Exception as e:
        print(f"列出设备失败: {e}")


@app.cli.command()
def list_rentals():
    """列出所有租赁记录"""
    try:
        rentals = Rental.query.all()
        if not rentals:
            print("没有找到租赁记录")
            return
        
        print(f"找到 {len(rentals)} 条租赁记录:")
        print("-" * 80)
        for rental in rentals:
            print(f"ID: {rental.id}")
            print(f"设备ID: {rental.device_id}")
            print(f"客户: {rental.customer_name}")
            print(f"电话: {rental.customer_phone}")
            print(f"开始日期: {rental.start_date}")
            print(f"结束日期: {rental.end_date}")
            print(f"状态: {rental.status}")
            print(f"创建时间: {rental.created_at}")
            print("-" * 80)
            
    except Exception as e:
        print(f"列出租赁记录失败: {e}")


@app.cli.command()
def check_device_status():
    """检查设备状态"""
    try:
        devices = Device.query.all()
        if not devices:
            print("没有找到设备")
            return
        
        print("设备状态统计:")
        print("-" * 40)
        
        status_counts = {}
        for device in devices:
            status = device.status
            status_counts[status] = status_counts.get(status, 0) + 1
        
        for status, count in status_counts.items():
            print(f"{status}: {count}")
        
        print("-" * 40)
        print(f"总计: {len(devices)}")
        
    except Exception as e:
        print(f"检查设备状态失败: {e}")


if __name__ == '__main__':
    port = int(os.environ.get('APP_PORT', 5001))  # 使用环境变量或默认端口5001
    # 启动内置调度器
    #start_embedded_scheduler()
    app.run(debug=True, host='0.0.0.0', port=port)
