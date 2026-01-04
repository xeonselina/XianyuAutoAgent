# 数据模型设计: 简化租赁附件选择

**日期**: 2026-01-04  
**功能**: 001-simplify-rental-accessories  
**基于**: research.md 方案A决策

---

## 1. 数据模型概览

本功能涉及的核心数据模型:

1. **Rental** (租赁订单) - **需修改**
2. **Device** (设备) - 不变
3. **DeviceModel** (设备型号) - 不变

---

## 2. Rental (租赁订单) 模型

### 2.1 完整Schema定义

```python
class Rental(db.Model):
    """租赁订单模型"""
    __tablename__ = 'rentals'
    
    # ========== 主键和关联 ==========
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    device_id = db.Column(db.Integer, db.ForeignKey('devices.id'), nullable=False, index=True)
    parent_rental_id = db.Column(db.Integer, db.ForeignKey('rentals.id'), nullable=True, index=True)
    
    # ========== 时间信息 ==========
    start_date = db.Column(db.Date, nullable=False, index=True)
    end_date = db.Column(db.Date, nullable=False, index=True)
    ship_out_time = db.Column(db.DateTime, nullable=True)
    ship_in_time = db.Column(db.DateTime, nullable=True)
    scheduled_ship_time = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=db.func.now())
    updated_at = db.Column(db.DateTime, default=db.func.now(), onupdate=db.func.now())
    
    # ========== 客户信息 ==========
    customer_name = db.Column(db.String(100), nullable=False)
    customer_phone = db.Column(db.String(20), nullable=True)
    destination = db.Column(db.String(100), nullable=True)
    
    # ========== 订单信息 ==========
    xianyu_order_no = db.Column(db.String(50), nullable=True, unique=True)
    order_amount = db.Column(db.DECIMAL(10, 2), nullable=True)
    buyer_id = db.Column(db.String(100), nullable=True)
    
    # ========== 物流信息 ==========
    ship_out_tracking_no = db.Column(db.String(50), nullable=True)
    ship_in_tracking_no = db.Column(db.String(50), nullable=True)
    express_type_id = db.Column(db.Integer, default=2)  # 快递类型ID
    
    # ========== 状态 ==========
    status = db.Column(
        db.Enum('not_shipped', 'scheduled_for_shipping', 'shipped', 'returned', 'completed', 'cancelled'),
        default='not_shipped',
        nullable=False
    )
    
    # ========== 🆕 配套附件标记 (新增字段) ==========
    includes_handle = db.Column(db.Boolean, default=False, nullable=False)
    includes_lens_mount = db.Column(db.Boolean, default=False, nullable=False)
    
    # ========== 关系定义 ==========
    device = db.relationship('Device', backref='rentals', lazy='joined')
    child_rentals = db.relationship(
        'Rental',
        backref=db.backref('parent_rental', remote_side=[id]),
        lazy='select'
    )
    
    # ========== 方法 ==========
    
    def to_dict(self, include_accessories=True) -> dict:
        """
        转换为字典格式
        
        Args:
            include_accessories: 是否包含附件信息
            
        Returns:
            dict: 订单信息字典
        """
        data = {
            'id': self.id,
            'device_id': self.device_id,
            'device_name': self.device.name if self.device else None,
            'device_model': self.device.model if self.device else None,
            'parent_rental_id': self.parent_rental_id,
            
            'start_date': self.start_date.isoformat() if self.start_date else None,
            'end_date': self.end_date.isoformat() if self.end_date else None,
            'ship_out_time': self.ship_out_time.isoformat() if self.ship_out_time else None,
            'ship_in_time': self.ship_in_time.isoformat() if self.ship_in_time else None,
            'scheduled_ship_time': self.scheduled_ship_time.isoformat() if self.scheduled_ship_time else None,
            
            'customer_name': self.customer_name,
            'customer_phone': self.customer_phone,
            'destination': self.destination,
            
            'xianyu_order_no': self.xianyu_order_no,
            'order_amount': float(self.order_amount) if self.order_amount else None,
            'buyer_id': self.buyer_id,
            
            'ship_out_tracking_no': self.ship_out_tracking_no,
            'ship_in_tracking_no': self.ship_in_tracking_no,
            'express_type_id': self.express_type_id,
            
            'status': self.status,
            
            # 🆕 配套附件信息
            'includes_handle': self.includes_handle,
            'includes_lens_mount': self.includes_lens_mount,
            
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        if include_accessories:
            # 获取库存附件(手机支架、三脚架等)
            data['accessories'] = [
                {
                    'id': child.device_id,
                    'rental_id': child.id,
                    'name': child.device.name if child.device else None,
                    'model': child.device.model if child.device else None,
                    'serial_number': child.device.serial_number if child.device else None,
                    'type': self._infer_accessory_type(child.device.name if child.device else '')
                }
                for child in self.child_rentals
            ]
        
        return data
    
    def _infer_accessory_type(self, device_name: str) -> str:
        """根据设备名称推断附件类型"""
        if '手机支架' in device_name:
            return 'phone_holder'
        elif '三脚架' in device_name:
            return 'tripod'
        elif '手柄' in device_name:
            return 'handle'  # 兼容旧数据
        elif '镜头支架' in device_name:
            return 'lens_mount'  # 兼容旧数据
        else:
            return 'other'
    
    def get_all_accessories_for_display(self) -> list:
        """
        获取所有附件信息(用于打印和甘特图显示)
        包含配套附件和库存附件
        
        Returns:
            list: 附件信息列表
        """
        accessories = []
        
        # 配套附件
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
        
        # 库存附件
        for child in self.child_rentals:
            if child.device:
                accessories.append({
                    'id': child.device.id,
                    'name': child.device.name,
                    'serial_number': child.device.serial_number,
                    'type': self._infer_accessory_type(child.device.name),
                    'is_bundled': False
                })
        
        return accessories
    
    def is_main_rental(self) -> bool:
        """判断是否为主订单(非附件订单)"""
        return self.parent_rental_id is None
    
    def get_all_related_rentals(self) -> list:
        """获取主订单及其所有附件订单"""
        if self.is_main_rental():
            return [self] + self.child_rentals
        elif self.parent_rental:
            return self.parent_rental.get_all_related_rentals()
        else:
            return [self]
    
    def __repr__(self):
        return f'<Rental {self.id}: {self.device.name if self.device else "Unknown"} - {self.customer_name}>'
```

