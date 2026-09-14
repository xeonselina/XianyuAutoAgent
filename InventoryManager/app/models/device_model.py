"""
设备型号数据模型
"""

from app import db
from app.lens_combos import (
    compatibility_lens_combo_config,
    parse_allowed_lens_combos,
)
from app.rental_packages import (
    compatibility_rental_package_config,
    parse_rental_packages,
    serialize_json,
)
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
    allowed_lens_combos = db.Column(db.Text, nullable=True, comment='允许的镜头组合，JSON格式')
    default_lens_combo = db.Column(db.String(30), nullable=True, comment='默认镜头组合')
    rental_packages = db.Column(db.Text, nullable=True, comment='型号租赁组合，JSON格式')
    default_rental_package_id = db.Column(db.String(64), nullable=True, comment='默认租赁组合ID')

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
        packages, default_package_id = self.get_effective_rental_package_config()
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
            'allowed_lens_combos': self.get_effective_lens_combo_config()[0],
            'default_lens_combo': self.get_effective_lens_combo_config()[1],
            'rental_packages': packages,
            'default_rental_package_id': default_package_id,
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

    def get_allowed_lens_combos_list(self):
        """读取型号自身保存的镜头组合。"""
        return parse_allowed_lens_combos(self.allowed_lens_combos)

    def set_allowed_lens_combos_list(self, combinations):
        """保存型号镜头组合。"""
        self.allowed_lens_combos = (
            json.dumps(combinations, ensure_ascii=False) if combinations else None
        )

    def get_effective_lens_combo_config(self):
        """返回预定时使用的配置，并兼容迁移前或旧数据。"""
        if self.is_accessory:
            return [], None
        allowed = self.get_allowed_lens_combos_list()
        if allowed and self.default_lens_combo in allowed:
            return allowed, self.default_lens_combo
        return compatibility_lens_combo_config(self.name)

    def get_rental_packages_list(self):
        """读取型号自身保存的自由租赁组合。"""
        return parse_rental_packages(self.rental_packages)

    def set_rental_packages_list(self, packages):
        """保存型号自由租赁组合。"""
        self.rental_packages = serialize_json(packages) if packages else None

    def get_effective_rental_package_config(self):
        """返回预定使用的组合配置，并兼容尚未迁移的型号。"""
        if self.is_accessory:
            return [], None
        packages = self.get_rental_packages_list()
        enabled_ids = {
            item.get('id') for item in packages if item.get('is_active', True)
        }
        if packages and self.default_rental_package_id in enabled_ids:
            return packages, self.default_rental_package_id
        allowed, default = self.get_effective_lens_combo_config()
        return compatibility_rental_package_config(self.name, allowed, default)

    def get_rental_package(self, package_id, *, enabled_only=False):
        """按稳定 ID 查找型号组合。"""
        packages, _default = self.get_effective_rental_package_config()
        for package in packages:
            if package.get('id') != package_id:
                continue
            if enabled_only and not package.get('is_active', True):
                return None
            return package
        return None

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
