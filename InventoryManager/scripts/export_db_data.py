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
from app.models.device_model import DeviceModel
from app.models.rental_statistics import RentalStatistics
from app.models.audit_log import AuditLog

try:
    from faker import Faker
    fake = Faker('zh_CN')
except ImportError:
    print("错误: 需要安装 faker 库")
    print("请运行: pip install faker")
    sys.exit(1)


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


def fake_customer_name():
    """生成假的客户姓名"""
    return fake.name()


def fake_phone():
    """生成假的手机号"""
    return fake.phone_number()


def fake_address():
    """生成假的地址"""
    name = fake.name()
    phone = fake.phone_number()
    address = f"{fake.province()}{fake.city()}{fake.district()}{fake.street_address()}"
    return f"{name} {phone}\n{address}"


def generate_device_model_inserts():
    """生成设备型号表的INSERT语句"""
    models = DeviceModel.query.order_by(DeviceModel.id).all()

    inserts = []
    for model in models:
        values = [
            str(model.id),
            escape_string(model.name),
            escape_string(model.display_name),
            escape_string(model.description),
            'TRUE' if model.is_active else 'FALSE',
            'TRUE' if model.is_accessory else 'FALSE',
            str(model.parent_model_id) if model.parent_model_id else 'NULL',
            escape_string(model.default_accessories),
            escape_string(str(model.device_value) if model.device_value else None),
            escape_string(model.created_at.strftime('%Y-%m-%d %H:%M:%S') if model.created_at else None),
            escape_string(model.updated_at.strftime('%Y-%m-%d %H:%M:%S') if model.updated_at else None),
        ]

        insert_sql = f"INSERT INTO device_models (id, name, display_name, description, is_active, is_accessory, parent_model_id, default_accessories, device_value, created_at, updated_at) VALUES ({', '.join(values)});"
        inserts.append(insert_sql)

    return inserts


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
            str(device.model_id) if device.model_id else 'NULL',
            'TRUE' if device.is_accessory else 'FALSE',
            escape_string(device.status),
            escape_string(device.created_at.strftime('%Y-%m-%d %H:%M:%S') if device.created_at else None),
            escape_string(device.updated_at.strftime('%Y-%m-%d %H:%M:%S') if device.updated_at else None),
        ]

        insert_sql = f"INSERT INTO devices (id, name, serial_number, model, model_id, is_accessory, status, created_at, updated_at) VALUES ({', '.join(values)});"
        inserts.append(insert_sql)

    return inserts


