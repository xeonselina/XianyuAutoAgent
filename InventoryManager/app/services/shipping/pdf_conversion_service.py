"""
PDF转换服务
将SF快递面单PDF转换为适合热敏打印机的图像格式
"""
import base64
import logging
from io import BytesIO
from typing import List, Optional

from PIL import Image
from pdf2image import convert_from_bytes

logger = logging.getLogger(__name__)


class PDFConversionError(Exception):
    """PDF转换异常"""
    pass


class PDFConversionService:
    """PDF转图像转换服务"""

    def __init__(self, default_dpi: int = 203):
        """
        初始化PDF转换服务

        Args:
            default_dpi: 默认打印机DPI分辨率（203或300）
        """
        self.default_dpi = default_dpi
        logger.info(f"PDFConversionService初始化完成，默认DPI: {default_dpi}")

    def convert_pdf_to_images(
        self,
        pdf_data: bytes,
        dpi: Optional[int] = None
    ) -> List[Image.Image]:
        """
        将PDF字节数据转换为PNG图像列表

        Args:
            pdf_data: PDF文件的二进制数据
            dpi: 目标DPI分辨率（默认使用初始化时的值）

        Returns:
            PIL Image对象列表，每页一个图像

        Raises:
            PDFConversionError: PDF转换失败
        """
        target_dpi = dpi or self.default_dpi
        logger.info(f"开始转换PDF，目标DPI: {target_dpi}")

        try:
            # 使用pdf2image转换PDF为图像
            images = convert_from_bytes(
                pdf_data,
                dpi=target_dpi,
                fmt='PNG'
            )

            logger.info(f"PDF转换成功，共{len(images)}页")
            return images

        except Exception as e:
            error_msg = f"PDF转换失败: {type(e).__name__}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise PDFConversionError(error_msg) from e

    def optimize_for_thermal_printer(self, image: Image.Image) -> Image.Image:
        """
        优化图像以适配热敏打印机
        - 转换为1位黑白模式
        - 应用抖动以提高质量
        - 增强对比度

        Args:
            image: 原始PIL图像

        Returns:
            优化后的PIL图像
        """
        logger.debug("开始优化图像以适配热敏打印机")

        try:
            # 先转换为灰度图
            if image.mode != 'L':
                image = image.convert('L')

            # 增强对比度
            # 使用point函数应用对比度曲线
            # 将中间值向黑白两极推移
            def enhance_contrast(x):
                # 简单的对比度增强：加强黑白对比
                if x < 128:
                    return int(x * 0.7)  # 暗区域变更暗
                else:
                    return min(255, int(128 + (x - 128) * 1.3))  # 亮区域变更亮

            image = image.point(enhance_contrast)

            # 转换为1位黑白模式，使用Floyd-Steinberg抖动
            image = image.convert('1', dither=Image.Dither.FLOYDSTEINBERG)

            logger.debug(f"图像优化完成，最终尺寸: {image.size}, 模式: {image.mode}")
            return image

        except Exception as e:
            logger.error(f"图像优化失败: {e}", exc_info=True)
            # 如果优化失败，尝试简单转换
            return image.convert('1')

    def image_to_base64(self, image: Image.Image) -> str:
        """
        将PIL图像编码为base64字符串

        Args:
            image: PIL图像对象

        Returns:
            base64编码的字符串
        """
        logger.debug("开始将图像转换为base64")

        try:
            # 将图像保存到BytesIO缓冲区
            buffer = BytesIO()
            image.save(buffer, format='PNG')
            buffer.seek(0)

            # 编码为base64
            base64_data = base64.b64encode(buffer.read()).decode('utf-8')

            logger.debug(f"base64编码完成，长度: {len(base64_data)}")
            return base64_data

        except Exception as e:
            logger.error(f"图像base64编码失败: {e}", exc_info=True)
            raise PDFConversionError(f"图像base64编码失败: {str(e)}") from e

    def convert_pdf_to_base64_images(
        self,
        pdf_data: bytes,
        dpi: Optional[int] = None
    ) -> List[str]:
        """
        一站式转换：PDF -> 图像 -> 优化 -> base64

        Args:
            pdf_data: PDF文件的二进制数据
            dpi: 目标DPI分辨率

        Returns:
            base64编码的图像字符串列表

        Raises:
            PDFConversionError: 转换过程中的任何错误
        """
        logger.info("开始完整的PDF转base64流程")
        logger.info(f"输入PDF数据类型: {type(pdf_data)}, 长度: {len(pdf_data) if pdf_data else 0}")

        try:
            # 1. PDF转图像
            logger.info("步骤1: PDF转图像")
            images = self.convert_pdf_to_images(pdf_data, dpi)
            logger.info(f"PDF转图像成功，共{len(images)}页")

            # 2. 优化并转换为base64
            base64_images = []
            for idx, image in enumerate(images):
                logger.info(f"步骤2: 处理第{idx + 1}/{len(images)}页")
                optimized = self.optimize_for_thermal_printer(image)
                logger.info(f"第{idx + 1}页优化完成")
                base64_str = self.image_to_base64(optimized)
                logger.info(f"第{idx + 1}页base64编码完成，长度: {len(base64_str)}")
                base64_images.append(base64_str)

            logger.info(f"完整转换流程完成，共{len(base64_images)}张图像")
            return base64_images

        except PDFConversionError:
            # 已经是我们的异常，直接传递
            logger.error("PDF转换过程中发生PDFConversionError")
            raise
        except Exception as e:
            error_msg = f"PDF转base64流程失败: {type(e).__name__}: {str(e)}"
            logger.error(error_msg, exc_info=True)
            raise PDFConversionError(error_msg) from e
