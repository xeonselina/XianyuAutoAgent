"""
腾讯文档API集成工具
用于读取在线表格中的库存数据
"""

import requests
import json
import time
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from loguru import logger
import os


class TencentDocsAPI:
    """腾讯文档API客户端"""
    
    def __init__(self, access_token: str = None):
        self.access_token = access_token or os.getenv("TENCENT_DOCS_ACCESS_TOKEN")
        self.base_url = "https://docs.qq.com/openapi"
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Accept': 'application/json',
            'Content-Type': 'application/json'
        })
        
        if self.access_token:
            self.session.headers.update({
                'Authorization': f'Bearer {self.access_token}'
            })
    
    def get_sheet_data(self, sheet_id: str, sheet_name: str = "Sheet1") -> List[Dict]:
        """
        获取表格数据
        
        Args:
            sheet_id: 表格ID
            sheet_name: 工作表名称
            
        Returns:
            List[Dict]: 表格数据列表
        """
        try:
            # 腾讯文档API调用
            url = f"{self.base_url}/sheets/{sheet_id}/values/{sheet_name}"
            response = self.session.get(url)
            
            if response.status_code == 200:
                data = response.json()
                return self._parse_sheet_data(data)
            else:
                logger.error(f"获取表格数据失败: {response.status_code} - {response.text}")
                return []
                
        except Exception as e:
            logger.error(f"获取表格数据异常: {e}")
            return []
    
    def _parse_sheet_data(self, raw_data: Dict) -> List[Dict]:
        """解析表格原始数据"""
        try:
            # 假设返回的数据结构包含values字段
            if 'values' not in raw_data:
                logger.warning("表格数据格式不符合预期")
                return []
            
            values = raw_data['values']
            if not values or len(values) < 2:  # 至少需要表头和一行数据
                return []
            
            # 第一行是表头
            headers = values[0]
            data_rows = values[1:]
            
            parsed_data = []
            for row in data_rows:
                if len(row) >= len(headers):
                    row_data = {}
                    for i, header in enumerate(headers):
                        if i < len(row):
                            row_data[header] = row[i]
                        else:
                            row_data[header] = ""
                    parsed_data.append(row_data)
            
            return parsed_data
            
        except Exception as e:
            logger.error(f"解析表格数据失败: {e}")
            return []
    
    def update_cell_value(self, sheet_id: str, sheet_name: str, row: int, col: int, value: str) -> bool:
        """
        更新单元格值
        
        Args:
            sheet_id: 表格ID
            row: 行号（从1开始）
            col: 列号（从1开始）
            value: 新值
            
        Returns:
            bool: 是否更新成功
        """
        try:
            url = f"{self.base_url}/sheets/{sheet_id}/values/{sheet_name}!{self._get_cell_ref(row, col)}"
            data = {"value": value}
            
            response = self.session.put(url, json=data)
            
            if response.status_code == 200:
                logger.info(f"更新单元格成功: {sheet_name}!{self._get_cell_ref(row, col)} = {value}")
                return True
            else:
                logger.error(f"更新单元格失败: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"更新单元格异常: {e}")
            return False
    
    def _get_cell_ref(self, row: int, col: int) -> str:
        """将行列号转换为Excel单元格引用格式"""
        col_letter = ""
        while col > 0:
            col, remainder = divmod(col - 1, 26)
            col_letter = chr(65 + remainder) + col_letter
        return f"{col_letter}{row}"


class TencentDocsInventoryManager:
    """基于腾讯文档的库存管理器"""
    
    def __init__(self, sheet_id: str, access_token: str = None):
        self.sheet_id = sheet_id
        self.api = TencentDocsAPI(access_token)
        self.cache = {}
        self.cache_expiry = 300  # 缓存5分钟
        
    def _get_cached_data(self, key: str) -> Any:
        """获取缓存数据"""
        if key in self.cache:
            data, timestamp = self.cache[key]
            if time.time() - timestamp < self.cache_expiry:
                return data
        return None
    
    def _set_cached_data(self, key: str, data: Any):
        """设置缓存数据"""
        self.cache[key] = (data, time.time())
    
    def get_inventory_data(self, force_refresh: bool = False) -> List[Dict]:
        """获取库存数据"""
        cache_key = "inventory_data"
        
        if not force_refresh:
            cached_data = self._get_cached_data(cache_key)
            if cached_data:
                return cached_data
        
        try:
            # 从腾讯文档获取数据
            raw_data = self.api.get_sheet_data(self.sheet_id, "Sheet1")
            
            # 处理数据，转换为标准格式
            processed_data = self._process_raw_data(raw_data)
            
            # 缓存数据
            self._set_cached_data(cache_key, processed_data)
            
            return processed_data
            
        except Exception as e:
            logger.error(f"获取库存数据失败: {e}")
            return []
    
    def _process_raw_data(self, raw_data: List[Dict]) -> List[Dict]:
        """处理原始数据，转换为标准格式"""
        processed_data = []
        
        for row in raw_data:
            try:
                # 根据Excel表格结构处理数据
                device_data = {
                    "device_id": row.get("设备ID", ""),
                    "model": row.get("型号", ""),
                    "status": self._determine_status(row),
                    "ship_date": self._parse_date(row.get("发货时间", "")),
                    "rental_start": self._parse_date(row.get("租赁开始时间", "")),
                    "rental_end": self._parse_date(row.get("租赁结束时间", "")),
                    "expected_return": self._parse_date(row.get("预计收货时间", "")),
                    "customer": row.get("客户", ""),
                    "destination": row.get("目的地", ""),
                    "notes": row.get("备注", ""),
                    "last_updated": datetime.now().isoformat()
                }
                
                # 只处理有效的设备数据
                if device_data["device_id"] and device_data["model"]:
                    processed_data.append(device_data)
                    
            except Exception as e:
                logger.warning(f"处理行数据失败: {row} - {e}")
                continue
        
        return processed_data
    
    def _determine_status(self, row: Dict) -> str:
        """根据表格数据确定设备状态"""
        ship_date = self._parse_date(row.get("发货时间", ""))
        rental_start = self._parse_date(row.get("租赁开始时间", ""))
        rental_end = self._parse_date(row.get("租赁结束时间", ""))
        expected_return = self._parse_date(row.get("预计收货时间", ""))
        
        now = datetime.now()
        
        # 如果发货时间已过但租赁未开始，状态为"运输中"
        if ship_date and ship_date < now and (not rental_start or rental_start > now):
            return "shipping"
        
        # 如果在租赁期间内，状态为"已租出"
        if rental_start and rental_end and rental_start <= now <= rental_end:
            return "rented"
        
        # 如果租赁已结束但未收到，状态为"运输中"
        if rental_end and rental_end < now and (not expected_return or expected_return > now):
            return "returning"
        
        # 如果预计收货时间已过，状态为"可用"
        if expected_return and expected_return < now:
            return "available"
        
        # 默认状态为"可用"
        return "available"
    
    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """解析日期字符串"""
        if not date_str:
            return None
        
        try:
            # 尝试多种日期格式
            date_formats = [
                "%Y-%m-%d",
                "%Y/%m/%d",
                "%Y年%m月%d日",
                "%m/%d/%Y",
                "%d/%m/%Y"
            ]
            
            for fmt in date_formats:
                try:
                    return datetime.strptime(date_str.strip(), fmt)
                except ValueError:
                    continue
            
            # 如果都失败了，尝试解析Excel数字日期
            try:
                excel_date = float(date_str)
                # Excel日期是从1900年1月1日开始的天数
                delta = timedelta(days=excel_date - 2)  # 减去2是因为Excel的日期系统
                base_date = datetime(1900, 1, 1)
                return base_date + delta
            except (ValueError, TypeError):
                pass
            
            logger.warning(f"无法解析日期: {date_str}")
            return None
            
        except Exception as e:
            logger.error(f"解析日期失败: {date_str} - {e}")
            return None
    
    def check_availability(self, start_date: str, end_date: str, model: str = None) -> Dict:
        """检查档期可用性"""
        try:
            start = datetime.fromisoformat(start_date)
            end = datetime.fromisoformat(end_date)
            
            inventory_data = self.get_inventory_data()
            
            available_devices = []
            unavailable_devices = []
            
            for device in inventory_data:
                if model and device["model"] != model:
                    continue
                
                if device["status"] != "available":
                    unavailable_devices.append(device)
                    continue
                
                # 检查是否有档期冲突
                has_conflict = self._check_schedule_conflict(device, start, end)
                
                if not has_conflict:
                    available_devices.append(device)
                else:
                    unavailable_devices.append(device)
            
            return {
                "available_count": len(available_devices),
                "unavailable_count": len(unavailable_devices),
                "available_devices": available_devices,
                "unavailable_devices": unavailable_devices,
                "requested_period": {
                    "start": start_date,
                    "end": end_date,
                    "days": (end - start).days
                }
            }
            
        except Exception as e:
            logger.error(f"检查档期可用性失败: {e}")
            return {"error": str(e)}
    
    def _check_schedule_conflict(self, device: Dict, start: datetime, end: datetime) -> bool:
        """检查档期冲突"""
        # 检查租赁期间是否有重叠
        if device["rental_start"] and device["rental_end"]:
            rental_start = device["rental_start"]
            rental_end = device["rental_end"]
            
            # 检查日期重叠
            if start < rental_end and end > rental_start:
                return True
        
        return False
    
    def get_device_status(self, device_id: str) -> Optional[Dict]:
        """获取指定设备的状态"""
        inventory_data = self.get_inventory_data()
        
        for device in inventory_data:
            if device["device_id"] == device_id:
                return device
        
        return None
    
    def get_inventory_summary(self) -> Dict:
        """获取库存摘要"""
        inventory_data = self.get_inventory_data()
        
        status_counts = {}
        for device in inventory_data:
            status = device["status"]
            status_counts[status] = status_counts.get(status, 0) + 1
        
        return {
            "total": len(inventory_data),
            "status_breakdown": status_counts,
            "last_updated": datetime.now().isoformat()
        }
    
    def search_devices(self, **filters) -> List[Dict]:
        """搜索设备"""
        inventory_data = self.get_inventory_data()
        results = []
        
        for device in inventory_data:
            match = True
            
            for key, value in filters.items():
                if key in device:
                    if isinstance(value, str) and value.lower() not in str(device[key]).lower():
                        match = False
                        break
                    elif device[key] != value:
                        match = False
                        break
            
            if match:
                results.append(device)
        
        return results
    
    def refresh_cache(self):
        """刷新缓存"""
        self.cache.clear()
        logger.info("库存缓存已刷新")


# 使用示例
if __name__ == "__main__":
    # 创建库存管理器（需要提供腾讯文档的表格ID和访问令牌）
    sheet_id = "your_sheet_id_here"
    access_token = "your_access_token_here"
    
    inventory_mgr = TencentDocsInventoryManager(sheet_id, access_token)
    
    # 获取库存数据
    inventory = inventory_mgr.get_inventory_data()
    print(f"获取到 {len(inventory)} 台设备")
    
    # 检查档期
    result = inventory_mgr.check_availability("2024-01-15", "2024-01-17")
    print("档期检查结果:", json.dumps(result, ensure_ascii=False, indent=2))
    
    # 获取库存摘要
    summary = inventory_mgr.get_inventory_summary()
    print("库存摘要:", json.dumps(summary, ensure_ascii=False, indent=2))
