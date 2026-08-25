from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import DEFAULT, Mock

import pytest
import schedule

from app import create_app, db
from app.control.models import ControlBase, Tenant
from app.control.store import ControlStore
from app.crypto import SecretBox
from app.models.device import Device
from app.models.rental import Rental
from app.models.warehouse import Warehouse
from app.models.xianyu_shop import XianyuShop
from app.tenant_context import current_tenant_id


MASTER_KEY = "AAECAwQFBgcICQoLDA0ODxAREhMUFRYXGBkaGxwdHh8="
NOW = datetime(2026, 8, 25, 12)


class FakeConnection:
    def __init__(self, lock_result):
        self.lock_result = lock_result
        self.statements = []
        self.closed = False

    def execute(self, statement, parameters=None):
        sql = str(statement)
        self.statements.append((sql, parameters))
        value = self.lock_result if any(key in sql for key in ("GET_LOCK", "CONNECTION_ID", "IS_USED_LOCK")) else 1
        return SimpleNamespace(scalar_one=lambda: value)

    def close(self):
        self.closed = True


class FakeStore:
    def __init__(self, lock_result):
        self.connection = FakeConnection(lock_result)
        self.engine = SimpleNamespace(connect=lambda: self.connection)
        self.disposed = False

    def dispose(self):
        self.disposed = True


class FakeRegistry:
    def __init__(self):
        self.seen = []
        self.disposed = False

    def get(self, tenant):
        self.seen.append(tenant.id)
        return object()

    def dispose_all(self):
        self.disposed = True


def _lock_worker(lock_result, sleeper=lambda _seconds: None):
    from worker import Worker

    store, registry = FakeStore(lock_result), FakeRegistry()
    app = SimpleNamespace(extensions={
        "control_store": store, "tenant_engine_registry": registry,
    })
    return Worker(app, scheduler=schedule.Scheduler(), sleeper=sleeper), store, registry


def test_worker_stops_between_startup_cycles_when_lock_is_lost_and_releases():
    worker, store, registry = _lock_worker(1)
    events = []
    worker.run_scheduled_shipping_cycle = lambda: (events.append("shipping"), setattr(store.connection, "lock_result", 0))
    worker._eligible_tenants = lambda: events.append("xianyu") or []
    worker.register_jobs()

    with pytest.raises(RuntimeError, match="lock ownership lost"): worker.run_forever()
    assert events == ["shipping"]
    assert [(job.interval, job.unit) for job in worker.scheduler.jobs] == [
        (60, "seconds"), (180, "seconds"),
    ]
    assert "GET_LOCK" in store.connection.statements[1][0]
    assert store.connection.statements[1][1]["name"] == "inventory-manager-worker-v1"
    assert "RELEASE_LOCK" in store.connection.statements[-1][0]
    assert store.connection.closed and store.disposed and registry.disposed


def test_second_worker_exits_without_entering_standby():
    sleeps = []
    worker, store, registry = _lock_worker(0, sleeps.append)

    assert worker.run_forever() is False
    assert sleeps == []
    assert store.connection.closed and store.disposed and registry.disposed
    assert len(store.connection.statements) == 3


def test_cycle_filters_tenants_and_cleans_binding_after_each(tmp_path, monkeypatch):
    import worker as worker_module

    box = SecretBox.from_base64(MASTER_KEY)
    store = ControlStore(f"sqlite+pysqlite:///{tmp_path / 'control.db'}", box)
    ControlBase.metadata.create_all(store.engine)
    with store.session() as session:
        for tenant_id, status, provisioning, expiry in [
            (5, "active", "active", NOW + timedelta(days=1)),
            (2, "suspended", "active", NOW + timedelta(days=1)),
            (3, "active", "active", NOW),
            (4, "active", "failed", NOW + timedelta(days=1)),
            (1, "active", "active", NOW + timedelta(days=1)),
        ]:
            session.add(Tenant(
                id=tenant_id, name=str(tenant_id), status=status,
                provisioning_status=provisioning, expires_at=expiry,
                db_name=f"tenant_{tenant_id}", db_username=f"user_{tenant_id}",
                db_password_ciphertext=box.encrypt("pw", "tenant-db-password"),
            ))
    app = create_app("testing")
    registry = FakeRegistry()
    app.extensions.update(control_store=store, tenant_engine_registry=registry)
    observed = []

    def task():
        observed.append(current_tenant_id())
        if current_tenant_id() == 1:
            raise RuntimeError("private")

    original_remove = worker_module.db.session.remove
    monkeypatch.setattr(worker_module, "process_scheduled_shipments_for_current_tenant", task)
    monkeypatch.setattr(worker_module.db.session, "remove", Mock(wraps=original_remove, side_effect=[RuntimeError("remove"), DEFAULT, DEFAULT, DEFAULT]))
    monkeypatch.setattr(worker_module, "reset_tenant", Mock(wraps=worker_module.reset_tenant, side_effect=[RuntimeError("reset"), DEFAULT]))
    worker = worker_module.Worker(app, clock=lambda: NOW)
    worker.run_scheduled_shipping_cycle()

    assert observed == [1, 5]
    assert registry.seen == [1, 5]
    assert current_tenant_id() is None
    worker.shutdown()
    app.extensions["tenant_resource_finalizer"]()


