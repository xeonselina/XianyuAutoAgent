"""
租赁附件关联模型

注意：该模型已废弃！
新架构中，附件租赁直接作为独立的Rental记录，通过parent_rental_id关联到主租赁。
请使用 Rental.parent_rental_id 和 Rental.child_rentals 来处理附件关联。

@deprecated 该模型将在下个版本中删除
"""

from app import db
from datetime import datetime


class RentalAccessory(db.Model):
    """租赁附件关联模型"""
    __tablename__ = 'rental_accessories'
    
    # 主键
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='关联ID')
    
    # 关联信息
    rental_id = db.Column(db.Integer, db.ForeignKey('rentals.id'), nullable=False, comment='租赁ID')
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, comment='附件设备ID')
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='更新时间')
    
    # 关系
    rental = db.relationship('Rental', backref='accessories')
    device = db.relationship('Device', backref='rental_accessories')
    
    def __repr__(self):
        return f'<RentalAccessory {self.rental_id}-{self.device_id}>'
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'rental_id': self.rental_id,
            'device_id': self.device_id,
            'device_info': self.device.to_dict() if self.device else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }