"""
设备相关API模块
"""

from flask import Blueprint, request, jsonify, current_app
from app.models.device import Device
from app.models.rental import Rental
from app.services.inventory_service import InventoryService
from app import db
from datetime import datetime, date, timedelta

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
            model_id=data.get('model_id'),
            is_accessory=data.get('is_accessory', False),
            status='online'
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
                'model_id': device.model_id,
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
            new_status = data['status']
            # 验证状态值
            if new_status not in ['online', 'offline']:
                return jsonify({
                    'success': False,
                    'error': '无效的设备状态，只支持 online 或 offline'
                }), 400
            device.status = new_status
        
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




# ==================== Device Lifecycle Management Endpoints ====================

@bp.route('/api/devices/<device_id>/lifecycle', methods=['PUT'])
def update_device_lifecycle(device_id):
    """更新设备生命周期状态"""
    try:
        device = Device.query.get(device_id)
        if not device:
            return jsonify({
                'success': False,
                'error': '设备不存在'
            }), 404
        
        data = request.get_json()
        
        # 验证必填字段
        if 'lifecycle_status' not in data:
            return jsonify({
                'success': False,
                'error': '缺少必填字段: lifecycle_status'
            }), 400
        
        new_status = data['lifecycle_status']
        reason = data.get('lifecycle_reason')
        
        # 使用模型方法设置生命周期状态
        success, message = device.set_lifecycle_status(new_status, reason)
        
        if not success:
            return jsonify({
                'success': False,
                'error': message
            }), 400
        
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': message,
            'data': {
                'id': device.id,
                'name': device.name,
                'lifecycle_status': device.lifecycle_status,
                'lifecycle_reason': device.lifecycle_reason,
                'lifecycle_date': device.lifecycle_date.isoformat() if device.lifecycle_date else None,
                'is_in_service': device.is_in_service(),
                'is_excluded_from_statistics': device.is_excluded_from_statistics()
            }
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新设备生命周期状态失败: {e}")
        return jsonify({
            'success': False,
            'error': '更新设备生命周期状态失败'
        }), 500


@bp.route('/api/devices/<device_id>/mark-sold', methods=['PUT'])
def mark_device_sold(device_id):
    """快速标记设备为已销售"""
    try:
        device = Device.query.get(device_id)
        if not device:
            return jsonify({
                'success': False,
                'error': '设备不存在'
            }), 404
        
        data = request.get_json() or {}
        reason = data.get('reason', '设备已销售')
        
        if device.mark_as_sold(reason):
            device.updated_at = datetime.utcnow()
            db.session.commit()
            
            return jsonify({
                'success': True,
                'message': '设备已成功标记为销售',
                'data': {
                    'id': device.id,
                    'name': device.name,
                    'lifecycle_status': device.lifecycle_status,
                    'lifecycle_reason': device.lifecycle_reason,
                    'lifecycle_date': device.lifecycle_date.isoformat() if device.lifecycle_date else None
                }
            })
        else:
            return jsonify({
                'success': False,
                'error': '设备已处于已销售状态'
            }), 400
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"标记设备为销售失败: {e}")
        return jsonify({
            'success': False,
            'error': '标记设备为销售失败'
        }), 500


@bp.route('/api/devices/lifecycle/summary', methods=['GET'])
def get_lifecycle_summary():
    """获取设备生命周期状态汇总"""
    try:
        # 按生命周期状态统计
        stats = Device.query.with_entities(
            Device.lifecycle_status,
            db.func.count(Device.id).label('count')
        ).group_by(Device.lifecycle_status).all()
        
        summary = {
            'active': 0,
            'sold': 0,
            'decommissioned': 0,
            'damaged': 0,
            'retired': 0,
            'total': 0
        }
        
        for status, count in stats:
            summary[status] = count
            summary['total'] += count
        
        # 计算在服务中的设备
        active_devices = Device.query.filter(
            Device.lifecycle_status == 'active',
            Device.status == 'online'
        ).count()
        
        # 计算应从统计中排除的设备
        excluded_devices = Device.query.filter(
            Device.lifecycle_status.in_(['sold', 'decommissioned', 'damaged', 'retired'])
        ).count()
        
        return jsonify({
            'success': True,
            'data': {
                'lifecycle_status_summary': summary,
                'active_and_online': active_devices,
                'excluded_from_statistics': excluded_devices,
                'available_for_rental': active_devices
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"获取生命周期汇总失败: {e}")
        return jsonify({
            'success': False,
            'error': '获取生命周期汇总失败'
        }), 500


@bp.route('/api/devices/lifecycle/list', methods=['GET'])
def get_devices_by_lifecycle_status():
    """按生命周期状态过滤获取设备列表"""
    try:
        # 获取查询参数
        status = request.args.get('status', 'all')  # all, active, sold, decommissioned, damaged, retired
        
        # 构建查询
        query = Device.query
        
        if status != 'all':
            valid_statuses = ['active', 'sold', 'decommissioned', 'damaged', 'retired']
            if status not in valid_statuses:
                return jsonify({
                    'success': False,
                    'error': f'无效的生命周期状态。有效值: {", ".join(valid_statuses)}'
                }), 400
            query = query.filter(Device.lifecycle_status == status)
        
        devices = query.order_by(Device.lifecycle_date.desc().nullsfirst(), Device.created_at.desc()).all()
        
        device_list = []
        for device in devices:
            device_info = device.to_dict()
            device_info['is_in_service'] = device.is_in_service()
            device_info['is_excluded_from_statistics'] = device.is_excluded_from_statistics()
            device_list.append(device_info)
        
        return jsonify({
            'success': True,
            'data': device_list,
            'total': len(device_list),
            'filter': status
        })
        
    except Exception as e:
        current_app.logger.error(f"获取设备列表失败: {e}")
        return jsonify({
            'success': False,
            'error': '获取设备列表失败'
        }), 500