@pytest.fixture
def business_app():
    application = create_app("testing")
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.mark.parametrize(
    "mode,expected", [
        ("success", "shipped"), ("failure", "scheduled_for_shipping"),
        ("exception", "scheduled_for_shipping"), ("no-shop", "shipped"),
    ],
)
def test_scheduled_shipping_isolates_each_main_rental_and_children(
    business_app, monkeypatch, mode, expected,
):
    import app.services.xianyu_order_service as xianyu_module
    from app.utils.scheduler_tasks import process_scheduled_shipments_for_current_tenant

    with business_app.app_context():
        warehouse = Warehouse(province="粤", city="深", name="仓")
        shop = XianyuShop(name="店", app_key="key", is_active=True)
        db.session.add(warehouse)
        db.session.flush()
        devices = [Device(name=str(i), model="x200u",
                          warehouse_id=warehouse.id) for i in range(3)]
        db.session.add_all([shop, *devices])
        db.session.flush()
        main = Rental(
            device_id=devices[0].id, warehouse_id=warehouse.id,
            start_date=date.today(), end_date=date.today(), customer_name="A",
            status="scheduled_for_shipping", scheduled_ship_time=NOW,
            ship_out_tracking_no="SF1", xianyu_order_no="XY1",
            xianyu_shop_id=None if mode == "no-shop" else shop.id,
        )
        db.session.add(main)
        db.session.flush()
        child = Rental(
            device_id=devices[1].id, warehouse_id=warehouse.id,
            start_date=date.today(), end_date=date.today(), customer_name="A",
            status="scheduled_for_shipping", scheduled_ship_time=NOW,
            parent_rental_id=main.id,
        )
        offline = Rental(
            device_id=devices[2].id, warehouse_id=warehouse.id,
            start_date=date.today(), end_date=date.today(), customer_name="B",
            status="scheduled_for_shipping", scheduled_ship_time=NOW,
        )
        db.session.add_all([child, offline])
        db.session.commit()
        calls = []
        def ship_order(rental):
            calls.append(rental.id)
            if mode == "exception":
                raise RuntimeError("private")
            return {"success": mode == "success"}

        monkeypatch.setattr(xianyu_module, "get_xianyu_service", lambda **_kwargs: SimpleNamespace(ship_order=ship_order))
        monkeypatch.setattr("app.utils.scheduler_tasks.datetime", SimpleNamespace(utcnow=lambda: NOW))
        process_scheduled_shipments_for_current_tenant()
        db.session.expire_all()

        rows = [db.session.get(Rental, row.id) for row in (main, child, offline)]
        assert [row.status for row in rows] == [expected, expected, "shipped"]
        expected_times = [NOW, NOW] if expected == "shipped" else [None, None]
        assert [row.ship_out_time for row in rows[:2]] == expected_times
        assert calls == ([] if mode == "no-shop" else [main.id])


def test_shop_reconciliation_orders_active_shops_and_continues(business_app, monkeypatch):
    from app.services.xianyu_order_reconciliation_service import XianyuOrderReconciliationService
    from app.utils.scheduler_tasks import reconcile_active_shops_for_current_tenant

    with business_app.app_context():
        db.session.add_all([
            XianyuShop(id=3, name="C", app_key="c", is_active=True),
            XianyuShop(id=1, name="A", app_key="a", is_active=True),
            XianyuShop(id=2, name="B", app_key="b", is_active=False),
        ])
        db.session.commit()
        calls = []

        def reconcile(_service, shop_id):
            calls.append(shop_id)
            if shop_id == 1:
                raise RuntimeError("private")

        monkeypatch.setattr(XianyuOrderReconciliationService, "reconcile_shop", reconcile)
        reconcile_active_shops_for_current_tenant()

        assert calls == [1, 3]
