# 待归还订单分组展示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将只提醒今日订单的功能扩展为查询全部今天及以前仍未寄回的订单，并按逾期时间段分组展示。

**Architecture:** Flask 服务端以服务器本地日期计算 `due_date` 和 `overdue_days`，通过新的规范接口返回平铺、稳定排序的列表，同时保留旧接口别名。Vue 前端消费服务端计算结果，在抽屉组件内按固定区间分组，不重复计算日期，并保持原有行级状态更新流程。

**Tech Stack:** Python、Flask、SQLAlchemy、pytest、Vue 3、TypeScript、Element Plus、Vitest、Vue Test Utils

## Global Constraints

- 服务器本地日期是唯一日期口径，前端不得根据浏览器日期重新计算逾期天数。
- 待归还记录必须同时满足 `end_date <= today - 1 天`、`status == "shipped"`、`parent_rental_id IS NULL`。
- 分组固定为“今日”“逾期 1–3 天”“逾期 4–7 天”“逾期超过 7 天”，空分组不展示。
- 新规范接口为 `/api/rentals/pending-returns`，旧 `/api/rentals/due-today` 必须保留并返回相同数据。
- 数据库结构和 `returned` 状态值不变，不新增依赖。
- Element Plus 抽屉 `size` 只能使用 splitter 支持的像素或百分比格式。
- 只提交本功能相关源文件、测试与文档，不提交工作区中已有的无关构建产物。

---

### Task 1: 服务端待归还查询与兼容接口

**Files:**
- Modify: `InventoryManager/app/services/rental/rental_service.py:19-51`
- Modify: `InventoryManager/app/handlers/rental_handlers.py:57-72`
- Modify: `InventoryManager/app/routes/rental_api.py:28-33`
- Modify: `InventoryManager/tests/integration/test_due_today_rentals_api.py`

**Interfaces:**
- Produces: `RentalService.get_pending_returns(today: Optional[date] = None) -> List[Dict[str, Any]]`
- Produces: `RentalHandlers.handle_get_pending_returns() -> ApiResponse`
- Produces: `GET /api/rentals/pending-returns` and compatibility alias `GET /api/rentals/due-today`
- Response rows add `due_date: str` and `overdue_days: int` while retaining every existing field.

- [ ] **Step 1: Replace the exact-day integration expectation with boundary and ordering expectations**

Seed main rentals whose `end_date` values map to `overdue_days` 0, 1, 3, 4, 7, and 8, plus a future rental, a returned rental, and a child rental. Assert the canonical endpoint returns only the six eligible rows and exact pairs:

```python
assert [
    (row["id"], row["due_date"], row["overdue_days"])
    for row in payload["data"]["rentals"]
] == [
    (overdue_8_id, (today - timedelta(days=8)).isoformat(), 8),
    (overdue_7_id, (today - timedelta(days=7)).isoformat(), 7),
    (overdue_4_id, (today - timedelta(days=4)).isoformat(), 4),
    (overdue_3_id, (today - timedelta(days=3)).isoformat(), 3),
    (overdue_1_id, (today - timedelta(days=1)).isoformat(), 1),
    (due_today_id, today.isoformat(), 0),
]
```

Add a compatibility assertion that `/api/rentals/due-today` returns the same `data` as `/api/rentals/pending-returns`. Retain the model fallback test against the canonical endpoint.

- [ ] **Step 2: Run the backend test and verify the new behavior fails**

Run:

```bash
cd InventoryManager
pytest tests/integration/test_due_today_rentals_api.py -q
```

Expected: FAIL because `/api/rentals/pending-returns` is missing and the existing query excludes overdue rows and fields.

- [ ] **Step 3: Implement the pending-return service, handler, and routes**

Replace the old service method with:

```python
@staticmethod
def get_pending_returns(today: Optional[date] = None) -> List[Dict[str, Any]]:
    current_date = today or date.today()
    latest_end_date = current_date - timedelta(days=1)
    rentals = (
        Rental.query
        .options(joinedload(Rental.device))
        .filter(
            Rental.end_date <= latest_end_date,
            Rental.status == 'shipped',
            Rental.parent_rental_id.is_(None),
        )
        .all()
    )

    rows = []
    for rental in rentals:
        due_date = rental.end_date + timedelta(days=1)
        overdue_days = (current_date - due_date).days
        device = rental.device
        device_model = None
        if device:
            if device.device_model:
                device_model = device.device_model.display_name
            device_model = device_model or device.model or device.name
        rows.append({
            'id': rental.id,
            'device_model': device_model or '-',
            'start_date': rental.start_date.isoformat(),
            'end_date': rental.end_date.isoformat(),
            'due_date': due_date.isoformat(),
            'overdue_days': overdue_days,
            'destination': rental.destination,
            'customer_phone': rental.customer_phone,
            'status': rental.status,
        })

    return sorted(rows, key=lambda row: (-row['overdue_days'], row['id']))
```

Rename the handler to `handle_get_pending_returns`, update its copy to “待归还”, add the canonical route, and point both routes to the same handler.

- [ ] **Step 4: Run the backend integration test and verify it passes**

Run:

```bash
cd InventoryManager
pytest tests/integration/test_due_today_rentals_api.py -q
```

Expected: all tests PASS.

- [ ] **Step 5: Commit the backend task**

```bash
git add InventoryManager/app/services/rental/rental_service.py \
  InventoryManager/app/handlers/rental_handlers.py \
  InventoryManager/app/routes/rental_api.py \
  InventoryManager/tests/integration/test_due_today_rentals_api.py
git commit -m "feat: include overdue pending returns"
```

### Task 2: 前端待归还类型与状态管理

**Files:**
- Create: `InventoryManager/frontend/src/types/pendingReturn.ts`
- Delete: `InventoryManager/frontend/src/types/dueTodayRental.ts`
- Create: `InventoryManager/frontend/src/composables/usePendingReturns.ts`
- Delete: `InventoryManager/frontend/src/composables/useDueTodayRentals.ts`
- Create: `InventoryManager/frontend/tests/unit/composables/usePendingReturns.spec.ts`
- Delete: `InventoryManager/frontend/tests/unit/composables/useDueTodayRentals.spec.ts`

**Interfaces:**
- Produces: `PendingReturn` with `due_date: string` and `overdue_days: number`.
- Produces: `usePendingReturns()` returning `rentals`, `count`, `loading`, `updatingIds`, `load`, and `markReturned`.
- Consumes: `GET /api/rentals/pending-returns` and the existing status-update endpoint.

- [ ] **Step 1: Add the renamed composable tests with the canonical endpoint and complete payload**

Define the fixture with:

```typescript
const pendingReturn: PendingReturn = {
  id: 7,
  device_model: 'iPhone 15 Pro',
  start_date: '2026-07-25',
  end_date: '2026-07-28',
  due_date: '2026-07-29',
  overdue_days: 3,
  destination: '上海市浦东新区测试路 1 号',
  customer_phone: '13800138000',
  status: 'shipped',
}
```

Retain the existing success, update failure, and refresh-failure cases, but assert `axios.get('/api/rentals/pending-returns')`.

- [ ] **Step 2: Run the composable test and verify it fails**

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/composables/usePendingReturns.spec.ts
```

Expected: FAIL because the new type and composable modules do not exist.

- [ ] **Step 3: Implement the renamed type and composable**

Create:

```typescript
export interface PendingReturn {
  id: number
  device_model: string
  start_date: string
  end_date: string
  due_date: string
  overdue_days: number
  destination: string | null
  customer_phone: string | null
  status: 'shipped'
}
```

Move the existing state/update behavior into `usePendingReturns`, change the list request to `/api/rentals/pending-returns`, and change user-facing fallback errors from “今日应归还” to “待归还”. Remove the old modules only after all imports move in later tasks.

- [ ] **Step 4: Run the composable test and verify it passes**

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/composables/usePendingReturns.spec.ts
```

Expected: all tests PASS.

### Task 3: 分组待归还抽屉

**Files:**
- Create: `InventoryManager/frontend/src/components/PendingReturnsDrawer.vue`
- Delete: `InventoryManager/frontend/src/components/DueTodayReturnsDrawer.vue`
- Create: `InventoryManager/frontend/tests/unit/components/PendingReturnsDrawer.spec.ts`
- Delete: `InventoryManager/frontend/tests/unit/components/DueTodayReturnsDrawer.spec.ts`

**Interfaces:**
- Consumes: `PendingReturn[]`, `loading: boolean`, and `updatingIds: Set<number>`.
- Emits: `update:modelValue` and `mark-returned` with the rental ID.
- Produces: fixed, nonempty `groups` in the order today, 1–3, 4–7, and over 7 days.

- [ ] **Step 1: Add drawer tests for every boundary and grouped rendering**

Mount returns with `overdue_days` 0, 1, 3, 4, 7, and 8. Assert:

```typescript
expect(wrapper.findAll('[data-testid="pending-return-group"]')).toHaveLength(4)
expect(wrapper.text()).toContain('今日（1）')
expect(wrapper.text()).toContain('逾期 1–3 天（2）')
expect(wrapper.text()).toContain('逾期 4–7 天（2）')
expect(wrapper.text()).toContain('逾期超过 7 天（1）')
```

Assert group heading order, the exact “应归还：2026-07-29” copy, empty-group hiding, “暂无待归还订单”, row event emission, row-level disabling, and a splitter-compatible `size` prop.

