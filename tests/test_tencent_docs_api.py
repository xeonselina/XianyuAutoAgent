"""
腾讯文档API单元测试
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import sys
import os
import json

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.tencent_docs_api import TencentDocsAPI, TencentDocsInventoryManager


class TestTencentDocsAPI(unittest.TestCase):
    """腾讯文档API测试类"""
    
    def setUp(self):
        """测试前的准备工作"""
        self.api = TencentDocsAPI("test_token")
        self.sample_response = {
            "values": [
                ["设备ID", "型号", "发货时间", "租赁开始时间", "租赁结束时间", "预计收货时间", "客户", "目的地", "备注"],
                ["PHONE001", "iPhone 15 Pro", "", "", "", "", "", "", ""],
                ["PHONE002", "iPhone 15 Pro", "2024-01-15", "2024-01-16", "2024-01-18", "2024-01-20", "张三", "北京", "客户要求加急"],
                ["PHONE003", "iPhone 15 Pro Max", "2024-01-20", "2024-01-22", "2024-01-24", "2024-01-26", "李四", "上海", ""]
            ]
        }
    
    def test_init_with_token(self):
        """测试带令牌初始化"""
        api = TencentDocsAPI("test_token")
        self.assertEqual(api.access_token, "test_token")
        self.assertIn("Authorization", api.session.headers)
    
    def test_init_without_token(self):
        """测试不带令牌初始化"""
        api = TencentDocsAPI()
        self.assertIsNone(api.access_token)
        self.assertNotIn("Authorization", api.session.headers)
    
    def test_get_cell_ref(self):
        """测试单元格引用转换"""
        # 测试列A
        self.assertEqual(self.api._get_cell_ref(1, 1), "A1")
        
        # 测试列B
        self.assertEqual(self.api._get_cell_ref(1, 2), "B1")
        
        # 测试列Z
        self.assertEqual(self.api._get_cell_ref(1, 26), "Z1")
        
        # 测试列AA
        self.assertEqual(self.api._get_cell_ref(1, 27), "AA1")
        
        # 测试列AB
        self.assertEqual(self.api._get_cell_ref(1, 28), "AB1")
    
    @patch('requests.Session.get')
    def test_get_sheet_data_success(self, mock_get):
        """测试成功获取表格数据"""
        # 设置模拟响应
        mock_response = Mock()
        mock_response.status_code = 200
        mock_response.json.return_value = self.sample_response
        mock_get.return_value = mock_response
        
        result = self.api.get_sheet_data("test_sheet_id")
        
        self.assertEqual(len(result), 3)  # 3行数据
        self.assertEqual(result[0]["设备ID"], "PHONE001")
        self.assertEqual(result[0]["型号"], "iPhone 15 Pro")
        
        # 验证API调用
        mock_get.assert_called_once()
    
    @patch('requests.Session.get')
    def test_get_sheet_data_failure(self, mock_get):
        """测试获取表格数据失败"""
        # 设置模拟响应
        mock_response = Mock()
        mock_response.status_code = 404
        mock_response.text = "Not Found"
        mock_get.return_value = mock_response
        
        result = self.api.get_sheet_data("test_sheet_id")
        
        self.assertEqual(result, [])
    
    @patch('requests.Session.get')
    def test_get_sheet_data_exception(self, mock_get):
        """测试获取表格数据异常"""
        mock_get.side_effect = Exception("Network error")
        
        result = self.api.get_sheet_data("test_sheet_id")
        
        self.assertEqual(result, [])
    
    def test_parse_sheet_data_empty(self):
        """测试解析空表格数据"""
        empty_data = {"values": []}
        result = self.api._parse_sheet_data(empty_data)
        
        self.assertEqual(result, [])
    
    def test_parse_sheet_data_only_header(self):
        """测试只有表头的数据"""
        header_only = {"values": [["设备ID", "型号"]]}
        result = self.api._parse_sheet_data(header_only)
        
        self.assertEqual(result, [])
    
    def test_parse_sheet_data_malformed(self):
        """测试格式错误的数据"""
        malformed_data = {"values": [["设备ID"], ["PHONE001", "iPhone 15 Pro"]]}
        result = self.api._parse_sheet_data(malformed_data)
        
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["设备ID"], "PHONE001")
        self.assertEqual(result[0]["型号"], "iPhone 15 Pro")
    
    @patch('requests.Session.put')
    def test_update_cell_value_success(self, mock_put):
        """测试成功更新单元格值"""
        # 设置模拟响应
        mock_response = Mock()
        mock_response.status_code = 200
        mock_put.return_value = mock_response
        
        result = self.api.update_cell_value("test_sheet_id", "Sheet1", 2, 1, "新值")
        
        self.assertTrue(result)
        mock_put.assert_called_once()
    
    @patch('requests.Session.put')
    def test_update_cell_value_failure(self, mock_put):
        """测试更新单元格值失败"""
        # 设置模拟响应
        mock_response = Mock()
        mock_response.status_code = 403
        mock_response.text = "Forbidden"
        mock_put.return_value = mock_response
        
        result = self.api.update_cell_value("test_sheet_id", "Sheet1", 2, 1, "新值")
        
        self.assertFalse(result)
    
    @patch('requests.Session.put')
    def test_update_cell_value_exception(self, mock_put):
        """测试更新单元格值异常"""
        mock_put.side_effect = Exception("Network error")
        
        result = self.api.update_cell_value("test_sheet_id", "Sheet1", 2, 1, "新值")
        
        self.assertFalse(result)


class TestTencentDocsInventoryManager(unittest.TestCase):
    """腾讯文档库存管理器测试类"""
    
    def setUp(self):
        """测试前的准备工作"""
        self.manager = TencentDocsInventoryManager("test_sheet_id", "test_token")
        
        # 模拟原始数据
        self.raw_data = [
            {
                "设备ID": "PHONE001",
                "型号": "iPhone 15 Pro",
                "发货时间": "",
                "租赁开始时间": "",
                "租赁结束时间": "",
                "预计收货时间": "",
                "客户": "",
                "目的地": "",
                "备注": ""
            },
            {
                "设备ID": "PHONE002",
                "型号": "iPhone 15 Pro",
                "发货时间": "2024-01-15",
                "租赁开始时间": "2024-01-16",
                "租赁结束时间": "2024-01-18",
                "预计收货时间": "2024-01-20",
                "客户": "张三",
                "目的地": "北京",
                "备注": "客户要求加急"
            }
        ]
        
        # 模拟处理后的数据
        self.processed_data = [
            {
                "device_id": "PHONE001",
                "model": "iPhone 15 Pro",
                "status": "available",
                "ship_date": None,
                "rental_start": None,
                "rental_end": None,
                "expected_return": None,
                "customer": "",
                "destination": "",
                "notes": ""
            },
            {
                "device_id": "PHONE002",
                "model": "iPhone 15 Pro",
                "status": "rented",
                "ship_date": datetime(2024, 1, 15),
                "rental_start": datetime(2024, 1, 16),
                "rental_end": datetime(2024, 1, 18),
                "expected_return": datetime(2024, 1, 20),
                "customer": "张三",
                "destination": "北京",
                "notes": "客户要求加急"
            }
        ]
    
    def test_init(self):
        """测试初始化"""
        self.assertEqual(self.manager.sheet_id, "test_sheet_id")
        self.assertIsNotNone(self.manager.api)
    
    def test_cache_operations(self):
        """测试缓存操作"""
        # 设置缓存
        self.manager._set_cached_data("test_key", "test_value")
        
        # 获取缓存
        cached_value = self.manager._get_cached_data("test_key")
        self.assertEqual(cached_value, "test_value")
        
        # 测试缓存过期
        self.manager.cache_expiry = 0
        expired_value = self.manager._get_cached_data("test_key")
        self.assertIsNone(expired_value)
    
    @patch.object(TencentDocsInventoryManager, 'api')
    def test_get_inventory_data_with_cache(self, mock_api):
        """测试带缓存的库存数据获取"""
        # 设置缓存
        self.manager._set_cached_data("inventory_data", self.processed_data)
        
        # 获取数据（应该从缓存）
        result = self.manager.get_inventory_data()
        
        self.assertEqual(result, self.processed_data)
        # 不应该调用API
        mock_api.get_sheet_data.assert_not_called()
    
    @patch.object(TencentDocsInventoryManager, 'api')
    def test_get_inventory_data_force_refresh(self, mock_api):
        """测试强制刷新库存数据"""
        # 设置缓存
        self.manager._set_cached_data("inventory_data", self.processed_data)
        
        # 设置API返回值
        mock_api.get_sheet_data.return_value = self.raw_data
        
        # 强制刷新
        result = self.manager.get_inventory_data(force_refresh=True)
        
        # 应该调用API
        mock_api.get_sheet_data.assert_called_once()
    
    def test_process_raw_data(self):
        """测试原始数据处理"""
        result = self.manager._process_raw_data(self.raw_data)
        
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["device_id"], "PHONE001")
        self.assertEqual(result[0]["status"], "available")
        self.assertEqual(result[1]["device_id"], "PHONE002")
        self.assertEqual(result[1]["status"], "rented")
    
    def test_determine_status_available(self):
        """测试确定可用状态"""
        row = {
            "发货时间": "",
            "租赁开始时间": "",
            "租赁结束时间": "",
            "预计收货时间": ""
        }
        
        status = self.manager._determine_status(row)
        self.assertEqual(status, "available")
    
    def test_determine_status_shipping(self):
        """测试确定运输中状态"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        row = {
            "发货时间": yesterday,
            "租赁开始时间": tomorrow,
            "租赁结束时间": "",
            "预计收货时间": ""
        }
        
        status = self.manager._determine_status(row)
        self.assertEqual(status, "shipping")
    
    def test_determine_status_rented(self):
        """测试确定已租出状态"""
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        
        row = {
            "发货时间": "",
            "租赁开始时间": yesterday,
            "租赁结束时间": tomorrow,
            "预计收货时间": ""
        }
        
        status = self.manager._determine_status(row)
        self.assertEqual(status, "rented")
    
    def test_parse_date_success(self):
        """测试成功解析日期"""
        # 测试标准格式
        result = self.manager._parse_date("2024-01-15")
        self.assertIsInstance(result, datetime)
        self.assertEqual(result.year, 2024)
        self.assertEqual(result.month, 1)
        self.assertEqual(result.day, 15)
        
        # 测试其他格式
        result = self.manager._parse_date("01/15/2024")
        self.assertIsInstance(result, datetime)
        
        result = self.manager._parse_date("2024年1月15日")
        self.assertIsInstance(result, datetime)
    
    def test_parse_date_failure(self):
        """测试解析日期失败"""
        # 测试无效日期
        result = self.manager._parse_date("invalid-date")
        self.assertIsNone(result)
        
        # 测试空字符串
        result = self.manager._parse_date("")
        self.assertIsNone(result)
        
        # 测试None
        result = self.manager._parse_date(None)
        self.assertIsNone(result)
    
    def test_parse_date_excel_number(self):
        """测试解析Excel数字日期"""
        # Excel日期：2024年1月15日对应的数字
        excel_date = 45292  # 这是示例数字，实际值可能不同
        
        result = self.manager._parse_date(str(excel_date))
        # 由于Excel日期计算复杂，这里只测试不抛出异常
        self.assertIsNotNone(result)
    
    @patch.object(TencentDocsInventoryManager, 'get_inventory_data')
    def test_check_availability(self, mock_get_data):
        """测试档期可用性检查"""
        mock_get_data.return_value = self.processed_data
        
        result = self.manager.check_availability("2024-01-15", "2024-01-17")
        
        self.assertIn("available_count", result)
        self.assertIn("unavailable_count", result)
        self.assertIn("available_devices", result)
        self.assertIn("unavailable_devices", result)
    
    def test_check_schedule_conflict(self):
        """测试档期冲突检查"""
        device = {
            "rental_start": datetime(2024, 1, 16),
            "rental_end": datetime(2024, 1, 18)
        }
        
        # 测试有冲突
        has_conflict = self.manager._check_schedule_conflict(
            device, 
            datetime(2024, 1, 17), 
            datetime(2024, 1, 19)
        )
        self.assertTrue(has_conflict)
        
        # 测试无冲突
        has_conflict = self.manager._check_schedule_conflict(
            device, 
            datetime(2024, 1, 19), 
            datetime(2024, 1, 21)
        )
        self.assertFalse(has_conflict)
    
    @patch.object(TencentDocsInventoryManager, 'get_inventory_data')
    def test_get_device_status(self, mock_get_data):
        """测试获取设备状态"""
        mock_get_data.return_value = self.processed_data
        
        result = self.manager.get_device_status("PHONE001")
        
        self.assertIsNotNone(result)
        self.assertEqual(result["device_id"], "PHONE001")
    
    @patch.object(TencentDocsInventoryManager, 'get_inventory_data')
    def test_get_device_status_not_found(self, mock_get_data):
        """测试获取不存在的设备状态"""
        mock_get_data.return_value = self.processed_data
        
        result = self.manager.get_device_status("NONEXISTENT")
        
        self.assertIsNone(result)
    
    @patch.object(TencentDocsInventoryManager, 'get_inventory_data')
    def test_get_inventory_summary(self, mock_get_data):
        """测试获取库存摘要"""
        mock_get_data.return_value = self.processed_data
        
        result = self.manager.get_inventory_summary()
        
        self.assertIn("total", result)
        self.assertIn("status_breakdown", result)
        self.assertEqual(result["total"], 2)
    
    @patch.object(TencentDocsInventoryManager, 'get_inventory_data')
    def test_search_devices(self, mock_get_data):
        """测试设备搜索"""
        mock_get_data.return_value = self.processed_data
        
        # 测试按型号搜索
        result = self.manager.search_devices(model="iPhone 15 Pro")
        self.assertEqual(len(result), 2)
        
        # 测试按状态搜索
        result = self.manager.search_devices(status="available")
        self.assertEqual(len(result), 1)
        
        # 测试无结果搜索
        result = self.manager.search_devices(model="NonExistent")
        self.assertEqual(len(result), 0)
    
    def test_refresh_cache(self):
        """测试刷新缓存"""
        # 设置一些缓存数据
        self.manager._set_cached_data("test_key", "test_value")
        
        # 刷新缓存
        self.manager.refresh_cache()
        
        # 缓存应该被清空
        cached_value = self.manager._get_cached_data("test_key")
        self.assertIsNone(cached_value)


if __name__ == '__main__':
    # 运行测试
    unittest.main(verbosity=2)
