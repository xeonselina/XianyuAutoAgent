"""
快递面单打印服务
整合顺丰面单获取、PDF转换和快麦云打印功能
"""
import logging
from typing import Dict, List, Optional

from app.models import Rental
from app.services.integration_resolver import (
    ConfigurationIncomplete,
    IntegrationResolver,
)
from app.services.rental.rental_service import WarehouseMismatchError
from app.tenant_context import current_tenant_id
from app.services.shipping.pdf_conversion_service import PDFConversionService, PDFConversionError
from app.services.printing.shipping_slip_image_service import shipping_slip_image_service, SlipGenerationError

logger = logging.getLogger(__name__)


def build_sf_client_order_id(tenant_id: int, rental_id: int) -> str:
    """Return the stable cross-tenant SF customer order id."""
    if tenant_id is None:
        raise ConfigurationIncomplete("tenant", None, ("tenant_id",))
    return f"t{tenant_id}-r{rental_id}"


def validate_shipping_warehouse(rental) -> None:
    """Validate the main Rental and every physical Device warehouse."""
    if rental.parent_rental_id is not None:
        raise WarehouseMismatchError("附件租赁不能单独发货")
    if rental.warehouse_id is None or rental.warehouse is None:
        raise ConfigurationIncomplete(
            "warehouse", rental.warehouse_id, ("warehouse_id",)
        )
    related = [rental, *list(rental.child_rentals)]
    if any(
        row.warehouse_id != rental.warehouse_id
        or row.device is None
        or row.device.warehouse_id != rental.warehouse_id
        for row in related
    ):
        raise WarehouseMismatchError("租赁设备或实际附件不在履约仓库")


def validate_shipping_preflight(rental) -> None:
    """Fail closed before creating a new SF order for one main Rental."""
    validate_shipping_warehouse(rental)
    missing = tuple(
        field for field in ("customer_name", "customer_phone", "destination")
        if not str(getattr(rental, field, None) or "").strip()
    )
    if missing:
        raise ConfigurationIncomplete("rental", rental.id, missing)
    if rental.ship_out_tracking_no:
        raise ValueError("已有运单号，不得重复下单")
    IntegrationResolver().sf_for_rental(rental)


def sf_client_order_id_for(rental) -> str:
    return build_sf_client_order_id(current_tenant_id(), rental.id)


def normalize_sender_address(province, city, address) -> str:
    """Join warehouse address parts without repeating existing prefixes."""
    detail = str(address or "").strip()
    parts = list(dict.fromkeys(str(value or "").strip() for value in (province, city)))
    for part in parts:
        if part and detail.startswith(part):
            detail = detail[len(part):].lstrip()
    return "".join(parts) + detail


