# 技术调研报告: 简化租赁附件选择

**日期**: 2026-01-04  
**功能**: 001-simplify-rental-accessories  
**调研目的**: 确定实现方案的技术细节和最佳实践

---

## 1. 数据模型设计方案

### 1.1 问题分析

**现状**:
- 附件作为独立的`Rental`记录存储,通过`parent_rental_id`关联到主订单
- 所有附件(手柄、镜头支架、手机支架、三脚架)都需要选择具体的设备ID
- `Device`表有`is_accessory`字段标记设备是否为附件

**需求变化**:
- 手柄和镜头支架已与设备1:1配齐,无需选择具体设备
- 手机支架和三脚架仍需选择具体设备(库存有限)

### 1.2 方案对比

#### 方案A: 在Rental表添加布尔字段(推荐)

**设计**:
```python
class Rental(db.Model):
    # 现有字段...
    
    # 新增字段
    includes_handle = db.Column(db.Boolean, default=False)      # 是否包含手柄
    includes_lens_mount = db.Column(db.Boolean, default=False)  # 是否包含镜头支架
```

**优点**:
- ✅ 简单直观,符合业务语义
- ✅ 查询效率高(单表查询)
- ✅ 向后兼容:历史订单可通过数据迁移脚本从子租赁记录转换
- ✅ 打印和甘特图逻辑改动最小

**缺点**:
- ⚠️ 如果未来需要追踪具体手柄/镜头支架编号,需要schema变更

**迁移策略**:
```python
# 数据迁移伪代码
for rental in Rental.query.filter(Rental.parent_rental_id == None).all():
    # 检查子租赁中是否有手柄
    handle_rental = Rental.query.filter_by(
        parent_rental_id=rental.id
    ).join(Device).filter(Device.name.like('%手柄%')).first()
    
    if handle_rental:
        rental.includes_handle = True
        # 可选:删除旧的子租赁记录
        db.session.delete(handle_rental)
    
    # 镜头支架同理
    # ...
```

#### 方案B: 新增AccessoryConfig表

**设计**:
```python
class AccessoryConfig(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    rental_id = db.Column(db.Integer, db.ForeignKey('rentals.id'))
    has_handle = db.Column(db.Boolean)
    has_lens_mount = db.Column(db.Boolean)
    phone_holder_id = db.Column(db.Integer, db.ForeignKey('devices.id'))
    tripod_id = db.Column(db.Integer, db.ForeignKey('devices.id'))
```

**优点**:
- ✅ 所有附件信息集中管理
- ✅ 易于扩展

**缺点**:
- ❌ 增加表关联,查询复杂度提升
- ❌ 打印和甘特图需要JOIN多个表
- ❌ 过度设计(对于4种附件来说)

#### 方案C: JSON字段存储附件配置

**设计**:
```python
class Rental(db.Model):
    # ...
    accessory_config = db.Column(db.JSON)
    # 示例: {"handle": true, "lens_mount": false, "phone_holder_id": 42}
```

**优点**:
- ✅ 灵活,易于扩展

**缺点**:
- ❌ 无法利用数据库索引
- ❌ 查询和过滤困难
- ❌ 类型安全性差

### 1.3 决策

**选择方案A**: 在`Rental`表添加布尔字段

**理由**:
1. 业务语义清晰:手柄和镜头支架是"包含/不包含"的概念
2. 性能最优:避免额外JOIN
3. 向后兼容:通过迁移脚本处理历史数据
4. 维护成本低:最小化对现有打印/甘特图代码的影响

---

## 2. 前端UI实现最佳实践

### 2.1 Element Plus复选框组件

**组件选择**: `el-checkbox` / `el-checkbox-group`

**示例代码**:
```vue
<template>
  <el-form-item label="配套附件">
    <el-checkbox-group v-model="form.bundledAccessories">
      <el-checkbox label="handle">手柄</el-checkbox>
      <el-checkbox label="lens_mount">镜头支架</el-checkbox>
    </el-checkbox-group>
  </el-form-item>
  
  <el-form-item label="手机支架" prop="phoneHolderId">
    <el-select v-model="form.phoneHolderId" clearable placeholder="选择手机支架(可选)">
      <el-option
        v-for="holder in phoneHolders"
        :key="holder.id"
        :label="`${holder.name} - ${holder.availability_status}`"
        :value="holder.id"
        :disabled="!holder.is_available"
      />
    </el-select>
  </el-form-item>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'

const form = ref({
  bundledAccessories: [] as string[],  // ['handle', 'lens_mount']
  phoneHolderId: null as number | null,
  tripodId: null as number | null
})

// 计算属性:转换为后端需要的格式
const accessoryPayload = computed(() => ({
  includes_handle: form.value.bundledAccessories.includes('handle'),
  includes_lens_mount: form.value.bundledAccessories.includes('lens_mount'),
  phone_holder_id: form.value.phoneHolderId,
  tripod_id: form.value.tripodId
}))
</script>
```

