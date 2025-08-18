"""
库存管理服务
"""

from app.models import Device, Rental
from app import db
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple
import logging

logger = logging.getLogger(__name__)


class InventoryService:
    """库存管理服务"""
    
    @staticmethod
    def get_available_devices(start_date: date, end_date: date, 
                            device_type: str = None, location: str = None) -> List[Device]:
        """
        获取指定时间段可用的设备
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            device_type: 设备类型（可选）
            location: 设备位置（可选）
            
        Returns:
            List[Device]: 可用设备列表
        """
        try:
            # 基础查询：状态为可用的设备
            query = Device.query.filter(Device.status == 'available')
            
            # 按类型过滤
            if device_type:
                query = query.filter(Device.type == device_type)
            
            # 按位置过滤
            if location:
                query = query.filter(Device.location == location)
            
            # 获取所有符合条件的设备
            devices = query.all()
            
            # 过滤掉有时间冲突的设备
            available_devices = []
            for device in devices:
                if device.is_available(start_date, end_date):
                    available_devices.append(device)
            
            logger.info(f"查询到 {len(available_devices)} 台可用设备")
            return available_devices
            
        except Exception as e:
            logger.error(f"获取可用设备失败: {e}")
            return []
    
    @staticmethod
    def check_device_availability(device_id: str, start_date: date, 
                                end_date: date) -> Dict:
        """
        检查指定设备在指定时间段是否可用
        
        Args:
            device_id: 设备ID
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            Dict: 可用性检查结果
        """
        try:
            device = Device.query.get(device_id)
            if not device:
                return {
                    'available': False,
                    'reason': '设备不存在',
                    'device_id': device_id
                }
            
            # 检查设备状态
            if device.status != 'available':
                return {
                    'available': False,
                    'reason': f'设备状态为: {device.status}',
                    'device_id': device_id,
                    'device_status': device.status
                }
            
            # 检查时间冲突
            if device.is_available(start_date, end_date):
                return {
                    'available': True,
                    'device_id': device_id,
                    'device_info': device.to_dict()
                }
            else:
                # 获取冲突的租赁记录
                conflicting_rentals = Rental.query.filter(
                    db.and_(
                        Rental.device_id == device_id,
                        Rental.status == 'active',
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
                ).all()
                
                return {
                    'available': False,
                    'reason': '时间冲突',
                    'device_id': device_id,
                    'conflicting_rentals': [
                        {
                            'rental_id': rental.id,
                            'start_date': rental.start_date.isoformat(),
                            'end_date': rental.end_date.isoformat(),
                            'customer_name': rental.customer_name
                        }
                        for rental in conflicting_rentals
                    ]
                }
                
        except Exception as e:
            logger.error(f"检查设备可用性失败: {e}")
            return {
                'available': False,
                'reason': '系统错误',
                'error': str(e)
            }
    
    @staticmethod
    def get_device_schedule(device_id: str, start_date: date = None, 
                           end_date: date = None) -> Dict:
        """
        获取设备的档期信息
        
        Args:
            device_id: 设备ID
            start_date: 开始日期（可选，默认30天前）
            end_date: 结束日期（可选，默认30天后）
            
        Returns:
            Dict: 设备档期信息
        """
        try:
            device = Device.query.get(device_id)
            if not device:
                return {
                    'success': False,
                    'error': '设备不存在'
                }
            
            # 设置默认日期范围
            if not start_date:
                start_date = date.today() - timedelta(days=30)
            if not end_date:
                end_date = date.today() + timedelta(days=30)
            
            # 获取指定时间范围内的租赁记录
            rentals = Rental.query.filter(
                db.and_(
                    Rental.device_id == device_id,
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
            ).order_by(Rental.start_date).all()
            
            # 构建档期数据
            schedule_data = []
            for rental in rentals:
                schedule_data.append({
                    'rental_id': rental.id,
                    'start_date': rental.start_date.isoformat(),
                    'end_date': rental.end_date.isoformat(),
                    'customer_name': rental.customer_name,
                    'purpose': rental.purpose,
                    'status': rental.status,
                    'daily_rate': float(rental.daily_rate) if rental.daily_rate else None,
                    'total_cost': float(rental.total_cost) if rental.total_cost else None
                })
            
            return {
                'success': True,
                'device_info': device.to_dict(),
                'schedule': schedule_data,
                'date_range': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                },
                'total_rentals': len(schedule_data)
            }
            
        except Exception as e:
            logger.error(f"获取设备档期失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod
    def get_inventory_summary() -> Dict:
        """
        获取库存摘要信息
        
        Returns:
            Dict: 库存摘要
        """
        try:
            # 设备统计
            device_stats = Device.get_device_count_by_status()
            device_type_stats = Device.get_device_count_by_type()
            
            # 租赁统计
            today = date.today()
            active_rentals = Rental.query.filter(
                db.and_(
                    Rental.status == 'active',
                    Rental.start_date <= today,
                    Rental.end_date >= today
                )
            ).count()
            
            upcoming_rentals = Rental.query.filter(
                db.and_(
                    Rental.status == 'active',
                    Rental.start_date > today
                )
            ).count()
            
            overdue_rentals = Rental.query.filter(
                db.and_(
                    Rental.status == 'active',
                    Rental.end_date < today
                )
            ).count()
            
            return {
                'success': True,
                'summary': {
                    'devices': {
                        'total': sum(count for _, count in device_stats),
                        'by_status': {status: count for status, count in device_stats},
                        'by_type': {device_type: count for device_type, count in device_type_stats}
                    },
                    'rentals': {
                        'active': active_rentals,
                        'upcoming': upcoming_rentals,
                        'overdue': overdue_rentals
                    },
                    'last_updated': datetime.now().isoformat()
                }
            }
            
        except Exception as e:
            logger.error(f"获取库存摘要失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod
    def search_devices(keyword: str = None, device_type: str = None, 
                      status: str = None, location: str = None) -> List[Device]:
        """
        搜索设备
        
        Args:
            keyword: 搜索关键词（设备名称、型号、序列号）
            device_type: 设备类型
            status: 设备状态
            location: 设备位置
            
        Returns:
            List[Device]: 搜索结果
        """
        try:
            query = Device.query
            
            # 关键词搜索
            if keyword:
                query = query.filter(
                    db.or_(
                        Device.name.contains(keyword),
                        Device.model.contains(keyword),
                        Device.serial_number.contains(keyword),
                        Device.brand.contains(keyword)
                    )
                )
            
            # 类型过滤
            if device_type:
                query = query.filter(Device.type == device_type)
            
            # 状态过滤
            if status:
                query = query.filter(Device.status == status)
            
            # 位置过滤
            if location:
                query = query.filter(Device.location == location)
            
            devices = query.all()
            logger.info(f"搜索到 {len(devices)} 台设备")
            return devices
            
        except Exception as e:
            logger.error(f"搜索设备失败: {e}")
            return []
    
    @staticmethod
    def get_device_utilization(device_id: str, start_date: date, 
                              end_date: date) -> Dict:
        """
        获取设备利用率
        
        Args:
            device_id: 设备ID
            start_date: 开始日期
            end_date: 结束日期
            
        Returns:
            Dict: 设备利用率信息
        """
        try:
            device = Device.query.get(device_id)
            if not device:
                return {
                    'success': False,
                    'error': '设备不存在'
                }
            
            # 计算总天数
            total_days = (end_date - start_date).days + 1
            
            # 获取租赁天数
            rental_days = db.session.query(
                db.func.sum(
                    db.func.greatest(
                        0,
                        db.func.least(
                            Rental.end_date,
                            end_date
                        ) - db.func.greatest(
                            Rental.start_date,
                            start_date
                        ) + 1
                    )
                )
            ).filter(
                db.and_(
                    Rental.device_id == device_id,
                    Rental.status == 'active',
                    db.or_(
                        db.and_(
                            Rental.start_date <= end_date,
                            Rental.end_date >= start_date
                        )
                    )
                )
            ).scalar() or 0
            
            utilization_rate = (rental_days / total_days) * 100 if total_days > 0 else 0
            
            return {
                'success': True,
                'device_id': device_id,
                'period': {
                    'start_date': start_date.isoformat(),
                    'end_date': end_date.isoformat(),
                    'total_days': total_days
                },
                'utilization': {
                    'rental_days': rental_days,
                    'available_days': total_days - rental_days,
                    'utilization_rate': round(utilization_rate, 2)
                }
            }
            
        except Exception as e:
            logger.error(f"获取设备利用率失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
    
    @staticmethod
    def export_inventory_report(start_date: date = None, end_date: date = None) -> Dict:
        """
        导出库存报告
        
        Args:
            start_date: 开始日期（可选）
            end_date: 结束日期（可选）
            
        Returns:
            Dict: 库存报告数据
        """
        try:
            # 获取所有设备
            devices = Device.query.all()
            
            # 获取租赁记录
            rental_query = Rental.query
            if start_date and end_date:
                rental_query = rental_query.filter(
                    db.and_(
                        Rental.start_date >= start_date,
                        Rental.end_date <= end_date
                    )
                )
            
            rentals = rental_query.all()
            
            # 构建报告数据
            report_data = {
                'export_time': datetime.now().isoformat(),
                'period': {
                    'start_date': start_date.isoformat() if start_date else None,
                    'end_date': end_date.isoformat() if end_date else None
                },
                'devices': [device.to_dict() for device in devices],
                'rentals': [rental.to_dict() for rental in rentals],
                'summary': {
                    'total_devices': len(devices),
                    'total_rentals': len(rentals),
                    'device_types': Device.get_device_count_by_type(),
                    'device_status': Device.get_device_count_by_status()
                }
            }
            
            return {
                'success': True,
                'data': report_data
            }
            
        except Exception as e:
            logger.error(f"导出库存报告失败: {e}")
            return {
                'success': False,
                'error': str(e)
            }
