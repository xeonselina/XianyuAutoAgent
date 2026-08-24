from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest
from sqlalchemy import func, select

from inventory_control import ControlBase, ControlDatabase
from inventory_control.default_migration import (
    DefaultTenantMigrationGrantWriter,
    DefaultTenantMigrationManifest,
    MigrationJournal,
    MigrationManifestMismatchError,
    MigrationOrderError,
    MigrationPhase,
    MigrationPhaseEvidence,
)
from inventory_control.models import (
    PlanRevision,
    Subscription,
    SubscriptionEvent,
    Tenant,
    TenantDatabase,
)
from inventory_control.subscriptions import (
    SubscriptionLedgerService,
    parse_core_entitlements,
)


TENANT_UUID = UUID("20000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("20000000-0000-4000-8000-000000000002")
PLAN_UUID = UUID("20000000-0000-4000-8000-000000000003")
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest(*, bundle: str = "bundle") -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-tenant-integrated-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=PLAN_UUID,
        control_schema_head="202608220026",
        tenant_schema_head="20260824_legacy_history",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest(bundle),
        display_name_input_commitment=_digest("keyed-name"),
        first_admin_phone_input_commitment=_digest("keyed-phone"),
    )


def _journal(
    manifest: DefaultTenantMigrationManifest,
    *,
    reconciled: bool,
) -> MigrationJournal:
    phases = (
        (MigrationPhase.EXPAND,)
        if not reconciled
        else (MigrationPhase.EXPAND, MigrationPhase.BACKFILL_VERIFY)
    )
    return MigrationJournal(
        manifest_digest=manifest.digest,
        completed=tuple(
            MigrationPhaseEvidence(
                phase=phase,
                manifest_digest=manifest.digest,
                input_state_digest=_digest(f"{phase.value}:input"),
                result_state_digest=_digest(f"{phase.value}:result"),
                completed_at=NOW,
                executor_reference=f"isolated-test:{phase.value}",
            )
            for phase in phases
        ),
    )


@pytest.fixture
def control_database(mysql_control_database):
    database = mysql_control_database
    snapshot = parse_core_entitlements(
        schema_version=1,
        entitlements={
            "features": {"xianyu_sync": True},
            "limits": {"member_seats": 10},
        },
    )
    with database.transaction() as session:
        session.add(Tenant(id=str(TENANT_UUID), status="provisioning"))
        session.add(
            TenantDatabase(
                tenant_id=str(TENANT_UUID),
                database_uuid=str(DATABASE_UUID),
                database_instance_key="isolated-test",
                database_name="tenant_fixture",
                status="ready",
                schema_version="test-head",
                activated_by_registration_commit_uuid=(
                    "20000000-0000-4000-8000-000000000099"
                ),
                activation_route_version=1,
                activation_credential_generation=1,
                dml_username="tenant_dml_g1",
                dml_credential_generation=1,
                dml_root_key_version=1,
                dml_derivation_version=1,
                route_version=1,
                dml_desired_login_state="active",
                dml_observed_login_state="active",
                dml_login_state_version=1,
                platform_read_username="tenant_read_g1",
                platform_read_credential_generation=1,
                platform_read_root_key_version=1,
                platform_read_derivation_version=1,
                platform_read_route_version=1,
            )
        )
        session.add(
            PlanRevision(
                id=str(PLAN_UUID),
                code="core",
                revision=1,
                name="Core",
                entitlements_schema_version=1,
                entitlements_json={
                    "features": {"xianyu_sync": True},
                    "limits": {"member_seats": 10},
                },
                entitlements_digest=snapshot.digest_sha256,
                active=True,
            )
        )
    return database


def _writer(now: datetime) -> DefaultTenantMigrationGrantWriter:
    return DefaultTenantMigrationGrantWriter(
        ledger_service=SubscriptionLedgerService(
            database_clock=lambda _session: now
        )
    )


def test_grant_writer_requires_reconciliation_before_any_control_write(
    control_database,
) -> None:
    manifest = _manifest()

    with control_database.transaction() as session:
        with pytest.raises(MigrationOrderError, match="reconciliation"):
            _writer(NOW).write(
                session,
                manifest=manifest,
                journal=_journal(manifest, reconciled=False),
            )

    with control_database.new_session() as session:
        assert session.scalar(select(func.count()).select_from(Subscription)) == 0


def test_grant_writer_binds_manifest_and_replays_without_extending(
    control_database,
) -> None:
    manifest = _manifest()
    journal = _journal(manifest, reconciled=True)
    with control_database.transaction() as session:
        first = _writer(NOW).write(
            session,
            manifest=manifest,
            journal=journal,
        )
    with control_database.transaction() as session:
        replayed = _writer(NOW + timedelta(days=30)).write(
            session,
            manifest=manifest,
            journal=journal,
        )

    assert first.created is True
    assert replayed.created is False
    assert replayed.subscription_uuid == first.subscription_uuid
    assert replayed.event_uuid == first.event_uuid
    assert replayed.expires_at.replace(tzinfo=timezone.utc) == (
        NOW + timedelta(days=36_500)
    )
    with control_database.new_session() as session:
        assert session.scalar(select(func.count()).select_from(Subscription)) == 1
        event = session.scalar(select(SubscriptionEvent))
        assert event.exact_duration_seconds == 3_153_600_000
        assert event.after_plan_revision_uuid == str(PLAN_UUID)


def test_grant_writer_rejects_journal_from_changed_manifest(control_database) -> None:
    original = _manifest()
    changed = _manifest(bundle="changed")

    with control_database.transaction() as session:
        with pytest.raises(MigrationManifestMismatchError, match="another"):
            _writer(NOW).write(
                session,
                manifest=changed,
                journal=_journal(original, reconciled=True),
            )
