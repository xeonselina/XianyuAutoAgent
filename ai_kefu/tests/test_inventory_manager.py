"""
库存管理器单元测试
"""

import unittest
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timedelta
import sys
import os

# 添加项目根目录到Python路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from utils.inventory_manager import InventoryManager


class TestInventoryManager(unittest.TestCase):
    """库存管理器测试类"""
    
    def setUp(self):
        """测试前的准备工作"""
        # 模拟腾讯文档API模块
        self.mock_tencent_docs = Mock()
        self.mock_tencent_docs_api = Mock()
        
        # 模拟TencentDocsInventoryManager类
        self.mock_manager_class = Mock()
        self.mock_manager_instance = Mock()
        self.mock_manager_class.return_value = self.mock_manager_instance
        
        # 设置模拟数据
        self.sample_inventory_data = [
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
                "ship_date": "2024-01-15",
                "rental_start": "2024-01-16",
                "rental_end": "2024-01-18",
                "expected_return": "2024-01-20",
                "customer": "张三",
                "destination": "北京",
                "notes": "客户要求加急"
            },
            {
                "device_id": "PHONE003",
                "model": "iPhone 15 Pro Max",
                "status": "shipping",
                "ship_date": "2024-01-20",
                "rental_start": "2024-01-22",
                "rental_end": "2024-01-24",
                "expected_return": "2024-01-26",
                "customer": "李四",
                "destination": "上海",
                "notes": ""
            }
        ]
        
        # 设置模拟方法返回值
        self.mock_manager_instance.get_inventory_data.return_value = self.sample_inventory_data
        self.mock_manager_instance.get_inventory_summary.return_value = {
            "total": 3,
            "status_breakdown": {
                "available": 1,
                "rented": 1,
                "shipping": 1
            },
            "last_updated": datetime.now().isoformat()
        }
        
        # 模拟档期检查结果
        self.mock_manager_instance.check_availability.return_value = {
            "available_count": 1,
            "unavailable_count": 2,
            "available_devices": [self.sample_inventory_data[0]],
            "unavailable_devices": self.sample_inventory_data[1:],
            "requested_period": {
                "start": "2024-01-15",
                "end": "2024-01-17",
                "days": 2
            }
        }
        
        # 模拟设备状态查询
        self.mock_manager_instance.get_device_status.return_value = self.sample_inventory_data[0]
        
        # 模拟设备搜索
        self.mock_manager_instance.search_devices.return_value = [self.sample_inventory_data[0]]
    
    @patch('utils.inventory_manager.TencentDocsInventoryManager')
    def test_init_success(self, mock_tencent_docs_class):
        """测试成功初始化"""
        mock_tencent_docs_class.return_value = self.mock_manager_instance
        
        # 测试正常初始化
        manager = InventoryManager("test_sheet_id", "test_token")
        
        self.assertIsNotNone(manager.tencent_mgr)
        mock_tencent_docs_class.assert_called_once_with("test_sheet_id", "test_token")
    
    def test_init_missing_sheet_id(self):
        """测试缺少表格ID的初始化"""
        with self.assertRaises(ValueError) as context:
            InventoryManager("", "test_token")
        
        self.assertIn("必须提供腾讯文档表格ID", str(context.exception))
    
    def test_init_missing_sheet_id_none(self):
        """测试表格ID为None的初始化"""
        with self.assertRaises(ValueError) as context:
            InventoryManager(None, "test_token")
        
        self.assertIn("必须提供腾讯文档表格ID", str(context.exception))
    
    @patch('utils.inventory_manager.TencentDocsInventoryManager', None)
    def test_init_missing_module(self):
        """测试缺少腾讯文档API模块的初始化"""
        with self.assertRaises(ImportError) as context:
            InventoryManager("test_sheet_id", "test_token")
        
        self.assertIn("腾讯文档API模块未安装", str(context.exception))
    
    @patch('utils.inventory_manager.TencentDocsInventoryManager')
    def test_get_inventory_data(self, mock_tencent_docs_class):
        """测试获取库存数据"""
        mock_tencent_docs_class.return_value = self.mock_manager_instance
        
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.get_inventory_data()
        
        self.assertEqual(result, self.sample_inventory_data)
        self.mock_manager_instance.get_inventory_data.assert_called_once_with(False)
    
    @patch('utils.inventory_manager.TencentDocsInventoryManager')
    def test_get_inventory_data_force_refresh(self, mock_tencent_docs_class):
        """测试强制刷新获取库存数据"""
        mock_tencent_docs_class.return_value = self.mock_manager_instance
        
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.get_inventory_data(force_refresh=True)
        
        self.assertEqual(result, self.sample_inventory_data)
        self.mock_manager_instance.get_inventory_data.assert_called_once_with(True)
    
    @patch('utils.inventory_manager.TencentDocsInventoryManager')
    def test_check_availability(self, mock_tencent_docs_class):
        """测试档期可用性检查"""
        mock_tencent_docs_class.return_value = self.mock_manager_instance
        
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.check_availability("2024-01-15", "2024-01-17")
        
        self.assertEqual(result["available_count"], 1)
        self.assertEqual(result["unavailable_count"], 2)
        self.mock_manager_instance.check_availability.assert_called_once_with("2024-01-15", "2024-01-17", None)
    
    @patch('utils.inventory_manager.TencentDocsInventoryManager')
    def test_check_availability_with_model(self, mock_tencent_docs_class):
        """测试带型号的档期可用性检查"""
        mock_tencent_docs_class.return_value = self.mock_manager_instance
        
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.check_availability("2024-01-15", "2024-01-17", "iPhone 15 Pro")
        
        self.mock_manager_instance.check_availability.assert_called_once_with("2024-01-15", "2024-01-17", "iPhone 15 Pro")
    
    @patch('utils.inventory_manager.TencentDocsInventoryManager')
    def test_get_device_status(self, mock_tencent_docs_class):
        """测试获取设备状态"""
        mock_tencent_docs_class.return_value = self.mock_manager_instance
        
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.get_device_status("PHONE001")
        
        self.assertEqual(result, self.sample_inventory_data[0])
        self.mock_manager_instance.get_device_status.assert_called_once_with("PHONE001")
    
    @patch('utils.inventory_manager.TencentDocsInventoryManager')
    def test_get_inventory_summary(self, mock_tencent_docs_class):
        """测试获取库存摘要"""
        mock_tencent_docs_class.return_value = self.mock_manager_instance
        
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.get_inventory_summary()
        
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["status_breakdown"]["available"], 1)
        self.mock_manager_instance.get_inventory_summary.assert_called_once()
    
    @patch('utils.inventory_manager.TencentDocsInventoryManager')
    def test_search_devices(self, mock_tencent_docs_class):
        """测试设备搜索"""
        mock_tencent_docs_class.return_value = self.mock_manager_instance
        
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.search_devices(model="iPhone 15 Pro")
        
        self.assertEqual(len(result), 1)
        self.mock_manager_instance.search_devices.assert_called_once_with(model="iPhone 15 Pro")
    
    @patch('utils.inventory_manager.TencentDocsInventoryManager')
    def test_refresh_cache(self, mock_tencent_docs_class):
        """测试刷新缓存"""
        mock_tencent_docs_class.return_value = self.mock_manager_instance
        
        manager = InventoryManager("test_sheet_id", "test_token")
        manager.refresh_cache()
        
        self.mock_manager_instance.refresh_cache.assert_called_once()
    
    def test_get_shipping_time_known_city(self):
        """测试获取已知城市的快递时效"""
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.get_shipping_time("北京")
        
        expected = {"standard": 1, "express": 1, "safe_buffer": 1}
        self.assertEqual(result, expected)
    
    def test_get_shipping_time_unknown_city(self):
        """测试获取未知城市的快递时效"""
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.get_shipping_time("未知城市")
        
        expected = {"standard": 3, "express": 2, "safe_buffer": 2}
        self.assertEqual(result, expected)
    
    def test_get_shipping_time_with_suffix(self):
        """测试带后缀的城市名称处理"""
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.get_shipping_time("北京市")
        
        expected = {"standard": 1, "express": 1, "safe_buffer": 1}
        self.assertEqual(result, expected)
    
    def test_calculate_schedule_success(self):
        """测试成功计算档期安排"""
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.calculate_schedule("2024-01-15", "2024-01-17", "北京")
        
        self.assertNotIn("error", result)
        self.assertEqual(result["receive_date"], "2024-01-15")
        self.assertEqual(result["return_date"], "2024-01-17")
        self.assertEqual(result["rental_days"], 2)
        self.assertIn("shipping_info", result)
    
    def test_calculate_schedule_invalid_date(self):
        """测试无效日期计算档期安排"""
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.calculate_schedule("invalid-date", "2024-01-17", "北京")
        
        self.assertIn("error", result)
    
    def test_calculate_schedule_negative_days(self):
        """测试负天数计算档期安排"""
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.calculate_schedule("2024-01-17", "2024-01-15", "北京")
        
        self.assertNotIn("error", result)
        self.assertEqual(result["rental_days"], 0)
    
    @patch('utils.inventory_manager.pd')
    @patch('utils.inventory_manager.TencentDocsInventoryManager')
    def test_export_to_excel_success(self, mock_tencent_docs_class, mock_pd):
        """测试成功导出Excel"""
        mock_tencent_docs_class.return_value = self.mock_manager_instance
        mock_df = Mock()
        mock_pd.DataFrame.return_value = mock_df
        
        manager = InventoryManager("test_sheet_id", "test_token")
        result = manager.export_to_excel("test.xlsx")
        
        self.assertTrue(result)
        mock_pd.DataFrame.assert_called_once()
        mock_df.to_excel.assert_called_once_with("test.xlsx", index=False)
    
    @patch('utils.inventory_manager.TencentDocsInventoryManager')
    def test_export_to_excel_no_pandas(self, mock_tencent_docs_class):
        """测试没有pandas时导出Excel"""
        mock_tencent_docs_class.return_value = self.mock_manager_instance
        
        # 模拟pandas未安装
        with patch.dict('sys.modules', {'pandas': None}):
            manager = InventoryManager("test_sheet_id", "test_token")
            result = manager.export_to_excel("test.xlsx")
            
            self.assertFalse(result)