### 2.2 历史订单显示策略

**问题**: 历史订单可能有具体的手柄/镜头支架设备ID,新界面只有复选框

**解决方案**:
```typescript
// 加载历史订单时的数据转换
function loadHistoricalRental(rental: Rental) {
  form.value.bundledAccessories = []
  
  // 检查是否有手柄(通过子租赁或新字段)
  if (rental.includes_handle || rental.child_rentals?.some(c => c.device_name?.includes('手柄'))) {
    form.value.bundledAccessories.push('handle')
  }
  
  // 镜头支架同理
  if (rental.includes_lens_mount || rental.child_rentals?.some(c => c.device_name?.includes('镜头支架'))) {
    form.value.bundledAccessories.push('lens_mount')
  }
  
  // 手机支架和三脚架:提取具体ID
  const phoneHolder = rental.child_rentals?.find(c => c.device_name?.includes('手机支架'))
  form.value.phoneHolderId = phoneHolder?.device_id || null
}
```

### 2.3 TypeScript类型定义

```typescript
// frontend/src/types/rental.ts

export interface AccessorySelection {
  includes_handle: boolean
  includes_lens_mount: boolean
  phone_holder_id: number | null
  tripod_id: number | null
}

export interface RentalFormData {
  device_id: number
  start_date: string
  end_date: string
  customer_name: string
  // ...其他字段
  bundled_accessories: string[]  // UI层使用
  phone_holder_id: number | null
  tripod_id: number | null
}

export interface RentalCreatePayload {
  // ...租赁基本信息
  includes_handle: boolean         // API层使用
  includes_lens_mount: boolean
  accessory_ids: number[]          // 手机支架和三脚架的ID数组
}
```

---

## 3. 后端API设计

### 3.1 创建租赁API调整

**端点**: `POST /api/rentals`

**请求体变更**:
```json
{
  "device_id": 123,
  "start_date": "2026-01-05",
  "end_date": "2026-01-10",
  "customer_name": "张三",
  "customer_phone": "13800138000",
  
  // 新附件字段
  "includes_handle": true,
  "includes_lens_mount": false,
  "accessory_ids": [45, 67]  // 手机支架ID=45, 三脚架ID=67
}
```

**后端处理逻辑**:
```python
def create_rental_with_accessories(data: Dict[str, Any]) -> Tuple[Rental, List[Rental]]:
    # 1. 创建主租赁记录(含布尔字段)
    main_rental = Rental(
        device_id=data['device_id'],
        start_date=data['start_date'],
        end_date=data['end_date'],
        customer_name=data['customer_name'],
        includes_handle=data.get('includes_handle', False),
        includes_lens_mount=data.get('includes_lens_mount', False),
        status='not_shipped'
    )
    db.session.add(main_rental)
    db.session.flush()
    
    # 2. 只为手机支架和三脚架创建子租赁记录
    accessory_rentals = []
    for accessory_id in data.get('accessory_ids', []):
        accessory_device = Device.query.get(accessory_id)
        if accessory_device and accessory_device.is_accessory:
            accessory_rental = Rental(
                device_id=accessory_id,
                customer_name=data['customer_name'],
                start_date=data['start_date'],
                end_date=data['end_date'],
                parent_rental_id=main_rental.id,
                status='not_shipped'
            )
            db.session.add(accessory_rental)
            accessory_rentals.append(accessory_rental)
    
    db.session.commit()
    return main_rental, accessory_rentals
```

### 3.2 查询API调整

**端点**: `GET /api/rentals/{id}`

**响应体变更**:
```json
{
  "id": 1001,
  "device_id": 123,
  "device_name": "设备X200U-001",
  "start_date": "2026-01-05",
  "end_date": "2026-01-10",
  
  // 附件信息
  "includes_handle": true,
  "includes_lens_mount": false,
  "accessories": [
    {
      "id": 45,
      "name": "手机支架-A01",
      "type": "phone_holder"
    },
    {
      "id": 67,
      "name": "三脚架-T05",
      "type": "tripod"
    }
  ]
}
```

---

## 4. 打印服务兼容性

### 4.1 发货单生成

**文件**: `app/services/printing/shipping_slip_image_service.py`

