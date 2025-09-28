"""
租赁相关API路由
重构后的精简版本，只包含路由定义
"""

from flask import Blueprint
from app.handlers.rental_handlers import RentalHandlers

bp = Blueprint('rental_api', __name__)


# ===================== 基础租赁API =====================

@bp.route('/api/rentals')
def get_rentals():
    """获取租赁记录列表"""
    response_data, status_code = RentalHandlers.handle_get_rentals()
    return response_data, status_code


@bp.route('/api/rentals/<rental_id>')
def get_rental(rental_id):
    """获取单个租赁记录"""
    response_data, status_code = RentalHandlers.handle_get_rental(rental_id)
    return response_data, status_code


@bp.route('/api/rentals', methods=['POST'])
def create_rental():
    """创建租赁记录"""
    response_data, status_code = RentalHandlers.handle_create_rental()
    return response_data, status_code


@bp.route('/api/rentals/<rental_id>', methods=['PUT'])
def update_rental(rental_id):
    """更新租赁记录"""
    # 使用Web界面的更新处理器，因为功能相同
    response_data, status_code = RentalHandlers.handle_web_update_rental(rental_id)
    return response_data, status_code


@bp.route('/api/rentals/<rental_id>', methods=['DELETE'])
def delete_rental(rental_id):
    """删除租赁记录"""
    response_data, status_code = RentalHandlers.handle_delete_rental(rental_id)
    return response_data, status_code


@bp.route('/api/rentals/<rental_id>/status', methods=['PUT'])
def update_rental_status(rental_id):
    """更新租赁状态"""
    response_data, status_code = RentalHandlers.handle_update_rental_status(rental_id)
    return response_data, status_code


# ===================== 租赁检查API =====================

@bp.route('/api/rentals/check-conflict', methods=['POST'])
def check_rental_conflict():
    """检查租赁冲突"""
    response_data, status_code = RentalHandlers.handle_check_rental_conflict()
    return response_data, status_code


@bp.route('/api/rentals/check-duplicate', methods=['POST'])
def check_duplicate_rental():
    """检查重复租赁"""
    response_data, status_code = RentalHandlers.handle_check_duplicate_rental()
    return response_data, status_code


# ===================== Web界面API =====================

@bp.route('/web/rentals/<rental_id>', methods=['GET'])
def web_get_rental(rental_id):
    """Web界面获取租赁记录"""
    response_data, status_code = RentalHandlers.handle_get_rental(rental_id)
    return response_data, status_code


@bp.route('/web/rentals/<rental_id>', methods=['PUT'])
def web_update_rental(rental_id):
    """Web界面更新租赁记录"""
    response_data, status_code = RentalHandlers.handle_web_update_rental(rental_id)
    return response_data, status_code


@bp.route('/web/rentals/<rental_id>', methods=['DELETE'])
def web_delete_rental(rental_id):
    """Web界面删除租赁记录"""
    response_data, status_code = RentalHandlers.handle_delete_rental(rental_id)
    return response_data, status_code