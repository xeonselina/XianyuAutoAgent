"""
审计日志数据模型
"""

from app import db
from datetime import datetime
import uuid


class AuditLog(db.Model):
    """审计日志模型"""
    __tablename__ = 'audit_logs'
    
    # 主键
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    
    # 关联信息
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), comment='相关设备ID')
    rental_id = db.Column(db.Integer, db.ForeignKey('rentals.id'), comment='相关租赁ID')
    
    # 操作信息
    action = db.Column(db.String(50), nullable=False, comment='操作类型')
    resource_type = db.Column(db.String(50), comment='资源类型')
    resource_id = db.Column(db.String(50), comment='资源ID')
    
    # 详细信息
    description = db.Column(db.Text, comment='操作描述')
    details = db.Column(db.JSON, comment='操作详情')
    ip_address = db.Column(db.String(45), comment='IP地址')
    user_agent = db.Column(db.String(500), comment='用户代理')
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    
    def __repr__(self):
        return f'<AuditLog {self.id}: {self.action}>'
    
    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'device_id': self.device_id,
            'rental_id': self.rental_id,
            'action': self.action,
            'resource_type': self.resource_type,
            'resource_id': self.resource_id,
            'description': self.description,
            'details': self.details,
            'ip_address': self.ip_address,
            'user_agent': self.user_agent,
            'created_at': self.created_at.isoformat()
        }
    
    @classmethod
    def log_action(cls, action, resource_type=None, resource_id=None, 
                   description=None, details=None, ip_address=None, user_agent=None):
        """记录操作日志"""
        log = cls(
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            description=description,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent
        )
        
        db.session.add(log)
        db.session.commit()
        
        return log
    
    @classmethod
    def get_device_actions(cls, device_id, limit=50):
        """获取设备操作记录"""
        return cls.query.filter_by(device_id=device_id).order_by(cls.created_at.desc()).limit(limit).all()
    
    @classmethod
    def get_rental_actions(cls, rental_id, limit=50):
        """获取租赁操作记录"""
        return cls.query.filter_by(rental_id=rental_id).order_by(cls.created_at.desc()).limit(limit).all()
    
    @classmethod
    def get_actions_by_type(cls, action, limit=50):
        """根据操作类型获取记录"""
        return cls.query.filter_by(action=action).order_by(cls.created_at.desc()).limit(limit).all()
    
    @classmethod
    def get_recent_actions(cls, hours=24, limit=100):
        """获取最近的操作记录"""
        from datetime import timedelta
        
        cutoff_time = datetime.utcnow() - timedelta(hours=hours)
        
        return cls.query.filter(
            cls.created_at >= cutoff_time
        ).order_by(cls.created_at.desc()).limit(limit).all()
    
    @classmethod
    def get_action_statistics(cls, start_date=None, end_date=None):
        """获取操作统计信息"""
        query = cls.query
        
        if start_date and end_date:
            query = query.filter(
                db.and_(
                    cls.created_at >= start_date,
                    cls.created_at <= end_date
                )
            )
        
        # 按操作类型统计
        action_stats = db.session.query(
            cls.action,
            db.func.count(cls.id).label('count')
        ).group_by(cls.action).all()
        
        # 按资源类型统计
        resource_stats = db.session.query(
            cls.resource_type,
            db.func.count(cls.id).label('count')
        ).filter(cls.resource_type.isnot(None)).group_by(cls.resource_type).all()
        
        return {
            'action_statistics': [{'action': action, 'count': count} for action, count in action_stats],
            'resource_statistics': [{'resource_type': resource_type, 'count': count} for resource_type, count in resource_stats],
            'total_actions': query.count(),
            'period': {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if end_date else None
            }
        }
