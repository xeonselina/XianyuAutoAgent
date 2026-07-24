# Xianyu Missing Order Alerts Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Detect Xianyu orders waiting for shipment with paid amounts above ¥50 that are missing from inventory rentals, and surface them as an actionable warning at the top of the existing Gantt view.

**Architecture:** Extend the existing signed Xianyu client with complete pagination, then reconcile external order numbers against `Rental.xianyu_order_no` into a durable alert cache. APScheduler refreshes that cache every ten minutes, Flask APIs expose cached state/refresh/permanent-ignore operations, and a focused Vue warning component opens the existing `BookingDialog` with an initial order number.

**Tech Stack:** Python 3, Flask, Flask-SQLAlchemy, Flask-Migrate/Alembic, APScheduler, pytest, Vue 3, TypeScript, Element Plus, Axios, Vitest.

## Global Constraints

- Eligible orders are exactly `order_status = 12` and `pay_amount > 5000` cents.
- Refund status does not affect eligibility.
- The configured Xianyu credentials represent one store.
- Reuse the existing `BookingDialog`; do not create another booking page or form.
- Display warnings only inline at the top of the Gantt view.
- Permanent ignores require a non-empty reason and have no restore UI.
- Failed or incomplete external reads must retain the previous successful alert cache.
- Do not log signed URLs, response bodies containing buyer data, or buyer mobile numbers.

---

## File Structure

- Create `app/models/xianyu_order_alert.py`: durable alert rows and singleton sync-state model.
- Modify `app/models/__init__.py`: register both new models.
- Create `migrations/versions/20260724_add_xianyu_order_alerts.py`: create the alert and sync-state tables.
- Modify `app/services/xianyu_order_service.py`: add safe logging, list pagination, and a typed external-service error.
- Create `app/services/xianyu_order_reconciliation_service.py`: eligibility, database comparison, atomic cache replacement, permanent ignore, and process-safe refresh lock.
- Create `app/handlers/xianyu_order_alert_handlers.py`: translate reconciliation operations into `ApiResponse`.
- Create `app/routes/xianyu_order_alert_api.py`: define cache, refresh, and ignore endpoints.
- Modify `app/routes/web.py`: register the new internal API blueprint.
- Modify `app/utils/scheduler.py`: register the ten-minute reconciliation job.
- Modify `app/utils/scheduler_tasks.py`: add the application-context scheduler entry point.
- Create `tests/unit/test_xianyu_order_service.py`: pagination and failure semantics.
- Create `tests/unit/test_xianyu_order_reconciliation_service.py`: amount boundary, rental exclusion, ignore persistence, and failed-refresh retention.
- Create `tests/integration/test_xianyu_order_alert_api.py`: response and validation behavior.
- Create `frontend/src/types/xianyuOrderAlert.ts`: frontend API types.
- Create `frontend/src/composables/useXianyuOrderAlerts.ts`: cached reads, refresh, ignore, and one-minute cache polling.
- Create `frontend/src/components/XianyuOrderAlertBar.vue`: inline warning presentation and permanent-ignore confirmation.
- Create `frontend/tests/unit/components/XianyuOrderAlertBar.spec.ts`: presentation and emitted actions.
- Modify `frontend/src/components/BookingDialog.vue`: accept an optional initial order number and call the existing detail-fetch method.
- Modify `frontend/src/components/GanttChart.vue`: place the warning bar, drive alert state, and reopen the existing booking flow.

---

### Task 1: Durable alert state

**Files:**
- Create: `app/models/xianyu_order_alert.py`
- Modify: `app/models/__init__.py`
- Create: `migrations/versions/20260724_add_xianyu_order_alerts.py`
- Test: `tests/unit/test_xianyu_order_reconciliation_service.py`

**Interfaces:**
- Produces: `XianyuOrderAlert.to_dict() -> dict`
- Produces: `XianyuOrderSyncState.get_or_create() -> XianyuOrderSyncState`

- [ ] **Step 1: Write a failing model test**

