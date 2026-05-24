"""
库存相关API模块
重构后的精简版本，只包含路由定义
"""

from flask import Blueprint
from app.handlers.inventory_handlers import InventoryHandlers
from app.utils.response import handle_response

bp = Blueprint('inventory_api', __name__)


@bp.route('/api/inventory/available', methods=['GET'])
@handle_response
def get_internal_available_inventory():
    """内部库存查询接口（无需认证）"""
    return InventoryHandlers.handle_get_available_inventory()