### 2.2 新增字段说明

| 字段名 | 类型 | 默认值 | 可空 | 索引 | 说明 |
|--------|------|--------|------|------|------|
| `includes_handle` | Boolean | False | NOT NULL | 建议添加 | 是否包含配套手柄 |
| `includes_lens_mount` | Boolean | False | NOT NULL | 建议添加 | 是否包含配套镜头支架 |

**设计原则**:
- 使用布尔值而非外键,因为手柄和镜头支架已与设备1:1配齐
- 不存储具体的手柄/镜头支架设备ID,简化数据模型
- 默认值为False,确保向后兼容

### 2.3 数据验证规则

```python
class RentalValidator:
    """租赁订单数据验证器"""
    
    @staticmethod
    def validate_create_data(data: dict) -> tuple[bool, str]:
        """
        验证创建租赁订单的数据
        
        Returns:
            (is_valid, error_message)
        """
        # 基本字段验证
        required_fields = ['device_id', 'start_date', 'end_date', 'customer_name']
        for field in required_fields:
            if field not in data or not data[field]:
                return False, f"缺少必填字段: {field}"
        
        # 日期验证
        try:
            start_date = datetime.strptime(data['start_date'], '%Y-%m-%d').date()
            end_date = datetime.strptime(data['end_date'], '%Y-%m-%d').date()
            
            if end_date < start_date:
                return False, "结束日期不能早于开始日期"
            
            if start_date < date.today():
                return False, "开始日期不能早于今天"
        except ValueError:
            return False, "日期格式错误,应为 YYYY-MM-DD"
        
        # 设备存在性验证
        device = Device.query.get(data['device_id'])
        if not device:
            return False, f"设备ID {data['device_id']} 不存在"
        
        if device.is_accessory:
            return False, "主设备不能是附件"
        
        # 附件验证
        accessory_ids = data.get('accessory_ids', [])
        for acc_id in accessory_ids:
            accessory_device = Device.query.get(acc_id)
            if not accessory_device:
                return False, f"附件设备ID {acc_id} 不存在"
            if not accessory_device.is_accessory:
                return False, f"设备 {accessory_device.name} 不是附件"
        
        return True, ""
    
    @staticmethod
    def validate_update_data(rental: 'Rental', data: dict) -> tuple[bool, str]:
        """验证更新租赁订单的数据"""
        # 状态转换验证
        if 'status' in data:
            valid_transitions = {
                'not_shipped': ['scheduled_for_shipping', 'shipped', 'cancelled'],
                'scheduled_for_shipping': ['shipped', 'cancelled'],
                'shipped': ['returned', 'cancelled'],
                'returned': ['completed'],
                'completed': [],
                'cancelled': []
            }
            
            new_status = data['status']
            if new_status not in valid_transitions.get(rental.status, []):
                return False, f"不允许从状态 '{rental.status}' 转换到 '{new_status}'"
        
        # 日期验证(如果修改)
        if 'start_date' in data or 'end_date' in data:
            start_date = datetime.strptime(data.get('start_date', rental.start_date.isoformat()), '%Y-%m-%d').date()
            end_date = datetime.strptime(data.get('end_date', rental.end_date.isoformat()), '%Y-%m-%d').date()
            
            if end_date < start_date:
                return False, "结束日期不能早于开始日期"
        
        return True, ""
```

