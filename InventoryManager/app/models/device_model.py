"""
设备型号数据模型
"""

from app import db
from datetime import datetime
import json


class DeviceModel(db.Model):
    """设备型号模型"""
    __tablename__ = 'device_models'

    # 主键
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='型号ID')

    # 基本信息
    name = db.Column(db.String(50), nullable=False, unique=True, comment='型号名称')
    display_name = db.Column(db.String(100), nullable=False, comment='显示名称')
    description = db.Column(db.Text, nullable=True, comment='型号描述')
    is_active = db.Column(db.Boolean, default=True, comment='是否启用')

    # 新增字段
    default_accessories = db.Column(db.Text, nullable=True, comment='默认附件列表，JSON格式')
    device_value = db.Column(db.Numeric(precision=10, scale=2), nullable=True, comment='设备价值')

    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='更新时间')

    # 关系
    devices = db.relationship('Device', backref='device_model', lazy='dynamic')
    accessories = db.relationship('ModelAccessory', backref='model', lazy='dynamic', cascade='all, delete-orphan')

    def __repr__(self):
        return f'<DeviceModel {self.name}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'name': self.name,
            'display_name': self.display_name,
            'description': self.description,
            'is_active': self.is_active,
            'default_accessories': self.get_default_accessories_list(),
            'device_value': float(self.device_value) if self.device_value else None,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'accessories': [acc.to_dict() for acc in self.accessories.filter_by(is_active=True)]
        }

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

    @classmethod
    def get_active_models(cls):
        """获取所有激活的设备型号"""
        return cls.query.filter_by(is_active=True).all()


class ModelAccessory(db.Model):
    """型号附件关系模型"""
    __tablename__ = 'model_accessories'

    # 主键
    id = db.Column(db.Integer, primary_key=True, autoincrement=True, comment='关系ID')

    # 外键
    model_id = db.Column(db.Integer, db.ForeignKey('device_models.id'), nullable=False, comment='主设备型号ID')

    # 基本信息
    accessory_name = db.Column(db.String(100), nullable=False, comment='附件名称')
    accessory_description = db.Column(db.Text, nullable=True, comment='附件描述')
    accessory_value = db.Column(db.Numeric(precision=10, scale=2), nullable=True, comment='附件价值')
    is_required = db.Column(db.Boolean, default=False, comment='是否必需附件')
    is_active = db.Column(db.Boolean, default=True, comment='是否启用')

    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='更新时间')

    def __repr__(self):
        return f'<ModelAccessory {self.accessory_name} for {self.model.name}>'

    def to_dict(self):
        """转换为字典"""
        return {
            'id': self.id,
            'model_id': self.model_id,
            'accessory_name': self.accessory_name,
            'accessory_description': self.accessory_description,
            'accessory_value': float(self.accessory_value) if self.accessory_value else None,
            'is_required': self.is_required,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat()
        }

    @classmethod
    def get_accessories_for_model(cls, model_id):
        """获取指定型号的所有激活附件"""
        return cls.query.filter_by(model_id=model_id, is_active=True).all()