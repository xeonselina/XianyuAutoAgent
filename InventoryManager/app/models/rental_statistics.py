"""
租赁统计数据模型
用于存储每日的租赁统计快照
"""

from app import db
from datetime import datetime


class RentalStatistics(db.Model):
    """租赁统计数据模型"""
    __tablename__ = 'rental_statistics'

    # 主键
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='统计ID')

    # 统计日期（用于标识是哪一天的统计）
    stat_date = db.Column(db.Date, nullable=False, unique=True, index=True, comment='统计日期')

    # 统计周期
    period_start = db.Column(db.Date, nullable=False, comment='统计周期开始日期')
    period_end = db.Column(db.Date, nullable=False, comment='统计周期结束日期')

    # 统计数据
    total_rentals = db.Column(db.Integer, nullable=False, default=0, comment='订单总数')
    total_rent = db.Column(db.Numeric(precision=10, scale=2), nullable=False, default=0, comment='订单总租金')
    total_value = db.Column(db.Numeric(precision=10, scale=2), nullable=False, default=0, comment='订单总收入价值')

    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='更新时间')

    def __repr__(self):
        return f'<RentalStatistics {self.stat_date}: {self.total_rentals} orders, ¥{self.total_value}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'stat_date': self.stat_date.isoformat(),
            'period_start': self.period_start.isoformat(),
            'period_end': self.period_end.isoformat(),
            'total_rentals': self.total_rentals,
            'total_rent': float(self.total_rent) if self.total_rent else 0,
            'total_value': float(self.total_value) if self.total_value else 0,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    @classmethod
    def get_latest_statistics(cls, limit=30):
        """获取最近的统计记录"""
        return cls.query.order_by(cls.stat_date.desc()).limit(limit).all()

    @classmethod
    def get_statistics_by_date_range(cls, start_date, end_date):
        """获取指定日期范围的统计记录"""
        return cls.query.filter(
            cls.stat_date >= start_date,
            cls.stat_date <= end_date
        ).order_by(cls.stat_date.asc()).all()