class WaybillPrintService:
    """快递面单打印服务"""

    def __init__(self, resolver=None):
        """初始化面单打印服务"""
        self.resolver = resolver or IntegrationResolver()
        self.pdf_service = PDFConversionService(default_dpi=203)

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
            validate_shipping_warehouse(rental)
            # 2. 检查运单号
            logger.info(f"Rental {rental_id}: 步骤2 - 检查运单号")
            if not rental.ship_out_tracking_no:
                logger.error(f"Rental {rental_id}: 缺少运单号")
                return {
                    'success': False,
                    'rental_id': rental_id,
                    'message': '缺少运单号'
                }
            sf_service = self.resolver.sf_for_rental(rental)
            kuaimai_service = self.resolver.kuaimai_for_rental(rental)

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
            sf_result = sf_service.get_waybill_pdf(rental)
            logger.info(f"Rental {rental_id}: 顺丰API返回: success={sf_result.get('success')}")

            if not sf_result.get('success'):
                logger.error(f"Rental {rental_id}: 获取面单失败")
                return {
                    'success': False,
                    'rental_id': rental_id,
                    'message': '顺丰服务调用失败',
                    'code': 'EXTERNAL_SERVICE_ERROR',
                }

            pdf_data = sf_result.get('pdf_data')
            logger.info(f"Rental {rental_id}: PDF数据类型: {type(pdf_data)}, 长度: {len(pdf_data) if pdf_data else 0}")

            # 5. 将PDF转换为base64图像
            logger.info(f"Rental {rental_id}: 步骤5 - 转换PDF为图像")
            try:
                base64_images = self.pdf_service.convert_pdf_to_base64_images(pdf_data)
                logger.info(f"Rental {rental_id}: PDF转换成功，共{len(base64_images)}张图像")
            except PDFConversionError as e:
                logger.error(f"Rental {rental_id}: PDF转换失败: {type(e).__name__}")
                return {
                    'success': False,
                    'rental_id': rental_id,
                    'message': '面单处理失败',
                    'code': 'EXTERNAL_SERVICE_ERROR',
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
                print_result = kuaimai_service.print_image(
                    base64_image=base64_image,
                    copies=1
                )
                logger.info(f"Rental {rental_id}: 第{idx + 1}页打印结果: success={print_result.get('success')}")
                print_results.append(print_result)

                # 如果任何一页打印失败，立即返回错误
                if not print_result.get('success'):
                    logger.error(f"Rental {rental_id}: 打印第{idx + 1}页失败")
                    return {
                        'success': False,
                        'rental_id': rental_id,
                        'message': '快麦打印服务调用失败',
                        'code': 'EXTERNAL_SERVICE_ERROR',
                    }

            # 7. 所有页打印成功
            job_ids = [r.get('job_id') for r in print_results if r.get('job_id')]
            return {
                'success': True,
                'rental_id': rental_id,
                'message': '打印成功',
                'job_ids': job_ids
            }

        except ConfigurationIncomplete:
            return {
                'success': False, 'rental_id': rental_id,
                'message': '仓库发货或打印配置不完整',
                'code': 'CONFIG_INCOMPLETE',
            }
        except WarehouseMismatchError as e:
            return {
                'success': False, 'rental_id': rental_id,
                'message': str(e), 'code': 'WAREHOUSE_MISMATCH',
            }
        except Exception as e:
            logger.error(f"打印面单异常: Rental {rental_id}, {type(e).__name__}")
            return {
                'success': False,
                'rental_id': rental_id,
                'message': '打印服务调用失败',
                'code': 'EXTERNAL_SERVICE_ERROR',
            }

    def _print_single_shipping_slip(
        self, rental_id: int, kuaimai_service, sf_service
    ) -> Dict:
        """
        打印单个发货单

        Args:
            rental_id: 租赁记录ID

        Returns:
            Dict: {
                'success': bool,
                'job_id': str (可选),
                'error': str (可选)
            }
        """
        try:
            logger.info(f"Rental {rental_id}: 开始生成发货单图像")

            # 生成发货单图像
            image_base64 = shipping_slip_image_service.generate_slip_image(
                rental_id,
                return_name=sf_service.sender_name,
                return_phone=sf_service.sender_phone,
                return_address=normalize_sender_address(sf_service.config.province,
                    sf_service.config.city, sf_service.sender_address),
            )

            logger.info(f"Rental {rental_id}: 发货单图像生成成功, 大小: {len(image_base64)} bytes")

            # 发送到快麦打印 (使用实际纸张尺寸76×130mm)
            result = kuaimai_service.print_image(
                base64_image=image_base64,
                copies=1,
                width=76,
                height=130
            )

            if not result.get('success'):
                logger.error(f"Rental {rental_id}: 发货单打印失败")
                return {
                    'success': False,
                    'error': '快麦打印服务调用失败',
                    'code': 'EXTERNAL_SERVICE_ERROR',
                }

            return result

        except SlipGenerationError as e:
            logger.error(f"Rental {rental_id}: 发货单生成失败: {type(e).__name__}")
            return {'success': False, 'error': '发货单生成失败',
                    'code': 'EXTERNAL_SERVICE_ERROR'}

        except Exception as e:
            logger.error(f"Rental {rental_id}: 发货单打印异常: {type(e).__name__}")
            return {'success': False, 'error': '打印服务调用失败',
                    'code': 'EXTERNAL_SERVICE_ERROR'}

    def batch_print_waybills(
        self,
        rental_ids: List[int],
        include_shipping_slips: bool = True
    ) -> Dict:
        """
        批量打印面单（顺序打印，可选交替打印发货单）

        Args:
            rental_ids: 租赁记录ID列表
            include_shipping_slips: 是否同时打印发货单（交替打印）

        Returns:
            Dict: {
                'total': int,
                'waybill_success_count': int,
                'slip_success_count': int (可选),
                'failed_count': int,
                'results': List[Dict]
            }
        """
        logger.info(f"开始批量打印面单: {len(rental_ids)}个订单, 交替打印发货单: {include_shipping_slips}")

        results = []

        # 顺序处理每个打印任务
        for idx, rental_id in enumerate(rental_ids, 1):
            logger.info(f"处理第 {idx}/{len(rental_ids)} 个订单: Rental {rental_id}")
            try:
                # 1. 打印面单
                logger.info(f"Rental {rental_id}: 开始打印面单")
                waybill_result = self.print_single_waybill(rental_id)

                # 如果面单打印失败,跳过发货单
                if not waybill_result.get('success'):
                    logger.error(f"Rental {rental_id}: 面单打印失败,跳过发货单")
                    results.append({
                        'rental_id': rental_id,
                        'waybill_success': False,
                        'slip_success': False,
                        'code': waybill_result.get('code'),
                        'error': waybill_result.get('message', '面单打印失败')
                    })
                    continue

                logger.info(f"Rental {rental_id}: 面单打印成功")

                # 2. 打印发货单(如果启用)
                slip_result = {'success': True, 'job_id': None}
                if include_shipping_slips:
                    logger.info(f"Rental {rental_id}: 开始打印发货单")
                    rental = Rental.query.get(rental_id)
                    sf_service = self.resolver.sf_for_rental(rental)
                    kuaimai_service = self.resolver.kuaimai_for_rental(rental)
                    slip_result = self._print_single_shipping_slip(
                        rental_id, kuaimai_service, sf_service
                    )

                    if slip_result['success']:
                        logger.info(f"Rental {rental_id}: 发货单打印成功")
                    else:
                        logger.error(f"Rental {rental_id}: 发货单打印失败: {slip_result.get('error')}")

                results.append({
                    'rental_id': rental_id,
                    'waybill_success': True,
                    'slip_success': slip_result['success'],
                    'code': slip_result.get('code'),
                    'slip_error': slip_result.get('error'),
                    'job_ids': {
                        'waybill': waybill_result.get('job_ids'),
                        'slip': slip_result.get('job_id')
                    }
                })

            except Exception as e:
                logger.error(f"Rental {rental_id}: 打印任务异常: {type(e).__name__}")
                results.append({
                    'rental_id': rental_id,
                    'waybill_success': False,
                    'slip_success': False,
                    'error': '打印服务调用失败',
                    'code': 'EXTERNAL_SERVICE_ERROR',
                })

        # 统计结果
        waybill_success_count = sum(1 for r in results if r.get('waybill_success'))
        slip_success_count = sum(1 for r in results if r.get('slip_success'))
        failed_count = len(results) - waybill_success_count

        logger.info(f"批量打印完成: 总数 {len(results)}, 面单成功 {waybill_success_count}, 发货单成功 {slip_success_count}, 失败 {failed_count}")

        return {
            'total': len(results),
            'waybill_success_count': waybill_success_count,
            'slip_success_count': slip_success_count if include_shipping_slips else 0,
            'failed_count': failed_count,
            'results': results
        }


def get_waybill_print_service() -> WaybillPrintService:
    """Build a fresh compatibility service until callers resolve by rental."""
    return WaybillPrintService()
