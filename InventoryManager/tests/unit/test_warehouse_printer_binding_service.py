from __future__ import annotations

from datetime import datetime, timezone

import pytest

from app import create_app, db
from app.models.warehouse import Warehouse, WarehousePrinter
from app.services.warehouse import (
    WarehousePrinterBindingConflictError,
    WarehousePrinterBindingService,
    WarehousePrinterBindingTransactionError,
    WarehousePrinterBindingUnavailableError,
)


NOW = datetime(2026, 8, 23, 6, 0, tzinfo=timezone.utc)


@pytest.fixture
def application():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        try:
            yield app
        finally:
            db.session.remove()
            db.drop_all()


def _warehouse(name: str, *, active: bool = True) -> Warehouse:
    return Warehouse(
        name=name,
        status="active" if active else "inactive",
        setup_state="ready",
        is_default=False,
        contact_name="联系人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="测试路 1 号",
    )


def test_verified_binding_is_exactly_replayable_and_resolvable(application):
    session = db.session()
    with session.begin():
        warehouse = _warehouse("默认仓")
        session.add(warehouse)
        session.flush()
        warehouse_id = warehouse.id
        created = WarehousePrinterBindingService(
            session
        ).bind_verified_kuaimai_printer(
            warehouse_id=warehouse_id,
            printer_sn="KM-001",
            display_name="前台打印机",
            verified_at=NOW,
        )
    with session.begin():
        service = WarehousePrinterBindingService(session)
        replay = service.bind_verified_kuaimai_printer(
            warehouse_id=warehouse_id,
            printer_sn="KM-001",
            display_name="前台打印机",
            verified_at=NOW,
        )
        resolved = service.resolve_active_kuaimai_printer(
            warehouse_id=warehouse_id,
            expected_printer_sn="KM-001",
        )

    assert created.printer_sn == "KM-001"
    assert replay.idempotent_replay is True
    assert resolved.warehouse_uuid == created.warehouse_uuid
    assert resolved.last_verified_at == NOW


def test_rebind_updates_only_current_pointer_and_old_print_snapshot_is_external(
    application,
):
    session = db.session()
    with session.begin():
        warehouse = _warehouse("默认仓")
        session.add(warehouse)
        session.flush()
        warehouse_id = warehouse.id
        service = WarehousePrinterBindingService(session)
        service.bind_verified_kuaimai_printer(
            warehouse_id=warehouse_id,
            printer_sn="KM-OLD",
            display_name="旧打印机",
            verified_at=NOW,
        )
    with session.begin():
        rebound = WarehousePrinterBindingService(
            session
        ).bind_verified_kuaimai_printer(
            warehouse_id=warehouse_id,
            printer_sn="KM-NEW",
            display_name="新打印机",
            verified_at=NOW,
        )

    assert rebound.printer_sn == "KM-NEW"
    assert session.query(WarehousePrinter).one().printer_sn == "KM-NEW"


def test_printer_sn_cannot_be_bound_to_two_warehouses(application):
    session = db.session()
    with session.begin():
        first = _warehouse("一仓")
        second = _warehouse("二仓")
        session.add_all((first, second))
        session.flush()
        service = WarehousePrinterBindingService(session)
        service.bind_verified_kuaimai_printer(
            warehouse_id=first.id,
            printer_sn="KM-SHARED",
            display_name="共享打印机",
            verified_at=NOW,
        )
        with pytest.raises(WarehousePrinterBindingConflictError):
            service.bind_verified_kuaimai_printer(
                warehouse_id=second.id,
                printer_sn="KM-SHARED",
                display_name="共享打印机",
                verified_at=NOW,
            )


@pytest.mark.parametrize(
    ("status", "verified"),
    [
        ("inactive", True),
        ("verification_failed", True),
        ("active", False),
    ],
)
def test_noncurrent_binding_never_resolves(application, status, verified):
    session = db.session()
    with session.begin():
        warehouse = _warehouse("默认仓")
        session.add(warehouse)
        session.flush()
        session.add(
            WarehousePrinter(
                warehouse_id=warehouse.id,
                printer_sn="KM-001",
                display_name="打印机",
                provider="kuaimai",
                status=status,
                last_verified_at=NOW if verified else None,
            )
        )
        warehouse_id = warehouse.id

    with session.begin(), pytest.raises(
        WarehousePrinterBindingUnavailableError
    ):
        WarehousePrinterBindingService(
            session
        ).resolve_active_kuaimai_printer(warehouse_id=warehouse_id)


def test_binding_service_requires_explicit_transaction(application):
    session = db.session()

    with pytest.raises(WarehousePrinterBindingTransactionError):
        WarehousePrinterBindingService(session).resolve_active_kuaimai_printer(
            warehouse_id=1
        )
