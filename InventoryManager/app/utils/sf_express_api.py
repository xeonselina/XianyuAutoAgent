"""
顺丰快递API集成模块
"""

import requests
import json
import hashlib
import time
import base64
from datetime import datetime
from typing import Dict, Optional, List
import logging

logger = logging.getLogger(__name__)


class SFExpressAPI:
    """顺丰快递API客户端"""
    
    def __init__(self, partner_id: str, checkword: str, test_mode: bool = False):
        """
        初始化顺丰API客户端
        
        Args:
            partner_id: 顺丰分配的合作伙伴ID
            checkword: 顺丰分配的校验码
            test_mode: 是否为测试模式
        """
        self.partner_id = partner_id
        self.checkword = checkword
        self.test_mode = test_mode
        
        # API地址
        if test_mode:
            self.api_url = "http://sfapi-sbox.sf-express.com/std/service"
        else:
            self.api_url = "https://sfapi.sf-express.com/std/service"
    
    def _generate_verifycode(self, msg_data: str, timestamp: str) -> str:
        """
        生成验证码
        
        Args:
            msg_data: 消息数据
            timestamp: 时间戳
            
        Returns:
            str: 验证码
        """
        # 拼接字符串：消息内容 + 时间戳 + 校验码
        sign_str = msg_data + timestamp + self.checkword
        
        # MD5加密并转为大写
        md5_hash = hashlib.md5(sign_str.encode('utf-8')).hexdigest().upper()
        
        # Base64编码
        return base64.b64encode(md5_hash.encode('utf-8')).decode('utf-8')
    
    def _make_request(self, service_code: str, msg_data: dict) -> Dict:
        """
        发送API请求
        
        Args:
            service_code: 服务代码
            msg_data: 消息数据
            
        Returns:
            Dict: API响应
        """
        try:
            # 转换消息数据为JSON字符串
            msg_data_str = json.dumps(msg_data, ensure_ascii=False, separators=(',', ':'))
            
            # 生成时间戳
            timestamp = str(int(time.time()))
            
            # 生成验证码
            verifycode = self._generate_verifycode(msg_data_str, timestamp)
            
            # 构建请求参数
            request_data = {
                "partnerID": self.partner_id,
                "requestID": f"REQ{timestamp}",
                "serviceCode": service_code,
                "timestamp": timestamp,
                "msgData": msg_data_str,
                "msgDigest": verifycode
            }
            
            logger.info(f"发送顺丰API请求: {service_code}")
            logger.info(f"请求URL: {self.api_url}")
            logger.info(f"请求数据: {request_data}")
            
            # 发送POST请求
            response = requests.post(
                self.api_url,
                data=request_data,
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=30
            )
            
            logger.info(f"HTTP状态码: {response.status_code}")
            logger.info(f"响应头: {dict(response.headers)}")
            logger.info(f"原始响应内容: {response.text}")
            
            response.raise_for_status()
            result = response.json()
            
            logger.info(f"解析后的JSON响应: {result}")
            
            return result
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API请求失败: {e}")
            return {"apiResultCode": "A1000", "apiErrorMsg": f"网络请求失败: {str(e)}"}
        except json.JSONDecodeError as e:
            logger.error(f"JSON解析失败: {e}")
            return {"apiResultCode": "A1001", "apiErrorMsg": f"响应解析失败: {str(e)}"}
        except Exception as e:
            logger.error(f"API请求异常: {e}")
            return {"apiResultCode": "A9999", "apiErrorMsg": f"未知错误: {str(e)}"}
    
    def search_routes(self, tracking_number: str) -> Dict:
        """
        查询快递路由信息
        
        Args:
            tracking_number: 快递单号
            
        Returns:
            Dict: 路由信息
        """
        msg_data = {
            "trackingType": "1",  # 1:根据顺丰运单号查询
            "trackingNumber": [tracking_number],
            "methodType": "1"  # 1:标准查询
        }
        
        return self._make_request("EXP_RECE_SEARCH_ROUTES", msg_data)
    
    def batch_search_routes(self, tracking_numbers: List[str]) -> Dict:
        """
        批量查询快递路由信息
        
        Args:
            tracking_numbers: 快递单号列表
            
        Returns:
            Dict: 路由信息
        """
        if len(tracking_numbers) > 100:
            raise ValueError("批量查询单号数量不能超过100个")
        
        msg_data = {
            "trackingType": "1",
            "trackingNumber": tracking_numbers,
            "methodType": "1"
        }
        
        return self._make_request("EXP_RECE_SEARCH_ROUTES", msg_data)
    
    def parse_route_response(self, response: Dict) -> Dict[str, Dict]:
        """
        解析路由查询响应
        
        Args:
            response: API响应
            
        Returns:
            Dict: 解析后的路由信息，键为单号，值为路由详情
        """
        result = {}
        
        logger.info(f"开始解析路由响应: {response}")
        
        if response.get("apiResultCode") != "A1000":
            logger.error(f"API调用失败: apiResultCode={response.get('apiResultCode')}, apiErrorMsg={response.get('apiErrorMsg', '未知错误')}")
            return result
        
        try:
            msg_data_str = response.get("msgData", "{}")
            logger.info(f"msgData字符串: {msg_data_str}")
            
            msg_data = json.loads(msg_data_str)
            logger.info(f"解析后的msgData: {msg_data}")
            
            if not msg_data.get("success", False):
                logger.error(f"查询失败: success={msg_data.get('success')}, errorMsg={msg_data.get('errorMsg', '未知错误')}")
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
                
                # 确定快递状态和送达时间
                if route_info["routes"]:
                    latest_route = route_info["routes"][0]  # 最新的路由信息通常在第一位
                    route_info["last_update"] = latest_route["accept_time"]
                    
                    # 根据op_code判断状态
                    op_code = latest_route.get("op_code", "")
                    if op_code in ["80", "8000"]:  # 已签收
                        route_info["status"] = "delivered"
                        route_info["delivered_time"] = latest_route["accept_time"]
                    elif op_code in ["70", "7000"]:  # 派送中
                        route_info["status"] = "delivering"
                    elif op_code in ["50", "5000"]:  # 运输中
                        route_info["status"] = "in_transit"
                    elif op_code in ["10", "1000"]:  # 已收件
                        route_info["status"] = "picked_up"
                    else:
                        route_info["status"] = "processing"
                
                result[tracking_no] = route_info
                
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            logger.error(f"解析路由响应失败: {e}")
        
        return result
    
    def get_delivery_status(self, tracking_number: str) -> Dict:
        """
        获取快递送达状态
        
        Args:
            tracking_number: 快递单号
            
        Returns:
            Dict: 送达状态信息
        """
        response = self.search_routes(tracking_number)
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


