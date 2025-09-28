"""
外部API路由 - 用于其他系统集成（需要API密钥认证）
"""

from flask import Blueprint, request, jsonify, current_app
from app.models import Device, Rental
from app.services.inventory_service import InventoryService
from app.services.rental_service import RentalService
from datetime import datetime, date
from functools import wraps
import json

bp = Blueprint('external_api', __name__)


def require_api_key(f):
    """API密钥验证装饰器"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        if not api_key or api_key != current_app.config.get('API_KEY'):
            return jsonify({
                'success': False,
                'error': '无效的API密钥'
            }), 401
        return f(*args, **kwargs)
    return decorated_function


@bp.route('/devices/<int:device_id>/status', methods=['PUT'])
@require_api_key
def update_device_status(device_id):
    """更新设备状态"""
    try:
        data = request.get_json()
        if not data or 'status' not in data:
            return jsonify({
                'success': False,
                'error': '缺少状态参数'
            }), 400
        
        new_status = data['status']
        valid_statuses = ['online', 'offline']
        
        if new_status not in valid_statuses:
            return jsonify({
                'success': False,
                'error': f'无效的状态值: {new_status}'
            }), 400
        
        # 查找设备
        device = Device.query.get(device_id)
        if not device:
            return jsonify({
                'success': False,
                'error': '设备不存在'
            }), 404
        
        # 更新状态
        old_status = device.status
        device.status = new_status
        device.updated_at = datetime.utcnow()
        
        # 保存到数据库
        from app import db
        db.session.commit()
        
        current_app.logger.info(f"设备 {device.name} (ID: {device_id}) 状态从 {old_status} 更新为 {new_status}")
        
        return jsonify({
            'success': True,
            'message': f'设备状态已更新为: {new_status}',
            'data': {
                'device_id': device_id,
                'old_status': old_status,
                'new_status': new_status,
                'updated_at': device.updated_at.isoformat()
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"更新设备状态失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误'
        }), 500


@bp.route('/inventory/available', methods=['GET'])
@require_api_key
def get_available_inventory():
    """查询可用库存 - 主要API端点"""
    try:
        # 获取查询参数
        ship_out_time_str = request.args.get('ship_out_time')
        ship_in_time_str = request.args.get('ship_in_time')
        device_type = request.args.get('device_type')
        
        # 验证必填参数
        if not ship_out_time_str or not ship_in_time_str:
            return jsonify({
                'success': False,
                'error': '缺少必填参数: ship_out_time 和 ship_in_time'
            }), 400
        
        # 解析时间
        try:
            ship_out_time = datetime.fromisoformat(ship_out_time_str)
            ship_in_time = datetime.fromisoformat(ship_in_time_str)
        except ValueError:
            return jsonify({
                'success': False,
                'error': '时间格式错误，请使用ISO格式 (YYYY-MM-DDTHH:MM:SS)'
            }), 400
        
        # 验证时间
        if ship_out_time >= ship_in_time:
            return jsonify({
                'success': False,
                'error': '寄出时间必须早于收回时间'
            }), 400
        
        if ship_out_time < datetime.now():
            return jsonify({
                'success': False,
                'error': '寄出时间不能早于当前时间'
            }), 400
        
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
                'location': None  # location字段已移除
            }
            response_data.append(device_info)
        
        return jsonify({
            'success': True,
            'data': response_data,
            'query_params': {
                'ship_out_time': ship_out_time_str,
                'ship_in_time': ship_in_time_str,
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


@bp.route('/inventory/check', methods=['POST'])
@require_api_key
def check_inventory_availability():
    """批量检查库存可用性"""
    try:
        data = request.get_json()
        
        if not data or 'queries' not in data:
            return jsonify({
                'success': False,
                'error': '缺少查询数据'
            }), 400
        
        queries = data['queries']
        if not isinstance(queries, list):
            return jsonify({
                'success': False,
                'error': 'queries必须是数组格式'
            }), 400
        
        results = []
        for query in queries:
            try:
                # 验证查询参数
                required_fields = ['ship_out_time', 'ship_in_time']
                for field in required_fields:
                    if field not in query:
                        results.append({
                            'query': query,
                            'success': False,
                            'error': f'缺少必填字段: {field}'
                        })
                        continue
                
                # 解析时间
                ship_out_time = datetime.fromisoformat(query['ship_out_time'])
                ship_in_time = datetime.fromisoformat(query['ship_in_time'])
                device_type = query.get('device_type')
                
                # 查询可用设备
                available_devices = Device.get_available_devices(ship_out_time, ship_in_time)
                
                # 按设备类型过滤（如果指定）
                if device_type:
                    available_devices = [d for d in available_devices if device_type.lower() in d.name.lower()]
                
                results.append({
                    'query': query,
                    'success': True,
                    'available_devices': [device.id for device in available_devices],
                    'total_available': len(available_devices)
                })
                
            except Exception as e:
                results.append({
                    'query': query,
                    'success': False,
                    'error': str(e)
                })
        
        return jsonify({
            'success': True,
            'data': results,
            'total_queries': len(queries),
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"批量检查库存可用性失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误'
        }), 500


@bp.route('/rentals', methods=['POST'])
@require_api_key
def create_rental():
    """创建租赁记录"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'success': False,
                'error': '缺少租赁数据'
            }), 400
        
        # 使用租赁服务创建记录
        result = RentalService.create_rental(
            device_id=data.get('device_id'),
            start_date=datetime.strptime(data['start_date'], '%Y-%m-%d').date(),
            end_date=datetime.strptime(data['end_date'], '%Y-%m-%d').date(),
            customer_name=data.get('customer_name'),
            customer_phone=data.get('customer_phone')
        )
        
        if result['success']:
            return jsonify(result), 201
        else:
            return jsonify(result), 400
        
    except Exception as e:
        current_app.logger.error(f"创建租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误'
        }), 500


