"""
设备相关API模块
"""

from flask import Blueprint, request, jsonify, current_app
from app.models.device import Device
from app.services.inventory_service import InventoryService
from app import db
from datetime import datetime

bp = Blueprint('device_api', __name__)


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
                'model': device.model,
                'is_accessory': device.is_accessory,
                'status': device.status,
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
            'model': device.model,
            'is_accessory': device.is_accessory,
            'status': device.status,
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
    """创建设备"""
    try:
        data = request.get_json()
        
        # 验证必填字段
        required_fields = ['name', 'serial_number']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'error': f'缺少必填字段: {field}'
                }), 400
        
        # 检查序列号是否已存在
        existing_device = Device.query.filter_by(serial_number=data['serial_number']).first()
        if existing_device:
            return jsonify({
                'success': False,
                'error': '序列号已存在'
            }), 400
        
        # 创建设备
        device = Device(
            name=data['name'],
            serial_number=data['serial_number'],
            model=data.get('model', 'x200u'),
            is_accessory=data.get('is_accessory', False),
            status='idle'
        )
        
        db.session.add(device)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '设备创建成功',
            'data': {
                'id': device.id,
                'name': device.name,
                'serial_number': device.serial_number,
                'model': device.model,
                'is_accessory': device.is_accessory,
                'status': device.status
            }
        })
        
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
        
        # 更新字段
        if 'name' in data:
            device.name = data['name']
        if 'serial_number' in data:
            # 检查序列号是否已被其他设备使用
            existing_device = Device.query.filter(
                Device.serial_number == data['serial_number'],
                Device.id != device_id
            ).first()
            if existing_device:
                return jsonify({
                    'success': False,
                    'error': '序列号已被其他设备使用'
                }), 400
            device.serial_number = data['serial_number']
        if 'model' in data:
            device.model = data['model']
        if 'is_accessory' in data:
            device.is_accessory = data['is_accessory']
        if 'status' in data:
            device.status = data['status']
        
        device.updated_at = datetime.utcnow()
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '设备更新成功',
            'data': {
                'id': device.id,
                'name': device.name,
                'serial_number': device.serial_number,
                'model': device.model,
                'is_accessory': device.is_accessory,
                'status': device.status
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
        if device.rentals:
            return jsonify({
                'success': False,
                'error': '设备有关联的租赁记录，无法删除'
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
            'error': '删除设备失败'
        }), 500
