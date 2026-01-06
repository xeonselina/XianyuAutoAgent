"""
前端页面路由模块
"""

from flask import Blueprint, render_template, current_app
from app.models.device import Device
from app.models.rental import Rental

bp = Blueprint('web_pages', __name__)


# 注意：'/' 路由已迁移到 vue_app.py 的统一设备检测路由
# 旧路由已注释，使用新的自动设备检测功能
# @bp.route('/')
# def index():
#     """主页 - 甘特图界面"""
#     return render_template('index.html')


@bp.route('/gantt')
def gantt():
    """甘特图页面 - 直接显示Vue应用"""
    from flask import send_from_directory
    import os
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'index.html')


@bp.route('/shipping/<int:rental_id>')
def shipping_order(rental_id):
    """出货单页面 - 服务Vue应用"""
    from flask import send_from_directory
    import os
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'index.html')


@bp.route('/contract/<int:rental_id>')
def rental_contract(rental_id):
    """租赁合同页面 - 服务Vue应用"""
    from flask import send_from_directory
    import os
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'index.html')


@bp.route('/sf-tracking')
def sf_tracking():
    """顺丰物流追踪页面 - 服务Vue应用"""
    from flask import send_from_directory
    import os
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'index.html')


@bp.route('/batch-shipping')
def batch_shipping():
    """批量发货管理页面 - 服务Vue应用"""
    from flask import send_from_directory
    import os
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'index.html')


@bp.route('/batch-shipping-order')
def batch_shipping_order():
    """批量发货单打印页面 - 服务Vue应用"""
    from flask import send_from_directory
    import os
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'index.html')


@bp.route('/inspection')
def inspection():
    """验货页面 - 服务Vue应用"""
    from flask import send_from_directory
    import os
    vue_dist_path = os.path.join(current_app.root_path, '..', 'static', 'vue-dist')
    return send_from_directory(vue_dist_path, 'index.html')


@bp.route('/devices')
def devices():
    """设备管理页面"""
    return render_template('devices.html')


@bp.route('/rentals')
def rentals():
    """租赁管理页面"""
    return render_template('rentals.html')


def _prepare_shipping_order_data(rental, device):
    """准备出货单页面数据"""
    # 计算寄出和收回时间
    from datetime import timedelta
    
    logistics_days = 1  # 默认物流时间1天
    ship_out_date = rental.start_date - timedelta(days=1 + logistics_days)
    ship_in_date = rental.end_date + timedelta(days=1 + logistics_days)
    
    return {
        'rental': rental,
        'device': device,
        'ship_out_date': ship_out_date,
        'ship_in_date': ship_in_date,
        'logistics_days': logistics_days
    }


def _prepare_contract_data(rental, device):
    """准备租赁合同页面数据"""
    # 计算寄出和收回时间
    from datetime import timedelta
    
    logistics_days = 1  # 默认物流时间1天
    ship_out_date = rental.start_date - timedelta(days=1 + logistics_days)
    ship_in_date = rental.end_date + timedelta(days=1 + logistics_days)
    
    return {
        'rental': rental,
        'device': device,
        'ship_out_date': ship_out_date,
        'ship_in_date': ship_in_date,
        'logistics_days': logistics_days
    }
