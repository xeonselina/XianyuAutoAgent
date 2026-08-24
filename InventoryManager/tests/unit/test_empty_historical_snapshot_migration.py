from __future__ import annotations

import hashlib
from datetime import date, datetime
from uuid import UUID

import pytest
from sqlalchemy.orm import Session, sessionmaker

from app import create_app, db
from app.models.audit_log import AuditLog
from app.models.database_identity import TenantDatabaseIdentity
from app.models.device import Device
from app.models.rental import Rental
from app.models.shipping_execution import OutboundShipment
from app.models.warehouse import Warehouse
from app.services.migration import (
    EmptyHistoricalSnapshotIdentityError,
    EmptyHistoricalSnapshotTransactionError,
    EmptyHistoricalSnapshotVerifier,
    HistoricalSnapshotNotEmptyError,
    VerifiedEmptyHistoricalSnapshotsStep,
)
from inventory_control.default_migration import (
    DefaultMigrationStepInvocation,
    DefaultTenantMigrationManifest,
    MigrationExecutionMode,
    MigrationExecutionPlan,
    MigrationPhase,
    MigrationPhaseInvocation,
)


TENANT_UUID = UUID("82000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("82000000-0000-4000-8000-000000000002")
PLAN_UUID = UUID("82000000-0000-4000-8000-000000000003")


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="empty-history-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management_test",
        baseline_migration_id="baseline-v1",
        core_plan_revision_uuid=PLAN_UUID,
        control_schema_head="202608220026",
        tenant_schema_head="20260824_legacy_history",
        source_snapshot_digest=_digest("empty-source-snapshot"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("display-name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


def _step_invocation() -> DefaultMigrationStepInvocation:
    manifest = _manifest()
    plan = MigrationExecutionPlan(
        phase=MigrationPhase.BACKFILL_VERIFY,
        mode=MigrationExecutionMode.APPLY,
        manifest_digest=manifest.digest,
        prerequisites=(),
        completion_conditions=(),
        stop_conditions=(),
        rollback_action="retain reversible facts",
        mutations_allowed=True,
    )
    phase_key = "default-migration:" + hashlib.sha256(
        b"default-tenant-migration-phase-v1\x00"
        + manifest.digest
        + b"\x00backfill_verify"
    ).hexdigest()
    phase = MigrationPhaseInvocation(
        manifest=manifest,
        plan=plan,
        phase_execution_key=phase_key,
    )
    step_name = "historical_snapshots"
    step_key = "default-step:" + hashlib.sha256(
        b"default-migration-step-v1\x00"
        + phase_key.encode("ascii")
        + b"\x00"
        + step_name.encode("ascii")
    ).hexdigest()
    return DefaultMigrationStepInvocation(
        phase_invocation=phase,
        step_name=step_name,
        step_execution_key=step_key,
    )


@pytest.fixture
def tenant_database():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        db.session.add(
            TenantDatabaseIdentity(
                singleton_key=1,
                tenant_id=str(TENANT_UUID),
                database_uuid=str(DATABASE_UUID),
                schema_generation=3,
            )
        )
        db.session.commit()
        factory = sessionmaker(bind=db.engine, expire_on_commit=False)
        try:
            yield app, factory
        finally:
            db.session.remove()
            db.drop_all()


def test_empty_history_verification_and_phase_evidence_replay_stably(
    tenant_database,
) -> None:
    _app, factory = tenant_database
    verifier = EmptyHistoricalSnapshotVerifier()
    with factory() as session, session.begin():
        first = verifier.verify(
            session,
            manifest=_manifest(),
            expected_schema_generation=3,
        )
    with factory() as session, session.begin():
        replay = verifier.verify(
            session,
            manifest=_manifest(),
            expected_schema_generation=3,
        )

    assert first == replay
    assert dict(first.counts) == {
        "legacy_historical_rentals": 0,
        "legacy_print_audits": 0,
        "legacy_tracking_rows": 0,
        "legacy_unattributed_prints": 0,
        "legacy_unattributed_shipments": 0,
        "outbound_shipments": 0,
        "provider_operation_attempts": 0,
        "waybill_print_jobs": 0,
    }
    assert first.safe_summary()["verification_passed"] is True

    step = VerifiedEmptyHistoricalSnapshotsStep(
        tenant_session_factory=factory,
        expected_schema_generation=3,
    )
    evidence = step.execute(_step_invocation())
    replay_evidence = step.execute(_step_invocation())
    assert evidence == replay_evidence
    assert evidence.step_name == "historical_snapshots"
    assert evidence.executor_reference == (
        "verified-empty-history:historical_snapshots"
    )
    assert "session='<bound>'" in repr(step)


@pytest.mark.parametrize("candidate", ["lifecycle", "tracking", "print_audit"])
def test_any_legacy_shipping_or_print_hint_requires_nonempty_adapter(
    tenant_database,
    candidate,
) -> None:
    _app, factory = tenant_database
    if candidate == "print_audit":
        db.session.add(AuditLog(action="print_waybill"))
    else:
        device = Device(name="历史设备", model="x200u")
        rental = Rental(
            device=device,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 2),
            customer_name="历史客户",
            status=("shipped" if candidate == "lifecycle" else "not_shipped"),
            ship_out_tracking_no=(
                "SF-HISTORICAL" if candidate == "tracking" else None
            ),
        )
        db.session.add_all([device, rental])
    db.session.commit()

    with factory() as session, session.begin():
        with pytest.raises(HistoricalSnapshotNotEmptyError):
            EmptyHistoricalSnapshotVerifier().verify(
                session,
                manifest=_manifest(),
                expected_schema_generation=3,
            )


def test_existing_target_shipment_is_not_misreported_as_empty(
    tenant_database,
) -> None:
    _app, factory = tenant_database
    warehouse = Warehouse(
        warehouse_uuid="82000000-0000-4000-8000-000000000020",
        name="默认仓",
        status="active",
        setup_state="ready",
        is_default=True,
        default_slot=1,
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="测试地址",
    )
    device = Device(name="设备", model="x200u", warehouse=warehouse)
    rental = Rental(
        device=device,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        customer_name="客户",
        status="not_shipped",
    )
    shipment = OutboundShipment(
        rental=rental,
        origin_warehouse=warehouse,
        origin_warehouse_uuid=warehouse.warehouse_uuid,
        integration_uuid="82000000-0000-4000-8000-000000000010",
        provider_account_uuid="82000000-0000-4000-8000-000000000011",
        integration_secret_revision_uuid=(
            "82000000-0000-4000-8000-000000000012"
        ),
        provider_account_secret_revision_uuid=(
            "82000000-0000-4000-8000-000000000013"
        ),
        binding_revision=1,
        account_masked_hint="****1234",
        sender_snapshot={"masked": True},
        receiver_snapshot={"masked": True},
        cargo_snapshot={
            "items": [{"name": "租赁设备", "count": 1}]
        },
        tracking_check_phone_last4="8000",
        express_type_id=2,
        scheduled_dispatch_at=datetime(2026, 9, 1, 1),
        provider_order_id="empty-history-target-shipment",
        request_hash="a" * 64,
        status="prepared",
    )
    db.session.add_all([warehouse, device, rental, shipment])
    db.session.commit()

    with factory() as session, session.begin():
        with pytest.raises(HistoricalSnapshotNotEmptyError):
            EmptyHistoricalSnapshotVerifier().verify(
                session,
                manifest=_manifest(),
                expected_schema_generation=3,
            )


def test_identity_and_transaction_must_match_the_bound_manifest(
    tenant_database,
) -> None:
    _app, factory = tenant_database
    session = factory()
    try:
        with pytest.raises(EmptyHistoricalSnapshotTransactionError):
            EmptyHistoricalSnapshotVerifier().verify(
                session,
                manifest=_manifest(),
                expected_schema_generation=3,
            )
    finally:
        session.close()

    with factory() as session, session.begin():
        with pytest.raises(EmptyHistoricalSnapshotIdentityError):
            EmptyHistoricalSnapshotVerifier().verify(
                session,
                manifest=_manifest(),
                expected_schema_generation=4,
            )
