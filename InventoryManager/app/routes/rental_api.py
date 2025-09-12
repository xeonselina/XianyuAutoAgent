"""
租赁相关API模块
"""

from flask import Blueprint, request, jsonify, current_app
from app.models.device import Device
from app.models.rental import Rental
# RentalAccessory 模型已废弃，新架构中附件租赁直接作为Rental记录
from app.services.rental_service import RentalService
from app import db
from datetime import datetime, date, timedelta
import re

bp = Blueprint('rental_api', __name__)


@bp.route('/api/rentals')
def get_rentals():
    """获取租赁记录列表"""
    try:
        rentals = Rental.query.order_by(Rental.created_at.desc()).all()
        rental_list = []
        
        for rental in rentals:
            rental_info = {
                'id': rental.id,
                'device_id': rental.device_id,
                'device_name': rental.device.name if rental.device else 'Unknown',
                'start_date': rental.start_date.isoformat(),
                'end_date': rental.end_date.isoformat(),
                'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None,
                'customer_name': rental.customer_name,
                'customer_phone': rental.customer_phone,
                'destination': rental.destination,
                'status': rental.status,
                'created_at': rental.created_at.isoformat()
            }
            rental_list.append(rental_info)
        
        return jsonify({
            'success': True,
            'data': rental_list,
            'total': len(rental_list)
        })
        
    except Exception as e:
        current_app.logger.error(f"获取租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '获取租赁记录失败'
        }), 500


@bp.route('/api/rentals/<rental_id>')
def get_rental(rental_id):
    """获取单个租赁记录"""
    try:
        rental = Rental.query.get(rental_id)
        if not rental:
            return jsonify({
                'success': False,
                'error': '租赁记录不存在'
            }), 404
        
        # 获取附件信息（通过child_rentals获取）
        accessories_info = []
        for child_rental in rental.child_rentals:
            if child_rental.device:
                accessories_info.append({
                    'id': child_rental.device.id,
                    'name': child_rental.device.name,
                    'model': child_rental.device.model,
                    'is_accessory': child_rental.device.is_accessory,
                    'rental_id': child_rental.id
                })

        rental_info = {
            'id': rental.id,
            'device_id': rental.device_id,
            'device_name': rental.device.name if rental.device else 'Unknown',
            'start_date': rental.start_date.isoformat(),
            'end_date': rental.end_date.isoformat(),
            'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
            'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None,
            'customer_name': rental.customer_name,
            'customer_phone': rental.customer_phone,
            'destination': rental.destination,
            'ship_out_tracking_no': rental.ship_out_tracking_no,
            'ship_in_tracking_no': rental.ship_in_tracking_no,
            'status': rental.status,
            'created_at': rental.created_at.isoformat(),
            'accessories': accessories_info
        }
        
        return jsonify({
            'success': True,
            'data': rental_info
        })
        
    except Exception as e:
        current_app.logger.error(f"获取租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '获取租赁记录失败'
        }), 500


