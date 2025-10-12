"""
统计数据 API 路由
"""

from flask import Blueprint, jsonify, request
from app import db
from app.models.rental import Rental
from app.models.rental_statistics import RentalStatistics
from datetime import datetime, date, timedelta

bp = Blueprint('statistics_api', __name__, url_prefix='/api/statistics')


@bp.route('/recent', methods=['GET'])
def get_recent_statistics():
    """
    获取最近的统计数据

    Query Parameters:
        days: 获取最近多少天的数据，默认 30

    Returns:
        JSON: {
            "success": true,
            "data": [
                {
                    "stat_date": "2025-10-11",
                    "total_rentals": 122,
                    "total_rent": 26048.00,
                    "total_value": 24218.00,
                    ...
                },
                ...
            ]
        }
    """
    try:
        days = request.args.get('days', 30, type=int)

        # 获取最近N天的统计记录
        stats = RentalStatistics.get_latest_statistics(limit=days)

        # 转换为字典列表（按日期升序排序）
        data = [stat.to_dict() for stat in reversed(stats)]

        return jsonify({
            'success': True,
            'data': data
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/date-range', methods=['GET'])
def get_statistics_by_date_range():
    """
    获取指定日期范围的统计数据

    Query Parameters:
        start_date: 开始日期，格式 YYYY-MM-DD
        end_date: 结束日期，格式 YYYY-MM-DD

    Returns:
        JSON: {
            "success": true,
            "data": [...]
        }
    """
    try:
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        if not start_date_str or not end_date_str:
            return jsonify({
                'success': False,
                'error': '缺少 start_date 或 end_date 参数'
            }), 400

        # 解析日期
        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()

        # 获取统计记录
        stats = RentalStatistics.get_statistics_by_date_range(start_date, end_date)

        # 转换为字典列表
        data = [stat.to_dict() for stat in stats]

        return jsonify({
            'success': True,
            'data': data
        })
    except ValueError as e:
        return jsonify({
            'success': False,
            'error': '日期格式错误，请使用 YYYY-MM-DD 格式'
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/latest', methods=['GET'])
def get_latest_statistics():
    """
    获取最新的一条统计记录

    Returns:
        JSON: {
            "success": true,
            "data": {...}
        }
    """
    try:
        latest = RentalStatistics.get_latest_statistics(limit=1)

        if not latest:
            return jsonify({
                'success': False,
                'error': '暂无统计数据'
            }), 404

        return jsonify({
            'success': True,
            'data': latest[0].to_dict()
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


def _calculate_rental_value(rental):
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


def _get_recent_30days_rental_data():
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
        result = _calculate_rental_value(rental)

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


def _save_statistics_to_db(stats):
    """
    保存统计数据到数据库

    Args:
        stats: 统计结果字典（最近30天的统计数据）

    Returns:
        RentalStatistics: 保存的统计记录对象
    """
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
        return new_stat


@bp.route('/calculate', methods=['POST'])
def calculate_statistics():
    """
    计算并保存最近30天的租赁统计数据

    该接口可以通过cron定时调用，用于定期更新统计数据

    Returns:
        JSON: {
            "success": true,
            "message": "统计数据已更新",
            "data": {
                "stat_id": 123,
                "is_new": true,
                "statistics": {...}
            }
        }
    """
    try:
        # 获取最近30天的统计数据
        stats = _get_recent_30days_rental_data()

        # 保存到数据库
        saved_stat = _save_statistics_to_db(stats)

        return jsonify({
            'success': True,
            'message': '统计数据已更新',
            'data': {
                'stat_id': saved_stat.id,
                'stat_date': saved_stat.stat_date.isoformat(),
                'is_new': saved_stat.created_at == saved_stat.updated_at,
                'statistics': {
                    'total_rentals': stats['total_rentals'],
                    'total_rent': stats['total_rent'],
                    'total_value': stats['total_value'],
                    'period_start': stats['period_start'],
                    'period_end': stats['period_end']
                }
            }
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({
            'success': False,
            'error': f'计算统计数据失败: {str(e)}'
        }), 500
