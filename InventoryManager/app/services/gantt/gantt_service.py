"""
甘特图业务逻辑服务层
"""

from datetime import datetime, date, timedelta
from flask import current_app
from app import db
from app.models.rental import Rental
from app.models.device import Device
from app.services.inventory_service import InventoryService
from app.utils.date_utils import (
    parse_date_strings,
    validate_date_range,
    convert_dates_to_datetime,
)
from app.models.device_model import DeviceModel


class GanttService:
    """甘特图服务类"""

    @staticmethod
    def get_gantt_data(start_date_str=None, end_date_str=None) -> dict:
        """获取甘特图数据
        
        Args:
            start_date_str: 开始日期字符串 (YYYY-MM-DD格式)
            end_date_str: 结束日期字符串 (YYYY-MM-DD格式)
        
        Returns:
            dict: 包含设备、租赁和日期范围的甘特图数据
        """
        try:
            # 解析日期参数，如果未提供则使用当前月份
            if not start_date_str or not end_date_str:
                today = date.today()
                start_date = today.replace(day=1)
                if today.month == 12:
                    end_date = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
                else:
                    end_date = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
            else:
                start_date, end_date = parse_date_strings(start_date_str, end_date_str)

            # 获取所有非附件设备（甘特图不显示附件）
            devices = Device.query.filter(Device.is_accessory.is_(False)).all()

            # 获取指定时间范围内的租赁记录（只包括主租赁记录，用于甘特图显示）
            rentals = Rental.query.filter(
                Rental.status != 'cancelled',
                Rental.parent_rental_id.is_(None),  # 只显示主租赁记录
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
            ).all()

            # 构建甘特图数据
            gantt_data = {
                'devices': [],
                'rentals': [],
                'date_range': {
                    'start': start_date.isoformat(),
                    'end': end_date.isoformat()
                },
                'today': date.today().isoformat()
            }

            # 处理设备数据
            for device in devices:
                device_data = {
                    'id': device.id,
                    'name': device.name,
                    'serial_number': device.serial_number,
                    'model': getattr(device, 'model', 'x200u'),  # 默认值防止旧数据报错
                    'model_id': device.model_id,
                    'device_model': device.device_model.to_dict() if device.device_model else None,
                    'is_accessory': getattr(device, 'is_accessory', False),  # 默认值防止旧数据报错
                    'status': device.status,
                    'lifecycle_status': device.lifecycle_status,
                    'lifecycle_reason': device.lifecycle_reason,
                    'lifecycle_date': device.lifecycle_date.isoformat() if device.lifecycle_date else None,
                    'rentals': []
                }

                # 处理该设备的租赁记录
                device_rentals = [r for r in rentals if r.device_id == device.id]
                for rental in device_rentals:
                    rental_data = {
                        'id': rental.id,
                        'start_date': rental.start_date.isoformat(),
                        'end_date': rental.end_date.isoformat(),
                        'customer_name': rental.customer_name,
                        'customer_phone': rental.customer_phone,
                        'destination': rental.destination,
                        'ship_out_tracking_no': rental.ship_out_tracking_no,
                        'ship_in_tracking_no': rental.ship_in_tracking_no,
                        'status': rental.status,
                        'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                        'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None
                    }
                    device_data['rentals'].append(rental_data)

                gantt_data['devices'].append(device_data)

            # 处理所有租赁记录
            for rental in rentals:
                # 使用新的统一方法获取所有附件信息（包括配套和库存附件）
                accessories_info = rental.get_all_accessories_for_display()

                rental_data = {
                    'id': rental.id,
                    'device_id': rental.device_id,
                    'device_name': rental.device.name if rental.device else 'Unknown',
                    'start_date': rental.start_date.isoformat(),
                    'end_date': rental.end_date.isoformat(),
                    'customer_name': rental.customer_name,
                    'customer_phone': rental.customer_phone,
                    'destination': rental.destination,
                    'ship_out_tracking_no': rental.ship_out_tracking_no,
                    'ship_in_tracking_no': rental.ship_in_tracking_no,
                    'status': rental.status,
                    'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                    'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None,
                    'accessories': accessories_info  # 包含is_bundled标记的附件信息
                }
                gantt_data['rentals'].append(rental_data)

            return gantt_data

        except Exception as e:
            current_app.logger.error(f"获取甘特图数据失败: {e}")
            raise

    @staticmethod
    def get_daily_statistics(date_str=None, device_model=None) -> dict:
        """获取每日统计信息
        
        Args:
            date_str: 目标日期字符串 (YYYY-MM-DD格式)，不提供则使用今天
            device_model: 设备型号显示名称（可选，用于筛选）
        
        Returns:
            dict: 包含空闲设备数、待寄出数等统计信息
        """
        try:
            # 解析目标日期
            if date_str:
                try:
                    target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                except ValueError:
                    raise ValueError('日期格式错误，请使用YYYY-MM-DD格式')
            else:
                target_date = date.today()

            # 计算指定日期空闲设备数量
            target_start = datetime.combine(target_date, datetime.min.time())
            target_end = datetime.combine(target_date, datetime.max.time())

            # 查询在目标日期这一天不被任何租赁物流时间占用的设备
            available_devices = InventoryService.get_available_devices(target_start, target_end)

            # 如果指定了设备型号，筛选对应型号的设备
            if device_model:
                model_obj = DeviceModel.query.filter_by(display_name=device_model).first()
                if model_obj:
                    available_devices = [dev for dev in available_devices if dev.model_id == model_obj.id]
                    current_app.logger.debug(f"筛选型号{device_model}(id={model_obj.id})后的可用设备数量: {len(available_devices)}")
                else:
                    available_devices = []
                    current_app.logger.debug(f"未找到设备型号{device_model}")

            available_count = len(available_devices)

            # 计算待寄出设备数量
            rentals_with_ship_out = Rental.query.filter(
                db.and_(
                    Rental.ship_out_time.isnot(None),
                    Rental.status.in_(['not_shipped', 'scheduled_for_shipping'])
                )
            ).all()

            main_device_ship_out_count = 0
            accessory_ship_out_count = 0

            for rental in rentals_with_ship_out:
                if rental.ship_out_time:
                    rental_ship_date = rental.ship_out_time.date()
                    if rental_ship_date == target_date:
                        # 根据设备类型分别统计
                        if rental.device and rental.device.is_accessory:
                            if device_model and rental.parent_rental_id:
                                parent_rental = Rental.query.get(rental.parent_rental_id)
                                if parent_rental and parent_rental.device:
                                    if parent_rental.device.device_model and \
                                       parent_rental.device.device_model.display_name != device_model:
                                        continue
                            accessory_ship_out_count += 1
                            current_app.logger.debug(f"附件租赁{rental.id}在{target_date}寄出")
                        else:
                            if device_model and rental.device:
                                if rental.device.device_model and \
                                   rental.device.device_model.display_name != device_model:
                                    continue
                            main_device_ship_out_count += 1
                            current_app.logger.debug(f"主设备租赁{rental.id}在{target_date}寄出")

            current_app.logger.debug(
                f"日期{target_date}统计结果(型号筛选:{device_model}): "
                f"空闲={available_count}, 主设备寄出={main_device_ship_out_count}, 附件寄出={accessory_ship_out_count}"
            )

            return {
                'date': target_date.isoformat(),
                'available_count': available_count,
                'ship_out_count': main_device_ship_out_count,
                'accessory_ship_out_count': accessory_ship_out_count
            }

        except Exception as e:
            current_app.logger.error(f"获取每日统计失败: {e}")
            raise

    @staticmethod
    def find_available_slot(start_date, end_date, logistics_days, model_filter, is_accessory=False) -> dict:
        """查找可用的租赁时间段
        
        Args:
            start_date: 租赁开始日期
            end_date: 租赁结束日期
            logistics_days: 物流天数
            model_filter: 设备型号过滤条件（可以是型号名称或model_id）
            is_accessory: 是否为附件
        
        Returns:
            dict: 包含可用设备和附件信息的字典
        """
        try:
            # 计算寄出时间和收回时间
            ship_out_date = start_date - timedelta(days=1 + logistics_days)
            ship_in_date = end_date + timedelta(days=1 + logistics_days)

            current_app.logger.info(
                f"find_rental_slot: start_date: {start_date}, end_date: {end_date}, "
                f"logistics_days: {logistics_days}, ship_out_date: {ship_out_date}, "
                f"ship_in_date: {ship_in_date}, model: {model_filter}"
            )

            # 转换时间用于查询
            ship_out_time, ship_in_time = convert_dates_to_datetime(
                ship_out_date,
                ship_in_date,
                ship_out_hour="19:00:00",
                ship_in_hour="12:00:00"
            )

            # 根据 model_filter 查找设备
            device_type = "附件" if is_accessory else "主设备"

            devices_query = Device.in_service_query(is_accessory=is_accessory)

            if model_filter and str(model_filter).strip():
                try:
                    model_id = int(model_filter)
                    devices = devices_query.filter(Device.model_id == model_id).all()
                    current_app.logger.info(f"查找{device_type} model_id={model_id}, 找到 {len(devices)} 台设备")
                except (TypeError, ValueError):
                    current_app.logger.error(f"无效的 model_id: {model_filter}")
                    return None
            else:
                devices = devices_query.all()
                current_app.logger.info(f"查找所有{device_type}, 找到 {len(devices)} 台设备")

            # 检查设备可用性
            available_devices = []
            available_device_objects = []
            for device in devices:
                availability = InventoryService.check_device_availability(
                    device.id, ship_out_time, ship_in_time
                )
                if availability['available']:
                    available_devices.append(device.id)
                    available_device_objects.append(device)

            # 返回结果
            if available_devices:
                # 获取第一个可用设备的详细信息
                first_device = Device.query.get(available_devices[0])
                
                message_parts = [f'找到 {len(available_devices)} 台 {model_filter} 型号的可用设备']
                
                result = {
                    'is_accessory': is_accessory,
                    'ship_out_date': ship_out_date.isoformat(),
                    'ship_in_date': ship_in_date.isoformat(),
                    'available_devices': [d.to_dict() for d in available_device_objects],
                    'total_available': len(available_devices),
                    'available_accessories': [],
                    'device_model': None,
                    'device': first_device.to_dict() if first_device else None,
                    'message': '，'.join(message_parts)
                }
                current_app.logger.info(f"找到可用档期: {len(available_devices)}台{device_type}")
                return result
            else:
                current_app.logger.info(f"未找到可用档期: {device_type}")
                return None

        except Exception as e:
            current_app.logger.error(f"查找可用档期失败: {e}")
            raise
