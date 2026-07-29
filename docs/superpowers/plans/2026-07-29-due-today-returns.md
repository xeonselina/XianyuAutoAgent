# 今日应归还提醒列表 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在甘特图顶部增加准确、可操作的今日应归还列表，并将 `returned` 状态文案统一为“已寄回”。

**Architecture:** 后端提供独立的按服务器当天日期查询接口，前端用一个组合式函数管理列表与状态更新，用独立抽屉组件展示数据，甘特图只负责入口、数量和刷新协作。数据库枚举保持不变。

**Tech Stack:** Flask、Flask-SQLAlchemy、pytest、Vue 3、Pinia、Element Plus、Axios、Vitest、TypeScript。

## Global Constraints

- 今日应归还严格定义为 `end_date + 1 day == today` 且 `status == "shipped"`。
- 仅返回 `parent_rental_id IS NULL` 的主租赁。
- `returned` 数据值保持不变，所有用户可见文案统一为“已寄回”。
- 行内只提供一键“标记为已寄回”，不提供任意状态下拉框。

---

### Task 1: 今日应归还后端接口

**Files:**
- Modify: `InventoryManager/app/services/rental/rental_service.py`
- Modify: `InventoryManager/app/handlers/rental_handlers.py`
- Modify: `InventoryManager/app/routes/rental_api.py`
- Test: `InventoryManager/tests/integration/test_due_today_rentals_api.py`

**Interfaces:**
- Produces: `RentalService.get_due_today_rentals(today: date | None = None) -> list[dict]`
- Produces: `GET /api/rentals/due-today`

- [ ] **Step 1: 写失败的接口测试**

创建昨天结束且为 `shipped` 的主租赁、错误日期租赁、错误状态租赁和子租赁，断言接口只返回目标主租赁，并返回 `device_model`、`start_date`、`end_date`、`destination`、`customer_phone`、`status`。

- [ ] **Step 2: 运行测试确认按预期失败**

Run: `pytest tests/integration/test_due_today_rentals_api.py -q`

Expected: FAIL，接口返回 404。

- [ ] **Step 3: 实现最小查询和路由**

服务方法以 `today or date.today()` 计算 `target_end_date = today - timedelta(days=1)`，过滤 `shipped` 主租赁并将设备型号按 `display_name -> model -> name` 回退。handler 用统一 `success(data={"rentals": rows, "count": len(rows)})` 响应。

- [ ] **Step 4: 运行测试确认通过**

Run: `pytest tests/integration/test_due_today_rentals_api.py -q`

Expected: PASS。

### Task 2: 前端今日应归还状态管理

**Files:**
- Create: `InventoryManager/frontend/src/types/dueTodayRental.ts`
- Create: `InventoryManager/frontend/src/composables/useDueTodayRentals.ts`
- Test: `InventoryManager/frontend/tests/unit/composables/useDueTodayRentals.spec.ts`

**Interfaces:**
- Produces: `useDueTodayRentals()`，包含 `rentals`、`count`、`loading`、`updatingIds`、`load()`、`markReturned(id)`。

- [ ] **Step 1: 写失败的组合式函数测试**

断言 `load()` 请求 `/api/rentals/due-today` 并保存完整列表；`markReturned(id)` 请求 `/api/rentals/<id>/status`、提交 `{status: "returned"}`，成功后重新加载，失败时保留数据并清理当前行 loading。

- [ ] **Step 2: 运行测试确认按预期失败**

Run: `npm run test:run -- tests/unit/composables/useDueTodayRentals.spec.ts`

Expected: FAIL，模块不存在。

- [ ] **Step 3: 实现最小组合式函数**

