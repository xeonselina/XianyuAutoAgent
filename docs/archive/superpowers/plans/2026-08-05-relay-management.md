# Relay Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为物流区间重叠至少 2 天的前后 rental 提供可管理状态、永久绑定、顺丰跟踪、桌面宽表和移动卡片。

**Architecture:** 使用新的 `RentalRelayCase` 持久化运营状态，待处理候选由 `RelayCaseService` 实时计算并与持久记录合并。进入/退出已同意边界时在同一事务中维护 `RentalRelayBinding`；顺丰轨迹查询抽取为共享服务并与状态事务解耦。PC 和移动 Vue 页面共用 REST API，但分别使用紧凑宽表与触控卡片。

**Tech Stack:** Python 3 / Flask / SQLAlchemy / Alembic / pytest，Vue 3 / TypeScript / Element Plus / Vitest，Vue 3 / Vant / Playwright，现有顺丰 SDK。

## Global Constraints

- 接力候选必须是同一设备上按 `ship_out_time` 相邻的非取消主 rental，且 `predecessor.ship_in_time.date() - successor.ship_out_time.date() >= 2 days`。
- 前单应寄出日必须是 `predecessor.end_date + 1 day`；后单收货日必须是 `successor.start_date - 1 day`。
- 状态值固定为 `pending`, `notified`, `agreed`, `shipped`, `completed`；签收不得自动设置 `completed`。
- 默认状态筛选为 `pending,notified,agreed,shipped`，默认“寄出时间范围”为服务端今日 T-3 至 T+5，默认每页 50 条。
- 只支持顺丰；跟踪使用前单客户手机号后四位；物流失败不得回滚已寄出状态。
- 所有前端改动必须同时考虑 PC、iPad 和手机；PC 为宽表，移动端为独立卡片页。
- 不增加其他快递公司、自动客户通知、自动创建运单或后台候选物化任务。

## File Map

- `InventoryManager/app/models/rental_relay_case.py`: 接力运营记录和状态/物流字段。
- `InventoryManager/app/services/relay/relay_case_service.py`: 候选识别、列表合并、状态和绑定事务、物流缓存。
- `InventoryManager/app/services/shipping/sf_tracking_service.py`: 共享顺丰客户端和轨迹查询。
- `InventoryManager/app/handlers/relay_case_handlers.py`: HTTP 参数验证和服务异常映射。
- `InventoryManager/app/routes/relay_case_api.py`: 接力 REST 路由。
- `InventoryManager/migrations/versions/20260805_add_rental_relay_cases.py`: 表结构和现有绑定回填。
- `InventoryManager/frontend/src/types/relayCase.ts` 与 `src/api/relayCases.ts`: PC 类型和 API 封装。
- `InventoryManager/frontend/src/views/RelayManagementView.vue`: PC 筛选、宽表和分页。
- `InventoryManager/frontend/src/components/relay/RelayStatusDialog.vue`: PC 状态/运单操作。
- `InventoryManager/frontend-mobile/src/types/relayCase.ts` 与 `src/api/relayCases.ts`: 移动类型和 API 封装。
- `InventoryManager/frontend-mobile/src/views/RelayManagementView.vue`: 移动筛选和卡片列表。
- `InventoryManager/frontend-mobile/src/components/RelayCaseCard.vue` 与 `RelayStatusSheet.vue`: 触控卡片和底部操作弹层。

---

### Task 1: 接力模型与候选识别

**Files:**
- Create: `InventoryManager/app/models/rental_relay_case.py`
- Create: `InventoryManager/app/services/relay/__init__.py`
- Create: `InventoryManager/app/services/relay/relay_case_service.py`
- Create: `InventoryManager/migrations/versions/20260805_add_rental_relay_cases.py`
- Modify: `InventoryManager/app/models/__init__.py`
- Test: `InventoryManager/tests/unit/test_relay_case_service.py`

**Interfaces:**
- Produces: `RentalRelayCase`, `RelayCaseService.find_candidates()`, `RelayCaseService.list_cases()` 和列表项 schema。
- Consumes: `Rental`, `RentalRelayBinding`, `Device`, `DeviceModel` 以及 rental 现有附件关系。

