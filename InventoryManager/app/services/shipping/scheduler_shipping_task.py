"""
定时发货任务
"""

from datetime import datetime
import logging
from typing import Optional, List, Dict
from app import db
from app.models.rental import Rental
from app.services.shipping.sf_express_service import get_sf_express_service
from app.services.xianyu_order_service import get_xianyu_service

logger = logging.getLogger(__name__)


def _execute_shipment(rental: Rental, sf_service, xianyu_service) -> Dict:
    """
    执行单个订单的发货操作

    Args:
        rental: 租赁记录
        sf_service: 顺丰服务实例
        xianyu_service: 闲鱼服务实例

    Returns:
        Dict: {'sf_success': bool, 'xianyu_success': bool, 'error': str}
    """
    result = {
        'sf_success': False,
        'xianyu_success': False,
        'error': None
    }

    # 1. 调用顺丰API下单
    try:
        sf_result = sf_service.place_shipping_order(rental)
        if sf_result.get('success'):
            logger.info(f"Rental {rental.id} 顺丰下单成功")
            result['sf_success'] = True
        else:
            error_msg = sf_result.get('message', '未知错误')
            logger.error(f"Rental {rental.id} 顺丰下单失败: {error_msg}")
            result['error'] = f"顺丰下单失败: {error_msg}"
    except Exception as e:
        logger.error(f"Rental {rental.id} 顺丰下单异常: {e}")
        result['error'] = f"顺丰下单异常: {str(e)}"

    # 2. 调用闲鱼API发货通知（仅在顺丰成功且有闲鱼订单号时）
    if result['sf_success']:
        if rental.xianyu_order_no:
            try:
                xianyu_result = xianyu_service.ship_order(rental)
                if xianyu_result.get('success'):
                    logger.info(f"Rental {rental.id} 闲鱼发货通知成功")
                    result['xianyu_success'] = True
                elif xianyu_result.get('skipped'):
                    logger.info(f"Rental {rental.id} 闲鱼发货通知跳过")
                    result['xianyu_success'] = True  # 跳过也算成功
                else:
                    error_msg = xianyu_result.get('message', '未知错误')
                    logger.error(f"Rental {rental.id} 闲鱼发货通知失败: {error_msg}")
                    result['error'] = f"闲鱼发货失败: {error_msg}"
            except Exception as e:
                logger.error(f"Rental {rental.id} 闲鱼发货通知异常: {e}")
                result['error'] = f"闲鱼发货异常: {str(e)}"
        else:
            logger.info(f"Rental {rental.id} 没有闲鱼订单号，跳过闲鱼通知")
            result['xianyu_success'] = True  # 没有订单号不算失败

    return result


def _process_rentals_batch(
    rentals: List[Rental],
    max_retries: int = 1,
    update_status: bool = True
) -> Dict:
    """
    批量处理租赁记录的发货

    Args:
        rentals: 租赁记录列表
        max_retries: 最大重试次数（默认1次，即不重试）
        update_status: 是否更新rental状态为shipped

    Returns:
        Dict: 统计结果
    """
    if not rentals:
        return {'total': 0, 'success': 0, 'failed': 0, 'skipped': 0}

    # 获取服务实例
    sf_service = get_sf_express_service()
    xianyu_service = get_xianyu_service()

    success_count = 0
    failed_count = 0
    skipped_count = 0

    for rental in rentals:
        try:
            # 跳过已发货的订单
            if rental.status == 'shipped':
                logger.info(f"Rental {rental.id} 已发货，跳过")
                skipped_count += 1
                continue

            # 尝试发货（含重试逻辑）
            shipment_success = False
            last_error = None

            for attempt in range(max_retries):
                if max_retries > 1:
                    logger.info(f"处理 Rental {rental.id}, 第 {attempt + 1}/{max_retries} 次")
                else:
                    logger.info(f"处理租赁记录 {rental.id}")

                result = _execute_shipment(rental, sf_service, xianyu_service)

                # 判断是否成功：顺丰成功 且 (没有闲鱼订单号 或 闲鱼成功)
                if result['sf_success'] and (not rental.xianyu_order_no or result['xianyu_success']):
                    shipment_success = True

                    if update_status:
                        rental.status = 'shipped'
                        rental.ship_out_time = datetime.utcnow()
                        db.session.commit()
                        logger.info(f"Rental {rental.id} 状态已更新为shipped")

                    success_count += 1
                    break
                else:
                    last_error = result.get('error', '未知错误')
                    if attempt < max_retries - 1:
                        logger.warning(f"Rental {rental.id} 第 {attempt + 1} 次尝试失败，准备重试")

            if not shipment_success:
                logger.error(f"Rental {rental.id} 发货失败: {last_error}")
                failed_count += 1
                db.session.rollback()

        except Exception as e:
            logger.error(f"处理 Rental {rental.id} 时发生异常: {e}")
            db.session.rollback()
            failed_count += 1

    return {
        'total': len(rentals),
        'success': success_count,
        'failed': failed_count,
        'skipped': skipped_count
    }


def process_scheduled_shipments():
    """
    处理预约发货任务

    检查所有到达预约时间的租赁记录，执行发货操作：
    1. 调用顺丰API下单
    2. 调用闲鱼API发货通知
    3. 更新rental状态为shipped
    """
    import traceback

    logger.info("开始处理预约发货任务")

    try:
        # 查询需要发货的租赁记录
        logger.info("正在查询数据库...")
        rentals = Rental.query.filter(
            Rental.scheduled_ship_time.isnot(None),
            Rental.status != 'shipped',
            Rental.ship_out_tracking_no.isnot(None)
        ).all()

        logger.info(f"数据库查询完成，找到 {len(rentals)} 条记录")

        if not rentals:
            logger.info("没有需要发货的订单")
            return {
                'total': 0,
                'success': 0,
                'failed': 0,
                'skipped': 0
            }

        logger.info(f"找到 {len(rentals)} 个待发货订单")

        # 使用统一的批量处理函数
        result = _process_rentals_batch(rentals, max_retries=1, update_status=True)

        logger.info(f"预约发货任务完成: {result}")
        return result

    except Exception as e:
        logger.error(f"预约发货任务执行异常: {type(e).__name__}: {e}")
        logger.error(f"完整堆栈:\n{traceback.format_exc()}")
        return {
            'total': 0,
            'success': 0,
            'failed': 0,
            'skipped': 0,
            'error': str(e)
        }


def retry_failed_shipments(rental_ids: Optional[List[int]] = None, max_retries: int = 3):
    """
    重试失败的发货

    Args:
        rental_ids: 需要重试的租赁记录ID列表，如果为None则重试所有预约过但未发货的
        max_retries: 最大重试次数

    Returns:
        Dict: 重试结果统计
    """
    logger.info(f"开始重试发货任务, rental_ids={rental_ids}, max_retries={max_retries}")

    # 查询需要重试的租赁记录
    query = Rental.query.filter(
        Rental.scheduled_ship_time.isnot(None),
        Rental.status != 'shipped',
        Rental.ship_out_tracking_no.isnot(None)
    )

    if rental_ids:
        query = query.filter(Rental.id.in_(rental_ids))

    rentals = query.all()

    if not rentals:
        logger.info("没有需要重试的订单")
        return {
            'total': 0,
            'success': 0,
            'failed': 0,
            'skipped': 0
        }

    logger.info(f"找到 {len(rentals)} 个需要重试的订单")

    # 使用统一的批量处理函数，启用重试逻辑
    result = _process_rentals_batch(rentals, max_retries=max_retries, update_status=True)

    logger.info(f"重试发货任务完成: {result}")
    return result