@bp.route('/rentals/<int:rental_id>', methods=['GET'])
@require_api_key
def get_rental(rental_id):
    """获取租赁记录详情"""
    try:
        rental = Rental.query.get(rental_id)
        if not rental:
            return jsonify({
                'success': False,
                'error': '租赁记录不存在'
            }), 404
        
        return jsonify({
            'success': True,
            'data': rental.to_dict()
        })
        
    except Exception as e:
        current_app.logger.error(f"获取租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误'
        }), 500


@bp.route('/rentals/<int:rental_id>', methods=['PUT'])
@require_api_key
def update_rental(rental_id):
    """更新租赁记录"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'error': '缺少更新数据'
            }), 400
        
        rental = Rental.query.get(rental_id)
        if not rental:
            return jsonify({
                'success': False,
                'error': '租赁记录不存在'
            }), 404
        
        # 更新字段
        if 'ship_out_time' in data and data['ship_out_time']:
            rental.ship_out_time = datetime.fromisoformat(data['ship_out_time'])
        
        if 'ship_in_time' in data and data['ship_in_time']:
            rental.ship_in_time = datetime.fromisoformat(data['ship_in_time'])
        
        if 'status' in data:
            rental.status = data['status']
        
        rental.updated_at = datetime.utcnow()
        
        from app import db
        db.session.commit()
        
        current_app.logger.info(f"更新租赁记录: {rental_id}")
        
        return jsonify({
            'success': True,
            'message': '租赁记录更新成功',
            'data': rental.to_dict()
        })
        
    except Exception as e:
        from app import db
        db.session.rollback()
        current_app.logger.error(f"更新租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误'
        }), 500


@bp.route('/rentals/<int:rental_id>/cancel', methods=['POST'])
@require_api_key
def cancel_rental(rental_id):
    """取消租赁记录"""
    try:
        result = RentalService.cancel_rental(rental_id)
        
        if result['success']:
            return jsonify(result)
        else:
            return jsonify(result), 400
        
    except Exception as e:
        current_app.logger.error(f"取消租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误'
        }), 500


@bp.route('/devices', methods=['GET'])
@require_api_key
def get_devices():
    """获取设备列表"""
    try:
        status_filter = request.args.get('status')
        location_filter = request.args.get('location')  # 已废弃
        
        query = Device.query
        
        if status_filter:
            query = query.filter(Device.status == status_filter)
        
        # location字段已移除，忽略位置过滤
        # if location_filter:
        #     query = query.filter(Device.location == location_filter)
        
        devices = query.all()
        
        device_list = []
        for device in devices:
            device_info = {
                'id': device.id,
                'name': device.name,
                'serial_number': device.serial_number,
                'status': device.status,
                'location': None,  # location字段已移除
                'created_at': device.created_at.isoformat(),
                'updated_at': device.updated_at.isoformat()
            }
            device_list.append(device_info)
        
        return jsonify({
            'success': True,
            'data': device_list,
            'total': len(device_list),
            'filters': {
                'status': status_filter,
                'location': None  # location字段已移除
            }
        })
        
    except Exception as e:
        current_app.logger.error(f"获取设备列表失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误'
        }), 500


@bp.route('/devices/<device_id>', methods=['GET'])
@require_api_key
def get_device(device_id):
    """获取设备详情"""
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
            'location': None,  # location字段已移除
            'created_at': device.created_at.isoformat(),
            'updated_at': device.updated_at.isoformat(),
            'current_rental': device.get_current_rental().to_dict() if device.get_current_rental() else None
        }
        
        return jsonify({
            'success': True,
            'data': device_info
        })
        
    except Exception as e:
        current_app.logger.error(f"获取设备详情失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误'
        }), 500


@bp.route('/statistics', methods=['GET'])
@require_api_key
def get_statistics():
    """获取统计信息"""
    try:
        # 设备统计
        total_devices = Device.query.count()
        online_devices = Device.query.filter_by(status='online').count()
        offline_devices = Device.query.filter_by(status='offline').count()
        
        # 租赁统计
        total_rentals = Rental.query.count()
        active_rentals = Rental.query.filter_by(status='active').count()
        pending_rentals = Rental.query.filter_by(status='pending').count()
        completed_rentals = Rental.query.filter_by(status='completed').count()
        overdue_rentals = Rental.query.filter_by(status='overdue').count()
        
        # 计算设备在线率
        online_rate = (online_devices / total_devices * 100) if total_devices > 0 else 0
        
        stats = {
            'devices': {
                'total': total_devices,
                'online': online_devices,
                'offline': offline_devices,
                'online_rate': round(online_rate, 2)
            },
            'rentals': {
                'total': total_rentals,
                'active': active_rentals,
                'pending': pending_rentals,
                'completed': completed_rentals,
                'overdue': overdue_rentals
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
            'error': '服务器内部错误'
        }), 500


@bp.route('/health', methods=['GET'])
def health_check():
    """健康检查（无需认证）"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'InventoryManager External API'
    })


