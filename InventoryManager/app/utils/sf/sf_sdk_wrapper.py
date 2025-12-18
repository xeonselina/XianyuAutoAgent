"""
顺丰快递 SDK 封装
基于顺丰 OpenAPI 2.0 (OAuth2.0 鉴权方式)
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

    def __init__(self, partner_id: str, checkword: str, test_mode:bool = False, use_oauth: bool = True):
        """
        初始化顺丰 SDK

        Args:
            partner_id: 顺丰分配的顾客编码 (OAuth2.0 时为 dev_id)
            checkword: 顺丰分配的校验码 (OAuth2.0 时为 dev_key)
            test_mode: 是否使用测试环境
            use_oauth: 是否使用 OAuth2.0 鉴权方式（默认 True，新版 API）
        """
        self.partner_id = partner_id
        self.checkword = checkword
        self.test_mode = test_mode
        self.use_oauth = use_oauth
        self.access_token = None
        self.token_expires_at = 0

        # API 地址
        if test_mode:
            self.req_url = 'https://sfapi-sbox.sf-express.com/std/service'
        else:
            self.req_url = 'https://bspgw.sf-express.com/std/service' 

    def _call_sf_express_service(self, service_code: str, msg_data: dict) -> dict:
        """
        调用顺丰 API 服务 (msgDigest 鉴权方式 - 旧版)

        Args:
            service_code: 服务代码 (如 EXP_RECE_CREATE_ORDER, EXP_RECE_SEARCH_ROUTES)
            msg_data: 消息数据字典

        Returns:
            dict: API 响应结果
        """
        response = None
        try:
            # 将消息数据转换为 JSON 字符串
            msg_data_str = json.dumps(msg_data, ensure_ascii=False, separators=(',', ':'))

            # 生成 UUID 和时间戳
            request_id = str(uuid.uuid1())
            
            timestamp = str(int(time.time())*1000)

            sign = urllib.parse.quote_plus(msg_data_str + timestamp + self.checkword)
            # 先md5加密然后base64加密
            m = hashlib.md5()    
            m.update(sign.encode('utf-8'))       
            md5Str = m.digest()    
            msgDigest = base64.b64encode(md5Str).decode('utf-8')
            data = {"partnerID": self.partner_id,"requestID": request_id,"serviceCode": service_code,"timestamp": timestamp,"msgDigest": msgDigest,"msgData": msg_data_str}
            # 发送post请求
            logger.info(f"调用顺丰API : {service_code} with ")
            logger.info("msg_data_str: " + msg_data_str)
            logger.info("msgDigest: " + msgDigest)
            logger.info(f"请求数据: {data}")
            logger.info(f"req_url: {self.req_url}")
            response = requests.post(self.req_url, data=data)
            logger.info(f"HTTP状态码: {response.status_code}")
            logger.info(f"响应内容: {response.text}")

            response.raise_for_status()
            result = response.json()

            return result

        except requests.exceptions.RequestException as e:
            import traceback
            logger.error(f"API请求失败: {type(e).__name__}")
            logger.error(f"错误详情: {str(e)}")
            logger.error(f"完整堆栈:\n{traceback.format_exc()}")
            return {"apiResultCode": "A9999", "apiErrorMsg": "网络请求失败"}
        except json.JSONDecodeError as e:
            import traceback
            logger.error(f"JSON解析失败: {type(e).__name__}")
            logger.error(f"错误详情: {str(e)}")
            logger.error(f"完整堆栈:\n{traceback.format_exc()}")
            return {"apiResultCode": "A9998", "apiErrorMsg": "响应解析失败"}
        except Exception as e:
            import traceback
            logger.error(f"API调用异常: {type(e).__name__}")
            logger.error(f"错误详情: {str(e)}")
            logger.error(f"完整堆栈:\n{traceback.format_exc()}")
            return {"apiResultCode": "A9997", "apiErrorMsg": "未知错误"}

    def create_order(self, order_data: dict) -> Dict:
        """
        创建速运订单

        Args:
            order_data: 订单数据

        Returns:
            Dict: API 响应，包含运单号信息
        """
        response = self._call_sf_express_service('EXP_RECE_CREATE_ORDER', order_data)

        # response 的格式:
        # {"apiErrorMsg":"","apiResponseID":"xxx","apiResultCode":"A1000",
        #  "apiResultData":"{\"success\":true,\"errorCode\":\"S0000\",\"msgData\":{\"waybillNoInfoList\":[{\"waybillType\":1,\"waybillNo\":\"SF1234567890\"}]}}"}

        # 检查API调用是否成功
        if response.get('apiResultCode') != 'A1000':
            return {
                'success': False,
                'message': response.get('apiErrorMsg', '下单失败'),
                'code': response.get('apiResultCode')
            }

        # 解析 apiResultData
        try:
            api_result_data_str = response.get('apiResultData', '{}')
            api_result_data = json.loads(api_result_data_str) if isinstance(api_result_data_str, str) else api_result_data_str

            if not api_result_data.get('success', False):
                # 业务失败
                error_msg = api_result_data.get('errorMsg', '下单失败')
                error_code = api_result_data.get('errorCode', '')
                logger.error(f"顺丰下单业务失败: {error_code} - {error_msg}")
                return {
                    'success': False,
                    'message': f"{error_code}: {error_msg}" if error_code else error_msg,
                    'code': response.get('apiResultCode')
                }

            # 提取运单号 - 从 msgData.waybillNoInfoList 中获取
            msg_data = api_result_data.get('msgData', {})
            waybill_no_info_list = msg_data.get('waybillNoInfoList', [])
            waybill_no = None

            if waybill_no_info_list and len(waybill_no_info_list) > 0:
                if len(waybill_no_info_list) > 1:
                    logger.warning(f"waybillNoInfoList包含多个元素: {len(waybill_no_info_list)}, 仅使用第一个")
                waybill_no = waybill_no_info_list[0].get('waybillNo')

            if not waybill_no:
                logger.error(f"顺丰API未返回运单号, apiResultData: {api_result_data_str}")
                return {
                    'success': False,
                    'message': '顺丰API未返回运单号',
                    'code': response.get('apiResultCode')
                }

            logger.info(f"顺丰下单成功，运单号: {waybill_no}")
            return {
                'success': True,
                'message': '下单成功',
                'waybill_no': waybill_no,
                'data': api_result_data
            }

        except json.JSONDecodeError as e:
            logger.error(f"解析apiResultData失败: {e}, 原始数据: {response.get('apiResultData')}")
            return {
                'success': False,
                'message': '顺丰API响应格式异常',
                'code': response.get('apiResultCode')
            }
        except (KeyError, TypeError) as e:
            logger.error(f"提取运单号失败: {e}, apiResultData: {response.get('apiResultData')}")
            return {
                'success': False,
                'message': f'解析运单号失败: {str(e)}',
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
            # 先解析 apiResultData (它是一个JSON字符串)
            api_result_data_str = response.get("apiResultData", "{}")
            api_result_data = json.loads(api_result_data_str) if isinstance(api_result_data_str, str) else api_result_data_str

            logger.info(f"解析后的 apiResultData: {api_result_data}")

            if not api_result_data.get("success", False):
                logger.error(f"查询失败: {api_result_data.get('errorMsg', '未知错误')}")
                return result

            # 从 msgData 中获取 routeResps
            routes = api_result_data.get("msgData", {}).get("routeResps", [])

            for route in routes:
                tracking_no = route.get("mailNo", "")
                if not tracking_no:
                    continue

                route_info = {
                    "tracking_number": tracking_no,
                    "routes": [],
                    "status": "unknown",
                    "status_text": "未知",
                    "delivered_time": None,
                    "last_update": None
                }

                # 解析路由详情
                for route_detail in route.get("routes", []):
                    route_item = {
                        "accept_time": route_detail.get("acceptTime", ""),
                        "accept_address": route_detail.get("acceptAddress", ""),
                        "remark": route_detail.get("remark", ""),
                        "op_code": route_detail.get("opCode", ""),
                        "first_status_code": route_detail.get("firstStatusCode", ""),
                        "first_status_name": route_detail.get("firstStatusName", ""),
                        "secondary_status_code": route_detail.get("secondaryStatusCode", ""),
                        "secondary_status_name": route_detail.get("secondaryStatusName", "")
                    }
                    route_info["routes"].append(route_item)

                # 确定快递状态 (使用最新的路由记录)
                if route_info["routes"]:
                    latest_route = route_info["routes"][-1]  # 最后一条是最新的
                    route_info["last_update"] = latest_route["accept_time"]

                    # 使用 firstStatusCode 判断状态
                    first_status_code = latest_route.get("first_status_code", "")
                    first_status_name = latest_route.get("first_status_name", "")
                    op_code = latest_route.get("op_code", "")

                    # 根据一级状态码判断
                    if first_status_code == "4" or op_code == "80":
                        route_info["status"] = "delivered"
                        route_info["status_text"] = "已签收"
                        route_info["delivered_time"] = latest_route["accept_time"]
                    elif first_status_code == "3":
                        route_info["status"] = "delivering"
                        route_info["status_text"] = "派送中"
                    elif first_status_code == "2":
                        route_info["status"] = "in_transit"
                        route_info["status_text"] = "运送中"
                    elif first_status_code == "1":
                        route_info["status"] = "picked_up"
                        route_info["status_text"] = "已揽收"
                    else:
                        route_info["status"] = "processing"
                        route_info["status_text"] = first_status_name or "处理中"

                result[tracking_no] = route_info

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            import traceback
            logger.error(f"解析路由响应失败: {e}")
            logger.error(f"完整堆栈:\n{traceback.format_exc()}")

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
