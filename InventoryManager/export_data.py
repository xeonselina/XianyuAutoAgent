#!/usr/bin/env python3
"""
数据库导出脚本 - 导出 device 和 rental 数据为 SQL 格式
"""

import os
from datetime import datetime

# 必须在导入app之前设置，现在从.env文件读取
# os.environ['DATABASE_URL'] = 'mysql+pymysql://root:123456@localhost:3306/testdb'

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental


def quote_value(value):
    """处理 SQL 值的引号"""
    if value is None:
        return 'NULL'
    elif isinstance(value, str):
        # 转义单引号
        escaped_value = value.replace("'", "''")
        return f"'{escaped_value}'"
    elif isinstance(value, datetime):
        return f"'{value.strftime('%Y-%m-%d %H:%M:%S')}'"
    elif isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    else:
        return str(value)


def export_devices():
    """导出设备数据为 SQL INSERT 语句"""
    devices = Device.query.all()
    
    if not devices:
        return []
    
    sql_statements = []
    
    for device in devices:
        values = [
            quote_value(device.id),
            quote_value(device.name),
            quote_value(device.serial_number),
            quote_value(device.model),
            quote_value(device.is_accessory),
            quote_value(device.status),
            quote_value(device.created_at),
            quote_value(device.updated_at)
        ]

        sql = f"INSERT INTO devices (id, name, serial_number, model, is_accessory, status, created_at, updated_at) VALUES ({', '.join(values)});"
        sql_statements.append(sql)
    
    return sql_statements


def export_rentals():
    """导出租赁数据为 SQL INSERT 语句"""
    rentals = Rental.query.all()
    
    if not rentals:
        return []
    
    sql_statements = []
    
    for rental in rentals:
        values = [
            quote_value(rental.id),
            quote_value(rental.device_id),
            quote_value(rental.start_date.strftime('%Y-%m-%d')),
            quote_value(rental.end_date.strftime('%Y-%m-%d')),
            quote_value(rental.ship_out_time),
            quote_value(rental.ship_in_time),
            quote_value(rental.customer_name),
            quote_value(rental.customer_phone),
            quote_value(rental.destination),
            quote_value(rental.ship_out_tracking_no),
            quote_value(rental.ship_in_tracking_no),
            quote_value(rental.status),
            quote_value(rental.parent_rental_id),
            quote_value(rental.created_at),
            quote_value(rental.updated_at)
        ]

        sql = f"INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES ({', '.join(values)});"
        sql_statements.append(sql)
    
    return sql_statements


def generate_data_sql():
    """生成包含所有数据的 SQL 文件内容"""
    
    app = create_app()
    
    with app.app_context():
        print("正在导出设备数据...")
        device_statements = export_devices()
        print(f"导出了 {len(device_statements)} 个设备记录")
        
        print("正在导出租赁数据...")
        rental_statements = export_rentals()
        print(f"导出了 {len(rental_statements)} 个租赁记录")
        
        # 生成 Python 代码格式的数据
        sql_content = []
        
        if device_statements:
            sql_content.append("            # 导入设备数据")
            for sql in device_statements:
                sql_content.append(f"            db.session.execute(text(\"{sql}\"))")
        
        if rental_statements:
            sql_content.append("\n            # 导入租赁数据")
            for sql in rental_statements:
                sql_content.append(f"            db.session.execute(text(\"{sql}\"))")
        
        sql_content.append("\n            # 提交所有导入的数据")
        sql_content.append("            db.session.commit()")
        sql_content.append("            print(\"数据导入成功\")")
        
        return '\n'.join(sql_content)


def save_exported_data():
    """保存导出的数据到文件"""
    try:
        exported_data = generate_data_sql()
        
        # 保存到文件
        with open('exported_data.sql.py', 'w', encoding='utf-8') as f:
            f.write("# 导出的数据库数据 - 用于插入到 init_db.py 中\n")
            f.write("# 将以下代码复制到 init_db.py 的适当位置\n\n")
            f.write(exported_data)
        
        print("数据导出完成！")
        print("导出的数据已保存到: exported_data.sql.py")
        print("请将文件内容复制到 init_db.py 的适当位置")
        
    except Exception as e:
        print(f"导出数据失败: {e}")


if __name__ == '__main__':
    save_exported_data()