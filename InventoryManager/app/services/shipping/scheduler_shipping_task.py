"""
定时发货任务
"""

from datetime import datetime
import logging
from app import db
from app.models.rental import Rental
from app.services.shipping.sf_express_service import get_sf_express_service
from app.services.xianyu_order_service import get_xianyu_service

logger = logging.getLogger(__name__)


def process_scheduled_shipments():
    """
    处理预约发货任务

    检查所有到达预约时间的租赁记录，执行发货操作：
    1. 调用顺丰API下单
    2. 调用闲鱼API发货通知
    3. 更新rental状态为shipped
    """
    logger.info("开始处理预约发货任务")

    # 获取服务实例
    sf_service = get_sf_express_service()
    xianyu_service = get_xianyu_service()

    # 查询需要发货的租赁记录
    now = datetime.utcnow()
    rentals = Rental.query.filter(
        Rental.scheduled_ship_time <= now,
        Rental.status != 'shipped',
        Rental.ship_out_tracking_no.isnot(None)
    ).all()

    if not rentals:
        logger.info("没有需要发货的订单")
        return {
            'total': 0,
            'success': 0,
            'failed': 0,
            'skipped': 0
        }

    logger.info(f"找到 {len(rentals)} 个待发货订单")

    # 统计结果
    success_count = 0
    failed_count = 0
    skipped_count = 0

    for rental in rentals:
        try:
            logger.info(f"处理租赁记录 {rental.id}")

            # 如果已经是shipped状态，跳过
            if rental.status == 'shipped':
                logger.info(f"Rental {rental.id} 已发货，跳过")
                skipped_count += 1
                continue

            # 标记是否成功
            sf_success = False
            xianyu_success = False

            # 1. 调用顺丰API下单
            try:
                sf_result = sf_service.place_shipping_order(rental)
                if sf_result.get('success'):
                    logger.info(f"Rental {rental.id} 顺丰下单成功")
                    sf_success = True
                else:
                    logger.error(f"Rental {rental.id} 顺丰下单失败: {sf_result.get('message')}")
                    # 顺丰失败，记录错误但继续处理闲鱼
            except Exception as e:
                logger.error(f"Rental {rental.id} 顺丰下单异常: {e}")

            # 2. 调用闲鱼API发货通知（如果有闲鱼订单号）
            if rental.xianyu_order_no:
                try:
                    xianyu_result = xianyu_service.ship_order(rental)
                    if xianyu_result.get('success'):
                        logger.info(f"Rental {rental.id} 闲鱼发货通知成功")
                        xianyu_success = True
                    elif xianyu_result.get('skipped'):
                        logger.info(f"Rental {rental.id} 闲鱼发货通知跳过")
                        xianyu_success = True  # 跳过也算成功
                    else:
                        logger.error(f"Rental {rental.id} 闲鱼发货通知失败: {xianyu_result.get('message')}")
                except Exception as e:
                    logger.error(f"Rental {rental.id} 闲鱼发货通知异常: {e}")
            else:
                logger.info(f"Rental {rental.id} 没有闲鱼订单号，跳过闲鱼通知")
                xianyu_success = True  # 没有订单号不算失败

            # 3. 如果至少顺丰成功，或者只有闲鱼订单且闲鱼成功，则更新状态
            # 这里的策略是：只要有一个成功就算发货成功
            if sf_success or (xianyu_success and not rental.xianyu_order_no):
                rental.status = 'shipped'
                rental.ship_out_time = now
                db.session.commit()
                logger.info(f"Rental {rental.id} 状态已更新为shipped")
                success_count += 1
            else:
                logger.error(f"Rental {rental.id} 发货失败，状态未更新")
                failed_count += 1
                db.session.rollback()

        except Exception as e:
            logger.error(f"处理 Rental {rental.id} 时发生异常: {e}")
            db.session.rollback()
            failed_count += 1

    result = {
        'total': len(rentals),
        'success': success_count,
        'failed': failed_count,
        'skipped': skipped_count
    }

    logger.info(f"预约发货任务完成: {result}")
    return result


def retry_failed_shipments(rental_ids: list = None, max_retries: int = 3):
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
            'failed': 0
        }

    logger.info(f"找到 {len(rentals)} 个需要重试的订单")

    # 获取服务实例
    sf_service = get_sf_express_service()
    xianyu_service = get_xianyu_service()

    success_count = 0
    failed_count = 0

    for rental in rentals:
        retry_success = False

        for attempt in range(max_retries):
            try:
                logger.info(f"重试 Rental {rental.id}, 第 {attempt + 1}/{max_retries} 次")

                # 调用顺丰API
                sf_result = sf_service.place_shipping_order(rental)

                # 调用闲鱼API（如果有订单号）
                xianyu_result = {'success': True}  # 默认成功
                if rental.xianyu_order_no:
                    xianyu_result = xianyu_service.ship_order(rental)

                # 如果都成功，更新状态
                if sf_result.get('success') and xianyu_result.get('success'):
                    rental.status = 'shipped'
                    rental.ship_out_time = datetime.utcnow()
                    db.session.commit()
                    logger.info(f"Rental {rental.id} 重试成功")
                    retry_success = True
                    success_count += 1
                    break
                else:
                    logger.warning(f"Rental {rental.id} 第 {attempt + 1} 次重试失败")

            except Exception as e:
                logger.error(f"重试 Rental {rental.id} 第 {attempt + 1} 次异常: {e}")
                db.session.rollback()

        if not retry_success:
            logger.error(f"Rental {rental.id} 重试失败，已达最大重试次数")
            failed_count += 1

    result = {
        'total': len(rentals),
        'success': success_count,
        'failed': failed_count
    }

    logger.info(f"重试发货任务完成: {result}")
    return result
