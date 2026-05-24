"""
批量发货 API 路由模块
重构后的精简版本，只包含路由定义
"""

from flask import Blueprint
from app.handlers.shipping_batch_handlers import ShippingBatchHandlers
from app.utils.response import handle_response

bp = Blueprint('shipping_batch', __name__, url_prefix='/api/shipping-batch')


@bp.route('/schedule', methods=['POST'])
@handle_response
def schedule_shipment():
    """预约发货"""
    return ShippingBatchHandlers.handle_schedule_shipment()


@bp.route('/status', methods=['GET'])
@handle_response
def get_status():
    """获取批量发货状态摘要"""
    return ShippingBatchHandlers.handle_get_status()


@bp.route('/express-type', methods=['PATCH'])
@handle_response
def update_express_type():
    """更新租赁订单的快递类型"""
    return ShippingBatchHandlers.handle_update_express_type()


@bp.route('/printers', methods=['GET'])
@handle_response
def get_printers():
    """获取打印机配置信息"""
    return ShippingBatchHandlers.handle_get_printers()


@bp.route('/print-waybills', methods=['POST'])
@handle_response
def print_waybills():
    """批量打印快递面单"""
    return ShippingBatchHandlers.handle_print_waybills()


@bp.route('/ship-to-xianyu/<int:rental_id>', methods=['POST'])
@handle_response
def ship_to_xianyu(rental_id):
    """发货到闲鱼"""
    return ShippingBatchHandlers.handle_ship_to_xianyu(rental_id)
