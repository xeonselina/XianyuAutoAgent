"""
顺丰速运 API 服务 - 速运下单接口
"""

import os
import logging
from typing import Dict, Optional
from app.utils.sf.sf_sdk_wrapper import SFExpressSDK

logger = logging.getLogger(__name__)


class SFExpressService:
    """顺丰速运服务封装"""

    def __init__(self):
        """初始化顺丰速运服务"""
        # 从环境变量读取配置
        self.partner_id = os.getenv('SF_PARTNER_ID') or os.getenv('SF_APP_KEY')
        self.checkword = os.getenv('SF_CHECKWORD') or os.getenv('SF_APP_SECRET')
        self.test_mode = os.getenv('SF_API_MODE', 'test') == 'test'

        # 寄件方信息
        self.sender_name = os.getenv('SF_SENDER_NAME', '张女士')
        self.sender_phone = os.getenv('SF_SENDER_PHONE', '13510224947')
        self.sender_address = os.getenv('SF_SENDER_ADDRESS', '广东省深圳市南山区西丽街道松坪村竹苑9栋4单元415')

        if not self.partner_id or not self.checkword:
            logger.warning('顺丰API凭证未配置 (SF_PARTNER_ID/SF_APP_KEY, SF_CHECKWORD/SF_APP_SECRET)')

        # 创建SF SDK客户端
        self.client = SFExpressSDK(
            partner_id=self.partner_id,
            checkword=self.checkword,
            test_mode=self.test_mode
        )

    def place_shipping_order(self, rental) -> Dict:
        """
        下速运订单

        Args:
            rental: 租赁记录对象

        Returns:
            Dict: API响应结果
        """
        try:
            # 检查必要字段
            if not rental.customer_name or not rental.customer_phone or not rental.destination:
                logger.error(f"Rental {rental.id} 缺少收件人信息")
                return {
                    'success': False,
                    'message': '缺少收件人信息'
                }

            if not rental.ship_out_tracking_no:
                logger.error(f"Rental {rental.id} 没有运单号")
                return {
                    'success': False,
                    'message': '没有运单号'
                }

            # 构建订单数据
            order_data = {
                'orderId': f"R{rental.id}_{rental.ship_out_tracking_no}",  # 客户订单号
                'cargoDetails': [
                    {
                        'name': rental.device.device_model.name if rental.device and rental.device.device_model else '租赁设备',
                        'count': 1
                    }
                ],
                'consigneeInfo': {
                    'name': rental.customer_name,
                    'mobile': rental.customer_phone,
                    'address': rental.destination
                },
                'contactInfoList': [
                    {
                        'contactType': 1,  # 寄件人
                        'contact': self.sender_name,
                        'tel': self.sender_phone,
                        'address': self.sender_address
                    }
                ],
                'expressTypeId': 1,  # 标准快递
                'payMethod': 1,  # 寄付月结
                'waybillNo': rental.ship_out_tracking_no  # 运单号
            }

            logger.info(f"顺丰下单: Rental {rental.id}, 运单号 {rental.ship_out_tracking_no}")
            logger.debug(f"订单数据: {order_data}")

            # 调用顺丰SDK下单
            result = self.create_order(order_data)

            if result.get('success'):
                logger.info(f"顺丰下单成功: Rental {rental.id}")
                return result
            else:
                logger.error(f"顺丰下单失败: Rental {rental.id}, {result.get('message')}")
                return result

        except Exception as e:
            logger.error(f"顺丰下单异常: Rental {rental.id}, {e}")
            return {
                'success': False,
                'message': f'下单异常: {str(e)}'
            }

    def create_order(self, order_data: Dict) -> Dict:
        """
        创建速运订单

        Args:
            order_data: 订单数据

        Returns:
            Dict: API响应
        """
        try:
            # 调用顺丰SDK下单
            result = self.client.create_order(order_data)
            return result

        except Exception as e:
            logger.error(f"顺丰SDK调用失败: {e}")
            return {
                'success': False,
                'message': f'SDK调用失败: {str(e)}'
            }


# 创建全局实例
_sf_service = None

def get_sf_express_service() -> SFExpressService:
    """获取顺丰速运服务单例"""
    global _sf_service
    if _sf_service is None:
        _sf_service = SFExpressService()
    return _sf_service
