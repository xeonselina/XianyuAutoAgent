# Data Model: 设备验货系统

**Feature**: 002-device-inspection  
**Date**: 2026-01-04  
**Status**: Complete

## 概述

本文档定义验货系统的数据模型，包括新增的验货记录（InspectionRecord）、验货检查项（InspectionCheckItem）实体，以及对现有租赁记录（Rental）实体的扩展。

## 实体关系图（ER Diagram）

```text
┌─────────────────┐
│     Device      │
│                 │
│  id (PK)        │
│  name           │
│  serial_number  │
│  ...            │
└────────┬────────┘
         │
         │ 1
         │
         │ N
┌────────┴────────┐           ┌─────────────────────┐
│     Rental      │           │  InspectionRecord   │
│                 │ 1      N  │                     │
│  id (PK)        ├───────────┤  id (PK)            │
│  device_id (FK) │           │  rental_id (FK)     │
│  customer_name  │           │  device_id (FK)     │
│  includes_handle│           │  status             │
│  includes_lens_ │           │  inspector_user_id  │
│     mount       │           │  created_at         │
│  photo_transfer │ (新增)    │  updated_at         │
│  accessories    │           └──────────┬──────────┘
│  ...            │                      │
└─────────────────┘                      │ 1
                                         │
                                         │ N
                              ┌──────────┴─────────────┐
                              │  InspectionCheckItem   │
                              │                        │
                              │  id (PK)               │
                              │  inspection_record_id  │
                              │      (FK)              │
                              │  item_name             │
                              │  is_checked            │
                              │  item_order            │
                              └────────────────────────┘
```

## 实体详细定义

### 1. InspectionRecord（验货记录）

**描述**: 表示一次完整的设备验货记录，包含验货的基本信息和验货结果状态。

#### 字段定义

| 字段名 | 数据类型 | 约束 | 默认值 | 说明 |
|--------|---------|------|--------|------|
| `id` | Integer | PRIMARY KEY, AUTO_INCREMENT | - | 验货记录唯一标识 |
| `rental_id` | Integer | FOREIGN KEY (Rental.id), NOT NULL, INDEX | - | 关联的租赁记录ID |
| `device_id` | Integer | FOREIGN KEY (Device.id), NOT NULL, INDEX | - | 关联的设备ID（冗余字段，便于查询） |
| `status` | String(20) | NOT NULL, INDEX | 'abnormal' | 验货状态：'normal' / 'abnormal' |
| `inspector_user_id` | Integer | FOREIGN KEY (User.id), NULLABLE | NULL | 验货人员ID（预留字段） |
| `created_at` | DateTime | NOT NULL | CURRENT_TIMESTAMP | 验货记录创建时间 |
| `updated_at` | DateTime | NOT NULL | CURRENT_TIMESTAMP ON UPDATE | 最后修改时间 |

#### 字段说明

- **rental_id**: 关联到 Rental 表，标识本次验货对应的租赁订单
- **device_id**: 冗余字段，从 rental.device_id 复制而来，便于按设备查询验货历史
- **status**: 
  - `'normal'`: 验机正常（所有检查项都已勾选）
  - `'abnormal'`: 验机异常（至少有一个检查项未勾选）
- **inspector_user_id**: 预留字段，如果系统有用户登录功能，记录是哪个工作人员进行的验货
- **updated_at**: 记录最后修改时间，用于审计验货记录的变更历史

#### 索引设计

```sql
CREATE INDEX idx_inspection_rental_id ON inspection_record(rental_id);
CREATE INDEX idx_inspection_device_id ON inspection_record(device_id);
CREATE INDEX idx_inspection_status ON inspection_record(status);
CREATE INDEX idx_inspection_created_at ON inspection_record(created_at DESC);
```

#### 业务规则

1. **唯一性约束**: 一个租赁订单可以有多次验货记录（例如退回维修后重新验货）
2. **级联删除**: 当 InspectionRecord 被删除时，关联的 InspectionCheckItem 应级联删除（ON DELETE CASCADE）
3. **状态计算**: `status` 字段应根据关联的 InspectionCheckItem 的勾选情况自动计算
4. **只读历史**: 验货记录一旦创建，不应删除（只能编辑），用于审计追溯

#### SQLAlchemy 模型定义

