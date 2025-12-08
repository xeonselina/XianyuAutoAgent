"""
闲鱼管家API服务
用于调用闲鱼管家平台API获取订单详情
"""

import hashlib
import http.client
import json
import time
import os
import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)


class XianyuOrderService:
    """闲鱼管家订单API服务类"""

    def __init__(self):
        """初始化服务,从环境变量读取配置"""
        self.app_key = os.getenv('XIANYU_APP_KEY')
        self.app_secret = os.getenv('XIANYU_APP_SECRET')
        self.api_domain = os.getenv('XIANYU_API_DOMAIN', 'open.goofish.pro')

        if not self.app_key or not self.app_secret:
            logger.warning("闲鱼API凭证未配置。请设置XIANYU_APP_KEY和XIANYU_APP_SECRET环境变量")

    def gen_sign(self, body_json: str, timestamp: int) -> str:
        """
        生成API签名

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

    def request(self, url: str, data: dict, timeout: int = 10) -> Optional[Dict[str, Any]]:
        """
        发送API请求

        Args:
            url: API路径(如 /api/open/order/detail)
            data: 请求数据字典
            timeout: 超时时间(秒)

        Returns:
            API响应的JSON数据,失败返回None
        """
        try:
            # 将json对象转成json字符串
            # 特别注意：使用 json.dumps 函数时必须补充第二个参数 separators=(',', ':') 用于过滤空格，否则会签名错误
            body = json.dumps(data, separators=(",", ":"))

            # 时间戳秒
            timestamp = int(time.time())

            # 生成签名
            sign = self.gen_sign(body, timestamp)

            # 拼接地址
            full_url = f"{url}?appid={self.app_key}&timestamp={timestamp}&sign={sign}"

            # 设置请求头
            headers = {"Content-Type": "application/json"}

            # 请求接口
            conn = http.client.HTTPSConnection(self.api_domain, timeout=timeout)
            try:
                conn.request("POST", full_url, body, headers)
                res = conn.getresponse()
                resp_data = res.read().decode("utf-8")

                # 解析响应
                result = json.loads(resp_data)
                return result
            finally:
                conn.close()

        except http.client.HTTPException as e:
            logger.error(f"闲鱼API HTTP错误: {e}")
            return None
        except json.JSONDecodeError as e:
            logger.error(f"闲鱼API响应解析失败: {e}")
            return None
        except Exception as e:
            logger.error(f"闲鱼API请求失败: {e}")
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
        result = self.request("/api/open/order/detail", request_data)

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


# 创建全局服务实例
xianyu_service = XianyuOrderService()
