"""
库存API处理器
包含库存相关的请求处理逻辑
"""

from flask import request, current_app
from app.utils.response import (
    ApiResponse,
    success,
    bad_request,
    server_error
)
from app.utils.date_utils import (
    parse_date_strings,
    validate_date_range
)
from app.services.inventory_service import InventoryService


class InventoryHandlers:
    """库存处理器类"""

    @staticmethod
    def handle_get_available_inventory() -> ApiResponse:
        """处理获取可用库存请求"""
        try:
            # 获取查询参数
            start_date_str = request.args.get('start_date')
            end_date_str = request.args.get('end_date')
            device_type = request.args.get('device_type')

            # 验证必填参数
            if not start_date_str or not end_date_str:
                return bad_request('缺少必填参数: start_date 和 end_date')

            # 解析和验证日期
            try:
                start_date, end_date = parse_date_strings(start_date_str, end_date_str)
            except ValueError as e:
                return bad_request(str(e))

            # 验证日期范围
            validation_error = validate_date_range(start_date, end_date)
            if validation_error:
                return bad_request(validation_error)

            # 调用服务层查询可用库存
            response_data = InventoryService.query_available_inventory(
                start_date,
                end_date,
                device_type
            )

            return success(
                data=response_data,
                message=f'查询成功，共 {len(response_data)} 台可用设备'
            )

        except Exception as e:
            current_app.logger.error(f"查询可用库存失败: {e}")
            return server_error('查询可用库存失败')
