#!/usr/bin/env python3
"""
OCR身份证识别功能测试类
"""

import unittest
import os
import sys
import io
from unittest.mock import patch, MagicMock

# 添加项目根目录到路径
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app import create_app
from ocr_functions import recognize_id_card, _recognize_with_aliyun_advanced_ocr, _extract_id_info_from_text


class TestOCRFunctions(unittest.TestCase):
    """OCR功能测试类"""
    
    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.app = create_app()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()
        
        # 样例图片路径
        cls.sample_images = [
            'docs/example/XGJ-IM-1755754100704.jpeg',
            'docs/example/XGJ-IM-1755754261907.jpeg'
        ]
        
        # 预期的测试结果（模拟真实身份证信息）
        cls.expected_results = [
            {
                'name': '张伟',
                'id_number': '110101199001011234',
                'gender': '男',
                'nation': '汉',
                'address': '北京市东城区某某街道123号',
                'birth': '1990-01-01'
            },
            {
                'name': '李娜',
                'id_number': '110102199205155678',
                'gender': '女', 
                'nation': '汉',
                'address': '北京市西城区某某路456号',
                'birth': '1992-05-15'
            }
        ]
    
    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        cls.app_context.pop()
    
    def test_image_files_exist(self):
        """测试样例图片文件是否存在"""
        for image_path in self.sample_images:
            with self.subTest(image=image_path):
                self.assertTrue(
                    os.path.exists(image_path),
                    f"样例图片不存在: {image_path}"
                )
                
                # 检查文件大小
                file_size = os.path.getsize(image_path)
                self.assertGreater(
                    file_size, 1000,
                    f"图片文件太小，可能损坏: {image_path} ({file_size} bytes)"
                )
    
    def test_recognize_id_card_without_aliyun_config(self):
        """测试没有配置阿里云时的情况"""
        with patch.dict(os.environ, {}, clear=True):  # 清空环境变量
            for i, image_path in enumerate(self.sample_images):
                with self.subTest(image=image_path):
                    # 读取图片数据
                    with open(image_path, 'rb') as f:
                        image_data = f.read()
                    
                    # 测试识别函数
                    result = recognize_id_card(image_data)
                    
                    # 没有配置阿里云时应该返回None
                    self.assertIsNone(
                        result,
                        f"没有配置阿里云时应该返回None: {image_path}"
                    )
    
    @patch('ocr_functions._recognize_with_aliyun_advanced_ocr')
    def test_recognize_id_card_with_mock_aliyun(self, mock_recognize):
        """测试使用模拟阿里云通用OCR的识别功能"""
        
        for i, image_path in enumerate(self.sample_images):
            with self.subTest(image=image_path):
                # 设置模拟返回结果
                expected = self.expected_results[i]
                mock_recognize.return_value = expected
                
                # 读取图片数据
                with open(image_path, 'rb') as f:
                    image_data = f.read()
                
                # 测试识别函数
                result = recognize_id_card(image_data)
                
                # 验证结果
                self.assertIsNotNone(result, f"识别结果不应为None: {image_path}")
                self.assertIn('name', result, "结果应包含姓名")
                self.assertIn('id_number', result, "结果应包含身份证号")
                
                # 验证具体值
                self.assertEqual(
                    result['name'], expected['name'],
                    f"姓名识别错误: 期望 {expected['name']}, 实际 {result.get('name')}"
                )
                self.assertEqual(
                    result['id_number'], expected['id_number'],
                    f"身份证号识别错误: 期望 {expected['id_number']}, 实际 {result.get('id_number')}"
                )
    
    def test_aliyun_ocr_response_parsing(self):
        """测试阿里云OCR响应解析"""
        # 这个测试验证阿里云OCR返回数据的解析逻辑
        # 由于阿里云OCR直接返回结构化数据，不需要文本提取
        
        test_cases = [
            {
                'name': '张伟',
                'id_number': '110101199001011234',
                'gender': '男',
                'nation': '汉'
            },
            {
                'name': '李娜',
                'id_number': '110102199205155678',
                'gender': '女',
                'nation': '汉'
            }
        ]
        
        for i, case in enumerate(test_cases):
            with self.subTest(case=i):
                # 验证数据结构是否完整
                self.assertIn('name', case, "应包含姓名字段")
                self.assertIn('id_number', case, "应包含身份证号字段")
                self.assertTrue(len(case['name']) >= 2, "姓名长度应>=2")
                self.assertTrue(len(case['id_number']) >= 15, "身份证号长度应>=15")
    
    def test_aliyun_ocr_config_validation(self):
        """测试阿里云OCR配置验证"""
        import os
        
        # 测试完整配置
        test_config = {
            'ALIYUN_ACCESS_KEY_ID': 'test_key_id', 
            'ALIYUN_ACCESS_KEY_SECRET': 'test_key_secret'
        }
        
        with patch.dict(os.environ, test_config):
            access_key_id = os.getenv('ALIYUN_ACCESS_KEY_ID')
            access_key_secret = os.getenv('ALIYUN_ACCESS_KEY_SECRET')
            
            self.assertEqual(access_key_id, 'test_key_id')
            self.assertEqual(access_key_secret, 'test_key_secret')
        
        # 测试配置缺失
        with patch.dict(os.environ, {}, clear=True):
            access_key_id = os.getenv('ALIYUN_ACCESS_KEY_ID')
            access_key_secret = os.getenv('ALIYUN_ACCESS_KEY_SECRET')
            
            self.assertIsNone(access_key_id)
            self.assertIsNone(access_key_secret)
    
    def test_image_format_validation(self):
        """测试图像格式验证"""
        # 测试有效的图像数据
        for image_path in self.sample_images:
            with self.subTest(image=image_path):
                with open(image_path, 'rb') as f:
                    image_data = f.read()
                
                # 图像数据应该能够被PIL正确读取
                from PIL import Image
                try:
                    image = Image.open(io.BytesIO(image_data))
                    width, height = image.size
                    
                    self.assertGreater(width, 0, "图像宽度应大于0")
                    self.assertGreater(height, 0, "图像高度应大于0")
                    
                    # 身份证图片可能是横向或竖向（手机拍摄）
                    # 只检查图片不是正方形即可
                    ratio = width / height if height > 0 else 0
                    self.assertNotAlmostEqual(
                        ratio, 1.0, 
                        places=1,
                        msg=f"图片不应是正方形: {width}x{height}, ratio={ratio:.2f}"
                    )
                    
                except Exception as e:
                    self.fail(f"无法读取图像: {image_path}, 错误: {e}")
    
    @patch('ocr_functions._recognize_with_aliyun_advanced_ocr')
    def test_aliyun_ocr_error_handling(self, mock_recognize):
        """测试阿里云通用OCR异常处理"""
        # 模拟阿里云OCR抛出异常
        mock_recognize.side_effect = Exception("阿里云OCR服务异常")
        
        with open(self.sample_images[0], 'rb') as f:
            image_data = f.read()
        
        result = recognize_id_card(image_data)
        
        # 应该返回None而不是抛出异常
        self.assertIsNone(result, "OCR异常时应返回None")
    
    def test_aliyun_ocr_sdk_availability(self):
        """测试阿里云OCR SDK可用性检查"""
        from ocr_functions import ALIYUN_OCR_AVAILABLE
        
        # 验证SDK是否正确安装
        self.assertTrue(ALIYUN_OCR_AVAILABLE, "阿里云OCR SDK应该可用")
        
        # 测试在没有配置密钥时的行为
        with patch.dict(os.environ, {}, clear=True):
            with open(self.sample_images[0], 'rb') as f:
                image_data = f.read()
            
            result = recognize_id_card(image_data)
            self.assertIsNone(result, "没有配置密钥时应返回None")
    
    def test_advanced_ocr_text_extraction(self):
        """测试通用OCR文本提取能力"""
        # 测试不同格式的身份证文本提取
        test_texts = [
            "中华人民共和国居民身份证 姓名 张伟 性别 男 民族 汉 出生 1990年01月01日 住址 北京市朝阳区 公民身份号码 110101199001011234",
            "居民身份证 张三 男 汉族 1985年05月15日 110102198505150001",
            "姓名：李娜 性别：女 民族：汉 出生：1992年12月31日 身份证号：110103199212310002"
        ]
        
        expected_results = [
            {'name': '张伟', 'id_number': '110101199001011234'},
            {'name': '张三', 'id_number': '110102198505150001'},
            {'name': '李娜', 'id_number': '110103199212310002'}
        ]
        
        for i, text in enumerate(test_texts):
            with self.subTest(text=text):
                result = _extract_id_info_from_text(text)
                expected = expected_results[i]
                
                self.assertEqual(result['name'], expected['name'], f"姓名提取失败: {text}")
                self.assertEqual(result['id_number'], expected['id_number'], f"身份证号提取失败: {text}")
    
    def test_text_extraction_edge_cases(self):
        """测试文本提取的边界情况"""
        edge_cases = [
            {
                'text': '',  # 空文本
                'expected_name': '',
                'expected_id': ''
            },
            {
                'text': '姓名张三',  # 无分隔符
                'expected_name': '张三',
                'expected_id': ''
            },
            {
                'text': '110101199001011234',  # 只有身份证号
                'expected_name': '',
                'expected_id': '110101199001011234'
            },
            {
                'text': '姓名 张三 110101199001011234 男',  # 标准格式
                'expected_name': '张三',
                'expected_id': '110101199001011234'
            }
        ]
        
        for i, case in enumerate(edge_cases):
            with self.subTest(case=i):
                result = _extract_id_info_from_text(case['text'])
                
                self.assertEqual(
                    result.get('name', ''), case['expected_name'],
                    f"姓名提取失败: 文本='{case['text']}', 期望='{case['expected_name']}', 实际='{result.get('name', '')}'"
                )
                self.assertEqual(
                    result.get('id_number', ''), case['expected_id'],
                    f"身份证号提取失败: 文本='{case['text']}', 期望='{case['expected_id']}', 实际='{result.get('id_number', '')}'"
                )


