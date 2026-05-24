"""
设备型号业务逻辑服务层
"""

from flask import current_app
from app.models.device_model import DeviceModel


class DeviceModelService:
    """设备型号服务类"""

    @staticmethod
    def get_active_models_with_accessories() -> list:
        """获取所有激活的设备型号及其附件
        
        Returns:
            list: 包含设备型号信息和关联附件的列表
        """
        try:
            # 只获取主设备型号（不包括附件）
            models = DeviceModel.get_active_models(include_accessories=False)
            result = []

            for model in models:
                model_data = model.to_dict(include_accessories=True)
                result.append(model_data)

            return result

        except Exception as e:
            current_app.logger.error(f"获取设备型号失败: {e}")
            raise

    @staticmethod
    def get_accessories_for_model(model_id: int) -> list:
        """获取指定型号的附件
        
        Args:
            model_id: 设备型号ID
        
        Returns:
            list: 该型号的附件列表
        """
        try:
            # 使用 DeviceModel 的类方法来获取附件
            accessories = DeviceModel.get_accessories_for_model(model_id)
            result = [acc.to_dict(include_accessories=False) for acc in accessories]
            return result

        except Exception as e:
            current_app.logger.error(f"获取设备附件失败: {e}")
            raise
