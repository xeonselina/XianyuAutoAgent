from __future__ import annotations

import hashlib
from datetime import date, datetime, timezone
from uuid import UUID

import pytest
import sqlalchemy as sa

from app import create_app, db
from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    AccessoryUnitEvent,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.database_identity import TenantDatabaseIdentity
from app.models.device import Device
from app.models.rental import Rental
from app.models.warehouse import Warehouse
from app.services.migration.logical_accessory_backfill import (
    LegacyAccessoryRequestEntry,
    LegacyAccessoryUnitEntry,
    LogicalAccessoryBackfillConflictError,
    LogicalAccessoryBackfillPlan,
    LogicalAccessoryBackfillService,
)
from inventory_control.default_migration import DefaultTenantMigrationManifest


TENANT_UUID = UUID("80000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("80000000-0000-4000-8000-000000000002")
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-accessories-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID(
            "80000000-0000-4000-8000-000000000003"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


@pytest.fixture
def application():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        db.session.add(
            TenantDatabaseIdentity(
                singleton_key=1,
                tenant_id=str(TENANT_UUID),
                database_uuid=str(DATABASE_UUID),
                schema_generation=9,
            )
        )
        warehouse = Warehouse(
            warehouse_uuid="80000000-0000-4000-8000-000000000010",
            name="fixture",
            status="active",
            setup_state="ready",
            is_default=True,
            default_slot=1,
            contact_name="fixture",
            contact_phone="13800138000",
            province="广东省",
            city="深圳市",
            district="南山区",
            address_detail="fixture",
        )
        accessory_type = AccessoryType(
            name="tripod",
            display_name="三脚架",
            tracking_mode="logical_unit",
            is_active=True,
            display_order=1,
        )
        db.session.add_all((warehouse, accessory_type))
        db.session.commit()
        try:
            yield app, warehouse.id, accessory_type.id
        finally:
            db.session.remove()
            db.drop_all()


def _rental(device, *, parent=None, status="not_shipped"):
    return Rental(
        device=device,
        parent_rental=parent,
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 12),
        planned_ship_out_date=date(2026, 9, 7),
        planned_return_date=date(2026, 9, 15),
        logistics_days=2,
        customer_name="fixture",
        status=status,
    )


def _plan(manifest, unit_device, warehouse_id, type_id, *, child=None, linked=True):
    requests = ()
    if child is not None:
        requests = (
            LegacyAccessoryRequestEntry(
                child_rental_id=child.id,
                main_rental_id=child.parent_rental_id,
                accessory_type_id=type_id,
                linked_legacy_device_id=(unit_device.id if linked else None),
            ),
        )
    return LogicalAccessoryBackfillPlan(
        parent_manifest_digest=manifest.digest,
        migration_idempotency_key=manifest.migration_idempotency_key,
        units=(
            LegacyAccessoryUnitEntry(
                legacy_device_id=unit_device.id,
                accessory_type_id=type_id,
                expected_warehouse_id=warehouse_id,
                expected_lifecycle_status=unit_device.lifecycle_status,
                reliable_and_available=(
                    unit_device.lifecycle_status == "active"
                ),
            ),
        ),
        requests=requests,
    )


def _backfill(manifest, plan):
    session = db.session()
    if session.in_transaction():
        session.rollback()
    with session.begin():
        return LogicalAccessoryBackfillService(clock=lambda: NOW).backfill(
            session,
            manifest=manifest,
            expected_schema_generation=9,
            plan=plan,
        )


def test_not_shipped_child_creates_unit_request_link_and_exactly_replays(
    application,
) -> None:
    _app, warehouse_id, type_id = application
    manifest = _manifest()
    main_device = Device(name="main", model="x200u", warehouse_id=warehouse_id)
    accessory = Device(
        name="legacy tripod",
        model="tripod",
        is_accessory=True,
        warehouse_id=warehouse_id,
        lifecycle_status="active",
    )
    main = _rental(main_device)
    child = _rental(accessory, parent=main)
    db.session.add_all((main_device, accessory, main, child))
    db.session.commit()
    plan = _plan(manifest, accessory, warehouse_id, type_id, child=child)

    first = _backfill(manifest, plan)
    replay = _backfill(manifest, plan)

    assert first.unit_count == first.request_count == first.link_count == 1
    assert first.holder_count == 0
    assert first.created_event_count == first.linked_event_count == 1
    assert first.dispatched_event_count == 0
    assert first.created_fact_count == 5
    assert replay.idempotent_replay is True
    assert replay.created_fact_count == 0
    assert replay.result_digest == first.result_digest
    unit = db.session.scalar(sa.select(AccessoryUnit))
    assert unit.legacy_source_type == "device"
    assert unit.legacy_source_id == str(accessory.id)
    assert unit.current_holder_rental_id is None
    assert db.session.scalar(
        sa.select(sa.func.count()).select_from(RentalAccessoryRequest)
    ) == 1
    assert db.session.scalar(
        sa.select(sa.func.count()).select_from(RentalAccessoryUnitLink)
    ) == 1
    assert db.session.scalar(
        sa.select(sa.func.count()).select_from(AccessoryUnitEvent)
    ) == 2


def test_shipped_child_sets_main_holder_and_dispatched_event(application) -> None:
    _app, warehouse_id, type_id = application
    manifest = _manifest()
    main_device = Device(name="main", model="x200u", warehouse_id=warehouse_id)
    accessory = Device(
        name="legacy tripod",
        model="tripod",
        is_accessory=True,
        warehouse_id=warehouse_id,
        lifecycle_status="active",
    )
    main = _rental(main_device, status="shipped")
    child = _rental(accessory, parent=main, status="shipped")
    db.session.add_all((main_device, accessory, main, child))
    db.session.commit()

    result = _backfill(
        manifest,
        _plan(manifest, accessory, warehouse_id, type_id, child=child),
    )

    assert result.holder_count == 1
    assert result.dispatched_event_count == 1
    unit = db.session.scalar(sa.select(AccessoryUnit))
    assert unit.current_holder_rental_id == main.id
    dispatched = db.session.scalar(
        sa.select(AccessoryUnitEvent).where(
            AccessoryUnitEvent.event_type == "dispatched"
        )
    )
    assert dispatched.to_holder_rental_id == main.id
    assert dispatched.reason == "migration"


def test_unreliable_unit_is_unavailable_and_has_no_link(application) -> None:
    _app, warehouse_id, type_id = application
    manifest = _manifest()
    accessory = Device(
        name="uncertain legacy item",
        model="unknown",
        is_accessory=True,
        warehouse_id=warehouse_id,
        lifecycle_status="damaged",
    )
    db.session.add(accessory)
    db.session.commit()

    result = _backfill(
        manifest,
        _plan(manifest, accessory, warehouse_id, type_id),
    )

    assert result.unit_count == 1
    assert result.request_count == result.link_count == 0
    assert db.session.scalar(sa.select(AccessoryUnit)).condition_status == (
        "maintenance"
    )


def test_unlisted_child_or_unlinked_shipped_child_fails_without_facts(
    application,
) -> None:
    _app, warehouse_id, type_id = application
    manifest = _manifest()
    main_device = Device(name="main", model="x200u", warehouse_id=warehouse_id)
    accessory = Device(
        name="legacy tripod",
        model="tripod",
        is_accessory=True,
        warehouse_id=warehouse_id,
    )
    main = _rental(main_device, status="shipped")
    child = _rental(accessory, parent=main, status="shipped")
    db.session.add_all((main_device, accessory, main, child))
    db.session.commit()

    with pytest.raises(LogicalAccessoryBackfillConflictError):
        _backfill(
            manifest,
            _plan(manifest, accessory, warehouse_id, type_id, child=None),
        )
    with pytest.raises(LogicalAccessoryBackfillConflictError):
        _backfill(
            manifest,
            _plan(
                manifest,
                accessory,
                warehouse_id,
                type_id,
                child=child,
                linked=False,
            ),
        )

    assert db.session.scalar(
        sa.select(sa.func.count()).select_from(AccessoryUnit)
    ) == 0
    assert db.session.scalar(
        sa.select(sa.func.count()).select_from(AccessoryUnitEvent)
    ) == 0
