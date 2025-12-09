"""
顺丰下单测试 API 路由模块
"""

from flask import Blueprint, request, jsonify
from app.models.rental import Rental
from app.services.shipping.sf_express_service import get_sf_express_service
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('sf_test', __name__, url_prefix='/api/sf-test')


@bp.route('/order/<int:rental_id>', methods=['POST'])
def test_sf_order(rental_id):
    """
    测试顺丰下单接口

    通过租赁ID测试顺丰下单功能
    """
    try:
        # 查询租赁记录
        rental = Rental.query.get(rental_id)

        if not rental:
            return jsonify({
                'success': False,
                'message': f'租赁记录不存在 (ID: {rental_id})'
            }), 404

        # 检查必要信息
        if not rental.ship_out_tracking_no:
            return jsonify({
                'success': False,
                'message': '该租赁记录缺少运单号，请先录入运单号'
            }), 400

        if not rental.customer_name or not rental.customer_phone or not rental.destination:
            return jsonify({
                'success': False,
                'message': '该租赁记录缺少收件人信息'
            }), 400

        # 获取顺丰服务并测试下单
        sf_service = get_sf_express_service()

        logger.info(f"测试顺丰下单: Rental {rental_id}, 测试模式: {sf_service.client.test_mode}")

        result = sf_service.place_shipping_order(rental)

        return jsonify({
            'success': result.get('success'),
            'message': result.get('message'),
            'data': result.get('data'),
            'test_mode': sf_service.client.test_mode,
            'auth_method': 'OAuth2.0' if sf_service.client.use_oauth else 'msgDigest',
            'rental_info': {
                'id': rental.id,
                'customer_name': rental.customer_name,
                'customer_phone': rental.customer_phone,
                'destination': rental.destination,
                'tracking_no': rental.ship_out_tracking_no
            }
        }), 200 if result.get('success') else 400

    except Exception as e:
        logger.error(f"测试顺丰下单失败: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500


@bp.route('/status', methods=['GET'])
def test_sf_status():
    """
    获取顺丰服务配置状态
    """
    try:
        sf_service = get_sf_express_service()

        return jsonify({
            'success': True,
            'data': {
                'test_mode': sf_service.client.test_mode,
                'use_oauth': sf_service.client.use_oauth,
                'auth_method': 'OAuth2.0' if sf_service.client.use_oauth else 'msgDigest',
                'api_url': sf_service.client.req_url,
                'partner_id_configured': bool(sf_service.client.partner_id),
                'checkword_configured': bool(sf_service.client.checkword),
                'sender_info': {
                    'name': sf_service.sender_name,
                    'phone': sf_service.sender_phone,
                    'address': sf_service.sender_address
                }
            }
        }), 200

    except Exception as e:
        logger.error(f"获取顺丰服务状态失败: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500


@bp.route('/mock-order', methods=['POST'])
def test_mock_order():
    """
    使用模拟数据测试顺丰下单

    不需要真实的租赁记录，使用请求中的数据进行测试
    """
    try:
        data = request.get_json()

        # 获取顺丰服务
        sf_service = get_sf_express_service()

        # 构建模拟订单数据
        order_data = {
            'orderId': data.get('order_id', 'TEST_ORDER_001'),
            'cargoDetails': data.get('cargo_details', [
                {
                    'name': '测试商品',
                    'count': 1
                }
            ]),
            'consigneeInfo': data.get('consignee_info', {
                'name': '测试收件人',
                'mobile': '13800138000',
                'address': '广东省深圳市福田区测试地址'
            }),
            'contactInfoList': [
                {
                    'contactType': 1,
                    'contact': sf_service.sender_name,
                    'tel': sf_service.sender_phone,
                    'address': sf_service.sender_address
                }
            ],
            'expressTypeId': data.get('express_type_id', 1),
            'payMethod': data.get('pay_method', 1),
            'waybillNo': data.get('waybill_no', 'SF1234567890')
        }

        logger.info(f"测试模拟顺丰下单, 测试模式: {sf_service.client.test_mode}")
        logger.debug(f"订单数据: {order_data}")

        # 调用顺丰SDK下单
        result = sf_service.create_order(order_data)

        return jsonify({
            'success': result.get('success'),
            'message': result.get('message'),
            'data': result.get('data'),
            'test_mode': sf_service.client.test_mode,
            'auth_method': 'OAuth2.0' if sf_service.client.use_oauth else 'msgDigest',
            'request_data': order_data
        }), 200 if result.get('success') else 400

    except Exception as e:
        logger.error(f"测试模拟顺丰下单失败: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500
