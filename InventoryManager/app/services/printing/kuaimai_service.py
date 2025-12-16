"""
快麦云打印服务
提供与快麦云打印平台的集成功能
"""
import hashlib
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class KuaimaiPrintService:
    """快麦云打印服务"""

    # API基础URL
    BASE_URL = "http://cloud.kuaimai.com"

    # API端点映射
    API_ENDPOINTS = {
        'tsplXmlWrite': '/api/cloud/print/tsplXmlWrite',
        'getPrintJobStatus': '/api/cloud/print/result',
    }

    def __init__(self):
        """初始化快麦云打印服务"""
        self.app_id = os.getenv('KUAIMAI_APP_ID', '')
        self.app_secret = os.getenv('KUAIMAI_APP_SECRET', '')
        self.default_printer_sn = os.getenv('KUAIMAI_PRINTER_SN', '')

        logger.info(f"KUAIMAI_APP_ID: {self.app_id}")
        logger.info(f"KUAIMAI_APP_SECRET: {self.app_secret}")
        logger.info(f"KUAIMAI_PRINTER_SN: {self.default_printer_sn}")

        # 验证配置
        if not self.app_id or not self.app_secret:
            logger.warning("快麦云打印服务未配置：缺少 KUAIMAI_APP_ID 或 KUAIMAI_APP_SECRET")
            self.configured = False
        else:
            logger.info(f"快麦云打印服务初始化完成，AppID: {self.app_id}")
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
        md5_hash = hashlib.md5(sign_str.encode('utf-8')).hexdigest()
        logger.debug(f"生成签名: {md5_hash}")
        return md5_hash

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
            raise Exception("快麦云打印服务未配置，请设置环境变量 KUAIMAI_APP_ID 和 KUAIMAI_APP_SECRET")

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

        logger.info(f"调用快麦API: {method} -> {url}")
        logger.debug(f"请求参数: {params}")

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
            logger.debug(f"API响应: {result}")

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

                raise Exception(f"快麦API错误 [{error_code}]: {error_msg}")

            return result.get('data', {})

        except requests.exceptions.RequestException as e:
            logger.error(f"快麦API请求失败: {e}", exc_info=True)
            raise Exception(f"快麦API请求失败: {str(e)}") from e

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
            error_msg = "未指定打印机SN，且未配置默认打印机（KUAIMAI_PRINTER_SN）"
            logger.error(error_msg)
            return {
                'success': False,
                'error': error_msg
            }

        logger.info(f"发起打印任务，打印机SN: {sn}, 份数: {copies}, 尺寸: {width}x{height}mm")

        try:
            # 构建XML字符串，将base64图像嵌入到<img>标签中
            xml_str = f'''<page>
  <render width="{width}" height="{height}">
    <img x='1' y='1'>{base64_image}</img>
  </render>
</page>'''

            logger.debug(f"XML长度: {len(xml_str)} 字符")

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
            logger.info(f"打印任务提交成功，任务ID: {job_id}")

            return {
                'success': True,
                'job_id': job_id
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"打印任务提交失败: {error_msg}")
            return {
                'success': False,
                'error': error_msg
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
        logger.info(f"查询打印任务状态: {job_id}")

        try:
            params = {'jobId': job_id}
            result = self._make_request('getPrintJobStatus', params)

            status = result.get('status', 'unknown')
            message = result.get('message', '')
            timestamp = result.get('timestamp', '')

            logger.info(f"打印任务 {job_id} 状态: {status}")

            return {
                'status': status,
                'message': message,
                'timestamp': timestamp
            }

        except Exception as e:
            logger.error(f"查询打印任务状态失败: {e}")
            return {
                'status': 'error',
                'message': str(e)
            }
