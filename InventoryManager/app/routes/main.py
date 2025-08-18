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
                rental.ship_out_time = datetime.fromisoformat(data['ship_out_time'].replace('Z', '+00:00'))
            except ValueError:
                pass
        
        if data.get('ship_in_time'):
            try:
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
