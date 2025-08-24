"""
库存相关API模块
"""

from flask import Blueprint, request, jsonify, current_app
from app.models.device import Device
from app.services.inventory_service import InventoryService
from app.utils.date_utils import (
    parse_date_strings, 
    validate_date_range, 
    convert_dates_to_datetime,
    create_error_response,
    create_success_response
)
from datetime import datetime

bp = Blueprint('inventory_api', __name__)


@bp.route('/api/inventory/available', methods=['GET'])
def get_internal_available_inventory():
    """内部库存查询接口（无需认证）"""
    try:
        # 获取查询参数
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        device_type = request.args.get('device_type')
        
        # 验证必填参数
        if not start_date_str or not end_date_str:
            return create_error_response('缺少必填参数: start_date 和 end_date')
        
        # 解析和验证日期
        try:
            start_date, end_date = parse_date_strings(start_date_str, end_date_str)
        except ValueError as e:
            return create_error_response(str(e))
        
        # 验证日期范围
        validation_error = validate_date_range(start_date, end_date)
        if validation_error:
            return create_error_response(validation_error)
        
        # 使用通用库存查询方法
        response_data = InventoryService.query_available_inventory(
            start_date, 
            end_date, 
            device_type
        )
        
        return create_success_response(
            data=response_data,
            query_params={
                'start_date': start_date_str,
                'end_date': end_date_str,
                'device_type': device_type
            },
            total_available=len(response_data)
        )
        
    except Exception as e:
        current_app.logger.error(f"查询可用库存失败: {e}")
        return create_error_response('服务器内部错误', 500)
