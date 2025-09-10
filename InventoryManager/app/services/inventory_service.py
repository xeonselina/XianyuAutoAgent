"""
库存管理服务
"""

from app.models import Device, Rental
from app import db
from datetime import datetime, date, timedelta
from typing import List, Dict, Optional, Tuple, Union
from app.utils.date_utils import convert_dates_to_datetime
import logging

logger = logging.getLogger(__name__)


class InventoryService:
    """库存管理服务"""
    
    @staticmethod
    def get_available_devices(ship_out_time: datetime, ship_in_time: datetime) -> List[Device]:
        """
        获取指定时间段内可用的设备
        
        Args:
            ship_out_time: 寄出时间
            ship_in_time: 收回时间
            
        Returns:
            List[Device]: 可用设备列表，按优选策略排序
        """
        try:
            from app.models.rental import Rental
            
            logger.info(f"calc available devices: ship_out_time: {ship_out_time}, ship_in_time: {ship_in_time}")
            
            # 获取所有非附件设备（过滤掉手柄等附件）
            all_devices = Device.query.filter(Device.is_accessory.is_(False)).all()
            available_devices = []
            
            for device in all_devices:
                # 只排除离线状态的设备
                if device.status == 'offline':
                    continue
                
                # 检查设备在指定时间段内是否有冲突的租赁记录
                conflicting_rentals = Rental.query.filter(
                    db.and_(
                        Rental.device_id == device.id,
                        Rental.status.in_(['pending', 'active', 'completed']),  # 不包括取消的租赁
                        Rental.ship_out_time.isnot(None),  # 必须有寄出时间
                        Rental.ship_in_time.isnot(None),   # 必须有收回时间
                        # 检查时间段重叠：租赁的物流时间段与查询时间段重叠
                        db.and_(
                            Rental.ship_out_time < ship_in_time,   # 租赁寄出时间 < 查询收回时间
                            Rental.ship_in_time > ship_out_time    # 租赁收回时间 > 查询寄出时间
                        )
                    )
                ).all()
                
                if not conflicting_rentals:
                    # 没有冲突的租赁记录，设备可用
                    # 查找设备的最近一次完成的租赁记录用于排序
                    latest_completed_rental = Rental.query.filter(
                        db.and_(
                            Rental.device_id == device.id,
                            Rental.ship_in_time.isnot(None),
                            Rental.ship_in_time <= ship_out_time  # 已经完成的租赁
                        )
                    ).order_by(Rental.ship_in_time.desc()).first()
                    
                    if latest_completed_rental:
                        time_gap = (ship_out_time - latest_completed_rental.ship_in_time).total_seconds() / 3600
                    else:
                        time_gap = float('inf')  # 没有历史租赁记录
                    
                    available_devices.append({
                        'device': device,
                        'latest_rental': latest_completed_rental,
                        'time_gap': time_gap
                    })
            
            # 优选策略排序
            def sort_key(item):
                device = item['device']
                latest_rental = item['latest_rental']
                time_gap = item['time_gap']
                
                if latest_rental is None:
                    # 没有租赁记录的设备最优先
                    return (0, 0)
                
                # 时间差小于4小时的排在最后
                if time_gap < 4:
                    return (3, time_gap)
                
                # 时间差接近但不小于4小时的优先（4-24小时）
                if 4 <= time_gap <= 24:
                    return (1, -time_gap)  # 负数确保时间差小的排在前面
                
                # 时间差较大的排在中间
                return (2, time_gap)
            
            # 按优选策略排序
            available_devices.sort(key=sort_key)
            
            # 返回排序后的设备列表
            return [item['device'] for item in available_devices]
            
        except Exception as e:
            logger.error(f"获取可用设备失败: {e}")
            return []
    
    @staticmethod
    def check_device_availability(device_id: str, ship_out_time: datetime, 
                                ship_in_time: datetime, exclude_rental_id: int = None) -> Dict:
        """
        检查指定设备在指定寄出和收回时间段是否可用
        
        Args:
            device_id: 设备ID
            ship_out_time: 寄出时间
            ship_in_time: 收回时间
            exclude_rental_id: 要排除的租赁记录ID（用于编辑租赁时）
            
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
            
            # 根据用户要求，不检查设备状态，只检测档期冲突
            # if device.status != 'idle':
            #     return {
            #         'available': False,
            #         'reason': f'设备当前状态为 {device.status}，不可预定',
            #         'device_id': device_id,
            #         'device_status': device.status
            #     }
            
            # 检查寄出和收回时间冲突（使用寄出收回时间而不是租赁时间）
            # 查找在指定寄出收回时间段内有冲突的租赁记录
            query_filters = [
                Rental.device_id == device_id,
                Rental.status.in_(['pending', 'confirmed', 'shipped', 'returned']),  # 排除已取消的
                Rental.ship_out_time.isnot(None),  # 必须有寄出时间
                Rental.ship_in_time.isnot(None),   # 必须有收回时间
                # 时间段重叠检测：寄出时间和收回时间有交叉
                db.and_(
                    Rental.ship_out_time < ship_in_time,   # 现有记录的寄出时间 < 新记录的收回时间
                    Rental.ship_in_time > ship_out_time    # 现有记录的收回时间 > 新记录的寄出时间
                )
            ]
            
            # 如果提供了要排除的租赁记录ID，则排除该记录
            if exclude_rental_id:
                query_filters.append(Rental.id != exclude_rental_id)
            
            conflicting_rentals = Rental.query.filter(
                db.and_(*query_filters)
            ).all()
            
            if not conflicting_rentals:
                return {
                    'available': True,
                    'device_id': device_id,
                    'device_info': device.to_dict()
                }
            else:
                return {
                    'available': False,
                    'reason': '设备在指定寄出收回时间段内已被占用',
                    'device_id': device_id,
                    'conflicting_rentals': [
                        {
                            'rental_id': rental.id,
                            'start_date': rental.start_date.isoformat(),
                            'end_date': rental.end_date.isoformat(),
                            'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                            'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None,
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
                    'destination': rental.destination,
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
            
            # 按位置统计设备（使用实际存在的字段）
            # location字段已移除，跳过位置统计
            location_stats = []
            
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
                        'by_location': {}  # location字段已移除
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
    def search_devices(keyword: str = None, status: str = None,
                      location: str = None) -> List[Device]:  # location已废弃，保留参数兼容性
        """
        搜索设备
        
        Args:
            keyword: 搜索关键词（设备名称或序列号）
            status: 设备状态
            location: 设备位置（已废弃）
            
        Returns:
            List[Device]: 设备列表
        """
        try:
            query = Device.query
            
            # 关键词搜索
            if keyword:
                query = query.filter(
                    db.or_(
                        Device.name.contains(keyword),
                        Device.serial_number.contains(keyword)
                    )
                )
            
            # 状态过滤
            if status:
                query = query.filter(Device.status == status)
            
            # 位置过滤
            # location字段已移除，忽略位置过滤
            # if location:
            #     query = query.filter(Device.location == location)
            
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
                    'device_locations': [],  # location字段已移除
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

    @staticmethod
    def query_available_inventory(start_date: date, end_date: date, 
                                device_type: str = None) -> List[Dict]:
        """
        通用库存查询方法
        
        Args:
            start_date: 开始日期
            end_date: 结束日期
            device_type: 设备类型过滤（可选）
            
        Returns:
            List[Dict]: 可用设备列表，每个设备包含id和详细信息
        """
        try:
            # 转换为datetime对象进行查询
            ship_out_time, ship_in_time = convert_dates_to_datetime(
                start_date, 
                end_date, 
                ship_out_hour="19:00:00",  # 使用最小时间
                ship_in_hour="12:00:00"    # 使用最大时间
            )
            
            # 查询可用设备（使用新的参数类型）
            available_devices = InventoryService.get_available_devices(ship_out_time, ship_in_time)
            logger.info(f"查询到 {available_devices} 可用设备")
            
            # 按设备类型过滤（如果指定）
            if device_type:
                available_devices = [d for d in available_devices if device_type.lower() in d.name.lower()]
            
            # 返回统一的设备信息格式
            response_data = []
            for device in available_devices:
                device_info = {
                    'id': device.id,
                    'name': device.name,
                    'serial_number': device.serial_number,
                    'status': device.status,
                    'location': None  # location字段已移除
                }
                response_data.append(device_info)
            
            return response_data
                
        except Exception as e:
            logger.error(f"查询可用库存失败: {e}")
            return []