- [ ] **Step 1: 写候选和日期的失败测试**

```python
def test_candidates_require_two_full_overlap_days(relay_seed):
    one_day = relay_seed.pair(overlap_days=1)
    two_days = relay_seed.pair(overlap_days=2, device=one_day.device)
    candidates = RelayCaseService.find_candidates()
    assert (one_day.first.id, one_day.second.id) not in candidates
    assert (two_days.first.id, two_days.second.id) in candidates

def test_candidate_dates_come_from_rental_period(relay_seed):
    pair = relay_seed.pair(overlap_days=2)
    item = RelayCaseService.list_cases(today=date(2026, 8, 5))["items"][0]
    assert item["planned_ship_date"] == (pair.first.end_date + timedelta(days=1)).isoformat()
    assert item["planned_receive_date"] == (pair.second.start_date - timedelta(days=1)).isoformat()
```

- [ ] **Step 2: 运行测试确认因模型/服务缺失而失败**

Run: `cd InventoryManager && TESTING=true pytest tests/unit/test_relay_case_service.py -v`

Expected: FAIL with `ModuleNotFoundError: app.models.rental_relay_case`.

- [ ] **Step 3: 实现最小模型和候选服务**

```python
class RentalRelayCase(db.Model):
    __tablename__ = "rental_relay_cases"
    __table_args__ = (
        db.UniqueConstraint("predecessor_rental_id", "successor_rental_id", name="uq_relay_case_pair"),
        db.CheckConstraint("predecessor_rental_id <> successor_rental_id", name="ck_relay_case_distinct"),
    )
    id = db.Column(db.Integer, primary_key=True)
    predecessor_rental_id = db.Column(db.Integer, db.ForeignKey("rentals.id", ondelete="CASCADE"), nullable=False)
    successor_rental_id = db.Column(db.Integer, db.ForeignKey("rentals.id", ondelete="CASCADE"), nullable=False)
    status = db.Column(db.Enum("pending", "notified", "agreed", "shipped", "completed", name="relay_case_status"), nullable=False, default="pending")
    sf_tracking_number = db.Column(db.String(50))
    sf_tracking_status = db.Column(db.String(50))
    sf_tracking_summary = db.Column(db.String(500))
    sf_last_checked_at = db.Column(db.DateTime)
    notified_at = db.Column(db.DateTime)
    agreed_at = db.Column(db.DateTime)
    shipped_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
```

Implement `find_candidates()` by querying non-cancelled main rentals with non-null logistics times, grouping by `device_id`, stable-sorting by `(ship_out_time, id)`, and including only adjacent pairs with at least two days. Implement `list_cases()` as a merge of those pairs and persisted cases; hide invalid `pending`, retain invalid later statuses with `schedule_changed=True`.

- [ ] **Step 4: 增加迁移和历史绑定回填测试**

```python
def test_existing_binding_is_exposed_as_agreed(relay_seed):
    pair = relay_seed.bound_pair(overlap_days=2)
    item = RelayCaseService.list_cases()["items"][0]
    assert item["status"] == "agreed"
    assert item["predecessor"]["id"] == pair.first.id
```

The migration uses `down_revision = "20260729_device_lifecycle_only"`, creates indexes on `status`, `predecessor_rental_id`, `successor_rental_id`, and inserts missing `agreed` rows from `rental_relay_bindings` using `confirmed_at` for `agreed_at`.

- [ ] **Step 5: 运行候选测试**

Run: `cd InventoryManager && TESTING=true pytest tests/unit/test_relay_case_service.py -v`

Expected: PASS for threshold, adjacency, main-only, cancellation, computed dates, invalid pending hiding, retained notified warning, and existing binding initialization cases.

- [ ] **Step 6: 提交模型和候选服务**

```bash
git add InventoryManager/app/models InventoryManager/app/services/relay InventoryManager/migrations/versions/20260805_add_rental_relay_cases.py InventoryManager/tests/unit/test_relay_case_service.py
git commit -m "feat: identify relay management cases"
```

