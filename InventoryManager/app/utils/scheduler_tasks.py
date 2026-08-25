"""
定时任务模块
"""

import logging
import fcntl
from datetime import datetime, date, timedelta
from typing import List, Dict
from sqlalchemy import and_, or_

from app import db
from app.models.rental import Rental
from app.models.device import Device
from app.services.integration_resolver import ConfigurationIncomplete
from app.services.rental.rental_service import WarehouseMismatchError
import os

logger = logging.getLogger(__name__)

# 任务锁文件路径
TASK_LOCK_PATH = '/tmp/inventory_scheduled_shipping_task.lock'


class RentalTrackingScheduler:
    """租赁记录快递追踪定时任务"""
    
    def get_today_rentals_with_shipping(self) -> List[Rental]:
        """
        获取今天涉及的有快递单号的租赁记录
        
        Returns:
            List[Rental]: 租赁记录列表
        """
        try:
            today = date.today()
            
            # 查找今天涉及的租赁记录（ship_out_date 或 ship_in_date 覆盖今天）
            rentals = Rental.query.filter(
                and_(
                    # 租赁时间段包含今天
                    or_(
                        and_(
                            Rental.start_date <= today,
                            Rental.end_date >= today
                        ),
                        # 或者寄出/收回时间在今天前后一周内
                        and_(
                            Rental.ship_out_time.isnot(None),
                            Rental.ship_out_time >= datetime.combine(today - timedelta(days=7), datetime.min.time()),
                            Rental.ship_out_time <= datetime.combine(today + timedelta(days=1), datetime.min.time())
                        ),
                        and_(
                            Rental.ship_in_time.isnot(None),
                            Rental.ship_in_time >= datetime.combine(today - timedelta(days=7), datetime.min.time()),
                            Rental.ship_in_time <= datetime.combine(today + timedelta(days=1), datetime.min.time())
                        )
                    ),
                    # 有快递单号的记录
                    or_(
                        Rental.ship_out_tracking_no.isnot(None),
                        Rental.ship_in_tracking_no.isnot(None)
                    ),
                    # 排除已取消的记录
                    Rental.status != 'cancelled'
                )
            ).all()
            
            logger.info(f"找到 {len(rentals)} 条需要查询快递状态的租赁记录")
            return rentals
            
        except Exception as e:
            logger.error(f"获取租赁记录失败: {e}")
            return []
    
    def collect_tracking_numbers(self, rentals: List[Rental]) -> Dict[str, List[Rental]]:
        """
        收集所有需要查询的快递单号
        
        Args:
            rentals: 租赁记录列表
            
        Returns:
            Dict: 快递单号到租赁记录的映射
        """
        tracking_map = {}
        
        for rental in rentals:
            # 寄出快递单号
            if rental.ship_out_tracking_no:
                tracking_no = rental.ship_out_tracking_no.strip()
                if tracking_no:
                    if tracking_no not in tracking_map:
                        tracking_map[tracking_no] = []
                    tracking_map[tracking_no].append(rental)
            
            # 寄回快递单号
            if rental.ship_in_tracking_no:
                tracking_no = rental.ship_in_tracking_no.strip()
                if tracking_no:
                    if tracking_no not in tracking_map:
                        tracking_map[tracking_no] = []
                    tracking_map[tracking_no].append(rental)
        
        logger.info(f"收集到 {len(tracking_map)} 个快递单号需要查询")
        return tracking_map
    
    def update_rental_shipping_status(self, rental: Rental, tracking_info: Dict, tracking_type: str):
        """
        更新租赁记录的快递状态
        
        Args:
            rental: 租赁记录
            tracking_info: 快递信息
            tracking_type: 快递类型 ('out' 或 'in')
        """
        try:
            tracking_number = tracking_info.get('tracking_number', '')
            status = tracking_info.get('status', 'unknown')
            is_delivered = tracking_info.get('is_delivered', False)
            delivered_time_str = tracking_info.get('delivered_time')
            last_update_str = tracking_info.get('last_update')
            
            # 解析时间
            delivered_time = None
            if delivered_time_str:
                try:
                    delivered_time = datetime.strptime(delivered_time_str, '%Y-%m-%d %H:%M:%S')
                except ValueError:
                    logger.warning(f"无法解析送达时间: {delivered_time_str}")
            
            # 更新租赁记录
            update_made = False
            
            if tracking_type == 'in' and is_delivered and delivered_time:
                # 更新寄回送达时间
                if rental.ship_in_time != delivered_time:
                    rental.ship_in_time = delivered_time
                    update_made = True
                    logger.info(f"更新租赁 {rental.id} 的寄回时间: {delivered_time}")
            
            if update_made:
                rental.updated_at = datetime.utcnow()
                db.session.add(rental)
                
        except Exception as e:
            logger.error(f"更新租赁记录 {rental.id} 快递状态失败: {e}")
    
    def batch_update_tracking_status(self):
        """批量更新快递状态"""
        try:
            # 获取需要查询的租赁记录
            rentals = self.get_today_rentals_with_shipping()
            if not rentals:
                logger.info("没有需要查询快递状态的租赁记录")
                return
            
            # 收集快递单号
            tracking_map = self.collect_tracking_numbers(rentals)
            if not tracking_map:
                logger.info("没有有效的快递单号")
                return
            
            # 批量查询快递信息
            tracking_numbers = list(tracking_map.keys())
            logger.info(f"开始批量查询 {len(tracking_numbers)} 个快递单号")
            
            all_tracking_info = {}
            from app.services.shipping.sf_tracking_service import (
                SFTrackingService,
            )
            for tracking_number in tracking_numbers:
                try:
                    all_tracking_info[tracking_number] = (
                        SFTrackingService.query_scoped(tracking_number)
                    )
                except Exception as exc:
                    logger.warning(
                        "跳过物流查询 %s: %s",
                        tracking_number, type(exc).__name__,
                    )
            
            # 更新租赁记录
            updated_count = 0
            for tracking_no, tracking_info in all_tracking_info.items():
                if tracking_no in tracking_map:
                    rentals_with_tracking = tracking_map[tracking_no]
                    
                    for rental in rentals_with_tracking:
                        # 判断是寄出还是寄回快递
                        if rental.ship_out_tracking_no == tracking_no:
                            self.update_rental_shipping_status(rental, tracking_info, 'out')
                        
                        if rental.ship_in_tracking_no == tracking_no:
                            self.update_rental_shipping_status(rental, tracking_info, 'in')
                        
                        updated_count += 1
            
            # 提交数据库更改
            db.session.commit()
            logger.info(f"成功更新 {updated_count} 条租赁记录的快递状态")
            
        except Exception as e:
            logger.error(f"批量更新快递状态失败: {e}")
            db.session.rollback()
    
    def run_hourly_task(self):
        """每小时执行的任务"""
        logger.info("开始执行每小时定时任务：更新快递状态")
        start_time = datetime.now()
        
        try:
            self.batch_update_tracking_status()
        except Exception as e:
            logger.error(f"定时任务执行失败: {e}")
        finally:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            logger.info(f"定时任务执行完成，耗时: {duration:.2f} 秒")


