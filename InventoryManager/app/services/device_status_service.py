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
        """计算设备在当前日期的状态 - 简化版只返回在线或离线"""
        try:
            # 简化版：设备默认在线，只有显式设置才会离线
            # 这里可以根据业务需求添加判断逻辑，比如：
            # - 设备长时间无租赁可设为离线
            # - 设备故障时设为离线
            # - 设备维修时设为离线

            # 目前保持当前状态
            return device.status if device.status in ['online', 'offline'] else 'online'

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