### Task 2: 状态、永久绑定与事务

**Files:**
- Modify: `InventoryManager/app/services/relay/relay_case_service.py`
- Test: `InventoryManager/tests/unit/test_relay_case_transitions.py`

**Interfaces:**
- Consumes: `RentalRelayCase`, `RentalRelayBinding.validate_pair()` and candidate validation from Task 1.
- Produces: `RelayCaseService.update_case(predecessor_id: int, successor_id: int, status: str, sf_tracking_number: str | None = None, now: datetime | None = None) -> RentalRelayCase`.

- [ ] **Step 1: 写状态与绑定失败测试**

```python
def test_agreed_creates_binding_and_audit(relay_seed):
    pair = relay_seed.pair(overlap_days=2)
    case = RelayCaseService.update_case(pair.first.id, pair.second.id, "agreed")
    assert case.status == "agreed"
    assert RentalRelayBinding.query.filter_by(predecessor_rental_id=pair.first.id, successor_rental_id=pair.second.id).one()
    assert AuditLog.query.filter_by(action="relay_case_status_changed").count() == 1

def test_rollback_before_agreed_removes_binding(relay_seed):
    pair = relay_seed.bound_case(status="shipped")
    RelayCaseService.update_case(pair.first.id, pair.second.id, "notified")
    assert RentalRelayBinding.query.count() == 0
```

- [ ] **Step 2: 运行测试确认 `update_case` 缺失**

Run: `cd InventoryManager && TESTING=true pytest tests/unit/test_relay_case_transitions.py -v`

Expected: FAIL with `AttributeError: RelayCaseService has no attribute update_case`.

- [ ] **Step 3: 实现状态边界和时间戳**

```python
STATUS_ORDER = {"pending": 0, "notified": 1, "agreed": 2, "shipped": 3, "completed": 4}
MILESTONE_FIELDS = {"notified": "notified_at", "agreed": "agreed_at", "shipped": "shipped_at", "completed": "completed_at"}

@classmethod
def update_case(cls, predecessor_id, successor_id, status, sf_tracking_number=None, now=None):
    if status not in STATUS_ORDER:
        raise ValueError("无效的接力状态")
    now = now or datetime.utcnow()
    rentals = Rental.query.filter(Rental.id.in_([predecessor_id, successor_id])).with_for_update().all()
    rental_by_id = {rental.id: rental for rental in rentals}
    predecessor = rental_by_id.get(predecessor_id)
    successor = rental_by_id.get(successor_id)
    if predecessor is None or successor is None:
        raise ValueError("前单或后单不存在")
    case = RentalRelayCase.query.filter_by(
        predecessor_rental_id=predecessor_id,
        successor_rental_id=successor_id,
    ).with_for_update().one_or_none()
    old_status = case.status if case else "pending"
    case = case or RentalRelayCase(
        predecessor_rental_id=predecessor_id,
        successor_rental_id=successor_id,
    )
    if STATUS_ORDER[status] >= STATUS_ORDER["agreed"]:
        cls._require_current_candidate(predecessor, successor)
        cls._ensure_binding(predecessor, successor)
    elif STATUS_ORDER[old_status] >= STATUS_ORDER["agreed"]:
        cls._delete_exact_binding(predecessor_id, successor_id)
    if STATUS_ORDER[status] >= STATUS_ORDER["shipped"]:
        tracking = (sf_tracking_number or case.sf_tracking_number or "").strip()
        if not tracking:
            raise ValueError("已寄出必须录入顺丰运单号")
        case.sf_tracking_number = tracking
    case.status = status
    cls._update_milestones(case, old_status, status, now)
    db.session.add(case)
    db.session.flush()
    cls._add_audit(case, old_status, status)
    db.session.commit()
    return case
```

Entering `agreed`, `shipped`, or `completed` creates/keeps the exact binding. Moving to `pending` or `notified` deletes only the exact binding. Reject another predecessor/successor binding with HTTP-mappable `RelayBindingConflictError`. Require a non-empty tracking number for `shipped` and `completed` only when the case has not already stored one.

