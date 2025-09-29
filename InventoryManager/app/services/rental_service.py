"""
租赁管理服务
"""

from app.models import Device, Rental
from app import db
from datetime import datetime, date
from typing import Dict
import logging

logger = logging.getLogger(__name__)



class RentalService:
    """租赁管理服务"""
    
    @staticmethod
    def create_rental(device_id: str, start_date: date, end_date: date,ship_out_time: datetime, ship_in_time: datetime,
                      customer_name: str, customer_phone: str = None) -> Dict:
        """
        创建新的租赁记录
        
        Args:
            device_id: 设备ID
            start_date: 开始日期
            end_date: 结束日期
            ship_out_time: 寄出时间
            ship_in_time: 收回时间
            customer_name: 客户姓名
            customer_phone: 客户电话
            
        Returns:
            Dict: 创建结果
        """
        try:
            # 验证设备是否存在
            device = Device.query.get(device_id)
            if not device:
                return {
                    'success': False,
                    'message': '设备不存在',
                    'error': 'DEVICE_NOT_FOUND'
                }
            
            # 检查设备是否可用 (在线才能租赁)
            if device.status != 'online':
                return {
                    'success': False,
                    'message': f'设备当前状态为离线，无法租赁',
                    'error': 'DEVICE_NOT_AVAILABLE'
                }
            
            
            # 验证日期
            if start_date > end_date:
                return {
                    'success': False,
                    'message': '开始日期必须早于结束日期',
                    'error': 'INVALID_DATE_RANGE'
                }
            
            if start_date < date.today():
                return {
                    'success': False,
                    'message': '开始日期不能早于今天',
                    'error': 'INVALID_START_DATE'
                }
            
            # 创建租赁记录
            rental = Rental(
                device_id=device_id,
                start_date=start_date,
                end_date=end_date,
                customer_name=customer_name,
                customer_phone=customer_phone,
                ship_out_time=ship_out_time,
                ship_in_time=ship_in_time,
                status='not_shipped'
            )
            
            db.session.add(rental)
            db.session.commit()
            
            logger.info(f"成功创建租赁记录: {rental.id}")
            return {
                'success': True,
                'message': '租赁记录创建成功',
                'rental_id': rental.id,
                'rental': rental.to_dict()
            }
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"创建租赁记录失败: {e}")
            return {
                'success': False,
                'message': f'创建租赁记录失败: {str(e)}',
                'error': 'INTERNAL_ERROR'
            }
    
    @staticmethod
    def cancel_rental(rental_id: int, reason: str = None) -> Dict:
        """
        取消租赁
        
        Args:
            rental_id: 租赁记录ID
            reason: 取消原因
            
        Returns:
            Dict: 取消结果
        """
        try:
            rental = Rental.query.get(rental_id)
            if not rental:
                return {
                    'success': False,
                    'message': '租赁记录不存在',
                    'error': 'RENTAL_NOT_FOUND'
                }
            
            if not rental.can_cancel():
                return {
                    'success': False,
                    'message': '当前状态无法取消',
                    'error': 'CANNOT_CANCEL'
                }
            
            # 取消租赁
            rental.status = 'cancelled'
            
            # 设备状态不需要更改，因为现在只有在线/离线两种状态
            
            db.session.commit()
            
            logger.info(f"租赁记录 {rental_id} 已取消")
            return {
                'success': True,
                'message': '租赁已取消',
                'rental': rental.to_dict()
            }
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"取消租赁记录失败: {e}")
            return {
                'success': False,
                'message': f'取消失败: {str(e)}',
                'error': 'INTERNAL_ERROR'
            }
    
