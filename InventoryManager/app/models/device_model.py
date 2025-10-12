"""
设备型号数据模型
"""

from app import db
from datetime import datetime
import json


class DeviceModel(db.Model):
    """设备型号模型（包含主设备和附件）"""
    __tablename__ = 'device_models'

    # 主键
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='型号ID')

    # 基本信息
    name = db.Column(db.String(50), nullable=False, unique=True, comment='型号名称')
    display_name = db.Column(db.String(100), nullable=False, comment='显示名称')
    description = db.Column(db.Text, nullable=True, comment='型号描述')
    is_active = db.Column(db.Boolean, default=True, comment='是否启用')

    # 附件相关字段
    is_accessory = db.Column(db.Boolean, default=False, nullable=False, comment='是否为附件')
    parent_model_id = db.Column(db.Integer, db.ForeignKey('device_models.id'), nullable=True, comment='主设备型号ID（如果是附件）')

    # 价值字段（主设备和附件共用）
    default_accessories = db.Column(db.Text, nullable=True, comment='默认附件列表，JSON格式')
    device_value = db.Column(db.Numeric(precision=10, scale=2), nullable=True, comment='设备/附件价值')

    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='更新时间')

    # 关系
    devices = db.relationship('Device', backref='device_model', lazy='dynamic')

    # 附件关系（自引用）
    parent_model = db.relationship('DeviceModel', remote_side=[id], backref='accessories', foreign_keys=[parent_model_id])

    def __repr__(self):
        return f'<DeviceModel {self.name}>'

    def to_dict(self, include_accessories=True):
        """转换为字典"""
        result = {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'description': self.description,
            'is_active': self.is_active,
            'is_accessory': self.is_accessory,
            'parent_model_id': self.parent_model_id,
            'default_accessories': self.get_default_accessories_list(),
            'device_value': float(self.device_value) if self.device_value else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

        # 只有主设备型号才返回附件列表
        if not self.is_accessory and include_accessories:
            result['accessories'] = [
                acc.to_dict(include_accessories=False)
                for acc in self.accessories
                if acc.is_active
            ]

        return result

    def get_default_accessories_list(self):
        """获取默认附件列表"""
        if self.default_accessories:
            try:
                # 首先尝试解析JSON格式
                return json.loads(self.default_accessories)
            except (json.JSONDecodeError, TypeError):
                # 如果解析失败，尝试解析换行分隔的字符串格式
                accessories = []
                for line in self.default_accessories.strip().split('\n'):
                    line = line.strip()
                    if line:
                        accessories.append(line)
                return accessories
        return []

    def set_default_accessories_list(self, accessories_list):
        """设置默认附件列表"""
        if accessories_list:
            self.default_accessories = json.dumps(accessories_list, ensure_ascii=False)
        else:
            self.default_accessories = None

    def get_active_accessories(self):
        """获取该型号的所有激活附件"""
        if self.is_accessory:
            return []  # 附件本身没有附件
        return [acc for acc in self.accessories if acc.is_active]

    @classmethod
    def get_active_models(cls, include_accessories=False):
        """
        获取所有激活的设备型号

        Args:
            include_accessories: 是否包含附件型号，默认False（只返回主设备型号）
        """
        query = cls.query.filter_by(is_active=True)
        if not include_accessories:
            query = query.filter_by(is_accessory=False)
        return query.all()

    @classmethod
    def get_accessories_for_model(cls, model_id):
        """获取指定型号的所有激活附件"""
        return cls.query.filter_by(
            parent_model_id=model_id,
            is_accessory=True,
            is_active=True
        ).all()