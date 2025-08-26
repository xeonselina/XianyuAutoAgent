"""
库存系统配置文件
"""

import os
from typing import Dict, Any


class InventoryConfig:
    """库存系统配置类"""
    
    def __init__(self):
        self.load_config()
    
    def load_config(self):
        """加载配置"""
        # 数据源配置
        self.data_source = os.getenv("INVENTORY_DATA_SOURCE", "local")
        
        # 腾讯文档配置
        self.tencent_docs = {
            "sheet_id": os.getenv("TENCENT_DOCS_SHEET_ID", ""),
            "access_token": os.getenv("TENCENT_DOCS_ACCESS_TOKEN", ""),
            "base_url": os.getenv("TENCENT_DOCS_BASE_URL", "https://docs.qq.com/openapi"),
            "timeout": int(os.getenv("TENCENT_DOCS_TIMEOUT", "30"))
        }
        
        # 本地文件配置
        self.local = {
            "inventory_file": os.getenv("LOCAL_INVENTORY_FILE", "data/inventory.json"),
            "backup_dir": os.getenv("LOCAL_BACKUP_DIR", "data/backup"),
            "auto_backup": os.getenv("LOCAL_AUTO_BACKUP", "true").lower() == "true"
        }
        
        # 缓存配置
        self.cache = {
            "enabled": os.getenv("INVENTORY_CACHE_ENABLED", "true").lower() == "true",
            "expiry": int(os.getenv("INVENTORY_CACHE_EXPIRY", "300")),  # 5分钟
            "max_size": int(os.getenv("INVENTORY_CACHE_MAX_SIZE", "100"))
        }
        
        # 快递时效配置
        self.shipping = {
            "base_city": "深圳",
            "default_standard": 2,
            "default_express": 1,
            "safe_buffer": 1,
            "cities": self._load_shipping_cities()
        }
        
        # 档期计算配置
        self.schedule = {
            "min_advance_days": int(os.getenv("SCHEDULE_MIN_ADVANCE_DAYS", "2")),
            "max_rental_days": int(os.getenv("SCHEDULE_MAX_RENTAL_DAYS", "30")),
            "allow_same_day": os.getenv("SCHEDULE_ALLOW_SAME_DAY", "false").lower() == "true"
        }
    
    def _load_shipping_cities(self) -> Dict[str, Dict[str, int]]:
        """加载城市快递时效配置"""
        return {
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
    
    def get_shipping_time(self, destination: str) -> Dict[str, int]:
        """获取指定城市的快递时效"""
        # 清理城市名称
        city = destination.replace("市", "").replace("省", "").strip()
        
        if city in self.shipping["cities"]:
            return self.shipping["cities"][city]
        else:
            # 返回默认时效
            return {
                "standard": self.shipping["default_standard"],
                "express": self.shipping["default_express"],
                "safe_buffer": self.shipping["safe_buffer"]
            }
    
    def validate_config(self) -> Dict[str, Any]:
        """验证配置有效性"""
        errors = []
        warnings = []
        
        # 检查数据源配置
        if self.data_source == "tencent_docs":
            if not self.tencent_docs["sheet_id"]:
                errors.append("腾讯文档模式需要设置TENCENT_DOCS_SHEET_ID")
            if not self.tencent_docs["access_token"]:
                errors.append("腾讯文档模式需要设置TENCENT_DOCS_ACCESS_TOKEN")
        
        # 检查本地配置
        if self.data_source == "local":
            if not os.path.exists(self.local["inventory_file"]):
                warnings.append(f"本地库存文件不存在: {self.local['inventory_file']}")
        
        # 检查缓存配置
        if self.cache["expiry"] < 60:
            warnings.append("缓存过期时间过短，建议至少60秒")
        
        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
    
    def get_config_summary(self) -> str:
        """获取配置摘要"""
        validation = self.validate_config()
        
        summary = f"""
库存系统配置摘要：
==================
数据源: {self.data_source}
缓存: {'启用' if self.cache['enabled'] else '禁用'} (过期时间: {self.cache['expiry']}秒)
档期最小提前天数: {self.schedule['min_advance_days']}天
档期最大租赁天数: {self.schedule['max_rental_days']}天
        """
        
        if self.data_source == "tencent_docs":
            summary += f"""
腾讯文档配置:
  表格ID: {self.tencent_docs['sheet_id'] or '未设置'}
  访问令牌: {'已设置' if self.tencent_docs['access_token'] else '未设置'}
            """
        
        if validation["errors"]:
            summary += f"\n配置错误:\n" + "\n".join(f"  - {error}" for error in validation["errors"])
        
        if validation["warnings"]:
            summary += f"\n配置警告:\n" + "\n".join(f"  - {warning}" for warning in validation["warnings"])
        
        return summary


# 全局配置实例
inventory_config = InventoryConfig()


def get_inventory_config() -> InventoryConfig:
    """获取库存配置实例"""
    return inventory_config


# 使用示例
if __name__ == "__main__":
    config = get_inventory_config()
    print(config.get_config_summary())
    
    # 测试快递时效
    print(f"\n北京快递时效: {config.get_shipping_time('北京')}")
    print(f"未知城市快递时效: {config.get_shipping_time('未知城市')}")