# 创建全局实例（需要配置实际的partner_id和checkword）
def create_sf_client(partner_id: str = None, checkword: str = None, test_mode: bool = True) -> SFExpressAPI:
    """
    创建顺丰API客户端实例
    
    Args:
        partner_id: 合作伙伴ID
        checkword: 校验码
        test_mode: 测试模式
        
    Returns:
        SFExpressAPI: API客户端实例
    """
    # 这里应该从配置文件或环境变量中读取
    if not partner_id or not checkword:
        # 默认测试参数（需要替换为实际参数）
        partner_id = partner_id or "test_partner_id"
        checkword = checkword or "test_checkword"
    
    return SFExpressAPI(partner_id, checkword, test_mode)


# 便捷函数
def query_tracking_info(tracking_number: str, partner_id: str = None, checkword: str = None) -> Dict:
    """
    查询单个快递信息的便捷函数
    
    Args:
        tracking_number: 快递单号
        partner_id: 合作伙伴ID
        checkword: 校验码
        
    Returns:
        Dict: 快递信息
    """
    client = create_sf_client(partner_id, checkword)
    return client.get_delivery_status(tracking_number)


def batch_query_tracking_info(tracking_numbers: List[str], partner_id: str = None, checkword: str = None) -> Dict[str, Dict]:
    """
    批量查询快递信息的便捷函数
    
    Args:
        tracking_numbers: 快递单号列表
        partner_id: 合作伙伴ID
        checkword: 校验码
        
    Returns:
        Dict: 快递信息字典，键为单号
    """
    client = create_sf_client(partner_id, checkword)
    response = client.batch_search_routes(tracking_numbers)
    return client.parse_route_response(response)