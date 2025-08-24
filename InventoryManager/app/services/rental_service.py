"""
租赁管理服务
"""

from app.models import Device, Rental
from app import db
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


def _check_device_availability(device_id: int, start_date: date, end_date: date) -> bool:
    """
    检查设备在指定时间段是否可用
    
    Args:
        device_id: 设备ID
        start_date: 开始日期
        end_date: 结束日期
        
    Returns:
        bool: 是否可用
    """
    try:
        from app.models.rental import Rental
        
        # 查找在指定时间段内有冲突的租赁记录
        conflicting_rentals = Rental.query.filter(
            db.and_(
                Rental.device_id == device_id,
                Rental.status.in_(['pending', 'active']),  # 包括待处理和活动中的租赁
                # 租赁时间段与请求时间段重叠
                db.and_(
                    Rental.start_date <= end_date,
                    Rental.end_date >= start_date
                )
            )
        ).count()
        
        return conflicting_rentals == 0
        
    except Exception as e:
        logger.error(f"检查设备可用性失败: {e}")
        return False


class RentalService:
    """租赁管理服务"""
    
    @staticmethod
    def create_rental(device_id: str, start_date: date, end_date: date,
                      customer_name: str, customer_phone: str = None) -> Dict:
        """
        创建新的租赁记录
        
        Args:
            device_id: 设备ID
            start_date: 开始日期
            end_date: 结束日期
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
            
            # 检查设备是否可用
            if device.status != 'available':
                return {
                    'success': False,
                    'message': f'设备当前状态为: {device.status}',
                    'error': 'DEVICE_NOT_AVAILABLE'
                }
            
            # 检查时间冲突
            if not _check_device_availability(device.id, start_date, end_date):
                return {
                    'success': False,
                    'message': '设备在指定时间段不可用',
                    'error': 'TIME_CONFLICT'
                }
            
            # 验证日期
            if start_date >= end_date:
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
                status='pending'
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
    def approve_rental(rental_id: int) -> Dict:
        """
        审批租赁申请
        
        Args:
            rental_id: 租赁记录ID
            
        Returns:
            Dict: 审批结果
        """
        try:
            rental = Rental.query.get(rental_id)
            if not rental:
                return {
                    'success': False,
                    'message': '租赁记录不存在',
                    'error': 'RENTAL_NOT_FOUND'
                }
            
            if rental.status != 'pending':
                return {
                    'success': False,
                    'message': f'租赁记录状态为 {rental.status}，无法审批',
                    'error': 'INVALID_STATUS'
                }
            
            # 再次检查设备可用性
            device = rental.device
            if not _check_device_availability(device.id, rental.start_date, rental.end_date):
                return {
                    'success': False,
                    'message': '设备在指定时间段不可用',
                    'error': 'DEVICE_NOT_AVAILABLE'
                }
            
            # 审批通过
            rental.status = 'active'
            device.status = 'rented'
            
            db.session.commit()
            
            logger.info(f"租赁记录 {rental_id} 审批通过")
            return {
                'success': True,
                'message': '租赁申请审批通过',
                'rental': rental.to_dict()
            }
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"审批租赁记录失败: {e}")
            return {
                'success': False,
                'message': f'审批失败: {str(e)}',
                'error': 'INTERNAL_ERROR'
            }
    
    @staticmethod
    def complete_rental(rental_id: int) -> Dict:
        """
        完成租赁
        
        Args:
            rental_id: 租赁记录ID
            
        Returns:
            Dict: 完成结果
        """
        try:
            rental = Rental.query.get(rental_id)
            if not rental:
                return {
                    'success': False,
                    'message': '租赁记录不存在',
                    'error': 'RENTAL_NOT_FOUND'
                }
            
            if rental.status != 'active':
                return {
                    'success': False,
                    'message': f'租赁记录状态为 {rental.status}，无法完成',
                    'error': 'INVALID_STATUS'
                }
            
            # 完成租赁
            rental.status = 'completed'
            rental.device.status = 'available'
            
            db.session.commit()
            
            logger.info(f"租赁记录 {rental_id} 已完成")
            return {
                'success': True,
                'message': '租赁已完成',
                'rental': rental.to_dict()
            }
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"完成租赁记录失败: {e}")
            return {
                'success': False,
                'message': f'完成失败: {str(e)}',
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
            
            # 如果设备状态为已租，恢复为可用
            if rental.device.status == 'rented':
                rental.device.status = 'available'
            
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
    
    @staticmethod
    def extend_rental(rental_id: int, new_end_date: date) -> Dict:
        """
        延期租赁
        
        Args:
            rental_id: 租赁记录ID
            new_end_date: 新的结束日期
            
        Returns:
            Dict: 延期结果
        """
        try:
            rental = Rental.query.get(rental_id)
            if not rental:
                return {
                    'success': False,
                    'message': '租赁记录不存在',
                    'error': 'RENTAL_NOT_FOUND'
                }
            
            if not rental.can_extend():
                return {
                    'success': False,
                    'message': '当前状态无法延期',
                    'error': 'CANNOT_EXTEND'
                }
            
            # 验证新日期
            if new_end_date <= rental.end_date:
                return {
                    'success': False,
                    'message': '新结束日期必须晚于当前结束日期',
                    'error': 'INVALID_NEW_END_DATE'
                }
            
            # 检查设备在新时间段是否可用
            device = rental.device
            if not _check_device_availability(device.id, rental.end_date + timedelta(days=1), new_end_date):
                return {
                    'success': False,
                    'message': '设备在新时间段不可用',
                    'error': 'TIME_CONFLICT'
                }
            
            # 延期
            old_end_date = rental.end_date
            rental.end_date = new_end_date
            
            db.session.commit()
            
            logger.info(f"租赁记录 {rental_id} 延期至 {new_end_date}")
            return {
                'success': True,
                'message': '租赁延期成功',
                'rental': rental.to_dict(),
                'old_end_date': old_end_date.isoformat(),
                'new_end_date': new_end_date.isoformat()
            }
            
        except Exception as e:
            db.session.rollback()
            logger.error(f"延期租赁记录失败: {e}")
            return {
                'success': False,
                'message': f'延期失败: {str(e)}',
                'error': 'INTERNAL_ERROR'
            }
    
    @staticmethod
    def get_rental_by_id(rental_id: int) -> Optional[Rental]:
        """
        根据ID获取租赁记录
        
        Args:
            rental_id: 租赁记录ID
            
        Returns:
            Optional[Rental]: 租赁记录对象
        """
        return Rental.query.get(rental_id)
    
    @staticmethod
    def get_rentals_by_device(device_id: str, status: str = None) -> List[Rental]:
        """
        获取指定设备的租赁记录
        
        Args:
            device_id: 设备ID
            status: 状态过滤（可选）
            
        Returns:
            List[Rental]: 租赁记录列表
        """
        query = Rental.query.filter(Rental.device_id == device_id)
        if status:
            query = query.filter(Rental.status == status)
        return query.order_by(Rental.start_date.desc()).all()
    
    @staticmethod
    def get_rentals_by_customer(customer_name: str, status: str = None) -> List[Rental]:
        """
        获取指定客户的租赁记录
        
        Args:
            customer_name: 客户姓名
            status: 状态过滤（可选）
            
        Returns:
            List[Rental]: 租赁记录列表
        """
        query = Rental.query.filter(Rental.customer_name == customer_name)
        if status:
            query = query.filter(Rental.status == status)
        return query.order_by(Rental.start_date.desc()).all()
    
    @staticmethod
    def get_active_rentals() -> List[Rental]:
        """
        获取所有活动状态的租赁记录
        
        Returns:
            List[Rental]: 活动租赁记录列表
        """
        return Rental.query.filter(Rental.status == 'active').all()
    
    @staticmethod
    def get_overdue_rentals() -> List[Rental]:
        """
        获取所有逾期的租赁记录
        
        Returns:
            List[Rental]: 逾期租赁记录列表
        """
        today = date.today()
        return Rental.query.filter(
            Rental.status == 'active',
            Rental.end_date < today
        ).all()
    
    @staticmethod
    def get_rentals_by_date_range(start_date: date, end_date: date, 
                                 status: str = None) -> List[Rental]:
        """
        获取指定日期范围内的租赁记录
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            status: 状态过滤（可选）
            
        Returns:
            List[Rental]: 租赁记录列表
        """
        query = Rental.query.filter(
            db.or_(
                db.and_(
                    Rental.start_date <= start_date,
                    Rental.end_date >= start_date
                ),
                db.and_(
                    Rental.start_date <= end_date,
                    Rental.end_date >= end_date
                ),
                db.and_(
                    Rental.start_date >= start_date,
                    Rental.end_date <= end_date
                )
            )
        )
        
        if status:
            query = query.filter(Rental.status == status)
        
        return query.order_by(Rental.start_date).all()
    
    @staticmethod
    def get_rental_statistics() -> Dict:
        """
        获取租赁统计信息
        
        Returns:
            Dict: 统计信息
        """
        try:
            total_rentals = Rental.query.count()
            active_rentals = Rental.query.filter(Rental.status == 'active').count()
            pending_rentals = Rental.query.filter(Rental.status == 'pending').count()
            completed_rentals = Rental.query.filter(Rental.status == 'completed').count()
            cancelled_rentals = Rental.query.filter(Rental.status == 'cancelled').count()
            overdue_rentals = Rental.query.filter(
                Rental.status == 'active',
                Rental.end_date < date.today()
            ).count()
            
            return {
                'total': total_rentals,
                'active': active_rentals,
                'pending': pending_rentals,
                'completed': completed_rentals,
                'cancelled': cancelled_rentals,
                'overdue': overdue_rentals
            }
            
        except Exception as e:
            logger.error(f"获取租赁统计信息失败: {e}")
            return {}
