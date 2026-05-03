"""
出租周期统计 API —— 按周 / 按月，按型号
"""

from flask import Blueprint, jsonify, request
from app import db
from app.models.rental import Rental
from app.models.device import Device
from app.models.device_model import DeviceModel
from datetime import date, timedelta, datetime
import math
from sqlalchemy import func

bp = Blueprint('rental_stats_api', __name__, url_prefix='/api/rental-stats')

# 忽略的设备（name 字段值，即设备编号）
# 2005/3005/3006：已损坏/停用设备
# 代发01~03、代发04深圳：代发设备，不计入自营统计
EXCLUDED_DEVICE_NAMES = {'2005', '3005', '3006', '代发01', '代发02', '代发03', '代发 04 深圳'}

# x200u 折旧模型参数（来自 Excel）
# 购买价 = 5800 + 1499 = 7299
X200U_PURCHASE_PRICE = 7299.0
# Excel 中记录的购买日期：2025-08-01（E4=45870 换算）
X200U_PURCHASE_DATE = date(2025, 8, 1)


def _get_excluded_device_ids_from_db():
    """返回需要排除的设备 ID 集合（按 name 字段匹配编号）"""
    excluded = Device.query.filter(Device.name.in_(EXCLUDED_DEVICE_NAMES)).all()
    return {d.id for d in excluded}


def _get_model_id_by_name(model_name: str):
    """根据型号短名（x200u / x300pro / x300u）查找 model_id"""
    # 按 device_models.id 硬映射（防止 display_name 变更）
    id_map = {
        'x200u':   1,
        'x300pro': 7,
        'x300u':   11,
    }
    return id_map.get(model_name.lower())


@bp.route('/models', methods=['GET'])
def get_models():
    """返回可用的主设备型号列表（供前端下拉使用）"""
    try:
        models = DeviceModel.query.filter(
            DeviceModel.is_accessory == False,
            DeviceModel.is_active == True
        ).order_by(DeviceModel.id).all()
        data = [{'id': m.id, 'name': m.name, 'display_name': m.display_name} for m in models]
        return jsonify({'success': True, 'data': data})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


def _calc_period_depreciation(
    device_id: int,
    purchase_price: float,
    purchase_date: date,
    p_start: date,
    p_end: date,
) -> float:
    """
    计算单台设备在 [p_start, p_end] 内的折旧额
    公式：depreciation = price × [0.5^(weeks_start/52) - 0.5^(weeks_end/52)]
    purchase_date 视为设备"投入"日期（即第一笔订单日期）
    """
    weeks_start = (p_start - purchase_date).days / 7.0
    weeks_end = (p_end - purchase_date).days / 7.0
    residual_start = purchase_price * math.pow(0.5, max(0.0, weeks_start) / 52.0)
    residual_end   = purchase_price * math.pow(0.5, max(0.0, weeks_end)   / 52.0)
    return residual_start - residual_end


def _get_periods(period_type: str, start: date, end: date):
    """
    按 period_type ('week'|'month') 把 [start, end] 切成周期列表
    返回 [(period_label, period_start, period_end), ...]
    """
    periods = []
    if period_type == 'week':
        # 以 start 所在周一为第一周开始
        current = start - timedelta(days=start.weekday())
        while current <= end:
            period_end = current + timedelta(days=6)
            periods.append((
                f"{current.strftime('%Y-%m-%d')}",
                current,
                min(period_end, end)
            ))
            current = period_end + timedelta(days=1)
    else:  # month
        current = start.replace(day=1)
        while current <= end:
            # 月末
            if current.month == 12:
                month_end = current.replace(year=current.year + 1, month=1, day=1) - timedelta(days=1)
            else:
                month_end = current.replace(month=current.month + 1, day=1) - timedelta(days=1)
            periods.append((
                current.strftime('%Y-%m'),
                current,
                min(month_end, end)
            ))
            if current.month == 12:
                current = current.replace(year=current.year + 1, month=1, day=1)
            else:
                current = current.replace(month=current.month + 1, day=1)
    return periods