**需要修改的部分**:
```python
def _draw_accessories_section(self, draw, accessories_info):
    """绘制附件清单部分"""
    y_position = self.current_y
    
    # 标题
    draw.text((self.margin, y_position), "附件清单:", font=self.font_bold)
    y_position += self.line_height
    
    # 配套附件(布尔值显示)
    if accessories_info.get('includes_handle'):
        draw.text((self.margin + 20, y_position), "✓ 手柄 (配套)", font=self.font)
        y_position += self.line_height
    
    if accessories_info.get('includes_lens_mount'):
        draw.text((self.margin + 20, y_position), "✓ 镜头支架 (配套)", font=self.font)
        y_position += self.line_height
    
    # 库存附件(显示具体编号)
    for accessory in accessories_info.get('accessories', []):
        text = f"• {accessory['name']} (编号: {accessory['serial_number']})"
        draw.text((self.margin + 20, y_position), text, font=self.font)
        y_position += self.line_height
    
    self.current_y = y_position
```

### 4.2 面单打印

**文件**: `app/services/shipping/waybill_print_service.py`

**评估**: 面单由顺丰API生成,我们只传递打印任务。附件信息不直接体现在面单上,**无需修改**。

但需要确保在调用顺丰API时,备注字段(如有)包含完整的附件信息。

---

## 5. 甘特图显示调整

### 5.1 后端数据格式

**文件**: `app/routes/gantt_api.py`

**调整`GET /api/gantt/data`响应**:
```python
def format_rental_for_gantt(rental: Rental) -> dict:
    # 获取子租赁(仅手机支架和三脚架)
    child_rentals = Rental.query.filter_by(parent_rental_id=rental.id).all()
    accessories_info = []
    
    # 添加配套附件(布尔值)
    if rental.includes_handle:
        accessories_info.append({
            'name': '手柄',
            'type': 'bundled',
            'is_bundled': True
        })
    
    if rental.includes_lens_mount:
        accessories_info.append({
            'name': '镜头支架',
            'type': 'bundled',
            'is_bundled': True
        })
    
    # 添加库存附件(具体设备)
    for child_rental in child_rentals:
        if child_rental.device:
            accessories_info.append({
                'id': child_rental.device.id,
                'name': child_rental.device.name,
                'type': 'inventory',
                'is_bundled': False
            })
    
    return {
        'id': rental.id,
        'device_name': rental.device.name,
        'start_date': rental.start_date.isoformat(),
        'end_date': rental.end_date.isoformat(),
        'accessories': accessories_info
    }
```

### 5.2 前端甘特图显示

**文件**: `frontend/src/components/GanttRow.vue`

**工具提示显示附件**:
```vue
<template>
  <div class="gantt-row">
    <el-tooltip placement="top">
      <template #content>
        <div>
          <p><strong>订单 #{{ rental.id }}</strong></p>
          <p>客户: {{ rental.customer_name }}</p>
          <p>附件:</p>
          <ul>
            <li v-for="acc in rental.accessories" :key="acc.name">
              {{ acc.name }}
              <el-tag v-if="acc.is_bundled" size="small">配套</el-tag>
            </li>
          </ul>
        </div>
      </template>
      <div class="rental-bar">{{ rental.device_name }}</div>
    </el-tooltip>
  </div>
</template>
```

---

## 6. 数据库迁移策略

### 6.1 迁移脚本设计

**文件**: `migrations/versions/[timestamp]_add_bundled_accessory_flags.py`