def update_rental_tracking_status():
    """
    更新租赁快递状态的入口函数
    供外部调用
    """
    RentalTrackingScheduler().run_hourly_task()


def manual_query_tracking(
    tracking_number: str, warehouse_id=None, phone_last4=None
) -> Dict:
    """
    手动查询单个快递状态
    
    Args:
        tracking_number: 快递单号
        
    Returns:
        Dict: 快递状态信息
    """
    logger.info(f"开始手动查询快递单号: {tracking_number}")
    
    try:
        from app.services.shipping.sf_tracking_service import (
            SFTrackingService,
        )
        tracking_info = SFTrackingService.query_scoped(
            tracking_number,
            warehouse_id=warehouse_id,
            phone_last4=phone_last4,
        )
        return {
            'success': True,
            'message': '查询成功',
            'tracking_info': tracking_info
        }
    except ConfigurationIncomplete:
        return {'success': False, 'code': 'CONFIG_INCOMPLETE',
                'message': '仓库顺丰配置不完整', 'tracking_info': None}
    except WarehouseMismatchError:
        return {'success': False, 'code': 'WAREHOUSE_MISMATCH',
                'message': '运单号无法确定唯一仓库', 'tracking_info': None}
    except ValueError as exc:
        return {'success': False, 'code': 'BAD_REQUEST',
                'message': str(exc), 'tracking_info': None}
    except Exception as exc:
        logger.error(
            f"手动查询快递状态失败: {type(exc).__name__}"
        )
        return {
            'success': False,
            'code': 'EXTERNAL_SERVICE_ERROR',
            'message': '顺丰服务调用失败',
            'tracking_info': None
        }


