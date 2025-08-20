"""
主要Web路由
"""

from flask import Blueprint, render_template, request, jsonify, current_app
from app.models.device import Device
from app.models.rental import Rental
from app.services.inventory_service import InventoryService
from app.services.rental_service import RentalService
from datetime import datetime, date, timedelta
import json
from app import db
import uuid

bp = Blueprint('main', __name__)


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
                'location': device.location
            }
            gantt_data['devices'].append(device_data)
        
        # 处理租赁数据
        for rental in rentals:
            rental_data = {
                'id': rental.id,
                'device_id': rental.device_id,
                'start_date': rental.start_date.isoformat(),
                'end_date': rental.end_date.isoformat(),
                'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None,
                'customer_name': rental.customer_name,
                'customer_phone': rental.customer_phone,
                'destination': rental.destination,
                'ship_out_tracking_no': rental.ship_out_tracking_no,
                'ship_in_tracking_no': rental.ship_in_tracking_no,
                'status': rental.status
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
            'error': str(e)
        }), 500


@bp.route('/api/devices')
def get_devices():
    """获取设备列表"""
    try:
        devices = Device.query.all()
        return jsonify({
            'success': True,
            'data': [device.to_dict() for device in devices]
        })
    except Exception as e:
        current_app.logger.error(f"获取设备列表失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/devices/<device_id>')
def get_device(device_id):
    """获取单个设备信息"""
    try:
        device = Device.query.get_or_404(device_id)
        return jsonify({
            'success': True,
            'data': device.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f"获取设备信息失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/devices', methods=['POST'])
def create_device():
    """创建设备"""
    try:
        data = request.get_json()
        
        # 验证必填字段（以模型真实字段为准）
        required_fields = ['name']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'error': f'缺少必填字段: {field}'
                }), 400
        
        # 创建设备
        device = Device(
            name=data['name'],
            serial_number=data.get('serial_number'),
            location=data.get('location')
        )
        
        db.session.add(device)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'data': device.to_dict(),
            'message': '设备创建成功'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"创建设备失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/devices/<device_id>', methods=['PUT'])
def update_device(device_id):
    """更新设备信息"""
    try:
        device = Device.query.get_or_404(device_id)
        data = request.get_json()
        
        # 更新字段
        for field, value in data.items():
            if hasattr(device, field) and field not in ['id', 'created_at', 'updated_at']:
                setattr(device, field, value)
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'data': device.to_dict(),
            'message': '设备更新成功'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新设备失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/devices/<device_id>', methods=['DELETE'])
def delete_device(device_id):
    """删除设备"""
    try:
        device = Device.query.get_or_404(device_id)
        
        # 检查是否有活动的租赁记录
        active_rentals = Rental.query.filter_by(
            device_id=device_id,
            status='active'
        ).first()
        
        if active_rentals:
            return jsonify({
                'success': False,
                'error': '设备有活动的租赁记录，无法删除'
            }), 400
        
        db.session.delete(device)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '设备删除成功'
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"删除设备失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/rentals')
def get_rentals():
    """获取租赁记录列表"""
    try:
        rentals = Rental.query.all()
        return jsonify({
            'success': True,
            'data': [rental.to_dict() for rental in rentals]
        })
    except Exception as e:
        current_app.logger.error(f"获取租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/rentals/<rental_id>')
def get_rental(rental_id):
    """获取单个租赁记录"""
    try:
        rental = Rental.query.get_or_404(rental_id)
        return jsonify({
            'success': True,
            'data': rental.to_dict()
        })
    except Exception as e:
        current_app.logger.error(f"获取租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/rentals', methods=['POST'])
def create_rental():
    """创建租赁记录"""
    try:
        # 避免潜在的循环导入：在函数内进行局部导入
        from app.models.rental import Rental as RentalModel
        data = request.get_json()
        
        # 验证必填字段（与模型定义保持一致）
        required_fields = ['device_id', 'start_date', 'end_date', 'customer_name']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'error': f'缺少必填字段: {field}'
                }), 400
        
        # 解析日期
        start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
        
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
        
        # 检查设备存在
        device = Device.query.get_or_404(data['device_id'])
        
        # 创建租赁记录
        rental = RentalModel(
            device_id=data['device_id'],
            start_date=start_date,
            end_date=end_date,
            customer_name=data['customer_name'],
            customer_phone=data.get('customer_phone'),
            destination=data.get('destination')
        )
        
        # 设置物流时间（如果提供）
        if data.get('ship_out_time'):
            try:
                # 处理日期字符串（如 "2025-08-19"）
                if len(data['ship_out_time']) == 10:  # YYYY-MM-DD 格式
                    ship_out_date = datetime.strptime(data['ship_out_time'], '%Y-%m-%d').date()
                    rental.ship_out_time = datetime.combine(ship_out_date, datetime.min.time())
                else:
                    # 处理 ISO 格式
                    rental.ship_out_time = datetime.fromisoformat(data['ship_out_time'].replace('Z', '+00:00'))
            except ValueError:
                pass
        
        if data.get('ship_in_time'):
            try:
                # 处理日期字符串（如 "2025-08-19"）
                if len(data['ship_in_time']) == 10:  # YYYY-MM-DD 格式
                    ship_in_date = datetime.strptime(data['ship_in_time'], '%Y-%m-%d').date()
                    rental.ship_in_time = datetime.combine(ship_in_date, datetime.min.time())
                else:
                    # 处理 ISO 格式
                    rental.ship_in_time = datetime.fromisoformat(data['ship_in_time'].replace('Z', '+00:00'))
            except ValueError:
                pass
        
        db.session.add(rental)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'data': rental.to_dict(),
            'message': '租赁记录创建成功'
        }), 201
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"创建租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/rentals/<rental_id>', methods=['DELETE'])
@bp.route('/web/rentals/<rental_id>', methods=['DELETE'])
def delete_rental(rental_id):
    """删除租赁记录"""
    try:
        rental = Rental.query.get_or_404(rental_id)
        
        # 检查是否可以删除
        if rental.status == 'active' and rental.start_date <= date.today() <= rental.end_date:
            return jsonify({
                'success': False,
                'error': '租赁正在进行中，无法删除'
            }), 400
        
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
            'error': str(e)
        }), 500


