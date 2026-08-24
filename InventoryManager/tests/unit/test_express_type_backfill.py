from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date, datetime
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.dialects import mysql

from app import db
from app.models.database_identity import TenantDatabaseIdentity
from app.models.device import Device
from app.models.rental import Rental
from app.services.migration.express_type_backfill import (
    ExpressTypeBackfillConflictError,
    ExpressTypeBackfillIdentityMismatchError,
    ExpressTypeBackfillManifest,
    ExpressTypeBackfillSchemaMismatchError,
    ExpressTypeBackfillService,
    ExpressTypeBackfillTransactionError,
    ExpressTypeState,
    TenantSchemaAuthorityFacts,
    _identity_lock_statement,
    _rental_lock_statement,
    build_express_type_source_snapshot,
    tenant_database_identity_digest,
)


TENANT_UUID = uuid5(NAMESPACE_URL, "express-type-backfill/tenant")
DATABASE_UUID = uuid5(NAMESPACE_URL, "express-type-backfill/database")
SCHEMA_GENERATION = 12
SCHEMA_REVISION = "20260822_add_shipping_execution_ledgers"
SCHEMA_DIGEST = hashlib.sha256(b"offline-tenant-schema-v1").digest()
PARENT_MANIFEST_DIGEST = hashlib.sha256(b"default-migration-manifest").digest()
IDENTITY_CREATED_AT = datetime(2026, 8, 22, 1, 2, 3)


def _seed_identity() -> None:
    db.session.add(
        TenantDatabaseIdentity(
            singleton_key=1,
            tenant_id=str(TENANT_UUID),
            database_uuid=str(DATABASE_UUID),
            created_at=IDENTITY_CREATED_AT,
            schema_generation=SCHEMA_GENERATION,
        )
    )
    db.session.commit()


def _seed_rentals(values: list[object]) -> tuple[int, ...]:
    device = Device(name="express-type-backfill-device")
    db.session.add(device)
    db.session.flush()
    rentals = []
    for offset, _value in enumerate(values):
        rental = Rental(
            device_id=device.id,
            start_date=date(2026, 9, 1 + offset),
            end_date=date(2026, 9, 2 + offset),
            customer_name="fixture",
            status="not_shipped",
            express_type_id=2,
        )
        db.session.add(rental)
        rentals.append(rental)
    db.session.flush()
    ids = tuple(rental.id for rental in rentals)
    for rental_id, value in zip(ids, values, strict=True):
        db.session.execute(
            sa.update(Rental)
            .where(Rental.id == rental_id)
            .values(express_type_id=value)
        )
    db.session.commit()
    db.session.remove()
    return ids


def _raw_rows() -> tuple[tuple[int, object], ...]:
    rows = db.session.execute(
        sa.select(Rental.id, Rental.express_type_id).order_by(Rental.id)
    ).all()
    return tuple((row.id, row.express_type_id) for row in rows)


def _manifest() -> ExpressTypeBackfillManifest:
    rows = _raw_rows()
    db.session.commit()
    return ExpressTypeBackfillManifest(
        migration_idempotency_key="default-tenant.express-type.v1",
        parent_manifest_digest=PARENT_MANIFEST_DIGEST,
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        schema_generation=SCHEMA_GENERATION,
        tenant_identity_digest=tenant_database_identity_digest(
            tenant_uuid=TENANT_UUID,
            database_uuid=DATABASE_UUID,
            created_at=IDENTITY_CREATED_AT,
            schema_generation=SCHEMA_GENERATION,
        ),
        schema_revision=SCHEMA_REVISION,
        schema_digest=SCHEMA_DIGEST,
        source_snapshot=build_express_type_source_snapshot(rows),
    )


def _facts(**overrides) -> TenantSchemaAuthorityFacts:
    values = {
        "tenant_uuid": TENANT_UUID,
        "database_uuid": DATABASE_UUID,
        "schema_generation": SCHEMA_GENERATION,
        "schema_revision": SCHEMA_REVISION,
        "schema_digest": SCHEMA_DIGEST,
    }
    values.update(overrides)
    return TenantSchemaAuthorityFacts(**values)


def _run(
    manifest: ExpressTypeBackfillManifest,
    *,
    facts: TenantSchemaAuthorityFacts | None = None,
):
    selected_facts = facts or _facts()
    session = db.session()
    with session.begin():
        return ExpressTypeBackfillService(
            lambda current_session, identity: selected_facts
        ).backfill(session, manifest=manifest)


@pytest.mark.parametrize(
    ("value", "state", "expected", "passed"),
    (
        (None, ExpressTypeState.HISTORICAL_NULL, 2, True),
        (1, ExpressTypeState.CANONICAL_1, 1, True),
        (2, ExpressTypeState.CANONICAL_2, 2, True),
        (263, ExpressTypeState.CANONICAL_263, 263, True),
        (6, ExpressTypeState.LEGACY_6, 6, False),
        (99, ExpressTypeState.UNSUPPORTED, 99, False),
    ),
)
def test_backfill_only_changes_historical_null_and_reports_every_state(
    application,
    value,
    state,
    expected,
    passed,
):
    _seed_identity()
    (rental_id,) = _seed_rentals([value])
    manifest = _manifest()

    result = _run(manifest)

    assert db.session.get(Rental, rental_id).express_type_id == expected
    assert dict(result.source_state_counts)[state.value] == 1
    assert result.updated_count == (1 if value is None else 0)
    assert result.verification_passed is passed
    assert result.safe_status == (
        "verified"
        if passed
        else "blocked_legacy_6"
        if value == 6
        else "blocked_unsupported"
    )


