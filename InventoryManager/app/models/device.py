"""
设备数据模型
"""

from app import db
from app.models.rental import Rental
from datetime import datetime


class Device(db.Model):
    """设备模型"""
    __tablename__ = 'devices'
    
    # 主键
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='设备ID')
    
    # 基本信息
    name = db.Column(db.String(100), nullable=False, comment='设备名称')
    serial_number = db.Column(db.String(100), unique=True, comment='设备序列号')
    model = db.Column(db.String(50), nullable=False, default='x200u', comment='设备型号')
    model_id = db.Column(db.Integer, db.ForeignKey('device_models.id'), nullable=True, comment='设备型号ID')
    is_accessory = db.Column(db.Boolean, default=False, comment='是否为附件')
    
    # 状态信息
    status = db.Column(
        db.Enum('online', 'offline', name='device_status'),
        default='online',
        comment='设备状态'
    )
    
    # 生命周期管理字段
    lifecycle_status = db.Column(
        db.Enum('active', 'sold', 'decommissioned', 'damaged', 'retired', name='device_lifecycle_status'),
        default='active',
        nullable=False,
        comment='设备生命周期状态'
    )
    lifecycle_reason = db.Column(
        db.String(255),
        nullable=True,
        comment='生命周期变更原因'
    )
    lifecycle_date = db.Column(
        db.DateTime,
        nullable=True,
        comment='生命周期状态变更日期'
    )
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='更新时间')
    
    # 关系
    rentals = db.relationship('Rental', backref='device', lazy='dynamic', cascade='all, delete-orphan')
    audit_logs = db.relationship('AuditLog', backref='device', lazy='dynamic')
    
    def __repr__(self):
        return f'<Device {self.name} ({self.id})>'
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'serial_number': self.serial_number,
            'model': self.model,
            'model_id': self.model_id,
            'device_model': self.device_model.to_dict() if self.device_model else None,
            'is_accessory': self.is_accessory,
            'status': self.status,
            'lifecycle_status': self.lifecycle_status,
            'lifecycle_reason': self.lifecycle_reason,
            'lifecycle_date': self.lifecycle_date.isoformat() if self.lifecycle_date else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
    
    # ==================== Lifecycle Management Methods ====================
    
    def is_in_service(self):
        """
        检查设备是否在服务中（可用于新租赁）
        
        Returns:
            bool: True if device is active and online
        """
        return self.lifecycle_status == 'active' and self.status == 'online'
    
    def is_excluded_from_statistics(self):
        """
        检查设备是否应从统计中排除
        
        不包括以下状态的设备：
        - sold（已销售）
        - decommissioned（已停用）
        - damaged（已损坏）
        - retired（已退役）
        
        Returns:
            bool: True if device should be excluded from statistics
        """
        excluded_statuses = ['sold', 'decommissioned', 'damaged', 'retired']
        return self.lifecycle_status in excluded_statuses
    
    def can_create_new_rental(self):
        """
        检查是否可以为此设备创建新租赁
        
        Returns:
            bool: True if device is in service (active + online)
        """
        return self.is_in_service()
    
    def mark_as_sold(self, reason=None):
        """
        标记设备为已销售
        
        Args:
            reason (str, optional): 销售原因说明
            
        Returns:
            bool: True if status was changed successfully
        """
        if self.lifecycle_status != 'sold':
            self.lifecycle_status = 'sold'
            self.lifecycle_reason = reason or '设备已销售'
            self.lifecycle_date = datetime.utcnow()
            return True
        return False
    
    def mark_as_decommissioned(self, reason=None):
        """
        标记设备为已停用
        
        Args:
            reason (str, optional): 停用原因说明
            
        Returns:
            bool: True if status was changed successfully
        """
        if self.lifecycle_status != 'decommissioned':
            self.lifecycle_status = 'decommissioned'
            self.lifecycle_reason = reason or '设备已停用'
            self.lifecycle_date = datetime.utcnow()
            return True
        return False
    
    def mark_as_damaged(self, reason=None):
        """
        标记设备为已损坏
        
        Args:
            reason (str, optional): 损坏原因说明
            
        Returns:
            bool: True if status was changed successfully
        """
        if self.lifecycle_status != 'damaged':
            self.lifecycle_status = 'damaged'
            self.lifecycle_reason = reason or '设备已损坏'
            self.lifecycle_date = datetime.utcnow()
            return True
        return False
    
    def mark_as_retired(self, reason=None):
        """
        标记设备为已退役
        
        Args:
            reason (str, optional): 退役原因说明
            
        Returns:
            bool: True if status was changed successfully
        """
        if self.lifecycle_status != 'retired':
            self.lifecycle_status = 'retired'
            self.lifecycle_reason = reason or '设备已退役'
            self.lifecycle_date = datetime.utcnow()
            return True
        return False
    
    def restore_to_active(self, reason=None):
        """
        恢复设备为活动状态
        
        Args:
            reason (str, optional): 恢复原因说明
            
        Returns:
            bool: True if status was changed successfully
        """
        if self.lifecycle_status != 'active':
            self.lifecycle_status = 'active'
            self.lifecycle_reason = reason or '设备已恢复为活动状态'
            self.lifecycle_date = datetime.utcnow()
            return True
        return False
    
    def set_lifecycle_status(self, new_status, reason=None):
        """
        设置设备的生命周期状态
        
        Args:
            new_status (str): 新的生命周期状态 (active, sold, decommissioned, damaged, retired)
            reason (str, optional): 状态变更原因说明
            
        Returns:
            tuple: (success: bool, message: str)
        """
        valid_statuses = ['active', 'sold', 'decommissioned', 'damaged', 'retired']
        
        if new_status not in valid_statuses:
            return False, f'无效的生命周期状态。有效值: {", ".join(valid_statuses)}'
        
        old_status = self.lifecycle_status
        
        if new_status == old_status:
            return False, f'设备已处于 {new_status} 状态'
        
        self.lifecycle_status = new_status
        self.lifecycle_reason = reason or f'从 {old_status} 变更为 {new_status}'
        self.lifecycle_date = datetime.utcnow()
        
        return True, f'成功将设备状态从 {old_status} 变更为 {new_status}'
    
    # ==================== Rental History Methods ====================
   
    def get_current_rental(self):
        """获取当前租赁记录"""
        today = datetime.now().date()
        return self.rentals.filter(
            db.and_(
                Rental.start_date <= today,
                Rental.end_date >= today,
                Rental.status == 'shipped'
            )
        ).first()
    
    def get_rental_history(self, limit=10):
        """获取租赁历史"""
        return self.rentals.order_by(Rental.created_at.desc()).limit(limit).all()
    
    
    @classmethod
    def get_device_count_by_status(cls):
        """按状态统计设备数量"""
        return db.session.query(
            cls.status,
            db.func.count(cls.id).label('count')
        ).group_by(cls.status).all()
    
    @classmethod
    def get_device_count_by_lifecycle_status(cls):
        """按生命周期状态统计设备数量"""
        return db.session.query(
            cls.lifecycle_status,
            db.func.count(cls.id).label('count')
        ).group_by(cls.lifecycle_status).all()
    
    @classmethod
    def get_active_devices(cls):
        """获取所有活动中的设备（在统计中计算）"""
        return cls.query.filter(
            cls.lifecycle_status == 'active'
        ).all()
    
    @classmethod
    def get_excluded_devices(cls):
        """获取所有应从统计中排除的设备"""
        excluded_statuses = ['sold', 'decommissioned', 'damaged', 'retired']
        return cls.query.filter(
            cls.lifecycle_status.in_(excluded_statuses)
        ).all()
