"""
租赁相关API路由
重构后的精简版本，只包含路由定义
"""

from flask import Blueprint
from app.handlers.rental_handlers import RentalHandlers
from app.utils.response import handle_response

bp = Blueprint('rental_api', __name__)


# ===================== 基础租赁API =====================

@bp.route('/api/rentals/estimate-logistics')
@handle_response
def estimate_logistics():
    """根据目的地预估顺丰标快物流时效"""
    return RentalHandlers.handle_estimate_logistics()

@bp.route('/api/rentals')
@handle_response
def get_rentals():
    """获取租赁记录列表"""
    return RentalHandlers.handle_get_rentals()


@bp.route('/api/rentals/pending-returns')
@handle_response
def get_pending_returns():
    """获取今天及以前应归还的租赁记录"""
    return RentalHandlers.handle_get_pending_returns()


@bp.route('/api/rentals/due-today')
@handle_response
def get_due_today_rentals():
    """待归还租赁记录的兼容接口"""
    return RentalHandlers.handle_get_pending_returns()


@bp.route('/api/rentals/<rental_id>')
@handle_response
def get_rental(rental_id):
    """获取单个租赁记录"""
    return RentalHandlers.handle_get_rental(rental_id)


@bp.route('/api/rentals', methods=['POST'])
@handle_response
def create_rental():
    """创建租赁记录"""
    return RentalHandlers.handle_create_rental()


@bp.route('/api/rentals/<rental_id>', methods=['PUT'])
@handle_response
def update_rental(rental_id):
    """更新租赁记录"""
    # 使用Web界面的更新处理器，因为功能相同
    return RentalHandlers.handle_web_update_rental(rental_id)


@bp.route('/api/rentals/<rental_id>', methods=['DELETE'])
@handle_response
def delete_rental(rental_id):
    """删除租赁记录"""
    return RentalHandlers.handle_delete_rental(rental_id)


@bp.route('/api/rentals/<rental_id>/status', methods=['PUT'])
@handle_response
def update_rental_status(rental_id):
    """更新租赁状态"""
    return RentalHandlers.handle_update_rental_status(rental_id)


@bp.route('/api/rentals/<rental_id>/ship-to-xianyu', methods=['POST'])
@handle_response
def ship_rental_to_xianyu(rental_id):
    """单个租赁发货到闲鱼"""
    return RentalHandlers.handle_ship_rental_to_xianyu(rental_id)


# ===================== 租赁检查API =====================

@bp.route('/api/rentals/check-conflict', methods=['POST'])
@handle_response
def check_rental_conflict():
    """检查租赁冲突"""
    return RentalHandlers.handle_check_rental_conflict()


@bp.route('/api/rentals/check-duplicate', methods=['POST'])
@handle_response
def check_duplicate_rental():
    """检查重复租赁"""
    return RentalHandlers.handle_check_duplicate_rental()


# ===================== Web界面API =====================

@bp.route('/web/rentals/<rental_id>', methods=['GET'])
@handle_response
def web_get_rental(rental_id):
    """Web界面获取租赁记录"""
    return RentalHandlers.handle_get_rental(rental_id)


@bp.route('/web/rentals/<rental_id>', methods=['PUT'])
@handle_response
def web_update_rental(rental_id):
    """Web界面更新租赁记录"""
    return RentalHandlers.handle_web_update_rental(rental_id)


@bp.route('/web/rentals/<rental_id>', methods=['DELETE'])
@handle_response
def web_delete_rental(rental_id):
    """Web界面删除租赁记录"""
    return RentalHandlers.handle_delete_rental(rental_id)


# ===================== 闲鱼订单API =====================

@bp.route('/api/rentals/fetch-xianyu-order', methods=['POST'])
@handle_response
def fetch_xianyu_order():
    """获取闲鱼订单详情"""
    return RentalHandlers.handle_fetch_xianyu_order()




# ===================== 搜索API =====================

@bp.route('/api/rentals/search', methods=['POST'])
@handle_response
def search_rentals():
    """搜索租赁记录 - 支持多字段搜索"""
    return RentalHandlers.handle_search_rentals()

# ===================== 批量打印API =====================

@bp.route('/api/rentals/by-ship-date', methods=['GET'])
@handle_response
def get_rentals_by_ship_date():
    """根据发货日期范围查询租赁记录（用于批量打印）"""
    return RentalHandlers.handle_get_rentals_by_ship_date()