@bp.route('/docs', methods=['GET'])
def api_docs():
    """API文档"""
    docs = {
        'title': 'InventoryManager External API',
        'version': '1.0.0',
        'description': '设备租赁管理系统外部API接口',
        'authentication': {
            'type': 'API Key',
            'header': 'X-API-Key',
            'description': '除了健康检查接口外，所有接口都需要在请求头中包含API密钥'
        },
        'endpoints': {
            'devices': {
                'GET /devices': '获取设备列表',
                'GET /devices/{id}': '获取设备详情',
                'PUT /devices/{id}/status': '更新设备状态'
            },
            'inventory': {
                'GET /inventory/available': '查询可用库存',
                'POST /inventory/check': '批量检查库存可用性'
            },
            'rentals': {
                'POST /rentals': '创建租赁记录',
                'GET /rentals/{id}': '获取租赁记录详情',
                'PUT /rentals/{id}': '更新租赁记录',
                'POST /rentals/{id}/cancel': '取消租赁记录'
            },
            'system': {
                'GET /statistics': '获取统计信息',
                'GET /health': '健康检查',
                'GET /docs': 'API文档'
            }
        },
        'examples': {
            'query_available_inventory': {
                'url': '/inventory/available',
                'method': 'GET',
                'headers': {
                    'X-API-Key': 'your-api-key'
                },
                'params': {
                    'ship_out_time': '2024-01-01T10:00:00',
                    'ship_in_time': '2024-01-10T18:00:00',
                    'device_type': 'phone'
                }
            },
            'create_rental': {
                'url': '/rentals',
                'method': 'POST',
                'headers': {
                    'X-API-Key': 'your-api-key',
                    'Content-Type': 'application/json'
                },
                'body': {
                    'device_id': 1,
                    'start_date': '2024-01-01',
                    'end_date': '2024-01-10',
                    'customer_name': '张三',
                    'customer_phone': '13800138000'
                }
            }
        },
        'timestamp': datetime.utcnow().isoformat()
    }
    
    return jsonify(docs)