def test_mixed_snapshot_never_maps_six_or_invalid_value_to_263_or_calls_provider(
    application,
    monkeypatch,
):
    _seed_identity()
    rental_ids = _seed_rentals([None, 1, 2, 263, 6, 99])
    manifest = _manifest()
    provider_calls: list[object] = []
    monkeypatch.setattr(
        "app.services.shipping.sf_express_service.get_sf_express_service",
        lambda: provider_calls.append("called"),
    )

    result = _run(manifest)

    values = tuple(
        db.session.get(Rental, rental_id).express_type_id for rental_id in rental_ids
    )
    assert values == (2, 1, 2, 263, 6, 99)
    assert provider_calls == []
    assert result.updated_count == 1
    assert result.verification_passed is False
    assert result.safe_status == "blocked_legacy_and_unsupported"
    assert dict(result.source_state_counts) == {
        "canonical_1": 1,
        "canonical_2": 1,
        "canonical_263": 1,
        "historical_null": 1,
        "legacy_6": 1,
        "unsupported": 1,
    }


def test_same_manifest_exactly_replays_from_expected_result_snapshot(application):
    _seed_identity()
    _seed_rentals([None, 2, 263])
    manifest = _manifest()

    first = _run(manifest)
    replay = _run(manifest)

    assert first.updated_count == 1
    assert first.idempotent_replay is False
    assert replay.updated_count == 0
    assert replay.idempotent_replay is True
    assert replay.operation_uuid == first.operation_uuid
    assert replay.manifest_digest == first.manifest_digest
    assert replay.source_snapshot_digest == first.source_snapshot_digest
    assert replay.result_snapshot_digest == first.result_snapshot_digest
    assert replay.report_digest == first.report_digest
    assert replay.source_state_counts == first.source_state_counts
    assert replay.verification_passed is True


def test_snapshot_or_idempotency_identity_drift_fails_closed(application):
    _seed_identity()
    (rental_id,) = _seed_rentals([None])
    manifest = _manifest()
    db.session.execute(
        sa.update(Rental).where(Rental.id == rental_id).values(express_type_id=263)
    )
    db.session.commit()

    with pytest.raises(ExpressTypeBackfillConflictError):
        _run(manifest)

    assert db.session.get(Rental, rental_id).express_type_id == 263


