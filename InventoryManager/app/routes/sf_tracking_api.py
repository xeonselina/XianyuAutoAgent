"""
顺丰物流追踪 API 路由模块
"""

from flask import Blueprint, request, jsonify
from app import db
from app.models.rental import Rental
from app.utils.sf.sf_sdk_wrapper import SFExpressSDK
from datetime import datetime, timedelta
import os
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('sf_tracking', __name__, url_prefix='/api/sf-tracking')

# 寄件人手机号后四位(用于顺丰API验证)
SENDER_PHONE_LAST4 = '4947'  # 13510224947 的后四位


def get_sf_client():
    """获取顺丰 SDK 客户端实例"""
    partner_id = os.getenv('SF_PARTNER_ID')
    checkword = os.getenv('SF_CHECKWORD')
    test_mode = os.getenv('SF_TEST_MODE', 'true') == 'true'
    logger.info(f"test_mode in sf_tracking_api: {test_mode}")
    logger.info(f"partner_id in sf_tracking_api: {partner_id}")
    logger.info(f"checkword in sf_tracking_api: {checkword}")

    return SFExpressSDK(
        partner_id=partner_id,
        checkword=checkword,
        test_mode=test_mode
    )


@bp.route('/list', methods=['GET'])
def get_rental_list():
    """
    获取所有有顺丰运单号的租赁订单列表

    查询参数:
    - start_date: 开始日期 (可选, 默认: 4天前)
    - end_date: 结束日期 (可选, 默认: 4天后)

    返回:
    - success: 是否成功
    - data: 租赁订单列表
    """
    try:
        # 获取查询参数
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')

        # 默认显示过去4天 + 未来4天
        if not start_date_str:
            start_date = datetime.now() - timedelta(days=4)
        else:
            start_date = datetime.fromisoformat(start_date_str.replace('Z', '+00:00'))

        if not end_date_str:
            end_date = datetime.now() + timedelta(days=4)
        else:
            end_date = datetime.fromisoformat(end_date_str.replace('Z', '+00:00'))

        # 查询有运单号的租赁记录
        query = Rental.query.filter(
            Rental.ship_out_tracking_no.isnot(None),
            Rental.ship_out_tracking_no != ''
        )

        # 应用日期筛选
        query = query.filter(
            Rental.ship_out_time >= start_date,
            Rental.ship_out_time <= end_date
        )

        # 按发货时间降序排列
        rentals = query.order_by(Rental.ship_out_time.desc()).all()

        # 构建响应数据
        rental_list = []
        for rental in rentals:
            # 获取设备名称
            device_name = None
            if rental.device:
                if rental.device.device_model:
                    device_name = rental.device.device_model.name
                else:
                    device_name = rental.device.name

            rental_list.append({
                'rental_id': rental.id,
                'customer_name': rental.customer_name,
                'customer_phone': rental.customer_phone,
                'destination': rental.destination,
                'device_name': device_name,
                'ship_out_tracking_no': rental.ship_out_tracking_no,
                'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                'status': rental.status
            })

        logger.info(f"查询到 {len(rental_list)} 条有运单号的租赁记录")

        return jsonify({
            'success': True,
            'data': rental_list,
            'total': len(rental_list)
        }), 200

    except Exception as e:
        logger.error(f"获取租赁列表失败: {e}")
        return jsonify({
            'success': False,
            'message': f'获取列表失败: {str(e)}'
        }), 500


@bp.route('/query', methods=['POST'])
def query_tracking():
    """
    查询单个运单的物流轨迹

    请求体:
    - tracking_number: 顺丰运单号

    返回:
    - success: 是否成功
    - data: 物流轨迹信息
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据不能为空'
            }), 400

        tracking_number = data.get('tracking_number', '').strip()

        if not tracking_number:
            return jsonify({
                'success': False,
                'message': '运单号不能为空'
            }), 400

        logger.info(f"查询运单物流: {tracking_number}")

        # 获取顺丰客户端
        sf_client = get_sf_client()

        # 调用顺丰 API 查询路由
        response = sf_client.search_routes(tracking_number, SENDER_PHONE_LAST4)

        # 解析路由响应
        parsed_routes = sf_client.parse_route_response(response)

        if tracking_number in parsed_routes:
            route_info = parsed_routes[tracking_number]
            logger.info(f"运单 {tracking_number} 查询成功, 状态: {route_info.get('status')}")

            return jsonify({
                'success': True,
                'data': route_info
            }), 200
        else:
            logger.warning(f"运单 {tracking_number} 未找到物流信息")
            return jsonify({
                'success': False,
                'message': '未找到该运单的物流信息',
                'data': {
                    'tracking_number': tracking_number,
                    'status': 'not_found',
                    'routes': [],
                    'last_update': None,
                    'delivered_time': None
                }
            }), 200

    except Exception as e:
        logger.error(f"查询物流信息失败: {e}")
        return jsonify({
            'success': False,
            'message': f'查询失败: {str(e)}'
        }), 500


@bp.route('/batch-query', methods=['POST'])
def batch_query_tracking():
    """
    批量查询运单物流轨迹

    请求体:
    - tracking_numbers: 运单号列表 (最多100个)

    返回:
    - success: 是否成功
    - data: 物流轨迹信息字典 { tracking_number: route_info }
    - errors: 查询失败的运单号列表
    """
    try:
        data = request.get_json()

        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据不能为空'
            }), 400

        tracking_numbers = data.get('tracking_numbers', [])

        if not tracking_numbers:
            return jsonify({
                'success': False,
                'message': '运单号列表不能为空'
            }), 400

        if len(tracking_numbers) > 100:
            return jsonify({
                'success': False,
                'message': '一次最多查询100个运单号'
            }), 400

        logger.info(f"批量查询 {len(tracking_numbers)} 个运单")

        # 获取顺丰客户端
        sf_client = get_sf_client()

        # 调用顺丰 API 批量查询
        try:
            response = sf_client.batch_search_routes(tracking_numbers, SENDER_PHONE_LAST4)
            parsed_routes = sf_client.parse_route_response(response)
        except Exception as api_error:
            logger.error(f"顺丰API调用失败: {api_error}")
            return jsonify({
                'success': False,
                'message': f'顺丰API调用失败: {str(api_error)}'
            }), 500

        # 检查哪些运单号查询失败
        errors = []
        for tracking_number in tracking_numbers:
            if tracking_number not in parsed_routes:
                errors.append(tracking_number)

        success_count = len(parsed_routes)
        logger.info(f"批量查询完成: 成功 {success_count}, 失败 {len(errors)}")

        return jsonify({
            'success': True,
            'data': parsed_routes,
            'total': len(tracking_numbers),
            'success_count': success_count,
            'errors': errors
        }), 200

    except Exception as e:
        logger.error(f"批量查询失败: {e}")
        return jsonify({
            'success': False,
            'message': f'批量查询失败: {str(e)}'
        }), 500