- [ ] **Step 4: 增加失效档期、冲突和回滚测试**

```python
def test_schedule_changed_case_cannot_newly_agree(relay_seed):
    case = relay_seed.persisted_case(status="notified", valid=False)
    with pytest.raises(ValueError, match="档期已变化"):
        RelayCaseService.update_case(case.predecessor_rental_id, case.successor_rental_id, "agreed")

def test_audit_failure_rolls_back_case_and_binding(relay_seed, monkeypatch):
    pair = relay_seed.pair(overlap_days=2)
    monkeypatch.setattr(RelayCaseService, "_add_audit", classmethod(lambda cls, *args: (_ for _ in ()).throw(RuntimeError("注入失败"))))
    with pytest.raises(RuntimeError):
        RelayCaseService.update_case(pair.first.id, pair.second.id, "agreed")
    db.session.rollback()
    assert RentalRelayCase.query.count() == 0
    assert RentalRelayBinding.query.count() == 0
```

- [ ] **Step 5: 运行状态测试**

Run: `cd InventoryManager && TESTING=true pytest tests/unit/test_relay_case_transitions.py -v`

Expected: PASS with no transaction warnings.

- [ ] **Step 6: 提交状态和绑定逻辑**

```bash
git add InventoryManager/app/services/relay/relay_case_service.py InventoryManager/tests/unit/test_relay_case_transitions.py
git commit -m "feat: manage relay case workflow"
```

### Task 3: 共享顺丰轨迹和接力物流缓存

**Files:**
- Create: `InventoryManager/app/services/shipping/sf_tracking_service.py`
- Modify: `InventoryManager/app/routes/sf_tracking_api.py`
- Modify: `InventoryManager/app/services/relay/relay_case_service.py`
- Test: `InventoryManager/tests/unit/test_sf_tracking_service.py`
- Test: `InventoryManager/tests/unit/test_relay_case_tracking.py`

**Interfaces:**
- Produces: `SFTrackingService.query(tracking_number: str, phone_last4: str) -> dict` and `RelayCaseService.refresh_tracking(case_id: int) -> dict`.
- Preserves: existing `/api/sf-tracking/query` and `/api/sf-tracking/batch-query` response shapes.

- [ ] **Step 1: 先写共享顺丰服务和个性化手机后四位测试**

```python
def test_query_passes_supplied_phone_last4(monkeypatch):
    client = FakeSFClient(parsed={"SF1": {"status": "in_transit", "routes": []}})
    monkeypatch.setattr(SFTrackingService, "get_client", classmethod(lambda cls: client))
    result = SFTrackingService.query("SF1", "8000")
    assert client.search_calls == [("SF1", "8000")]
    assert result["status"] == "in_transit"

def test_refresh_uses_predecessor_phone_and_does_not_complete(relay_seed, monkeypatch):
    case = relay_seed.bound_case(status="shipped", tracking_number="SF1", predecessor_phone="13800138000")
    monkeypatch.setattr(SFTrackingService, "query", classmethod(lambda cls, number, last4: {"status": "delivered", "status_text": "已签收", "routes": []}))
    RelayCaseService.refresh_tracking(case.id)
    assert case.status == "shipped"
    assert case.sf_tracking_status == "delivered"
```

- [ ] **Step 2: 运行测试确认共享服务缺失**

Run: `cd InventoryManager && TESTING=true pytest tests/unit/test_sf_tracking_service.py tests/unit/test_relay_case_tracking.py -v`

Expected: FAIL with `ModuleNotFoundError: app.services.shipping.sf_tracking_service`.

- [ ] **Step 3: 实现共享查询并改造现有路由**

```python
class SFTrackingService:
    @classmethod
    def get_client(cls):
        return SFExpressSDK(partner_id=os.getenv("SF_PARTNER_ID"), checkword=os.getenv("SF_CHECKWORD"), test_mode=os.getenv("SF_TEST_MODE", "true") == "true")

    @classmethod
    def query(cls, tracking_number, phone_last4):
        response = cls.get_client().search_routes(tracking_number, phone_last4)
        routes = cls.get_client().parse_route_response(response)
        if tracking_number not in routes:
            raise TrackingNotFoundError("未找到该运单的物流信息")
        return routes[tracking_number]
```