@bp.route('/periodic', methods=['GET'])
def get_periodic_stats():
    """
    按周或按月，按型号统计出租数据

    Query Params:
        period_type: 'week' | 'month'（默认 month）
        model: 'x200u' | 'x300pro' | 'x300u' | 'all'（默认 all）
        start_date: YYYY-MM-DD（默认一年前）
        end_date:   YYYY-MM-DD（默认今天）

    Response:
    {
        "success": true,
        "period_type": "month",
        "model": "x200u",
        "data": [
            {
                "period":        "2025-08",
                "period_start":  "2025-08-01",
                "period_end":    "2025-08-31",
                "device_count":  10,
                "order_count":   28,
                "rental_rate":   0.70,
                "order_amount":  4200.0,
                "profit":        3836.0
            },
            ...
        ],
        "summary": {
            "avg_rental_rate":   0.68,
            "total_order_amount": 12600.0,
            "total_profit":      11508.0,
            "total_orders":      84
        }
    }
    """
    try:
        period_type = request.args.get('period_type', 'month')
        model_filter = request.args.get('model', 'all')  # 'all' 或 model_id 整数字符串
        start_str = request.args.get('start_date')
        end_str = request.args.get('end_date')

        today = date.today()
        if start_str:
            start_date = datetime.strptime(start_str, '%Y-%m-%d').date()
        else:
            start_date = today - timedelta(days=365)
        if end_str:
            end_date = datetime.strptime(end_str, '%Y-%m-%d').date()
        else:
            end_date = today

        excluded = _get_excluded_device_ids_from_db()

        # 查询所有非附件设备（排除黑名单）
        device_query = Device.query.filter(
            Device.is_accessory == False,
            ~Device.id.in_(excluded)
        )
        if model_filter != 'all':
            try:
                filter_model_id = int(model_filter)
            except (ValueError, TypeError):
                # 兼容旧的短名传参（x200u / x300pro / x300u）
                filter_model_id = _get_model_id_by_name(model_filter)
            if filter_model_id is None:
                return jsonify({'success': False, 'error': f'未找到型号: {model_filter}'}), 400
            device_query = device_query.filter(Device.model_id == filter_model_id)
        all_devices = device_query.all()
        all_device_ids = {d.id for d in all_devices}

        # device_id -> purchase_price（来自 device_models.device_value）
        device_price: dict[int, float] = {}
        for d in all_devices:
            price = float(d.device_model.device_value) if d.device_model and d.device_model.device_value else 0.0
            device_price[d.id] = price

        # 查询范围内所有主租赁订单（排除 cancelled，排除黑名单设备）
        rentals_query = Rental.query.filter(
            Rental.parent_rental_id.is_(None),
            Rental.status != 'cancelled',
            Rental.device_id.in_(all_device_ids),
            Rental.start_date <= end_date,
            Rental.end_date >= start_date
        ).all()

        # 建立 device_id -> first_order_start_date 映射，用于确定设备"投入时间"
        device_first_order = {}
        for r in Rental.query.filter(
            Rental.parent_rental_id.is_(None),
            Rental.status != 'cancelled',
            Rental.device_id.in_(all_device_ids)
        ).order_by(Rental.start_date).all():
            if r.device_id not in device_first_order:
                device_first_order[r.device_id] = r.start_date

        periods = _get_periods(period_type, start_date, end_date)
        result = []

        for label, p_start, p_end in periods:
            # 该周期内"已投入"的设备：第一张订单开始日期 <= 周期结束
            active_device_ids = {
                did for did, first in device_first_order.items()
                if first <= p_end and did in all_device_ids
            }
            device_count = len(active_device_ids)

            # 该周期内的订单：start_date 在 [p_start, p_end]
            period_rentals = [
                r for r in rentals_query
                if r.start_date >= p_start and r.start_date <= p_end
                and r.device_id in active_device_ids
            ]

            order_count = len(period_rentals)
            order_amount = sum(
                float(r.order_amount) if r.order_amount is not None else 0.0
                for r in period_rentals
            )
            # 预计收益 = 订单金额 - 每订单 15 元快递费
            profit = order_amount - order_count * 15.0

            # 折旧：对该周期内每台活跃设备，以其 first_order_date 为购买日计算
            depreciation = sum(
                _calc_period_depreciation(
                    did,
                    device_price.get(did, 0.0),
                    device_first_order[did],   # 购买日 = 第一笔订单日
                    p_start,
                    p_end,
                )
                for did in active_device_ids
                if did in device_first_order
            )

            # 利润 = 预计收益 - 预计折旧
            net_profit = profit - depreciation

            # 出租率：
            #   按周 = 订单数 / 设备数（单周维度，每台设备最多 1 单）
            #   按月 = 订单数 / (设备数 × 本月周数)（消除月份长短差异）
            if device_count > 0:
                if period_type == 'month':
                    weeks_in_period = (p_end - p_start).days / 7.0
                    denominator = device_count * weeks_in_period
                else:
                    denominator = device_count
                rental_rate = round(order_count / denominator, 4) if denominator > 0 else 0.0
            else:
                rental_rate = 0.0

            avg_revenue_per_device = round(order_amount / device_count, 2) if device_count > 0 else 0.0

            result.append({
                'period': label,
                'period_start': p_start.isoformat(),
                'period_end': p_end.isoformat(),
                'device_count': device_count,
                'order_count': order_count,
                'rental_rate': rental_rate,
                'order_amount': round(order_amount, 2),
                'avg_revenue_per_device': avg_revenue_per_device,
                'profit': round(profit, 2),
                'depreciation': round(depreciation, 2),
                'net_profit': round(net_profit, 2),
            })

        # footer 汇总
        total_orders = sum(r['order_count'] for r in result)
        total_amount = sum(r['order_amount'] for r in result)
        total_profit = sum(r['profit'] for r in result)
        total_depreciation = sum(r['depreciation'] for r in result)
        total_net_profit = sum(r['net_profit'] for r in result)
        valid_periods = [r for r in result if r['device_count'] > 0]
        avg_rental_rate = (
            round(sum(r['rental_rate'] for r in valid_periods) / len(valid_periods), 4)
            if valid_periods else 0.0
        )

        return jsonify({
            'success': True,
            'period_type': period_type,
            'model': model_filter,
            'data': result,
            'summary': {
                'avg_rental_rate': avg_rental_rate,
                'total_order_amount': round(total_amount, 2),
                'avg_revenue_per_device': round(total_amount / sum(r['device_count'] for r in valid_periods), 2) if valid_periods else 0.0,
                'total_profit': round(total_profit, 2),
                'total_depreciation': round(total_depreciation, 2),
                'total_net_profit': round(total_net_profit, 2),
                'total_orders': total_orders
            }
        })

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500