```python
def test_alert_serializes_amount_and_order_fields(app, db_session):
    from app.models.xianyu_order_alert import XianyuOrderAlert

    with app.app_context():
        alert = XianyuOrderAlert(
            order_no=" XY-1 ",
            state="pending",
            pay_amount=5001,
            buyer_nick="买家",
            receiver_mobile="13800138000",
            goods_title="相机租赁",
        )
        db_session.add(alert)
        db_session.commit()

        payload = alert.to_dict()
        assert alert.order_no == "XY-1"
        assert payload["pay_amount"] == 5001
        assert payload["buyer_nick"] == "买家"
```

- [ ] **Step 2: Run the test and confirm the model is missing**

Run: `pytest tests/unit/test_xianyu_order_reconciliation_service.py::test_alert_serializes_amount_and_order_fields -v`

Expected: FAIL with `ModuleNotFoundError: app.models.xianyu_order_alert`.

- [ ] **Step 3: Add the models and migration**

Implement:

```python
class XianyuOrderAlert(db.Model):
    __tablename__ = "xianyu_order_alerts"
    id = db.Column(db.Integer, primary_key=True)
    order_no = db.Column(db.String(50), nullable=False, unique=True, index=True)
    state = db.Column(db.String(20), nullable=False, default="pending", index=True)
    pay_amount = db.Column(db.BigInteger, nullable=False)
    buyer_nick = db.Column(db.String(100))
    receiver_name = db.Column(db.String(100))
    receiver_mobile = db.Column(db.String(20))
    address = db.Column(db.String(500))
    goods_title = db.Column(db.String(500))
    goods_sku_text = db.Column(db.String(500))
    order_time = db.Column(db.DateTime)
    first_detected_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    ignored_reason = db.Column(db.String(500))
    ignored_at = db.Column(db.DateTime)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(
        db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    @validates("order_no")
    def normalize_order_no(self, _key, value):
        normalized = str(value or "").strip()
        if not normalized:
            raise ValueError("订单号不能为空")
        return normalized

    def to_dict(self):
        return {
            "order_no": self.order_no,
            "pay_amount": self.pay_amount,
            "buyer_nick": self.buyer_nick,
            "receiver_name": self.receiver_name,
            "receiver_mobile": self.receiver_mobile,
            "address": self.address,
            "goods_title": self.goods_title,
            "goods_sku_text": self.goods_sku_text,
            "order_time": self.order_time.isoformat() if self.order_time else None,
            "first_detected_at": self.first_detected_at.isoformat(),
            "last_seen_at": self.last_seen_at.isoformat(),
        }


class XianyuOrderSyncState(db.Model):
    __tablename__ = "xianyu_order_sync_state"
    id = db.Column(db.Integer, primary_key=True, default=1)
    last_attempt_at = db.Column(db.DateTime)
    last_success_at = db.Column(db.DateTime)
    last_error = db.Column(db.String(1000))

    @classmethod
    def get_or_create(cls):
        state = db.session.get(cls, 1)
        if state is None:
            state = cls(id=1)
            db.session.add(state)
            db.session.flush()
        return state
```

Register both classes from `app/models/__init__.py`. Create both tables, indexes, and the `pending`/`ignored` state check constraint in Alembic revision `20260724_xianyu_alerts` with `down_revision = "20260711_relay_bindings"`.

- [ ] **Step 4: Run the model test**

Run: `pytest tests/unit/test_xianyu_order_reconciliation_service.py::test_alert_serializes_amount_and_order_fields -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/models/xianyu_order_alert.py app/models/__init__.py migrations/versions/20260724_add_xianyu_order_alerts.py tests/unit/test_xianyu_order_reconciliation_service.py
git commit -m "feat: add Xianyu order alert persistence"
```

### Task 2: Complete Xianyu list reads and reconciliation

**Files:**
- Modify: `app/services/xianyu_order_service.py`
- Create: `app/services/xianyu_order_reconciliation_service.py`
- Test: `tests/unit/test_xianyu_order_service.py`
- Test: `tests/unit/test_xianyu_order_reconciliation_service.py`

**Interfaces:**
- Produces: `XianyuOrderService.list_orders(order_status: int = 12, page_size: int = 100) -> list[dict]`
- Produces: `XianyuOrderReconciliationService.reconcile() -> dict`
- Produces: `XianyuOrderReconciliationService.get_snapshot() -> dict`
- Produces: `XianyuOrderReconciliationService.ignore(order_no: str, reason: str) -> dict`