def generate_rental_inserts():
    """生成租赁表的INSERT语句（敏感数据已脱敏）"""
    rentals = Rental.query.order_by(Rental.id).all()

    inserts = []
    for rental in rentals:
        # 使用假数据替换敏感信息
        values = [
            str(rental.id),
            str(rental.device_id),
            escape_string(rental.start_date.strftime('%Y-%m-%d') if rental.start_date else None),
            escape_string(rental.end_date.strftime('%Y-%m-%d') if rental.end_date else None),
            escape_string(rental.ship_out_time.strftime('%Y-%m-%d %H:%M:%S') if rental.ship_out_time else None),
            escape_string(rental.ship_in_time.strftime('%Y-%m-%d %H:%M:%S') if rental.ship_in_time else None),
            escape_string(fake_customer_name()),  # 替换真实姓名
            escape_string(fake_phone()),          # 替换真实手机号
            escape_string(fake_address()),        # 替换真实地址
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


def generate_rental_statistics_inserts():
    """生成租赁统计表的INSERT语句"""
    statistics = RentalStatistics.query.order_by(RentalStatistics.id).all()

    inserts = []
    for stat in statistics:
        values = [
            str(stat.id),
            escape_string(stat.stat_date.strftime('%Y-%m-%d') if stat.stat_date else None),
            escape_string(stat.period_start.strftime('%Y-%m-%d') if stat.period_start else None),
            escape_string(stat.period_end.strftime('%Y-%m-%d') if stat.period_end else None),
            str(stat.total_rentals) if stat.total_rentals else '0',
            escape_string(str(stat.total_rent) if stat.total_rent else None),
            escape_string(str(stat.total_value) if stat.total_value else None),
            escape_string(stat.created_at.strftime('%Y-%m-%d %H:%M:%S') if stat.created_at else None),
            escape_string(stat.updated_at.strftime('%Y-%m-%d %H:%M:%S') if stat.updated_at else None),
        ]

        insert_sql = f"INSERT INTO rental_statistics (id, stat_date, period_start, period_end, total_rentals, total_rent, total_value, created_at, updated_at) VALUES ({', '.join(values)});"
        inserts.append(insert_sql)

    return inserts


def generate_audit_log_inserts():
    """生成审计日志表的INSERT语句（可选）"""
    # 审计日志可能很多，这里只导出最近的1000条
    logs = AuditLog.query.order_by(AuditLog.id.desc()).limit(1000).all()

    inserts = []
    for log in logs:
        values = [
            str(log.id),
            escape_string(log.action),
            escape_string(log.table_name),
            str(log.record_id) if log.record_id else 'NULL',
            escape_string(log.old_value),
            escape_string(log.new_value),
            escape_string(log.user),
            str(log.device_id) if log.device_id else 'NULL',
            str(log.rental_id) if log.rental_id else 'NULL',
            escape_string(log.created_at.strftime('%Y-%m-%d %H:%M:%S') if log.created_at else None),
        ]

        insert_sql = f"INSERT INTO audit_logs (id, action, table_name, record_id, old_value, new_value, user, device_id, rental_id, created_at) VALUES ({', '.join(values)});"
        inserts.append(insert_sql)

    return inserts


def main():
    """主函数"""
    app = create_app()

    with app.app_context():
        print("正在导出数据库数据...\n")

        # 按照外键依赖顺序导出数据
        print("1. 导出设备型号数据...")
        device_model_inserts = generate_device_model_inserts()

        print("2. 导出设备数据...")
        device_inserts = generate_device_inserts()

        print("3. 导出租赁数据...")
        rental_inserts = generate_rental_inserts()

        print("4. 导出租赁统计数据...")
        rental_statistics_inserts = generate_rental_statistics_inserts()

        print("5. 导出审计日志数据（最近1000条）...")
        audit_log_inserts = generate_audit_log_inserts()

        # 写入文件
        output_file = os.path.join(os.path.dirname(__file__), 'exported_data.sql')
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write("-- ============================================\n")
            f.write("-- 数据库数据导出（敏感数据已脱敏）\n")
            f.write(f"-- 导出时间: {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write("-- 注意：客户姓名、电话、地址均为假数据\n")
            f.write("-- ============================================\n\n")

            f.write("-- 1. 设备型号数据（device_models）\n")
            f.write("-- 注意：需要先导入主设备型号，再导入附件型号\n")
            for insert in device_model_inserts:
                f.write(insert + '\n')

            f.write("\n-- 2. 设备数据（devices）\n")
            for insert in device_inserts:
                f.write(insert + '\n')

            f.write("\n-- 3. 租赁数据（rentals）\n")
            f.write("-- 注意：需要先导入主租赁记录，再导入附件租赁记录\n")
            for insert in rental_inserts:
                f.write(insert + '\n')

            f.write("\n-- 4. 租赁统计数据（rental_statistics）\n")
            for insert in rental_statistics_inserts:
                f.write(insert + '\n')

            f.write("\n-- 5. 审计日志数据（audit_logs）- 最近1000条\n")
            for insert in audit_log_inserts:
                f.write(insert + '\n')

        print(f"\n{'='*80}")
        print("数据导出完成！")
        print(f"{'='*80}")
        print(f"导出文件: {output_file}")
        print(f"\n统计信息:")
        print(f"  - 设备型号: {len(device_model_inserts)} 条")
        print(f"  - 设备: {len(device_inserts)} 条")
        print(f"  - 租赁记录: {len(rental_inserts)} 条")
        print(f"  - 租赁统计: {len(rental_statistics_inserts)} 条")
        print(f"  - 审计日志: {len(audit_log_inserts)} 条")

        # 显示部分数据预览
        print(f"\n{'='*80}")
        print("数据预览（每类前3条）:")
        print(f"{'='*80}")

        print("\n[设备型号]")
        for insert in device_model_inserts[:3]:
            print(insert)
        if len(device_model_inserts) > 3:
            print(f"... 还有 {len(device_model_inserts) - 3} 条")

        print("\n[设备]")
        for insert in device_inserts[:3]:
            print(insert)
        if len(device_inserts) > 3:
            print(f"... 还有 {len(device_inserts) - 3} 条")

        print("\n[租赁记录]")
        for insert in rental_inserts[:3]:
            print(insert)
        if len(rental_inserts) > 3:
            print(f"... 还有 {len(rental_inserts) - 3} 条")


if __name__ == '__main__':
    main()
