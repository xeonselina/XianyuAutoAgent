"""
租赁相关API路由
重构后的精简版本，只包含路由定义
"""

from flask import Blueprint
from app.handlers.rental_handlers import RentalHandlers
from app.utils.response import handle_response

bp = Blueprint('rental_api', __name__)


# ===================== 基础租赁API =====================

@bp.route('/api/rentals')
@handle_response
def get_rentals():
    """获取租赁记录列表"""
    return RentalHandlers.handle_get_rentals()


@bp.route('/api/rentals/<rental_id>')
@handle_response
def get_rental(rental_id):
    """获取单个租赁记录"""
    return RentalHandlers.handle_get_rental(rental_id)


@bp.route('/api/rentals', methods=['POST'])
@handle_response
def create_rental():
    """创建租赁记录"""
    return RentalHandlers.handle_create_rental()


@bp.route('/api/rentals/<rental_id>', methods=['PUT'])
@handle_response
def update_rental(rental_id):
    """更新租赁记录"""
    # 使用Web界面的更新处理器，因为功能相同
    return RentalHandlers.handle_web_update_rental(rental_id)


@bp.route('/api/rentals/<rental_id>', methods=['DELETE'])
@handle_response
def delete_rental(rental_id):
    """删除租赁记录"""
    return RentalHandlers.handle_delete_rental(rental_id)


@bp.route('/api/rentals/<rental_id>/status', methods=['PUT'])
@handle_response
def update_rental_status(rental_id):
    """更新租赁状态"""
    return RentalHandlers.handle_update_rental_status(rental_id)


# ===================== 租赁检查API =====================

@bp.route('/api/rentals/check-conflict', methods=['POST'])
@handle_response
def check_rental_conflict():
    """检查租赁冲突"""
    return RentalHandlers.handle_check_rental_conflict()


@bp.route('/api/rentals/check-duplicate', methods=['POST'])
@handle_response
def check_duplicate_rental():
    """检查重复租赁"""
    return RentalHandlers.handle_check_duplicate_rental()


# ===================== Web界面API =====================

@bp.route('/web/rentals/<rental_id>', methods=['GET'])
@handle_response
def web_get_rental(rental_id):
    """Web界面获取租赁记录"""
    return RentalHandlers.handle_get_rental(rental_id)


@bp.route('/web/rentals/<rental_id>', methods=['PUT'])
@handle_response
def web_update_rental(rental_id):
    """Web界面更新租赁记录"""
    return RentalHandlers.handle_web_update_rental(rental_id)


@bp.route('/web/rentals/<rental_id>', methods=['DELETE'])
@handle_response
def web_delete_rental(rental_id):
    """Web界面删除租赁记录"""
    return RentalHandlers.handle_delete_rental(rental_id)