- [ ] **Step 1: Write failing pagination tests**

```python
def test_list_orders_fetches_every_page(monkeypatch):
    service = XianyuOrderService()
    responses = [
        {"code": 0, "data": {"list": [{"order_no": "1"}], "count": 2}},
        {"code": 0, "data": {"list": [{"order_no": "2"}], "count": 2}},
    ]
    monkeypatch.setattr(service, "_request_with_body_sign", lambda *_args, **_kw: responses.pop(0))

    assert [row["order_no"] for row in service.list_orders(page_size=1)] == ["1", "2"]


def test_list_orders_rejects_partial_results(monkeypatch):
    service = XianyuOrderService()
    responses = [
        {"code": 0, "data": {"list": [{"order_no": "1"}], "count": 2}},
        None,
    ]
    monkeypatch.setattr(service, "_request_with_body_sign", lambda *_args, **_kw: responses.pop(0))

    with pytest.raises(XianyuOrderServiceError):
        service.list_orders(page_size=1)
```

- [ ] **Step 2: Run pagination tests**

Run: `pytest tests/unit/test_xianyu_order_service.py -v`

Expected: FAIL because `list_orders` and `XianyuOrderServiceError` do not exist.

- [ ] **Step 3: Implement safe pagination**

Add `XianyuOrderServiceError(RuntimeError)` and implement:

```python
def list_orders(self, order_status=12, page_size=100):
    if not self.app_key or not self.app_secret:
        raise XianyuOrderServiceError("闲鱼API凭证未配置")
    orders = []
    page_no = 1
    while True:
        result = self._request_with_body_sign(
            "/api/open/order/list",
            {"order_status": order_status, "page_no": page_no, "page_size": page_size},
        )
        if not result:
            raise XianyuOrderServiceError("闲鱼订单列表无响应")
        if result.get("code") != 0:
            raise XianyuOrderServiceError(result.get("msg") or "闲鱼订单列表查询失败")
        data = result.get("data") or {}
        page = data.get("list")
        if not isinstance(page, list):
            raise XianyuOrderServiceError("闲鱼订单列表响应格式错误")
        orders.extend(page)
        total = int(data.get("count", len(orders)))
        if len(orders) >= total:
            return orders
        if not page or page_no >= 100:
            raise XianyuOrderServiceError("闲鱼订单列表分页不完整")
        page_no += 1
```

Replace signed-URL and response-body log statements with path, page/status, and response code only.

- [ ] **Step 4: Write failing reconciliation tests**

```python
def test_reconcile_filters_amount_and_existing_rentals(
    app, db_session, device, monkeypatch
):
    from app.models.rental import Rental
    service = XianyuOrderReconciliationService()
    monkeypatch.setattr(
        service.xianyu_service,
        "list_orders",
        lambda: [
            make_order("LOW", 5000),
            make_order("MISSING", 5001),
            make_order("RECORDED", 9000),
        ],
    )
    db_session.add(make_rental(device.id, "RECORDED"))
    db_session.commit()

    with app.app_context():
        result = service.reconcile()

    assert [row["order_no"] for row in result["alerts"]] == ["MISSING"]


def test_failed_reconcile_keeps_existing_cache(app, db_session, monkeypatch):
    db_session.add(XianyuOrderAlert(order_no="OLD", state="pending", pay_amount=6000))
    db_session.commit()
    service = XianyuOrderReconciliationService()
    monkeypatch.setattr(
        service.xianyu_service,
        "list_orders",
        Mock(side_effect=XianyuOrderServiceError("timeout")),
    )

    with app.app_context():
        result = service.reconcile()

    assert [row["order_no"] for row in result["alerts"]] == ["OLD"]
    assert result["sync"]["last_error"] == "timeout"
```

- [ ] **Step 5: Run reconciliation tests**

Run: `pytest tests/unit/test_xianyu_order_reconciliation_service.py -v`

Expected: FAIL because the reconciliation service does not exist.

- [ ] **Step 6: Implement reconciliation and permanent ignore**

Implement `XianyuOrderReconciliationService` with:

```python
MIN_PAY_AMOUNT = 5000
LOCK_PATH = "/tmp/inventory_xianyu_order_reconcile.lock"

def _eligible_orders(self, orders):
    return {
        str(order.get("order_no") or "").strip(): order
        for order in orders
        if str(order.get("order_no") or "").strip()
        and int(order.get("pay_amount") or 0) > self.MIN_PAY_AMOUNT
    }

def reconcile(self):
    lock_handle = self._try_acquire_lock()
    if lock_handle is None:
        snapshot = self.get_snapshot()
        snapshot["refreshing"] = True
        return snapshot
    try:
        now = datetime.utcnow()
        orders = self._eligible_orders(self.xianyu_service.list_orders())
        existing = {
            value.strip()
            for (value,) in db.session.query(Rental.xianyu_order_no)
            .filter(Rental.xianyu_order_no.in_(orders))
            .all()
            if value and value.strip()
        }
        ignored = {
            value
            for (value,) in db.session.query(XianyuOrderAlert.order_no)
            .filter(XianyuOrderAlert.state == "ignored")
            .all()
        }
        pending = {key: value for key, value in orders.items() if key not in existing | ignored}
        self._replace_pending(pending, now)
        state = XianyuOrderSyncState.get_or_create()
        state.last_attempt_at = now
        state.last_success_at = now
        state.last_error = None
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        state = XianyuOrderSyncState.get_or_create()
        state.last_attempt_at = datetime.utcnow()
        state.last_error = str(exc)[:1000]
        db.session.commit()
    finally:
        self._release_lock(lock_handle)
    return self.get_snapshot()
```

`_replace_pending` must delete only stale `state="pending"` rows, preserve all ignored rows, convert Unix `order_time` to UTC `datetime`, combine address fields, and upsert all display fields. `get_snapshot` must exclude order numbers currently present in rentals and sort newest order first. `ignore` must reject empty reasons and missing/non-pending alerts, then set `state`, `ignored_reason`, and `ignored_at`.

- [ ] **Step 7: Run service tests**

Run: `pytest tests/unit/test_xianyu_order_service.py tests/unit/test_xianyu_order_reconciliation_service.py -v`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add app/services/xianyu_order_service.py app/services/xianyu_order_reconciliation_service.py tests/unit/test_xianyu_order_service.py tests/unit/test_xianyu_order_reconciliation_service.py
git commit -m "feat: reconcile missing Xianyu orders"
```

### Task 3: Internal APIs and ten-minute scheduler

**Files:**
- Create: `app/handlers/xianyu_order_alert_handlers.py`
- Create: `app/routes/xianyu_order_alert_api.py`
- Modify: `app/routes/web.py`
- Modify: `app/utils/scheduler.py`
- Modify: `app/utils/scheduler_tasks.py`
- Test: `tests/integration/test_xianyu_order_alert_api.py`

**Interfaces:**
- Produces: `GET /api/xianyu-order-alerts`
- Produces: `POST /api/xianyu-order-alerts/refresh`
- Produces: `POST /api/xianyu-order-alerts/<order_no>/ignore` with `{"reason": string}`

- [ ] **Step 1: Write failing endpoint tests**

```python
def test_get_alerts_returns_snapshot(client, monkeypatch):
    monkeypatch.setattr(
        XianyuOrderAlertHandlers.service,
        "get_snapshot",
        lambda: {"alerts": [{"order_no": "XY-1"}], "count": 1, "sync": {}, "refreshing": False},
    )
    response = client.get("/api/xianyu-order-alerts")
    assert response.status_code == 200
    assert response.get_json()["data"]["count"] == 1


def test_ignore_requires_reason(client):
    response = client.post("/api/xianyu-order-alerts/XY-1/ignore", json={"reason": " "})
    assert response.status_code == 400
```

- [ ] **Step 2: Run endpoint tests**

Run: `pytest tests/integration/test_xianyu_order_alert_api.py -v`

Expected: FAIL because the route is not registered.

- [ ] **Step 3: Add handler and route**

Implement handlers that return `success(data=snapshot)`, validate `reason.strip()`, map a missing pending alert to `not_found`, and map unexpected failures to `server_error`. Register the route blueprint through `app/routes/web.py`.

```python
@bp.get("/api/xianyu-order-alerts")
@handle_response
def get_alerts():
    return XianyuOrderAlertHandlers.get_alerts()

