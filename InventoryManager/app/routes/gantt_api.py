"""
甘特图相关API模块
"""

from flask import Blueprint, request, jsonify, current_app
from app.models.rental import Rental
from app.models.device import Device
from app.services.rental_service import RentalService
from app import db
from app.utils.date_utils import (
    parse_date_strings,
    validate_date_range,
    convert_dates_to_datetime,
    create_error_response,
    create_success_response
)
from datetime import datetime, date, timedelta

bp = Blueprint('gantt_api', __name__)


@bp.route('/api/gantt/data')
def gantt_data():
    """获取甘特图数据"""
    try:
        # 获取查询参数
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        # 解析日期参数
        if not start_date_str or not end_date_str:
            today = date.today()
            start_date = today.replace(day=1)
            if today.month == 12:
                end_date = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end_date = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        else:
            try:
                start_date, end_date = parse_date_strings(start_date_str, end_date_str)
            except ValueError as e:
                return create_error_response(str(e)), 400
        
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
            # 获取子租赁（附件）信息
            child_rentals = Rental.query.filter_by(parent_rental_id=rental.id).all()
            accessories_info = []

            for child_rental in child_rentals:
                if child_rental.device:
                    accessories_info.append({
                        'id': child_rental.device.id,
                        'name': child_rental.device.name,
                        'model': child_rental.device.model or '',
                        'is_accessory': child_rental.device.is_accessory
                    })

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
                'accessories': accessories_info  # 新增附件信息
            }
            gantt_data['rentals'].append(rental_data)
        
        return jsonify({
            'success': True,
            'data': gantt_data
        })
        
    except Exception as e:
        current_app.logger.error(f"获取甘特图数据失败: {e}")
        return jsonify({
            'success': False,
            'error': '获取数据失败',
            'message': str(e)
        }), 500


@bp.route('/api/rentals/find-slot', methods=['POST'])
def find_rental_slot():
    """查找可用的租赁时间段"""
    try:
        data = request.get_json()
        
        # 验证必填字段
        required_fields = ['start_date', 'end_date', 'logistics_days', 'model','is_accessory']
        for field in required_fields:
            if not data.get(field):
                return create_error_response(f'缺少必填字段: {field}'), 400
        
        # 解析日期
        try:
            start_date, end_date = parse_date_strings(data['start_date'], data['end_date'])
        except ValueError as e:
            return create_error_response(str(e)), 400
        
        logistics_days = int(data['logistics_days'])
        model = data['model']
        is_accessory = data.get('is_accessory', False)
        
        # 验证日期范围（允许相同日期，因为这是租赁时间）
        validation_error = validate_date_range(start_date, end_date, allow_same_date=True)
        if validation_error:
            return create_error_response(validation_error), 400
        
        # 计算寄出时间和收回时间
        ship_out_date = start_date - timedelta(days=1 + logistics_days)
        ship_in_date = end_date + timedelta(days=1 + logistics_days)
        current_app.logger.info(f"find_rental_slot: start_date: {start_date}, end_date: {end_date}, logistics_days: {logistics_days}, ship_out_date: {ship_out_date}, ship_in_date: {ship_in_date}, model: {model}")
        
        current_app.logger.info(f"开始查找可用档期")
        print(f"find available slot parameters: {ship_out_date}, {ship_in_date}, {model}, {is_accessory}")
        # 查找指定型号的可用档期
        available_slot = find_available_time_slot(ship_out_date, ship_in_date, model, is_accessory)
        print(f"available_slot: {available_slot}")
        
        if available_slot:
            # 获取第一个可用设备的详细信息
            first_device = None
            if available_slot['available_devices']:
                from app.models.device import Device
                first_device = Device.query.get(available_slot['available_devices'][0])

            # 构建响应消息
            message_parts = [f'找到 {available_slot["total_available"]} 台 {model} 型号的可用设备']
            if available_slot.get('available_accessories'):
                accessory_count = len(available_slot['available_accessories'])
                message_parts.append(f'{accessory_count} 个相关附件')

            return create_success_response({
                'is_accessory': is_accessory,
                'ship_out_date': ship_out_date.isoformat(),
                'ship_in_date': ship_in_date.isoformat(),
                'available_devices': available_slot['available_devices'],
                'total_available': available_slot['total_available'],
                'available_accessories': available_slot.get('available_accessories', []),
                'device_model': available_slot.get('device_model'),
                'device': first_device.to_dict() if first_device else None
            }, message='，'.join(message_parts)), 200
        else:
            return create_error_response(f'在指定时间段内没有可用的 {model} 型号设备档期'), 404
            
    except Exception as e:
        current_app.logger.error(f"查找租赁档期失败: {e}")
        return create_error_response('查找档期失败'), 500