- [ ] **Step 2: Run the drawer test and verify it fails**

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/components/PendingReturnsDrawer.spec.ts
```

Expected: FAIL because `PendingReturnsDrawer.vue` does not exist.

- [ ] **Step 3: Implement the grouped drawer**

Use a computed list based only on `overdue_days`:

```typescript
const groups = computed(() => [
  { key: 'today', label: '今日', rentals: props.rentals.filter((item) => item.overdue_days === 0) },
  { key: 'one-to-three', label: '逾期 1–3 天', rentals: props.rentals.filter((item) => item.overdue_days >= 1 && item.overdue_days <= 3) },
  { key: 'four-to-seven', label: '逾期 4–7 天', rentals: props.rentals.filter((item) => item.overdue_days >= 4 && item.overdue_days <= 7) },
  { key: 'over-seven', label: '逾期超过 7 天', rentals: props.rentals.filter((item) => item.overdue_days >= 8) },
].filter((group) => group.rentals.length > 0))
```

Render one table per nonempty group, keep the existing row action behavior and CSS, add the due-date line, change title/empty copy to “待归还”, and preserve `size="920px"`.

- [ ] **Step 4: Run the drawer test and verify it passes**

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/components/PendingReturnsDrawer.spec.ts
```

Expected: all tests PASS.

### Task 4: 甘特图待归还流程集成与旧模块移除

**Files:**
- Modify: `InventoryManager/frontend/src/components/GanttChart.vue`
- Create: `InventoryManager/frontend/tests/unit/components/GanttPendingReturnsFlow.spec.ts`
- Delete: `InventoryManager/frontend/tests/unit/components/GanttDueTodayReturnsFlow.spec.ts`
- Delete old frontend modules listed in Tasks 2 and 3 after all imports are updated.

**Interfaces:**
- Consumes: `PendingReturnsDrawer` and `usePendingReturns()`.
- Produces: `data-testid="pending-returns-button"`, `.pending-returns-badge`, “待归还” copy, refresh-on-open behavior, and existing mark-returned flow.

- [ ] **Step 1: Add the renamed Gantt flow test**

Use a full pending-return fixture including `due_date` and `overdue_days`. Assert the initial and open-time requests both call `/api/rentals/pending-returns`, the badge total is correct, clicking the “待归还” button opens `PendingReturnsDrawer`, and marking a row still refreshes Gantt data and shows “已标记为已寄回”.

- [ ] **Step 2: Run the Gantt flow test and verify it fails**

```bash
cd InventoryManager/frontend
npm run test:run -- tests/unit/components/GanttPendingReturnsFlow.spec.ts
```

Expected: FAIL because Gantt still imports and calls the due-today modules and endpoint.

- [ ] **Step 3: Update Gantt integration and remove old modules**

Rename the component import, composable import, refs, handlers, CSS class, and test ID from due-today terminology to pending-returns terminology. Change the button label to “待归还”. Preserve mount-time count loading, refresh on open, row update, toast, and Gantt refresh behavior. Delete old type, composable, component, and test files after `rg -n "DueToday|dueToday|due-today" InventoryManager/frontend/src InventoryManager/frontend/tests` shows only intentional compatibility references or no matches.

- [ ] **Step 4: Run all pending-return frontend tests**

```bash
cd InventoryManager/frontend
npm run test:run -- \
  tests/unit/composables/usePendingReturns.spec.ts \
  tests/unit/components/PendingReturnsDrawer.spec.ts \
  tests/unit/components/GanttPendingReturnsFlow.spec.ts
```

Expected: all tests PASS.

- [ ] **Step 5: Commit the frontend task**

```bash
git add InventoryManager/frontend/src/types \
  InventoryManager/frontend/src/composables \
  InventoryManager/frontend/src/components/GanttChart.vue \
  InventoryManager/frontend/src/components/PendingReturnsDrawer.vue \
  InventoryManager/frontend/tests/unit/composables \
  InventoryManager/frontend/tests/unit/components
git commit -m "feat: group pending returns by overdue period"
```

### Task 5: Complete verification and push

**Files:**
- Verify only; no expected source changes.

**Interfaces:**
- Consumes all completed backend and frontend tasks.
- Produces a pushed `main` branch with only relevant commits.

- [ ] **Step 1: Run backend verification**

```bash
cd InventoryManager
pytest tests/integration/test_due_today_rentals_api.py -q
```

Expected: all tests PASS.

- [ ] **Step 2: Run frontend verification**

```bash
cd InventoryManager/frontend
npm run test:run
npm run type-check
```

Expected: 0 failed tests and type-check exit code 0.

- [ ] **Step 3: Build to a temporary directory**

Use a temporary output directory so existing static bundle changes remain untouched:

```bash
cd InventoryManager/frontend
task_build_dir=$(mktemp -d /tmp/xianyu-pending-returns.XXXXXX)
npx vite build --outDir "$task_build_dir" --emptyOutDir
```

Expected: build exit code 0.

- [ ] **Step 4: Verify commit scope and whitespace**

```bash
git diff --check HEAD~2..HEAD
git status --short
git log -3 --oneline
```

Expected: implementation commits contain only planned source/tests; pre-existing unrelated static bundle changes remain uncommitted.

- [ ] **Step 5: Push current main branch**

```bash
git push
```

Expected: local `main` pushes successfully to its configured upstream.