@bp.post("/api/xianyu-order-alerts/refresh")
@handle_response
def refresh_alerts():
    return XianyuOrderAlertHandlers.refresh_alerts()

@bp.post("/api/xianyu-order-alerts/<order_no>/ignore")
@handle_response
def ignore_alert(order_no):
    return XianyuOrderAlertHandlers.ignore_alert(order_no)
```

- [ ] **Step 4: Register the scheduled job**

Add:

```python
def reconcile_xianyu_orders(app=None):
    if app is None:
        app = current_app._get_current_object()
    with app.app_context():
        XianyuOrderReconciliationService().reconcile()
```

Register it with:

```python
scheduler.add_job(
    func=lambda: reconcile_xianyu_orders(app),
    trigger=IntervalTrigger(minutes=10),
    id="reconcile_xianyu_orders",
    name="检查闲鱼漏录订单",
    replace_existing=True,
)
```

- [ ] **Step 5: Run API and scheduler-focused tests**

Run: `pytest tests/integration/test_xianyu_order_alert_api.py tests/unit/test_xianyu_order_reconciliation_service.py -v`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/handlers/xianyu_order_alert_handlers.py app/routes/xianyu_order_alert_api.py app/routes/web.py app/utils/scheduler.py app/utils/scheduler_tasks.py tests/integration/test_xianyu_order_alert_api.py
git commit -m "feat: expose and schedule Xianyu order alerts"
```

### Task 4: Inline Gantt warning component

**Files:**
- Create: `frontend/src/types/xianyuOrderAlert.ts`
- Create: `frontend/src/composables/useXianyuOrderAlerts.ts`
- Create: `frontend/src/components/XianyuOrderAlertBar.vue`
- Create: `frontend/tests/unit/components/XianyuOrderAlertBar.spec.ts`

**Interfaces:**
- Produces: `useXianyuOrderAlerts()` with `snapshot`, `loading`, `load()`, `refresh()`, `ignore(orderNo, reason)`, `startPolling()`, and `stopPolling()`
- Produces component events: `book(orderNo: string)` and `ignored()`

- [ ] **Step 1: Write failing component tests**

```typescript
it('shows count and emits the selected order for booking', async () => {
  const wrapper = mount(XianyuOrderAlertBar, {
    props: { snapshot: makeSnapshot('XY-1'), loading: false }
  })
  expect(wrapper.text()).toContain('发现 1 笔待发货订单尚未录入库存管理')
  await wrapper.get('[data-testid="toggle-alerts"]').trigger('click')
  await wrapper.get('[data-testid="book-XY-1"]').trigger('click')
  expect(wrapper.emitted('book')).toEqual([['XY-1']])
})
```

- [ ] **Step 2: Run the component test**

Run: `cd frontend && npm run test:run -- tests/unit/components/XianyuOrderAlertBar.spec.ts`

Expected: FAIL because the component does not exist.

- [ ] **Step 3: Implement types and composable**

Define:

```typescript
export interface XianyuOrderAlert {
  order_no: string
  pay_amount: number
  buyer_nick?: string | null
  receiver_name?: string | null
  receiver_mobile?: string | null
  address?: string | null
  goods_title?: string | null
  goods_sku_text?: string | null
  order_time?: string | null
}

export interface XianyuOrderAlertSnapshot {
  alerts: XianyuOrderAlert[]
  count: number
  refreshing: boolean
  sync: {
    last_attempt_at?: string | null
    last_success_at?: string | null
    last_error?: string | null
  }
}
```

The composable must GET cached data, POST refresh, POST ignore, retain its current snapshot if an Axios request fails, and poll only the cache endpoint every 60 seconds.

- [ ] **Step 4: Implement the inline warning component**

Render nothing only when `count === 0`, there is a successful sync, and there is no current error. Otherwise render an Element Plus warning area with count, expand/collapse, refresh, stale/error copy, and an inline table. Use `ElMessageBox.prompt` for a required ignore reason, then a second `ElMessageBox.confirm` containing “永久忽略且无法恢复”, and emit the validated `{orderNo, reason}` to the parent.