---

## 3. Device (设备) 模型

### 3.1 现有Schema (无变更)

```python
class Device(db.Model):
    """设备模型"""
    __tablename__ = 'devices'
    
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    name = db.Column(db.String(100), nullable=False, index=True)
    serial_number = db.Column(db.String(100), unique=True, nullable=True)
    model = db.Column(db.String(50), default='x200u')
    model_id = db.Column(db.Integer, db.ForeignKey('device_models.id'), nullable=True)
    is_accessory = db.Column(db.Boolean, default=False, nullable=False, index=True)
    status = db.Column(db.Enum('online', 'offline'), default='online')
    
    # 关系
    rentals = db.relationship('Rental', backref='device', lazy='dynamic')
    
    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'name': self.name,
            'serial_number': self.serial_number,
            'model': self.model,
            'model_id': self.model_id,
            'is_accessory': self.is_accessory,
            'status': self.status
        }
```

### 3.2 附件设备命名约定

为了便于程序识别附件类型,建议遵循以下命名规范:

| 附件类型 | 命名模式 | 示例 |
|---------|---------|------|
| 手柄 | `手柄-{编号}` | 手柄-A01, 手柄-B02 |
| 镜头支架 | `镜头支架-{编号}` | 镜头支架-L01, 镜头支架-L02 |
| 手机支架 | `手机支架-{编号}` | 手机支架-P01, 手机支架-P02 |
| 三脚架 | `三脚架-{编号}` | 三脚架-T01, 三脚架-T02 |

**重要**: 所有附件设备必须设置 `is_accessory = True`

---

## 4. 数据关系图

