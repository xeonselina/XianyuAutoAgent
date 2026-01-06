"""
验货相关路由
"""
from flask import Blueprint, request, jsonify
from app.services.inspection_service import InspectionService
from app.models.device import Device

inspection_bp = Blueprint('inspection', __name__, url_prefix='/api/inspections')


@inspection_bp.route('/rental/latest/<int:device_id>', methods=['GET'])
def get_latest_rental_by_device(device_id):
    """
    根据设备ID获取最近的租赁记录（在今天之前）
    
    Args:
        device_id: 设备ID
        
    Returns:
        JSON: 租赁记录详情和动态生成的检查清单
    """
    try:
        # 验证设备存在
        device = Device.query.get(device_id)
        if not device:
            return jsonify({
                'success': False,
                'error': 'Device not found',
                'message': f'设备ID {device_id} 不存在'
            }), 404
        
        # 查找最近的租赁记录
        rental = InspectionService.find_latest_rental_by_device_id(device_id)
        if not rental:
            return jsonify({
                'success': False,
                'error': 'No rental found',
                'message': f'设备 {device.name} 未找到今天之前的租赁记录'
            }), 404
        
        # 生成检查清单
        checklist = InspectionService.generate_checklist_for_rental(rental.id)
        
        return jsonify({
            'success': True,
            'data': {
                'rental': rental.to_dict(),
                'checklist': checklist
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': '获取租赁记录失败'
        }), 500


@inspection_bp.route('/rental/latest/by-name/<device_name>', methods=['GET'])
def get_latest_rental_by_device_name(device_name):
    """
    根据设备名称获取最近的租赁记录（在今天之前）
    
    Args:
        device_name: 设备名称（纯数字）
        
    Returns:
        JSON: 租赁记录详情和动态生成的检查清单
    """
    try:
        # 根据设备名称查询设备
        device = Device.query.filter_by(name=device_name).first()
        if not device:
            return jsonify({
                'success': False,
                'error': 'Device not found',
                'message': f'设备名称 {device_name} 不存在'
            }), 404
        
        # 查找最近的租赁记录
        rental = InspectionService.find_latest_rental_by_device_id(device.id)
        if not rental:
            return jsonify({
                'success': False,
                'error': 'No rental found',
                'message': f'设备 {device.name} 未找到今天之前的租赁记录'
            }), 404
        
        # 生成检查清单
        checklist = InspectionService.generate_checklist_for_rental(rental.id)
        
        return jsonify({
            'success': True,
            'data': {
                'rental': rental.to_dict(),
                'checklist': checklist
            }
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': '获取租赁记录失败'
        }), 500


@inspection_bp.route('', methods=['POST'])
def create_inspection():
    """
    创建验货记录
    
    Request Body:
        {
            "rental_id": 1,
            "device_id": 1,
            "check_items": [
                {"name": "机身外观", "is_checked": true, "order": 1},
                {"name": "屏幕显示", "is_checked": true, "order": 2},
                ...
            ]
        }
    
    Returns:
        JSON: 创建的验货记录详情
    """
    try:
        data = request.get_json()
        
        # 验证必需字段
        if not data or 'rental_id' not in data or 'device_id' not in data or 'check_items' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required fields',
                'message': '缺少必需字段：rental_id, device_id, check_items'
            }), 400
        
        # 创建验货记录
        inspection_record = InspectionService.create_inspection_record(
            rental_id=data['rental_id'],
            device_id=data['device_id'],
            check_items=data['check_items']
        )
        
        return jsonify({
            'success': True,
            'data': inspection_record.to_dict()
        }), 201
        
    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': '创建验货记录失败'
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': '创建验货记录失败'
        }), 500


@inspection_bp.route('/<int:inspection_id>', methods=['GET'])
def get_inspection(inspection_id):
    """
    获取验货记录详情
    
    Args:
        inspection_id: 验货记录ID
        
    Returns:
        JSON: 验货记录详情
    """
    try:
        inspection_record = InspectionService.get_inspection_record(inspection_id)
        
        if not inspection_record:
            return jsonify({
                'success': False,
                'error': 'Inspection record not found',
                'message': f'验货记录 {inspection_id} 不存在'
            }), 404
        
        return jsonify({
            'success': True,
            'data': inspection_record.to_dict()
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': '获取验货记录失败'
        }), 500


@inspection_bp.route('/<int:inspection_id>', methods=['PUT'])
def update_inspection(inspection_id):
    """
    更新验货记录
    
    Args:
        inspection_id: 验货记录ID
        
    Request Body:
        {
            "check_items": [
                {"id": 1, "is_checked": true},
                {"id": 2, "is_checked": false},
                ...
            ]
        }
    
    Returns:
        JSON: 更新后的验货记录详情
    """
    try:
        data = request.get_json()
        
        # 验证必需字段
        if not data or 'check_items' not in data:
            return jsonify({
                'success': False,
                'error': 'Missing required fields',
                'message': '缺少必需字段：check_items'
            }), 400
        
        # 更新验货记录
        inspection_record = InspectionService.update_inspection_record(
            inspection_id=inspection_id,
            check_items=data['check_items']
        )
        
        return jsonify({
            'success': True,
            'data': inspection_record.to_dict()
        }), 200
        
    except ValueError as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': '更新验货记录失败'
        }), 400
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': '更新验货记录失败'
        }), 500


@inspection_bp.route('', methods=['GET'])
def list_inspections():
    """
    获取验货记录列表（支持筛选和分页）
    
    Query Parameters:
        - device_name: 设备名称（模糊匹配）
        - status: 验货状态 (normal/abnormal)
        - page: 页码（默认1）
        - per_page: 每页数量（默认20）
    
    Returns:
        JSON: 验货记录列表和分页信息
    """
    try:
        # 获取查询参数
        device_name = request.args.get('device_name')
        status = request.args.get('status')
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        
        # 验证分页参数
        if page < 1:
            page = 1
        if per_page < 1 or per_page > 100:
            per_page = 20
        
        # 获取验货记录列表
        result = InspectionService.get_inspection_records(
            device_name=device_name,
            status=status,
            page=page,
            per_page=per_page
        )
        
        return jsonify({
            'success': True,
            'data': result
        }), 200
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e),
            'message': '获取验货记录列表失败'
        }), 500
