"""
OCR相关API模块
"""

from flask import Blueprint, request, jsonify, current_app, send_file
import os
import base64
import io
from PIL import Image
import sys
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from ocr_functions import recognize_id_card

bp = Blueprint('ocr_api', __name__)


@bp.route('/api/ocr/id-card', methods=['POST'])
def ocr_id_card():
    """身份证OCR识别"""
    try:
        # 检查是否有文件上传 - 支持多种字段名
        file = None
        for field_name in ['id_card', 'image', 'file']:
            if field_name in request.files:
                file = request.files[field_name]
                break
        
        if not file:
            return jsonify({
                'success': False,
                'error': '没有上传图片文件'
            }), 400
        
        # 检查文件类型
        if not file.filename.lower().endswith(('.png', '.jpg', '.jpeg')):
            return jsonify({
                'success': False,
                'error': '只支持PNG、JPG、JPEG格式的图片'
            }), 400
        
        # 读取图片
        try:
            image = Image.open(file.stream)
            # 转换为RGB模式（如果是RGBA）
            if image.mode == 'RGBA':
                image = image.convert('RGB')
        except Exception as e:
            return jsonify({
                'success': False,
                'error': f'图片读取失败: {str(e)}'
            }), 400
        
        # 调用OCR识别函数
        image_bytes = io.BytesIO()
        image.save(image_bytes, format='JPEG')
        image_data = image_bytes.getvalue()
        
        # 调用OCR识别函数
        ocr_result = recognize_id_card(image_data)
        
        if ocr_result:
            return jsonify({
                'success': True,
                'data': ocr_result
            })
        else:
            return jsonify({
                'success': False,
                'error': 'OCR识别失败，未能提取到有效信息'
            }), 400
        
    except Exception as e:
        current_app.logger.error(f"OCR识别失败: {e}")
        return jsonify({
            'success': False,
            'error': f'识别服务异常: {str(e)}'
        }), 500

