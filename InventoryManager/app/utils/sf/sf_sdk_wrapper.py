"""
顺丰快递 SDK 封装
基于官方 SDK (callExpressRequest.py) 的封装
"""

import time
import uuid
import json
import hashlib
import base64
import urllib.parse
import requests
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class SFExpressSDK:
    """顺丰快递 SDK 封装类"""

    def __init__(self, partner_id: str, checkword: str, test_mode: bool = False):
        """
        初始化顺丰 SDK

        Args:
            partner_id: 顺丰分配的顾客编码
            checkword: 顺丰分配的校验码
            test_mode: 是否使用测试环境
        """
        self.partner_id = partner_id
        self.checkword = checkword
        self.test_mode = test_mode

        # API 地址
        if test_mode:
            self.req_url = 'https://sfapi-sbox.sf-express.com/std/service'
        else:
            self.req_url = 'https://sfapi.sf-express.com/std/service'

    def _call_sf_express_service(self, service_code: str, msg_data: dict) -> dict:
        """
        调用顺丰 API 服务 (基于官方 SDK)

        Args:
            service_code: 服务代码 (如 EXP_RECE_CREATE_ORDER, EXP_RECE_SEARCH_ROUTES)
            msg_data: 消息数据字典

        Returns:
            dict: API 响应结果
        """
        try:
            # 将消息数据转换为 JSON 字符串
            msg_data_str = json.dumps(msg_data, ensure_ascii=False, separators=(',', ':'))

            # 生成 UUID 和时间戳
            request_id = str(uuid.uuid1())
            timestamp = str(int(time.time()))

            # 构建签名字符串并进行 URL 编码
            sign_str = msg_data_str + timestamp + self.checkword
            encoded_str = urllib.parse.quote_plus(sign_str)

            # MD5 加密
            m = hashlib.md5()
            m.update(encoded_str.encode('utf-8'))
            md5_bytes = m.digest()

            # Base64 编码
            msg_digest = base64.b64encode(md5_bytes).decode('utf-8')

            # 构建请求参数
            data = {
                "partnerID": self.partner_id,
                "requestID": request_id,
                "serviceCode": service_code,
                "timestamp": timestamp,
                "msgDigest": msg_digest,
                "msgData": msg_data_str
            }

            logger.info(f"调用顺丰API: {service_code}")
            logger.debug(f"请求数据: {data}")

            # 发送 POST 请求
            response = requests.post(
                self.req_url,
                data=data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30
            )

            logger.info(f"HTTP状态码: {response.status_code}")
            logger.debug(f"响应内容: {response.text}")

            response.raise_for_status()
            result = response.json()

            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"API请求失败: {e}")
            return {"apiResultCode": "A9999", "apiErrorMsg": f"网络请求失败: {str(e)}"}
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}, 响应内容: {response.text}")
            return {"apiResultCode": "A9998", "apiErrorMsg": f"响应解析失败: {str(e)}"}
        except Exception as e:
            logger.error(f"API调用异常: {e}")
            return {"apiResultCode": "A9997", "apiErrorMsg": f"未知错误: {str(e)}"}

    def create_order(self, order_data: dict) -> Dict:
        """
        创建速运订单

        Args:
            order_data: 订单数据

        Returns:
            Dict: API 响应
        """
        response = self._call_sf_express_service('EXP_RECE_CREATE_ORDER', order_data)

        # 解析响应
        if response.get('apiResultCode') == 'A1000':
            msg_data_str = response.get('msgData', '{}')
            try:
                data = json.loads(msg_data_str) if isinstance(msg_data_str, str) else msg_data_str
                return {
                    'success': True,
                    'message': '下单成功',
                    'data': data
                }
            except json.JSONDecodeError as e:
                logger.error(f"解析订单响应失败: {e}")
                return {
                    'success': False,
                    'message': f'解析响应失败: {str(e)}'
                }
        else:
            return {
                'success': False,
                'message': response.get('apiErrorMsg', '下单失败'),
                'code': response.get('apiResultCode')
            }

    def search_routes(self, tracking_number: str, check_phone_no: str) -> Dict:
        """
        查询快递路由信息

        Args:
            tracking_number: 快递单号
            check_phone_no: 收件人或寄件人手机号后四位

        Returns:
            Dict: 路由信息
        """
        msg_data = {
            "trackingType": "1",  # 1:根据顺丰运单号查询
            "checkPhoneNo": check_phone_no,
            "trackingNumber": [tracking_number],
            "methodType": "1"  # 1:标准查询
        }

        return self._call_sf_express_service("EXP_RECE_SEARCH_ROUTES", msg_data)

    def batch_search_routes(self, tracking_numbers: List[str], check_phone_no: str) -> Dict:
        """
        批量查询快递路由信息

        Args:
            tracking_numbers: 快递单号列表
            check_phone_no: 收件人或寄件人手机号后四位

        Returns:
            Dict: 路由信息
        """
        if len(tracking_numbers) > 100:
            raise ValueError("批量查询单号数量不能超过100个")

        msg_data = {
            "trackingType": "1",
            "checkPhoneNo": check_phone_no,
            "trackingNumber": tracking_numbers,
            "methodType": "1"
        }

        return self._call_sf_express_service("EXP_RECE_SEARCH_ROUTES", msg_data)

    def parse_route_response(self, response: Dict) -> Dict[str, Dict]:
        """
        解析路由查询响应

        Args:
            response: API 响应

        Returns:
            Dict: 解析后的路由信息，键为单号，值为路由详情
        """
        result = {}

        logger.info(f"开始解析路由响应: {response}")

        if response.get("apiResultCode") != "A1000":
            logger.error(f"API调用失败: {response.get('apiErrorMsg', '未知错误')}")
            return result

        try:
            msg_data_str = response.get("msgData", "{}")
            msg_data = json.loads(msg_data_str) if isinstance(msg_data_str, str) else msg_data_str

            if not msg_data.get("success", False):
                logger.error(f"查询失败: {msg_data.get('errorMsg', '未知错误')}")
                return result

            routes = msg_data.get("msgData", {}).get("routeResps", [])

            for route in routes:
                tracking_no = route.get("mailNo", "")
                if not tracking_no:
                    continue

                route_info = {
                    "tracking_number": tracking_no,
                    "routes": [],
                    "status": "unknown",
                    "delivered_time": None,
                    "last_update": None
                }

                # 解析路由详情
                for route_detail in route.get("routes", []):
                    route_item = {
                        "accept_time": route_detail.get("acceptTime", ""),
                        "accept_address": route_detail.get("acceptAddress", ""),
                        "remark": route_detail.get("remark", ""),
                        "op_code": route_detail.get("opCode", "")
                    }
                    route_info["routes"].append(route_item)

                # 确定快递状态
                if route_info["routes"]:
                    latest_route = route_info["routes"][0]
                    route_info["last_update"] = latest_route["accept_time"]

                    op_code = latest_route.get("op_code", "")
                    if op_code in ["80", "8000"]:
                        route_info["status"] = "delivered"
                        route_info["delivered_time"] = latest_route["accept_time"]
                    elif op_code in ["70", "7000"]:
                        route_info["status"] = "delivering"
                    elif op_code in ["50", "5000"]:
                        route_info["status"] = "in_transit"
                    elif op_code in ["10", "1000"]:
                        route_info["status"] = "picked_up"
                    else:
                        route_info["status"] = "processing"

                result[tracking_no] = route_info

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"解析路由响应失败: {e}")

        return result

    def get_delivery_status(self, tracking_number: str, check_phone_no: str) -> Dict:
        """
        获取快递送达状态

        Args:
            tracking_number: 快递单号
            check_phone_no: 收件人或寄件人手机号后四位

        Returns:
            Dict: 送达状态信息
        """
        response = self.search_routes(tracking_number, check_phone_no)
        parsed_routes = self.parse_route_response(response)

        if tracking_number in parsed_routes:
            route_info = parsed_routes[tracking_number]
            return {
                "tracking_number": tracking_number,
                "status": route_info["status"],
                "is_delivered": route_info["status"] == "delivered",
                "delivered_time": route_info["delivered_time"],
                "last_update": route_info["last_update"],
                "routes": route_info["routes"]
            }
        else:
            return {
                "tracking_number": tracking_number,
                "status": "not_found",
                "is_delivered": False,
                "delivered_time": None,
                "last_update": None,
                "routes": []
            }


