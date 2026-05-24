"""
批量发货API处理器
包含批量发货相关的请求处理逻辑
"""

from datetime import datetime
from flask import request, current_app
from app import db
from app.models.rental import Rental
from app.utils.response import (
    ApiResponse,
    success,
    bad_request,
    not_found,
    server_error
)
from app.services.shipping.waybill_print_service import get_waybill_print_service
from app.services.printing.kuaimai_service import KuaimaiPrintService


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
                scheduled_time = datetime.fromisoformat(scheduled_time_str.replace('Z', '+00:00'))
            except ValueError:
                return bad_request('时间格式无效，请使用ISO格式')

            # 获取服务实例
            from app.services.shipping.sf_express_service import get_sf_express_service
            from app.services.xianyu_order_service import get_xianyu_service

            sf_service = get_sf_express_service()
            xianyu_service = get_xianyu_service()

            # 查询租赁记录
            rentals = Rental.query.filter(Rental.id.in_(rental_ids)).all()

            success_count = 0
            failed_rentals = []
            results = []

            for rental in rentals:
                # 跳过已发货或已预约发货的订单
                if rental.status in ('shipped', 'scheduled_for_shipping'):
                    current_app.logger.info(f"Rental {rental.id} 已发货或已预约发货，跳过")
                    result_item = {
                        'success': False,
                        'rental_id': rental.id,
                        'message': '订单已发货或已预约发货',
                        'waybill_no': None
                    }
                    results.append(result_item)
                    failed_rentals.append({
                        'id': rental.id,
                        'reason': '订单已发货或已预约发货',
                        'waybill_no': None
                    })
                    continue

                try:
                    # 调用顺丰API下单
                    current_app.logger.info(f"预约发货: Rental {rental.id}, 预约时间: {scheduled_time}")
                    sf_result = sf_service.place_shipping_order(rental, scheduled_time=scheduled_time)

                    if not sf_result.get('success'):
                        error_msg = sf_result.get('message', '未知错误')
                        current_app.logger.error(f"Rental {rental.id} 顺丰下单失败: {error_msg}")
                        result_item = {
                            'success': False,
                            'rental_id': rental.id,
                            'message': f'顺丰下单失败: {error_msg}',
                            'waybill_no': None
                        }
                        results.append(result_item)
                        failed_rentals.append({
                            'id': rental.id,
                            'reason': f'顺丰下单失败: {error_msg}',
                            'waybill_no': None
                        })
                        continue

                    # 获取运单号
                    waybill_no = sf_result.get('waybill_no')
                    if not waybill_no:
                        error_msg = '顺丰API未返回运单号'
                        current_app.logger.error(f"Rental {rental.id} {error_msg}")
                        result_item = {
                            'success': False,
                            'rental_id': rental.id,
                            'message': error_msg,
                            'waybill_no': None
                        }
                        results.append(result_item)
                        failed_rentals.append({
                            'id': rental.id,
                            'reason': error_msg,
                            'waybill_no': None
                        })
                        continue

                    current_app.logger.info(f"Rental {rental.id} 顺丰下单成功，运单号: {waybill_no}")

                    # 保存运单号和预约时间
                    rental.ship_out_tracking_no = waybill_no
                    rental.scheduled_ship_time = scheduled_time
                    rental.status = 'scheduled_for_shipping'

                    success_count += 1
                    result_item = {
                        'success': True,
                        'rental_id': rental.id,
                        'message': '预约发货成功',
                        'waybill_no': waybill_no
                    }
                    results.append(result_item)
                    current_app.logger.info(f"Rental {rental.id} 预约发货成功，运单号: {waybill_no}")

                except Exception as e:
                    current_app.logger.error(f"处理 Rental {rental.id} 时发生异常: {e}")
                    result_item = {
                        'success': False,
                        'rental_id': rental.id,
                        'message': f'系统异常: {str(e)}',
                        'waybill_no': None
                    }
                    results.append(result_item)
                    failed_rentals.append({
                        'id': rental.id,
                        'reason': f'系统异常: {str(e)}',
                        'waybill_no': None
                    })

            # 提交数据库更改
            db.session.commit()

            current_app.logger.info(f"预约发货完成: 成功 {success_count} 个, 失败 {len(failed_rentals)} 个")

            return success(data={
                'scheduled_count': success_count,
                'failed_rentals': failed_rentals,
                'results': results
            })

        except Exception as e:
            current_app.logger.error(f"预约发货失败: {e}")
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
            kuaimai_service = KuaimaiPrintService()

            # 检查服务是否已配置
            if not kuaimai_service.configured:
                return bad_request('快麦云打印服务未配置，请设置环境变量 KUAIMAI_APP_ID 和 KUAIMAI_APP_SECRET')

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

        except Exception as e:
            current_app.logger.error(f"获取打印机配置失败: {e}")
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
                'waybill_success_count': result['waybill_success_count'],
                'failed_count': result['failed_count'],
                'results': result['results']
            }

            if include_shipping_slips:
                response_data['slip_success_count'] = result['slip_success_count']

            return success(data=response_data)

        except Exception as e:
            current_app.logger.error(f"批量打印快递面单失败: {e}")
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
            xianyu_service = get_xianyu_service()

            # 调用闲鱼API
            current_app.logger.info(f"手动发货到闲鱼: Rental {rental_id}, Order {rental.xianyu_order_no}")
            xianyu_result = xianyu_service.ship_order(rental)

            if not xianyu_result.get('success'):
                error_msg = xianyu_result.get('message', '未知错误')
                current_app.logger.error(f"Rental {rental_id} 闲鱼发货失败: {error_msg}")
                return bad_request(f'闲鱼发货失败: {error_msg}')

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
            current_app.logger.error(f"发货到闲鱼失败: {e}")
            db.session.rollback()
            return server_error('发货到闲鱼失败')