使用 `ref` 保存数据和 `Set<number>`，统一解析后端错误消息；`markReturned` 用 `try/finally` 管理行级状态，成功后调用 `load()`。

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run test:run -- tests/unit/composables/useDueTodayRentals.spec.ts`

Expected: PASS。

### Task 3: 抽屉和甘特图入口

**Files:**
- Create: `InventoryManager/frontend/src/components/DueTodayReturnsDrawer.vue`
- Modify: `InventoryManager/frontend/src/components/GanttChart.vue`
- Test: `InventoryManager/frontend/tests/unit/components/DueTodayReturnsDrawer.spec.ts`
- Test: `InventoryManager/frontend/tests/unit/components/GanttDueTodayReturnsFlow.spec.ts`

**Interfaces:**
- Consumes: `DueTodayRental[]`、`loading: boolean`、`updatingIds: Set<number>`。
- Produces: `update:modelValue`、`refresh`、`mark-returned` 事件。

- [ ] **Step 1: 写失败的组件和流程测试**

抽屉测试断言字段、空状态和行按钮事件；甘特图流程测试断言挂载时加载数量、按钮展示数量、打开时刷新、状态成功后刷新甘特图。

- [ ] **Step 2: 运行测试确认按预期失败**

Run: `npm run test:run -- tests/unit/components/DueTodayReturnsDrawer.spec.ts tests/unit/components/GanttDueTodayReturnsFlow.spec.ts`

Expected: FAIL，组件和入口不存在。

- [ ] **Step 3: 实现抽屉和入口**

按钮放在甘特图顶部右侧操作区，使用 `Bell` 图标和徽标；抽屉宽度兼容窄屏，地址与电话缺失时显示 `-`；操作失败由甘特图显示 `ElMessage.error`，成功显示“已标记为已寄回”并调用 `ganttStore.loadData()`。

- [ ] **Step 4: 运行测试确认通过**

Run: `npm run test:run -- tests/unit/components/DueTodayReturnsDrawer.spec.ts tests/unit/components/GanttDueTodayReturnsFlow.spec.ts`

Expected: PASS。

### Task 4: 统一“已寄回”状态文案并完成验证

**Files:**
- Modify: `InventoryManager/frontend/src/components/RentalTooltip.vue`
- Modify: `InventoryManager/frontend/src/components/rental/RentalShippingForm.vue`
- Modify: `InventoryManager/frontend/src/components/inspection/RentalInfoCard.vue`
- Modify: `InventoryManager/frontend/src/components/inspection/InspectionRecordCard.vue`
- Modify: `InventoryManager/frontend-mobile/src/views/EditRentalView.vue`
- Modify: `InventoryManager/frontend-mobile/src/views/SearchView.vue`
- Modify: `InventoryManager/frontend-mobile/src/components/BatchShippingCard.vue`
- Modify: `InventoryManager/frontend-mobile/src/components/RentalBottomSheet.vue`
- Modify comments: `InventoryManager/frontend/src/components/GanttRow.vue`
- Modify comments: `InventoryManager/frontend-mobile/src/components/GanttGrid.vue`
- Test: `InventoryManager/frontend/tests/unit/components/RentalShippingForm.spec.ts`

**Interfaces:**
- Produces: 所有 `returned` 用户可见文案为“已寄回”。

- [ ] **Step 1: 先修改现有组件测试期望并确认失败**

在 `RentalShippingForm.spec.ts` 中断言 `returned` 选项标签为“已寄回”。

- [ ] **Step 2: 运行测试确认按预期失败**

Run: `npm run test:run -- tests/unit/components/RentalShippingForm.spec.ts`

Expected: FAIL，实际仍为“已收回”。

- [ ] **Step 3: 统一桌面端和移动端文案**

将所有用户可见的 `returned` 标签改成“已寄回”，同时更新相关颜色映射注释，不改状态值。

- [ ] **Step 4: 完整验证**

Run:

```bash
pytest tests/integration/test_due_today_rentals_api.py -q
cd frontend && npm run test:run && npm run build
cd ../frontend-mobile && npm run build
rg -n '已收回|已还租|已回收' frontend/src frontend-mobile/src
```

Expected: 后端测试通过；桌面端测试与构建通过；移动端构建通过；`rg` 无匹配。

- [ ] **Step 5: 提交并推送**

```bash
git add docs/superpowers/specs/2026-07-29-due-today-returns-design.md \
  docs/superpowers/plans/2026-07-29-due-today-returns.md \
  InventoryManager/openspec/changes/add-due-today-returns \
  InventoryManager/app InventoryManager/tests \
  InventoryManager/frontend/src InventoryManager/frontend/tests \
  InventoryManager/frontend-mobile/src
git commit -m "feat: add due today return reminders"
git push
```