```
┌─────────────────────────────────────┐
│           Rental (主订单)             │
│  ─────────────────────────────────  │
│  id: 1001                            │
│  device_id: 123 (X200U-001)         │
│  parent_rental_id: NULL              │
│  includes_handle: TRUE     🆕        │
│  includes_lens_mount: FALSE 🆕       │
│  customer_name: "张三"               │
│  ...                                 │
└──────────────┬──────────────────────┘
               │
               │ parent_rental_id
               │
       ┌───────┴──────────┐
       │                  │
       ▼                  ▼
┌─────────────┐    ┌─────────────┐
│  Rental     │    │  Rental     │
│  (附件订单)  │    │  (附件订单)  │
├─────────────┤    ├─────────────┤
│ id: 1002    │    │ id: 1003    │
│ device_id:  │    │ device_id:  │
│   45 (手机  │    │   67 (三脚  │
│   支架-P01) │    │   架-T05)   │
│ parent:1001 │    │ parent:1001 │
└──────┬──────┘    └──────┬──────┘
       │                  │
       └────────┬─────────┘
                │ device_id
                ▼
        ┌────────────────┐
        │     Device     │
        ├────────────────┤
        │ is_accessory:  │
        │     TRUE       │
        └────────────────┘
```

**关键点**:
- 主订单的`parent_rental_id`为NULL
- 配套附件(手柄、镜头支架)通过布尔字段标记,**不创建子租赁记录**
- 库存附件(手机支架、三脚架)仍创建子租赁记录

---

## 5. 数据库迁移SQL

### 5.1 添加新字段

```sql
-- 添加配套附件标记字段
ALTER TABLE rentals 
ADD COLUMN includes_handle BOOLEAN NOT NULL DEFAULT FALSE,
ADD COLUMN includes_lens_mount BOOLEAN NOT NULL DEFAULT FALSE;

-- 添加索引(可选,用于按附件类型筛选订单)
CREATE INDEX idx_rentals_includes_handle ON rentals(includes_handle);
CREATE INDEX idx_rentals_includes_lens_mount ON rentals(includes_lens_mount);
```

### 5.2 数据迁移(从旧架构转换)

```sql
-- 迁移历史数据:从子租赁推断配套附件标记
UPDATE rentals r
SET includes_handle = TRUE
WHERE r.parent_rental_id IS NULL
AND EXISTS (
    SELECT 1 FROM rentals child
    JOIN devices d ON child.device_id = d.id
    WHERE child.parent_rental_id = r.id
    AND d.name LIKE '%手柄%'
);

UPDATE rentals r
SET includes_lens_mount = TRUE
WHERE r.parent_rental_id IS NULL
AND EXISTS (
    SELECT 1 FROM rentals child
    JOIN devices d ON child.device_id = d.id
    WHERE child.parent_rental_id = r.id
    AND d.name LIKE '%镜头支架%'
);

-- 验证迁移结果
SELECT 
    r.id,
    r.customer_name,
    r.includes_handle,
    r.includes_lens_mount,
    GROUP_CONCAT(d.name SEPARATOR ', ') as child_devices
FROM rentals r
LEFT JOIN rentals child ON child.parent_rental_id = r.id
LEFT JOIN devices d ON child.device_id = d.id
WHERE r.parent_rental_id IS NULL
GROUP BY r.id
LIMIT 20;
```

### 5.3 清理旧数据(可选,建议观察一段时间后执行)

```sql
-- 删除已迁移的手柄和镜头支架子租赁记录
-- ⚠️ 谨慎操作,建议先备份!

-- 1. 标记要删除的记录(先不真删)
ALTER TABLE rentals ADD COLUMN _to_delete BOOLEAN DEFAULT FALSE;

UPDATE rentals r
JOIN devices d ON r.device_id = d.id
SET r._to_delete = TRUE
WHERE r.parent_rental_id IS NOT NULL
AND (d.name LIKE '%手柄%' OR d.name LIKE '%镜头支架%');

-- 2. 验证标记的记录
SELECT r.id, r.parent_rental_id, d.name
FROM rentals r
JOIN devices d ON r.device_id = d.id
WHERE r._to_delete = TRUE;

-- 3. 确认无误后删除
DELETE FROM rentals WHERE _to_delete = TRUE;

-- 4. 清理标记字段
ALTER TABLE rentals DROP COLUMN _to_delete;
```

---

## 6. 状态转换图

