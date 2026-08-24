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
from app.services.migration.structured_address_backfill import (
    StructuredAddressBackfillConflictError,
    StructuredAddressBackfillIdentityMismatchError,
    StructuredAddressBackfillInputError,
    StructuredAddressBackfillPlan,
    StructuredAddressBackfillService,
    StructuredAddressBackfillTransactionError,
    StructuredRentalAddressEntry,
    legacy_destination_digest,
)
from inventory_control.default_migration import DefaultTenantMigrationManifest


TENANT_UUID = UUID("51000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("51000000-0000-4000-8000-000000000002")
SCHEMA_GENERATION = 9


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-address-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID(
            "51000000-0000-4000-8000-000000000003"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="20260824_legacy_history",
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


def _rental(device, *, destination, parent=None):
    return Rental(
        device=device,
        start_date=date(2026, 9, 10),
        end_date=date(2026, 9, 12),
        customer_name="fixture",
        customer_phone="13800000000",
        destination=destination,
        parent_rental=parent,
        status="not_shipped",
    )


def _entry(rental, *, address_detail="复核路1号"):
    return StructuredRentalAddressEntry(
        rental_id=rental.id,
        expected_parent_rental_id=rental.parent_rental_id,
        expected_legacy_destination_digest=legacy_destination_digest(
            rental.destination
        ),
        province="北京市",
        city="北京市",
        district="朝阳区",
        address_detail=address_detail,
    )


def _plan(manifest, *rentals):
    return StructuredAddressBackfillPlan(
        parent_manifest_digest=manifest.digest,
        migration_idempotency_key=manifest.migration_idempotency_key,
        entries=tuple(sorted((_entry(item) for item in rentals), key=lambda x: x.rental_id)),
    )


def _backfill(manifest, plan):
    session = db.session()
    if session.in_transaction():
        session.rollback()
    with session.begin():
        return StructuredAddressBackfillService().backfill(
            session,
            manifest=manifest,
            expected_schema_generation=SCHEMA_GENERATION,
            plan=plan,
        )


def test_explicit_addresses_update_parent_child_and_replay(application) -> None:
    manifest = _manifest()
    main_device = Device(name="main", model="x200u")
    accessory = Device(name="tripod", model="tripod", is_accessory=True)
    main = _rental(main_device, destination="旧自由文本地址")
    child = _rental(accessory, destination="旧自由文本地址", parent=main)
    db.session.add_all((main_device, accessory, main, child))
    db.session.commit()
    plan = _plan(manifest, main, child)

    first = _backfill(manifest, plan)
    replay = _backfill(manifest, plan)

    assert first.addressed_rental_count == 2
    assert first.updated_row_count == 2
    assert first.idempotent_replay is False
    assert replay.updated_row_count == 0
    assert replay.idempotent_replay is True
    assert replay.plan_digest == first.plan_digest
    assert replay.result_digest == first.result_digest
    for rental_id in (main.id, child.id):
        rental = db.session.get(Rental, rental_id)
        assert rental.destination == "旧自由文本地址"
        assert (
            rental.customer_province,
            rental.customer_city,
            rental.customer_district,
            rental.customer_address_detail,
        ) == ("北京市", "北京市", "朝阳区", "复核路1号")


def test_source_drift_rolls_back_earlier_rows_even_if_caller_continues(
    application,
) -> None:
    manifest = _manifest()
    first_device = Device(name="first", model="x200u")
    second_device = Device(name="second", model="x200u")
    first = _rental(first_device, destination="地址一")
    second = _rental(second_device, destination="地址二")
    db.session.add_all((first_device, second_device, first, second))
    db.session.commit()
    plan = _plan(manifest, first, second)
    second.destination = "地址已经变化"
    db.session.commit()

    session = db.session()
    if session.in_transaction():
        session.rollback()
    with session.begin():
        with pytest.raises(StructuredAddressBackfillConflictError):
            StructuredAddressBackfillService().backfill(
                session,
                manifest=manifest,
                expected_schema_generation=SCHEMA_GENERATION,
                plan=plan,
            )

    db.session.expire_all()
    assert db.session.get(Rental, first.id).customer_province is None
    assert db.session.get(Rental, second.id).customer_province is None


def test_partial_or_different_existing_address_fails_closed(application) -> None:
    manifest = _manifest()
    device = Device(name="main", model="x200u")
    rental = _rental(device, destination="旧地址")
    rental.customer_province = "北京市"
    db.session.add_all((device, rental))
    db.session.commit()

    with pytest.raises(StructuredAddressBackfillConflictError):
        _backfill(manifest, _plan(manifest, rental))

    db.session.expire_all()
    stored = db.session.get(Rental, rental.id)
    assert stored.customer_province == "北京市"
    assert stored.customer_city is None


def test_plan_identity_is_pii_free_but_changes_with_reviewed_address(
    application,
) -> None:
    manifest = _manifest()
    device = Device(name="main", model="x200u")
    rental = _rental(device, destination="敏感旧地址")
    db.session.add_all((device, rental))
    db.session.commit()
    first_entry = _entry(rental, address_detail="秘密街1号")
    second_entry = _entry(rental, address_detail="秘密街2号")
    first = StructuredAddressBackfillPlan(
        parent_manifest_digest=manifest.digest,
        migration_idempotency_key=manifest.migration_idempotency_key,
        entries=(first_entry,),
    )
    second = StructuredAddressBackfillPlan(
        parent_manifest_digest=manifest.digest,
        migration_idempotency_key=manifest.migration_idempotency_key,
        entries=(second_entry,),
    )

    assert first.digest != second.digest
    assert "敏感旧地址" not in repr(first_entry)
    assert "秘密街1号" not in repr(first_entry)
    assert "敏感旧地址".encode("utf-8") not in first.canonical_bytes()
    assert "秘密街1号".encode("utf-8") not in first.canonical_bytes()


def test_identity_manifest_and_transaction_boundaries(application) -> None:
    manifest = _manifest()
    device = Device(name="main", model="x200u")
    rental = _rental(device, destination=None)
    db.session.add_all((device, rental))
    db.session.commit()
    plan = _plan(manifest, rental)
    identity = db.session.scalar(sa.select(TenantDatabaseIdentity))
    identity.schema_generation += 1
    db.session.commit()

    with pytest.raises(StructuredAddressBackfillIdentityMismatchError):
        _backfill(manifest, plan)

    changed = _manifest()
    object.__setattr__(changed, "migration_bundle_digest", _digest("changed"))
    with pytest.raises(StructuredAddressBackfillInputError):
        _backfill(changed, plan)

    identity.schema_generation = SCHEMA_GENERATION
    db.session.commit()
    with pytest.raises(StructuredAddressBackfillTransactionError):
        StructuredAddressBackfillService().backfill(
            db.session(),
            manifest=manifest,
            expected_schema_generation=SCHEMA_GENERATION,
            plan=plan,
        )


def test_entry_requires_all_reviewed_fields_and_never_inferrs(application) -> None:
    with pytest.raises(StructuredAddressBackfillInputError):
        StructuredRentalAddressEntry(
            rental_id=1,
            expected_parent_rental_id=None,
            expected_legacy_destination_digest=legacy_destination_digest(
                "北京市朝阳区某路"
            ),
            province="北京市",
            city="北京市",
            district="",
            address_detail="某路",
        )
