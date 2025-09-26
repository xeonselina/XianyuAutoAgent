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
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
    
   
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
