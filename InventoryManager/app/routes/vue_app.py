"""
Vue应用路由
PC端和移动端前端
"""

from flask import Blueprint, render_template, send_from_directory, current_app
import os

bp = Blueprint('vue_app', __name__)


# =============================================================================
# PC端前端路由
# =============================================================================

@bp.route('/vue')
@bp.route('/vue/')
def vue_index():
    """Vue应用首页(PC端)"""
    # 直接返回构建后的Vue应用
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'index.html')


@bp.route('/vue/<path:filename>')
def vue_assets(filename):
    """Vue应用静态资源(PC端)"""
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, filename)


@bp.route('/assets/<path:filename>')
def vue_assets_absolute(filename):
    """Vue应用绝对路径静态资源(PC端)"""
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist', 'assets')
    return send_from_directory(vue_dist_path, filename)


@bp.route('/favicon.ico')
def vue_favicon():
    """Vue应用图标(PC端)"""
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'favicon.ico')


# =============================================================================
# 移动端前端路由
# =============================================================================

@bp.route('/mobile')
@bp.route('/mobile/')
def mobile_index():
    """Vue应用首页(移动端)"""
    mobile_dist_path = os.path.join(current_app.root_path, '..', 'static', 'mobile-dist')
    return send_from_directory(mobile_dist_path, 'index.html')


@bp.route('/mobile/<path:filename>')
def mobile_assets(filename):
    """Vue应用静态资源(移动端)"""
    mobile_dist_path = os.path.join(current_app.root_path, '..', 'static', 'mobile-dist')
    
    # 如果是访问子路由(不包含文件扩展名),返回 index.html
    # 这样可以支持前端路由(如 /mobile/gantt, /mobile/booking)
    if '.' not in filename.split('/')[-1]:
        return send_from_directory(mobile_dist_path, 'index.html')
    
    return send_from_directory(mobile_dist_path, filename)
