"""
客户历史 API

对外提供两个端点，供甘特图「客户历史」入口使用：
- GET /api/customers/search?q=xxx       模糊搜索候选客户列表
- GET /api/customers/rentals?...        指定客户的最近 N 单
"""

import re
from datetime import date
from typing import Optional

from flask import Blueprint, request, current_app
from sqlalchemy import func, or_

from app import db
from app.models.rental import Rental
from app.utils.response import handle_response, success, bad_request
from app.services.printing.rental_product_lines import lens_combo_display

bp = Blueprint('customer_api', __name__)


_DIGITS_RE = re.compile(r'\D+')


def _normalize_phone(phone: Optional[str]) -> str:
    """去掉非数字字符，便于 contains 比较。"""
    if not phone:
        return ''
    return _DIGITS_RE.sub('', phone)


def _mask_phone(phone: Optional[str]) -> str:
    """脱敏：保留尾 4 位。"""
    digits = _normalize_phone(phone)
    if len(digits) < 4:
        return digits or ''
    return '****' + digits[-4:]


def _customer_key(rental: Rental) -> tuple:
    """生成聚合 key：归一化 phone 优先；无 phone 退化为 name+buyer_id。"""
    phone = _normalize_phone(rental.customer_phone)
    if phone:
        return ('phone', phone)
    return ('name', (rental.customer_name or '').strip(), (rental.buyer_id or '').strip())


@bp.route('/api/customers/search', methods=['GET'])
@handle_response
def search_customers():
    """模糊搜索客户候选列表。

    Query:
        q: 搜索关键词（可匹配 phone 数字片段 / name 子串 / buyer_id 子串）

    Returns:
        list[{customer_name, customer_phone_masked, buyer_id, total_rentals}]
    """
    query_str = (request.args.get('q') or '').strip()
    if not query_str:
        return success(data={'customers': []})

    q_digits = _normalize_phone(query_str)
    like = f'%{query_str}%'

    conditions = [
        Rental.customer_name.like(like),
        Rental.buyer_id.like(like),
    ]
    if q_digits:
        # MySQL 没有 regexp_replace 的方便做法，这里用 LIKE 把候选拿回来再在 Python 侧精确归一化匹配
        conditions.append(Rental.customer_phone.like(f'%{q_digits}%'))

    rentals = (
        Rental.query
        .filter(or_(*conditions))
        .order_by(Rental.created_at.desc())
        .limit(500)  # 控制扫描量；候选合并后再 limit 20
        .all()
    )

    # 聚合
    buckets = {}
    for r in rentals:
        # phone 归一化命中再过一道 filter
        if q_digits and not (
            q_digits in _normalize_phone(r.customer_phone)
            or query_str in (r.customer_name or '')
            or query_str in (r.buyer_id or '')
        ):
            continue
        key = _customer_key(r)
        bucket = buckets.setdefault(key, {
            'key': key,
            'customer_name': r.customer_name,
            'customer_phone': r.customer_phone,
            'customer_phone_masked': _mask_phone(r.customer_phone),
            'buyer_id': r.buyer_id,
            'total_rentals': 0,
            'latest_created_at': r.created_at,
        })
        bucket['total_rentals'] += 1
        # 选最新一条订单上的 name/buyer_id 作为代表
        if r.created_at and (bucket['latest_created_at'] is None or r.created_at >= bucket['latest_created_at']):
            bucket['latest_created_at'] = r.created_at
            bucket['customer_name'] = r.customer_name or bucket['customer_name']
            bucket['buyer_id'] = r.buyer_id or bucket['buyer_id']

    customers = sorted(buckets.values(), key=lambda b: b['total_rentals'], reverse=True)[:20]
    return success(data={
        'customers': [
            {
                'customer_name': c['customer_name'],
                'customer_phone': c['customer_phone'],
                'customer_phone_masked': c['customer_phone_masked'],
                'buyer_id': c['buyer_id'],
                'total_rentals': c['total_rentals'],
            }
            for c in customers
        ]
    })


@bp.route('/api/customers/rentals', methods=['GET'])
@handle_response
def get_customer_rentals():
    """获取指定客户的最近 N 单（默认 5），按 start_date desc, created_at desc。

    Query:
        phone:    客户电话（按归一化数字 contains 匹配，优先）
        name:     客户姓名（精确 contains 匹配，作为退化或补充）
        buyer_id: 闲鱼 EID（精确匹配，作为退化或补充）
        limit:    返回条数，默认 5
    """
    phone = (request.args.get('phone') or '').strip()
    name = (request.args.get('name') or '').strip()
    buyer_id = (request.args.get('buyer_id') or '').strip()
    try:
        limit = int(request.args.get('limit') or 5)
    except ValueError:
        limit = 5
    limit = max(1, min(limit, 50))

    if not (phone or name or buyer_id):
        return bad_request('至少需要 phone / name / buyer_id 之一')

    digits = _normalize_phone(phone)

    # 优先 phone，再退化到 name + buyer_id 组合
    query = Rental.query
    if digits:
        # 候选用宽 LIKE 取回，再在 Python 端按归一化精确匹配
        query = query.filter(Rental.customer_phone.like(f'%{digits}%'))
    else:
        if name:
            query = query.filter(Rental.customer_name == name)
        if buyer_id:
            query = query.filter(Rental.buyer_id == buyer_id)

    rentals = (
        query
        .order_by(Rental.start_date.desc(), Rental.created_at.desc())
        .limit(200)
        .all()
    )

    if digits:
        rentals = [r for r in rentals if digits in _normalize_phone(r.customer_phone)]

    rentals = rentals[:limit]

    data = []
    for r in rentals:
        device = getattr(r, 'device', None)
        dm = getattr(device, 'device_model', None) if device else None
        model_name = (dm.name if dm and dm.name else getattr(device, 'model', None)) if device else None
        model_display = (dm.display_name if dm and dm.display_name else model_name) or '未知'

        data.append({
            'id': r.id,
            'device_model_name': model_name,
            'device_model_display_name': model_display,
            'lens_combo': r.lens_combo,
            'lens_combo_display': lens_combo_display(r.lens_combo),
            'order_amount': float(r.order_amount) if r.order_amount is not None else None,
            'start_date': r.start_date.isoformat() if r.start_date else None,
            'end_date': r.end_date.isoformat() if r.end_date else None,
            'duration_days': r.get_duration_days(),
            'customer_name': r.customer_name,
            'customer_phone': r.customer_phone,
        })

    return success(data={'rentals': data})
