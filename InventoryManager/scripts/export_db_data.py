#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
导出数据库数据为SQL INSERT语句
"""

import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental


def escape_string(value):
    """转义SQL字符串中的特殊字符"""
    if value is None:
        return 'NULL'
    if isinstance(value, bool):
        return 'TRUE' if value else 'FALSE'
    if isinstance(value, (int, float)):
        return str(value)
    # 字符串需要转义单引号并加上引号
    return "'" + str(value).replace("'", "''").replace("\\", "\\\\") + "'"


def generate_device_inserts():
    """生成设备表的INSERT语句"""
    devices = Device.query.order_by(Device.id).all()

    inserts = []
    for device in devices:
        values = [
            str(device.id),
            escape_string(device.name),
            escape_string(device.serial_number),
            escape_string(device.model),
            escape_string(device.model_id),
            'TRUE' if device.is_accessory else 'FALSE',
            escape_string(device.status),
            escape_string(device.created_at.strftime('%Y-%m-%d %H:%M:%S') if device.created_at else None),
            escape_string(device.updated_at.strftime('%Y-%m-%d %H:%M:%S') if device.updated_at else None),
        ]

        insert_sql = f"INSERT INTO devices (id, name, serial_number, model, model_id, is_accessory, status, created_at, updated_at) VALUES ({', '.join(values)});"
        inserts.append(insert_sql)

    return inserts


def generate_rental_inserts():
    """生成租赁表的INSERT语句"""
    rentals = Rental.query.order_by(Rental.id).all()

    inserts = []
    for rental in rentals:
        values = [
            str(rental.id),
            str(rental.device_id),
            escape_string(rental.start_date.strftime('%Y-%m-%d') if rental.start_date else None),
            escape_string(rental.end_date.strftime('%Y-%m-%d') if rental.end_date else None),
            escape_string(rental.ship_out_time.strftime('%Y-%m-%d %H:%M:%S') if rental.ship_out_time else None),
            escape_string(rental.ship_in_time.strftime('%Y-%m-%d %H:%M:%S') if rental.ship_in_time else None),
            escape_string(rental.customer_name),
            escape_string(rental.customer_phone),
            escape_string(rental.destination),
            escape_string(rental.ship_out_tracking_no),
            escape_string(rental.ship_in_tracking_no),
            escape_string(rental.status),
            str(rental.parent_rental_id) if rental.parent_rental_id else 'NULL',
            escape_string(rental.created_at.strftime('%Y-%m-%d %H:%M:%S') if rental.created_at else None),
            escape_string(rental.updated_at.strftime('%Y-%m-%d %H:%M:%S') if rental.updated_at else None),
        ]

        insert_sql = f"INSERT INTO rentals (id, device_id, start_date, end_date, ship_out_time, ship_in_time, customer_name, customer_phone, destination, ship_out_tracking_no, ship_in_tracking_no, status, parent_rental_id, created_at, updated_at) VALUES ({', '.join(values)});"
        inserts.append(insert_sql)

    return inserts


def main():
    """主函数"""
    app = create_app()

    with app.app_context():
        print("正在导出设备数据...")
        device_inserts = generate_device_inserts()

        print("正在导出租赁数据...")
        rental_inserts = generate_rental_inserts()

        # 写入文件
        output_file = os.path.join(os.path.dirname(__file__), 'exported_data.sql')
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("-- 设备数据\n")
            for insert in device_inserts:
                f.write(insert + '\n')

            f.write("\n-- 租赁数据\n")
            for insert in rental_inserts:
                f.write(insert + '\n')

        print(f"\n数据已导出到: {output_file}")
        print(f"设备数量: {len(device_inserts)}")
        print(f"租赁记录数量: {len(rental_inserts)}")

        # 同时输出到控制台
        print("\n" + "="*80)
        print("设备数据:")
        print("="*80)
        for insert in device_inserts[:5]:  # 只显示前5条
            print(insert)
        if len(device_inserts) > 5:
            print(f"... 还有 {len(device_inserts) - 5} 条设备数据")

        print("\n" + "="*80)
        print("租赁数据:")
        print("="*80)
        for insert in rental_inserts[:5]:  # 只显示前5条
            print(insert)
        if len(rental_inserts) > 5:
            print(f"... 还有 {len(rental_inserts) - 5} 条租赁数据")


if __name__ == '__main__':
    main()