@bp.route('/api/rentals/<rental_id>', methods=['PUT'])
@bp.route('/web/rentals/<rental_id>', methods=['PUT'])
def update_rental(rental_id):
    """更新租赁记录（不需要API Key）"""
    try:
        rental = Rental.query.get_or_404(rental_id)
        data = request.get_json() or {}

        updated_end_date = False

        # 可更新字段
        if 'customer_phone' in data:
            rental.customer_phone = data.get('customer_phone')
        if 'destination' in data:
            rental.destination = data.get('destination')
        if 'ship_out_tracking_no' in data:
            rental.ship_out_tracking_no = data.get('ship_out_tracking_no')
        if 'ship_in_tracking_no' in data:
            rental.ship_in_tracking_no = data.get('ship_in_tracking_no')
        if 'end_date' in data and data.get('end_date'):
            try:
                new_end = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            except ValueError:
                return jsonify({'success': False, 'error': '结束日期格式不正确，应为YYYY-MM-DD'}), 400
            # 允许等于开始日期
            if new_end < rental.start_date:
                return jsonify({'success': False, 'error': '结束日期不能早于开始日期'}), 400
            rental.end_date = new_end
            updated_end_date = True

        # 如果结束日期更新了，则同步更新 ship_in_time
        if updated_end_date:
            # 通过现有 ship_out_time 与 start_date 反推出 logistics_days
            logistics_days = 1
            if rental.ship_out_time:
                try:
                    ship_out_d = rental.ship_out_time.date()
                    logistics_days = (rental.start_date - ship_out_d).days - 1
                except Exception:
                    logistics_days = 1
            if logistics_days is None:
                logistics_days = 1
            # 计算新的 ship_in_time = end_date + 1 + logistics_days （按本地日0点保存）
            new_ship_in_date = rental.end_date + timedelta(days=1 + int(logistics_days))
            rental.ship_in_time = datetime.combine(new_ship_in_date, datetime.min.time())

        db.session.commit()
        return jsonify({'success': True, 'data': rental.to_dict(), 'message': '租赁记录更新成功'})
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新租赁记录失败: {e}")
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/api/statistics')
def get_statistics():
    """获取统计信息"""
    try:
        # 设备统计
        device_stats = {
            'total': Device.query.count(),
            'available': Device.query.filter_by(status='available').count(),
            'rented': Device.query.filter_by(status='rented').count(),
            'maintenance': Device.query.filter_by(status='maintenance').count(),
            'retired': Device.query.filter_by(status='retired').count()
        }
        
        # 租赁统计
        rental_stats = Rental.get_rental_statistics()
        
        # 按位置统计设备（使用实际存在的 location 字段）
        location_stats = db.session.query(
            Device.location, 
            db.func.count(Device.id)
        ).filter(Device.location.isnot(None)).group_by(Device.location).all()
        
        return jsonify({
            'success': True,
            'data': {
                'devices': device_stats,
                'rentals': rental_stats,
                'device_locations': [{'location': loc[0], 'count': loc[1]} for loc in location_stats]
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"获取统计信息失败: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/health')
def health_check():
    """健康检查"""
    try:
        # 检查数据库连接
        db.session.execute('SELECT 1')
        
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.utcnow().isoformat(),
            'database': 'connected'
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'timestamp': datetime.utcnow().isoformat(),
            'database': 'disconnected',
            'error': str(e)
        }), 500


@bp.route('/api/rentals/find-slot', methods=['POST'])
@bp.route('/web/rentals/find-slot', methods=['POST'])
def find_available_slot():
    """查找可用档期"""
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
            # 不再返回 404，改为 200 且 success=false，避免前端/日志把其当作错误
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


def find_available_time_slot(ship_out_date, ship_in_date):
    """查找可用档期（内部函数）"""
    try:
        # 获取所有可用设备（新枚举：idle）
        available_devices = Device.query.filter_by(status='idle').all()
        
        for device in available_devices:
            # 检查设备在指定时间段是否可用
            if is_device_available_in_period(device.id, ship_out_date, ship_in_date):
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


def is_device_available_in_period(device_id, start_date, end_date):
    """检查设备在指定时间段是否可用（内部函数）"""
    try:
        # 查找与指定时间段重叠的租赁记录
        # 使用 ship_out_time 和 ship_in_time 来判断重叠
        conflicting_rentals = Rental.query.filter(
            db.and_(
                Rental.device_id == device_id,
                Rental.status != 'cancelled',
                db.or_(
                    # 情况1：现有租赁的寄出时间在查询时间段内
                    db.and_(
                        Rental.ship_out_time.isnot(None),
                        Rental.ship_in_time.isnot(None),
                        db.or_(
                            db.and_(
                                Rental.ship_out_time <= datetime.combine(end_date, datetime.min.time()),
                                Rental.ship_in_time >= datetime.combine(start_date, datetime.min.time())
                            )
                        )
                    ),
                    # 情况2：现有租赁没有物流时间，使用租赁时间判断（向后兼容）
                    db.and_(
                        Rental.ship_out_time.is_(None),
                        Rental.ship_in_time.is_(None),
                        db.or_(
                            db.and_(
                                Rental.start_date <= end_date,
                                Rental.end_date >= start_date
                            )
                        )
                    )
                )
            )
        ).first()
        
        return conflicting_rentals is None
        
    except Exception as e:
        current_app.logger.error(f"检查设备可用性失败: {e}")
        return False
