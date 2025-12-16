"""
批量发货 API 路由模块
"""

from flask import Blueprint, request, jsonify
from app import db
from app.models.rental import Rental
from app.services.shipping.waybill_print_service import get_waybill_print_service
from app.services.printing.kuaimai_service import KuaimaiPrintService
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

bp = Blueprint('shipping_batch', __name__, url_prefix='/api/shipping-batch')


@bp.route('/schedule', methods=['POST'])
def schedule_shipment():
    """
    预约发货

    接收租赁ID列表和预约时间，立即向顺丰下单（将预约时间作为sendStartTm参数）
    """
    try:
        data = request.get_json()
        rental_ids = data.get('rental_ids', [])
        scheduled_time_str = data.get('scheduled_time')

        if not rental_ids or not scheduled_time_str:
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
            }), 400

        # 解析预约时间
        try:
            scheduled_time = datetime.fromisoformat(scheduled_time_str.replace('Z', '+00:00'))
        except ValueError:
            return jsonify({
                'success': False,
                'message': '时间格式无效'
            }), 400

        # 查询租赁记录
        rentals = Rental.query.filter(Rental.id.in_(rental_ids)).all()

        # 获取服务实例
        from app.services.shipping.sf_express_service import get_sf_express_service
        from app.services.xianyu_order_service import get_xianyu_service

        sf_service = get_sf_express_service()
        xianyu_service = get_xianyu_service()

        success_count = 0
        failed_rentals = []
        results = []

        for rental in rentals:
            # 跳过已发货的订单
            if rental.status == 'shipped':
                logger.info(f"Rental {rental.id} 已发货，跳过")
                result_item = {
                    'success': False,
                    'rental_id': rental.id,
                    'message': '订单已发货',
                    'waybill_no': None
                }
                results.append(result_item)
                failed_rentals.append({
                    'id': rental.id,
                    'reason': '订单已发货',
                    'waybill_no': None
                })
                continue

            try:
                # 1. 调用顺丰API下单，传入预约时间，自动获取运单号
                logger.info(f"预约发货: Rental {rental.id}, 预约时间: {scheduled_time}")
                sf_result = sf_service.place_shipping_order(rental, scheduled_time=scheduled_time)

                if not sf_result.get('success'):
                    error_msg = sf_result.get('message', '未知错误')
                    logger.error(f"Rental {rental.id} 顺丰下单失败: {error_msg}")
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

                # 从顺丰API响应中获取运单号
                waybill_no = sf_result.get('waybill_no')
                if not waybill_no:
                    error_msg = '顺丰API未返回运单号'
                    logger.error(f"Rental {rental.id} {error_msg}")
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

                logger.info(f"Rental {rental.id} 顺丰下单成功，运单号: {waybill_no}")

                # 保存运单号到数据库
                rental.ship_out_tracking_no = waybill_no

                # 2. 调用闲鱼API发货通知（如果有闲鱼订单号）
                if rental.xianyu_order_no:
                    xianyu_result = xianyu_service.ship_order(rental)
                    if not xianyu_result.get('success') and not xianyu_result.get('skipped'):
                        error_msg = xianyu_result.get('message', '未知错误')
                        logger.error(f"Rental {rental.id} 闲鱼发货通知失败: {error_msg}")
                        result_item = {
                            'success': False,
                            'rental_id': rental.id,
                            'message': f'闲鱼发货失败: {error_msg}',
                            'waybill_no': waybill_no
                        }
                        results.append(result_item)
                        failed_rentals.append({
                            'id': rental.id,
                            'reason': f'闲鱼发货失败: {error_msg}',
                            'waybill_no': waybill_no
                        })
                        continue

                # 3. 更新租赁记录状态
                rental.scheduled_ship_time = scheduled_time
                rental.status = 'shipped'
                rental.ship_out_time = datetime.utcnow()

                success_count += 1
                result_item = {
                    'success': True,
                    'rental_id': rental.id,
                    'message': '预约发货成功',
                    'waybill_no': waybill_no
                }
                results.append(result_item)
                logger.info(f"Rental {rental.id} 预约发货成功，运单号: {waybill_no}")

            except Exception as e:
                logger.error(f"处理 Rental {rental.id} 时发生异常: {e}")
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

        logger.info(f"预约发货完成: 成功 {success_count} 个, 失败 {len(failed_rentals)} 个")

        return jsonify({
            'success': True,
            'data': {
                'scheduled_count': success_count,
                'failed_rentals': failed_rentals,
                'results': results
            }
        }), 200

    except Exception as e:
        logger.error(f"预约发货失败: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500


@bp.route('/status', methods=['GET'])
def get_status():
    """
    获取批量发货状态摘要

    返回各状态的订单数量
    """
    try:
        # 获取查询参数
        start_date = request.args.get('start_date')
        end_date = request.args.get('end_date')
        rental_ids_str = request.args.get('rental_ids')

        # 构建基础查询
        query = Rental.query

        if rental_ids_str:
            rental_ids = [int(id) for id in rental_ids_str.split(',')]
            query = query.filter(Rental.id.in_(rental_ids))
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

        return jsonify({
            'success': True,
            'data': {
                'total': total,
                'waybill_recorded': waybill_recorded,
                'scheduled': scheduled,
                'shipped': shipped
            }
        }), 200

    except Exception as e:
        logger.error(f"获取状态失败: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500


@bp.route('/express-type', methods=['PATCH'])
def update_express_type():
    """
    更新租赁订单的快递类型

    接收租赁ID和快递类型ID，更新数据库
    """
    try:
        data = request.get_json()
        rental_id = data.get('rental_id')
        express_type_id = data.get('express_type_id')

        # 验证参数
        if not rental_id or express_type_id is None:
            return jsonify({
                'success': False,
                'message': '缺少必要参数'
            }), 400

        # 验证快递类型ID
        if express_type_id not in [1, 2, 6]:
            return jsonify({
                'success': False,
                'message': '快递类型无效'
            }), 400

        # 查询租赁记录
        rental = Rental.query.get(rental_id)

        if not rental:
            return jsonify({
                'success': False,
                'message': '租赁记录不存在'
            }), 404

        # 更新快递类型
        rental.express_type_id = express_type_id
        db.session.commit()

        logger.info(f"快递类型已更新: Rental {rental_id}, ExpressType {express_type_id}")

        return jsonify({
            'success': True,
            'message': '快递类型已更新'
        }), 200

    except Exception as e:
        logger.error(f"更新快递类型失败: {e}")
        db.session.rollback()
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500


@bp.route('/printers', methods=['GET'])
def get_printers():
    """
    获取打印机配置信息

    返回默认打印机SN（如果已配置）
    """
    try:
        kuaimai_service = KuaimaiPrintService()

        # 检查服务是否已配置
        if not kuaimai_service.configured:
            return jsonify({
                'success': False,
                'message': '快麦云打印服务未配置，请设置环境变量 KUAIMAI_APP_ID 和 KUAIMAI_APP_SECRET'
            }), 503

        # 返回默认打印机信息作为数组（保持与前端的兼容性）
        printers = []
        if kuaimai_service.default_printer_sn:
            printers.append({
                'id': kuaimai_service.default_printer_sn,  # 前端使用 id 字段
                'sn': kuaimai_service.default_printer_sn,
                'name': '默认打印机',
                'is_default': True
            })

        return jsonify({
            'success': True,
            'data': {
                'printers': printers,
                'message': '快麦打印机通过SN直接配置' if printers else '未配置打印机SN'
            }
        }), 200

    except Exception as e:
        logger.error(f"获取打印机配置失败: {e}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500


@bp.route('/print-waybills', methods=['POST'])
def print_waybills():
    """
    批量打印快递面单

    接收租赁ID列表，使用环境变量中配置的默认打印机打印所有面单
    """
    try:
        data = request.get_json()
        rental_ids = data.get('rental_ids', [])

        # 验证参数
        if not rental_ids:
            return jsonify({
                'success': False,
                'message': '缺少租赁ID列表'
            }), 400

        # 限制批量打印数量
        if len(rental_ids) > 100:
            return jsonify({
                'success': False,
                'message': '批量打印数量不能超过100个'
            }), 400

        logger.info(f"批量打印快递面单: {len(rental_ids)}个订单")

        # 调用面单打印服务（使用默认打印机）
        waybill_service = get_waybill_print_service()
        result = waybill_service.batch_print_waybills(
            rental_ids=rental_ids
        )

        # 返回结果
        return jsonify({
            'success': True,
            'data': {
                'total': result['total'],
                'success_count': result['success_count'],
                'failed_count': result['failed_count'],
                'results': result['results']
            }
        }), 200

    except Exception as e:
        import traceback
        logger.error(f"批量打印快递面单失败: {e}")
        logger.error(f"完整堆栈:\n{traceback.format_exc()}")
        return jsonify({
            'success': False,
            'message': f'服务器错误: {str(e)}'
        }), 500
