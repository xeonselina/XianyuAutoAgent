"""
Vue应用路由
PC端前端
"""

from flask import Blueprint, send_from_directory, current_app
import os
import logging

bp = Blueprint('vue_app', __name__)
logger = logging.getLogger(__name__)


# =============================================================================
# 统一入口路由
# =============================================================================

@bp.route('/')
@bp.route('/app/')
def unified_index():
    """统一入口路由 - 返回桌面版前端"""
    dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(dist_path, 'index.html')


@bp.route('/assets/<path:filename>')
def unified_assets(filename):
    """统一静态资源路由"""
    assets_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist', 'assets')
    return send_from_directory(assets_path, filename)


@bp.route('/favicon.ico')
def unified_favicon():
    """统一 favicon 路由"""
    dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(dist_path, 'favicon.ico')


# =============================================================================
# Vue Router 路由支持 - 捕获所有前端路由
# =============================================================================

@bp.route('/gantt')
@bp.route('/contract/<path:subpath>')
@bp.route('/shipping/<path:subpath>')
@bp.route('/batch-shipping-order')
@bp.route('/batch-shipping')
@bp.route('/statistics')
@bp.route('/sf-tracking')
@bp.route('/inspection')
@bp.route('/inspection-records')
def vue_router_routes(subpath=None):
    """处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理"""
    dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(dist_path, 'index.html')


# =============================================================================
# PC端前端路由 (向后兼容)
# =============================================================================

@bp.route('/vue')
@bp.route('/vue/')
def vue_index():
    """Vue应用首页(PC端) - 向后兼容的旧URL"""
    logger.warning("访问已废弃的 URL: /vue/ - 建议使用统一入口 /")
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'index.html')


@bp.route('/vue/<path:filename>')
def vue_assets(filename):
    """Vue应用静态资源(PC端)"""
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, filename)
