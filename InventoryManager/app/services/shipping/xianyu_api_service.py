"""
闲鱼管家 API 服务
"""

import requests
import hashlib
import time
import os
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)


class XianyuAPIService:
    """闲鱼管家API客户端"""

    def __init__(self):
        """初始化闲鱼API服务"""
        self.base_url = "https://open.goofish.pro"
        self.app_id = os.getenv('XIANYU_APP_ID')
        self.secret = os.getenv('XIANYU_SECRET')
        self.seller_id = os.getenv('XIANYU_SELLER_ID')

        # 寄件方信息（可选）
        self.ship_name = os.getenv('XIANYU_SHIP_NAME')
        self.ship_mobile = os.getenv('XIANYU_SHIP_MOBILE')
        self.ship_prov_name = os.getenv('XIANYU_SHIP_PROV_NAME')
        self.ship_city_name = os.getenv('XIANYU_SHIP_CITY_NAME')
        self.ship_area_name = os.getenv('XIANYU_SHIP_AREA_NAME')
        self.ship_address = os.getenv('XIANYU_SHIP_ADDRESS')

        if not self.app_id or not self.secret:
            logger.warning('闲鱼API凭证未配置 (XIANYU_APP_ID, XIANYU_SECRET)')

    def generate_sign(self, params: Dict) -> str:
        """
        生成MD5签名

        Args:
            params: 请求参数字典

        Returns:
            str: MD5签名
        """
        # 按key排序
        sorted_params = sorted(params.items(), key=lambda x: x[0])

        # 拼接 key + value
        sign_str = ''.join([f'{k}{v}' for k, v in sorted_params if v is not None])

        # 追加secret
        sign_str += self.secret

        # MD5哈希
        sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest()

        logger.debug(f"签名字符串: {sign_str}")
        logger.debug(f"生成签名: {sign}")

        return sign

    def ship_order(self, rental) -> Dict:
        """
        订单物流发货

        Args:
            rental: 租赁记录对象

        Returns:
            Dict: API响应
        """
        # 检查必要字段
        if not rental.xianyu_order_no:
            logger.warning(f"Rental {rental.id} 没有闲鱼订单号，跳过闲鱼发货通知")
            return {
                'success': False,
                'message': '没有闲鱼订单号',
                'skipped': True
            }

        if not rental.sf_waybill_no and not rental.ship_out_tracking_no:
            logger.error(f"Rental {rental.id} 没有运单号")
            return {
                'success': False,
                'message': '没有运单号'
            }

        # 使用顺丰运单号，如果没有则用备用运单号
        waybill_no = rental.sf_waybill_no or rental.ship_out_tracking_no

        # 构建请求参数
        timestamp = int(time.time())

        query_params = {
            'appid': self.app_id,
            'timestamp': timestamp
        }

        if self.seller_id:
            query_params['seller_id'] = self.seller_id

        # 生成签名（不包含sign本身）
        sign = self.generate_sign(query_params)
        query_params['sign'] = sign

        # 构建请求体
        body = {
            'order_no': rental.xianyu_order_no,
            'waybill_no': waybill_no,
            'express_code': 'shunfeng',  # 顺丰快递代码
            'express_name': '顺丰速运'
        }

        # 添加寄件方信息（如果配置了）
        if self.ship_name and self.ship_mobile:
            body['ship_name'] = self.ship_name
            body['ship_mobile'] = self.ship_mobile
            body['ship_address'] = self.ship_address

            # 优先使用省市区文本格式
            if self.ship_prov_name and self.ship_city_name and self.ship_area_name:
                body['ship_prov_name'] = self.ship_prov_name
                body['ship_city_name'] = self.ship_city_name
                body['ship_area_name'] = self.ship_area_name

        # 发送请求
        url = f"{self.base_url}/api/open/order/ship"

        logger.info(f"闲鱼发货通知: Rental {rental.id}, Order {rental.xianyu_order_no}")
        logger.debug(f"请求URL: {url}")
        logger.debug(f"查询参数: {query_params}")
        logger.debug(f"请求体: {body}")

        try:
            response = requests.post(
                url,
                params=query_params,
                json=body,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )

            logger.info(f"闲鱼API响应: {response.status_code}")
            logger.debug(f"响应内容: {response.text}")

            response.raise_for_status()
            result = response.json()

            # 检查业务状态码
            if result.get('code') == 0:
                logger.info(f"闲鱼发货成功: Rental {rental.id}")
                return {
                    'success': True,
                    'message': 'ok',
                    'data': result.get('data')
                }
            else:
                error_msg = result.get('msg', '未知错误')
                logger.error(f"闲鱼发货失败: Rental {rental.id}, 错误: {error_msg}")
                return {
                    'success': False,
                    'message': error_msg,
                    'code': result.get('code')
                }

        except requests.exceptions.Timeout:
            logger.error(f"闲鱼API超时: Rental {rental.id}")
            return {
                'success': False,
                'message': '请求超时'
            }

        except requests.exceptions.RequestException as e:
            logger.error(f"闲鱼API请求失败: Rental {rental.id}, {e}")
            return {
                'success': False,
                'message': f'网络请求失败: {str(e)}'
            }

        except Exception as e:
            logger.error(f"闲鱼API异常: Rental {rental.id}, {e}")
            return {
                'success': False,
                'message': f'未知错误: {str(e)}'
            }


# 创建全局实例
_xianyu_service = None

def get_xianyu_service() -> XianyuAPIService:
    """获取闲鱼API服务单例"""
    global _xianyu_service
    if _xianyu_service is None:
        _xianyu_service = XianyuAPIService()
    return _xianyu_service
