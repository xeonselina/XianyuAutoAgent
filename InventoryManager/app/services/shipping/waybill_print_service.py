"""
快递面单打印服务
整合顺丰面单获取、PDF转换和快麦云打印功能
"""
import logging
from typing import Dict, List, Optional

from app.models import Rental
from app.services.shipping.pdf_conversion_service import PDFConversionService, PDFConversionError
from app.services.shipping.sf_express_service import get_sf_express_service
from app.services.printing.kuaimai_service import KuaimaiPrintService

logger = logging.getLogger(__name__)


class WaybillPrintService:
    """快递面单打印服务"""

    def __init__(self):
        """初始化面单打印服务"""
        self.sf_service = get_sf_express_service()
        self.pdf_service = PDFConversionService(default_dpi=203)
        self.kuaimai_service = KuaimaiPrintService()

        logger.info("WaybillPrintService初始化完成")

    def print_single_waybill(
        self,
        rental_id: int
    ) -> Dict:
        """
        打印单个面单

        Args:
            rental_id: 租赁记录ID

        Returns:
            Dict: {
                'success': bool,
                'rental_id': int,
                'message': str,
                'job_id': str (可选)
            }
        """
        logger.info(f"开始打印面单: Rental {rental_id}")

        try:
            # 1. 查询租赁记录
            logger.info(f"Rental {rental_id}: 步骤1 - 查询租赁记录")
            rental = Rental.query.get(rental_id)
            if not rental:
                logger.error(f"Rental {rental_id}: 租赁记录不存在")
                return {
                    'success': False,
                    'rental_id': rental_id,
                    'message': '租赁记录不存在'
                }
            logger.info(f"Rental {rental_id}: 查询成功，客户: {rental.customer_name}")

            # 2. 检查运单号
            logger.info(f"Rental {rental_id}: 步骤2 - 检查运单号")
            if not rental.ship_out_tracking_no:
                logger.error(f"Rental {rental_id}: 缺少运单号")
                return {
                    'success': False,
                    'rental_id': rental_id,
                    'message': '缺少运单号'
                }
            logger.info(f"Rental {rental_id}: 运单号: {rental.ship_out_tracking_no}")

            # 3. 检查是否已发货
            logger.info(f"Rental {rental_id}: 步骤3 - 检查发货状态")
            logger.info(f"Rental {rental_id}: 当前状态: {rental.status}")
            #if rental.status == 'shipped':
            #    logger.warning(f"Rental {rental_id}: 订单已发货，无需打印")
            #    return {
            #        'success': False,
            #        'rental_id': rental_id,
            #        'message': '订单已发货，无需打印'
            #    }

            # 4. 从顺丰获取面单PDF
            logger.info(f"Rental {rental_id}: 步骤4 - 从顺丰获取面单PDF")
            sf_result = self.sf_service.get_waybill_pdf(rental)
            logger.info(f"Rental {rental_id}: 顺丰API返回: success={sf_result.get('success')}, message={sf_result.get('message')}")

            if not sf_result.get('success'):
                logger.error(f"Rental {rental_id}: 获取面单失败: {sf_result.get('message')}")
                return {
                    'success': False,
                    'rental_id': rental_id,
                    'message': f"获取面单失败: {sf_result.get('message')}"
                }

            pdf_data = sf_result.get('pdf_data')
            logger.info(f"Rental {rental_id}: PDF数据类型: {type(pdf_data)}, 长度: {len(pdf_data) if pdf_data else 0}")

            # 5. 将PDF转换为base64图像
            logger.info(f"Rental {rental_id}: 步骤5 - 转换PDF为图像")
            try:
                base64_images = self.pdf_service.convert_pdf_to_base64_images(pdf_data)
                logger.info(f"Rental {rental_id}: PDF转换成功，共{len(base64_images)}张图像")
            except PDFConversionError as e:
                logger.error(f"Rental {rental_id}: PDF转换失败: {str(e)}", exc_info=True)
                return {
                    'success': False,
                    'rental_id': rental_id,
                    'message': f"PDF转换失败: {str(e)}"
                }

            if not base64_images:
                logger.error(f"Rental {rental_id}: PDF转换结果为空")
                return {
                    'success': False,
                    'rental_id': rental_id,
                    'message': 'PDF转换结果为空'
                }

            # 6. 发送到快麦打印机
            logger.info(f"Rental {rental_id}: 步骤6 - 发送到快麦打印机，共{len(base64_images)}页")
            print_results = []
            for idx, base64_image in enumerate(base64_images):
                logger.info(f"Rental {rental_id}: 打印第{idx + 1}/{len(base64_images)}页")
                print_result = self.kuaimai_service.print_image(
                    base64_image=base64_image,
                    copies=1
                )
                logger.info(f"Rental {rental_id}: 第{idx + 1}页打印结果: {print_result}")
                print_results.append(print_result)

                # 如果任何一页打印失败，立即返回错误
                if not print_result.get('success'):
                    logger.error(f"Rental {rental_id}: 打印第{idx + 1}页失败: {print_result.get('error')}")
                    return {
                        'success': False,
                        'rental_id': rental_id,
                        'message': f"打印第{idx + 1}页失败: {print_result.get('error')}"
                    }

            # 7. 所有页打印成功
            job_ids = [r.get('job_id') for r in print_results if r.get('job_id')]
            logger.info(f"Rental {rental_id}: 步骤7 - 面单打印成功，任务ID: {job_ids}")

            return {
                'success': True,
                'rental_id': rental_id,
                'message': '打印成功',
                'job_ids': job_ids
            }

        except Exception as e:
            import traceback
            logger.error(f"打印面单异常: Rental {rental_id}, {e}")
            logger.error(f"完整堆栈:\n{traceback.format_exc()}")
            return {
                'success': False,
                'rental_id': rental_id,
                'message': f'打印异常: {str(e)}'
            }

    def batch_print_waybills(
        self,
        rental_ids: List[int]
    ) -> Dict:
        """
        批量打印面单（顺序打印）

        Args:
            rental_ids: 租赁记录ID列表

        Returns:
            Dict: {
                'total': int,
                'success_count': int,
                'failed_count': int,
                'results': List[Dict]
            }
        """
        logger.info(f"开始批量打印面单: {len(rental_ids)}个订单")

        results = []

        # 顺序处理每个打印任务
        for idx, rental_id in enumerate(rental_ids, 1):
            logger.info(f"处理第 {idx}/{len(rental_ids)} 个订单: Rental {rental_id}")
            try:
                result = self.print_single_waybill(rental_id)
                results.append(result)
                if result.get('success'):
                    logger.info(f"Rental {rental_id} 打印成功")
                else:
                    logger.error(f"Rental {rental_id} 打印失败: {result.get('message')}")
            except Exception as e:
                logger.error(f"Rental {rental_id} 打印任务异常: {e}", exc_info=True)
                results.append({
                    'success': False,
                    'rental_id': rental_id,
                    'message': f'任务异常: {str(e)}'
                })

        # 统计结果
        success_count = sum(1 for r in results if r.get('success'))
        failed_count = len(results) - success_count

        logger.info(f"批量打印完成: 总数 {len(results)}, 成功 {success_count}, 失败 {failed_count}")

        return {
            'total': len(results),
            'success_count': success_count,
            'failed_count': failed_count,
            'results': results
        }


# 创建全局实例
_waybill_print_service = None


def get_waybill_print_service() -> WaybillPrintService:
    """获取面单打印服务单例"""
    global _waybill_print_service
    if _waybill_print_service is None:
        _waybill_print_service = WaybillPrintService()
    return _waybill_print_service
