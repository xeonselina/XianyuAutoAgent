"""
设备状态自动更新服务
"""

from app import db
from app.models.device import Device
from app.models.rental import Rental
from datetime import datetime, date, timedelta
import logging

logger = logging.getLogger(__name__)


class DeviceStatusService:
    """设备状态自动更新服务"""
    
    @staticmethod
    def update_device_statuses():
        """更新所有设备的状态（按分钟调用）"""
        try:
            today = date.today()
            logger.info(f"开始自动更新设备状态，当前日期: {today}")
            
            # 获取所有设备
            devices = Device.query.all()
            updated_count = 0
            
            for device in devices:
                old_status = device.status
                new_status = DeviceStatusService._calculate_device_status(device, today)
                
                if new_status != old_status:
                    device.status = new_status
                    device.updated_at = datetime.utcnow()
                    updated_count += 1
                    logger.info(f"设备 {device.name} (ID: {device.id}) 状态从 {old_status} 更新为 {new_status}")
            
            if updated_count > 0:
                db.session.commit()
                logger.info(f"成功更新 {updated_count} 个设备的状态")
            else:
                logger.info("没有设备状态需要更新")
                
        except Exception as e:
            logger.error(f"自动更新设备状态失败: {e}")
            db.session.rollback()
            raise
    
    @staticmethod
    def _calculate_device_status(device, current_date):
        """计算设备在当前日期的状态"""
        try:
            # 获取设备的所有租赁记录
            rentals = device.rentals.filter(
                Rental.status.in_(['pending', 'active', 'completed'])
            ).order_by(Rental.start_date).all()
            
            if not rentals:
                return 'idle'  # 没有租赁记录，状态为空闲
            
            # 查找当前日期相关的租赁记录
            current_rental = None
            next_rental = None
            
            for rental in rentals:
                # 检查是否是当前租赁
                if rental.start_date <= current_date <= rental.end_date:
                    current_rental = rental
                    break
                
                # 检查是否是下一个租赁
                if rental.start_date > current_date:
                    next_rental = rental
                    break
            
            # 规则1: 如果设备状态是空闲，且有下一单租赁，则改为待寄出
            if device.status == 'idle' and next_rental:
                # 检查是否到了寄出时间（租赁开始前1-2天）
                ship_out_date = next_rental.start_date - timedelta(days=1)
                if current_date >= ship_out_date:
                    return 'pending_ship'
            
            # 规则2: 如果设备状态是待寄出，且在租赁时间范围内，则改为租赁中
            if device.status == 'pending_ship' and current_rental:
                return 'renting'
            
            # 规则3: 如果设备处于租赁中，且到了租赁结束时间，则改为待寄回
            if device.status == 'renting' and current_rental:
                if current_date >= current_rental.end_date:
                    return 'pending_return'
            
            # 规则4: 如果设备状态是待寄回，且超过了寄回时间，则改为已寄回
            if device.status == 'pending_return':
                # 检查是否有寄回时间记录
                if current_rental and current_rental.ship_in_time:
                    ship_in_date = current_rental.ship_in_time.date()
                    if current_date > ship_in_date:
                        return 'returned'
                else:
                    # 没有寄回时间记录，按默认逻辑处理
                    if current_rental and current_date > current_rental.end_date + timedelta(days=2):
                        return 'returned'
            
            # 规则5: 如果设备状态是已寄回，且没有下一单租赁，则改为空闲
            if device.status == 'returned' and not next_rental:
                return 'idle'
            
            # 如果没有触发任何规则，保持当前状态
            return device.status
            
        except Exception as e:
            logger.error(f"计算设备 {device.id} 状态时出错: {e}")
            return device.status  # 出错时保持当前状态
    
    @staticmethod
    def get_device_status_summary():
        """获取设备状态统计"""
        try:
            status_counts = db.session.query(
                Device.status, 
                db.func.count(Device.id)
            ).group_by(Device.status).all()
            
            summary = {}
            for status, count in status_counts:
                summary[status] = count
            
            return summary
            
        except Exception as e:
            logger.error(f"获取设备状态统计失败: {e}")
            return {}
    
    @staticmethod
    def force_update_device_status(device_id):
        """强制更新指定设备的状态"""
        try:
            device = Device.query.get(device_id)
            if not device:
                return False, "设备不存在"
            
            today = date.today()
            old_status = device.status
            new_status = DeviceStatusService._calculate_device_status(device, today)
            
            if new_status != old_status:
                device.status = new_status
                device.updated_at = datetime.utcnow()
                db.session.commit()
                
                logger.info(f"强制更新设备 {device.name} (ID: {device_id}) 状态从 {old_status} 更新为 {new_status}")
                return True, f"状态已从 {old_status} 更新为 {new_status}"
            else:
                return True, f"状态无需更新，当前状态: {old_status}"
                
        except Exception as e:
            logger.error(f"强制更新设备状态失败: {e}")
            db.session.rollback()
            return False, f"更新失败: {str(e)}"