```python
# app/models/inspection_record.py

from app import db
from datetime import datetime

class InspectionRecord(db.Model):
    """验货记录模型"""
    
    __tablename__ = 'inspection_record'
    
    id = db.Column(db.Integer, primary_key=True)
    rental_id = db.Column(db.Integer, db.ForeignKey('rental.id'), nullable=False, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey('device.id'), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default='abnormal', index=True, 
                      comment='验货状态: normal=验机正常, abnormal=验机异常')
    inspector_user_id = db.Column(db.Integer, nullable=True, comment='验货人员ID（预留）')
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # 关联关系
    rental = db.relationship('Rental', backref='inspection_records', lazy='joined')
    device = db.relationship('Device', backref='inspection_records', lazy='joined')
    check_items = db.relationship('InspectionCheckItem', backref='inspection_record', 
                                  lazy='select', cascade='all, delete-orphan', 
                                  order_by='InspectionCheckItem.item_order')
    
    def calculate_status(self):
        """根据检查项勾选情况计算验货状态"""
        if not self.check_items:
            return 'abnormal'
        
        all_checked = all(item.is_checked for item in self.check_items)
        return 'normal' if all_checked else 'abnormal'
    
    def to_dict(self):
        """转换为字典（API 响应）"""
        return {
            'id': self.id,
            'rental_id': self.rental_id,
            'device_id': self.device_id,
            'device_name': self.device.name if self.device else None,
            'customer_name': self.rental.customer_name if self.rental else None,
            'status': self.status,
            'inspector_user_id': self.inspector_user_id,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None,
            'check_items': [item.to_dict() for item in self.check_items]
        }
```

---

### 2. InspectionCheckItem（验货检查项）

**描述**: 表示验货清单中的单个检查项，记录检查项的名称、勾选状态和显示顺序。

#### 字段定义

| 字段名 | 数据类型 | 约束 | 默认值 | 说明 |
|--------|---------|------|--------|------|
| `id` | Integer | PRIMARY KEY, AUTO_INCREMENT | - | 检查项唯一标识 |
| `inspection_record_id` | Integer | FOREIGN KEY (InspectionRecord.id), NOT NULL, INDEX | - | 所属验货记录ID |
| `item_name` | String(100) | NOT NULL | - | 检查项名称 |
| `is_checked` | Boolean | NOT NULL | False | 是否已勾选 |
| `item_order` | Integer | NOT NULL | 0 | 显示顺序（基础检查项在前，附件检查项在后） |

#### 字段说明

- **inspection_record_id**: 外键，关联到 InspectionRecord 表
- **item_name**: 检查项的显示名称，例如：
  - 基础检查项："手机,镜头无严重磕碰"、"充电头和充电线"
  - 附件检查项："手柄"、"镜头支架"、"手机支架-P01"
  - 服务检查项："代传照片"
- **is_checked**: 布尔值，标识该检查项是否已被工作人员勾选
- **item_order**: 整数，用于前端按顺序显示检查项
  - 0-4: 基础检查项
  - 5+: 动态检查项（附件、服务等）

#### 索引设计

```sql
CREATE INDEX idx_check_item_inspection_id ON inspection_check_item(inspection_record_id);
```

#### 业务规则

1. **从属关系**: 检查项必须属于某个验货记录，不能独立存在
2. **级联删除**: 当 InspectionRecord 被删除时，所有关联的检查项应自动删除
3. **显示顺序**: 基础检查项应始终排在前面（item_order 0-4），动态检查项排在后面
4. **勾选状态**: 默认为未勾选（False），工作人员逐项检查后勾选

#### SQLAlchemy 模型定义

```python
# app/models/inspection_check_item.py

from app import db

class InspectionCheckItem(db.Model):
    """验货检查项模型"""
    
    __tablename__ = 'inspection_check_item'
    
    id = db.Column(db.Integer, primary_key=True)
    inspection_record_id = db.Column(db.Integer, db.ForeignKey('inspection_record.id'), 
                                    nullable=False, index=True)
    item_name = db.Column(db.String(100), nullable=False, comment='检查项名称')
    is_checked = db.Column(db.Boolean, nullable=False, default=False, comment='是否已勾选')
    item_order = db.Column(db.Integer, nullable=False, default=0, comment='显示顺序')
    
    def to_dict(self):
        """转换为字典（API 响应）"""
        return {
            'id': self.id,
            'inspection_record_id': self.inspection_record_id,
            'item_name': self.item_name,
            'is_checked': self.is_checked,
            'item_order': self.item_order
        }
```

---

### 3. Rental（租赁记录 - 扩展）

**描述**: 现有的租赁记录实体，需要添加"代传照片"字段以支持验货检查项的动态生成。

#### 新增字段

| 字段名 | 数据类型 | 约束 | 默认值 | 说明 |
|--------|---------|------|--------|------|
| `photo_transfer` | Boolean | NOT NULL | False | 是否包含代传照片服务 |

#### 字段说明

- **photo_transfer**: 布尔值，标识该租赁订单是否包含"代传照片"服务
- 如果为 `True`，验货时检查清单会自动添加"代传照片"检查项

#### 数据库迁移

