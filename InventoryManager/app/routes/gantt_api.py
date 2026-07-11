"""
甘特图相关API模块
重构后的精简版本，只包含路由定义
"""

from flask import Blueprint
from app.handlers.gantt_handlers import GanttHandlers
from app.utils.response import handle_response

bp = Blueprint('gantt_api', __name__)


@bp.route('/api/gantt/data')
@handle_response
def gantt_data():
    """获取甘特图数据"""
    return GanttHandlers.handle_get_gantt_data()


@bp.route('/api/gantt/daily-stats')
@handle_response
def get_daily_stats():
    """获取每日统计信息"""
    return GanttHandlers.handle_get_daily_stats()


@bp.route('/api/rentals/find-slot', methods=['POST'])
@handle_response
def find_rental_slot():
    """查找可用的租赁时间段"""
    return GanttHandlers.handle_find_rental_slot()


@bp.route('/api/gantt/reorder/analyze', methods=['POST'])
@handle_response
def analyze_reorder():
    """分析接力关系。"""
    return GanttHandlers.handle_analyze_reorder()


@bp.route('/api/gantt/reorder/preview', methods=['POST'])
@handle_response
def preview_reorder():
    """生成档期重排预览。"""
    return GanttHandlers.handle_preview_reorder()
