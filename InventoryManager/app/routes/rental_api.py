"""
租赁相关API模块
"""

from flask import Blueprint, request, jsonify, current_app
from app.models.device import Device
from app.models.rental import Rental
from app.services.rental_service import RentalService
from app import db
from datetime import datetime, date
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
    """创建租赁记录"""
    try:
        data = request.get_json()
        
        # 验证必填字段
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
        
        if data.get('ship_out_time'):
            try:
                ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                # 如果时间格式解析失败，尝试只解析日期
                try:
                    ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d')
                except ValueError:
                    current_app.logger.warning(f"无法解析寄出时间: {data['ship_out_time']}")
        
        if data.get('ship_in_time'):
            try:
                ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d %H:%M:%S')
            except ValueError:
                # 如果时间格式解析失败，尝试只解析日期
                try:
                    ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d')
                except ValueError:
                    current_app.logger.warning(f"无法解析收回时间: {data['ship_in_time']}")
        
        # 创建租赁记录
        rental = Rental(
            device_id=data['device_id'],
            start_date=start_date,
            end_date=end_date,
            customer_name=data['customer_name'],
            customer_phone=customer_phone,
            destination=data.get('destination', ''),
            status='pending',
            ship_out_time=ship_out_time,
            ship_in_time=ship_in_time
        )
        
        # 更新设备状态（只有在非强制创建时才更新）
        if not force_create:
            device.status = 'renting'
        
        db.session.add(rental)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '租赁记录创建成功',
            'data': {
                'id': rental.id,
                'device_id': rental.device_id,
                'start_date': rental.start_date.isoformat(),
                'end_date': rental.end_date.isoformat(),
                'customer_name': rental.customer_name,
                'status': rental.status
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
            rental.status = data['status']
        
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
        
        # 更新字段
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
                    rental.ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    # 如果时间格式解析失败，尝试只解析日期
                    try:
                        rental.ship_out_time = datetime.strptime(data['ship_out_time'], '%Y-%m-%d')
                    except ValueError:
                        current_app.logger.warning(f"无法解析寄出时间: {data['ship_out_time']}")
            else:
                rental.ship_out_time = None
        
        # 处理收回时间
        if 'ship_in_time' in data:
            if data['ship_in_time']:
                try:
                    rental.ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    # 如果时间格式解析失败，尝试只解析日期
                    try:
                        rental.ship_in_time = datetime.strptime(data['ship_in_time'], '%Y-%m-%d')
                    except ValueError:
                        current_app.logger.warning(f"无法解析收回时间: {data['ship_in_time']}")
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
                'end_date': rental.end_date.isoformat(),
                'ship_out_tracking_no': rental.ship_out_tracking_no,
                'ship_in_tracking_no': rental.ship_in_tracking_no,
                'ship_out_time': rental.ship_out_time.isoformat() if rental.ship_out_time else None,
                'ship_in_time': rental.ship_in_time.isoformat() if rental.ship_in_time else None
            }
        })
        
    except Exception as e:
        db.session.rollback()
        current_app.logger.error(f"更新租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '更新租赁记录失败'
        }), 500