Use a single client instance per query call; the snippet expresses the public interface, while implementation stores `client = cls.get_client()` before both SDK operations. Existing endpoints continue using `SENDER_PHONE_LAST4 = "4947"` through the shared service.

- [ ] **Step 4: 实现接力物流缓存和可重试错误**

`refresh_tracking()` extracts four digits from `case.predecessor.customer_phone`, calls `SFTrackingService.query`, caches `status`, human summary and UTC check time, and commits. Missing phone or external errors set `sf_tracking_status="query_failed"`, store a concise Chinese summary, update the check time, and return normally without changing `case.status`.

- [ ] **Step 5: 运行顺丰和接力物流测试**

Run: `cd InventoryManager && TESTING=true pytest tests/unit/test_sf_tracking_service.py tests/unit/test_relay_case_tracking.py -v`

Expected: PASS for success, not-found, missing phone, SDK failure, delivered-without-completion, and existing endpoint compatibility.

- [ ] **Step 6: 提交共享顺丰能力**

```bash
git add InventoryManager/app/services/shipping/sf_tracking_service.py InventoryManager/app/routes/sf_tracking_api.py InventoryManager/app/services/relay/relay_case_service.py InventoryManager/tests/unit/test_sf_tracking_service.py InventoryManager/tests/unit/test_relay_case_tracking.py
git commit -m "refactor: share sf tracking for relay cases"
```

### Task 4: 接力 REST API

**Files:**
- Create: `InventoryManager/app/handlers/relay_case_handlers.py`
- Create: `InventoryManager/app/routes/relay_case_api.py`
- Modify: `InventoryManager/app/routes/web.py`
- Test: `InventoryManager/tests/integration/test_relay_case_api.py`

**Interfaces:**
- Consumes: Task 1–3 service methods.
- Produces: `GET /api/relay-cases`, `PUT /api/relay-cases/<predecessor_id>/<successor_id>`, `POST /api/relay-cases/<case_id>/tracking/refresh`, `POST /api/relay-cases/tracking/refresh-batch`.

- [ ] **Step 1: 写列表默认值和状态 API 失败测试**

```python
def test_list_defaults_to_open_statuses_and_t_minus_3_to_plus_5(client, relay_seed, monkeypatch):
    captured = {}
    monkeypatch.setattr(RelayCaseService, "list_cases", classmethod(lambda cls, **kwargs: captured.update(kwargs) or {"items": [], "total": 0, "page": 1, "per_page": 50}))
    response = client.get("/api/relay-cases")
    assert response.status_code == 200
    assert captured["statuses"] == ["pending", "notified", "agreed", "shipped"]
    assert (captured["ship_date_to"] - captured["ship_date_from"]).days == 8

def test_shipped_requires_tracking_number(client, relay_seed):
    pair = relay_seed.pair(overlap_days=2)
    response = client.put(f"/api/relay-cases/{pair.first.id}/{pair.second.id}", json={"status": "shipped"})
    assert response.status_code == 400
    assert "顺丰运单号" in response.get_json()["message"]
```

- [ ] **Step 2: 运行 API 测试确认路由不存在**

Run: `cd InventoryManager && TESTING=true pytest tests/integration/test_relay_case_api.py -v`

Expected: FAIL with HTTP 404.

- [ ] **Step 3: 实现路由与参数处理**

```python
@bp.get("/api/relay-cases")
@handle_response
def list_relay_cases():
    return RelayCaseHandlers.handle_list()

@bp.put("/api/relay-cases/<int:predecessor_id>/<int:successor_id>")
@handle_response
def update_relay_case(predecessor_id, successor_id):
    return RelayCaseHandlers.handle_update(predecessor_id, successor_id)
```

