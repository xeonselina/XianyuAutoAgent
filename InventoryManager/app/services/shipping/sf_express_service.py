"""
顺丰速运 API 服务 - 速运下单接口
"""

import os,re
import logging
from typing import Dict, Optional
from app.utils.sf.sf_sdk_wrapper import SFExpressSDK

logger = logging.getLogger(__name__)


class SFExpressService:
    """顺丰速运服务封装"""

    def __init__(self):
        """初始化顺丰速运服务"""
        # 从环境变量读取配置
        self.partner_id = os.getenv('SF_PARTNER_ID') 
        self.checkword = os.getenv('SF_CHECKWORD')
        self.monthly_card = os.getenv('SF_MONTHLY_CARD')
        self.test_mode = os.getenv('SF_TEST_MODE', 'true') == 'true'

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

            # 获取快递类型，默认为2(标快)
            express_type_id = rental.express_type_id if rental.express_type_id else 2
            # rental.destination 的数据类似:
            # 灰灰 15976863836 广东省深圳市福田区福田街道平安金融中心 B2
            # 或者:
            # 收货人：刘鱼
            #手机号码：18537952739
            #收货地址：江苏省无锡市滨湖区华庄街道无锡太湖智选假日酒店门口丰巢柜
            # 使用正则表达式提取收货人、手机号码、收货地址

            destination_info = self._parse_destination(rental.destination)
            receiver_name = destination_info.get('name', rental.customer_name)
            receiver_phone = destination_info.get('phone', rental.customer_phone)
            receiver_address = destination_info.get('address', rental.destination)

            # 构建订单数据
            order_data = {
                'language': 'zh-CN',
                'orderId': f"R{rental.id}_{rental.ship_out_tracking_no}",  # 客户订单号
                'cargoDetails': [
                    {
                        'name': rental.device.device_model.name if rental.device and rental.device.device_model else '租赁设备',
                        'count': 1
                    }
                ],
                'monthlyCard': str(self.monthly_card),
                'contactInfoList': [
                    {
                        'contactType': 1,  # 寄件人
                        'contact': self.sender_name,
                        'mobile': self.sender_phone,
                        'address': self.sender_address,
                        'country': 'CN'
                    },
                    {
                        'contactType': 2,  # 收件人
                        'contact': receiver_name,
                        'mobile': receiver_phone,
                        'address': receiver_address,
                        'country': 'CN'
                    }
                ],
                'expressTypeId': express_type_id,  # 使用租赁记录的快递类型
                'payMethod': 1,  # 寄付月结
                'remark': f"R{rental.customer_name}",
                'waybillNoInfoList': [{'waybillType': 1,'waybillNo': rental.ship_out_tracking_no}],  # 运单号
                'isGenWaybillNo': 0,
                'isUnifiedWaybillNo': 1
            }

            # 快递类型名称映射
            express_type_names = {1: '特快', 2: '标快', 6: '半日达'}
            express_type_name = express_type_names.get(express_type_id, '未知')

            logger.info(f"顺丰下单: Rental {rental.id}, 运单号 {rental.ship_out_tracking_no}, 快递类型: {express_type_id}({express_type_name})")
            logger.info(f"订单数据: {order_data}")

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

    def _parse_destination(self, destination: str) -> Dict[str, str]:
        """
        解析目的地字符串，提取收货人、手机号码和收货地址

        支持两种格式:
        1. "姓名 手机号 地址" (如: 灰灰 15976863836 广东省深圳市福田区福田街道平安金融中心 B2)
        2. "收货人：姓名\n手机号码：手机号\n收货地址：地址" (多行格式)

        Args:
            destination: 目的地字符串

        Returns:
            Dict: 包含 name, phone, address 的字典
        """
        if not destination:
            return {'name': '', 'phone': '', 'address': ''}

        # 清理字符串
        destination = destination.strip()

        # 尝试格式2: 多行格式 "收货人：xxx\n手机号码：xxx\n收货地址：xxx"
        pattern2 = r'收货人[：:]\s*([^\n]+)[\s\n]+手机号码[：:]\s*([^\n]+)[\s\n]+收货地址[：:]\s*(.+)'
        match2 = re.search(pattern2, destination, re.DOTALL)
        if match2:
            return {
                'name': match2.group(1).strip(),
                'phone': match2.group(2).strip(),
                'address': match2.group(3).strip()
            }

        # 尝试格式1: "姓名 手机号 地址"
        # 手机号正则: 1开头的11位数字
        pattern1 = r'^([^\d\s]+)\s+(1[3-9]\d{9})\s+(.+)$'
        match1 = re.match(pattern1, destination)
        if match1:
            return {
                'name': match1.group(1).strip(),
                'phone': match1.group(2).strip(),
                'address': match1.group(3).strip()
            }

        # 如果都不匹配，尝试提取手机号
        phone_match = re.search(r'1[3-9]\d{9}', destination)
        if phone_match:
            phone = phone_match.group(0)
            # 尝试提取姓名 (手机号之前的非数字字符)
            name_match = re.match(r'^([^\d]+)', destination)
            name = name_match.group(1).strip() if name_match else ''
            # 地址是手机号之后的部分
            address = destination[phone_match.end():].strip()
            return {
                'name': name,
                'phone': phone,
                'address': address if address else destination
            }

        # 无法解析，返回空信息，让调用者使用默认值
        logger.warning(f"无法解析目的地信息: {destination}")
        return {'name': '', 'phone': '', 'address': destination}


# 创建全局实例
_sf_service = None

def get_sf_express_service() -> SFExpressService:
    """获取顺丰速运服务单例"""
    global _sf_service
    if _sf_service is None:
        _sf_service = SFExpressService()
    return _sf_service
