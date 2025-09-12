"""
租赁记录数据模型
"""

from app import db
from datetime import datetime, date
import uuid


class Rental(db.Model):
    """租赁记录模型"""
    __tablename__ = 'rentals'
    
    # 主键
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    
    # 关联信息
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, comment='设备ID')
    
    # 时间信息
    start_date = db.Column(db.Date, nullable=False, comment='开始日期')
    end_date = db.Column(db.Date, nullable=False, comment='结束日期')
    ship_out_time = db.Column(db.DateTime, nullable=True, comment='寄出时间')
    ship_in_time = db.Column(db.DateTime, nullable=True, comment='收回时间')
    
    # 客户信息
    customer_name = db.Column(db.String(100), nullable=False, comment='客户姓名')
    customer_phone = db.Column(db.String(20), comment='客户电话')
    destination = db.Column(db.String(100), comment='目的地')

    # 物流信息
    ship_out_tracking_no = db.Column(db.String(50), comment='寄出快递单号')
    ship_in_tracking_no = db.Column(db.String(50), comment='寄回快递单号')
    
    # 状态信息
    status = db.Column(
        db.Enum('pending', 'active', 'completed', 'cancelled', 'overdue', name='rental_status'),
        default='pending',
        comment='租赁状态'
    )
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='更新时间')
    
    # 租赁关联（主租赁ID，用于关联主设备和附件设备的租赁记录）
    parent_rental_id = db.Column(db.Integer, db.ForeignKey('rentals.id'), nullable=True, comment='父租赁记录ID（用于关联主设备和附件）')
    
    # 关系
    audit_logs = db.relationship('AuditLog', backref='rental', lazy='dynamic')
    # 子租赁记录（附件租赁）
    child_rentals = db.relationship('Rental', backref=db.backref('parent_rental', remote_side='Rental.id'), lazy='dynamic')
    
    def __repr__(self):
        return f'<Rental {self.id}: {self.device_id} ({self.start_date} - {self.end_date})>'
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'device_id': self.device_id,
            'start_date': self.start_date.isoformat(),
            'end_date': self.end_date.isoformat(),
            'ship_out_time': self.ship_out_time.isoformat() if self.ship_out_time else None,
            'ship_in_time': self.ship_in_time.isoformat() if self.ship_in_time else None,
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'destination': self.destination,
            'ship_out_tracking_no': self.ship_out_tracking_no,
            'ship_in_tracking_no': self.ship_in_tracking_no,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'duration_days': self.get_duration_days(),
            'is_overdue': self.is_overdue(),
            'device_info': self.device.to_dict() if self.device else None,
            'parent_rental_id': self.parent_rental_id,
            'child_rentals': [rental.to_dict() for rental in self.child_rentals] if self.child_rentals else []
        }
    
    def get_duration_days(self):
        """获取租赁天数"""
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return 0
    
    def is_overdue(self):
        """检查是否逾期"""
        if self.status == 'active' and self.end_date:
            return date.today() > self.end_date
        return False
    
    def is_active(self):
        """检查是否处于活动状态"""
        if self.status != 'active':
            return False
        
        today = date.today()
        return self.start_date <= today <= self.end_date
    
    def can_cancel(self):
        """检查是否可以取消"""
        return self.status in ['pending', 'active'] and not self.is_overdue()
    
    def can_extend(self):
        """检查是否可以延期"""
        return self.status == 'active' and not self.is_overdue()
    
    def approve(self):
        """审批租赁申请"""
        if self.status == 'pending':
            self.status = 'active'
            return True
        return False
    
    def complete(self):
        """完成租赁"""
        if self.status == 'active':
            self.status = 'completed'
            return True
        return False
    
    def cancel(self):
        """取消租赁"""
        if self.can_cancel():
            self.status = 'cancelled'
            return True
        return False
    
    def extend(self, new_end_date):
        """延期租赁"""
        if self.can_extend() and new_end_date > self.end_date:
            self.end_date = new_end_date
            return True
        return False
    
    def is_main_rental(self):
        """检查是否为主租赁记录"""
        return self.parent_rental_id is None
    
    def is_accessory_rental(self):
        """检查是否为附件租赁记录"""
        return self.parent_rental_id is not None
    
    def get_main_rental(self):
        """获取主租赁记录"""
        if self.is_main_rental():
            return self
        return self.parent_rental
    
    def get_all_related_rentals(self):
        """获取所有关联的租赁记录（包括主租赁和附件租赁）"""
        main_rental = self.get_main_rental()
        if main_rental:
            return [main_rental] + list(main_rental.child_rentals)
        return [self]
    
    @classmethod
    def get_active_rentals(cls, date_range=None, include_accessories=False):
        """获取活动租赁记录
        
        Args:
            date_range: 时间范围
            include_accessories: 是否包括附件租赁记录（默认只返回主租赁）
        """
        if include_accessories:
            query = cls.query.filter(cls.status == 'active')
        else:
            # 只返回主租赁记录（用于甘特图显示）
            query = cls.query.filter(
                db.and_(
                    cls.status == 'active',
                    cls.parent_rental_id.is_(None)
                )
            )
        
        if date_range:
            start_date, end_date = date_range
            query = query.filter(
                db.or_(
                    db.and_(
                        cls.start_date <= start_date,
                        cls.end_date >= start_date
                    ),
                    db.and_(
                        cls.start_date <= end_date,
                        cls.end_date >= end_date
                    ),
                    db.and_(
                        cls.start_date >= start_date,
                        cls.end_date <= end_date
                    )
                )
            )
        
        return query.all()
    
    @classmethod
    def get_overdue_rentals(cls):
        """获取逾期租赁记录"""
        today = date.today()
        return cls.query.filter(
            db.and_(
                cls.status == 'active',
                cls.end_date < today
            )
        ).all()
    
    @classmethod
    def get_rentals_by_device(cls, device_id, limit=20):
        """获取指定设备的租赁记录"""
        return cls.query.filter(
            cls.device_id == device_id
        ).order_by(cls.created_at.desc()).limit(limit).all()
    
    @classmethod
    def get_rentals_by_customer(cls, customer_name, limit=20):
        """获取指定客户的租赁记录"""
        return cls.query.filter(
            cls.customer_name == customer_name
        ).order_by(cls.created_at.desc()).limit(limit).all()
    
    @classmethod
    def get_rental_statistics(cls, start_date=None, end_date=None):
        """获取租赁统计信息"""
        query = cls.query
        
        if start_date and end_date:
            query = query.filter(
                db.and_(
                    cls.start_date >= start_date,
                    cls.end_date <= end_date
                )
            )
        
        total_rentals = query.count()
        active_rentals = query.filter(cls.status == 'active').count()
        completed_rentals = query.filter(cls.status == 'completed').count()
        cancelled_rentals = query.filter(cls.status == 'cancelled').count()
        
        return {
            'total_rentals': total_rentals,
            'active_rentals': active_rentals,
            'completed_rentals': completed_rentals,
            'cancelled_rentals': cancelled_rentals,
            'period': {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None
            }
        }
    