Parse comma-separated `statuses`, ISO date-only `ship_date_from`/`ship_date_to`, positive `page`, and `per_page` capped at 100. Invalid status/date/range returns 400; binding conflict returns 409; unexpected update failure logs exception, rolls back and returns 500. After a successful transition to `shipped`, call tracking refresh after the status transaction and include its cached result.

- [ ] **Step 4: 增加物流刷新和分页测试**

```python
def test_batch_refresh_only_accepts_current_page_case_ids(client, relay_seed, monkeypatch):
    cases = relay_seed.shipped_cases(2)
    response = client.post("/api/relay-cases/tracking/refresh-batch", json={"case_ids": [case.id for case in cases]})
    assert response.status_code == 200
    assert response.get_json()["data"]["total"] == 2
```

- [ ] **Step 5: 运行接力 API 测试**

Run: `cd InventoryManager && TESTING=true pytest tests/integration/test_relay_case_api.py -v`

Expected: PASS for default and custom filters, pagination, update, conflict, single refresh, partial batch failure, and Chinese errors.

- [ ] **Step 6: 提交接力 API**

```bash
git add InventoryManager/app/handlers/relay_case_handlers.py InventoryManager/app/routes/relay_case_api.py InventoryManager/app/routes/web.py InventoryManager/tests/integration/test_relay_case_api.py
git commit -m "feat: expose relay management api"
```

### Task 5: PC 紧凑宽表

**Files:**
- Create: `InventoryManager/frontend/src/types/relayCase.ts`
- Create: `InventoryManager/frontend/src/api/relayCases.ts`
- Create: `InventoryManager/frontend/src/components/relay/RelayStatusDialog.vue`
- Create: `InventoryManager/frontend/src/views/RelayManagementView.vue`
- Create: `InventoryManager/frontend/tests/unit/components/RelayStatusDialog.spec.ts`
- Create: `InventoryManager/frontend/tests/unit/views/RelayManagementView.spec.ts`
- Modify: `InventoryManager/frontend/src/router/index.ts`
- Modify: `InventoryManager/frontend/src/components/GanttChart.vue`
- Modify: `InventoryManager/app/routes/vue_app.py`

**Interfaces:**
- Consumes: Task 4 response schema.
- Produces: `/relay-management` desktop page and the Gantt “更多 > 接力管理” entry.

- [ ] **Step 1: 写 PC 默认筛选和信息渲染失败测试**

```ts
it('默认排除已完成并查询 T-3 至 T+5', async () => {
  vi.setSystemTime(new Date('2026-08-05T08:00:00+08:00'))
  mountView()
  await flushPromises()
  expect(listRelayCases).toHaveBeenCalledWith(expect.objectContaining({
    statuses: ['pending', 'notified', 'agreed', 'shipped'],
    shipDateFrom: '2026-08-02',
    shipDateTo: '2026-08-10',
    perPage: 50,
  }))
})

it('宽表显示两位客户、租期、设备组合和接力日期', async () => {
  const wrapper = mountView(sampleRelayCase)
  await flushPromises()
  expect(wrapper.text()).toContain('鹿鹿')
  expect(wrapper.text()).toContain('星星')
  expect(wrapper.text()).toContain('X300U')
  expect(wrapper.text()).toContain('2026-08-06')
  expect(wrapper.find('[data-testid="relay-wide-table"]').exists()).toBe(true)
})
```

- [ ] **Step 2: 运行 PC 测试确认页面缺失**

Run: `cd InventoryManager/frontend && npm run test:run -- tests/unit/views/RelayManagementView.spec.ts tests/unit/components/RelayStatusDialog.spec.ts`

Expected: FAIL because view and dialog modules do not exist.

- [ ] **Step 3: 实现类型、API 和宽表**

```ts
export type RelayCaseStatus = 'pending' | 'notified' | 'agreed' | 'shipped' | 'completed'
export interface RelayCaseListParams {
  statuses: RelayCaseStatus[]
  shipDateFrom: string
  shipDateTo: string
  page: number
  perPage: number
}
```

