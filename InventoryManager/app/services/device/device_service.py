"""
设备业务逻辑服务层
"""

from typing import List, Dict, Any, Optional
from flask import current_app
from app import db
from app.models.device import Device


class DeviceService:
    """设备服务类"""

    @staticmethod
    def get_devices_with_filters(
        page: int = 1,
        per_page: int = 20,
        name: Optional[str] = None,
        model: Optional[str] = None,
        status: Optional[str] = None,
        lifecycle_status: Optional[str] = None,
        is_accessory: Optional[bool] = None,
        serial_number: Optional[str] = None
    ) -> Dict[str, Any]:
        """获取带过滤条件的设备列表
        
        Args:
            page: 页码（从1开始）
            per_page: 每页数量（最多100）
            name: 设备名称（模糊查询）
            model: 设备型号（精确匹配）
            status: 设备状态 online/offline（精确匹配）
            lifecycle_status: 生命周期状态 active/sold/decommissioned/damaged/retired（精确匹配）
            is_accessory: 是否为附件（布尔值）
            serial_number: 序列号（模糊查询）
        
        Returns:
            Dict: 包含devices列表、分页信息
        """
        try:
            query = Device.query
            
            # 应用过滤条件
            if name:
                query = query.filter(Device.name.like(f'%{name}%'))
            
            if serial_number:
                query = query.filter(Device.serial_number.like(f'%{serial_number}%'))
            
            if model:
                query = query.filter(Device.model == model)
            
            if status:
                query = query.filter(Device.status == status)
            
            if lifecycle_status:
                query = query.filter(Device.lifecycle_status == lifecycle_status)
            
            if is_accessory is not None:
                query = query.filter(Device.is_accessory == is_accessory)
            
            # 按生命周期日期降序排列（最新的在前面），然后按创建日期降序
            # 使用 MySQL 兼容写法：IS NULL DESC 将 NULL 排在前面
            from sqlalchemy import text as sa_text
            query = query.order_by(
                sa_text('lifecycle_date IS NULL DESC'),
                Device.lifecycle_date.desc(),
                Device.created_at.desc()
            )
            
            # 分页
            pagination = query.paginate(
                page=page,
                per_page=min(per_page, 100),
                error_out=False
            )
            
            return {
                'devices': [device.to_dict() for device in pagination.items],
                'total': pagination.total,
                'pages': pagination.pages,
                'current_page': page,
                'per_page': min(per_page, 100),
                'has_next': pagination.has_next,
                'has_prev': pagination.has_prev
            }
        
        except Exception as e:
            current_app.logger.error(f"获取设备列表失败: {e}")
            raise
