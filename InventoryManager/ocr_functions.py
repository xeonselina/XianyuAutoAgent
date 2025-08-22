"""
身份证OCR识别相关函数 - 使用阿里云通用OCR识别
"""

import base64
import os
import re
from flask import current_app

# 阿里云OCR SDK
try:
    from alibabacloud_ocr_api20210707.client import Client as OcrClient
    from alibabacloud_tea_openapi import models as open_api_models
    from alibabacloud_ocr_api20210707 import models as ocr_models
    ALIYUN_OCR_AVAILABLE = True
except ImportError:
    ALIYUN_OCR_AVAILABLE = False


def recognize_id_card(image_data):
    """身份证OCR识别函数 - 使用阿里云通用OCR识别"""
    try:
        current_app.logger.info("开始阿里云通用OCR识别...")
        
        # 使用阿里云通用OCR进行识别
        result = _recognize_with_aliyun_advanced_ocr(image_data)
        if result and result.get('name') and result.get('id_number'):
            current_app.logger.info("阿里云通用OCR识别成功")
            return result
        
        current_app.logger.warning("OCR识别失败，未能提取到有效的姓名和身份证号")
        return None
        
    except Exception as e:
        current_app.logger.error(f"身份证OCR识别异常: {e}")
        return None


def _recognize_with_aliyun_advanced_ocr(image_data):
    """使用阿里云通用OCR进行识别"""
    # 检查SDK是否可用
    if not ALIYUN_OCR_AVAILABLE:
        current_app.logger.error("阿里云OCR SDK未安装，请执行: pip install alibabacloud-ocr-api20210707")
        return None
    
    # 检查阿里云配置
    access_key_id = os.getenv('ALIYUN_ACCESS_KEY_ID')
    access_key_secret = os.getenv('ALIYUN_ACCESS_KEY_SECRET')
    
    if not access_key_id or not access_key_secret:
        current_app.logger.error("阿里云OCR配置不完整，请设置环境变量 ALIYUN_ACCESS_KEY_ID 和 ALIYUN_ACCESS_KEY_SECRET")
        return None
    
    try:
        # 创建配置
        config = open_api_models.Config(
            access_key_id=access_key_id,
            access_key_secret=access_key_secret,
            endpoint='ocr-api.cn-hangzhou.aliyuncs.com'
        )
        
        # 创建客户端
        client = OcrClient(config)
        
        # 按照官方文档方式，直接传入图像数据
        request = ocr_models.RecognizeAdvancedRequest(
            body=image_data,           # 直接传入原始图像数据，不需要base64编码
            need_rotate=True,          # 自动旋转
            need_sort_page=True,       # 排序
            output_char_info=False,    # 不需要字符级信息
            output_table=False,        # 不需要表格信息
            no_stamp=True             # 忽略印章
        )
        
        # 调用API（使用带运行时选项的方法，参照官方文档）
        from alibabacloud_tea_util import models as util_models
        runtime = util_models.RuntimeOptions()
        response = client.recognize_advanced_with_options(request, runtime)
        
        # 解析结果
        if response.body and response.body.data:
            # 阿里云通用OCR返回的是字符串格式的内容
            content = response.body.data
            current_app.logger.info(f"阿里云OCR识别到的完整文本: {content}")
            
            # 从识别到的文本中提取身份证信息
            extracted_info = _extract_id_info_from_text(content)
            return extracted_info
        else:
            current_app.logger.warning("阿里云OCR未返回有效数据")
            return None
            
    except Exception as e:
        current_app.logger.error(f"阿里云OCR识别异常: {e}")
        return None


def _extract_id_info_from_text(text):
    """从OCR识别的文本中提取身份证信息"""
    result = {
        'name': '',
        'id_number': '',
        'gender': '',
        'nation': '',
        'birth': '',
        'address': ''
    }
    
    current_app.logger.info(f"开始从文本提取身份证信息: {text}")
    
    # 提取身份证号码（18位）
    id_patterns = [
        r'\b\d{17}[\dXx]\b',  # 标准18位身份证
        r'\b\d{15}\b'         # 15位身份证（老版本）
    ]
    
    for pattern in id_patterns:
        id_match = re.search(pattern, text)
        if id_match:
            result['id_number'] = id_match.group()
            current_app.logger.info(f"提取到身份证号: {result['id_number']}")
            break
    
    # 提取姓名（多种模式）
    name_patterns = [
        r'姓\s*名\s*[:：]?\s*([^\s\d]{2,4})',      # "姓名: 张三"
        r'姓名\s*[:：]?\s*([^\s\d]{2,4})',         # "姓名：张三"
        r'名\s*[:：]?\s*([^\s\d]{2,4})',           # "名: 张三"
        r'([^\s\d]{2,4})\s*[男女]',                # "张三 男"
        r'([^\s\d]{2,4})\s*汉',                    # "张三 汉"
        r'([^\s\d]{2,4})\s*\d{4}',                 # "张三 1990"（姓名在出生年份前）
        r'居民身份证.*?([^\s\d]{2,4})\s*[男女]',   # 从"居民身份证"开始查找
        r'中华人民共和国.*?([^\s\d]{2,4})\s*[男女]' # 从"中华人民共和国"开始查找
    ]
    
    for pattern in name_patterns:
        name_match = re.search(pattern, text)
        if name_match:
            potential_name = name_match.group(1)
            # 验证是否为合理的姓名
            if len(potential_name) >= 2 and len(potential_name) <= 4:
                # 排除一些明显不是姓名的词
                excluded_words = ['身份', '居民', '证件', '公民', '姓名', '性别', '民族', '出生', '住址', '签发', '有效期', '中华', '人民', '共和国']
                if potential_name not in excluded_words:
                    result['name'] = potential_name
                    current_app.logger.info(f"提取到姓名: {result['name']}")
                    break
    
    # 提取性别
    if '男' in text and '女' not in text:
        result['gender'] = '男'
    elif '女' in text and '男' not in text:
        result['gender'] = '女'
    
    # 提取民族
    nations = ['汉', '蒙古', '回', '藏', '维吾尔', '苗', '彝', '壮', '布依', '朝鲜', '满', '侗', '瑶', '白', '土家', '哈尼', '哈萨克', '傣', '黎', '傈僳', '佤', '畲', '高山', '拉祜', '水', '东乡', '纳西', '景颇', '柯尔克孜', '土', '达斡尔', '仫佬', '羌', '布朗', '撒拉', '毛南', '仡佬', '锡伯', '阿昌', '普米', '塔吉克', '怒', '乌孜别克', '俄罗斯', '鄂温克', '德昂', '保安', '裕固', '京', '塔塔尔', '独龙', '鄂伦春', '赫哲', '门巴', '珞巴', '基诺']
    for nation in nations:
        if nation in text:
            result['nation'] = nation
            break
    
    current_app.logger.info(f"最终提取结果: 姓名={result['name']}, 身份证号={result['id_number']}")
    return result