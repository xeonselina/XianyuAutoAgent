#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
租赁数据统计脚本

统计所有rental的价值数据:
1. 所有rental总共产生了多少价值
2. 所有rental每天平均产生多少价值

价值计算方法:
- 租赁天数 = end_date - start_date
- 租金 = 199 + (租赁天数 - 1) * 30
- 收入价值 = 租金 - 15
"""

import sys
import os
from datetime import date, timedelta

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app, db
from app.models.rental import Rental
from app.models.rental_statistics import RentalStatistics


def calculate_rental_value(rental):
    """
    计算单个rental的收入价值

    Args:
        rental: Rental对象

    Returns:
        dict: 包含租赁天数、租金、收入价值的字典
    """
    if not rental.start_date or not rental.end_date:
        return {
            'rental_days': 0,
            'rent': 0,
            'value': 0
        }

    # 计算租赁天数
    rental_days = (rental.end_date - rental.start_date).days

    # 计算租金: 199 + (租赁天数 - 1) * 30
    rent = 199 + (rental_days - 1) * 30

    # 计算收入价值: 租金 - 15
    value = rent - 15

    return {
        'rental_days': rental_days,
        'rent': rent,
        'value': value
    }


def get_rental_statistics():
    """
    获取所有rental的统计数据

    Returns:
        dict: 统计结果
    """
    # 查询所有主租赁记录(不包括附件租赁,避免重复计算)
    rentals = Rental.query.filter(Rental.parent_rental_id.is_(None)).all()

    total_value = 0
    total_days = 0
    rental_count = 0

    rental_details = []

    for rental in rentals:
        result = calculate_rental_value(rental)

        total_value += result['value']
        total_days += result['rental_days']
        rental_count += 1

        rental_details.append({
            'id': rental.id,
            'customer_name': rental.customer_name,
            'start_date': rental.start_date.isoformat(),
            'end_date': rental.end_date.isoformat(),
            'rental_days': result['rental_days'],
            'rent': result['rent'],
            'value': result['value'],
            'status': rental.status
        })

    # 计算每天平均产生的价值
    avg_value_per_day = total_value / total_days if total_days > 0 else 0

    return {
        'total_rentals': rental_count,
        'total_value': total_value,
        'total_days': total_days,
        'avg_value_per_day': avg_value_per_day,
        'details': rental_details
    }


def get_recent_30days_statistics():
    """
    获取最近30天的rental统计数据 (根据end_date)

    Returns:
        dict: 统计结果
    """
    # 计算30天前的日期
    today = date.today()
    thirty_days_ago = today - timedelta(days=30)

    # 查询end_date在最近30天内的主租赁记录
    rentals = Rental.query.filter(
        Rental.parent_rental_id.is_(None),
        Rental.end_date >= thirty_days_ago,
        Rental.end_date <= today
    ).all()

    total_value = 0
    total_rent = 0
    rental_count = 0

    rental_details = []

    for rental in rentals:
        result = calculate_rental_value(rental)

        total_value += result['value']
        total_rent += result['rent']
        rental_count += 1

        rental_details.append({
            'id': rental.id,
            'customer_name': rental.customer_name,
            'start_date': rental.start_date.isoformat(),
            'end_date': rental.end_date.isoformat(),
            'rental_days': result['rental_days'],
            'rent': result['rent'],
            'value': result['value'],
            'status': rental.status
        })

    return {
        'total_rentals': rental_count,
        'total_value': total_value,
        'total_rent': total_rent,
        'period_start': thirty_days_ago.isoformat(),
        'period_end': today.isoformat(),
        'details': rental_details
    }


def print_statistics(stats):
    """
    打印统计结果

    Args:
        stats: 统计结果字典
    """
    print("=" * 80)
    print("租赁数据统计报告")
    print("=" * 80)
    print(f"\n总租赁订单数: {stats['total_rentals']}")
    print(f"总租赁天数: {stats['total_days']} 天")
    print(f"\n1. 所有 rental 总共产生的价值: ¥{stats['total_value']:.2f}")
    print(f"2. 所有 rental 每天平均产生的价值: ¥{stats['avg_value_per_day']:.2f}")
    print("=" * 80)

    # 打印详细信息
    if stats['details']:
        print("\n详细租赁记录:")
        print("-" * 80)
        print(f"{'ID':<6} {'客户':<15} {'开始日期':<12} {'结束日期':<12} {'天数':<6} {'租金':<10} {'价值':<10} {'状态':<15}")
        print("-" * 80)

        for detail in stats['details']:
            print(f"{detail['id']:<6} "
                  f"{detail['customer_name']:<15} "
                  f"{detail['start_date']:<12} "
                  f"{detail['end_date']:<12} "
                  f"{detail['rental_days']:<6} "
                  f"¥{detail['rent']:<9.2f} "
                  f"¥{detail['value']:<9.2f} "
                  f"{detail['status']:<15}")
        print("-" * 80)


def print_recent_30days_statistics(stats):
    """
    打印最近30天的统计结果

    Args:
        stats: 统计结果字典
    """
    print("\n" + "=" * 80)
    print("最近30天租赁数据统计报告")
    print("=" * 80)
    print(f"统计周期: {stats['period_start']} ~ {stats['period_end']}")
    print(f"\n订单数: {stats['total_rentals']}")
    print(f"订单总租金: ¥{stats['total_rent']:.2f}")
    print(f"订单总收入: ¥{stats['total_value']:.2f}")
    print("=" * 80)

    # 打印详细信息
    if stats['details']:
        print("\n详细租赁记录:")
        print("-" * 80)
        print(f"{'ID':<6} {'客户':<15} {'开始日期':<12} {'结束日期':<12} {'天数':<6} {'租金':<10} {'价值':<10} {'状态':<15}")
        print("-" * 80)

        for detail in stats['details']:
            print(f"{detail['id']:<6} "
                  f"{detail['customer_name']:<15} "
                  f"{detail['start_date']:<12} "
                  f"{detail['end_date']:<12} "
                  f"{detail['rental_days']:<6} "
                  f"¥{detail['rent']:<9.2f} "
                  f"¥{detail['value']:<9.2f} "
                  f"{detail['status']:<15}")
        print("-" * 80)


def save_statistics_to_db(stats):
    """
    保存统计数据到数据库

    Args:
        stats: 统计结果字典（最近30天的统计数据）

    Returns:
        RentalStatistics: 保存的统计记录对象
    """
    from datetime import datetime

    today = date.today()

    # 检查今天是否已经有统计记录
    existing = RentalStatistics.query.filter_by(stat_date=today).first()

    if existing:
        # 更新现有记录
        existing.period_start = datetime.fromisoformat(stats['period_start']).date()
        existing.period_end = datetime.fromisoformat(stats['period_end']).date()
        existing.total_rentals = stats['total_rentals']
        existing.total_rent = stats['total_rent']
        existing.total_value = stats['total_value']
        existing.updated_at = datetime.utcnow()

        db.session.commit()
        print(f"\n✓ 已更新今日统计记录 (ID: {existing.id})")
        return existing
    else:
        # 创建新记录
        new_stat = RentalStatistics(
            stat_date=today,
            period_start=datetime.fromisoformat(stats['period_start']).date(),
            period_end=datetime.fromisoformat(stats['period_end']).date(),
            total_rentals=stats['total_rentals'],
            total_rent=stats['total_rent'],
            total_value=stats['total_value']
        )

        db.session.add(new_stat)
        db.session.commit()
        print(f"\n✓ 已保存新的统计记录 (ID: {new_stat.id})")
        return new_stat


def main():
    """主函数"""
    app = create_app()

    with app.app_context():
        print("正在统计rental数据...\n")

        # 统计所有rental数据
        stats = get_rental_statistics()
        print_statistics(stats)

        # 统计最近30天的rental数据
        recent_stats = get_recent_30days_statistics()
        print_recent_30days_statistics(recent_stats)

        # 保存最近30天的统计数据到数据库
        try:
            save_statistics_to_db(recent_stats)
        except Exception as e:
            print(f"\n✗ 保存统计数据失败: {e}")
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    main()
