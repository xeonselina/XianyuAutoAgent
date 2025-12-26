# Implementation Tasks

## 1. Backend - Add Previous Rental Status
- [x] 1.1 修改 `app/handlers/rental_handlers.py` 中的 `handle_get_rentals_by_ship_date` 方法
- [x] 1.2 为每个租赁记录查询该设备的上一单(根据 `ship_out_time` 倒序,取第一条)
- [x] 1.3 添加返回字段: `has_previous_rental`, `previous_rental_status`, `previous_rental_completed`
- [x] 1.4 测试API响应包含上一单状态信息

## 2. Database Optimization (Optional but Recommended)
- [ ] 2.1 检查 `rentals` 表是否存在 `(device_id, ship_out_time)` 复合索引
- [ ] 2.2 如果不存在,创建索引以优化上一单查询性能
- [ ] 2.3 测试索引创建后的查询性能

## 3. Frontend - Add Selection Column
- [x] 3.1 在 `frontend/src/views/BatchShippingView.vue` 的 `<el-table>` 中添加 `type="selection"` 列
- [x] 3.2 添加 `@selection-change="handleSelectionChange"` 事件处理
- [x] 3.3 添加 `:row-key="(row) => row.id"` 属性
- [x] 3.4 实现 `handleSelectionChange` 方法,保存选中的租赁记录到 `selectedRentals` ref
- [x] 3.5 实现 `isSelectableRow` 方法,仅允许选择 `status !== 'shipped' && status !== 'scheduled_for_shipping'` 的行

## 4. Frontend - Update Scheduled Shipment Button
- [x] 4.1 修改"预约发货"按钮的 `:disabled` 属性为 `selectedRentals.length === 0`
- [x] 4.2 修改按钮文本为 `预约发货 ({{ selectedRentals.length }})`
- [x] 4.3 更新 `showScheduleDialog` 中的提示文本,显示选中订单数量
- [x] 4.4 修改 `confirmSchedule` 方法,使用 `selectedRentals.value.map(r => r.id)` 替代原来的过滤逻辑

## 5. Frontend - Add Device Status Column
- [x] 5.1 在订单表格中添加"设备状态"列,位于"状态"列之后
- [x] 5.2 使用条件渲染显示设备状态:
  - [x] 5.2.1 无上一单: 显示 "-"
  - [x] 5.2.2 上一单已结束: 显示绿色 `<el-tag type="success">✓ 设备在库</el-tag>`
  - [x] 5.2.3 上一单未结束: 显示红色 `<el-tag type="danger">⚠ 上一单未结束</el-tag>`
- [x] 5.3 测试不同场景下的UI显示是否正确

## 6. Frontend - Remove Old Logic
- [x] 6.1 删除 `hasUnshipped` computed(不再需要,按钮禁用状态基于 `selectedRentals`)
- [x] 6.2 删除 `unshippedCount` computed(不再需要,按钮显示 `selectedRentals.length`)
- [x] 6.3 检查是否有其他地方依赖这两个computed,如有则一并修改

## 7. Testing
- [ ] 7.1 测试多选功能:勾选部分订单,验证只有选中的订单被发货
- [ ] 7.2 测试选择限制:验证已发货和已预约发货的订单无法选择
- [ ] 7.3 测试设备状态显示:
  - [ ] 7.3.1 首单订单显示 "-"
  - [ ] 7.3.2 上一单为 `completed` 显示绿色"设备在库"
  - [ ] 7.3.3 上一单为 `shipped` 显示红色"上一单未结束"
- [ ] 7.4 测试按钮状态:未选择任何订单时按钮禁用,选择后启用
- [ ] 7.5 测试预约对话框:验证显示的订单数量正确
- [ ] 7.6 端到端测试:完整的选择→预约→确认流程

## 8. Documentation (Optional)
- [ ] 8.1 更新用户文档,说明新的多选功能
- [ ] 8.2 说明"设备状态"列的含义和注意事项
- [ ] 8.3 添加截图或示例

## Progress Tracking
Total: 26 tasks
Completed: 20
Remaining: 6 (3 optional database optimization tasks + 3 optional documentation tasks)

## Implementation Summary

### Completed Changes

**Backend** (`app/handlers/rental_handlers.py`):
- Modified `handle_get_rentals_by_ship_date` to query previous rental for each device
- Added fields: `has_previous_rental`, `previous_rental_status`, `previous_rental_completed`
- Completed statuses: `completed`, `cancelled`, `returned`

**Frontend** (`frontend/src/views/BatchShippingView.vue`):
- Added selection column with checkbox to el-table
- Added `selectedRentals` state to track user selection
- Added `handleSelectionChange` and `isSelectableRow` methods
- Updated "预约发货" button to show selected count and disable when none selected
- Added "设备状态" column showing device availability status
- Removed `hasUnshipped` and `unshippedCount` computed properties
- Updated `confirmSchedule` to use selected rentals instead of all unshipped

### Testing Notes

The core functionality is implemented. Testing tasks (7.x) should be performed manually to verify:
- Multi-selection works correctly
- Only selectable rows can be checked
- Device status displays correctly based on previous rental
- Button state reflects selection
- Dialog shows correct count
- API is called with correct rental IDs

Database optimization (2.x) and documentation (8.x) tasks are optional enhancements.
