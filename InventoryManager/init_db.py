#!/usr/bin/env python3
"""
数据库初始化脚本
"""

import os

# 必须在导入app之前设置，因为init_db.py在宿主机运行
os.environ['DATABASE_URL'] = 'mysql+pymysql://root:123456@localhost:3306/testdb'

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental
from sqlalchemy import text
from datetime import datetime, date, timedelta

def init_database():
    """初始化数据库"""
    
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
            
            # 创建设备数据（来自Excel文件）
            sample_devices = [
                {'name': '2001', 'serial_number': '10AF4C15P8002JU', 'status': 'idle'},
                {'name': '2002', 'serial_number': '10AF4F2N88002K0', 'status': 'idle'},
                {'name': '2003', 'serial_number': '10AF5R2EJC003GQ', 'status': 'idle'},
                {'name': '2004', 'serial_number': '10AF6C23YF0040C', 'status': 'idle'},
                {'name': '2005', 'serial_number': '10AF4D034M002LD', 'status': 'idle'},
                {'name': '2006', 'serial_number': '10AF4U05QK002ZB', 'status': 'idle'},
                {'name': '2007', 'serial_number': '10AF5X2HDQ003M7', 'status': 'idle'},
                {'name': '2008', 'serial_number': '10AF7H1QM0004Y6', 'status': 'idle'},
                {'name': '2009', 'serial_number': '10AF7423K3004PL', 'status': 'idle'},
                {'name': '2010', 'serial_number': '10AF4U0FMT002ZB', 'status': 'idle'},
                {'name': '2011', 'serial_number': '10AF561KHA0035K', 'status': 'idle'},
                {'name': '2012', 'serial_number': '10AF3S0EQQ00206', 'status': 'idle'},
                {'name': '2013', 'serial_number': '10AF4U0D60002ZB', 'status': 'idle'},
                {'name': '2014', 'serial_number': '10AF6K10B30046N', 'status': 'idle'},
                {'name': '2015', 'serial_number': '10AF6MOPF00049M', 'status': 'idle'},
                {'name': '2016', 'serial_number': '10AF6D0Q7800439', 'status': 'idle'},
                {'name': '2017', 'serial_number': '10AF4F0A99002K0', 'status': 'idle'},
                {'name': '2018', 'serial_number': '10AF571CSR00375', 'status': 'idle'},
                {'name': '2019', 'serial_number': '10AF6S304P004E9', 'status': 'idle'},
                {'name': '2020', 'serial_number': '10AF4COULP002JU', 'status': 'idle'},
                {'name': '2021', 'serial_number': '10AF6MOPDK0049M', 'status': 'idle'},
                {'name': '2022', 'serial_number': '10AF4N0BXU002NC', 'status': 'idle'},
                {'name': '2023', 'serial_number': '10AF771R44004NB', 'status': 'idle'},
                {'name': '2024', 'serial_number': '10AF6S301B004E9', 'status': 'idle'},
                {'name': '2025', 'serial_number': '10AF5L1X57003DR', 'status': 'idle'},
                {'name': '2026', 'serial_number': '10AF460K5G002E9', 'status': 'idle'},
            ]
            
            for device_data in sample_devices:
                device = Device(**device_data)
                db.session.add(device)
            
            # 提交设备数据
            db.session.commit()
            print("示例设备创建成功")
            
            print("数据库初始化完成！")
            
        except Exception as e:
            print(f"数据库初始化失败: {e}")
            db.session.rollback()

if __name__ == '__main__':
    init_database()