```python
"""添加配套附件标记字段

Revision ID: abc123def456
Revises: previous_revision
Create Date: 2026-01-04 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

def upgrade():
    # 1. 添加新字段
    op.add_column('rentals', sa.Column('includes_handle', sa.Boolean(), nullable=False, server_default='0'))
    op.add_column('rentals', sa.Column('includes_lens_mount', sa.Boolean(), nullable=False, server_default='0'))
    
    # 2. 数据迁移:从子租赁推断
    connection = op.get_bind()
    
    # 查找所有主订单
    main_rentals = connection.execute(
        sa.text("SELECT id FROM rentals WHERE parent_rental_id IS NULL")
    ).fetchall()
    
    for (rental_id,) in main_rentals:
        # 检查是否有手柄子租赁
        handle_exists = connection.execute(
            sa.text("""
                SELECT COUNT(*) FROM rentals r
                JOIN devices d ON r.device_id = d.id
                WHERE r.parent_rental_id = :rental_id
                AND d.name LIKE '%手柄%'
            """),
            {'rental_id': rental_id}
        ).scalar()
        
        if handle_exists > 0:
            connection.execute(
                sa.text("UPDATE rentals SET includes_handle = 1 WHERE id = :rental_id"),
                {'rental_id': rental_id}
            )
        
        # 镜头支架同理
        lens_mount_exists = connection.execute(
            sa.text("""
                SELECT COUNT(*) FROM rentals r
                JOIN devices d ON r.device_id = d.id
                WHERE r.parent_rental_id = :rental_id
                AND d.name LIKE '%镜头支架%'
            """),
            {'rental_id': rental_id}
        ).scalar()
        
        if lens_mount_exists > 0:
            connection.execute(
                sa.text("UPDATE rentals SET includes_lens_mount = 1 WHERE id = :rental_id"),
                {'rental_id': rental_id}
            )
    
    # 3. 可选:删除旧的手柄/镜头支架子租赁记录
    # (建议先保留,观察一段时间后再删除)
    # connection.execute(sa.text("""
    #     DELETE r FROM rentals r
    #     JOIN devices d ON r.device_id = d.id
    #     WHERE r.parent_rental_id IS NOT NULL
    #     AND (d.name LIKE '%手柄%' OR d.name LIKE '%镜头支架%')
    # """))

def downgrade():
    op.drop_column('rentals', 'includes_lens_mount')
    op.drop_column('rentals', 'includes_handle')
```

### 6.2 迁移验证

**验证SQL**:
```sql
-- 检查迁移后的数据一致性
SELECT 
    r.id,
    r.includes_handle,
    r.includes_lens_mount,
    COUNT(CASE WHEN d.name LIKE '%手柄%' THEN 1 END) as handle_count,
    COUNT(CASE WHEN d.name LIKE '%镜头支架%' THEN 1 END) as lens_mount_count
FROM rentals r
LEFT JOIN rentals child ON child.parent_rental_id = r.id
LEFT JOIN devices d ON child.device_id = d.id
WHERE r.parent_rental_id IS NULL
GROUP BY r.id
HAVING 
    (r.includes_handle = 1 AND handle_count = 0) OR
    (r.includes_handle = 0 AND handle_count > 0) OR
    (r.includes_lens_mount = 1 AND lens_mount_count = 0) OR
    (r.includes_lens_mount = 0 AND lens_mount_count > 0);
```

---

## 7. 测试策略

### 7.1 后端单元测试

**文件**: `tests/unit/test_rental_service.py`

```python
def test_create_rental_with_bundled_accessories():
    """测试创建带配套附件的租赁"""
    data = {
        'device_id': 1,
        'start_date': date(2026, 1, 5),
        'end_date': date(2026, 1, 10),
        'customer_name': '测试客户',
        'includes_handle': True,
        'includes_lens_mount': False,
        'accessory_ids': []
    }
    
    rental, accessory_rentals = create_rental_with_accessories(data)
    
    assert rental.includes_handle == True
    assert rental.includes_lens_mount == False
    assert len(accessory_rentals) == 0  # 没有选择库存附件

def test_create_rental_with_mixed_accessories():
    """测试同时包含配套附件和库存附件"""
    data = {
        # ...
        'includes_handle': True,
        'includes_lens_mount': True,
        'accessory_ids': [45, 67]  # 手机支架和三脚架
    }
    
    rental, accessory_rentals = create_rental_with_accessories(data)
    
    assert rental.includes_handle == True
    assert len(accessory_rentals) == 2
```

### 7.2 前端组件测试

**文件**: `frontend/tests/unit/RentalAccessorySelector.spec.ts`

```typescript
import { mount } from '@vue/test-utils'
import RentalAccessorySelector from '@/components/rental/RentalAccessorySelector.vue'

describe('RentalAccessorySelector', () => {
  it('显示手柄和镜头支架复选框', () => {
    const wrapper = mount(RentalAccessorySelector)
    
    expect(wrapper.find('[label="handle"]').exists()).toBe(true)
    expect(wrapper.find('[label="lens_mount"]').exists()).toBe(true)
  })
  
  it('手机支架显示为下拉选择', () => {
    const wrapper = mount(RentalAccessorySelector, {
      props: {
        phoneHolders: [
          { id: 1, name: '手机支架-A01', is_available: true }
        ]
      }
    })
    
    expect(wrapper.find('el-select').exists()).toBe(true)
  })
  
  it('正确加载历史订单数据', async () => {
    const wrapper = mount(RentalAccessorySelector, {
      props: {
        historicalRental: {
          includes_handle: true,
          includes_lens_mount: false,
          accessories: [{ id: 45, name: '手机支架-A01' }]
        }
      }
    })
    
    await wrapper.vm.$nextTick()
    
    // 手柄复选框应该被勾选
    expect(wrapper.vm.bundledAccessories).toContain('handle')
    // 镜头支架不勾选
    expect(wrapper.vm.bundledAccessories).not.toContain('lens_mount')
  })
})
```