@bp.route('/api/rentals/booking-context')
@handle_response
def booking_context():
    """Read same-shop order records before explicitly appending a device."""
    from flask import request
    from app.models.rental import Rental
    from app.services.rental.rental_service import RentalService
    from app.utils.response import success, bad_request
    try:
        order_no, shop_id = RentalService._resolve_shop(request.args.get('order_no'), request.args.get('shop_id'))
        if not order_no:
            return success(data={'rentals': []})
        rows = Rental.query.filter_by(xianyu_order_no=order_no, xianyu_shop_id=shop_id, parent_rental_id=None).filter(Rental.status != 'cancelled').order_by(Rental.id).all()
        return success(data={'rentals': [r.to_dict() for r in rows]})
    except ValueError as exc:
        return bad_request(str(exc))


@bp.route('/api/rentals/<int:rental_id>/reduce-booking', methods=['POST'])
@handle_response
def reduce_booking(rental_id):
    """Explicitly reduce a declared order after cancelling a device."""
    from decimal import Decimal, InvalidOperation
    from flask import request
    from app import db
    from app.models.rental import Rental, RentalBooking
    from app.models.warehouse import resolve_write_warehouse_id
    from app.utils.response import success, bad_request
    try:
        data = request.get_json() or {}
        rental = db.session.get(Rental, rental_id)
        if rental is None or not rental.booking_id:
            return bad_request('租赁不属于多设备订单')
        if rental.warehouse_id != resolve_write_warehouse_id(data.get('warehouse_id')):
            return bad_request('请切换到订单所属仓库')
        reason = str(data.get('reason') or '').strip()
        if not reason or len(reason) > 500:
            return bad_request('请填写减租原因（最多 500 字）')
        total = Decimal(str(data.get('total_amount')))
        if not total.is_finite() or total < 0 or total > Decimal('99999999.99') or total != total.quantize(Decimal('.01')):
            return bad_request('请填写减租后的订单总金额，最多两位小数')
        booking = RentalBooking.query.filter_by(id=rental.booking_id).populate_existing().with_for_update().one()
        rows = Rental.query.filter_by(booking_id=booking.id).filter(Rental.status != 'cancelled').populate_existing().with_for_update().all()
        if booking.expected_quantity != 2 or len(rows) != 1:
            return bad_request('请先取消不再租用的一台，仅保留一台有效主机')
        booking.expected_quantity = 1
        booking.total_amount = total
        booking.quantity_change_reason = reason
        from app.models.audit_log import AuditLog
        AuditLog.log_action('reduce_booking', resource_type='rental_booking', resource_id=str(booking.id),
                            description=reason, details={'expected_quantity': 1, 'total_amount': str(total)}, commit=False)
        rows[0].order_amount = total
        db.session.commit()
        return success(data=booking.to_dict(), message='已确认减租为一台')
    except (ValueError, InvalidOperation):
        db.session.rollback()
        return bad_request('请检查仓库及减租后的订单金额')


@bp.route('/api/rentals/<int:rental_id>/declare-booking', methods=['POST'])
@handle_response
def declare_booking(rental_id):
    """Persist an explicit two-device declaration before filling the missing slot."""
    from flask import request
    from app import db
    from app.models.rental import Rental, RentalBooking
    from app.models.xianyu_shop import XianyuShop
    from app.models.warehouse import resolve_write_warehouse_id
    from app.utils.response import success, bad_request
    try:
        data = request.get_json() or {}
        warehouse_id = resolve_write_warehouse_id(data.get('warehouse_id'))
        source = db.session.get(Rental, rental_id)
        if source is None or source.warehouse_id != warehouse_id or source.parent_rental_id or source.status == 'cancelled':
            return bad_request('请选择本仓库有效主机记录')
        if source.xianyu_shop_id:
            XianyuShop.query.filter_by(id=source.xianyu_shop_id).with_for_update().one()
        source = Rental.query.filter_by(id=rental_id).populate_existing().with_for_update().one()
        if source.booking_id:
            return success(data=source.booking.to_dict())
        if source.xianyu_order_no:
            existing = Rental.query.filter_by(xianyu_shop_id=source.xianyu_shop_id, xianyu_order_no=source.xianyu_order_no, parent_rental_id=None).filter(Rental.status != 'cancelled').all()
            if len(existing) != 1:
                return bad_request('同单已有多条记录，请先核对，不能自动合并')
        booking = RentalBooking(xianyu_shop_id=source.xianyu_shop_id, order_no=source.xianyu_order_no,
                                expected_quantity=2, total_amount=source.order_amount)
        db.session.add(booking)
        source.booking = booking
        db.session.commit()
        return success(data=booking.to_dict(), message='已确认应租两台，待补齐提醒将保留')
    except ValueError as exc:
        db.session.rollback()
        return bad_request(str(exc))