@bp.route('/api/rentals', methods=['POST'])
def create_rental():
    """创建租赁记录"""
    try:
        data = request.get_json()
        
        # 添加调试日志 - 打印接收到的所有数据
        current_app.logger.info(f"=== 创建租赁 - 接收到的原始数据 ===")
        current_app.logger.info(f"完整数据: {data}")
        current_app.logger.info(f"ship_out_time 原始值: {data.get('ship_out_time')}")
        current_app.logger.info(f"ship_in_time 原始值: {data.get('ship_in_time')}")
        current_app.logger.info(f"数据类型 - ship_out_time: {type(data.get('ship_out_time'))}")
        current_app.logger.info(f"数据类型 - ship_in_time: {type(data.get('ship_in_time'))}")
        
        # 验证必填字段 (客户电话和地址设为非必填)
        required_fields = ['device_id', 'start_date', 'end_date', 'customer_name']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'error': f'缺少必填字段: {field}'
                }), 400
        
        # 验证设备是否存在
        device = Device.query.get(data['device_id'])
        if not device:
            return jsonify({
                'success': False,
                'error': '设备不存在'
            }), 400
        
        # 解析日期
        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        
        # 检查设备在指定时间段是否可用
        from app.services.inventory_service import InventoryService
        start_time = datetime.combine(start_date, datetime.min.time())
        end_time = datetime.combine(end_date, datetime.max.time())
        
        # 检查是否强制创建
        force_create = data.get('force_create', False)
        
        if not force_create:
            # 非强制创建时检查档期冲突（包括设备状态和时间冲突）
            availability_check = InventoryService.check_device_availability(data['device_id'], start_time, end_time)
            if not availability_check['available']:
                return jsonify({
                    'success': False,
                    'error': f'档期冲突: {availability_check["reason"]}'
                }), 400
        
        # 提取手机号
        customer_phone = None
        if data.get('destination'):
            phone_match = re.search(r'1[3-9]\d{9}', data['destination'])
            if phone_match:
                customer_phone = phone_match.group()
        
        # 处理寄出和收回时间
        ship_out_time = None
        ship_in_time = None
        
        current_app.logger.info(f"=== 开始处理时间字段 ===")
        
        if data.get('ship_out_time'):
            current_app.logger.info(f"处理 ship_out_time: {data['ship_out_time']}")
            try:
                ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d %H:%M:%S')
                current_app.logger.info(f"ship_out_time 解析成功 (格式1): {ship_out_time}")
            except ValueError:
                current_app.logger.info(f"ship_out_time 格式1解析失败，尝试格式2")
                # 如果时间格式解析失败，尝试只解析日期
                try:
                    ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d')
                    current_app.logger.info(f"ship_out_time 解析成功 (格式2): {ship_out_time}")
                except ValueError:
                    current_app.logger.warning(f"无法解析寄出时间: {data['ship_out_time']}")
                    # 尝试ISO格式解析
                    try:
                        from dateutil import parser
                        ship_out_time = parser.isoparse(data['ship_out_time']).replace(tzinfo=None)
                        current_app.logger.info(f"ship_out_time 解析成功 (ISO格式): {ship_out_time}")
                    except:
                        current_app.logger.error(f"ship_out_time 所有格式解析都失败: {data['ship_out_time']}")
        else:
            current_app.logger.info("ship_out_time 为空或不存在")
        
        if data.get('ship_in_time'):
            current_app.logger.info(f"处理 ship_in_time: {data['ship_in_time']}")
            try:
                ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d %H:%M:%S')
                current_app.logger.info(f"ship_in_time 解析成功 (格式1): {ship_in_time}")
            except ValueError:
                current_app.logger.info(f"ship_in_time 格式1解析失败，尝试格式2")
                # 如果时间格式解析失败，尝试只解析日期
                try:
                    ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d')
                    current_app.logger.info(f"ship_in_time 解析成功 (格式2): {ship_in_time}")
                except ValueError:
                    current_app.logger.warning(f"无法解析收回时间: {data['ship_in_time']}")
                    # 尝试ISO格式解析
                    try:
                        from dateutil import parser
                        ship_in_time = parser.isoparse(data['ship_in_time']).replace(tzinfo=None)
                        current_app.logger.info(f"ship_in_time 解析成功 (ISO格式): {ship_in_time}")
                    except:
                        current_app.logger.error(f"ship_in_time 所有格式解析都失败: {data['ship_in_time']}")
        else:
            current_app.logger.info("ship_in_time 为空或不存在")
        
        # 创建主设备租赁记录
        current_app.logger.info(f"=== 创建主设备租赁记录 ===")
        current_app.logger.info(f"准备保存的 ship_out_time: {ship_out_time} (类型: {type(ship_out_time)})")
        current_app.logger.info(f"准备保存的 ship_in_time: {ship_in_time} (类型: {type(ship_in_time)})")
        
        # 主设备租赁记录（parent_rental_id 为 None）
        main_rental = Rental(
            device_id=data['device_id'],
            start_date=start_date,
            end_date=end_date,
            customer_name=data['customer_name'],
            customer_phone=customer_phone,
            destination=data.get('destination', ''),
            status='pending',
            ship_out_time=ship_out_time,
            ship_in_time=ship_in_time,
            parent_rental_id=None  # 主租赁
        )
        
        current_app.logger.info(f"主租赁对象创建后 - ship_out_time: {main_rental.ship_out_time}")
        current_app.logger.info(f"主租赁对象创建后 - ship_in_time: {main_rental.ship_in_time}")
        
        # 更新主设备状态（只有在非强制创建时才更新）
        if not force_create:
            device.status = 'renting'
        
        db.session.add(main_rental)
        current_app.logger.info("主租赁记录已添加到会话")
        
        # 为附件创建独立的租赁记录
        accessories_data = data.get('accessories', [])
        accessory_rentals = []
        accessories_added = []
        if accessories_data:
            current_app.logger.info(f"为附件创建租赁记录: {accessories_data}")
            for accessory_id in accessories_data:
                # 验证附件存在且是附件类型
                accessory_device = Device.query.get(accessory_id)
                if accessory_device and accessory_device.is_accessory:
                    # 检查附件在该时间段是否可用
                    if ship_out_time and ship_in_time:
                        from app.services.inventory_service import InventoryService
                        availability = InventoryService.check_device_availability(
                            accessory_id, ship_out_time, ship_in_time
                        )
                        if not availability['available'] and not force_create:
                            current_app.logger.warning(f"附件{accessory_id}不可用: {availability['reason']}")
                            continue
                    
                    # 为附件创建独立的租赁记录
                    accessory_rental = Rental(
                        device_id=accessory_id,
                        start_date=start_date,
                        end_date=end_date,
                        customer_name=data['customer_name'],
                        customer_phone=customer_phone,
                        destination=data.get('destination', ''),
                        status='pending',
                        ship_out_time=ship_out_time,
                        ship_in_time=ship_in_time,
                        parent_rental_id=None  # 先设置为None，之后更新
                    )
                    
                    accessory_rentals.append(accessory_rental)
                    db.session.add(accessory_rental)
                    
                    # 更新附件设备状态为租赁中
                    if not force_create:
                        accessory_device.status = 'renting'
                        current_app.logger.info(f"附件设备 {accessory_device.name} 状态更新为 renting")
                    
                    accessories_added.append(accessory_device.name)
                    current_app.logger.info(f"为附件创建租赁记录: {accessory_device.name}")
        
        # 第一次提交以获取主租赁的ID
        db.session.flush()  # 刷新但不提交，获取ID
        
        # 更新附件租赁的parent_rental_id
        for accessory_rental in accessory_rentals:
            accessory_rental.parent_rental_id = main_rental.id
            current_app.logger.info(f"设置附件租赁 {accessory_rental.id} 的parent_rental_id为 {main_rental.id}")
        
        db.session.commit()
        current_app.logger.info(f"数据库提交成功 - 主租赁ID: {main_rental.id}, 附件租赁数量: {len(accessory_rentals)}, 附件: {accessories_added}")
        
        # 提交后再次检查数据库中的值
        saved_rental = Rental.query.get(main_rental.id)
        current_app.logger.info(f"数据库保存后查询 - ship_out_time: {saved_rental.ship_out_time}")
        current_app.logger.info(f"数据库保存后查询 - ship_in_time: {saved_rental.ship_in_time}")
        
        message = '租赁记录创建成功'
        if accessories_added:
            message += f'，已添加附件: {", ".join(accessories_added)}'
        
        return jsonify({
            'success': True,
            'message': message,
            'data': {
                'id': main_rental.id,
                'device_id': main_rental.device_id,
                'start_date': main_rental.start_date.isoformat(),
                'end_date': main_rental.end_date.isoformat(),
                'customer_name': main_rental.customer_name,
                'status': main_rental.status,
                'accessories': accessories_added,
                'accessory_rental_ids': [r.id for r in accessory_rentals]
            }
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"创建租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '创建租赁记录失败'
        }), 500


