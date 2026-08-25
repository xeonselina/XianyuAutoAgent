"""
快递追踪API路由
"""

from flask import Blueprint, request, jsonify, current_app
from app.utils.scheduler_tasks import manual_query_tracking
from app.utils.scheduler import run_task_now, get_scheduler_status
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('tracking_api', __name__)


@bp.route('/api/tracking/query', methods=['POST'])
def query_tracking():
    """
    手动查询快递状态
    
    请求格式:
    {
        "tracking_number": "快递单号"
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据不能为空'
            }), 400
        
        tracking_number = data.get('tracking_number', '').strip()
        if not tracking_number:
            return jsonify({
                'success': False,
                'message': '快递单号不能为空'
            }), 400
        
        # 查询快递状态
        result = manual_query_tracking(
            tracking_number,
            warehouse_id=data.get('warehouse_id'),
            phone_last4=data.get('phone_last4'),
        )
        
        if result['success']:
            return jsonify(result), 200
        else:
            status = {
                'CONFIG_INCOMPLETE': 400,
                'WAREHOUSE_MISMATCH': 409,
                'BAD_REQUEST': 400,
                'EXTERNAL_SERVICE_ERROR': 502,
            }.get(result.get('code'), 500)
            return jsonify(result), status
            
    except Exception as e:
        logger.error(f"查询快递状态异常: {type(e).__name__}")
        return jsonify({
            'success': False,
            'code': 'EXTERNAL_SERVICE_ERROR',
            'message': '顺丰服务调用失败',
            'tracking_info': None
        }), 500


@bp.route('/api/tracking/batch-query', methods=['POST'])
def batch_query_tracking():
    """
    批量查询快递状态
    
    请求格式:
    {
        "tracking_numbers": ["单号1", "单号2", ...]
    }
    """
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'success': False,
                'message': '请求数据不能为空'
            }), 400
        
        tracking_numbers = data.get('tracking_numbers', [])
        if not tracking_numbers:
            return jsonify({
                'success': False,
                'message': '快递单号列表不能为空'
            }), 400
        
        if len(tracking_numbers) > 50:
            return jsonify({
                'success': False,
                'message': '一次最多查询50个快递单号'
            }), 400
        
        # 批量查询
        results = {}
        for tracking_number in tracking_numbers:
            tracking_number = tracking_number.strip()
            if tracking_number:
                result = manual_query_tracking(
                    tracking_number,
                    warehouse_id=data.get('warehouse_id'),
                    phone_last4=data.get('phone_last4'),
                )
                results[tracking_number] = result
        
        return jsonify({
            'success': True,
            'message': '批量查询完成',
            'results': results
        }), 200
        
    except Exception as e:
        logger.error(f"批量查询快递状态异常: {type(e).__name__}")
        return jsonify({
            'success': False,
            'code': 'EXTERNAL_SERVICE_ERROR',
            'message': '顺丰服务调用失败',
            'results': {}
        }), 500


@bp.route('/api/tracking/update-now', methods=['POST'])
def update_tracking_now():
    """
    立即执行快递状态更新任务
    """
    try:
        success = run_task_now('update_tracking')
        
        if success:
            return jsonify({
                'success': True,
                'message': '快递状态更新任务已执行'
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': '执行任务失败'
            }), 500
            
    except Exception as e:
        logger.error(f"立即更新快递状态异常: {e}")
        return jsonify({
            'success': False,
            'message': f'执行失败: {str(e)}'
        }), 500


@bp.route('/api/tracking/scheduler-status', methods=['GET'])
def get_tracking_scheduler_status():
    """
    获取定时调度器状态
    """
    try:
        status = get_scheduler_status()
        return jsonify({
            'success': True,
            'data': status
        }), 200
        
    except Exception as e:
        logger.error(f"获取调度器状态异常: {e}")
        return jsonify({
            'success': False,
            'message': f'获取状态失败: {str(e)}',
            'data': None
        }), 500


@bp.route('/api/device/update-status', methods=['POST'])
def update_device_status():
    return jsonify({
        'success': False,
        'message': '设备在线/离线状态已移除'
    }), 410


@bp.route('/api/device/force-update-status', methods=['POST'])
def force_update_single_device_status():
    return jsonify({
        'success': False,
        'message': '设备在线/离线状态已移除'
    }), 410


@bp.route('/api/device/status-summary', methods=['GET'])
def get_devices_status_summary():
    return jsonify({
        'success': False,
        'message': '设备在线/离线状态已移除'
    }), 410
