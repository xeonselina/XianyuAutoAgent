"""
验货检查清单生成器
根据租赁记录内容动态生成检查项列表
"""
from typing import List, Dict


class ChecklistGenerator:
    """检查清单生成器"""
    
    # 基础检查项（所有租赁都包含）
    BASE_ITEMS = [
        {'name': '手机、镜头无严重磕碰', 'order': 1},
        {'name': '屏幕贴膜或贴纸', 'order': 2}
        {'name': '摄像头各焦段无白色十字', 'order': 3},
        {'name': '镜头镜片清晰，无雾无破裂', 'order': 4},
        {'name': '镜头拆装顺滑', 'order': 5},
        {'name': '充电头和充电线', 'order': 6}
    ]
    
    @classmethod
    def generate_checklist(cls, rental) -> List[Dict[str, any]]:
        """
        根据租赁记录生成检查清单
        
        Args:
            rental: Rental 模型实例
            
        Returns:
            List[Dict]: 检查项列表，每项包含 name 和 order 字段
        """
        checklist = []
        order_counter = 1
        
        # 1. 添加基础检查项
        for item in cls.BASE_ITEMS:
            checklist.append({
                'name': item['name'],
                'order': order_counter
            })
            order_counter += 1
        
        # 2. 如果包含手柄，添加手柄检查项
        if rental.includes_handle:
            checklist.append({
                'name': '手柄',
                'order': order_counter
            })
            order_counter += 1
        
        # 3. 如果包含镜头支架，添加镜头支架检查项
        if rental.includes_lens_mount:
            checklist.append({
                'name': '镜头支架',
                'order': order_counter
            })
            order_counter += 1
        
        # 4. 如果有附件租赁（child_rentals），添加个性化附件检查项
        if rental.child_rentals and rental.child_rentals.count() > 0:
            # 获取所有个性化附件的名称
            accessories = []
            for child_rental in rental.child_rentals:
                if child_rental.device and child_rental.device.name:
                    accessories.append(child_rental.device.name)
            
            if accessories:
                # 将附件名称组合成一个检查项
                checklist.append({
                    'name': '个性化附件：' + '、'.join(accessories),
                    'order': order_counter
                })
                order_counter += 1
        
        # 5. 如果需要代传照片，添加照片传输检查项
        if rental.photo_transfer:
            checklist.append({
                'name': '代传照片',
                'order': order_counter
            })
            order_counter += 1
        
        return checklist
    
    @classmethod
    def get_base_item_count(cls) -> int:
        """获取基础检查项数量"""
        return len(cls.BASE_ITEMS)
    
    @classmethod
    def calculate_expected_count(cls, rental) -> int:
        """
        计算预期的检查项总数
        
        Args:
            rental: Rental 模型实例
            
        Returns:
            int: 预期的检查项总数
        """
        count = cls.get_base_item_count()
        
        if rental.includes_handle:
            count += 1
        
        if rental.includes_lens_mount:
            count += 1
        
        if rental.child_rentals and rental.child_rentals.count() > 0:
            count += 1
        
        if rental.photo_transfer:
            count += 1
        
        return count