@bp.route('/api/rentals/<rental_id>', methods=['PUT'])
def update_rental(rental_id):
    """更新租赁记录"""
    try:
        rental = Rental.query.get(rental_id)
        if not rental:
            return jsonify({
                'success': False,
                'error': '租赁记录不存在'
            }), 404
        
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': '缺少更新数据'
            }), 400
        
        current_app.logger.info(f"更新租赁记录: {data}")
        
        # 更新字段
        if 'customer_name' in data:
            rental.customer_name = data['customer_name']
        
        if 'customer_phone' in data:
            rental.customer_phone = data['customer_phone']
        
        if 'destination' in data:
            rental.destination = data['destination']
        
        if 'start_date' in data:
            start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
            if start_date > rental.end_date:
                return jsonify({
                    'success': False,
                    'error': '开始日期不能晚于结束日期'
                }), 400
            rental.start_date = start_date
        
        if 'end_date' in data:
            end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            if end_date < rental.start_date:
                return jsonify({
                    'success': False,
                    'error': '结束日期不能早于开始日期'
                }), 400
            rental.end_date = end_date
        
        if 'status' in data:
            old_status = rental.status
            new_status = data['status']
            rental.status = new_status
            
            # 处理状态变化时的设备状态更新
            if old_status != new_status:
                current_app.logger.info(f"租赁状态从 {old_status} 变更为 {new_status}")
                
                # 更新主设备状态
                if rental.device:
                    if new_status in ['completed', 'cancelled']:
                        rental.device.status = 'idle'
                        current_app.logger.info(f"主设备 {rental.device.name} 状态更新为 idle")
                    elif new_status == 'active':
                        rental.device.status = 'renting'
                        current_app.logger.info(f"主设备 {rental.device.name} 状态更新为 renting")
                
                # 更新附件设备状态（新架构：通过child_rentals更新）
                for child_rental in rental.child_rentals:
                    if child_rental.device:
                        # 同步更新附件租赁的状态
                        child_rental.status = new_status
                        if new_status in ['completed', 'cancelled']:
                            child_rental.device.status = 'idle'
                            current_app.logger.info(f"附件设备 {child_rental.device.name} 状态更新为 idle")
                        elif new_status == 'active':
                            child_rental.device.status = 'renting'
                            current_app.logger.info(f"附件设备 {child_rental.device.name} 状态更新为 renting")
        
        if 'ship_out_time' in data:
            if data['ship_out_time']:
                rental.ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d')
            else:
                rental.ship_out_time = None
        
        if 'ship_in_time' in data:
            if data['ship_in_time']:
                rental.ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d')
            else:
                rental.ship_in_time = None
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '租赁记录更新成功',
            'data': {
                'id': rental.id,
                'customer_name': rental.customer_name,
                'customer_phone': rental.customer_phone,
                'destination': rental.destination,
                'start_date': rental.start_date.isoformat(),
                'end_date': rental.end_date.isoformat(),
                'status': rental.status
            }
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '更新租赁记录失败'
        }), 500


