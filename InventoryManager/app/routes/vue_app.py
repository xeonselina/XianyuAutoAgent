"""
Vue应用路由
"""

from flask import Blueprint, render_template, send_from_directory, current_app
import os

bp = Blueprint('vue_app', __name__)


@bp.route('/vue')
@bp.route('/vue/')
def vue_index():
    """Vue应用首页"""
    # 直接返回构建后的Vue应用
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'index.html')


@bp.route('/vue/<path:filename>')
def vue_assets(filename):
    """Vue应用静态资源"""
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, filename)


@bp.route('/assets/<path:filename>')
def vue_assets_absolute(filename):
    """Vue应用绝对路径静态资源"""
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist', 'assets')
    return send_from_directory(vue_dist_path, filename)


@bp.route('/favicon.ico')
def vue_favicon():
    """Vue应用图标"""
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'favicon.ico')