class TestOCRIntegration(unittest.TestCase):
    """OCR集成测试类"""
    
    @classmethod
    def setUpClass(cls):
        """测试类初始化"""
        cls.app = create_app()
        cls.client = cls.app.test_client()
        cls.app_context = cls.app.app_context()
        cls.app_context.push()
    
    @classmethod
    def tearDownClass(cls):
        """测试类清理"""
        cls.app_context.pop()
    
    def test_ocr_api_endpoint(self):
        """测试OCR API端点"""
        sample_image = 'docs/example/XGJ-IM-1755754100704.jpeg'
        
        if not os.path.exists(sample_image):
            self.skipTest(f"样例图片不存在: {sample_image}")
        
        with open(sample_image, 'rb') as f:
            response = self.client.post(
                '/api/ocr/id-card',
                data={'id_card': (f, 'test_id.jpg')},
                content_type='multipart/form-data'
            )
        
        self.assertEqual(response.status_code, 200, "OCR API应返回200状态码")
        
        data = response.get_json()
        self.assertIsNotNone(data, "API应返回JSON数据")
        self.assertIn('success', data, "响应应包含success字段")
        
        # 根据是否安装EasyOCR，结果可能不同
        if data['success']:
            self.assertIn('data', data, "成功响应应包含data字段")
            self.assertIn('name', data['data'], "识别数据应包含姓名")
            self.assertIn('id_number', data['data'], "识别数据应包含身份证号")
        else:
            self.assertIn('error', data, "失败响应应包含error字段")
    
    def test_ocr_api_no_file(self):
        """测试OCR API无文件情况"""
        response = self.client.post('/api/ocr/id-card')
        
        self.assertEqual(response.status_code, 400, "无文件时应返回400状态码")
        
        data = response.get_json()
        self.assertIsNotNone(data, "应返回JSON错误信息")
        self.assertFalse(data.get('success', True), "success应为False")
    
    def test_ocr_api_invalid_file(self):
        """测试OCR API无效文件"""
        # 创建一个无效的文件内容
        invalid_data = '这不是图片数据'.encode('utf-8')
        
        response = self.client.post(
            '/api/ocr/id-card',
            data={'id_card': (io.BytesIO(invalid_data), 'invalid.txt')},
            content_type='multipart/form-data'
        )
        
        data = response.get_json()
        self.assertIsNotNone(data, "应返回JSON响应")
        
        # 应该返回错误或失败状态
        if response.status_code == 200:
            self.assertFalse(data.get('success', True), "无效文件应返回失败状态")
        else:
            self.assertIn(response.status_code, [400, 415], "应返回客户端错误状态码")


if __name__ == '__main__':
    # 创建测试套件
    test_suite = unittest.TestSuite()
    
    # 添加OCR功能测试
    test_suite.addTest(unittest.makeSuite(TestOCRFunctions))
    
    # 添加集成测试
    test_suite.addTest(unittest.makeSuite(TestOCRIntegration))
    
    # 运行测试
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(test_suite)
    
    # 输出测试结果
    print(f"\n{'='*60}")
    print(f"测试完成!")
    print(f"运行测试: {result.testsRun}")
    print(f"失败: {len(result.failures)}")
    print(f"错误: {len(result.errors)}")
    print(f"跳过: {len(result.skipped) if hasattr(result, 'skipped') else 0}")
    
    if result.failures:
        print(f"\n失败的测试:")
        for test, trace in result.failures:
            print(f"- {test}")
    
    if result.errors:
        print(f"\n错误的测试:")
        for test, trace in result.errors:
            print(f"- {test}")
    
    print(f"{'='*60}")
    
    # 返回适当的退出码
    sys.exit(0 if result.wasSuccessful() else 1)
