"""
库存管理服务主应用
"""

import os
from app import create_app, db
from app.models import Device, Rental, AuditLog
from datetime import datetime, date, timedelta
import uuid

# 创建应用实例
app = create_app()

# 设置环境变量
os.environ.setdefault('FLASK_ENV', 'development')


@app.shell_context_processor
def make_shell_context():
    """为Flask shell提供上下文"""
    return {
        'db': db,
        'Device': Device,
        'Rental': Rental,
        'AuditLog': AuditLog
    }


@app.cli.command()
def init_db():
    """初始化数据库"""
    try:
        # 创建所有表
        db.create_all()
        print("数据库表创建成功")
        
        # 创建示例设备
        sample_devices = [
            {
                'name': 'iPhone 15 Pro',
                'serial_number': 'IP15P001',
                'location': '深圳仓库',
                'status': 'available'
            },
            {
                'name': 'MacBook Pro 14',
                'serial_number': 'MBP14001',
                'location': '深圳仓库',
                'status': 'available'
            },
            {
                'name': 'Sony A7M4',
                'serial_number': 'SA7M4001',
                'location': '深圳仓库',
                'status': 'available'
            },
            {
                'name': 'DJI Mini 3 Pro',
                'serial_number': 'DJM3P001',
                'location': '深圳仓库',
                'status': 'available'
            },
            {
                'name': 'GoPro Hero 11',
                'serial_number': 'GPH11001',
                'location': '深圳仓库',
                'status': 'available'
            }
        ]
        
        for device_data in sample_devices:
            device = Device(**device_data)
            db.session.add(device)
        
        # 创建示例租赁记录
        sample_rentals = [
            {
                'device_id': '1',  # 假设第一个设备的ID
                'start_date': date.today() + timedelta(days=1),
                'end_date': date.today() + timedelta(days=3),
                'customer_name': '张三',
                'customer_phone': '13800138000',
                'status': 'active'
            },
            {
                'device_id': '2',  # 假设第二个设备的ID
                'start_date': date.today() + timedelta(days=5),
                'end_date': date.today() + timedelta(days=7),
                'customer_name': '李四',
                'customer_phone': '13900139000',
                'status': 'active'
            }
        ]
        
        for rental_data in sample_rentals:
            rental = Rental(**rental_data)
            db.session.add(rental)
        
        db.session.commit()
        print("示例数据创建成功")
        
    except Exception as e:
        db.session.rollback()
        print(f"初始化数据库失败: {e}")


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


@app.cli.command()
def seed_data():
    """填充示例数据"""
    try:
        # 检查是否已有数据
        if Device.query.count() > 0:
            print("数据库中已有数据，跳过填充")
            return
        
        # 创建示例设备
        sample_devices = [
            {
                'name': 'iPhone 15 Pro',
                'serial_number': 'IP15P001',
                'location': '深圳仓库',
                'status': 'available'
            },
            {
                'name': 'MacBook Pro 14',
                'serial_number': 'MBP14001',
                'location': '深圳仓库',
                'status': 'available'
            },
            {
                'name': 'Sony A7M4',
                'serial_number': 'SA7M4001',
                'location': '深圳仓库',
                'status': 'available'
            },
            {
                'name': 'DJI Mini 3 Pro',
                'serial_number': 'DJM3P001',
                'location': '深圳仓库',
                'status': 'available'
            },
            {
                'name': 'GoPro Hero 11',
                'serial_number': 'GPH11001',
                'location': '深圳仓库',
                'status': 'available'
            }
        ]
        
        for device_data in sample_devices:
            device = Device(**device_data)
            db.session.add(device)
        
        db.session.commit()
        print("示例数据填充成功")
        
    except Exception as e:
        db.session.rollback()
        print(f"填充示例数据失败: {e}")


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
    app.run(debug=True, host='0.0.0.0', port=5000)
