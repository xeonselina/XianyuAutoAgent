"""
批量发货API处理器
包含批量发货相关的请求处理逻辑
"""

from datetime import datetime
from flask import request, current_app
from app import db
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.utils.response import (
    ApiResponse,
    success,
    error,
    bad_request,
    not_found,
    server_error
)
from app.services.integration_resolver import (
    ConfigurationIncomplete,
    IntegrationResolver,
)
from app.services.rental.rental_service import WarehouseMismatchError
from app.services.shipping.waybill_print_service import (
    get_waybill_print_service,
    sf_client_order_id_for,
    validate_shipping_preflight,
)
from app.utils.business_time import parse_business_datetime


class ShippingBatchHandlers:
    """批量发货处理器类"""

    @staticmethod
    def handle_schedule_shipment() -> ApiResponse:
        """处理预约发货请求"""
        try:
            data = request.get_json() or {}
            rental_ids = data.get('rental_ids', [])
            scheduled_time_str = data.get('scheduled_time')

            # 验证参数
            if not rental_ids or not scheduled_time_str:
                return bad_request('缺少必要参数: rental_ids 和 scheduled_time')

            # 解析预约时间
            try:
                scheduled_time = parse_business_datetime(scheduled_time_str)
            except (AttributeError, TypeError, ValueError):
                return bad_request('时间格式无效，请使用ISO格式')

            if not isinstance(rental_ids, list) or len(rental_ids) > 100 or any(type(i) is not int for i in rental_ids):
                return bad_request('租赁ID列表无效或超过100台')
            from app.services.shipping.shipment_group_service import group_shipments
            rentals = Rental.query.filter(Rental.id.in_(rental_ids)).order_by(Rental.id).all()
            relay_ids = {i for (i,) in db.session.query(RentalRelayBinding.successor_rental_id).filter(
                RentalRelayBinding.successor_rental_id.in_(rental_ids)).all()}
            groups = group_shipments(rentals, relay_ids)
            results = []
            for missing_id in set(rental_ids) - {r.id for r in rentals}:
                results.append({'success': False, 'rental_id': missing_id, 'message': '租赁记录不存在', 'waybill_no': None})
            shipment_count = 0
            for initial_group in groups:
                ids = [r.id for r in initial_group]
                try:
                    # A current read serializes duplicate submissions before contacting SF.
                    members = Rental.query.filter(Rental.id.in_(ids)).order_by(Rental.id).populate_existing().with_for_update().all()
                    if len(members) != len(ids) or len(group_shipments(members, relay_ids)) != 1:
                        raise ValueError('订单信息已变化，请刷新后重新选择')
                    for member in members:
                        if member.id in relay_ids:
                            raise ValueError('接力订单由前一位客户直接寄出，不能批量预约发货')
                        if member.status != 'not_shipped':
                            raise ValueError('订单已发货或已预约发货，不能重复预约')
                        validate_shipping_preflight(member)
                    rental = members[0]
                    sf_service = IntegrationResolver().sf_for_rental(rental)
                    kwargs = {'machine_count': len(members)} if len(members) > 1 else {}
                    sf_result = sf_service.place_shipping_order(
                        rental, scheduled_time=scheduled_time,
                        client_order_id=sf_client_order_id_for(rental), **kwargs)
                    if not sf_result.get('success') or not sf_result.get('waybill_no'):
                        raise RuntimeError('顺丰服务调用失败')
                    waybill_no = sf_result['waybill_no']
                    for member in members:
                        member.ship_out_tracking_no = waybill_no
                        member.scheduled_ship_time = scheduled_time
                        member.status = 'scheduled_for_shipping'
                    db.session.commit()
                    shipment_count += 1
                    results.extend({'success': True, 'rental_id': i, 'message': '预约发货成功',
                                    'waybill_no': waybill_no, 'parcel_rental_ids': ids} for i in ids)
                except Exception as exc:
                    db.session.rollback()
                    code = 'EXTERNAL_SERVICE_ERROR'
                    message = '顺丰服务调用失败'
                    if isinstance(exc, ConfigurationIncomplete):
                        code, message = 'CONFIG_INCOMPLETE', '仓库发货配置或收件信息不完整'
                    elif isinstance(exc, WarehouseMismatchError):
                        code, message = 'WAREHOUSE_MISMATCH', str(exc)
                    elif isinstance(exc, ValueError):
                        code, message = 'VALIDATION_ERROR', str(exc)
                    current_app.logger.warning('批量预约失败: %s', type(exc).__name__)
                    results.extend({'success': False, 'rental_id': i, 'message': message,
                                    'code': code, 'waybill_no': None} for i in ids)
            failed = [{'id': r['rental_id'], 'reason': r['message'], 'code': r.get('code'), 'waybill_no': None}
                      for r in results if not r['success']]
            return success(data={'scheduled_count': sum(r['success'] for r in results),
                                 'shipment_count': shipment_count, 'failed_rentals': failed, 'results': results})

        except Exception as e:
            current_app.logger.error(
                f"预约发货失败: {type(e).__name__}"
            )
            db.session.rollback()
            return server_error('预约发货失败')

    @staticmethod
    def handle_get_status() -> ApiResponse:
        """处理获取批量发货状态请求"""
        try:
            # 获取查询参数
            start_date = request.args.get('start_date')
            end_date = request.args.get('end_date')
            rental_ids_str = request.args.get('rental_ids')

            # 构建基础查询
            query = Rental.query

            if rental_ids_str:
                try:
                    rental_ids = [int(id) for id in rental_ids_str.split(',')]
                    query = query.filter(Rental.id.in_(rental_ids))
                except ValueError:
                    return bad_request('租赁ID格式无效')
            elif start_date and end_date:
                query = query.filter(
                    Rental.ship_out_time >= start_date,
                    Rental.ship_out_time <= end_date
                )

            rentals = query.all()

            # 统计各状态数量
            total = len(rentals)
            waybill_recorded = sum(1 for r in rentals if r.ship_out_tracking_no)
            scheduled = sum(1 for r in rentals if r.scheduled_ship_time)
            shipped = sum(1 for r in rentals if r.status == 'shipped')

            return success(data={
                'total': total,
                'waybill_recorded': waybill_recorded,
                'scheduled': scheduled,
                'shipped': shipped
            })

        except Exception as e:
            current_app.logger.error(f"获取状态失败: {e}")
            return server_error('获取状态失败')

    @staticmethod
    def handle_update_express_type() -> ApiResponse:
        """处理更新快递类型请求"""
        try:
            data = request.get_json() or {}
            rental_id = data.get('rental_id')
            express_type_id = data.get('express_type_id')

            # 验证参数
            if not rental_id or express_type_id is None:
                return bad_request('缺少必要参数: rental_id 和 express_type_id')

            # 验证快递类型ID
            if express_type_id not in [1, 2, 263]:
                return bad_request('快递类型无效')

            # 查询租赁记录
            rental = Rental.query.get(rental_id)
            if not rental:
                return not_found('租赁记录不存在')

            # 更新快递类型
            rental.express_type_id = express_type_id
            db.session.commit()

            current_app.logger.info(f"快递类型已更新: Rental {rental_id}, ExpressType {express_type_id}")

            return success(message='快递类型已更新')

        except Exception as e:
            current_app.logger.error(f"更新快递类型失败: {e}")
            db.session.rollback()
            return server_error('更新快递类型失败')

    @staticmethod
    def handle_get_printers() -> ApiResponse:
        """处理获取打印机配置请求"""
        try:
            raw_warehouse_id = request.args.get('warehouse_id')
            if raw_warehouse_id in (None, '', 'all'):
                return bad_request('请指定仓库')
            try:
                warehouse_id = int(raw_warehouse_id)
            except (TypeError, ValueError):
                return bad_request('仓库不存在')
            kuaimai_service = IntegrationResolver().kuaimai_for_warehouse(
                warehouse_id
            )

            # 返回默认打印机信息
            printers = []
            if kuaimai_service.default_printer_sn:
                printers.append({
                    'id': kuaimai_service.default_printer_sn,
                    'sn': kuaimai_service.default_printer_sn,
                    'name': '默认打印机',
                    'is_default': True
                })

            return success(data={
                'printers': printers,
                'message': '快麦打印机通过SN直接配置' if printers else '未配置打印机SN'
            })

        except ConfigurationIncomplete:
            return error(
                '仓库快麦配置不完整', status_code=400,
                code='CONFIG_INCOMPLETE',
            )
        except Exception as e:
            current_app.logger.error(
                f"获取打印机配置失败: {type(e).__name__}"
            )
            return server_error('获取打印机配置失败')

    @staticmethod
    def handle_print_waybills() -> ApiResponse:
        """处理批量打印快递面单请求"""
        try:
            data = request.get_json() or {}
            rental_ids = data.get('rental_ids', [])
            include_shipping_slips = data.get('include_shipping_slips', True)

            # 验证参数
            if not rental_ids:
                return bad_request('缺少租赁ID列表')

            # 限制批量打印数量
            if len(rental_ids) > 100:
                return bad_request('批量打印数量不能超过100个')

            current_app.logger.info(f"批量打印快递面单: {len(rental_ids)}个订单, 交替打印发货单: {include_shipping_slips}")

            # 调用面单打印服务
            waybill_service = get_waybill_print_service()
            result = waybill_service.batch_print_waybills(
                rental_ids=rental_ids,
                include_shipping_slips=include_shipping_slips
            )

            # 构建响应数据
            response_data = {
                'total': result['total'],
                'parcel_count': result.get('parcel_count', result['total']),
                'waybill_success_count': result['waybill_success_count'],
                'failed_count': result['failed_count'],
                'results': result['results']
            }

            if include_shipping_slips:
                response_data['slip_success_count'] = result['slip_success_count']

            return success(data=response_data)

        except Exception as e:
            current_app.logger.error(f"批量打印快递面单失败: {type(e).__name__}")
            return server_error('批量打印快递面单失败')

    @staticmethod
    def handle_ship_to_xianyu(rental_id: int) -> ApiResponse:
        """处理发货到闲鱼请求"""
        try:
            # 查询租赁记录
            rental = Rental.query.get(rental_id)
            if not rental:
                return not_found('租赁记录不存在')

            # 验证必要字段
            if not rental.xianyu_order_no:
                return bad_request('缺少闲鱼订单号')

            if not rental.ship_out_tracking_no:
                return bad_request('缺少发货单号')

            # 检查状态
            if rental.status not in ('not_shipped', 'scheduled_for_shipping'):
                return bad_request(f'当前状态不允许发货: {rental.status}')

            # 获取闲鱼服务实例
            from app.services.xianyu_order_service import get_xianyu_service
            xianyu_service = get_xianyu_service(rental=rental)

            # 调用闲鱼API
            xianyu_result = xianyu_service.ship_order(rental)

            if not xianyu_result.get('success'):
                current_app.logger.error("Rental %s 闲鱼发货失败", rental_id)
                return bad_request('闲鱼发货失败')

            # 更新租赁状态
            rental.status = 'shipped'
            if not rental.ship_out_time:
                rental.ship_out_time = datetime.utcnow()

            db.session.commit()
            current_app.logger.info(f"Rental {rental_id} 发货到闲鱼成功")

            return success(
                data=xianyu_result.get('data'),
                message='发货到闲鱼成功'
            )

        except Exception as e:
            current_app.logger.error("发货到闲鱼失败，类型: %s", type(e).__name__)
            db.session.rollback()
            return server_error('发货到闲鱼失败')
