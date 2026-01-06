"""
验货服务
处理验货记录的业务逻辑
"""
from datetime import datetime, date
from typing import Optional, List, Dict
from app import db
from app.models.rental import Rental
from app.models.device import Device
from app.models.inspection_record import InspectionRecord
from app.models.inspection_check_item import InspectionCheckItem
from app.services.checklist_generator import ChecklistGenerator


class InspectionService:
    """验货服务类"""
    
    @staticmethod
    def find_latest_rental_by_device_id(device_id: int) -> Optional[Rental]:
        """
        根据设备ID查询最近的租赁记录（在今天之前）
        
        Args:
            device_id: 设备ID
            
        Returns:
            Rental: 最近的租赁记录，如果没有则返回 None
        """
        today = date.today()
        
        # 查询该设备在今天之前的最近租赁记录
        # 按开始日期倒序排列，取第一条
        rental = Rental.query.filter(
            Rental.device_id == device_id,
            Rental.start_date < today
        ).order_by(Rental.start_date.desc()).first()
        
        return rental
    
    @staticmethod
    def create_inspection_record(
        rental_id: int,
        device_id: int,
        check_items: List[Dict[str, any]]
    ) -> InspectionRecord:
        """
        创建验货记录
        
        Args:
            rental_id: 租赁记录ID
            device_id: 设备ID
            check_items: 检查项列表，每项包含 name, is_checked, order
            
        Returns:
            InspectionRecord: 创建的验货记录
            
        Raises:
            ValueError: 如果租赁记录或设备不存在
        """
        # 验证租赁记录存在
        rental = Rental.query.get(rental_id)
        if not rental:
            raise ValueError(f"Rental {rental_id} not found")
        
        # 验证设备存在
        device = Device.query.get(device_id)
        if not device:
            raise ValueError(f"Device {device_id} not found")
        
        # 计算验货状态：所有项都勾选则为 normal，否则为 abnormal
        status = 'normal' if all(item.get('is_checked', False) for item in check_items) else 'abnormal'
        
        # 创建验货记录
        inspection_record = InspectionRecord(
            rental_id=rental_id,
            device_id=device_id,
            status=status,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
        db.session.add(inspection_record)
        db.session.flush()  # 获取 inspection_record.id
        
        # 创建检查项
        for item_data in check_items:
            check_item = InspectionCheckItem(
                inspection_record_id=inspection_record.id,
                item_name=item_data['name'],
                is_checked=item_data.get('is_checked', False),
                item_order=item_data.get('order', 0)
            )
            db.session.add(check_item)
        
        db.session.commit()
        
        return inspection_record
    
    @staticmethod
    def get_inspection_record(inspection_id: int) -> Optional[InspectionRecord]:
        """
        获取验货记录详情
        
        Args:
            inspection_id: 验货记录ID
            
        Returns:
            InspectionRecord: 验货记录，如果不存在则返回 None
        """
        return InspectionRecord.query.get(inspection_id)
    
    @staticmethod
    def update_inspection_record(
        inspection_id: int,
        check_items: List[Dict[str, any]]
    ) -> InspectionRecord:
        """
        更新验货记录
        
        Args:
            inspection_id: 验货记录ID
            check_items: 更新后的检查项列表，每项包含 id, is_checked
            
        Returns:
            InspectionRecord: 更新后的验货记录
            
        Raises:
            ValueError: 如果验货记录不存在
        """
        inspection_record = InspectionRecord.query.get(inspection_id)
        if not inspection_record:
            raise ValueError(f"Inspection record {inspection_id} not found")
        
        # 更新检查项
        for item_data in check_items:
            check_item = InspectionCheckItem.query.get(item_data['id'])
            if check_item and check_item.inspection_record_id == inspection_id:
                check_item.is_checked = item_data.get('is_checked', False)
        
        # 重新计算状态
        all_items = inspection_record.check_items.all()
        status = 'normal' if all(item.is_checked for item in all_items) else 'abnormal'
        inspection_record.status = status
        inspection_record.updated_at = datetime.utcnow()
        
        db.session.commit()
        
        return inspection_record
    
    @staticmethod
    def get_inspection_records(
        device_name: Optional[str] = None,
        status: Optional[str] = None,
        page: int = 1,
        per_page: int = 20
    ) -> Dict:
        """
        获取验货记录列表（分页、筛选）
        
        Args:
            device_name: 设备名称筛选（模糊匹配）
            status: 状态筛选 (normal/abnormal)
            page: 页码
            per_page: 每页数量
            
        Returns:
            Dict: 包含 records 和 pagination 信息
        """
        query = InspectionRecord.query
        
        # 设备名称筛选
        if device_name:
            query = query.join(Device).filter(Device.name.like(f'%{device_name}%'))
        
        # 状态筛选
        if status:
            query = query.filter(InspectionRecord.status == status)
        
        # 按创建时间倒序排列
        query = query.order_by(InspectionRecord.created_at.desc())
        
        # 分页
        pagination = query.paginate(page=page, per_page=per_page, error_out=False)
        
        return {
            'records': [record.to_dict() for record in pagination.items],
            'pagination': {
                'page': pagination.page,
                'per_page': pagination.per_page,
                'total': pagination.total,
                'pages': pagination.pages,
                'has_prev': pagination.has_prev,
                'has_next': pagination.has_next
            }
        }
    
    @staticmethod
    def generate_checklist_for_rental(rental_id: int) -> List[Dict[str, any]]:
        """
        为指定租赁记录生成检查清单
        
        Args:
            rental_id: 租赁记录ID
            
        Returns:
            List[Dict]: 检查清单
            
        Raises:
            ValueError: 如果租赁记录不存在
        """
        rental = Rental.query.get(rental_id)
        if not rental:
            raise ValueError(f"Rental {rental_id} not found")
        
        return ChecklistGenerator.generate_checklist(rental)