```python
# migrations/versions/xxxx_add_photo_transfer_to_rental.py

"""添加 photo_transfer 字段到 rental 表

Revision ID: xxxx
Revises: xxxx
Create Date: 2026-01-04

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = 'xxxx'
down_revision = 'xxxx'
branch_labels = None
depends_on = None

def upgrade():
    """升级数据库"""
    op.add_column('rental', 
        sa.Column('photo_transfer', sa.Boolean(), nullable=False, server_default='0', 
                 comment='是否代传照片')
    )

def downgrade():
    """回滚数据库"""
    op.drop_column('rental', 'photo_transfer')
```

#### SQLAlchemy 模型更新

```python
# app/models/rental.py

class Rental(db.Model):
    """租赁记录模型"""
    
    # ... 现有字段 ...
    
    # 新增字段
    photo_transfer = db.Column(db.Boolean, default=False, nullable=False, comment='是否代传照片')
    
    # ... 现有方法 ...
```

---

## 实体关系说明

### 1. InspectionRecord ↔ Rental（多对一）

- **关系**: 一个租赁订单可以有多次验货记录（例如退回维修后重新验货）
- **外键**: `InspectionRecord.rental_id → Rental.id`
- **查询示例**:
  ```python
  # 查询某个租赁的所有验货记录
  rental = Rental.query.get(123)
  inspections = rental.inspection_records
  ```

### 2. InspectionRecord ↔ Device（多对一）

- **关系**: 一个设备可以有多次验货记录（不同的租赁周期）
- **外键**: `InspectionRecord.device_id → Device.id`
- **冗余设计**: device_id 是从 rental.device_id 复制而来的冗余字段，便于查询设备验货历史
- **查询示例**:
  ```python
  # 查询某个设备的所有验货记录
  device = Device.query.get(2001)
  inspections = device.inspection_records
  ```

### 3. InspectionRecord ↔ InspectionCheckItem（一对多）

- **关系**: 一个验货记录包含多个检查项（5-15 个）
- **外键**: `InspectionCheckItem.inspection_record_id → InspectionRecord.id`
- **级联删除**: 验货记录删除时，关联的检查项自动删除（CASCADE）
- **查询示例**:
  ```python
  # 查询某个验货记录的所有检查项
  inspection = InspectionRecord.query.get(456)
  check_items = inspection.check_items  # 按 item_order 排序
  ```

---

## 验货清单生成逻辑

### 检查项生成规则

根据租赁记录的内容，动态生成检查项列表：

```python
def generate_check_items(rental: Rental) -> list[dict]:
    """
    根据租赁记录生成检查项列表
    
    Args:
        rental: Rental 对象
        
    Returns:
        list[dict]: 检查项列表，每项包含 item_name 和 item_order
    """
    check_items = []
    order = 0
    
    # 1. 基础检查项（固定 5 项）
    base_items = [
        "手机,镜头无严重磕碰",
        "摄像头各焦段无白色十字",
        "镜头镜片清晰,无雾无破裂",
        "镜头拆装顺滑",
        "充电头和充电线"
    ]
    for item_name in base_items:
        check_items.append({
            'item_name': item_name,
            'item_order': order
        })
        order += 1
    
    # 2. 手柄检查项（条件性）
    if rental.includes_handle:
        check_items.append({
            'item_name': '手柄',
            'item_order': order
        })
        order += 1
    
    # 3. 镜头支架检查项（条件性）
    if rental.includes_lens_mount:
        check_items.append({
            'item_name': '镜头支架',
            'item_order': order
        })
        order += 1
    
    # 4. 个性化附件检查项（动态）
    for accessory in rental.accessories:
        if not accessory.is_bundled:  # 只添加非配套附件
            check_items.append({
                'item_name': accessory.name,
                'item_order': order
            })
            order += 1
    
    # 5. 代传照片检查项（条件性）
    if rental.photo_transfer:
        check_items.append({
            'item_name': '代传照片',
            'item_order': order
        })
        order += 1
    
    return check_items
```

### 验货状态计算逻辑

```python
def calculate_inspection_status(inspection_record: InspectionRecord) -> str:
    """
    根据检查项勾选情况计算验货状态
    
    Args:
        inspection_record: InspectionRecord 对象
        
    Returns:
        str: 'normal' 或 'abnormal'
    """
    if not inspection_record.check_items:
        return 'abnormal'
    
    # 所有检查项都已勾选 → 验机正常
    all_checked = all(item.is_checked for item in inspection_record.check_items)
    
    return 'normal' if all_checked else 'abnormal'
```

---

## 数据完整性约束

### 1. 外键约束

