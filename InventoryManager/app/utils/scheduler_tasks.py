"""
定时任务模块
"""

import logging
from datetime import datetime, date, timedelta
from typing import List, Dict
from sqlalchemy import and_, or_

from app import db
from app.models.rental import Rental
from app.models.device import Device
from app.services.device_status_service import DeviceStatusService
from app.utils.sf_express_api import create_sf_client, batch_query_tracking_info
import os

logger = logging.getLogger(__name__)


class RentalTrackingScheduler:
    """租赁记录快递追踪定时任务"""
    
    def __init__(self):
        """初始化调度器"""
        self.sf_client = None
        self._init_sf_client()
    
    def _init_sf_client(self):
        """初始化顺丰客户端"""
        try:
            # 从环境变量或配置文件中读取顺丰API配置
            partner_id = os.getenv('SF_PARTNER_ID')
            checkword = os.getenv('SF_CHECKWORD')
            test_mode = os.getenv('SF_TEST_MODE', 'true').lower() == 'true'
            
            if partner_id and checkword:
                self.sf_client = create_sf_client(partner_id, checkword, test_mode)
                logger.info("顺丰API客户端初始化成功")
            else:
                logger.warning("顺丰API配置缺失，将使用测试配置")
                self.sf_client = create_sf_client(test_mode=True)
                
        except Exception as e:
            logger.error(f"初始化顺丰API客户端失败: {e}")
            self.sf_client = None
    
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
        if not self.sf_client:
            logger.error("顺丰API客户端未初始化，跳过更新")
            return
        
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
            
            # 分批查询（每次最多100个）
            batch_size = 100
            all_tracking_info = {}
            
            for i in range(0, len(tracking_numbers), batch_size):
                batch_numbers = tracking_numbers[i:i + batch_size]
                logger.info(f"查询第 {i//batch_size + 1} 批，共 {len(batch_numbers)} 个单号")
                
                batch_info = batch_query_tracking_info(
                    batch_numbers,
                    partner_id=self.sf_client.partner_id,
                    checkword=self.sf_client.checkword
                )
                
                all_tracking_info.update(batch_info)
            
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


class DeviceStatusScheduler:
    """设备状态更新定时任务"""
    
    def update_device_statuses(self):
        """更新所有设备状态"""
        logger.info("开始执行设备状态更新任务")
        start_time = datetime.now()
        
        try:
            DeviceStatusService.update_device_statuses()
        except Exception as e:
            logger.error(f"设备状态更新任务执行失败: {e}")
        finally:
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            logger.info(f"设备状态更新任务执行完成，耗时: {duration:.2f} 秒")
    
    def run_minute_task(self):
        """每分钟执行的任务"""
        logger.info("开始执行每分钟定时任务：更新设备状态")
        self.update_device_statuses()


# 全局调度器实例
rental_scheduler = RentalTrackingScheduler()
device_scheduler = DeviceStatusScheduler()


def update_rental_tracking_status():
    """
    更新租赁快递状态的入口函数
    供外部调用
    """
    rental_scheduler.run_hourly_task()


def update_device_statuses():
    """
    更新设备状态的入口函数
    供外部调用
    """
    device_scheduler.run_minute_task()


def manual_query_tracking(tracking_number: str) -> Dict:
    """
    手动查询单个快递状态
    
    Args:
        tracking_number: 快递单号
        
    Returns:
        Dict: 快递状态信息
    """
    logger.info(f"开始手动查询快递单号: {tracking_number}")
    
    if not rental_scheduler.sf_client:
        logger.error("顺丰API客户端未配置")
        return {
            'success': False,
            'message': '顺丰API客户端未配置',
            'tracking_info': None
        }
    
    try:
        logger.info(f"调用SF客户端查询: partner_id={rental_scheduler.sf_client.partner_id}, test_mode={rental_scheduler.sf_client.test_mode}")
        import os
        check_phone_no = os.getenv('SF_CHECKPHONENO')
        tracking_info = rental_scheduler.sf_client.get_delivery_status(tracking_number, check_phone_no)
        logger.info(f"SF客户端返回结果: {tracking_info}")
        
        return {
            'success': True,
            'message': '查询成功',
            'tracking_info': tracking_info
        }
    except Exception as e:
        logger.error(f"手动查询快递状态失败: {e}", exc_info=True)
        return {
            'success': False,
            'message': f'查询失败: {str(e)}',
            'tracking_info': None
        }


def force_update_device_status(device_id: int) -> Dict:
    """
    强制更新指定设备状态
    
    Args:
        device_id: 设备ID
        
    Returns:
        Dict: 更新结果
    """
    try:
        success, message = DeviceStatusService.force_update_device_status(device_id)
        return {
            'success': success,
            'message': message
        }
    except Exception as e:
        logger.error(f"强制更新设备状态失败: {e}")
        return {
            'success': False,
            'message': f'更新失败: {str(e)}'
        }


def get_device_status_summary() -> Dict:
    """
    获取设备状态统计

    Returns:
        Dict: 状态统计信息
    """
    try:
        summary = DeviceStatusService.get_device_status_summary()
        return {
            'success': True,
            'data': summary
        }
    except Exception as e:
        logger.error(f"获取设备状态统计失败: {e}")
        return {
            'success': False,
            'message': f'获取失败: {str(e)}',
            'data': {}
        }


def process_scheduled_shipments():
    """
    处理预约发货任务

    供调度器定期调用
    """
    logger.info("开始执行定时发货任务")
    start_time = datetime.now()

    try:
        from app.services.shipping.scheduler_shipping_task import process_scheduled_shipments as execute_shipments
        result = execute_shipments()
        logger.info(f"定时发货任务完成: {result}")
        return result
    except Exception as e:
        logger.error(f"定时发货任务执行失败: {e}", exc_info=True)
        return {
            'total': 0,
            'success': 0,
            'failed': 0,
            'error': str(e)
        }
    finally:
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.info(f"定时发货任务耗时: {duration:.2f} 秒")