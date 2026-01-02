"""
Vue应用路由
PC端和移动端前端

支持基于 User-Agent 的自动设备检测:
- 移动设备/平板 → 移动版界面
- 桌面设备 → 桌面版界面
"""

from flask import Blueprint, render_template, send_from_directory, current_app, request, make_response
import os
import logging

from app.utils.device_detector import detect_device_type, get_device_info, is_webview

bp = Blueprint('vue_app', __name__)
logger = logging.getLogger(__name__)


# =============================================================================
# 统一入口路由 (基于 User-Agent 自动检测)
# =============================================================================

@bp.route('/')
@bp.route('/app/')
def unified_index():
    """
    统一入口路由 - 基于 User-Agent 自动提供相应的前端版本

    设备检测逻辑:
    - 移动设备 (手机、平板) → mobile-dist
    - 桌面设备 → vue-dist
    - 无法识别/缺失 UA → vue-dist (默认桌面版)
    """
    # 获取 User-Agent 字符串
    ua_string = request.headers.get('User-Agent', '')

    # 检测设备类型
    device_type = detect_device_type(ua_string)

    # 获取详细设备信息 (用于日志)
    device_info = get_device_info(ua_string)
    webview_app = is_webview(ua_string)

    # 记录设备检测结果
    logger.info(
        f"Device detection: {device_type} | "
        f"OS: {device_info.get('os', 'Unknown')} | "
        f"Device: {device_info.get('device', 'Unknown')} | "
        f"Browser: {device_info.get('browser', 'Unknown')} | "
        f"WebView: {webview_app or 'None'}"
    )

    # 根据设备类型选择相应的前端
    if device_type == 'mobile':
        dist_path = os.path.join(current_app.root_path, '..', 'static', 'mobile-dist')
    else:
        dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')

    # 创建响应
    response = make_response(send_from_directory(dist_path, 'index.html'))

    # 添加响应头
    response.headers['X-Device-Type'] = device_type
    response.headers['Cache-Control'] = 'no-cache'
    response.headers['Vary'] = 'User-Agent'

    return response


@bp.route('/assets/<path:filename>')
def unified_assets(filename):
    """
    统一静态资源路由 - 基于 User-Agent 从相应的 dist 目录提供资源

    注意: 由于使用哈希文件名,移动和桌面版本的资源文件名不会冲突
    """
    # 获取 User-Agent 字符串
    ua_string = request.headers.get('User-Agent', '')

    # 检测设备类型
    device_type = detect_device_type(ua_string)

    # 根据设备类型选择相应的 assets 目录
    if device_type == 'mobile':
        assets_path = os.path.join(current_app.root_path, '..', 'static', 'mobile-dist', 'assets')
    else:
        assets_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist', 'assets')

    # 创建响应
    response = make_response(send_from_directory(assets_path, filename))

    # 设置缓存策略 (长期缓存,因为文件名包含哈希)
    response.headers['Cache-Control'] = 'public, max-age=31536000, immutable'

    return response


@bp.route('/favicon.ico')
def unified_favicon():
    """统一 favicon 路由"""
    ua_string = request.headers.get('User-Agent', '')
    device_type = detect_device_type(ua_string)

    if device_type == 'mobile':
        dist_path = os.path.join(current_app.root_path, '..', 'static', 'mobile-dist')
    else:
        dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')

    return send_from_directory(dist_path, 'favicon.ico')


# =============================================================================
# PC端前端路由 (向后兼容)
# =============================================================================

@bp.route('/vue')
@bp.route('/vue/')
def vue_index():
    """Vue应用首页(PC端) - 向后兼容的旧URL"""
    logger.warning("访问已废弃的 URL: /vue/ - 建议使用统一入口 /")
    # 直接返回构建后的Vue应用
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'index.html')


@bp.route('/vue/<path:filename>')
def vue_assets(filename):
    """Vue应用静态资源(PC端)"""
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, filename)


# =============================================================================
# 移动端前端路由
# =============================================================================

@bp.route('/mobile')
@bp.route('/mobile/')
def mobile_index():
    """Vue应用首页(移动端) - 向后兼容的旧URL"""
    logger.warning("访问已废弃的 URL: /mobile/ - 建议使用统一入口 /")
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