```
       创建订单
          │
          ▼
    ┌──────────┐
    │not_shipped│ ◄─────┐
    └─────┬────┘        │
          │             │ 取消
          │ 预约发货     │
          ▼             │
┌───────────────────┐   │
│scheduled_for_     │───┤
│shipping           │   │
└─────┬─────────────┘   │
      │                 │
      │ 发货             │
      ▼                 │
  ┌────────┐            │
  │shipped │────────────┤
  └────┬───┘            │
       │                │
       │ 收货归还        │
       ▼                │
  ┌─────────┐           │
  │returned │           │
  └────┬────┘           │
       │                │
       │ 确认完成        │
       ▼                ▼
  ┌──────────┐    ┌───────────┐
  │completed │    │ cancelled │
  └──────────┘    └───────────┘
```

---

## 7. 数据完整性约束

### 7.1 数据库层约束

```sql
-- 外键约束(已有)
ALTER TABLE rentals
ADD CONSTRAINT fk_rentals_device
    FOREIGN KEY (device_id) REFERENCES devices(id) ON DELETE RESTRICT,
ADD CONSTRAINT fk_rentals_parent
    FOREIGN KEY (parent_rental_id) REFERENCES rentals(id) ON DELETE CASCADE;

-- 检查约束
ALTER TABLE rentals
ADD CONSTRAINT chk_rentals_dates
    CHECK (end_date >= start_date),
ADD CONSTRAINT chk_rentals_parent_not_self
    CHECK (parent_rental_id IS NULL OR parent_rental_id != id);

-- 唯一约束(已有)
ALTER TABLE rentals
ADD CONSTRAINT uq_rentals_xianyu_order_no
    UNIQUE (xianyu_order_no);
```

### 7.2 应用层约束

```python
class RentalBusinessRules:
    """租赁订单业务规则"""
    
    @staticmethod
    def can_add_accessory(rental: Rental, accessory_device: Device, start_date: date, end_date: date) -> tuple[bool, str]:
        """
        检查是否可以为订单添加附件
        
        Returns:
            (can_add, reason)
        """
        # 检查附件可用性
        conflicts = Rental.query.filter(
            Rental.device_id == accessory_device.id,
            Rental.status.in_(['not_shipped', 'scheduled_for_shipping', 'shipped']),
            Rental.start_date <= end_date,
            Rental.end_date >= start_date
        ).all()
        
        if conflicts:
            return False, f"附件 {accessory_device.name} 在此时间段已被预订"
        
        return True, ""
    
    @staticmethod
    def validate_bundled_accessories(device: Device, includes_handle: bool, includes_lens_mount: bool) -> tuple[bool, str]:
        """
        验证配套附件配置是否合理
        
        Returns:
            (is_valid, message)
        """
        # 未来可以添加业务规则,例如:
        # - 某些设备型号不支持某些附件
        # - 检查设备是否真的配齐了手柄/镜头支架
        
        # 当前简单校验:只有主设备才能有配套附件
        if device.is_accessory:
            if includes_handle or includes_lens_mount:
                return False, "附件设备不能再包含配套附件"
        
        return True, ""
```

---

## 8. 查询示例

### 8.1 获取订单的所有附件信息

```python
def get_rental_with_all_accessories(rental_id: int) -> dict:
    """获取订单及其所有附件信息(含配套附件和库存附件)"""
    rental = Rental.query.get(rental_id)
    if not rental or not rental.is_main_rental():
        return None
    
    result = rental.to_dict()
    result['all_accessories'] = rental.get_all_accessories_for_display()
    
    return result

# 示例输出:
{
    'id': 1001,
    'device_name': 'X200U-001',
    'customer_name': '张三',
    'includes_handle': True,
    'includes_lens_mount': False,
    'accessories': [
        {'id': 45, 'name': '手机支架-P01', 'type': 'phone_holder', 'is_bundled': False}
    ],
    'all_accessories': [
        {'name': '手柄', 'type': 'handle', 'is_bundled': True},
        {'id': 45, 'name': '手机支架-P01', 'type': 'phone_holder', 'is_bundled': False}
    ]
}
```

