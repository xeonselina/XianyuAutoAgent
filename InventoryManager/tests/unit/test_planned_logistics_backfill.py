from __future__ import annotations

import hashlib
from datetime import date
from uuid import UUID

import pytest
import sqlalchemy as sa

from app import create_app, db
from app.models.database_identity import TenantDatabaseIdentity
from app.models.device import Device
from app.models.rental import Rental
from app.services.migration.planned_logistics_backfill import (
    PlannedLogisticsBackfillConflictError,
    PlannedLogisticsBackfillEntry,
    PlannedLogisticsBackfillIdentityMismatchError,
    PlannedLogisticsBackfillInputError,
    PlannedLogisticsBackfillPlan,
    PlannedLogisticsBackfillService,
    PlannedLogisticsBackfillTransactionError,
)
from inventory_control.default_migration import DefaultTenantMigrationManifest


TENANT_UUID = UUID("50000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("50000000-0000-4000-8000-000000000002")
SCHEMA_GENERATION = 9


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-logistics-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID(
            "50000000-0000-4000-8000-000000000003"
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
                schema_generation=SCHEMA_GENERATION,
            )
        )
        db.session.commit()
        try:
            yield app
        finally:
            db.session.remove()
            db.drop_all()


def _rental(device, *, parent=None, status="not_shipped"):
    return Rental(
        device=device,
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 12),
        customer_name="fixture",
        status=status,
        parent_rental=parent,
    )


def _plan(manifest, main, *, children=(), days=2):
    return PlannedLogisticsBackfillPlan(
        parent_manifest_digest=manifest.digest,
        migration_idempotency_key=manifest.migration_idempotency_key,
        entries=(
            PlannedLogisticsBackfillEntry(
                rental_id=main.id,
                expected_device_id=main.device_id,
                expected_start_date=main.start_date,
                expected_end_date=main.end_date,
                expected_status=main.status,
                logistics_days=days,
                expected_child_rental_ids=tuple(
                    sorted(item.id for item in children)
                ),
            ),
        ),
    )


def _backfill(manifest, plan):
    session = db.session()
    if session.in_transaction():
        session.rollback()
    with session.begin():
        return PlannedLogisticsBackfillService().backfill(
            session,
            manifest=manifest,
            expected_schema_generation=SCHEMA_GENERATION,
            plan=plan,
        )


def test_backfill_updates_exact_main_child_group_and_replays(application) -> None:
    manifest = _manifest()
    main_device = Device(name="main", model="x200u", is_accessory=False)
    accessory = Device(name="tripod", model="tripod", is_accessory=True)
    main = _rental(main_device)
    child = _rental(accessory, parent=main)
    db.session.add_all((main_device, accessory, main, child))
    db.session.commit()
    plan = _plan(manifest, main, children=(child,), days=2)

    first = _backfill(manifest, plan)
    replay = _backfill(manifest, plan)

    assert first.main_rental_count == 1
    assert first.child_rental_count == 1
    assert first.updated_row_count == 2
    assert first.idempotent_replay is False
    assert replay.updated_row_count == 0
    assert replay.idempotent_replay is True
    assert replay.plan_digest == first.plan_digest
    assert replay.result_digest == first.result_digest
    for rental_id in (main.id, child.id):
        rental = db.session.get(Rental, rental_id)
        assert rental.logistics_days == 2
        assert rental.planned_ship_out_date == date(2026, 9, 7)
        assert rental.planned_return_date == date(2026, 9, 15)


def test_partial_existing_fields_conflict_and_roll_back_whole_plan(application) -> None:
    manifest = _manifest()
    first_device = Device(name="first", model="x200u")
    second_device = Device(name="second", model="x200u")
    first = _rental(first_device)
    second = _rental(second_device)
    second.logistics_days = 2
    db.session.add_all((first_device, second_device, first, second))
    db.session.commit()
    plan = PlannedLogisticsBackfillPlan(
        parent_manifest_digest=manifest.digest,
        migration_idempotency_key=manifest.migration_idempotency_key,
        entries=tuple(
            sorted(
                (
                    PlannedLogisticsBackfillEntry(
                        rental_id=item.id,
                        expected_device_id=item.device_id,
                        expected_start_date=item.start_date,
                        expected_end_date=item.end_date,
                        expected_status=item.status,
                        logistics_days=2,
                    )
                    for item in (first, second)
                ),
                key=lambda item: item.rental_id,
            )
        ),
    )

    with pytest.raises(PlannedLogisticsBackfillConflictError):
        _backfill(manifest, plan)

    db.session.expire_all()
    assert db.session.get(Rental, first.id).logistics_days is None
    assert db.session.get(Rental, second.id).planned_ship_out_date is None


def test_unlisted_or_changed_child_fails_closed(application) -> None:
    manifest = _manifest()
    main_device = Device(name="main", model="x200u")
    accessory = Device(name="tripod", model="tripod", is_accessory=True)
    main = _rental(main_device)
    child = _rental(accessory, parent=main)
    db.session.add_all((main_device, accessory, main, child))
    db.session.commit()

    with pytest.raises(PlannedLogisticsBackfillConflictError):
        _backfill(manifest, _plan(manifest, main, children=()))

    child.status = "shipped"
    db.session.commit()
    with pytest.raises(PlannedLogisticsBackfillConflictError):
        _backfill(manifest, _plan(manifest, main, children=(child,)))


def test_wrong_database_identity_and_manifest_binding_are_rejected(application) -> None:
    manifest = _manifest()
    device = Device(name="main", model="x200u")
    main = _rental(device)
    db.session.add_all((device, main))
    db.session.commit()
    plan = _plan(manifest, main)
    identity = db.session.scalar(sa.select(TenantDatabaseIdentity))
    identity.schema_generation += 1
    db.session.commit()

    with pytest.raises(PlannedLogisticsBackfillIdentityMismatchError):
        _backfill(manifest, plan)

    changed = _manifest()
    object.__setattr__(changed, "migration_bundle_digest", _digest("changed"))
    with pytest.raises(PlannedLogisticsBackfillInputError):
        _backfill(changed, plan)


def test_service_requires_explicit_transaction_and_plan_is_canonical(application):
    manifest = _manifest()
    device = Device(name="main", model="x200u")
    main = _rental(device)
    db.session.add_all((device, main))
    db.session.commit()
    plan = _plan(manifest, main)
    assert plan.canonical_bytes() == plan.canonical_bytes()

    with pytest.raises(PlannedLogisticsBackfillTransactionError):
        PlannedLogisticsBackfillService().backfill(
            db.session(),
            manifest=manifest,
            expected_schema_generation=SCHEMA_GENERATION,
            plan=plan,
        )