class TestInventoryManagerIntegration(unittest.TestCase):
    """库存管理器集成测试类"""
    
    @patch('utils.inventory_manager.TencentDocsInventoryManager')
    def test_full_workflow(self, mock_tencent_docs_class):
        """测试完整工作流程"""
        # 设置模拟实例
        mock_instance = Mock()
        mock_tencent_docs_class.return_value = mock_instance
        
        # 模拟数据
        mock_inventory = [
            {"device_id": "PHONE001", "model": "iPhone 15 Pro", "status": "available"},
            {"device_id": "PHONE002", "model": "iPhone 15 Pro", "status": "rented"}
        ]
        
        mock_instance.get_inventory_data.return_value = mock_inventory
        mock_instance.get_inventory_summary.return_value = {"total": 2, "available": 1}
        mock_instance.check_availability.return_value = {
            "available_count": 1,
            "unavailable_count": 1,
            "available_devices": [mock_inventory[0]],
            "unavailable_devices": [mock_inventory[1]]
        }
        
        # 创建管理器
        manager = InventoryManager("test_sheet_id", "test_token")
        
        # 测试完整流程
        inventory = manager.get_inventory_data()
        self.assertEqual(len(inventory), 2)
        
        summary = manager.get_inventory_summary()
        self.assertEqual(summary["total"], 2)
        
        availability = manager.check_availability("2024-01-15", "2024-01-17")
        self.assertEqual(availability["available_count"], 1)
        
        shipping_info = manager.get_shipping_time("北京")
        self.assertIn("standard", shipping_info)
        
        schedule = manager.calculate_schedule("2024-01-15", "2024-01-17", "北京")
        self.assertNotIn("error", schedule)


if __name__ == '__main__':
    # 运行测试
    unittest.main(verbosity=2)