### 8.2 查找带手柄的所有订单

```sql
SELECT 
    r.id,
    r.customer_name,
    d.name as device_name,
    r.start_date,
    r.end_date
FROM rentals r
JOIN devices d ON r.device_id = d.id
WHERE r.parent_rental_id IS NULL
AND r.includes_handle = TRUE
ORDER BY r.start_date DESC;
```

### 8.3 统计附件使用情况

```sql
SELECT 
    '手柄' as accessory_type,
    COUNT(*) as rental_count,
    SUM(DATEDIFF(end_date, start_date)) as total_rental_days
FROM rentals
WHERE parent_rental_id IS NULL
AND includes_handle = TRUE
AND status != 'cancelled'

UNION ALL

SELECT 
    '镜头支架' as accessory_type,
    COUNT(*) as rental_count,
    SUM(DATEDIFF(end_date, start_date)) as total_rental_days
FROM rentals
WHERE parent_rental_id IS NULL
AND includes_lens_mount = TRUE
AND status != 'cancelled'

UNION ALL

SELECT 
    '手机支架' as accessory_type,
    COUNT(*) as rental_count,
    SUM(DATEDIFF(child.end_date, child.start_date)) as total_rental_days
FROM rentals child
JOIN devices d ON child.device_id = d.id
WHERE child.parent_rental_id IS NOT NULL
AND d.name LIKE '%手机支架%'
AND child.status != 'cancelled';
```

---

## 9. 数据迁移回滚方案

如果需要回滚到旧架构:

```sql
-- 1. 从布尔字段重建子租赁记录(需要手柄/镜头支架的设备ID)
-- 注意:需要提前准备设备ID映射表

INSERT INTO rentals (
    device_id,
    parent_rental_id,
    start_date,
    end_date,
    customer_name,
    customer_phone,
    status
)
SELECT 
    (SELECT id FROM devices WHERE name LIKE '%手柄%' AND is_accessory = TRUE LIMIT 1) as device_id,
    r.id as parent_rental_id,
    r.start_date,
    r.end_date,
    r.customer_name,
    r.customer_phone,
    r.status
FROM rentals r
WHERE r.parent_rental_id IS NULL
AND r.includes_handle = TRUE;

-- 2. 镜头支架同理...

-- 3. 删除新增字段
ALTER TABLE rentals 
DROP COLUMN includes_handle,
DROP COLUMN includes_lens_mount;
```

---

## 10. 性能考虑

### 10.1 索引策略

```sql
-- 主要查询模式的索引
CREATE INDEX idx_rentals_device_dates ON rentals(device_id, start_date, end_date);
CREATE INDEX idx_rentals_parent_status ON rentals(parent_rental_id, status);
CREATE INDEX idx_rentals_status_dates ON rentals(status, start_date, end_date);

-- 配套附件查询索引
CREATE INDEX idx_rentals_bundled_accessories ON rentals(includes_handle, includes_lens_mount) 
WHERE parent_rental_id IS NULL;
```

### 10.2 查询优化建议

1. **批量加载附件**: 使用`joinedload`避免N+1查询
   ```python
   rentals = Rental.query.options(
       db.joinedload(Rental.child_rentals).joinedload(Rental.device)
   ).filter(Rental.parent_rental_id == None).all()
   ```

2. **甘特图数据查询**: 使用单个查询获取所有需要的数据
   ```python
   rentals_with_accessories = db.session.query(Rental).options(
       db.joinedload(Rental.device),
       db.joinedload(Rental.child_rentals).joinedload(Rental.device)
   ).filter(
       Rental.parent_rental_id == None,
       Rental.start_date <= end_date,
       Rental.end_date >= start_date
   ).all()
   ```

---

**数据模型设计完成日期**: 2026-01-04  
**下一步**: 生成API合约文档 (contracts/api-spec.yaml)
