# 启用批量发货的多选功能并显示设备上一单状态

## Why

当前批量发货流程存在两个主要问题:

### 问题1: 强制全部发货,缺乏灵活性

当前批量发货要求用户必须将**所有未发货的订单**一次性下单发货。这种设计存在以下问题:

1. **缺乏灵活性**: 用户无法选择部分订单发货,必须全部发货或都不发货
2. **业务场景受限**: 实际场景中,用户可能只想发货部分订单(例如:库存不足、部分订单需要延后发货、分批次发货等)
3. **用户体验差**: 强制全部发货的设计不符合用户的实际工作流程
4. **已有技术基础**: 后端 `/api/shipping-batch/schedule` API 已经支持传入 `rental_ids` 数组,前端只需要添加多选功能即可

### 问题2: 无法判断设备是否在库,存在发货风险

当前批量发货界面无法显示设备的上一单状态,用户可能在设备还未归还的情况下发货同一设备,导致:

1. **发货错误**: 设备还在客户手中,无法发出新订单
2. **库存混乱**: 用户需要手动检查每个设备的历史订单,效率低
3. **风险提示缺失**: 系统没有警示用户"设备可能不在库"的信息

实际上,后端API已经设计为接受 `rental_ids` 数组,可以处理任意数量的租赁订单。当前问题在于前端硬编码为"全选所有未发货订单",没有提供用户选择和风险提示的界面。

## What Changes

### 核心改变1: 添加订单多选功能

**将批量发货从"强制全选"改为"用户多选"**:

1. **添加表格多选功能**:
   - 在 `BatchShippingView.vue` 的订单表格中添加多选列(checkbox)
   - 只允许选择状态为 `not_shipped` 的订单(已发货和已预约发货的订单不可选)
   - 提供"全选当前未发货订单"的快捷操作

2. **更新预约发货按钮行为**:
   - 将"预约发货 ({{ unshippedCount }})"改为"预约发货 ({{ selectedCount }})"
   - 按钮仅在至少选择1个订单时可用
   - 点击按钮时,仅对**用户选中的订单**调用API,而非所有未发货订单

3. **保留现有API不变**:
   - 后端 `/api/shipping-batch/schedule` API无需修改
   - 继续接收 `rental_ids` 数组参数
   - 前端只改变传入的 `rental_ids` 来源(从"所有未发货"改为"用户选中")

### 核心改变2: 显示设备上一单状态

**在批量发货列表中显示每个设备的上一单状态**:

1. **后端API增强** (`/api/rentals/by-ship-date`):
   - 为每个租赁记录查询该设备的上一单(根据 `ship_out_time` 排序,取当前订单之前的最近一单)
   - 返回上一单的状态: `previous_rental_status` 和 `previous_rental_completed` (布尔值,表示上一单是否已结束)
   - 已结束状态包括: `completed`, `cancelled`, `returned`
   - 未结束状态包括: `not_shipped`, `scheduled_for_shipping`, `shipped`

2. **前端UI显示**:
   - 在订单表格中添加"设备状态"列
   - 如果上一单已结束: 显示"✓ 设备在库"(绿色)
   - 如果上一单未结束: 显示"⚠ 上一单未结束"(红色文字),提示用户设备可能不在库
   - 如果是首单(无上一单): 显示"-"或"首单"

3. **用户体验**:
   - 用户可以快速识别哪些订单可能存在发货风险
   - 红色警告帮助用户避免发货错误
   - 不强制阻止发货,由用户自行判断(可能存在设备已归还但上一单未更新状态的情况)

### 前端变更细节

**BatchShippingView.vue 修改**:

```vue
<!-- 在 el-table 中添加 selection 列 -->
<el-table
  :data="rentals"
  @selection-change="handleSelectionChange"
  :row-key="(row) => row.id"
>
  <el-table-column
    type="selection"
    width="55"
    :selectable="isSelectableRow"
  />

  <!-- 新增:设备状态列 -->
  <el-table-column label="设备状态" width="120">
    <template #default="{ row }">
      <span v-if="!row.has_previous_rental">-</span>
      <el-tag v-else-if="row.previous_rental_completed" type="success" size="small">
        ✓ 设备在库
      </el-tag>
      <el-tag v-else type="danger" size="small">
        ⚠ 上一单未结束
      </el-tag>
    </template>
  </el-table-column>

  <!-- 其他列... -->
</el-table>

<!-- 更新按钮显示 -->
<el-button
  @click="showScheduleDialog"
  type="warning"
  :disabled="selectedRentals.length === 0"
>
  <el-icon><Clock /></el-icon>
  预约发货 ({{ selectedRentals.length }})
</el-button>
```

**新增数据和方法**:
```typescript
// 新增状态
const selectedRentals = ref<any[]>([])

// 多选变化处理
const handleSelectionChange = (selection: any[]) => {
  selectedRentals.value = selection
}

// 判断行是否可选(仅未发货的订单可选)
const isSelectableRow = (row: any) => {
  return row.status !== 'shipped' && row.status !== 'scheduled_for_shipping'
}

// 修改 confirmSchedule 使用选中的订单
const confirmSchedule = async () => {
  const rentalIds = selectedRentals.value.map(r => r.id)
  // ... API调用
}
```

### 后端变更细节

**app/handlers/rental_handlers.py 修改** (`handle_get_rentals_by_ship_date` 方法):

```python
# 构建响应数据,包含上一单状态
rentals_data = []
for rental in rentals:
    rental_dict = rental.to_dict()

    # 查询该设备的上一单(当前订单发货时间之前的最近一单)
    previous_rental = Rental.query.filter(
        Rental.device_id == rental.device_id,
        Rental.ship_out_time < rental.ship_out_time,
        Rental.parent_rental_id.is_(None)
    ).order_by(Rental.ship_out_time.desc()).first()

    if previous_rental:
        rental_dict['has_previous_rental'] = True
        rental_dict['previous_rental_status'] = previous_rental.status
        # 已结束状态: completed, cancelled, returned
        rental_dict['previous_rental_completed'] = previous_rental.status in ['completed', 'cancelled', 'returned']
    else:
        rental_dict['has_previous_rental'] = False
        rental_dict['previous_rental_status'] = None
        rental_dict['previous_rental_completed'] = None

    rentals_data.append(rental_dict)
```

### 用户体验改进

- ✅ **更灵活**: 用户可以自由选择要发货的订单
- ✅ **更符合实际业务**: 支持分批发货、延后发货等场景
- ✅ **更安全**: 显示设备状态,避免发货错误
- ✅ **更直观**: 红色警告快速识别风险订单
- ✅ **保持一致性**: UI模式与其他管理系统的表格多选一致
- ✅ **向后兼容**: 用户仍可"全选"实现原有的批量发货行为

### 受影响的组件

**前端修改**:
- `frontend/src/views/BatchShippingView.vue`: 添加多选功能 + 设备状态列

**后端修改**:
- `app/handlers/rental_handlers.py`: 在 `handle_get_rentals_by_ship_date` 中添加上一单状态查询

## Impact

### 受影响的规格

- **batch-print-ui** (可能需要修改): 如果 batch-print-ui 规格涵盖批量发货UI,需要添加多选功能的要求
- 可能需要创建新规格 **batch-shipping-ui**: 如果当前没有专门定义批量发货UI的规格,可以新建

### 用户工作流变化

**之前**:
1. 选择日期范围 → 预览订单
2. 点击"预约发货"(自动选中所有未发货订单)
3. 设置预约时间 → 确认
4. 无法判断设备是否在库

**之后**:
1. 选择日期范围 → 预览订单
2. **查看"设备状态"列,识别风险订单**(新增)
3. **在表格中勾选要发货的订单**(新增步骤)
4. 点击"预约发货" (仅对选中订单生效)
5. 设置预约时间 → 确认

### 向后兼容性

