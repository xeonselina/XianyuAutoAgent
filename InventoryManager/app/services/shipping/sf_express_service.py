"""
顺丰速运 API 服务 - 速运下单接口
"""

import os
import re
import logging
import tempfile
import requests
import base64
import time
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

    def place_shipping_order(self, rental, scheduled_time) -> Dict:
        """
        下速运订单

        Args:
            rental: 租赁记录对象
            scheduled_time: 预约发货时间（必需，datetime对象）

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

            if not scheduled_time:
                logger.error(f"Rental {rental.id} 缺少预约发货时间")
                return {
                    'success': False,
                    'message': '缺少预约发货时间'
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

            # 格式化预约发货时间为 YYYY-MM-DD HH24:MM:SS
            send_start_tm = scheduled_time.strftime('%Y-%m-%d %H:%M:%S')

            # 构建订单数据
            order_data = {
                'language': 'zh-CN',
                'orderId': f"R{rental.id}_{rental.customer_name}",  # 客户订单号（使用时间戳）
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
                'sendStartTm': send_start_tm,  # 预约发货时间
                'waybillNoInfoList': [{'waybillType': 1}],  # 运单号
                'isGenWaybillNo': 1,
                'isUnifiedWaybillNo': 1,
                'isDocall': 1
            }
            if express_type_id == 263:
                order_data['specialDeliveryTypeCode'] = 263
            

            # 快递类型名称映射
            express_type_names = {1: '特快', 2: '标快', 263: '半日达'}
            express_type_name = express_type_names.get(express_type_id, '未知')

            logger.info(f"顺丰下单: Rental {rental.id}, 快递类型: {express_type_id}({express_type_name}), 预约时间: {send_start_tm}")
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

    def _download_pdf(self, pdf_url: str, pdf_token: str, waybill_no: str) -> bytes:
        """
        从顺丰服务器下载PDF文件

        Args:
            pdf_url: PDF文件下载地址
            pdf_token: 认证token
            waybill_no: 运单号（用于保存临时文件）

        Returns:
            bytes: PDF文件的二进制数据

        Raises:
            Exception: 下载失败时抛出异常
        """
        try:
            logger.info(f"开始下载面单PDF: {waybill_no}")
            logger.info(f"PDF URL: {pdf_url}")

            # 设置请求头
            headers = {
                'X-Auth-Token': pdf_token
            }

            # 发送GET请求下载PDF
            response = requests.get(pdf_url, headers=headers, timeout=30)
            logger.info(f"下载面单PDF响应: {response.status_code}")
            response.raise_for_status()

            pdf_data = response.content
            logger.info(f"下载面单PDF成功: {waybill_no}, 大小: {len(pdf_data)} 字节")

            # 保存到临时目录用于调试
            temp_dir = tempfile.gettempdir()
            temp_file_path = os.path.join(temp_dir, f"sf_waybill_{waybill_no}.pdf")

            logger.info(f"准备保存PDF到: {temp_dir}")
            logger.info(f"完整路径: {temp_file_path}")

            try:
                with open(temp_file_path, 'wb') as f:
                    bytes_written = f.write(pdf_data)
                logger.info(f"写入了 {bytes_written} 字节到文件")

                # 验证文件是否存在
                if os.path.exists(temp_file_path):
                    file_size = os.path.getsize(temp_file_path)
                    logger.info(f"文件验证成功: {temp_file_path}, 大小: {file_size} 字节")
                else:
                    logger.error(f"文件写入后不存在: {temp_file_path}")
            except Exception as write_error:
                logger.error(f"写入文件失败: {write_error}", exc_info=True)

            return pdf_data

        except requests.exceptions.RequestException as e:
            logger.error(f"下载面单PDF失败: {waybill_no}, {e}")
            raise Exception(f"下载面单PDF失败: {str(e)}") from e
        except Exception as e:
            logger.error(f"保存面单PDF到临时文件失败: {waybill_no}, {e}")
            raise

    def get_waybill_pdf(self, rental) -> Dict:
        """
        获取快递面单PDF
        调用顺丰COM_RECE_CLOUD_PRINT_WAYBILLS接口

        Args:
            rental: 租赁记录对象

        Returns:
            Dict: {
                'success': bool,
                'pdf_data': bytes (可选),
                'message': str
            }
        """
        try:
            logger.info(f"get_waybill_pdf 开始执行: Rental {rental.id}")

            # 检查运单号
            logger.info(f"Rental {rental.id}: 检查运单号")
            if not rental.ship_out_tracking_no:
                logger.error(f"Rental {rental.id} 缺少运单号")
                return {
                    'success': False,
                    'message': '缺少运单号'
                }
            logger.info(f"Rental {rental.id}: 运单号 = {rental.ship_out_tracking_no}")

            # 检查收件人信息
            logger.info(f"Rental {rental.id}: 检查收件人信息")
            if not rental.customer_name or not rental.customer_phone or not rental.destination:
                logger.error(f"Rental {rental.id} 缺少收件人信息: customer_name={rental.customer_name}, phone={rental.customer_phone}, destination={rental.destination}")
                return {
                    'success': False,
                    'message': '缺少收件人信息'
                }
            logger.info(f"Rental {rental.id}: 收件人信息完整")

            # 解析目的地信息
            destination_info = self._parse_destination(rental.destination)
            receiver_name = destination_info.get('name', rental.customer_name)
            receiver_phone = destination_info.get('phone', rental.customer_phone)
            receiver_address = destination_info.get('address', rental.destination)

            # 构建备注信息
            remark = f"客户名：{rental.customer_name}| "

            # 添加设备信息
            if rental.device:
                remark+=f"设备号：{rental.device.name}| "

            # 添加附件信息
            accessories = []
            
            # 添加标准附件（勾选的）
            if rental.includes_handle:
                accessories.append("手柄")
            if rental.includes_lens_mount:
                accessories.append("转接环")
            
            # 添加个性化附件（child_rentals）
            if rental.child_rentals:
                for child_rental in rental.child_rentals:
                    if child_rental.device and child_rental.device.device_model:
                        accessories.append(child_rental.device.device_model.name)
            
            if accessories:
                remark+=f"附件：{'、'.join(accessories)}| "

            # 添加寄出日期
            if rental.ship_out_time:
                remark+=f"\n寄出日期：{rental.ship_out_time.strftime('%Y-%m-%d')}| "

            # 添加寄还时间
            if rental.ship_in_time:
                remark+=f"寄还时间：{rental.ship_in_time.strftime('%Y-%m-%d')} 16:00前"

            # 构建面单打印请求数据
            waybill_data = {
                'language': 'zh-CN',
                'documents': [
                    {
                        'masterWaybillNo': rental.ship_out_tracking_no,
                        'isPrintLogo': 'true',
                        'remark': remark
                    }
                ],
                'templateCode': 'fm_76130_standard_Y45WBDEO',  # 标准模板
                'version': '2.0',
                'fileType': 'pdf',  # 返回PDF格式
                'sync': 1  # 同步返回
            }

            logger.info(f"Rental {rental.id}: 调用顺丰API获取面单PDF")
            logger.info(f"Rental {rental.id}: 运单号 {rental.ship_out_tracking_no}")
            logger.info(f"Rental {rental.id}: 面单请求数据: {waybill_data}")

            # 调用顺丰SDK
            logger.info(f"Rental {rental.id}: 开始调用顺丰SDK")
            result = self.client._call_sf_express_service('COM_RECE_CLOUD_PRINT_WAYBILLS', waybill_data)
            logger.info(f"Rental {rental.id}: 顺丰API原始响应: {result}")

            # 检查API调用结果
            logger.info(f"Rental {rental.id}: 检查API响应码")
            if result.get('apiResultCode') != 'A1000':
                error_msg = result.get('apiErrorMsg', '未知错误')
                logger.error(f"Rental {rental.id}: 获取面单PDF失败，API错误码: {result.get('apiResultCode')}, 错误: {error_msg}")
                return {
                    'success': False,
                    'message': f'顺丰API错误: {error_msg}'
                }
            logger.info(f"Rental {rental.id}: API响应码正常 (A1000)")

            # 解析apiResultData
            logger.info(f"Rental {rental.id}: 解析apiResultData")
            import json
            api_result_data = result.get('apiResultData', '{}')
            logger.info(f"Rental {rental.id}: apiResultData类型: {type(api_result_data)}")
            if isinstance(api_result_data, str):
                logger.info(f"Rental {rental.id}: apiResultData是字符串，进行JSON解析")
                api_result_data = json.loads(api_result_data)
            logger.info(f"Rental {rental.id}: 解析后的apiResultData: {api_result_data}")

            if not api_result_data.get('success', False):
                error_msg = api_result_data.get('errorMsg', '未知错误')
                logger.error(f"Rental {rental.id}: 业务处理失败: {error_msg}")
                return {
                    'success': False,
                    'message': error_msg
                }
            logger.info(f"Rental {rental.id}: 业务处理成功")

            # 获取面单文件信息
            logger.info(f"Rental {rental.id}: 获取面单文件信息")
            obj = api_result_data.get('obj', {})
            logger.info(f"Rental {rental.id}: obj = {obj}")
            files = obj.get('files', [])
            logger.info(f"Rental {rental.id}: files数量 = {len(files)}")

            if not files:
                logger.error(f"Rental {rental.id}: 顺丰API未返回面单文件")
                return {
                    'success': False,
                    'message': '未获取到面单文件'
                }

            pdf_url = files[0]['url']
            pdf_token = files[0]['token']
            logger.info(f"Rental {rental.id}: PDF URL = {pdf_url}")
            logger.info(f"Rental {rental.id}: PDF Token = {pdf_token}")

            # 下载 pdf 文件
            logger.info(f"Rental {rental.id}: 开始下载PDF文件")
            pdf_data = self._download_pdf(pdf_url, pdf_token, rental.ship_out_tracking_no)
            logger.info(f"Rental {rental.id}: PDF下载完成，数据类型: {type(pdf_data)}, 长度: {len(pdf_data) if pdf_data else 0}")

            return {
                'success': True,
                'pdf_data': pdf_data,
                'message': '获取成功'
            }

        except Exception as e:
            import traceback
            logger.error(f"获取面单PDF异常: Rental {rental.id}, {e}")
            logger.error(f"完整堆栈:\n{traceback.format_exc()}")
            return {
                'success': False,
                'message': f'获取面单异常: {str(e)}'
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
