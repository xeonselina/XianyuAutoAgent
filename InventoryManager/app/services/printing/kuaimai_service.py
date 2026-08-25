"""
快麦云打印服务
提供与快麦云打印平台的集成功能
"""
import hashlib
import logging
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class KuaimaiServiceConfig:
    app_id: str
    app_secret: str
    printer_sn: str


class KuaimaiPrintService:
    """快麦云打印服务"""

    # API基础URL
    BASE_URL = "http://cloud.kuaimai.com"

    # API端点映射
    API_ENDPOINTS = {
        'tsplXmlWrite': '/api/cloud/print/tsplXmlWrite',
        'getPrintJobStatus': '/api/cloud/print/result',
    }

    def __init__(self, config: KuaimaiServiceConfig):
        """初始化当前仓库的快麦服务。"""
        self.config = config
        self.app_id = config.app_id
        self.app_secret = config.app_secret
        self.default_printer_sn = config.printer_sn
        self.configured = True

    def _generate_sign(self, params: Dict) -> str:
        """
        生成快麦API签名
        签名算法: MD5(appSecret + 按ASCII排序的参数 + appSecret)

        Args:
            params: API请求参数字典

        Returns:
            32位小写MD5签名
        """
        # 按key的ASCII顺序排序
        sorted_params = sorted(params.items())

        # 构建签名字符串: appSecret + key1value1key2value2... + appSecret
        sign_str = self.app_secret
        for key, value in sorted_params:
            sign_str += f"{key}{value}"
        sign_str += self.app_secret

        # 计算MD5
        return hashlib.md5(sign_str.encode('utf-8')).hexdigest()

    def _make_request(
        self,
        method: str,
        params: Dict,
        retry_on_rate_limit: bool = True
    ) -> Dict:
        """
        发起快麦API请求

        Args:
            method: API方法名（如 'tsplXmlWrite'）
            params: 请求参数（业务参数，不包含认证参数）
            retry_on_rate_limit: 是否在限流时重试

        Returns:
            API响应数据

        Raises:
            Exception: API调用失败
        """
        if not self.configured:
            raise Exception("快麦云打印服务配置不完整")

        # 获取API端点
        endpoint = self.API_ENDPOINTS.get(method)
        if not endpoint:
            raise Exception(f"未知的API方法: {method}")

        # 添加认证参数
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        params['appId'] = self.app_id
        params['timestamp'] = timestamp

        # 生成签名
        params['sign'] = self._generate_sign(params)

        # 构建完整URL
        url = f"{self.BASE_URL}{endpoint}"

        try:
            # 直接发送params作为请求体，不嵌套在data字段中
            response = requests.post(
                url,
                json=params,
                headers={'Content-Type': 'application/json'},
                timeout=30
            )
            response.raise_for_status()

            result = response.json()
            # 检查业务错误
            # 文档显示成功时 status=true，失败时 status=false
            if not result.get('status', False):
                error_msg = result.get('message', '未知错误')
                error_code = result.get('code')

                # 处理限流错误（code 6027或特定错误消息）
                if error_code == 6027 or '限流' in error_msg or '过于频繁' in error_msg:
                    if retry_on_rate_limit:
                        logger.warning("遇到API限流，等待2秒后重试")
                        time.sleep(2)
                        return self._make_request(method, params, retry_on_rate_limit=False)

                raise Exception(f"快麦API错误 [{error_code}]")

            return result.get('data', {})

        except requests.exceptions.RequestException as e:
            logger.error(f"快麦API请求失败: {type(e).__name__}")
            raise Exception("快麦API请求失败") from None

    def print_image(
        self,
        base64_image: str,
        copies: int = 1,
        width: int = 76,
        height: int = 130
    ) -> Dict:
        """
        打印base64编码的图像

        Args:
            base64_image: base64编码的图像数据
            printer_sn: 打印机序列号（可选，如果不提供则使用默认打印机）
            copies: 打印份数
            width: 打印宽度(mm)，默认76mm
            height: 打印高度(mm)，默认130mm

        Returns:
            {
                'success': bool,
                'job_id': str (可选),
                'error': str (可选)
            }
        """
        # 如果没有指定打印机SN，使用默认配置
        sn = self.default_printer_sn

        if not sn:
            error_msg = "当前仓库未配置打印机SN"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }

        try:
            # 构建XML字符串，将base64图像嵌入到<img>标签中
            xml_str = f'''<page><render width="{width}" height="{height}"><img x='1' y='1'>{base64_image}</img></render></page>'''

            # 构建打印参数（按照快麦API文档要求）
            params = {
                'sn': sn,
                'xmlStr': xml_str,
                'printTimes': copies
            }

            # 调用tsplXmlWrite接口
            result = self._make_request('tsplXmlWrite', params)

            # 从响应中获取job_id（如果有的话）
            job_id = result.get('jobId', '')
            return {
                'success': True,
                'job_id': job_id
            }

        except Exception as e:
            logger.error(f"打印任务提交失败: {type(e).__name__}")
            return {
                'success': False,
                'error': '快麦打印服务调用失败'
            }

    def get_print_status(self, job_id: str) -> Dict:
        """
        查询打印任务状态

        Args:
            job_id: 打印任务ID

        Returns:
            {
                'status': str,  # 'completed', 'failed', 'pending'
                'message': str,
                'timestamp': str (可选)
            }
        """
        try:
            params = {'jobId': job_id}
            result = self._make_request('getPrintJobStatus', params)

            status = result.get('status', 'unknown')
            message = ''
            timestamp = result.get('timestamp', '')

            return {
                'status': status,
                'message': message,
                'timestamp': timestamp
            }

        except Exception:
            logger.error("查询打印任务状态失败")
            return {
                'status': 'error',
                'message': '快麦打印服务调用失败'
            }


def get_kuaimai_print_service(rental=None, warehouse_id=None):
    """Build a fresh scoped service for temporary legacy callers."""
    from app.services.integration_resolver import IntegrationResolver

    resolver = IntegrationResolver()
    if rental is not None:
        return resolver.kuaimai_for_rental(rental)
    if warehouse_id is not None:
        return resolver.kuaimai_for_warehouse(warehouse_id)
    return resolver.kuaimai_for_only_warehouse()
