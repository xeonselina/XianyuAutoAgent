"""
API路由 - 用于其他系统集成
"""

from flask import Blueprint, request, jsonify, current_app
from app.models import Device, Rental
from app.services.inventory_service import InventoryService
from app.services.rental_service import RentalService
from datetime import datetime, date
from functools import wraps
import json

bp = Blueprint('api', __name__)


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


@bp.route('/inventory/available', methods=['GET'])
@require_api_key
def get_available_inventory():
    """查询可用库存 - 主要API端点"""
    try:
        # 获取查询参数
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        device_type = request.args.get('device_type')
        
        # 验证必填参数
        if not start_date_str or not end_date_str:
            return jsonify({
                'success': False,
                'error': '缺少必填参数: start_date, end_date'
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
        
        # 查询可用设备
        available_devices = Device.get_available_devices(start_date, end_date)
        
        # 构建响应数据
        response_data = []
        for device in available_devices:
            device_info = {
                'device_id': device.id,
                'device_name': device.name,
                'serial_number': device.serial_number,
                'status': 'available',
                'location': device.location
            }
            response_data.append(device_info)
        
        return jsonify({
            'success': True,
            'data': response_data,
            'query_params': {
                'start_date': start_date_str,
                'end_date': end_date_str
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
                required_fields = ['start_date', 'end_date']
                for field in required_fields:
                    if field not in query:
                        results.append({
                            'query': query,
                            'success': False,
                            'error': f'缺少必填字段: {field}'
                        })
                        continue
                
                # 解析日期
                start_date = datetime.strptime(query['start_date'], '%Y-%m-%d').date()
                end_date = datetime.strptime(query['end_date'], '%Y-%m-%d').date()
                device_type = query.get('device_type')
                
                # 查询可用设备
                available_devices = Device.get_available_devices(start_date, end_date, device_type)
                
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
            'results': results,
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"批量检查库存失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误',
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@bp.route('/rentals', methods=['POST'])
@require_api_key
def create_rental_api():
    """通过API创建租赁记录"""
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
        
        # 检查设备可用性
        device = Device.query.get_or_404(data['device_id'])
        if not device.is_available(start_date, end_date):
            return jsonify({
                'success': False,
                'error': '设备在指定时间段不可用'
            }), 400
        
        # 创建租赁记录
        rental = Rental(
            device_id=data['device_id'],
            start_date=start_date,
            end_date=end_date,
            customer_name=data['customer_name'],
            customer_phone=data.get('customer_phone'),
            destination=data.get('destination')
        )
        
        from app import db
        db.session.add(rental)
        db.session.commit()
        
        return jsonify({
            'success': True,
            'data': {
                'rental_id': rental.id,
                'device_id': rental.device_id,
                'start_date': rental.start_date.isoformat(),
                'end_date': rental.end_date.isoformat(),
                'customer_name': rental.customer_name,
                'total_cost': float(rental.total_cost) if rental.total_cost else None
            },
            'message': '租赁记录创建成功',
            'timestamp': datetime.utcnow().isoformat()
        }), 201
        
    except Exception as e:
        current_app.logger.error(f"API创建租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误',
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@bp.route('/rentals/<int:rental_id>', methods=['GET'])
@require_api_key
def get_rental_api(rental_id):
    """获取租赁记录信息"""
    try:
        rental = Rental.query.get_or_404(rental_id)
        
        return jsonify({
            'success': True,
            'data': rental.to_dict(),
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"API获取租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误',
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@bp.route('/rentals/<int:rental_id>', methods=['PUT'])
@require_api_key
def update_rental_api(rental_id):
    """更新租赁记录"""
    try:
        rental = Rental.query.get_or_404(rental_id)
        data = request.get_json()
        
        # 只允许更新特定字段
        allowed_fields = ['customer_phone', 'customer_email', 'customer_company', 'notes']
        
        for field, value in data.items():
            if field in allowed_fields and hasattr(rental, field):
                setattr(rental, field, value)
        
        from app import db
        db.session.commit()
        
        return jsonify({
            'success': True,
            'data': rental.to_dict(),
            'message': '租赁记录更新成功',
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"API更新租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误',
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@bp.route('/rentals/<int:rental_id>/cancel', methods=['POST'])
@require_api_key
def cancel_rental_api(rental_id):
    """取消租赁记录"""
    try:
        rental = Rental.query.get_or_404(rental_id)
        
        if not rental.can_cancel():
            return jsonify({
                'success': False,
                'error': '租赁记录无法取消'
            }), 400
        
        data = request.get_json() or {}
        notes = data.get('notes', '通过API取消')
        
        rental.cancel(notes)
        
        from app import db
        db.session.commit()
        
        return jsonify({
            'success': True,
            'message': '租赁记录取消成功',
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"API取消租赁记录失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误',
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@bp.route('/devices', methods=['GET'])
@require_api_key
def get_devices_api():
    """获取设备列表"""
    try:
        status = request.args.get('status')
        location = request.args.get('location')
        
        query = Device.query
        
        if status:
            query = query.filter(Device.status == status)
        
        if location:
            query = query.filter(Device.location == location)
        
        devices = query.all()
        
        return jsonify({
            'success': True,
            'data': [device.to_dict() for device in devices],
            'total': len(devices),
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"API获取设备列表失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误',
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@bp.route('/devices/<device_id>', methods=['GET'])
@require_api_key
def get_device_api(device_id):
    """获取单个设备信息"""
    try:
        device = Device.query.get_or_404(device_id)
        
        return jsonify({
            'success': True,
            'data': device.to_dict(),
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"API获取设备信息失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误',
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@bp.route('/statistics', methods=['GET'])
@require_api_key
def get_statistics_api():
    """获取统计信息"""
    try:
        start_date_str = request.args.get('start_date')
        end_date_str = request.args.get('end_date')
        
        start_date = None
        end_date = None
        
        if start_date_str and end_date_str:
            try:
                start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
                end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
            except ValueError:
                return jsonify({
                    'success': False,
                    'error': '日期格式错误，请使用YYYY-MM-DD格式'
                }), 400
        
        # 设备统计
        device_stats = {
            'total': Device.query.count(),
            'available': Device.query.filter_by(status='available').count(),
            'rented': Device.query.filter_by(status='rented').count(),
            'maintenance': Device.query.filter_by(status='maintenance').count(),
            'retired': Device.query.filter_by(status='retired').count()
        }
        
        # 租赁统计
        rental_stats = Rental.get_rental_statistics(start_date, end_date)
        
        # 按位置统计设备（使用实际存在的字段）
        from app import db
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
            },
            'timestamp': datetime.utcnow().isoformat()
        })
        
    except Exception as e:
        current_app.logger.error(f"API获取统计信息失败: {e}")
        return jsonify({
            'success': False,
            'error': '服务器内部错误',
            'timestamp': datetime.utcnow().isoformat()
        }), 500


@bp.route('/health', methods=['GET'])
def api_health_check():
    """API健康检查"""
    try:
        from app import db
        db.session.execute('SELECT 1')
        
        return jsonify({
            'status': 'healthy',
            'service': 'inventory_management_api',
            'timestamp': datetime.utcnow().isoformat(),
            'database': 'connected'
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'service': 'inventory_management_api',
            'timestamp': datetime.utcnow().isoformat(),
            'database': 'disconnected',
            'error': str(e)
        }), 500


@bp.route('/docs', methods=['GET'])
def api_docs():
    """API文档"""
    docs = {
        'title': '库存管理服务 API 文档',
        'version': '1.0.0',
        'description': '用于其他系统集成的库存管理API',
        'base_url': '/api',
        'endpoints': {
            'GET /inventory/available': {
                'description': '查询可用库存',
                'parameters': {
                    'start_date': '开始日期 (YYYY-MM-DD)',
                    'end_date': '结束日期 (YYYY-MM-DD)',
                    'device_type': '设备类型 (可选)'
                },
                'headers': {
                    'X-API-Key': 'API密钥'
                }
            },
            'POST /inventory/check': {
                'description': '批量检查库存可用性',
                'body': {
                    'queries': [
                        {
                            'start_date': '2024-01-15',
                            'end_date': '2024-01-17',
                            'device_type': '手机'
                        }
                    ]
                }
            },
            'POST /rentals': {
                'description': '创建租赁记录',
                'body': {
                    'device_id': '设备ID',
                    'start_date': '开始日期',
                    'end_date': '结束日期',
                    'customer_name': '客户姓名'
                }
            },
            'GET /devices': {
                'description': '获取设备列表',
                'parameters': {
                    'type': '设备类型 (可选)',
                    'status': '设备状态 (可选)'
                }
            },
            'GET /statistics': {
                'description': '获取统计信息',
                'parameters': {
                    'start_date': '开始日期 (可选)',
                    'end_date': '结束日期 (可选)'
                }
            }
        },
        'authentication': {
            'type': 'API Key',
            'header': 'X-API-Key',
            'description': '在请求头中包含有效的API密钥'
        },
        'error_codes': {
            '400': '请求参数错误',
            '401': '认证失败',
            '404': '资源不存在',
            '500': '服务器内部错误'
        }
    }
    
    return jsonify(docs)