@bp.route('/api/rentals/<rental_id>', methods=['DELETE'])
def delete_rental(rental_id):
    """删除租赁记录"""
    try:
        rental = Rental.query.get(rental_id)
        if not rental:
            return jsonify({
                'success': False,
                'error': '租赁记录不存在'
            }), 404
        
        # 检查租赁状态
        if rental.status in ['active', 'completed']:
            return jsonify({
                'success': False,
                'error': '无法删除进行中或已完成的租赁记录'
            }), 400
        
        # 恢复设备状态
        if rental.device:
            rental.device.status = 'idle'
        
        db.session.delete(rental)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '租赁记录删除成功'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '删除租赁记录失败'
        }), 500


@bp.route('/api/rentals/check-conflict', methods=['POST'])
def check_rental_conflict():
    """检查租赁时间冲突"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': '请求数据不能为空'
            }), 400
            
        device_id = data.get('device_id')
        start_date = data.get('start_date')
        end_date = data.get('end_date')
        exclude_rental_id = data.get('exclude_rental_id')
        
        if not all([device_id, start_date, end_date]):
            return jsonify({
                'success': False,
                'error': '缺少必要参数'
            }), 400
        
        # 解析日期并转换为datetime（使用寄出寄回的默认时间）
        try:
            start_date_obj = datetime.strptime(start_date, '%Y-%m-%d')
            end_date_obj = datetime.strptime(end_date, '%Y-%m-%d')
            # 设置寄出时间为开始日期的19:00，寄回时间为结束日期+1天的12:00
            ship_out_time = start_date_obj.replace(hour=19, minute=0, second=0)
            ship_in_time = end_date_obj.replace(hour=12, minute=0, second=0) + timedelta(days=1)
        except ValueError:
            return jsonify({
                'success': False,
                'error': '日期格式错误'
            }), 400
        
        # 使用现有的库存服务检查可用性
        from app.services.inventory_service import InventoryService
        availability_result = InventoryService.check_device_availability(
            device_id, ship_out_time, ship_in_time, exclude_rental_id
        )
        
        return jsonify({
            'success': True,
            'has_conflict': not availability_result['available'],
            'reason': availability_result.get('reason', ''),
            'conflict_details': availability_result.get('conflicting_rentals', [])
        })
        
    except Exception as e:
        current_app.logger.error(f"检查租赁冲突失败: {e}")
        return jsonify({
            'success': False,
            'error': '检查冲突失败'
        }), 500


@bp.route('/web/rentals/<rental_id>', methods=['GET'])
def web_get_rental(rental_id):
    """Web界面获取单个租赁记录（别名）"""
    return get_rental(rental_id)


@bp.route('/web/rentals/<rental_id>', methods=['DELETE'])
def web_delete_rental(rental_id):
    """Web界面删除租赁记录（别名）"""
    return delete_rental(rental_id)


@bp.route('/web/rentals/<rental_id>', methods=['PUT'])
def web_update_rental(rental_id):
    """Web界面更新租赁记录"""
    try:
        rental = Rental.query.get(rental_id)
        if not rental:
            return jsonify({
                'success': False,
                'error': '租赁记录不存在'
            }), 404
        
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': '缺少更新数据'
            }), 400
        
        current_app.logger.info(f"更新租赁记录: {data}")
        
        # 记录原始设备ID，用于检测是否修改了设备
        original_device_id = rental.device_id
        conflicts_detected = []
        
        # 检测设备修改和档期冲突
        if 'device_id' in data and data['device_id'] != original_device_id:
            # 验证新设备是否存在
            new_device = Device.query.get(data['device_id'])
            if not new_device:
                return jsonify({
                    'success': False,
                    'error': '选择的设备不存在'
                }), 400
            
            # 获取时间范围（使用现有的或更新的日期）
            start_date = rental.start_date
            end_date = rental.end_date
            ship_out_time = rental.ship_out_time
            ship_in_time = rental.ship_in_time
            
            # 如果请求中有新的日期，使用新日期
            if 'start_date' in data:
                start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
            if 'end_date' in data:
                end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            if 'ship_out_time' in data and data['ship_out_time']:
                try:
                    from dateutil import parser
                    parsed_time = parser.isoparse(data['ship_out_time'])
                    ship_out_time = parsed_time.replace(tzinfo=None)
                except (ValueError, ImportError):
                    try:
                        ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        try:
                            ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d')
                        except ValueError:
                            pass
            if 'ship_in_time' in data and data['ship_in_time']:
                try:
                    from dateutil import parser
                    parsed_time = parser.isoparse(data['ship_in_time'])
                    ship_in_time = parsed_time.replace(tzinfo=None)
                except (ValueError, ImportError):
                    try:
                        ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d %H:%M:%S')
                    except ValueError:
                        try:
                            ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d')
                        except ValueError:
                            pass
            
            # 检查新设备的档期冲突
            if ship_out_time and ship_in_time:
                from app.services.inventory_service import InventoryService
                availability_check = InventoryService.check_device_availability(
                    data['device_id'], 
                    ship_out_time, 
                    ship_in_time,
                    exclude_rental_id=rental.id  # 排除当前租赁记录
                )
                
                if not availability_check['available']:
                    conflicts_detected.append({
                        'type': 'device_conflict',
                        'message': f'设备档期冲突: {availability_check["reason"]}',
                        'details': availability_check
                    })
            
            # 检查是否强制更新
            force_update = data.get('force_update', False)
            if conflicts_detected and not force_update:
                return jsonify({
                    'success': False,
                    'error': '设备档期冲突',
                    'conflicts': conflicts_detected,
                    'requires_confirmation': True,
                    'message': '检测到档期冲突，是否继续修改？'
                }), 409  # 使用409 Conflict状态码
        
        # 更新字段
        if 'device_id' in data:
            # 恢复原设备状态
            if rental.device:
                rental.device.status = 'idle'
            
            # 更新设备ID并设置新设备状态
            rental.device_id = data['device_id']
            new_device = Device.query.get(data['device_id'])
            if new_device and rental.status == 'active':
                new_device.status = 'renting'
        
        if 'customer_name' in data:
            rental.customer_name = data['customer_name']
        
        if 'customer_phone' in data:
            rental.customer_phone = data['customer_phone']
        
        if 'destination' in data:
            rental.destination = data['destination']
        
        if 'end_date' in data:
            end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            if end_date < rental.start_date:
                return jsonify({
                    'success': False,
                    'error': '结束日期不能早于开始日期'
                }), 400
            rental.end_date = end_date
        
        if 'ship_out_tracking_no' in data:
            rental.ship_out_tracking_no = data['ship_out_tracking_no']
        
        if 'ship_in_tracking_no' in data:
            rental.ship_in_tracking_no = data['ship_in_tracking_no']
        
        # 处理寄出时间
        if 'ship_out_time' in data:
            if data['ship_out_time']:
                try:
                    # 直接按照东八区时间解析（前端发送的就是本地时间字符串）
                    rental.ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d %H:%M:%S')
                    current_app.logger.info(f"寄出时间解析成功: {data['ship_out_time']} -> {rental.ship_out_time}")
                except ValueError:
                    try:
                        rental.ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d')
                        current_app.logger.info(f"寄出时间解析成功(日期格式): {data['ship_out_time']} -> {rental.ship_out_time}")
                    except ValueError:
                        current_app.logger.warning(f"无法解析寄出时间: {data['ship_out_time']}")
            else:
                rental.ship_out_time = None
        
        # 处理收回时间
        if 'ship_in_time' in data:
            if data['ship_in_time']:
                try:
                    # 直接按照东八区时间解析（前端发送的就是本地时间字符串）
                    rental.ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d %H:%M:%S')
                    current_app.logger.info(f"收回时间解析成功: {data['ship_in_time']} -> {rental.ship_in_time}")
                except ValueError:
                    try:
                        rental.ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d')
                        current_app.logger.info(f"收回时间解析成功(日期格式): {data['ship_in_time']} -> {rental.ship_in_time}")
                    except ValueError:
                        current_app.logger.warning(f"无法解析收回时间: {data['ship_in_time']}")
            else:
                rental.ship_in_time = None
        
        # 处理附件更新（新架构：附件也是独立的租赁记录）
        if 'accessories' in data:
            current_app.logger.info(f"更新附件: {data['accessories']}")
            
            # 获取当前附件租赁记录
            current_accessory_rentals = list(rental.child_rentals)
            current_accessories = {r.device_id for r in current_accessory_rentals}
            new_accessories = set(data['accessories'] if data['accessories'] else [])
            
            # 找出需要删除和添加的附件
            to_remove = current_accessories - new_accessories
            to_add = new_accessories - current_accessories
            
            current_app.logger.info(f"需要删除的附件: {to_remove}")
            current_app.logger.info(f"需要添加的附件: {to_add}")
            
            # 删除不再需要的附件租赁记录
            for accessory_id in to_remove:
                accessory_rental_to_remove = next(
                    (r for r in current_accessory_rentals if r.device_id == accessory_id), 
                    None
                )
                if accessory_rental_to_remove:
                    # 删除附件租赁记录
                    db.session.delete(accessory_rental_to_remove)
                    # 更新附件设备状态为空闲
                    accessory_device = Device.query.get(accessory_id)
                    if accessory_device:
                        accessory_device.status = 'idle'
                        current_app.logger.info(f"删除附件租赁记录，设备 {accessory_device.name} 状态更新为 idle")
            
            # 为新附件创建租赁记录
            for accessory_id in to_add:
                # 验证附件存在且是附件类型
                accessory_device = Device.query.get(accessory_id)
                if accessory_device and accessory_device.is_accessory:
                    # 检查附件在该时间段是否可用
                    if rental.ship_out_time and rental.ship_in_time:
                        from app.services.inventory_service import InventoryService
                        availability = InventoryService.check_device_availability(
                            accessory_id, rental.ship_out_time, rental.ship_in_time,
                            exclude_rental_id=rental.id
                        )
                        force_update = data.get('force_update', False)
                        if not availability['available'] and not force_update:
                            current_app.logger.warning(f"附件{accessory_id}不可用: {availability['reason']}")
                            conflicts_detected.append({
                                'type': 'accessory_conflict',
                                'message': f'附件 {accessory_device.name} 档期冲突: {availability["reason"]}',
                                'details': availability,
                                'accessory_id': accessory_id,
                                'accessory_name': accessory_device.name
                            })
                            continue
                    
                    # 为附件创建新的租赁记录
                    accessory_rental = Rental(
                        device_id=accessory_id,
                        start_date=rental.start_date,
                        end_date=rental.end_date,
                        customer_name=rental.customer_name,
                        customer_phone=rental.customer_phone,
                        destination=rental.destination,
                        status=rental.status,
                        ship_out_time=rental.ship_out_time,
                        ship_in_time=rental.ship_in_time,
                        parent_rental_id=rental.id
                    )
                    db.session.add(accessory_rental)
                    
                    # 更新附件设备状态为租赁中
                    if rental.status == 'active':
                        accessory_device.status = 'renting'
                        current_app.logger.info(f"新增附件租赁记录，设备 {accessory_device.name} 状态更新为 renting")
                    
                    current_app.logger.info(f"为附件创建新租赁记录: {accessory_device.name}")
                else:
                    current_app.logger.warning(f"附件设备 {accessory_id} 不存在或不是附件类型")
        
        db.session.commit()
        
        result_data = {
            'success': True,
            'message': '租赁记录更新成功',
            'data': {
                'id': rental.id,
                'device_id': rental.device_id,
                'device_name': rental.device.name if rental.device else 'Unknown',
                'customer_name': rental.customer_name,
                'customer_phone': rental.customer_phone,
                'destination': rental.destination,
                'end_date': rental.end_date.isoformat(),
                'ship_out_tracking_no': rental.ship_out_tracking_no,
                'ship_in_tracking_no': rental.ship_in_tracking_no,
                'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None
            }
        }
        
        # 如果有冲突但强制更新了，添加警告信息
        if conflicts_detected:
            result_data['warnings'] = [
                {
                    'type': 'conflict_override',
                    'message': '已强制更新租赁记录，请注意档期冲突',
                    'conflicts': conflicts_detected
                }
            ]
        
        return jsonify(result_data)
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '更新租赁记录失败'
        }), 500
