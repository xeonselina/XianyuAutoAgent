"""
设备型号API路由
"""

from flask import Blueprint, jsonify
from app.models import DeviceModel

bp = Blueprint('device_model_api', __name__)


@bp.route('/api/device-models', methods=['GET'])
def get_device_models():
    """获取所有激活的设备型号及其附件"""
    try:
        # 只获取主设备型号（不包括附件）
        models = DeviceModel.get_active_models(include_accessories=False)
        result = []

        for model in models:
            model_data = model.to_dict(include_accessories=True)
            result.append(model_data)

        return jsonify({
            'success': True,
            'data': result
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


@bp.route('/api/device-models/<int:model_id>/accessories', methods=['GET'])
def get_model_accessories(model_id):
    """获取指定型号的附件"""
    try:
        # 使用 DeviceModel 的类方法来获取附件
        accessories = DeviceModel.get_accessories_for_model(model_id)
        result = [acc.to_dict(include_accessories=False) for acc in accessories]

        return jsonify({
            'success': True,
            'data': result
        })

    except Exception as e:
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500