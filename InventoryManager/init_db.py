#!/usr/bin/env python3
"""
数据库初始化脚本
"""

import os
from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental
from sqlalchemy import text
from datetime import datetime, date, timedelta

def init_database():
    """初始化数据库"""
    # 设置环境变量
    #os.environ.setdefault('DATABASE_URL', 'mysql+pymysql://root:123456@localhost:3306/testdb')
    
    # 创建应用实例
    app = create_app()
    
    with app.app_context():
        try:
            # 清空数据库（先关闭外键检查，避免删除顺序问题）
            try:
                db.session.execute(text('SET FOREIGN_KEY_CHECKS = 0;'))
            except Exception:
                # 非 MySQL 或权限不足时忽略
                pass

            db.drop_all()
            db.session.commit()
            print("已删除所有表")

            try:
                db.session.execute(text('SET FOREIGN_KEY_CHECKS = 1;'))
            except Exception:
                pass

            # 创建所有表
            db.create_all()
            print("数据库表创建成功")
            
            # 创建示例设备
            sample_devices = []
            for i in range(1, 27):
                device_name = f"20{i:02d}" 
                sample_devices.append({
                    'name': device_name,
                    'serial_number': f'DEV{i:03d}',
                    'location': '深圳仓库',
                    'status': 'idle'
                })
            
            for device_data in sample_devices:
                device = Device(**device_data)
                db.session.add(device)
            
            # 提交设备数据
            db.session.commit()
            print("示例设备创建成功")
            
            # 创建示例租赁记录（含新字段示例）
            sample_rentals = [
                {
                    'device_id': 1,  # 第一个设备的ID
                    'start_date': date.today() + timedelta(days=1),
                    'end_date': date.today() + timedelta(days=3),
                    'customer_name': '张三',
                    'customer_phone': '13800138000',
                    'status': 'active',
                    'destination': '广东省 广州市 天河区',
                    'ship_out_time': datetime.utcnow(),
                    'ship_out_tracking_no': 'SF123456789CN'
                },
                {
                    'device_id': 2,  # 第二个设备的ID
                    'start_date': date.today() + timedelta(days=5),
                    'end_date': date.today() + timedelta(days=7),
                    'customer_name': '李四',
                    'customer_phone': '13900139000',
                    'status': 'active',
                    'destination': '广东省 深圳市 南山区',
                    'ship_out_time': datetime.utcnow(),
                    'ship_out_tracking_no': 'YT987654321CN'
                }
            ]
            
            for rental_data in sample_rentals:
                rental = Rental(**rental_data)
                db.session.add(rental)
            
            # 提交租赁数据
            db.session.commit()
            print("示例租赁记录创建成功")
            
            print("数据库初始化完成！")
            
        except Exception as e:
            print(f"数据库初始化失败: {e}")
            db.session.rollback()

if __name__ == '__main__':
    init_database()
