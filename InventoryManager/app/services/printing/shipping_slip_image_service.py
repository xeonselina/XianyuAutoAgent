"""
发货单图像生成服务
使用PIL生成适配80mm热敏纸的精简发货单图像
"""
import base64
import io
import logging
import os
from typing import Optional
from datetime import timedelta

from PIL import Image, ImageDraw, ImageFont

from app.models import Rental
from app import db

logger = logging.getLogger(__name__)


class SlipGenerationError(Exception):
    """发货单生成失败异常"""
    pass


class ShippingSlipImageService:
    """发货单图像生成服务"""

    def __init__(self, width_mm: int = 80, dpi: int = 203):
        """
        初始化服务

        Args:
            width_mm: 纸张宽度(毫米)
            dpi: 打印分辨率
        """
        self.width_px = int(width_mm * dpi / 25.4)  # 转换为像素 (~640px)
        self.dpi = dpi
        self.padding = 20  # 边距
        self.line_spacing = 11  # 行间距(增加10%)

        # 获取项目根目录
        self.project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
        self.qr_codes_dir = os.path.join(self.project_root, 'frontend', 'src', 'assets')

        # 尝试加载字体,如果失败则使用默认字体（字体缩小10%）
        # 字体路径优先级: macOS PingFang -> Linux Noto CJK -> PIL默认
        font_paths = [
            "/System/Library/Fonts/PingFang.ttc",  # macOS
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",  # Linux Noto
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",  # 备选路径
        ]

        font_loaded = False
        for font_path in font_paths:
            try:
                self.font_large = ImageFont.truetype(font_path, 41)  # 45 * 0.9 ≈ 41
                self.font_medium = ImageFont.truetype(font_path, 35)  # 39 * 0.9 ≈ 35
                self.font_small = ImageFont.truetype(font_path, 30)  # 33 * 0.9 ≈ 30
                logger.info(f"成功加载字体: {font_path}")
                font_loaded = True
                break
            except Exception:
                continue

        if not font_loaded:
            logger.warning("无法加载任何中文字体,使用PIL默认字体")
            self.font_large = ImageFont.load_default()
            self.font_medium = ImageFont.load_default()
            self.font_small = ImageFont.load_default()

    def _mask_phone(self, phone: str) -> str:
        """手机号脱敏"""
        if not phone or len(phone) < 11:
            return phone
        return phone[:3] + '****' + phone[-4:]

    def _wrap_text(self, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list:
        """
        文本换行处理

        Args:
            text: 要换行的文本
            font: 字体
            max_width: 最大宽度(像素)

        Returns:
            换行后的文本列表
        """
        lines = []
        current_line = ''

        for char in text:
            test_line = current_line + char
            bbox = font.getbbox(test_line)
            width = bbox[2] - bbox[0]

            if width <= max_width:
                current_line = test_line
            else:
                if current_line:
                    lines.append(current_line)
                current_line = char

        if current_line:
            lines.append(current_line)

        return lines if lines else ['']

    def _draw_section_separator(self, draw: ImageDraw.Draw, y: int) -> int:
        """
        绘制分隔线

        Args:
            draw: ImageDraw对象
            y: 当前Y坐标

        Returns:
            新的Y坐标
        """
        y += 10
        # 绘制虚线分隔符
        x = self.padding
        dash_length = 10
        gap_length = 5
        while x < self.width_px - self.padding:
            draw.line([(x, y), (x + dash_length, y)], fill='black', width=1)
            x += dash_length + gap_length
        return y + 10

    def _load_and_resize_qr_code(self, filename: str, target_size: int) -> Optional[Image.Image]:
        """
        加载并调整二维码图片大小

        Args:
            filename: 图片文件名
            target_size: 目标尺寸(像素)

        Returns:
            调整大小后的图片对象，如果加载失败则返回None
        """
        try:
            qr_path = os.path.join(self.qr_codes_dir, filename)
            if not os.path.exists(qr_path):
                logger.warning(f"二维码图片不存在: {qr_path}")
                return None

            qr_img = Image.open(qr_path)
            # 转换为RGB模式（如果是RGBA）
            if qr_img.mode == 'RGBA':
                # 创建白色背景
                background = Image.new('RGB', qr_img.size, (255, 255, 255))
                background.paste(qr_img, mask=qr_img.split()[3])  # 使用alpha通道作为mask
                qr_img = background
            elif qr_img.mode != 'RGB':
                qr_img = qr_img.convert('RGB')

            # 调整大小
            qr_img = qr_img.resize((target_size, target_size), Image.Resampling.LANCZOS)
            return qr_img

        except Exception as e:
            logger.error(f"加载二维码图片失败: {filename}, 错误: {e}")
            return None

    def _draw_qr_codes_section(self, img: Image.Image, y: int) -> int:
        """
        绘制底部二维码区域（垂直排列）

        Args:
            img: 主图像对象
            y: 当前Y坐标

        Returns:
            新的Y坐标
        """
        # 二维码配置
        qr_codes = [
            ('镜头安装教程.png', '镜头安装教程'),
            ('拍摄调试教程.png', '拍摄调试教程'),
            ('照片传输教程.png', '照片传输教程')
        ]

        qr_size = 150  # 每个二维码的尺寸
        vertical_spacing = 10  # 二维码之间的垂直间距

        y += 15  # 顶部留白

        # 创建二维码标签专用字体（缩小20%）
        qr_label_size = 24  # 30 * 0.8 = 24
        font_paths = [
            "/System/Library/Fonts/PingFang.ttc",
            "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
            "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        ]

        qr_label_font = self.font_small  # 默认使用小号字体
        for font_path in font_paths:
            try:
                qr_label_font = ImageFont.truetype(font_path, qr_label_size)
                break
            except Exception:
                continue

        # 绘制三个二维码（垂直排列，交替左右）
        # 第1个：居左，标题在右边
        # 第2个：居右，标题在左边
        # 第3个：居左，标题在右边
        draw = ImageDraw.Draw(img)

        for idx, (filename, label) in enumerate(qr_codes):
            # 加载二维码图片
            qr_img = self._load_and_resize_qr_code(filename, qr_size)
            if not qr_img:
                continue

            # 第2个二维码（索引1）居右，其他居左
            if idx == 1:
                # 第2个：居右，标题在左边
                qr_x = self.width_px - self.padding - qr_size

                # 标题在二维码左边
                bbox = qr_label_font.getbbox(label)
                label_width = bbox[2] - bbox[0]
                label_height = bbox[3] - bbox[1]
                label_x = qr_x - 15 - label_width  # 二维码左边留15px间距
                label_y = y + (qr_size - label_height) // 2  # 垂直居中

                # 先绘制标题，再粘贴二维码
                draw.text((label_x, label_y), label, fill='black', font=qr_label_font)
                img.paste(qr_img, (qr_x, y))
            else:
                # 第1、3个：居左，标题在右边
                qr_x = self.padding

                # 粘贴二维码
                img.paste(qr_img, (qr_x, y))

                # 标题在二维码右边
                label_x = qr_x + qr_size + 15  # 二维码右边留15px间距
                bbox = qr_label_font.getbbox(label)
                label_height = bbox[3] - bbox[1]
                label_y = y + (qr_size - label_height) // 2  # 垂直居中
                draw.text((label_x, label_y), label, fill='black', font=qr_label_font)

            # 移动到下一个二维码位置
            y += qr_size + vertical_spacing

        # 返回最终Y位置
        return y + 10

    def _draw_info_row(self, draw: ImageDraw.Draw, y: int, label: str, value: str,
                      label_font: ImageFont.FreeTypeFont = None,
                      value_font: ImageFont.FreeTypeFont = None,
                      highlight: bool = False) -> int:
        """
        绘制信息行

        Args:
            draw: ImageDraw对象
            y: 当前Y坐标
            label: 标签文本
            value: 值文本
            label_font: 标签字体
            value_font: 值字体
            highlight: 是否高亮

        Returns:
            新的Y坐标
        """
        if label_font is None:
            label_font = self.font_small
        if value_font is None:
            value_font = self.font_small

        x = self.padding
        label_width = 180  # 标签固定宽度（从120增加到180以容纳更大字体）

        # 绘制标签
        draw.text((x, y), label, fill='black', font=label_font)

        # 绘制值(可能需要换行)
        value_x = x + label_width
        max_value_width = self.width_px - value_x - self.padding
        value_lines = self._wrap_text(value, value_font, max_value_width)

        value_color = 'red' if highlight else 'black'
        for line in value_lines:
            draw.text((value_x, y), line, fill=value_color, font=value_font)
            bbox = value_font.getbbox(line)
            y += bbox[3] - bbox[1] + 5

        return y

    def generate_slip_image(self, rental_id: int) -> str:
        """
        生成发货单图像

        Args:
            rental_id: 租赁记录ID

        Returns:
            str: base64编码的PNG图像

        Raises:
            SlipGenerationError: 生成失败时抛出
        """
        try:
            # 查询租赁记录
            rental = db.session.get(Rental, rental_id)
            if not rental:
                raise SlipGenerationError(f"租赁记录不存在: ID {rental_id}")

            # 创建图像(先创建足够高的图像,后续裁剪)
            img = Image.new('RGB', (self.width_px, 2000), 'white')
            draw = ImageDraw.Draw(img)

            y = self.padding

            # 1. 订单号部分
            order_text = f"光影租界: R-{rental.id}"
            bbox = self.font_large.getbbox(order_text)
            text_width = bbox[2] - bbox[0]
            x_centered = (self.width_px - text_width) // 2
            draw.text((x_centered, y), order_text, fill='black', font=self.font_large)
            y += bbox[3] - bbox[1] + 15

            y = self._draw_section_separator(draw, y)

            # 2. 客户信息部分
            y = self._draw_info_row(draw, y, "收货人:", rental.customer_name or '未填写')

            y = self._draw_section_separator(draw, y)

            # 3. 设备信息部分
            device_name = rental.device.name if rental.device else '未知设备'
            y = self._draw_info_row(draw, y, "设备:", device_name)

            # 附件信息（从child_rentals获取）
            child_rentals = list(rental.child_rentals.all()) if hasattr(rental, 'child_rentals') else []
            if child_rentals:
                accessories_list = []
                for child in child_rentals:
                    if child.device:
                        # 获取附件名称和型号
                        acc_name = child.device.name
                        acc_model = ''
                        if child.device.device_model:
                            acc_model = child.device.device_model.name
                        elif child.device.model:
                            acc_model = child.device.model

                        accessories_list.append(f"{acc_name}{(' ' + acc_model) if acc_model else ''}")

                if accessories_list:
                    accessories_text = ', '.join(accessories_list)
                    y = self._draw_info_row(draw, y, "附件:", accessories_text)

            y = self._draw_section_separator(draw, y)

            # 4. 归还时间（租期结束日期 + 1天）
            if rental.end_date:
                return_date = rental.end_date + timedelta(days=1)
                return_deadline = f"{return_date.strftime('%Y-%m-%d')} 16:00前"
            else:
                return_deadline = "-"
            y = self._draw_info_row(draw, y, "归还:", return_deadline, highlight=True)

            y = self._draw_section_separator(draw, y)

            # 5. 归还地址部分
            y = self._draw_info_row(draw, y, "寄回地址:", "广东省深圳市南山区西丽街道松坪村竹苑9栋4单元415")
            y = self._draw_info_row(draw, y, "收件人:", "张女士")
            y = self._draw_info_row(draw, y, "电话:", "13510224947")

            y = self._draw_section_separator(draw, y)

            # 6. 底部二维码区域
            y = self._draw_qr_codes_section(img, y)

            # 裁剪图像到实际使用的高度
            y += self.padding
            img = img.crop((0, 0, self.width_px, y))

            # 优化图像以适配热敏打印机(参考快递面单的压缩方式)
            # 1. 转换为灰度图
            img = img.convert('L')

            # 2. 增强对比度
            def enhance_contrast(x):
                if x < 128:
                    return int(x * 0.7)  # 暗区域变更暗
                else:
                    return min(255, int(128 + (x - 128) * 1.3))  # 亮区域变更亮

            img = img.point(enhance_contrast)

            # 3. 转换为1位黑白模式，使用Floyd-Steinberg抖动
            img = img.convert('1', dither=Image.Dither.FLOYDSTEINBERG)

            # 转换为base64 (1位PNG比JPEG小得多)
            buffer = io.BytesIO()
            img.save(buffer, format='PNG')
            image_data = buffer.getvalue()

            # 记录图像大小用于调试
            logger.info(f"发货单图像大小: {len(image_data)} bytes (~{len(image_data)/1024:.1f} KB)")

            return base64.b64encode(image_data).decode('utf-8')

        except SlipGenerationError:
            raise
        except Exception as e:
            logger.exception(f"生成发货单图像失败: rental_id={rental_id}")
            raise SlipGenerationError(f"生成发货单图像失败: {str(e)}")


# 全局单例 (76mm宽度符合实际热敏纸尺寸76×130mm)
shipping_slip_image_service = ShippingSlipImageService(width_mm=76, dpi=203)