@bp.route('/x200u-forecast', methods=['GET'])
def get_x200u_forecast():
    """
    x200u 年化收益率预测（5-8月）

    单价：对近 6 个完整月做线性回归，外推预测月单价
    年化收益率：历史实际净利润 + 未来预测净利润，累计到该月末后：
        累计年化 ROI = 累计净利润 / 总购买成本 / 已运营年数 × 100%
    """
    try:
        today = date.today()

        # ── 设备信息 ──────────────────────────────────────────
        excluded = _get_excluded_device_ids_from_db()
        x200u_model_id = _get_model_id_by_name('x200u')

        devices = Device.query.filter(
            Device.is_accessory == False,
            Device.model_id == x200u_model_id,
            ~Device.id.in_(excluded)
        ).all()
        device_count = len(devices)
        if device_count == 0:
            return jsonify({'success': False, 'error': '无 x200u 设备'}), 400

        purchase_price = float(devices[0].device_model.device_value) if devices[0].device_model and devices[0].device_model.device_value else X200U_PURCHASE_PRICE
        total_cost = purchase_price * device_count  # 总购买成本

        # device_id -> first_order_date（折旧计算起点）
        device_first_order: dict[int, date] = {}
        for r in Rental.query.filter(
            Rental.parent_rental_id.is_(None),
            Rental.status != 'cancelled',
            Rental.device_id.in_({d.id for d in devices})
        ).order_by(Rental.start_date).all():
            if r.device_id not in device_first_order:
                device_first_order[r.device_id] = r.start_date

        # 7月新投入设备数（通过 query param 传入，默认 0）
        new_devices_july = request.args.get('new_devices_july', 0, type=int)

        # ── 月度单价趋势（线性回归）──────────────────────────
        # 取近 6 个完整月（不含当月）的月均单价
        first_of_this_month = today.replace(day=1)
        rows = db.session.query(
            func.left(Rental.start_date.cast(db.String), 7).label('ym'),
            func.avg(Rental.order_amount).label('avg_amt'),
            func.count().label('cnt')
        ).join(Device, Device.id == Rental.device_id).filter(
            Device.model_id == x200u_model_id,
            Rental.parent_rental_id.is_(None),
            Rental.status != 'cancelled',
            Rental.order_amount.isnot(None),
            ~Device.id.in_(excluded),
            Rental.start_date < first_of_this_month
        ).group_by('ym').order_by('ym').all()

        # 取最近 6 个月（权重较高）
        recent = rows[-6:] if len(rows) >= 6 else rows
        if len(recent) >= 2:
            # 简单线性回归：x = 月序号（0,1,2...），y = avg_amt
            n = len(recent)
            xs = list(range(n))
            ys = [float(r.avg_amt) for r in recent]
            x_mean = sum(xs) / n
            y_mean = sum(ys) / n
            slope = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)) / \
                    sum((x - x_mean) ** 2 for x in xs)
            intercept = y_mean - slope * x_mean
            # 最近一个完整月的序号 = n-1，预测月从 n 开始
            base_idx = n  # 当月=n, 下一月=n+1...
        else:
            slope = 0.0
            intercept = float(recent[0].avg_amt) if recent else 178.0
            base_idx = 1

        def predicted_price(month_offset_from_base: int) -> float:
            """month_offset_from_base=0 表示当月，1=下月，以此类推"""
            p = intercept + slope * (base_idx + month_offset_from_base)
            return max(100.0, round(p, 2))  # 下限 100 元防止负值

        # ── 历史净利润（到上月末）────────────────────────────
        hist_end = first_of_this_month - timedelta(days=1)  # 上月末

        hist_rentals = Rental.query.join(Device).filter(
            Device.model_id == x200u_model_id,
            Rental.parent_rental_id.is_(None),
            Rental.status != 'cancelled',
            Rental.order_amount.isnot(None),
            ~Device.id.in_(excluded),
            Rental.start_date <= hist_end
        ).all()

        hist_revenue = sum(float(r.order_amount) for r in hist_rentals)
        hist_orders  = len(hist_rentals)
        hist_net_revenue = hist_revenue - hist_orders * 15.0  # 扣快递费

        # 历史折旧（对每台设备从 first_order_date 到上月末）
        hist_depreciation = sum(
            _calc_period_depreciation(did, purchase_price, fo, fo, hist_end)
            for did, fo in device_first_order.items()
            if fo <= hist_end
        )
        hist_net_profit = hist_net_revenue - hist_depreciation

        # 最早设备首单日期（用于计算已运营时长）
        earliest_first_order = min(device_first_order.values()) if device_first_order else today

        # ── 预测月份 ──────────────────────────────────────────
        # 当月也要用预测（因为只过了几天），5月=offset 0
        forecast_months = [
            {'label': '2026年5月', 'start': date(2026, 5, 1),  'end': date(2026, 5, 31),  'offset': 0},
            {'label': '2026年6月', 'start': date(2026, 6, 1),  'end': date(2026, 6, 30),  'offset': 1},
            {'label': '2026年7月', 'start': date(2026, 7, 1),  'end': date(2026, 7, 31),  'offset': 2},
            {'label': '2026年8月', 'start': date(2026, 8, 1),  'end': date(2026, 8, 31),  'offset': 3},
        ]

        # ── 场景计算 ──────────────────────────────────────────
        scenarios_def = {
            '乐观': 0.90,
            '中立': 0.70,
            '悲观': 0.50,
        }

        result = {}
        for scenario_name, rental_rate in scenarios_def.items():
            months_data = []
            cumulative_net = hist_net_profit  # 累计净利润初值=历史净利润

            for m in forecast_months:
                m_start = m['start']
                m_end   = m['end']
                offset  = m['offset']

                # 该月设备数（7月起加入新设备）
                month_device_count = device_count + (new_devices_july if m_start >= date(2026, 7, 1) else 0)

                # 该月预测单价
                avg_price = predicted_price(offset)

                weeks_in_month = (m_end - m_start).days / 7.0
                orders_per_device = rental_rate * weeks_in_month
                revenue_per_device = orders_per_device * (avg_price - 15.0)

                # 折旧：对已有设备用 first_order_date 作起点
                monthly_dep = sum(
                    _calc_period_depreciation(did, purchase_price, fo, m_start, m_end)
                    for did, fo in device_first_order.items()
                )
                # 新设备折旧（7月起，假设首单=7月1日）
                if new_devices_july > 0 and m_start >= date(2026, 7, 1):
                    new_dev_fo = date(2026, 7, 1)
                    new_dep_per = _calc_period_depreciation(0, purchase_price, new_dev_fo, m_start, m_end)
                    monthly_dep += new_dep_per * new_devices_july

                monthly_revenue = revenue_per_device * month_device_count
                monthly_net = monthly_revenue - monthly_dep

                cumulative_net += monthly_net

                # 累计年化 ROI：累计净利润 / 总成本 / 已运营年数
                period_end_months = (m_end.year - earliest_first_order.year) * 12 + (m_end.month - earliest_first_order.month) + 1
                years_operated = period_end_months / 12.0
                cum_cost = total_cost + (purchase_price * new_devices_july if new_devices_july > 0 and m_start >= date(2026, 7, 1) else 0)
                cum_annualized_roi = (cumulative_net / cum_cost / years_operated) * 100 if years_operated > 0 else 0.0

                months_data.append({
                    'month': m['label'],
                    'rental_rate': rental_rate,
                    'avg_order_price': round(avg_price, 2),
                    'orders_per_device': round(orders_per_device, 2),
                    'revenue_per_device': round(revenue_per_device, 2),
                    'depreciation_total': round(monthly_dep, 2),
                    'monthly_net': round(monthly_net, 2),
                    'cumulative_net': round(cumulative_net, 2),
                    'cum_annualized_roi': round(cum_annualized_roi, 2),
                    'device_count': month_device_count,
                })

            result[scenario_name] = {
                'rental_rate': rental_rate,
                'months': months_data,
                'hist_net_profit': round(hist_net_profit, 2),
                'total_net_at_aug_end': round(months_data[-1]['cumulative_net'], 2),
                'cum_annualized_roi_at_aug_end': round(months_data[-1]['cum_annualized_roi'], 2),
            }

        return jsonify({
            'success': True,
            'device_count': device_count,
            'purchase_price': purchase_price,
            'total_cost': round(total_cost, 2),
            'hist_net_profit': round(hist_net_profit, 2),
            'avg_order_amount': round(predicted_price(0), 2),  # 当月预测单价
            'price_slope': round(slope, 4),
            'scenarios': result
        })

    except Exception as e:
        import traceback
        return jsonify({'success': False, 'error': str(e), 'trace': traceback.format_exc()}), 500