- [ ] **Step 5: Run component tests and type-check**

Run: `cd frontend && npm run test:run -- tests/unit/components/XianyuOrderAlertBar.spec.ts && npm run type-check`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/types/xianyuOrderAlert.ts frontend/src/composables/useXianyuOrderAlerts.ts frontend/src/components/XianyuOrderAlertBar.vue frontend/tests/unit/components/XianyuOrderAlertBar.spec.ts
git commit -m "feat: add inline Xianyu order warning"
```

### Task 5: Reuse BookingDialog and integrate the Gantt flow

**Files:**
- Modify: `frontend/src/components/BookingDialog.vue`
- Modify: `frontend/src/components/GanttChart.vue`
- Modify: `openspec/changes/add-xianyu-missing-order-alerts/tasks.md`
- Test: `frontend/tests/unit/components/XianyuOrderAlertBar.spec.ts`

**Interfaces:**
- Consumes: `initialXianyuOrderNo?: string`
- Consumes: `book(orderNo)` and `ignore({orderNo, reason})` component events

- [ ] **Step 1: Extend the existing booking dialog**

Add `initialXianyuOrderNo?: string` to `Props`. When `modelValue` changes to true, load devices as before, then:

```typescript
if (props.initialXianyuOrderNo) {
  form.value.xianyuOrderNo = props.initialXianyuOrderNo
  await nextTick()
  await handleFetchOrderInfo()
}
```

Do not prefill dates, device, model, logistics days, bundled accessories, phone holder, tripod, photo transfer, or lens combination.

- [ ] **Step 2: Integrate the warning into GanttChart**

Add state:

```typescript
const bookingOrderNo = ref<string>()
const {
  snapshot: xianyuAlertSnapshot,
  loading: xianyuAlertsLoading,
  load: loadXianyuAlerts,
  refresh: refreshXianyuAlerts,
  ignore: ignoreXianyuAlert,
  startPolling: startXianyuAlertPolling,
  stopPolling: stopXianyuAlertPolling
} = useXianyuOrderAlerts()

const startMissingOrderBooking = (orderNo: string) => {
  bookingOrderNo.value = orderNo
  showBookingDialog.value = true
}
```

Place `XianyuOrderAlertBar` between `.toolbar` and `.filters`. Pass `:initial-xianyu-order-no="bookingOrderNo"` to the existing `BookingDialog`. Clear `bookingOrderNo` after the dialog closes. After booking success, call `loadXianyuAlerts()` so a newly recorded order disappears immediately. On mount, load the cache, start cache polling, and then refresh externally without blocking Gantt loading. On unmount, stop polling.

- [ ] **Step 3: Verify the frontend**

Run: `cd frontend && npm run test:run -- tests/unit/components/XianyuOrderAlertBar.spec.ts && npm run build`

Expected: component tests, Vue type-check, and Vite production build all PASS.

- [ ] **Step 4: Run the backend regression suite**

Run: `pytest tests/unit/test_xianyu_order_service.py tests/unit/test_xianyu_order_reconciliation_service.py tests/integration/test_xianyu_order_alert_api.py tests/integration/test_rental_api.py -v`

Expected: PASS.

- [ ] **Step 5: Validate OpenSpec and update task status**

Run: `openspec validate add-xianyu-missing-order-alerts --strict`

Expected: `Change 'add-xianyu-missing-order-alerts' is valid`.

Mark every completed checkbox in `openspec/changes/add-xianyu-missing-order-alerts/tasks.md` as checked.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/components/BookingDialog.vue frontend/src/components/GanttChart.vue openspec/changes/add-xianyu-missing-order-alerts/tasks.md
git commit -m "feat: integrate missing orders into booking flow"
```

- [ ] **Step 7: Final verification**

Run:

```bash
git diff --check
pytest tests/unit/test_xianyu_order_service.py tests/unit/test_xianyu_order_reconciliation_service.py tests/integration/test_xianyu_order_alert_api.py -v
cd frontend && npm run test:run -- tests/unit/components/XianyuOrderAlertBar.spec.ts && npm run build
```

Expected: no whitespace errors; all selected tests and production build pass.

