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

            response.raise_for_status()
            result = response.json()

            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"API请求失败: {type(e).__name__}")
            return {"apiResultCode": "A9999", "apiErrorMsg": "网络请求失败"}
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {type(e).__name__}")
            return {"apiResultCode": "A9998", "apiErrorMsg": "响应解析失败"}
        except Exception as e:
            logger.error(f"API调用异常: {type(e).__name__}")
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
                error_code = api_result_data.get('errorCode', '')
                logger.error(f"顺丰下单业务失败: {error_code}")
                return {
                    'success': False,
                    'message': '顺丰服务调用失败',
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
                logger.error("顺丰API未返回运单号")
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

        except json.JSONDecodeError:
            logger.error("解析apiResultData失败")
            return {
                'success': False,
                'message': '顺丰API响应格式异常',
                'code': response.get('apiResultCode')
            }
        except (KeyError, TypeError):
            logger.error("提取运单号失败")
            return {
                'success': False,
                'message': '顺丰API响应格式异常',
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

    @staticmethod
    def _resolve_route_status(route: Dict) -> tuple[str, str]:
        """把顺丰状态归一化，同时保留接口返回的具体中文状态。

        顺丰会持续增加二级状态和操作码。这里仅用稳定的一级状态码做
        大类映射，其余状态再根据顺丰返回的状态名和轨迹文案判断；即使
        遇到尚未见过的新码，也会展示原始状态/轨迹，而不会落成“未知”。
        """
        first_code = str(route.get("first_status_code") or "").strip()
        first_name = str(route.get("first_status_name") or "").strip()
        secondary_name = str(
            route.get("secondary_status_name") or ""
        ).strip()
        remark = str(route.get("remark") or "").strip()
        op_code = str(route.get("op_code") or "").strip()
        detail_text = " ".join(
            value for value in (secondary_name, first_name, remark) if value
        )

        # 具体轨迹比一级大类更准确，例如一级仍是“派送”时，二级状态
        # 可能已经是“派送失败”；因此异常/退回等状态优先判断。
        if any(keyword in detail_text for keyword in ("退回", "退件")):
            status = "returned"
            fallback_text = "退回中"
        elif any(
            keyword in detail_text
            for keyword in (
                "异常", "滞留", "破损", "丢失", "拒收", "取消",
                "无法派送", "派送失败",
            )
        ):
            status = "exception"
            fallback_text = "物流异常"
        # 已签收操作码 80 是现有接口中最明确的终态标识。
        elif (
            first_code == "4"
            or op_code == "80"
            or any(keyword in detail_text for keyword in ("签收", "妥投"))
        ):
            status = "delivered"
            fallback_text = "已签收"
        elif any(
            keyword in detail_text
            for keyword in ("派送", "派件", "配送", "投递")
        ) or first_code == "3":
            status = "delivering"
            fallback_text = "派送中"
        elif (
            any(keyword in detail_text for keyword in ("揽收", "收件"))
            or first_code == "1"
        ):
            status = "picked_up"
            fallback_text = "已揽收"
        elif any(
            keyword in detail_text
            for keyword in (
                "运输", "运送", "中转", "转运", "发往", "到达",
                "离开", "装车", "航班", "清关", "通关",
            )
        ) or first_code == "2":
            status = "in_transit"
            fallback_text = "运输中"
        else:
            status = "processing"
            fallback_text = "处理中"

        # 二级状态最具体，其次一级状态；都没有时使用轨迹文案。
        status_text = secondary_name or first_name or remark or fallback_text
        return status, status_text

    def parse_route_response(self, response: Dict) -> Dict[str, Dict]:
        """
        解析路由查询响应

        Args:
            response: API 响应

        Returns:
            Dict: 解析后的路由信息，键为单号，值为路由详情
        """
        result = {}

        if response.get("apiResultCode") != "A1000":
            logger.error("顺丰路由查询失败")
            return result

        try:
            # 先解析 apiResultData (它是一个JSON字符串)
            api_result_data_str = response.get("apiResultData", "{}")
            api_result_data = json.loads(api_result_data_str) if isinstance(api_result_data_str, str) else api_result_data_str

            if not api_result_data.get("success", False):
                logger.error("顺丰路由查询业务失败")
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
                    "status": "processing",
                    "status_text": "暂无轨迹",
                    "delivered_time": None,
                    "last_update": None,
                    "latest_route": None,
                }

                # 解析路由详情
                for route_detail in route.get("routes", []):
                    route_item = {
                        "accept_time": str(
                            route_detail.get("acceptTime") or ""
                        ),
                        "accept_address": str(
                            route_detail.get("acceptAddress") or ""
                        ),
                        "remark": str(route_detail.get("remark") or ""),
                        "op_code": str(route_detail.get("opCode") or ""),
                        "first_status_code": str(
                            route_detail.get("firstStatusCode") or ""
                        ),
                        "first_status_name": str(
                            route_detail.get("firstStatusName") or ""
                        ),
                        "secondary_status_code": str(
                            route_detail.get("secondaryStatusCode") or ""
                        ),
                        "secondary_status_name": str(
                            route_detail.get("secondaryStatusName") or ""
                        ),
                    }
                    route_info["routes"].append(route_item)

                # 确定快递状态 (使用最新的路由记录)
                if route_info["routes"]:
                    latest_route = route_info["routes"][-1]  # 最后一条是最新的
                    route_info["last_update"] = latest_route["accept_time"]
                    route_info["latest_route"] = latest_route
                    status, status_text = self._resolve_route_status(latest_route)
                    route_info["status"] = status
                    route_info["status_text"] = status_text

                    if status == "delivered":
                        route_info["delivered_time"] = latest_route["accept_time"]

                result[tracking_no] = route_info

        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"解析路由响应失败: {type(e).__name__}")

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
        raise ValueError("顺丰客户端必须显式提供 partner_id 和 checkword")

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
