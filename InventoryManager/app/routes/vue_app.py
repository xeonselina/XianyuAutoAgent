"""
Vue应用路由
PC端前端
"""

from flask import Blueprint, send_from_directory, current_app, request, redirect
import os
import logging
import re

bp = Blueprint('vue_app', __name__)
logger = logging.getLogger(__name__)

# 匹配手机 UA 的正则（不含平板，iPad 等走 PC 端体验更佳可按需调整）
_MOBILE_UA_RE = re.compile(
    r'(Android.*Mobile|iPhone|iPod|BlackBerry|IEMobile|Opera Mini)',
    re.IGNORECASE
)

def _is_mobile() -> bool:
    ua = request.headers.get('User-Agent', '')
    return bool(_MOBILE_UA_RE.search(ua))


# =============================================================================
# 统一入口路由
# =============================================================================

@bp.route('/')
@bp.route('/app/')
def unified_index():
    """统一入口路由 - 手机自动跳移动端，桌面返回 PC 端"""
    if _is_mobile():
        return redirect('/mobile/')
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
@bp.route('/rental-stats')
@bp.route('/sf-tracking')
@bp.route('/inspection')
@bp.route('/inspection-records')
def vue_router_routes(subpath=None):
    """处理所有 Vue Router 路由 - 返回 index.html 让前端路由处理"""
    dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(dist_path, 'index.html')


# =============================================================================
# 移动端前端路由 (Vant 4 移动版)
# =============================================================================

@bp.route('/mobile')
@bp.route('/mobile/')
def mobile_index():
    """移动端 Vue 应用入口"""
    mobile_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-mobile-dist')
    return send_from_directory(mobile_dist_path, 'index.html')


@bp.route('/mobile/assets/<path:filename>')
def mobile_assets(filename):
    """移动端静态资源"""
    assets_path = os.path.join(current_app.root_path, '..', 'static', 'vue-mobile-dist', 'assets')
    return send_from_directory(assets_path, filename)


@bp.route('/mobile/<path:subpath>')
def mobile_router_routes(subpath):
    """处理所有移动端 Vue Router 路由 - 返回 index.html 让前端路由处理"""
    mobile_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-mobile-dist')
    return send_from_directory(mobile_dist_path, 'index.html')


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
