"""
前端页面路由 + 内部API - 主模块
"""

from flask import Blueprint, jsonify, current_app
from app.routes.web_pages import bp as web_pages_bp
from app.routes.gantt_api import bp as gantt_api_bp
from app.routes.device_api import bp as device_api_bp
from app.routes.rental_api import bp as rental_api_bp
from app.routes.inventory_api import bp as inventory_api_bp
from app.routes.ocr_api import bp as ocr_api_bp

# 创建主蓝图
bp = Blueprint('web', __name__)

# 注册所有子模块蓝图
bp.register_blueprint(web_pages_bp)
bp.register_blueprint(gantt_api_bp)
bp.register_blueprint(device_api_bp)
bp.register_blueprint(rental_api_bp)
bp.register_blueprint(inventory_api_bp)
bp.register_blueprint(ocr_api_bp)


@bp.route('/health')
def health_check():
    """健康检查"""
    return jsonify({
        'status': 'healthy',
        'timestamp': '2024-01-01T00:00:00Z',
        'service': 'Inventory Manager Web API'
    })
