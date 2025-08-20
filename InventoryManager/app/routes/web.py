"""
前端页面路由 + 内部API
"""

from flask import Blueprint, render_template, request, jsonify, current_app
from app.models.device import Device
from app.models.rental import Rental
from app.services.inventory_service import InventoryService
from app.services.rental_service import RentalService
from datetime import datetime, date, timedelta
import json
from app import db

bp = Blueprint('web', __name__)


# ============= 前端页面路由 =============

@bp.route('/')
def index():
    """主页 - 甘特图界面"""
    return render_template('index.html')


@bp.route('/gantt')
def gantt():
    """甘特图页面"""
    return render_template('gantt.html')


@bp.route('/devices')
def devices():
    """设备管理页面"""
    return render_template('devices.html')


@bp.route('/rentals')
def rentals():
    """租赁管理页面"""
    return render_template('rentals.html')


# ============= 内部API路由 =============

@bp.route('/api/gantt/data')
def gantt_data():
    """获取甘特图数据"""
    try:
        # 获取查询参数
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        # 如果没有指定日期范围，默认显示当前月
        if not start_date_str or not end_date_str:
            today = date.today()
            start_date = today.replace(day=1)
            if today.month == 12:
                end_date = today.replace(year=today.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                end_date = today.replace(month=today.month + 1, day=1) - timedelta(days=1)
        else:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        # 获取所有设备
        devices = Device.query.all()
        
        # 获取指定时间范围内的租赁记录
        rentals = Rental.query.filter(
            Rental.status != 'cancelled',
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
                'status': device.status,
                'location': device.location,
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
                    'status': rental.status,
                    'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                    'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None
                }
                device_data['rentals'].append(rental_data)
            
            gantt_data['devices'].append(device_data)
        
        # 处理所有租赁记录
        for rental in rentals:
            rental_data = {
                'id': rental.id,
                'device_id': rental.device_id,
                'device_name': rental.device.name if rental.device else 'Unknown',
                'start_date': rental.start_date.isoformat(),
                'end_date': rental.end_date.isoformat(),
                'customer_name': rental.customer_name,
                'status': rental.status,
                'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None
            }
            gantt_data['rentals'].append(rental_data)
        
        return jsonify({
            'success': True,
            'data': gantt_data
        })
        
    except Exception as e:
        current_app.logger.error(f"获取甘特图数据失败: {e}")
        return jsonify({
            'error': '获取数据失败',
            'message': str(e)
        }), 500


@bp.route('/api/devices')
def get_devices():
    """获取设备列表"""
    try:
        devices = Device.query.all()
        device_list = []
        
        for device in devices:
            device_info = {
                'id': device.id,
                'name': device.name,
                'serial_number': device.serial_number,
                'status': device.status,
                'location': device.location,
                'created_at': device.created_at.isoformat(),
                'updated_at': device.updated_at.isoformat()
            }
            device_list.append(device_info)
        
        return jsonify({
            'success': True,
            'data': device_list,
            'total': len(device_list)
        })
        
    except Exception as e:
        current_app.logger.error(f"获取设备列表失败: {e}")
        return jsonify({
            'success': False,
            'error': '获取设备列表失败'
        }), 500


@bp.route('/api/devices/<device_id>')
def get_device(device_id):
    """获取单个设备信息"""
    try:
        device = Device.query.get(device_id)
        if not device:
            return jsonify({
                'success': False,
                'error': '设备不存在'
            }), 404
        
        device_info = {
            'id': device.id,
            'name': device.name,
            'serial_number': device.serial_number,
            'status': device.status,
            'location': device.location,
            'created_at': device.created_at.isoformat(),
            'updated_at': device.updated_at.isoformat()
        }
        
        return jsonify({
            'success': True,
            'data': device_info
        })
        
    except Exception as e:
        current_app.logger.error(f"获取设备信息失败: {e}")
        return jsonify({
            'success': False,
            'error': '获取设备信息失败'
        }), 500


@bp.route('/api/devices', methods=['POST'])
def create_device():
    """创建新设备"""
    try:
        data = request.get_json()
        
        if not data or 'name' not in data:
            return jsonify({
                'success': False,
                'error': '缺少设备名称'
            }), 400
        
        # 检查序列号是否重复
        if 'serial_number' in data and data['serial_number']:
            existing_device = Device.query.filter_by(serial_number=data['serial_number']).first()
            if existing_device:
                return jsonify({
                    'success': False,
                    'error': '序列号已存在'
                }), 400
        
        # 创建新设备
        new_device = Device(
            name=data['name'],
            serial_number=data.get('serial_number'),
            location=data.get('location'),
            status='idle'
        )
        
        db.session.add(new_device)
        db.session.commit()
        
        current_app.logger.info(f"成功创建设备: {new_device.name}")
        
        return jsonify({
            'success': True,
            'message': '设备创建成功',
            'data': {
                'id': new_device.id,
                'name': new_device.name,
                'serial_number': new_device.serial_number,
                'status': new_device.status,
                'location': new_device.location
            }
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"创建设备失败: {e}")
        return jsonify({
            'success': False,
            'error': '创建设备失败'
        }), 500


@bp.route('/api/devices/<device_id>', methods=['PUT'])
def update_device(device_id):
    """更新设备信息"""
    try:
        device = Device.query.get(device_id)
        if not device:
            return jsonify({
                'success': False,
                'error': '设备不存在'
            }), 404
        
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': '缺少更新数据'
            }), 400
        
        # 检查序列号是否重复
        if 'serial_number' in data and data['serial_number']:
            existing_device = Device.query.filter_by(serial_number=data['serial_number']).first()
            if existing_device and existing_device.id != int(device_id):
                return jsonify({
                    'success': False,
                    'error': '序列号已存在'
                }), 400
        
        # 更新设备信息
        if 'name' in data:
            device.name = data['name']
        if 'serial_number' in data:
            device.serial_number = data['serial_number']
        if 'location' in data:
            device.location = data['location']
        if 'status' in data:
            device.status = data['status']
        
        device.updated_at = datetime.utcnow()
        db.session.commit()
        
        current_app.logger.info(f"成功更新设备: {device.name}")
        
        return jsonify({
            'success': True,
            'message': '设备更新成功',
            'data': {
                'id': device.id,
                'name': device.name,
                'serial_number': device.serial_number,
                'status': device.status,
                'location': device.location,
                'updated_at': device.updated_at.isoformat()
            }
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新设备失败: {e}")
        return jsonify({
            'success': False,
            'error': '更新设备失败'
        }), 500


@bp.route('/api/devices/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    """删除设备"""
    try:
        device = Device.query.get(device_id)
        if not device:
            return jsonify({
                'success': False,
                'error': '设备不存在'
            }), 404
        
        # 检查设备是否有关联的租赁记录
        if device.rentals.count() > 0:
            return jsonify({
                'success': False,
                'error': '设备有关联的租赁记录，无法删除'
            }), 400
        
        device_name = device.name
        db.session.delete(device)
        db.session.commit()
        
        current_app.logger.info(f"成功删除设备: {device_name}")
        
        return jsonify({
            'success': True,
            'message': '设备删除成功'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除设备失败: {e}")
        return jsonify({
            'success': False,
            'error': '删除设备失败'
        }), 500


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
    """创建新租赁记录"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': '缺少租赁数据'
            }), 400
        
        # 验证必填字段
        required_fields = ['device_id', 'start_date', 'end_date', 'customer_name']
        for field in required_fields:
            if field not in data:
                return jsonify({
                    'success': False,
                    'error': f'缺少必填字段: {field}'
                }), 400
        
        # 解析日期
        try:
            start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        except ValueError:
            return jsonify({
                'success': False,
                'error': '日期格式错误，请使用YYYY-MM-DD格式'
            }), 400
        
        # 验证日期
        if start_date >= end_date:
            return jsonify({
                'success': False,
                'error': '开始日期必须早于结束日期'
            }), 400
        
        if start_date < date.today():
            return jsonify({
                'success': False,
                'error': '开始日期不能早于今天'
            }), 400
        
        # 检查设备是否存在
        device = Device.query.get(data['device_id'])
        if not device:
            return jsonify({
                'success': False,
                'error': '设备不存在'
            }), 404
        
        # 检查设备是否可用
        if device.status != 'idle':
            return jsonify({
                'success': False,
                'error': f'设备当前状态为: {device.status}'
            }), 400
        
        # 创建租赁记录
        new_rental = Rental(
            device_id=data['device_id'],
            start_date=start_date,
            end_date=end_date,
            customer_name=data['customer_name'],
            customer_phone=data.get('customer_phone'),
            destination=data.get('destination'),
            status='pending'
        )
        
        db.session.add(new_rental)
        db.session.commit()
        
        current_app.logger.info(f"成功创建租赁记录: {new_rental.id}")
        
        return jsonify({
            'success': True,
            'message': '租赁记录创建成功',
            'data': {
                'id': new_rental.id,
                'device_id': new_rental.device_id,
                'start_date': new_rental.start_date.isoformat(),
                'end_date': new_rental.end_date.isoformat(),
                'customer_name': new_rental.customer_name,
                'status': new_rental.status
            }
        }), 201
        
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
        
        # 更新字段
        if 'customer_name' in data:
            rental.customer_name = data['customer_name']
        if 'customer_phone' in data:
            rental.customer_phone = data['customer_phone']
        if 'destination' in data:
            rental.destination = data['destination']
        if 'status' in data:
            rental.status = data['status']
        
        # 更新寄出和收回时间
        if 'ship_out_time' in data and data['ship_out_time']:
            try:
                rental.ship_out_time = datetime.fromisoformat(data['ship_out_time'])
            except ValueError:
                return jsonify({
                    'success': False,
                    'error': '寄出时间格式错误'
                }), 400
        
        if 'ship_in_time' in data and data['ship_in_time']:
            try:
                rental.ship_in_time = datetime.fromisoformat(data['ship_in_time'])
            except ValueError:
                return jsonify({
                    'success': False,
                    'error': '收回时间格式错误'
                }), 400
        
        rental.updated_at = datetime.utcnow()
        db.session.commit()
        
        current_app.logger.info(f"成功更新租赁记录: {rental_id}")
        
        return jsonify({
            'success': True,
            'message': '租赁记录更新成功',
            'data': rental.to_dict()
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
                'error': f'租赁记录状态为 {rental.status}，无法删除'
            }), 400
        
        db.session.delete(rental)
        db.session.commit()
        
        current_app.logger.info(f"成功删除租赁记录: {rental_id}")
        
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


@bp.route('/api/statistics')
def get_statistics():
    """获取统计信息"""
    try:
        # 设备统计
        total_devices = Device.query.count()
        idle_devices = Device.query.filter_by(status='idle').count()
        renting_devices = Device.query.filter_by(status='renting').count()
        
        # 租赁统计
        total_rentals = Rental.query.count()
        active_rentals = Rental.query.filter_by(status='active').count()
        pending_rentals = Rental.query.filter_by(status='pending').count()
        completed_rentals = Rental.query.filter_by(status='completed').count()
        
        # 计算设备利用率
        utilization_rate = (renting_devices / total_devices * 100) if total_devices > 0 else 0
        
        stats = {
            'devices': {
                'total': total_devices,
                'idle': idle_devices,
                'renting': renting_devices,
                'utilization_rate': round(utilization_rate, 2)
            },
            'rentals': {
                'total': total_rentals,
                'active': active_rentals,
                'pending': pending_rentals,
                'completed': completed_rentals
            },
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify({
            'success': True,
            'data': stats
        })
        
    except Exception as e:
        current_app.logger.error(f"获取统计信息失败: {e}")
        return jsonify({
            'success': False,
            'error': '获取统计信息失败'
        }), 500


@bp.route('/health')
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'InventoryManager'
    })


@bp.route('/api/rentals/find-slot', methods=['POST'])
def find_rental_slot():
    """查找可用的租赁时间段"""
    try:
        data = request.get_json()
        
        # 验证必填字段
        required_fields = ['start_date', 'end_date', 'logistics_days']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'error': f'缺少必填字段: {field}'
                }), 400
        
        # 解析日期
        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        logistics_days = int(data['logistics_days'])
        
        # 验证日期
        if start_date > end_date:
            return jsonify({
                'success': False,
                'error': '开始日期不能晚于结束日期'
            }), 400
        
        if start_date < date.today():
            return jsonify({
                'success': False,
                'error': '开始日期不能早于今天'
            }), 400
        
        # 计算寄出时间和收回时间
        ship_out_date = start_date - timedelta(days=1 + logistics_days)
        ship_in_date = end_date + timedelta(days=1 + logistics_days)
        
        # 检查寄出时间不能早于今天
        if ship_out_date < date.today():
            return jsonify({
                'success': False,
                'error': f'寄出时间不能早于今天。当前计算的寄出时间是：{ship_out_date}，请调整租赁时间或物流时间。'
            }), 400
        
        # 查找可用档期
        available_slot = find_available_time_slot(ship_out_date, ship_in_date)
        
        if available_slot:
            return jsonify({
                'success': True,
                'data': {
                    'device': available_slot['device'],
                    'ship_out_date': ship_out_date.isoformat(),
                    'ship_in_date': ship_in_date.isoformat(),
                    'message': f'找到可用档期：{available_slot["device"]["name"]}'
                }
            })
        else:
            return jsonify({
                'success': False,
                'error': '未找到可用档期，请调整时间或物流时间',
                'code': 'NO_SLOT'
            })
        
    except Exception as e:
        current_app.logger.error(f"查找档期失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/inventory/available', methods=['GET'])
def get_internal_available_inventory():
    """内部库存查询接口（无需认证）"""
    try:
        # 获取查询参数
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        device_type = request.args.get('device_type')
        
        # 验证必填参数
        if not start_date_str or not end_date_str:
            return jsonify({
                'success': False,
                'error': '缺少必填参数: start_date 和 end_date'
            }), 400
        
        # 解析日期
        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            return jsonify({
                'success': False,
                'error': '日期格式错误，请使用YYYY-MM-DD格式'
            }), 400
        
        # 验证日期
        if start_date >= end_date:
            return jsonify({
                'success': False,
                'error': '开始日期必须早于结束日期'
            }), 400
        
        if start_date < date.today():
            return jsonify({
                'success': False,
                'error': '开始日期不能早于今天'
            }), 400
        
        # 转换为寄出收回时间进行查询
        ship_out_time = datetime.combine(start_date, datetime.min.time())
        ship_in_time = datetime.combine(end_date, datetime.max.time())
        
        # 查询可用设备
        available_devices = Device.get_available_devices(ship_out_time, ship_in_time)
        
        # 按设备类型过滤（如果指定）
        if device_type:
            available_devices = [d for d in available_devices if device_type.lower() in d.name.lower()]
        
        # 构建响应数据
        response_data = []
        for device in available_devices:
            device_info = {
                'device_id': device.id,
                'device_name': device.name,
                'serial_number': device.serial_number,
                'status': device.status,
                'location': device.location
            }
            response_data.append(device_info)
        
        return jsonify({
            'success': True,
            'data': response_data,
            'query_params': {
                'start_date': start_date_str,
                'end_date': end_date_str,
                'device_type': device_type
            },
            'total_available': len(response_data),
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"查询可用库存失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误',
            'timestamp': datetime.utcnow().isoformat()
        }), 500


def find_available_time_slot(ship_out_date, ship_in_date):
    """查找可用档期（内部函数）"""
    try:
        # 获取所有可用设备
        available_devices = Device.query.filter_by(status='idle').all()
        
        for device in available_devices:
            # 检查设备在指定时间段是否可用
            if device.is_available(
                datetime.combine(ship_out_date, datetime.min.time()),
                datetime.combine(ship_in_date, datetime.min.time())
            ):
                return {
                    'device': {
                        'id': device.id,
                        'name': device.name,
                        'serial_number': device.serial_number,
                        'location': device.location,
                        'status': device.status
                    }
                }
        
        return None
        
    except Exception as e:
        current_app.logger.error(f"查找可用档期失败: {e}")
        return None


# ============= Web别名路由（为了兼容前端调用） =============

@bp.route('/web/rentals/<rental_id>', methods=['DELETE'])
def web_delete_rental(rental_id):
    """Web界面删除租赁记录（别名）"""
    return delete_rental(rental_id)


@bp.route('/web/rentals/<rental_id>', methods=['PUT'])
def web_update_rental(rental_id):
    """Web界面更新租赁记录（别名）"""
    return update_rental(rental_id)
