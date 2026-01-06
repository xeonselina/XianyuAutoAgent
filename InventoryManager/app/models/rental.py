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

    # 订单信息
    xianyu_order_no = db.Column(db.String(50), nullable=True, comment='闲鱼订单号')
    order_amount = db.Column(db.DECIMAL(10, 2), nullable=True, comment='订单金额(元)')
    buyer_id = db.Column(db.String(100), nullable=True, comment='买家ID(闲鱼EID)')

    # 物流信息
    ship_out_tracking_no = db.Column(db.String(50), comment='寄出快递单号')
    ship_in_tracking_no = db.Column(db.String(50), comment='寄回快递单号')
    scheduled_ship_time = db.Column(db.DateTime, comment='预约发货时间')
    express_type_id = db.Column(db.Integer, default=2, comment='顺丰快递类型ID (1=特快,2=标快,263=半日达)')
    
    # 状态信息
    status = db.Column(
        db.Enum('not_shipped', 'scheduled_for_shipping', 'shipped', 'returned', 'completed', 'cancelled', name='rental_status'),
        default='not_shipped',
        comment='租赁状态'
    )
    
    # 时间戳
    created_at = db.Column(db.DateTime, default=datetime.utcnow, comment='创建时间')
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, comment='更新时间')
    
    # 租赁关联（主租赁ID，用于关联主设备和附件设备的租赁记录）
    parent_rental_id = db.Column(db.Integer, db.ForeignKey('rentals.id', ondelete='CASCADE'), nullable=True, comment='父租赁记录ID（用于关联主设备和附件）')
    
    # 配套附件标记（手柄和镜头支架已与设备1:1配齐）
    includes_handle = db.Column(db.Boolean, default=False, nullable=False, comment='是否包含手柄（配套附件）')
    includes_lens_mount = db.Column(db.Boolean, default=False, nullable=False, comment='是否包含镜头支架（配套附件）')
    
    # 代传照片标记
    photo_transfer = db.Column(db.Boolean, default=False, nullable=False, comment='是否代传照片')
    
    # 关系
    audit_logs = db.relationship('AuditLog', backref='rental', lazy='dynamic')
    # 子租赁记录（附件租赁）
    child_rentals = db.relationship('Rental', backref=db.backref('parent_rental', remote_side='Rental.id'), lazy='dynamic')
    
    def __repr__(self):
        return f'<Rental {self.id}: {self.device_id} ({self.start_date} - {self.end_date})>'
    
    def to_dict(self, include_children=True, _depth=0):
        """转换为字典

        Args:
            include_children: 是否包含子租赁详情（默认True）
            _depth: 内部递归深度计数器，防止无限递归
        """
        # 防止无限递归，最大深度为2
        if _depth > 2:
            return {
                'id': self.id,
                'device_id': self.device_id,
                'status': self.status
            }

        # 获取设备信息
        device_dict = self.device.to_dict() if self.device else None

        # 构建附件列表，兼容前端期望的数据结构
        accessories = []
        child_rentals_list = []

        if include_children and _depth < 2:
            for child_rental in self.child_rentals:
                if child_rental.device:
                    # 获取附件的显示名称
                    model_name = child_rental.device.model
                    if child_rental.device.device_model:
                        # 优先使用 device_model 的 display_name
                        model_name = child_rental.device.device_model.name
                    elif child_rental.device.is_accessory:
                        # 如果没有 device_model，使用 device.model
                        model_name = child_rental.device.device_model.name

                    accessories.append({
                        'id': child_rental.device.id,
                        'name': child_rental.device.name,
                        'model': model_name,
                        'is_accessory': child_rental.device.is_accessory,
                        'value': float(child_rental.device.device_model.device_value) if child_rental.device.device_model and child_rental.device.device_model.device_value else None
                    })

                # 递归调用时增加深度，避免无限循环
                child_rentals_list.append(child_rental.to_dict(include_children=False, _depth=_depth + 1))

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
            'xianyu_order_no': self.xianyu_order_no,
            'order_amount': float(self.order_amount) if self.order_amount else None,
            'buyer_id': self.buyer_id,
            'ship_out_tracking_no': self.ship_out_tracking_no,
            'ship_in_tracking_no': self.ship_in_tracking_no,
            'scheduled_ship_time': self.scheduled_ship_time.isoformat() if self.scheduled_ship_time else None,
            'express_type_id': self.express_type_id,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'updated_at': self.updated_at.isoformat(),
            'duration_days': self.get_duration_days(),
            'is_overdue': self.is_overdue(),
            'device': device_dict,
            'device_info': device_dict,  # 保留向后兼容
            'accessories': accessories,
            'parent_rental_id': self.parent_rental_id,
            'child_rentals': child_rentals_list,
            # 配套附件标记
            'includes_handle': self.includes_handle,
            'includes_lens_mount': self.includes_lens_mount,
            # 代传照片标记
            'photo_transfer': self.photo_transfer
        }
    
    def get_duration_days(self):
        """获取租赁天数"""
        if self.start_date and self.end_date:
            return (self.end_date - self.start_date).days + 1
        return 0
    
    def is_overdue(self):
        """检查是否逾期"""
        if self.status == 'shipped' and self.end_date:
            return date.today() > self.end_date
        return False
    
    def is_active(self):
        """检查是否处于活动状态"""
        if self.status != 'shipped':
            return False

        today = date.today()
        return self.start_date <= today <= self.end_date
    
    def can_cancel(self):
        """检查是否可以取消"""
        return self.status in ['not_shipped', 'shipped'] and not self.is_overdue()
    
    def can_extend(self):
        """检查是否可以延期"""
        return self.status == 'shipped' and not self.is_overdue()
    
    def ship(self):
        """发货租赁申请"""
        if self.status == 'not_shipped':
            self.status = 'shipped'
            self.ship_out_time = datetime.utcnow()
            return True
        return False
    
    def return_item(self):
        """设备已收回"""
        if self.status == 'shipped':
            self.status = 'returned'
            self.ship_in_time = datetime.utcnow()
            return True
        return False

    def complete(self):
        """完成租赁"""
        if self.status in ['shipped', 'returned']:
            self.status = 'completed'
            if not self.ship_in_time:
                self.ship_in_time = datetime.utcnow()
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
    
    def get_all_accessories_for_display(self):
        """获取所有附件信息，用于打印和展示
        
        返回统一格式的附件列表，包含配套附件（手柄、镜头支架）和库存附件（手机支架、三脚架）
        
        Returns:
            list: 附件信息列表，每项包含:
                - name: 附件名称
                - type: 附件类型 (handle/lens_mount/phone_holder/tripod)
                - is_bundled: 是否为配套附件（True表示配套，False表示库存附件）
                - id: 设备ID（仅库存附件有）
                - serial_number: 序列号（仅库存附件有）
        """
        accessories = []
        
        # 1. 添加配套附件（基于boolean字段）
        if self.includes_handle:
            accessories.append({
                'name': '手柄',
                'type': 'handle',
                'is_bundled': True
            })
        
        if self.includes_lens_mount:
            accessories.append({
                'name': '镜头支架',
                'type': 'lens_mount',
                'is_bundled': True
            })
        
        # 2. 添加库存附件（基于child_rentals）
        for child in self.child_rentals:
            if child.device:
                accessory_type = self._infer_accessory_type(child.device.name)
                accessories.append({
                    'id': child.device.id,
                    'name': child.device.name,
                    'serial_number': child.device.serial_number,
                    'type': accessory_type,
                    'is_bundled': False
                })
        
        return accessories
    
    def _infer_accessory_type(self, device_name):
        """根据设备名称推断附件类型
        
        Args:
            device_name: 设备名称
            
        Returns:
            str: 附件类型 (phone_holder/tripod/other)
        """
        if '手机支架' in device_name or 'phone' in device_name.lower():
            return 'phone_holder'
        elif '三脚架' in device_name or 'tripod' in device_name.lower():
            return 'tripod'
        elif '手柄' in device_name:
            return 'handle'
        elif '镜头支架' in device_name:
            return 'lens_mount'
        else:
            return 'other'
    
    @classmethod
    def get_active_rentals(cls, date_range=None, include_accessories=False):
        """获取活动租赁记录

        Args:
            date_range: 时间范围
            include_accessories: 是否包括附件租赁记录（默认只返回主租赁）
        """
        if include_accessories:
            query = cls.query.filter(cls.status == 'shipped')
        else:
            # 只返回主租赁记录（用于甘特图显示）
            query = cls.query.filter(
                db.and_(
                    cls.status == 'shipped',
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
                cls.status == 'shipped',
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
        shipped_rentals = query.filter(cls.status == 'shipped').count()
        not_shipped_rentals = query.filter(cls.status == 'not_shipped').count()
        returned_rentals = query.filter(cls.status == 'returned').count()
        completed_rentals = query.filter(cls.status == 'completed').count()
        cancelled_rentals = query.filter(cls.status == 'cancelled').count()

        # 计算收入统计
        revenue_query = query.filter(cls.order_amount.isnot(None))
        total_revenue = db.session.query(db.func.sum(cls.order_amount)).filter(
            cls.id.in_([r.id for r in query.all()]),
            cls.order_amount.isnot(None)
        ).scalar() or 0

        average_order_amount = db.session.query(db.func.avg(cls.order_amount)).filter(
            cls.id.in_([r.id for r in query.all()]),
            cls.order_amount.isnot(None)
        ).scalar() or 0

        orders_with_amount = revenue_query.count()
        orders_without_amount = total_rentals - orders_with_amount

        return {
            'total_rentals': total_rentals,
            'shipped_rentals': shipped_rentals,
            'not_shipped_rentals': not_shipped_rentals,
            'returned_rentals': returned_rentals,
            'completed_rentals': completed_rentals,
            'cancelled_rentals': cancelled_rentals,
            'total_revenue': float(total_revenue) if total_revenue else 0,
            'average_order_amount': float(average_order_amount) if average_order_amount else 0,
            'orders_with_amount': orders_with_amount,
            'orders_without_amount': orders_without_amount,
            'period': {
                'start_date': start_date.isoformat() if start_date else None,
                'end_date': end_date.isoformat() if start_date else None
            }
        }
    