Use Element Plus `el-select multiple` labelled “状态”, `el-date-picker type="daterange"` labelled “寄出时间范围”, `el-table` with fixed status/action columns and `min-width` customer/device columns, and `el-pagination` with 50 rows by default. Render `buyer_id` as nickname and `customer_name` as receiver; show `未填写` for missing fields and a warning tag for `schedule_changed`.

- [ ] **Step 4: 实现状态对话框和物流操作**

`RelayStatusDialog` accepts `{ relayCase, modelValue }`, emits `saved`, asks for confirmation when target order is lower, and requires `sfTrackingNumber.trim()` for `shipped`. The view offers single refresh and current-page batch refresh, disables tracking actions without a persisted case ID, and reloads the list after mutations.

- [ ] **Step 5: 增加路由和入口**

```ts
{ path: '/relay-management', name: 'relay-management', component: () => import('../views/RelayManagementView.vue') }
```

Add `@bp.route('/relay-management')` to the Vue fallback and `command="relay-management"` to the Gantt more menu, handled with `router.push('/relay-management')`.

- [ ] **Step 6: 运行 PC 测试和类型检查**

Run: `cd InventoryManager/frontend && npm run test:run -- tests/unit/views/RelayManagementView.spec.ts tests/unit/components/RelayStatusDialog.spec.ts && npm run type-check`

Expected: PASS with no Vue warnings or TypeScript errors.

- [ ] **Step 7: 提交 PC 页面**

```bash
git add InventoryManager/frontend/src/types/relayCase.ts InventoryManager/frontend/src/api/relayCases.ts InventoryManager/frontend/src/components/relay InventoryManager/frontend/src/views/RelayManagementView.vue InventoryManager/frontend/src/router/index.ts InventoryManager/frontend/src/components/GanttChart.vue InventoryManager/frontend/tests/unit InventoryManager/app/routes/vue_app.py
git commit -m "feat: add desktop relay management page"
```

### Task 6: 移动接力卡片

**Files:**
- Create: `InventoryManager/frontend-mobile/src/types/relayCase.ts`
- Create: `InventoryManager/frontend-mobile/src/api/relayCases.ts`
- Create: `InventoryManager/frontend-mobile/src/components/RelayCaseCard.vue`
- Create: `InventoryManager/frontend-mobile/src/components/RelayStatusSheet.vue`
- Create: `InventoryManager/frontend-mobile/src/views/RelayManagementView.vue`
- Create: `InventoryManager/frontend-mobile/e2e/relay-management.spec.ts`
- Modify: `InventoryManager/frontend-mobile/src/router/index.ts`
- Modify: `InventoryManager/frontend-mobile/src/App.vue`

**Interfaces:**
- Consumes: Task 4 API and the same field names as PC.
- Produces: `/mobile/relay`, touch cards, filter popup, status/tracking action sheet, and bottom tab entry.

- [ ] **Step 1: 写移动路由、默认查询和卡片失败 E2E**

```ts
test('shows relay cards and uses open-status default filters', async ({ page }) => {
  let requestUrl = ''
  await page.route('**/api/relay-cases**', async route => {
    requestUrl = route.request().url()
    await route.fulfill({ json: { success: true, data: sampleRelayList } })
  })
  await page.goto('/mobile/relay')
  await expect(page.getByText('接力管理')).toBeVisible()
  await expect(page.getByText('鹿鹿')).toBeVisible()
  expect(requestUrl).toContain('statuses=pending%2Cnotified%2Cagreed%2Cshipped')
})
```

- [ ] **Step 2: 运行 E2E 确认移动路由不存在**

Run in terminal A: `cd InventoryManager/frontend-mobile && npm run dev -- --host 127.0.0.1`

Run in terminal B: `cd InventoryManager/frontend-mobile && npx playwright test e2e/relay-management.spec.ts`

Expected: FAIL because `/mobile/relay` falls back to no matching route/content.

- [ ] **Step 3: 实现移动类型、API、卡片和筛选**