### 7.3 端到端集成测试

**测试用例**:
1. 创建新订单,勾选手柄和镜头支架,验证保存成功
2. 编辑订单,修改附件选择,验证更新成功
3. 打印发货单,验证附件信息正确显示
4. 查看甘特图,验证配套附件和库存附件都正确显示
5. 加载历史订单,验证数据兼容性

---

## 8. 风险评估与缓解

| 风险 | 影响 | 概率 | 缓解措施 |
|------|------|------|----------|
| 数据迁移失败导致历史订单信息丢失 | 高 | 低 | 1. 迁移前完整备份数据库<br>2. 在测试环境充分验证<br>3. 保留旧的子租赁记录作为备份 |
| 打印服务显示附件信息不完整 | 中 | 中 | 1. 详细的打印服务集成测试<br>2. 灰度发布,先用内部订单测试 |
| 前端UI变更导致用户操作困惑 | 低 | 中 | 1. 提供简短的功能说明提示<br>2. 保持视觉一致性 |
| 甘特图性能下降(因额外字段) | 低 | 低 | 1. 查询优化<br>2. 添加数据库索引(如需要) |

---

## 9. 性能优化建议

### 9.1 数据库索引

```sql
-- 如果经常根据附件类型筛选订单
CREATE INDEX idx_rentals_includes_handle ON rentals(includes_handle);
CREATE INDEX idx_rentals_includes_lens_mount ON rentals(includes_lens_mount);

-- 子订单查询优化(现有,应已存在)
CREATE INDEX idx_rentals_parent_id ON rentals(parent_rental_id);
```

### 9.2 前端性能

- 使用`computed`缓存附件可用性检查结果
- 避免在循环中调用API(批量查询附件状态)
- 使用虚拟滚动(如果附件列表很长)

---

## 10. 部署计划

### 10.1 部署步骤

1. **准备阶段**:
   - [ ] 备份生产数据库
   - [ ] 在staging环境部署并测试

2. **数据迁移**:
   - [ ] 执行数据库迁移脚本
   - [ ] 验证迁移结果

3. **代码部署**:
   - [ ] 部署后端代码(先部署,保持API向后兼容)
   - [ ] 部署前端代码

4. **验证**:
   - [ ] 冒烟测试:创建新订单
   - [ ] 验证打印功能
   - [ ] 检查甘特图显示

5. **监控**:
   - [ ] 监控API错误率
   - [ ] 监控打印服务调用日志
   - [ ] 收集用户反馈

### 10.2 回滚计划

如果出现严重问题:
1. 回滚前端代码到旧版本
2. 回滚后端代码到旧版本
3. 如果数据迁移有问题,从备份恢复(保留新创建的订单数据)

---

## 11. 未来扩展考虑

### 11.1 短期(3个月内)
- 监控新UI的用户接受度
- 收集对附件管理的其他需求

### 11.2 中期(6-12个月)
- 如果三脚架也实现1:1配齐,类似转换为布尔字段
- 附件库存预警功能

### 11.3 长期(1年以上)
- 如果需要追踪具体手柄/镜头支架编号(如维修记录),考虑:
  - 方案1:添加`handle_device_id`字段,但保持UI简洁
  - 方案2:在设备表添加`paired_main_device_id`字段,建立1:1关联

---

## 12. 技术决策总结

| 决策项 | 选择 | 理由 |
|--------|------|------|
| 数据模型设计 | 在Rental表添加布尔字段 | 简单、性能好、向后兼容 |
| 前端UI组件 | Element Plus的`el-checkbox` | 符合现有技术栈,用户熟悉 |
| 历史数据处理 | 迁移脚本转换 + 保留旧记录 | 确保数据安全,可回溯 |
| API设计 | 扩展现有`POST /api/rentals` | 最小化API变更 |
| 打印服务 | 发货单调整,面单不变 | 面单由顺丰生成,无需干预 |
| 甘特图显示 | 区分配套附件和库存附件 | 信息清晰,符合业务语义 |
| 测试策略 | 单元测试 + 集成测试 + E2E测试 | 全面覆盖 |
| 部署方式 | 先后端后前端,灰度发布 | 降低风险 |

---

**研究完成日期**: 2026-01-04  
**审核状态**: 待审核  
**后续行动**: 进入Phase 1设计阶段,生成data-model.md和API合约
