"""
库存管理工具类
用于管理手机库存状态和档期查询
仅支持腾讯文档在线表格集成
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from loguru import logger

# 导入腾讯文档API
try:
    from .tencent_docs_api import TencentDocsInventoryManager
except ImportError:
    TencentDocsInventoryManager = None


class InventoryManager:
    """库存管理器 - 仅支持腾讯文档数据源"""
    
    def __init__(self, sheet_id: str, access_token: str = None):
        """
        初始化库存管理器
        
        Args:
            sheet_id: 腾讯文档表格ID
            access_token: 访问令牌
        """
        if not sheet_id:
            raise ValueError("必须提供腾讯文档表格ID")
        
        if TencentDocsInventoryManager is None:
            raise ImportError("腾讯文档API模块未安装")
        
        self.tencent_mgr = TencentDocsInventoryManager(sheet_id, access_token)
        logger.info("库存管理器已连接到腾讯文档系统")
    
    def get_inventory_data(self, force_refresh: bool = False) -> List[Dict]:
        """获取库存数据"""
        return self.tencent_mgr.get_inventory_data(force_refresh)
    
    def check_availability(self, start_date: str, end_date: str, model: str = None) -> Dict:
        """检查档期可用性"""
        return self.tencent_mgr.check_availability(start_date, end_date, model)
    
    def get_device_status(self, device_id: str) -> Optional[Dict]:
        """获取指定设备的状态"""
        return self.tencent_mgr.get_device_status(device_id)
    
    def get_inventory_summary(self) -> Dict:
        """获取库存摘要"""
        return self.tencent_mgr.get_inventory_summary()
    
    def search_devices(self, **filters) -> List[Dict]:
        """搜索设备"""
        return self.tencent_mgr.search_devices(**filters)
    
    def refresh_cache(self):
        """刷新缓存"""
        self.tencent_mgr.refresh_cache()
    
    def get_shipping_time(self, destination: str) -> Dict:
        """获取快递时效信息"""
        # 标准快递时效表（深圳出发）
        shipping_times = {
            "北京": {"standard": 1, "express": 1, "safe_buffer": 1},
            "上海": {"standard": 1, "express": 1, "safe_buffer": 1},
            "广州": {"standard": 1, "express": 1, "safe_buffer": 1},
            "深圳": {"standard": 0, "express": 0, "safe_buffer": 0},
            "杭州": {"standard": 1, "express": 1, "safe_buffer": 1},
            "南京": {"standard": 1, "express": 1, "safe_buffer": 1},
            "武汉": {"standard": 2, "express": 1, "safe_buffer": 1},
            "成都": {"standard": 2, "express": 1, "safe_buffer": 1},
            "重庆": {"standard": 2, "express": 1, "safe_buffer": 1},
            "西安": {"standard": 2, "express": 1, "safe_buffer": 1},
            "青岛": {"standard": 2, "express": 1, "safe_buffer": 1},
            "大连": {"standard": 2, "express": 1, "safe_buffer": 1},
            "厦门": {"standard": 1, "express": 1, "safe_buffer": 1},
            "苏州": {"standard": 1, "express": 1, "safe_buffer": 1},
            "天津": {"standard": 1, "express": 1, "safe_buffer": 1}
        }
        
        # 获取城市信息（去掉"市"字）
        city = destination.replace("市", "").replace("省", "")
        
        if city in shipping_times:
            return shipping_times[city]
        else:
            # 默认时效（偏远地区）
            return {"standard": 3, "express": 2, "safe_buffer": 2}
    
    def calculate_schedule(self, desired_date: str, return_date: str, destination: str) -> Dict:
        """计算档期安排"""
        try:
            desired = datetime.fromisoformat(desired_date)
            return_dt = datetime.fromisoformat(return_date)
            
            # 获取快递时效
            shipping_info = self.get_shipping_time(destination)
            
            # 计算发货时间
            ship_date = desired - timedelta(days=shipping_info["standard"] + shipping_info["safe_buffer"])
            
            # 计算收货时间
            receive_date = desired
            
            # 计算归还时间
            actual_return_date = return_dt + timedelta(days=shipping_info["standard"] + shipping_info["safe_buffer"])
            
            # 计算实际租赁天数
            rental_days = (return_dt - desired).days
            if rental_days < 0:
                rental_days = 0
            
            return {
                "ship_date": ship_date.strftime("%Y-%m-%d"),
                "receive_date": receive_date.strftime("%Y-%m-%d"),
                "return_date": return_dt.strftime("%Y-%m-%d"),
                "actual_return_date": actual_return_date.strftime("%Y-%m-%d"),
                "rental_days": rental_days,
                "shipping_info": shipping_info,
                "total_days": (actual_return_date - ship_date).days
            }
            
        except Exception as e:
            logger.error(f"计算档期安排失败: {e}")
            return {"error": str(e)}
    
    def export_to_excel(self, output_file: str = "data/inventory_export.xlsx"):
        """导出库存到Excel（可选功能）"""
        try:
            import pandas as pd
            
            # 准备数据
            inventory_data = self.get_inventory_data()
            data = []
            
            for device in inventory_data:
                data.append({
                    "设备ID": device.get("device_id", ""),
                    "型号": device.get("model", ""),
                    "状态": device.get("status", ""),
                    "发货时间": device.get("ship_date", ""),
                    "租赁开始时间": device.get("rental_start", ""),
                    "租赁结束时间": device.get("rental_end", ""),
                    "预计收货时间": device.get("expected_return", ""),
                    "客户": device.get("customer", ""),
                    "目的地": device.get("destination", ""),
                    "备注": device.get("notes", "")
                })
            
            df = pd.DataFrame(data)
            df.to_excel(output_file, index=False)
            logger.info(f"库存数据已导出到: {output_file}")
            return True
            
        except ImportError:
            logger.warning("pandas未安装，无法导出Excel")
            return False
        except Exception as e:
            logger.error(f"导出Excel失败: {e}")
            return False


# 使用示例
if __name__ == "__main__":
    # 创建库存管理器（需要提供腾讯文档的表格ID和访问令牌）
    sheet_id = "your_sheet_id_here"
    access_token = "your_access_token_here"
    
    try:
        inventory_mgr = InventoryManager(sheet_id, access_token)
        
        # 获取库存数据
        inventory = inventory_mgr.get_inventory_data()
        print(f"获取到 {len(inventory)} 台设备")
        
        # 检查档期
        result = inventory_mgr.check_availability("2024-01-15", "2024-01-17")
        print("档期检查结果:", json.dumps(result, ensure_ascii=False, indent=2))
        
        # 获取库存摘要
        summary = inventory_mgr.get_inventory_summary()
        print("库存摘要:", json.dumps(summary, ensure_ascii=False, indent=2))
        
    except Exception as e:
        print(f"初始化失败: {e}")
