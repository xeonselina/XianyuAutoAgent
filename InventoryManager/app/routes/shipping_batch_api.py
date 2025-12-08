"""
批量发货 API 路由模块
"""

from flask import Blueprint, request, jsonify
from app import db
from app.models.rental import Rental
from datetime import datetime
import re
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('shipping_batch', __name__, url_prefix='/api/shipping-batch')


@bp.route('/scan-rental', methods=['POST'])
def scan_rental():
    """
    扫描租赁记录二维码

    接收租赁ID，返回租赁详情用于显示
    """
    try:
        data = request.get_json()
        rental_id = data.get('rental_id')

        if not rental_id:
            return jsonify({
                'success': False,
                'message': '缺少rental_id参数'
            }), 400

        # 查询租赁记录
        rental = Rental.query.get(rental_id)

        if not rental:
            return jsonify({
                'success': False,
                'message': f'租赁记录不存在 (ID: {rental_id})'
            }), 404

        # 获取附件列表
        accessories = []
        if rental.child_rentals:
            for child_rental in rental.child_rentals:
                if child_rental.device:
                    accessories.append(child_rental.device.device_model.name if child_rental.device.device_model else child_rental.device.name)

        # 返回租赁详情
        return jsonify({
            'success': True,
            'data': {
                'rental_id': rental.id,
                'customer_name': rental.customer_name,
                'customer_phone': rental.customer_phone,
                'destination': rental.destination,
                'device_name': rental.device.device_model.name if rental.device and rental.device.device_model else (rental.device.name if rental.device else None),
                'accessories': accessories,
                'start_date': rental.start_date.isoformat() if rental.start_date else None,
                'end_date': rental.end_date.isoformat() if rental.end_date else None,
                'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                'ship_out_tracking_no': rental.ship_out_tracking_no,
                'status': rental.status
            }
        }), 200

    except Exception as e:
        logger.error(f"扫描租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500


@bp.route('/record-waybill', methods=['POST'])
def record_waybill():
    """
    录入运单号

    接收租赁ID和运单号，更新数据库
    """
    try:
        data = request.get_json()
        rental_id = data.get('rental_id')
        waybill_no = data.get('waybill_no')

        if not rental_id or not waybill_no:
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
            }), 400

        # 验证运单号格式 (字母数字组合，至少10位)
        if not re.match(r'^[A-Z0-9]{10,}$', waybill_no, re.IGNORECASE):
            return jsonify({
                'success': False,
                'message': f'运单号格式无效: {waybill_no}'
            }), 400

        # 查询租赁记录
        rental = Rental.query.get(rental_id)

        if not rental:
            return jsonify({
                'success': False,
                'message': f'租赁记录不存在 (ID: {rental_id})'
            }), 404

        # 检查运单号是否已被其他租赁使用
        existing_rental = Rental.query.filter(
            Rental.ship_out_tracking_no == waybill_no,
            Rental.id != rental_id
        ).first()

        if existing_rental:
            return jsonify({
                'success': False,
                'message': f'运单号已被使用 (Rental: {existing_rental.id})',
                'existing_rental_id': existing_rental.id
            }), 409

        # 更新运单号
        rental.ship_out_tracking_no = waybill_no
        db.session.commit()

        logger.info(f"运单号已录入: Rental {rental_id}, Waybill {waybill_no}")

        return jsonify({
            'success': True,
            'message': '运单号已录入'
        }), 200

    except Exception as e:
        logger.error(f"录入运单号失败: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500


@bp.route('/schedule', methods=['POST'])
def schedule_shipment():
    """
    预约发货

    接收租赁ID列表和预约时间，更新数据库
    """
    try:
        data = request.get_json()
        rental_ids = data.get('rental_ids', [])
        scheduled_time_str = data.get('scheduled_time')

        if not rental_ids or not scheduled_time_str:
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
            }), 400

        # 解析预约时间
        try:
            scheduled_time = datetime.fromisoformat(scheduled_time_str.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({
                'success': False,
                'message': '时间格式无效'
            }), 400

        # 查询租赁记录
        rentals = Rental.query.filter(Rental.id.in_(rental_ids)).all()

        scheduled_count = 0
        failed_rentals = []

        for rental in rentals:
            # 只预约有运单号的租赁
            if not rental.ship_out_tracking_no:
                failed_rentals.append({
                    'id': rental.id,
                    'reason': '缺少运单号'
                })
                continue

            # 更新预约时间
            rental.scheduled_ship_time = scheduled_time
            scheduled_count += 1

        db.session.commit()

        logger.info(f"预约发货: {scheduled_count} 个订单, 时间: {scheduled_time}")

        return jsonify({
            'success': True,
            'data': {
                'scheduled_count': scheduled_count,
                'failed_rentals': failed_rentals
            }
        }), 200

    except Exception as e:
        logger.error(f"预约发货失败: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500


@bp.route('/status', methods=['GET'])
def get_status():
    """
    获取批量发货状态摘要

    返回各状态的订单数量
    """
    try:
        # 获取查询参数
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        rental_ids_str = request.args.get('rental_ids')

        # 构建基础查询
        query = Rental.query

        if rental_ids_str:
            rental_ids = [int(id) for id in rental_ids_str.split(',')]
            query = query.filter(Rental.id.in_(rental_ids))
        elif start_date and end_date:
            query = query.filter(
                Rental.ship_out_time >= start_date,
                Rental.ship_out_time <= end_date
            )

        rentals = query.all()

        # 统计各状态数量
        total = len(rentals)
        waybill_recorded = sum(1 for r in rentals if r.ship_out_tracking_no)
        scheduled = sum(1 for r in rentals if r.scheduled_ship_time)
        shipped = sum(1 for r in rentals if r.status == 'shipped')

        return jsonify({
            'success': True,
            'data': {
                'total': total,
                'waybill_recorded': waybill_recorded,
                'scheduled': scheduled,
                'shipped': shipped
            }
        }), 200

    except Exception as e:
        logger.error(f"获取状态失败: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500
