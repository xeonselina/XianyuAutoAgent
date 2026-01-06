"""
验货记录模型
"""
from datetime import datetime
from app import db


class InspectionRecord(db.Model):
    """验货记录表"""
    __tablename__ = 'inspection_record'

    id = db.Column(db.Integer, primary_key=True)
    rental_id = db.Column(db.Integer, db.ForeignKey('rentals.id'), nullable=False, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)
    status = db.Column(
        db.String(20), 
        nullable=False, 
        default='abnormal',
        index=True,
        comment='验货状态: normal=验机正常, abnormal=验机异常'
    )
    inspector_user_id = db.Column(db.Integer, nullable=True, comment='验货人员ID（预留）')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    # 关系
    rental = db.relationship('Rental', backref=db.backref('inspection_records', lazy='dynamic'))
    device = db.relationship('Device', backref=db.backref('inspection_records', lazy='dynamic'))
    check_items = db.relationship(
        'InspectionCheckItem',
        backref='inspection_record',
        lazy='dynamic',
        cascade='all, delete-orphan'
    )

    def __repr__(self):
        return f'<InspectionRecord {self.id} rental_id={self.rental_id} status={self.status}>'

    def to_dict(self):
        """转换为字典格式"""
        return {
            'id': self.id,
            'rental_id': self.rental_id,
            'device_id': self.device_id,
            'status': self.status,
            'inspector_user_id': self.inspector_user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'rental': self.rental.to_dict() if self.rental else None,
            'device': self.device.to_dict() if self.device else None,
            'check_items': [item.to_dict() for item in self.check_items.all()]
        }
