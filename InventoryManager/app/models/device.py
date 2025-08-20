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
    
    # 状态信息
    status = db.Column(
        db.Enum('idle', 'pending_ship', 'renting', 'pending_return', 'returned', 'offline', name='device_status'),
        default='idle',
        comment='设备状态'
    )
    
    # 物理信息
    location = db.Column(db.String(100), comment='设备位置')
    
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
            'status': self.status,
            'location': self.location,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }
    
    def _check_ship_time_conflict(self, ship_out_time, ship_in_time):
        """检查寄出和收回时间冲突的通用方法（包含向后兼容）"""
        if ship_out_time and ship_in_time:
            # 检查是否有寄出和收回时间冲突的租赁记录
            conflicting_rental = self.rentals.filter(
                db.and_(
                    db.or_(
                        # 情况1：现有租赁有物流时间，使用寄出收回时间判断
                        db.and_(
                            Rental.ship_out_time.isnot(None),
                            Rental.ship_in_time.isnot(None),
                            db.or_(
                                db.and_(
                                    Rental.ship_out_time <= ship_out_time,
                                    Rental.ship_in_time >= ship_out_time
                                ),
                                db.and_(
                                    Rental.ship_out_time <= ship_in_time,
                                    Rental.ship_in_time >= ship_in_time
                                ),
                                db.and_(
                                    Rental.ship_out_time >= ship_out_time,
                                    Rental.ship_in_time <= ship_in_time
                                )
                            )
                        ),
                        # 情况2：现有租赁没有物流时间，使用租赁时间判断（向后兼容）
                        db.and_(
                            Rental.ship_out_time.is_(None),
                            Rental.ship_in_time.is_(None),
                            db.or_(
                                db.and_(
                                    Rental.start_date <= ship_in_time.date(),
                                    Rental.end_date >= ship_out_time.date()
                                )
                            )
                        )
                    ),
                    Rental.status == 'active'
                )
            ).first()
            
            return conflicting_rental is None
        
        return True
    
    def is_available(self, ship_out_time=None, ship_in_time=None):
        """检查设备在指定寄出和收回时间段是否可用"""
        if self.status != 'idle':
            return False
        
        return self._check_ship_time_conflict(ship_out_time, ship_in_time)
    
    def get_current_rental(self):
        """获取当前租赁记录"""
        today = datetime.now().date()
        return self.rentals.filter(
            db.and_(
                Rental.start_date <= today,
                Rental.end_date >= today,
                Rental.status == 'active'
            )
        ).first()
    
    def get_rental_history(self, limit=10):
        """获取租赁历史"""
        return self.rentals.order_by(Rental.created_at.desc()).limit(limit).all()
    
    @classmethod
    def get_available_devices(cls, ship_out_time=None, ship_in_time=None):
        """获取可用设备列表（基于寄出和收回时间段）"""
        devices = cls.query.filter(cls.status == 'idle').all()
        
        if ship_out_time and ship_in_time:
            # 使用实例方法过滤有冲突的设备
            return [device for device in devices if device.is_available(ship_out_time, ship_in_time)]
        
        return devices
    
    @classmethod
    def get_device_count_by_status(cls):
        """按状态统计设备数量"""
        return db.session.query(
            cls.status,
            db.func.count(cls.id).label('count')
        ).group_by(cls.status).all()