def find_available_time_slot(ship_out_date, ship_in_date, model_filter, is_accessory=False):
    """
    查找指定型号设备的可用档期

    Args:
        ship_out_date: 寄出日期
        ship_in_date: 收回日期
        model_filter: 设备型号过滤条件，支持型号名称或display_name

    Returns:
        dict: 包含可用设备信息和相关附件的字典，如果没有可用设备返回None
    """
    try:
        from app.services.inventory_service import InventoryService
        from app.utils.date_utils import convert_dates_to_datetime
        from app.models.device_model import DeviceModel, ModelAccessory

        # 转换时间用于查询
        ship_out_time, ship_in_time = convert_dates_to_datetime(
            ship_out_date,
            ship_in_date,
            ship_out_hour="19:00:00",
            ship_in_hour="12:00:00"
        )

        # 直接通过 model_id 查找设备
        model_id = int(model_filter)  # model_filter 应该是 model_id
        devices = Device.query.filter(
            Device.model_id == model_id,
            Device.is_accessory == is_accessory
        ).all()

        device_type = "附件" if is_accessory else "主设备"
        current_app.logger.info(f"查找{device_type} model_id={model_id}, 找到 {len(devices)} 台设备")

        # 检查设备可用性
        available_devices = []
        for device in devices:
            availability = InventoryService.check_device_availability(
                device.id, ship_out_time, ship_in_time
            )
            print(f"find available slot availability: {availability}")
            if availability['available']:
                available_devices.append(device.id)
        # 返回结果
        if available_devices:
            result = {
                'available_devices': available_devices,
                'total_available': len(available_devices),
                'available_accessories': [],
                'device_model': None
            }
            current_app.logger.info(f"找到可用档期: {len(available_devices)}台{device_type}")
            return result
        else:
            return None

    except Exception as e:
        current_app.logger.error(f"查找可用档期失败: {e}")
        return None


@bp.route('/api/gantt/daily-stats')
def get_daily_stats():
    """获取每日统计信息"""
    try:
        # 获取查询参数
        date_str = request.args.get('date')
        device_model = request.args.get('device_model')  # 新增设备型号筛选参数

        if date_str:
            try:
                target_date = datetime.strptime(date_str, '%Y-%m-%d').date()
            except ValueError:
                return create_error_response('日期格式错误，请使用YYYY-MM-DD格式'), 400
        else:
            target_date = date.today()

        # 计算指定日期空闲设备数量（不在任何租赁的shipouttime到shipintime时间范围内）
        from app.services.inventory_service import InventoryService

        # 将目标日期转换为时间段（当天00:00到23:59）
        target_start = datetime.combine(target_date, datetime.min.time())
        target_end = datetime.combine(target_date, datetime.max.time())

        # 查询在目标日期这一天不被任何租赁物流时间占用的设备
        available_devices = InventoryService.get_available_devices(target_start, target_end)

        # 如果指定了设备型号，筛选对应型号的设备
        if device_model:
            # 从设备模型显示名称获取可用设备
            from app.models.device_model import DeviceModel
            model_obj = DeviceModel.query.filter_by(display_name=device_model).first()
            if model_obj:
                # 筛选指定型号的可用设备
                available_devices = [dev for dev in available_devices if dev.model_id == model_obj.id]
                current_app.logger.debug(f"筛选型号{device_model}(id={model_obj.id})后的可用设备数量: {len(available_devices)}")
            else:
                # 如果找不到对应的设备型号，返回空结果
                available_devices = []
                current_app.logger.debug(f"未找到设备型号{device_model}")

        available_count = len(available_devices)

        # 计算待寄出设备数量，分别统计主设备和附件设备
        # 算法：有多少rental的shipouttime的日期部分是当天且状态为未发货（使用系统时区）
        rentals_with_ship_out = Rental.query.filter(
            db.and_(
                Rental.ship_out_time.isnot(None),
                Rental.status == 'not_shipped'  # 只统计未发货的
            )
        ).all()

        main_device_ship_out_count = 0  # 主设备寄出数量（x 寄）
        accessory_ship_out_count = 0    # 附件寄出数量（x 附寄）

        for rental in rentals_with_ship_out:
            if rental.ship_out_time:
                # 直接比较日期部分（假设数据库存储的是UTC时间）
                rental_ship_date = rental.ship_out_time.date()
                if rental_ship_date == target_date:
                    # 根据设备类型分别统计
                    if rental.device and rental.device.is_accessory:
                        # 对于附件设备，需要检查其主设备的型号是否匹配
                        if device_model and rental.parent_rental_id:
                            # 获取父租赁（主设备租赁）
                            parent_rental = Rental.query.get(rental.parent_rental_id)
                            if parent_rental and parent_rental.device:
                                # 检查主设备的型号是否匹配
                                if parent_rental.device.device_model and parent_rental.device.device_model.display_name != device_model:
                                    continue  # 跳过不匹配的主设备型号的附件
                        accessory_ship_out_count += 1
                        current_app.logger.debug(f"附件租赁{rental.id}在{target_date}寄出")
                    else:
                        # 对于主设备，直接检查设备型号
                        if device_model and rental.device:
                            if rental.device.device_model and rental.device.device_model.display_name != device_model:
                                continue  # 跳过不匹配的设备型号
                        main_device_ship_out_count += 1
                        current_app.logger.debug(f"主设备租赁{rental.id}在{target_date}寄出")

        current_app.logger.debug(f"日期{target_date}统计结果(型号筛选:{device_model}): 空闲={available_count}, 主设备寄出={main_device_ship_out_count}, 附件寄出={accessory_ship_out_count}")

        return create_success_response({
            'date': target_date.isoformat(),
            'available_count': available_count,
            'ship_out_count': main_device_ship_out_count,
            'accessory_ship_out_count': accessory_ship_out_count
        }), 200

    except Exception as e:
        current_app.logger.error(f"获取每日统计失败: {e}")
        return create_error_response('获取统计失败'), 500
