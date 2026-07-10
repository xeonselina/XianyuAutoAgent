---
name: fix-gantt-lifecycle-status-bugs
overview: 修复两个 bug：(1) 预定设备下拉框的可用性标签未判断设备 lifecycle_status 是否为 active；(2) 甘特图表头每日闲置统计未过滤非 active 生命周期的设备。两个 bug 的根因都是只检查了 device.status（online/offline）而忽略了 lifecycle_status（active/sold/damaged/decommissioned/retired）。
todos:
  - id: fix-availability-check
    content: "修改 useAvailabilityCheck.ts: checkDevicesAvailability 中前置过滤非 active 设备"
    status: completed
  - id: fix-booking-dialog-display
    content: "修改 BookingDialog.vue: 非 active 设备显示对应生命周期状态标签"
    status: completed
    dependencies:
      - fix-availability-check
  - id: fix-inventory-service
    content: "修改 inventory_service.py: get_available_devices 排除非 active 生命周期设备"
    status: completed
  - id: fix-find-available-slot
    content: "修改 gantt_service.py: find_available_slot 查询增加 lifecycle_status 过滤"
    status: completed
---

## 用户需求

修复甘特图中 2 个与设备生命周期状态（`lifecycle_status`）判断缺失相关的 bug：

### Bug 1: 预定设备下拉框的可用性状态未判断 lifecycle_status

在库存管理-甘特图中，点击"预定设备"打开预定对话框后，设备下拉框中每台设备显示"可用"或"档期不可用"标签。当前判断逻辑仅检查档期冲突（通过 API 调用 `/api/rentals/check-conflict`），但忽略了设备的 `lifecycle_status`。导致已售出（sold）、已损坏（damaged）、已停用（decommissioned）、已退役（retired）的设备，只要档期不冲突就显示为"可用"，用户可能误选这些不可用设备进行预定。

### Bug 2: 甘特图表头每日"闲置"统计数未过滤非 active 设备

甘特图表头每个日期下方显示当日"闲置"设备数（`available_count`），该数据由后端 `get_daily_statistics` 方法通过 `InventoryService.get_available_devices()` 计算。该方法仅排除了 `status == 'offline'` 的设备，未排除 `lifecycle_status` 非 `active` 的设备，导致已售出、已损坏、已停用、已退役的设备也被计入闲置数量。

## Tech Stack

- 后端: Python (Flask) + SQLAlchemy
- 前端: Vue 3 (Composition API) + TypeScript + Element Plus
- 数据模型: Device 模型已有 `lifecycle_status` 字段和辅助方法 `is_excluded_from_statistics()` / `is_in_service()`

## Implementation Approach

### Bug 1 修复: 预定设备下拉框可用性判断

**前端优先策略**: 在 `useAvailabilityCheck.ts` 的 `checkDevicesAvailability` 方法中，于调用后端冲突检测 API 之前，先按 `lifecycle_status` 筛选。非 `active` 状态的设备直接归入不可用列表，不发起冲突检测请求，既修复 bug 又减少不必要的 API 调用（性能优化）。

同时在 `BookingDialog.vue` 中优化显示：非 active 设备显示对应的生命周期状态标签（如"已售出"），而非笼统的"档期不可用"。

**后端补充**: 在 `gantt_service.py` 的 `find_available_slot` 方法中，设备查询添加 `Device.lifecycle_status == 'active'` 过滤，确保后端查找档期也不返回非 active 设备。

### Bug 2 修复: 闲置统计数排除非 active 设备

在 `inventory_service.py` 的 `get_available_devices` 方法中，第41行处将 `if device.status == 'offline': continue` 扩展为同时检查 `lifecycle_status`，复用 Device 模型已有的 `is_excluded_from_statistics()` 方法，保持代码 DRY。

### Performance Considerations

- Bug 1 前端修复减少了非 active 设备的冲突检测 API 调用（N 次请求减少）
- Bug 2 后端修复在遍历阶段提前过滤，无额外查询开销
- 两者均复用已有的 `is_excluded_from_statistics()` 方法，无新增复杂度

## Implementation Notes

- `useAvailabilityCheck.ts` 中 `checkDevicesAvailability` 接收的 `devices` 参数已包含 `lifecycle_status` 字段（来自 `useDeviceManagement` 加载的设备数据），可直接访问
- Device 模型的 `is_excluded_from_statistics()` 方法（device.py 第89-103行）已封装排除逻辑，直接复用
- `find_available_slot` 中后端查询使用 SQLAlchemy filter，添加 `Device.lifecycle_status == 'active'` 条件即可
- 修改不影响现有 API 接口签名，仅改变返回结果的筛选逻辑，向后兼容

## Directory Structure

```
InventoryManager/
├── app/
│   ├── services/
│   │   ├── inventory_service.py      # [MODIFY] get_available_devices() 增加 lifecycle_status 过滤
│   │   └── gantt/
│   │       └── gantt_service.py      # [MODIFY] find_available_slot() 增加 lifecycle_status 过滤
│   └── models/
│       └── device.py                 # [READ-ONLY] 已有 is_excluded_from_statistics() 方法
├── frontend/
│   └── src/
│       ├── composables/
│       │   └── useAvailabilityCheck.ts  # [MODIFY] checkDevicesAvailability 前置过滤非 active 设备
│       └── components/
│           └── BookingDialog.vue     # [MODIFY] 设备下拉框显示非 active 设备的生命周期状态标签
```