class ScheduledShippingProcessor:
    """预约发货处理器 - 定时任务，将到达预约时间的订单状态改为已发货"""

    def process_due_shipments(self):
        """
        处理到达预约时间的发货订单

        查找status='scheduled_for_shipping'且scheduled_ship_time <= now的订单
        将其状态改为'shipped'，设置ship_out_time，并调用闲鱼API同步发货信息
        """
        # 尝试获取任务锁，防止并发执行
        try:
            lock_file = open(TASK_LOCK_PATH, 'w')
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            logger.info(f"预约发货任务已在其他进程中运行，跳过本次执行 (PID: {os.getpid()})")
            return
        except Exception as e:
            logger.error(f"获取任务锁失败: {e}")
            return

        logger.info(f"开始执行预约发货定时任务 (PID: {os.getpid()})")
        start_time = datetime.now()

        try:
            from app.services.xianyu_order_service import get_xianyu_service

            # 查询到达预约时间的订单
            now = datetime.now()
            due_rentals = Rental.query.filter(
                Rental.status == 'scheduled_for_shipping',
                Rental.scheduled_ship_time <= now
            ).all()

            logger.info(f"找到 {len(due_rentals)} 个需要发货的订单")

            processed_count = 0
            failed_count = 0

            for rental in due_rentals:
                try:
                    logger.info(f"处理预约发货: Rental {rental.id}, 预约时间: {rental.scheduled_ship_time}")

                    # 更新状态
                    rental.status = 'shipped'
                    rental.ship_out_time = datetime.utcnow()

                    # 如果有闲鱼订单号，调用闲鱼API同步
                    if rental.xianyu_order_no:
                        logger.info(f"Rental {rental.id} 有闲鱼订单号，调用闲鱼API同步")
                        if not rental.xianyu_shop_id:
                            db.session.commit()
                            processed_count += 1
                            continue
                        xianyu_result = get_xianyu_service(rental=rental).ship_order(rental)

                        if not xianyu_result.get('success') and not xianyu_result.get('skipped'):
                            logger.error("Rental %s 闲鱼同步失败", rental.id)
                            # 闲鱼同步失败，回滚事务，下次重试
                            db.session.rollback()
                            failed_count += 1
                            continue

                    # 提交事务
                    db.session.commit()
                    processed_count += 1
                    logger.info(f"Rental {rental.id} 预约发货处理成功")

                except Exception as e:
                    logger.error("处理 Rental %s 时发生异常，类型: %s", rental.id, type(e).__name__)
                    db.session.rollback()
                    failed_count += 1

            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            logger.info(f"预约发货定时任务执行完成: 成功 {processed_count} 个, 失败 {failed_count} 个, 耗时: {duration:.2f} 秒")

        except Exception as e:
            logger.error("预约发货定时任务执行失败，类型: %s", type(e).__name__)

        finally:
            # 释放任务锁
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                lock_file.close()
            except Exception as e:
                logger.error(f"释放任务锁失败: {e}")


# 全局调度器实例
scheduled_shipping_processor = ScheduledShippingProcessor()


def process_scheduled_shipments(app=None):
    """
    处理预约发货的入口函数
    供外部调用

    Args:
        app: Flask应用实例（可选，如果不提供则从flask.current_app获取）
    """
    # 如果没有提供app，尝试从flask获取
    if app is None:
        from flask import current_app
        try:
            app = current_app._get_current_object()
        except RuntimeError:
            # 如果没有应用上下文，返回错误
            logger.error("process_scheduled_shipments: 没有Flask应用上下文，无法执行")
            return

    # 在应用上下文中执行任务
    with app.app_context():
        scheduled_shipping_processor.process_due_shipments()


def reconcile_xianyu_orders(app=None):
    """执行闲鱼待发货订单与库存预定的对账。"""
    if app is None:
        from flask import current_app
        try:
            app = current_app._get_current_object()
        except RuntimeError:
            logger.error(
                "reconcile_xianyu_orders: 没有Flask应用上下文，无法执行"
            )
            return

    from app.services.xianyu_order_reconciliation_service import (
        XianyuOrderReconciliationService,
    )

    with app.app_context():
        XianyuOrderReconciliationService().reconcile()