```sql
ALTER TABLE inspection_record
  ADD CONSTRAINT fk_inspection_rental
  FOREIGN KEY (rental_id) REFERENCES rental(id);

ALTER TABLE inspection_record
  ADD CONSTRAINT fk_inspection_device
  FOREIGN KEY (device_id) REFERENCES device(id);

ALTER TABLE inspection_check_item
  ADD CONSTRAINT fk_check_item_inspection
  FOREIGN KEY (inspection_record_id) REFERENCES inspection_record(id)
  ON DELETE CASCADE;
```

### 2. 业务约束

- **非空约束**: `InspectionRecord.rental_id`, `InspectionRecord.device_id`, `InspectionCheckItem.item_name` 不能为空
- **状态枚举**: `InspectionRecord.status` 只能是 'normal' 或 'abnormal'
- **默认值**: `InspectionCheckItem.is_checked` 默认为 `False`

---

## 示例数据

### 示例 1: 完整验货记录

```python
# 租赁记录
rental = Rental(
    id=123,
    device_id=2001,
    customer_name='张三',
    customer_phone='13800138000',
    includes_handle=True,
    includes_lens_mount=True,
    photo_transfer=True
)

# 验货记录
inspection = InspectionRecord(
    rental_id=123,
    device_id=2001,
    status='normal',
    created_at=datetime(2026, 1, 4, 14, 30, 0)
)

# 验货检查项（8 项）
check_items = [
    InspectionCheckItem(item_name='手机,镜头无严重磕碰', is_checked=True, item_order=0),
    InspectionCheckItem(item_name='摄像头各焦段无白色十字', is_checked=True, item_order=1),
    InspectionCheckItem(item_name='镜头镜片清晰,无雾无破裂', is_checked=True, item_order=2),
    InspectionCheckItem(item_name='镜头拆装顺滑', is_checked=True, item_order=3),
    InspectionCheckItem(item_name='充电头和充电线', is_checked=True, item_order=4),
    InspectionCheckItem(item_name='手柄', is_checked=True, item_order=5),
    InspectionCheckItem(item_name='镜头支架', is_checked=True, item_order=6),
    InspectionCheckItem(item_name='代传照片', is_checked=True, item_order=7),
]
```

### 示例 2: 验货异常记录

```python
# 验货记录
inspection = InspectionRecord(
    rental_id=124,
    device_id=2002,
    status='abnormal',
    created_at=datetime(2026, 1, 4, 15, 0, 0)
)

# 验货检查项（充电线未勾选）
check_items = [
    InspectionCheckItem(item_name='手机,镜头无严重磕碰', is_checked=True, item_order=0),
    InspectionCheckItem(item_name='摄像头各焦段无白色十字', is_checked=True, item_order=1),
    InspectionCheckItem(item_name='镜头镜片清晰,无雾无破裂', is_checked=True, item_order=2),
    InspectionCheckItem(item_name='镜头拆装顺滑', is_checked=True, item_order=3),
    InspectionCheckItem(item_name='充电头和充电线', is_checked=False, item_order=4),  # 未勾选
]
```

---

## 数据迁移计划

### 迁移步骤

1. **创建 inspection_record 表**
2. **创建 inspection_check_item 表**
3. **为 rental 表添加 photo_transfer 字段**
4. **创建索引**
5. **验证外键约束**

### 迁移脚本

详见 Phase 1 输出的 `migrations/versions/xxxx_add_inspection_tables.py`

---

## 性能优化建议

1. **索引优化**: 
   - `inspection_record` 表的 `rental_id`, `device_id`, `status`, `created_at` 字段添加索引
   - 查询时优先使用索引字段

2. **查询优化**:
   - 使用 `lazy='joined'` 预加载关联的 Rental 和 Device 对象
   - 使用 `lazy='select'` 延迟加载 check_items（避免 N+1 查询）

3. **分页查询**:
   - 验货记录列表使用分页（默认每页 20 条）
   - 避免一次性加载所有历史记录

4. **冗余字段**:
   - `device_id` 在 `inspection_record` 中冗余存储，避免关联查询 Rental 表
   - 未来可考虑冗余 `customer_name`、`device_name` 等常用展示字段

---

## 总结

### 新增实体

- ✅ **InspectionRecord**: 验货记录主表，7 个字段
- ✅ **InspectionCheckItem**: 验货检查项表，5 个字段

### 扩展实体

- ✅ **Rental**: 添加 `photo_transfer` 字段

### 关系设计

- ✅ InspectionRecord → Rental (N:1)
- ✅ InspectionRecord → Device (N:1)
- ✅ InspectionRecord → InspectionCheckItem (1:N, CASCADE DELETE)

### 下一步

生成 **API 接口规范**（OpenAPI）和 **快速开发指南**（quickstart.md）
