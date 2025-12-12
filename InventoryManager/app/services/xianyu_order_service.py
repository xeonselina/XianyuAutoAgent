"""
闲鱼管家API服务
提供订单详情查询、发货通知等功能
"""

import hashlib
import requests
import json
import time
import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class XianyuOrderService:
    """闲鱼管家订单API服务类 - 统一的闲鱼API客户端"""

    def __init__(self):
        """初始化服务,从环境变量读取配置"""
        # 兼容两种环境变量命名方式
        self.app_key = os.getenv('XIANYU_APP_KEY') or os.getenv('XIANYU_APP_ID')
        self.app_secret = os.getenv('XIANYU_APP_SECRET') or os.getenv('XIANYU_SECRET')
        self.api_domain = os.getenv('XIANYU_API_DOMAIN', 'open.goofish.pro')
        self.base_url = f"https://{self.api_domain}"

        # 卖家ID（可选）
        self.seller_id = os.getenv('XIANYU_SELLER_ID')

        # 寄件方信息（可选，用于发货接口）
        self.ship_name = os.getenv('XIANYU_SHIP_NAME')
        self.ship_mobile = os.getenv('XIANYU_SHIP_MOBILE')
        self.ship_prov_name = os.getenv('XIANYU_SHIP_PROV_NAME')
        self.ship_city_name = os.getenv('XIANYU_SHIP_CITY_NAME')
        self.ship_area_name = os.getenv('XIANYU_SHIP_AREA_NAME')
        self.ship_address = os.getenv('XIANYU_SHIP_ADDRESS')

        if not self.app_key or not self.app_secret:
            logger.warning("闲鱼API凭证未配置。请设置XIANYU_APP_KEY/XIANYU_APP_ID和XIANYU_APP_SECRET/XIANYU_SECRET环境变量")

    def _gen_body_sign(self, body_json: str, timestamp: int) -> str:
        """
        生成基于请求体的API签名（用于订单详情接口）

        Args:
            body_json: 请求体JSON字符串
            timestamp: 时间戳(秒)

        Returns:
            签名字符串
        """
        # 将请求报文进行md5
        m = hashlib.md5()
        m.update(body_json.encode('utf8'))
        body_md5 = m.hexdigest()

        # 拼接字符串生成签名
        s = f"{self.app_key},{body_md5},{timestamp},{self.app_secret}"

        m = hashlib.md5()
        m.update(s.encode('utf8'))
        sign = m.hexdigest()

        return sign

    def _gen_param_sign(self, params: Dict) -> str:
        """
        生成基于参数的MD5签名（用于发货接口）

        Args:
            params: 请求参数字典

        Returns:
            MD5签名
        """
        # 按key排序
        sorted_params = sorted(params.items(), key=lambda x: x[0])

        # 拼接 key + value
        sign_str = ''.join([f'{k}{v}' for k, v in sorted_params if v is not None])

        # 追加secret
        sign_str += self.app_secret

        # MD5哈希
        sign = hashlib.md5(sign_str.encode('utf-8')).hexdigest()

        logger.debug(f"签名字符串: {sign_str}")
        logger.debug(f"生成签名: {sign}")

        return sign

    def _request_with_body_sign(self, url: str, data: dict, timeout: int = 30) -> Optional[Dict[str, Any]]:
        """
        使用请求体签名方式发送API请求（用于订单详情接口）

        Args:
            url: API路径(如 /api/open/order/detail)
            data: 请求数据字典
            timeout: 超时时间(秒)

        Returns:
            API响应的JSON数据,失败返回None
        """
        import traceback
        import sys

        try:
            # 将json对象转成json字符串
            # 特别注意：使用 json.dumps 函数时必须补充第二个参数 separators=(',', ':') 用于过滤空格，否则会签名错误
            body = json.dumps(data, separators=(",", ":"))

            # 时间戳秒
            timestamp = int(time.time())

            # 生成签名
            sign = self._gen_body_sign(body, timestamp)

            # 拼接地址
            full_url = f"{self.base_url}{url}?appid={self.app_key}&timestamp={timestamp}&sign={sign}"

            # 设置请求头
            headers = {"Content-Type": "application/json"}

            logger.debug(f"请求URL: {full_url}")
            logger.debug(f"请求体: {body}")

            # 详细的请求前日志
            logger.info(f"[REQUEST START] 准备发送闲鱼API请求")
            logger.info(f"[REQUEST] URL: {full_url}")
            logger.info(f"[REQUEST] 超时设置: {timeout}秒")
            logger.info(f"[REQUEST] Python版本: {sys.version}")
            logger.info(f"[REQUEST] Requests库版本: {requests.__version__}")

            # 检查是否在gevent环境
            try:
                import gevent
                logger.info(f"[REQUEST] Gevent版本: {gevent.__version__}")
                logger.info(f"[REQUEST] 当前Greenlet: {gevent.getcurrent()}")
            except ImportError:
                logger.info(f"[REQUEST] Gevent未安装")

            # 检查SSL配置
            try:
                import ssl
                logger.info(f"[REQUEST] SSL版本: {ssl.OPENSSL_VERSION}")
            except Exception as ssl_err:
                logger.warning(f"[REQUEST] 无法获取SSL版本: {ssl_err}")

            # 使用requests发送请求
            logger.info(f"[REQUEST] 正在调用 requests.post()...")
            response = requests.post(full_url, data=body, headers=headers, timeout=timeout)
            logger.info(f"[REQUEST SUCCESS] requests.post() 调用完成，状态码: {response.status_code}")

            response.raise_for_status()
            logger.info(f"[REQUEST] HTTP状态检查通过")

            result = response.json()
            logger.info(f"[REQUEST] JSON解析成功")
            logger.info(f"[response] {response.text}")
            return result

        except requests.exceptions.Timeout:
            logger.error(f"[REQUEST ERROR] 闲鱼API请求超时")
            logger.error(f"[REQUEST ERROR] 完整堆栈:\n{traceback.format_exc()}")
            return None
        except requests.exceptions.RequestException as e:
            logger.error(f"[REQUEST ERROR] 闲鱼API请求失败: {type(e).__name__}: {e}")
            logger.error(f"[REQUEST ERROR] 完整堆栈:\n{traceback.format_exc()}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"[REQUEST ERROR] 闲鱼API响应解析失败: {e}")
            logger.error(f"[REQUEST ERROR] 响应内容: {response.text if 'response' in locals() else 'N/A'}")
            logger.error(f"[REQUEST ERROR] 完整堆栈:\n{traceback.format_exc()}")
            return None
        except RecursionError as e:
            logger.error(f"[REQUEST ERROR] 递归深度超限!!!")
            logger.error(f"[REQUEST ERROR] RecursionError: {e}")
            logger.error(f"[REQUEST ERROR] 完整堆栈:\n{traceback.format_exc()}")
            logger.error(f"[REQUEST ERROR] 递归限制: {sys.getrecursionlimit()}")
            return None
        except Exception as e:
            logger.error(f"[REQUEST ERROR] 闲鱼API请求异常: {type(e).__name__}: {e}")
            logger.error(f"[REQUEST ERROR] 完整堆栈:\n{traceback.format_exc()}")
            return None

    def get_order_detail(self, order_no: str) -> Optional[Dict[str, Any]]:
        """
        获取订单详情

        Args:
            order_no: 闲鱼订单号

        Returns:
            订单详情字典,包含以下字段:
            - order_no: 订单号
            - receiver_name: 收货人姓名
            - receiver_mobile: 收货人电话
            - prov_name: 省份
            - city_name: 城市
            - area_name: 地区
            - town_name: 街道
            - address: 详细地址
            - buyer_eid: 买家ID
            - buyer_nick: 买家昵称
            - pay_amount: 实付金额(分)
            失败返回None
        """
        if not self.app_key or not self.app_secret:
            logger.error("闲鱼API凭证未配置")
            return None

        if not order_no or not order_no.strip():
            logger.error("订单号不能为空")
            return None

        # 构建请求数据
        request_data = {
            "order_no": order_no.strip()
        }

        # 调用API
        logger.info(f"正在获取闲鱼订单详情: {order_no}")
        result = self._request_with_body_sign("/api/open/order/detail", request_data)

        if not result:
            logger.error(f"获取订单详情失败: 无响应")
            return None

        # 检查响应码
        if result.get('code') != 0:
            error_msg = result.get('msg', '未知错误')
            logger.error(f"获取订单详情失败: {error_msg}")
            return None

        # 提取订单数据
        order_data = result.get('data')
        if not order_data:
            logger.error(f"订单详情数据为空")
            return None

        logger.info(f"成功获取订单详情: {order_no}")
        return order_data

    def ship_order(self, rental) -> Dict:
        """
        订单物流发货通知

        Args:
            rental: 租赁记录对象

        Returns:
            Dict: API响应结果
            {
                'success': bool,
                'message': str,
                'skipped': bool (可选),
                'data': dict (可选)
            }
        """
        # 检查必要字段
        if not rental.xianyu_order_no:
            logger.warning(f"Rental {rental.id} 没有闲鱼订单号，跳过闲鱼发货通知")
            return {
                'success': False,
                'message': '没有闲鱼订单号',
                'skipped': True
            }

        if not rental.ship_out_tracking_no:
            logger.error(f"Rental {rental.id} 没有运单号")
            return {
                'success': False,
                'message': '没有运单号'
            }

        # 使用寄出快递单号
        waybill_no = rental.ship_out_tracking_no

        # 构建请求体
        request_data = {
            'order_no': rental.xianyu_order_no,
            'waybill_no': waybill_no,
            'express_code': 'shunfeng',  # 顺丰快递代码
            'express_name': '顺丰速运'
        }

        # 添加寄件方信息（如果配置了）
        if self.ship_name and self.ship_mobile:
            request_data['ship_name'] = self.ship_name
            request_data['ship_mobile'] = self.ship_mobile
            request_data['ship_address'] = self.ship_address

            # 优先使用省市区文本格式
            if self.ship_prov_name and self.ship_city_name and self.ship_area_name:
                request_data['ship_prov_name'] = self.ship_prov_name
                request_data['ship_city_name'] = self.ship_city_name
                request_data['ship_area_name'] = self.ship_area_name

        logger.info(f"闲鱼发货通知: Rental {rental.id}, Order {rental.xianyu_order_no}")
        logger.debug(f"请求数据: {request_data}")

        # 使用与 get_order_detail 相同的签名方式
        result = self._request_with_body_sign("/api/open/order/ship", request_data)

        if not result:
            logger.error(f"闲鱼发货失败: Rental {rental.id}, 无响应")
            return {
                'success': False,
                'message': '无响应'
            }

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


# 创建全局服务实例
xianyu_service = XianyuOrderService()


# 向后兼容的工厂函数
def get_xianyu_service() -> XianyuOrderService:
    """获取闲鱼API服务单例（向后兼容）"""
    return xianyu_service
