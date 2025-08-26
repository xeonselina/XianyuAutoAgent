"""
库存管理服务主应用
"""

import os
from flask import Flask
from app import create_app, db
from app.models import Device, Rental, AuditLog
from datetime import datetime, date, timedelta
import uuid

# 创建应用实例
app = create_app()

# 设置环境变量
os.environ.setdefault('FLASK_ENV', 'development')


# ===================== 旧的内置调度器已迁移到新的调度器模块 =====================
# 设备状态更新和快递查询任务现在由 app/utils/scheduler.py 统一管理
# 在应用启动时会自动启动新的调度器


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
            # print(f"位置: {device.location}")  # location字段已移除
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
    port = int(os.environ.get('APP_PORT', 5002))  # 使用环境变量或默认端口5002
    # 新的调度器已在应用初始化时启动（见 app/__init__.py）
    app.run(debug=True, host='0.0.0.0', port=port)