def create_sf_client(partner_id: str = None, checkword: str = None, test_mode: bool = True) -> SFExpressSDK:
    """
    创建顺丰 SDK 客户端实例

    Args:
        partner_id: 合作伙伴 ID
        checkword: 校验码
        test_mode: 测试模式

    Returns:
        SFExpressSDK: SDK 实例
    """
    if not partner_id or not checkword:
        partner_id = partner_id or "test_partner_id"
        checkword = checkword or "test_checkword"

    return SFExpressSDK(partner_id, checkword, test_mode)


def query_tracking_info(tracking_number: str, check_phone_no: str, partner_id: str = None, checkword: str = None) -> Dict:
    """
    查询单个快递信息的便捷函数

    Args:
        tracking_number: 快递单号
        check_phone_no: 收件人或寄件人手机号后四位
        partner_id: 合作伙伴 ID
        checkword: 校验码

    Returns:
        Dict: 快递信息
    """
    client = create_sf_client(partner_id, checkword)
    return client.get_delivery_status(tracking_number, check_phone_no)


def batch_query_tracking_info(tracking_numbers: List[str], check_phone_no: str, partner_id: str = None, checkword: str = None) -> Dict[str, Dict]:
    """
    批量查询快递信息的便捷函数

    Args:
        tracking_numbers: 快递单号列表
        check_phone_no: 收件人或寄件人手机号后四位
        partner_id: 合作伙伴 ID
        checkword: 校验码

    Returns:
        Dict: 快递信息字典，键为单号
    """
    client = create_sf_client(partner_id, checkword)
    response = client.batch_search_routes(tracking_numbers, check_phone_no)
    return client.parse_route_response(response)