Use a Vant nav bar with pending count and refresh, a compact filter summary opening a popup/action sheet, and `RelayCaseCard` blocks with device combination, predecessor arrow successor, planned dates, status, warning and tracking summary. Date range uses Vant date picker popups and sends date-only strings.

- [ ] **Step 4: 实现底部状态弹层与物流操作**

`RelayStatusSheet` mirrors PC validation: confirmation for backward transitions, tracking number required for `shipped`, manual completion only, and explicit retry for query failure. Touch targets remain at least 44 px high.

- [ ] **Step 5: 增加移动路由和底部标签**

```ts
{ path: '/relay', name: 'relay', component: () => import('@/views/RelayManagementView.vue') }
```

Add `<van-tabbar-item name="relay" icon="exchange">接力</van-tabbar-item>`, include `relay` in `showTabbar`, and map the tab name through `router.push({ name })`.

- [ ] **Step 6: 运行移动 E2E 和构建**

Run: `cd InventoryManager/frontend-mobile && npx playwright test e2e/relay-management.spec.ts && npm run build`

Expected: PASS for default filters, card fields, filter update, status action, tracking validation, refresh, and tab navigation; build completes with no type errors.

- [ ] **Step 7: 提交移动页面**

```bash
git add InventoryManager/frontend-mobile/src InventoryManager/frontend-mobile/e2e/relay-management.spec.ts
git commit -m "feat: add mobile relay management page"
```

### Task 7: 全量验证、构建产物与规格状态

**Files:**
- Modify: `InventoryManager/openspec/changes/add-relay-management/tasks.md`
- Modify: `InventoryManager/static/vue-dist/**`
- Modify: `InventoryManager/static/vue-mobile-dist/**`

**Interfaces:**
- Consumes: all prior tasks.
- Produces: verified source, passing suites, current production bundles, and an accurate OpenSpec checklist.

- [ ] **Step 1: 运行接力后端套件**

Run: `cd InventoryManager && TESTING=true pytest tests/unit/test_relay_case_service.py tests/unit/test_relay_case_transitions.py tests/unit/test_sf_tracking_service.py tests/unit/test_relay_case_tracking.py tests/integration/test_relay_case_api.py -v`

Expected: all relay tests PASS.

- [ ] **Step 2: 运行相关既有回归测试**

Run: `cd InventoryManager && TESTING=true pytest tests/unit/test_gantt_relay_analysis.py tests/integration/test_gantt_reorder_api.py -v`

Expected: all existing Gantt relay/reorder tests PASS and permanent binding behavior is unchanged.

- [ ] **Step 3: 运行 PC 全量测试与构建**

Run: `cd InventoryManager/frontend && npm run test:run && npm run build`

Expected: Vitest, `vue-tsc`, and Vite build PASS; `InventoryManager/static/vue-dist` is refreshed.

- [ ] **Step 4: 运行移动接力 E2E 与构建**

Run: `cd InventoryManager/frontend-mobile && npx playwright test e2e/relay-management.spec.ts && npm run build`

Expected: mobile relay E2E and production build PASS; `InventoryManager/static/vue-mobile-dist` is refreshed.

- [ ] **Step 5: 做布局和完整流程检查**

At desktop widths 1280 px and 3840 px verify fixed status/action columns, horizontal scrolling at 1280 px, readable full customer details, default filters, state rollback confirmation, tracking number requirement and tracking refresh. At a 390x844 mobile viewport verify card wrapping, filter popups, 44 px touch controls, tab navigation and status sheet.

- [ ] **Step 6: 更新 OpenSpec 清单并严格校验**

Mark only genuinely completed items in `InventoryManager/openspec/changes/add-relay-management/tasks.md`, then run:

`cd InventoryManager && openspec validate add-relay-management --strict`

Expected: change is valid and all implemented task boxes are checked.

- [ ] **Step 7: 检查 diff 并提交最终产物**

```bash
git diff --check
git status --short
git add InventoryManager/openspec/changes/add-relay-management/tasks.md InventoryManager/static/vue-dist InventoryManager/static/vue-mobile-dist
git commit -m "build: publish relay management frontend bundles"
```