**NON-BREAKING CHANGE**:
- API响应结构扩展(新增字段),不影响现有代码
- 用户可通过"全选"实现原有行为
- 新增功能为可选操作,不强制使用

### 性能考虑

- **查询开销**: 每个订单需要额外查询一次上一单,可能增加数据库负载
- **优化方案**:
  - 使用单次JOIN查询替代循环查询
  - 对 `device_id` + `ship_out_time` 添加复合索引
  - 批量发货列表通常不超过100条,性能影响可控

## Alternatives Considered

### 方案1: 添加"自定义筛选条件"而非多选
- **优点**: 可基于规则批量选择(例如:按客户、按设备类型)
- **缺点**: 实现复杂,需要额外的筛选UI;不如直接勾选直观
- **结论**: 未采用。多选是最直接、最易用的方案

### 方案2: 分页批量发货(每次只发一页)
- **优点**: 实现简单,不需要多选组件
- **缺点**: 用户无法跨页选择,灵活性差
- **结论**: 未采用。不满足"部分订单发货"的核心需求

### 方案3: 保持现状,在"单个订单详情"中添加发货按钮
- **优点**: 不影响批量发货流程
- **缺点**: 无法满足"批量但非全部"的场景,用户需要逐个操作
- **结论**: 未采用。这是另一个独立功能(见 `add-single-rental-ship-button`),不解决批量场景问题

### 方案4: 强制阻止发货上一单未结束的订单
- **优点**: 避免发货错误
- **缺点**: 可能存在误判(上一单已归还但未更新状态);限制用户操作灵活性
- **结论**: 未采用。改为提示警告,由用户自行判断

### 方案5: 在后端批量查询所有设备的上一单(JOIN优化)
- **优点**: 减少数据库查询次数
- **缺点**: 实现复杂度高,需要SQL优化
- **结论**: 可在后续优化时采用。当前方案先实现功能,性能可控

## Dependencies

- Element Plus 表格组件的 `type="selection"` 功能(已存在)
- 现有的 `/api/shipping-batch/schedule` API(已实现)
- SQLAlchemy ORM 查询功能(已存在)

## Risks & Mitigations

**风险1: 用户误以为"预览订单"就是选中订单**
- **缓解**: 使用明确的视觉反馈(checkbox),按钮显示选中数量
- **缓解**: 预约对话框中显示"将为 X 个选中的订单预约发货"

**风险2: 用户可能忘记选择订单直接点击预约**
- **缓解**: 当 `selectedRentals.length === 0` 时禁用"预约发货"按钮
- **缓解**: 按钮文本显示选中数量 `(0)`,提示用户需要先选择

**风险3: 用户希望"记住上次的选择"(跨页面)**
- **缓解**: 当前版本不支持,可在后续迭代中考虑
- **缓解**: 使用 `:row-key` 确保翻页后选择状态正确

**风险4: 上一单状态可能不准确(已归还但未更新)**
- **缓解**: 使用警告而非强制阻止,由用户判断
- **缓解**: UI显示"上一单未结束"而非"设备不在库",避免误导

**风险5: 查询上一单可能影响性能**
- **缓解**: 批量发货列表通常不超过100条,循环查询可控
- **缓解**: 后续可优化为JOIN查询
- **缓解**: 考虑添加数据库索引: `(device_id, ship_out_time)`

## Related Changes

- 与 `simplify-batch-shipping-flow` 互补: 该变更简化了流程,本变更增加了灵活性和安全性
- 与 `add-single-rental-ship-button` 独立: 单个订单发货是不同的场景
- 可能影响 `batch-print-ui` 规格: 如果该规格定义了批量操作UI模式

## Out of Scope

以下功能**不在**本次变更范围内:

- 批量打印面单的多选功能(另一个独立功能)
- "记住选择状态"或"选择模板"等高级功能
- 强制阻止发货上一单未结束的订单(改为警告提示)
- 批量发货的其他优化(如:批量修改快递类型)
- 查询性能优化(JOIN查询):当前循环查询,后续优化
- 显示上一单的详细信息(客户、时间等):仅显示状态
