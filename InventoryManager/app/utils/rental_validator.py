"""
租赁数据验证器
"""

from datetime import datetime, date
from typing import Dict, Any, Tuple
from app.models.device import Device


class RentalValidator:
    """租赁数据验证器"""
    
    @staticmethod
    def validate_create_data(data: Dict[str, Any]) -> Tuple[bool, str]:
        """验证租赁创建数据
        
        Args:
            data: 租赁数据字典，包含：
                - device_id: 设备ID
                - start_date: 开始日期
                - end_date: 结束日期
                - customer_name: 客户姓名
                - includes_handle: 是否包含手柄（可选）
                - includes_lens_mount: 是否包含镜头支架（可选）
                - accessory_ids: 库存附件ID列表（可选）
        
        Returns:
            Tuple[bool, str]: (是否有效, 错误消息)
        """
        # 1. 检查必填字段
        required_fields = ['device_id', 'start_date', 'end_date', 'customer_name']
        for field in required_fields:
            if field not in data or not data[field]:
                return False, f"缺少必填字段: {field}"
        
        # 2. 验证设备是否存在
        device = Device.query.get(data['device_id'])
        if not device:
            return False, f"设备不存在: {data['device_id']}"
        
        # 3. 验证日期格式和逻辑
        try:
            if isinstance(data['start_date'], str):
                start_date = datetime.fromisoformat(data['start_date']).date()
            else:
                start_date = data['start_date']
            
            if isinstance(data['end_date'], str):
                end_date = datetime.fromisoformat(data['end_date']).date()
            else:
                end_date = data['end_date']
            
            if start_date > end_date:
                return False, "开始日期不能晚于结束日期"
            
            # 检查是否是过去的日期（警告但不阻止）
            # if start_date < date.today():
            #     return False, "开始日期不能早于今天"
            
        except (ValueError, AttributeError) as e:
            return False, f"日期格式无效: {str(e)}"
        
        # 4. 验证配套附件标记（应该是boolean类型）
        if 'includes_handle' in data and not isinstance(data['includes_handle'], bool):
            return False, "includes_handle 必须是布尔值"
        
        if 'includes_lens_mount' in data and not isinstance(data['includes_lens_mount'], bool):
            return False, "includes_lens_mount 必须是布尔值"
        
        # 5. 验证库存附件ID（如果提供）
        if 'accessory_ids' in data and data['accessory_ids']:
            if not isinstance(data['accessory_ids'], list):
                return False, "accessory_ids 必须是列表"
            
            for accessory_id in data['accessory_ids']:
                accessory = Device.query.get(accessory_id)
                if not accessory:
                    return False, f"附件设备不存在: {accessory_id}"
                
                if not accessory.is_accessory:
                    return False, f"设备 {accessory_id} 不是附件"
        
        # 6. 验证客户信息
        if len(data['customer_name'].strip()) < 2:
            return False, "客户姓名至少需要2个字符"
        
        return True, ""
    
    @staticmethod
    def validate_update_data(rental_id: int, data: Dict[str, Any]) -> Tuple[bool, str]:
        """验证租赁更新数据
        
        Args:
            rental_id: 租赁记录ID
            data: 更新数据字典
        
        Returns:
            Tuple[bool, str]: (是否有效, 错误消息)
        """
        from app.models.rental import Rental
        
        # 1. 检查租赁是否存在
        rental = Rental.query.get(rental_id)
        if not rental:
            return False, f"租赁记录不存在: {rental_id}"
        
        # 2. 检查是否可以修改（已完成或已取消的订单不能修改）
        if rental.status in ['completed', 'cancelled']:
            return False, f"订单状态为 {rental.status}，不能修改"
        
        # 3. 如果更新日期，验证日期逻辑
        if 'start_date' in data or 'end_date' in data:
            try:
                start_date = data.get('start_date', rental.start_date)
                end_date = data.get('end_date', rental.end_date)
                
                if isinstance(start_date, str):
                    start_date = datetime.fromisoformat(start_date).date()
                if isinstance(end_date, str):
                    end_date = datetime.fromisoformat(end_date).date()
                
                if start_date > end_date:
                    return False, "开始日期不能晚于结束日期"
                
            except (ValueError, AttributeError) as e:
                return False, f"日期格式无效: {str(e)}"
        
        # 4. 如果更新设备，验证设备是否存在
        if 'device_id' in data:
            device = Device.query.get(data['device_id'])
            if not device:
                return False, f"设备不存在: {data['device_id']}"
        
        # 5. 验证配套附件标记
        if 'includes_handle' in data and not isinstance(data['includes_handle'], bool):
            return False, "includes_handle 必须是布尔值"
        
        if 'includes_lens_mount' in data and not isinstance(data['includes_lens_mount'], bool):
            return False, "includes_lens_mount 必须是布尔值"
        
        # 6. 验证库存附件ID
        if 'accessory_ids' in data and data['accessory_ids']:
            if not isinstance(data['accessory_ids'], list):
                return False, "accessory_ids 必须是列表"
            
            for accessory_id in data['accessory_ids']:
                accessory = Device.query.get(accessory_id)
                if not accessory:
                    return False, f"附件设备不存在: {accessory_id}"
                
                if not accessory.is_accessory:
                    return False, f"设备 {accessory_id} 不是附件"
        
        return True, ""
    
    @staticmethod
    def validate_accessory_compatibility(device_id: int, accessory_ids: list) -> Tuple[bool, str]:
        """验证附件与主设备的兼容性（预留接口）
        
        Args:
            device_id: 主设备ID
            accessory_ids: 附件ID列表
        
        Returns:
            Tuple[bool, str]: (是否兼容, 错误消息)
        """
        # 当前简化实现：所有附件都兼容
        # 未来可以添加设备模型匹配逻辑
        return True, ""