@pytest.mark.parametrize(
    "change",
    (
        {"tenant_uuid": uuid5(NAMESPACE_URL, "wrong-tenant")},
        {"database_uuid": uuid5(NAMESPACE_URL, "wrong-database")},
        {"schema_generation": SCHEMA_GENERATION + 1},
        {"tenant_identity_digest": b"x" * 32},
    ),
)
def test_locked_database_identity_mismatch_precedes_rental_lock(
    application,
    change,
):
    _seed_identity()
    (rental_id,) = _seed_rentals([None])
    manifest = replace(_manifest(), **change)
    selected_tables: list[str] = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        lowered = statement.lower()
        if lowered.lstrip().startswith("select"):
            if "database_identity" in lowered:
                selected_tables.append("identity")
            elif "rentals" in lowered:
                selected_tables.append("rentals")

    event.listen(db.engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(ExpressTypeBackfillIdentityMismatchError):
            _run(manifest)
    finally:
        event.remove(db.engine, "before_cursor_execute", capture)

    assert selected_tables == ["identity"]
    assert db.session.get(Rental, rental_id).express_type_id is None


@pytest.mark.parametrize(
    "facts",
    (
        _facts(tenant_uuid=uuid5(NAMESPACE_URL, "schema-wrong-tenant")),
        _facts(database_uuid=uuid5(NAMESPACE_URL, "schema-wrong-db")),
        _facts(schema_generation=SCHEMA_GENERATION + 1),
        _facts(schema_revision="wrong_revision"),
        _facts(schema_digest=b"z" * 32),
    ),
)
def test_schema_current_read_mismatch_precedes_rental_lock(
    application,
    facts,
):
    _seed_identity()
    _seed_rentals([None])
    manifest = _manifest()
    selected_tables: list[str] = []

    def capture(_connection, _cursor, statement, _params, _context, _many):
        lowered = statement.lower()
        if lowered.lstrip().startswith("select"):
            if "database_identity" in lowered:
                selected_tables.append("identity")
            elif "rentals" in lowered:
                selected_tables.append("rentals")

    event.listen(db.engine, "before_cursor_execute", capture)
    try:
        with pytest.raises(ExpressTypeBackfillSchemaMismatchError):
            _run(manifest, facts=facts)
    finally:
        event.remove(db.engine, "before_cursor_execute", capture)

    assert selected_tables == ["identity"]


def test_schema_reader_receives_caller_session_and_locked_identity(application):
    _seed_identity()
    _seed_rentals([None])
    manifest = _manifest()
    observed: list[tuple[object, object]] = []
    session = db.session()

    def current_read(current_session, identity):
        observed.append((current_session, identity))
        assert current_session is session
        assert current_session.in_transaction()
        assert identity.singleton_key == 1
        return _facts()

    with session.begin():
        ExpressTypeBackfillService(current_read).backfill(
            session,
            manifest=manifest,
        )

    assert len(observed) == 1


def test_schema_reader_cannot_stage_writes_before_rental_lock(application):
    _seed_identity()
    _seed_rentals([None])
    manifest = _manifest()
    session = db.session()

    def dirty_reader(current_session, _identity):
        current_session.add(Device(name="unauthorized-reader-write"))
        return _facts()

    with pytest.raises(ExpressTypeBackfillTransactionError):
        with session.begin():
            ExpressTypeBackfillService(dirty_reader).backfill(
                session,
                manifest=manifest,
            )

    assert (
        db.session.scalar(
            sa.select(sa.func.count())
            .select_from(Device)
            .where(Device.name == "unauthorized-reader-write")
        )
        == 0
    )


@pytest.mark.parametrize("transaction_action", ("commit", "rollback"))
def test_schema_reader_cannot_end_caller_transaction(
    application,
    transaction_action,
):
    _seed_identity()
    _seed_rentals([None])
    manifest = _manifest()
    session = db.session()

    def transaction_ending_reader(current_session, _identity):
        getattr(current_session, transaction_action)()
        return _facts()

    with pytest.raises(ExpressTypeBackfillTransactionError):
        with session.begin():
            ExpressTypeBackfillService(transaction_ending_reader).backfill(
                session,
                manifest=manifest,
            )


def test_manifest_operation_identity_is_deterministic_and_input_bound(application):
    _seed_identity()
    _seed_rentals([None])
    manifest = _manifest()
    same = replace(manifest)
    changed = replace(
        manifest,
        migration_idempotency_key="default-tenant.express-type.v2",
    )

    assert same.digest == manifest.digest
    assert same.operation_uuid == manifest.operation_uuid
    assert changed.digest != manifest.digest
    assert changed.operation_uuid != manifest.operation_uuid


def test_outer_rollback_restores_historical_null(application):
    class RollbackProbe(RuntimeError):
        pass

    _seed_identity()
    (rental_id,) = _seed_rentals([None])
    manifest = _manifest()
    db.session.remove()
    session = db.session()
    with pytest.raises(RollbackProbe):
        with session.begin():
            result = ExpressTypeBackfillService(
                lambda current_session, identity: _facts()
            ).backfill(session, manifest=manifest)
            assert result.updated_count == 1
            raise RollbackProbe()
    db.session.remove()

    assert db.session.get(Rental, rental_id).express_type_id is None


def test_requires_explicit_clean_caller_owned_transaction(application):
    _seed_identity()
    _seed_rentals([None])
    manifest = _manifest()
    session = db.session()

    with pytest.raises(ExpressTypeBackfillTransactionError):
        ExpressTypeBackfillService(lambda current_session, identity: _facts()).backfill(
            session, manifest=manifest
        )

    with pytest.raises(ExpressTypeBackfillTransactionError):
        with session.begin():
            session.add(Device(name="preexisting-dirty-work"))
            ExpressTypeBackfillService(
                lambda current_session, identity: _facts()
            ).backfill(session, manifest=manifest)


def test_mysql_lock_sql_is_offline_and_uses_for_update():
    identity_sql = str(
        _identity_lock_statement().compile(dialect=mysql.dialect())
    ).upper()
    rental_sql = str(_rental_lock_statement().compile(dialect=mysql.dialect())).upper()

    assert "DATABASE_IDENTITY" in identity_sql
    assert "RENTALS" in rental_sql
    assert identity_sql.rstrip().endswith("FOR UPDATE")
    assert rental_sql.rstrip().endswith("FOR UPDATE")


def test_reports_and_errors_never_echo_invalid_raw_values(
    application,
    caplog,
):
    first_invalid_value = 2_147_483_647
    second_invalid_value = 2_147_483_646
    _seed_identity()
    (rental_id,) = _seed_rentals([first_invalid_value])
    manifest = _manifest()

    result = _run(manifest)
    rendered = repr(result) + repr(result.safe_summary()) + repr(manifest)
    assert str(first_invalid_value) not in rendered
    assert result.verification_passed is False
    assert result.safe_status == "blocked_unsupported"

    db.session.execute(
        sa.update(Rental)
        .where(Rental.id == rental_id)
        .values(express_type_id=second_invalid_value)
    )
    db.session.commit()
    with pytest.raises(ExpressTypeBackfillConflictError) as caught:
        _run(manifest)

    exposed = str(caught.value) + repr(caught.value) + caplog.text
    assert str(first_invalid_value) not in exposed
    assert str(second_invalid_value) not in exposed
    assert str(caught.value) == "EXPRESS_TYPE_BACKFILL_SNAPSHOT_CONFLICT"
