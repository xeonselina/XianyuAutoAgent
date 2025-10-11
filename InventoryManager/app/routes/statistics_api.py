"""
统计数据 API 路由
"""

from flask import Blueprint, jsonify, request
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
