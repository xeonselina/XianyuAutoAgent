from __future__ import annotations

import hashlib
from dataclasses import fields
from datetime import date, datetime
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.models.audit_log import AuditLog
from app.models.database_identity import TenantDatabaseIdentity
from app.models.device import Device
from app.models.legacy_unattributed_history import (
    LegacyUnattributedPrintSnapshot,
    LegacyUnattributedShipmentSnapshot,
)
from app.models.rental import Rental
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
    WaybillPrintJob,
)
from app.services.migration import (
    LegacyUnattributedHistoryBackfillService,
    LegacyUnattributedHistoryConflictError,
    VerifiedLegacyUnattributedHistoricalSnapshotsStep,
)
from app.services.shipping import (
    LegacyPrintHistorySummary,
    LegacyShipmentHistorySummary,
    LegacyUnattributedHistoryQueryService,
    ShipmentTrackingQueryService,
    TrackingShipmentUnavailableError,
)
from app.services.shipping_execution_service import (
    ShippingExecutionService,
    ShippingNotFoundError,
)
from inventory_control.default_migration import (
    HISTORICAL_BOUNDARY_COUNT_KEYS,
    DefaultHistoricalSnapshotBoundaryEvidence,
    DefaultMigrationStepInvocation,
    DefaultTenantMigrationManifest,
    HistoricalSnapshotDisposition,
    MigrationExecutionMode,
    MigrationExecutionPlan,
    MigrationPhase,
    MigrationPhaseInvocation,
)


TENANT_UUID = UUID("94000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("94000000-0000-4000-8000-000000000002")
PLAN_UUID = UUID("94000000-0000-4000-8000-000000000003")
SCHEMA_GENERATION = 5


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="legacy-unattributed-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management_test",
        baseline_migration_id="legacy-boundary-v1",
        core_plan_revision_uuid=PLAN_UUID,
        control_schema_head="202608220026",
        tenant_schema_head="20260824_legacy_history",
        source_snapshot_digest=_digest("legacy-source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("display-name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


def _boundary() -> DefaultHistoricalSnapshotBoundaryEvidence:
    counts = {
        "legacy_historical_rentals": 1,
        "legacy_print_audits": 1,
        "legacy_tracking_rows": 1,
        "outbound_shipments": 0,
        "provider_operation_attempts": 0,
        "waybill_print_jobs": 0,
    }
    return DefaultHistoricalSnapshotBoundaryEvidence(
        source_schema_name="inventory_management_test",
        baseline_migration_id="legacy-boundary-v1",
        source_snapshot_digest=_manifest().source_snapshot_digest,
        counts=tuple((key, counts[key]) for key in HISTORICAL_BOUNDARY_COUNT_KEYS),
        disposition=(
            HistoricalSnapshotDisposition.REQUIRES_APPROVED_NONEMPTY_ADAPTER
        ),
    )


def _invocation() -> DefaultMigrationStepInvocation:
    manifest = _manifest()
    plan = MigrationExecutionPlan(
        phase=MigrationPhase.BACKFILL_VERIFY,
        mode=MigrationExecutionMode.APPLY,
        manifest_digest=manifest.digest,
        prerequisites=(),
        completion_conditions=(),
        stop_conditions=(),
        rollback_action="retain read-only legacy snapshots",
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
    step_key = "default-step:" + hashlib.sha256(
        b"default-migration-step-v1\x00"
        + phase_key.encode("ascii")
        + b"\x00historical_snapshots"
    ).hexdigest()
    return DefaultMigrationStepInvocation(
        phase_invocation=phase,
        step_name="historical_snapshots",
        step_execution_key=step_key,
    )


def _seed(database) -> int:
    with database.new_session() as session, session.begin():
        session.add(
            TenantDatabaseIdentity(
                singleton_key=1,
                tenant_id=str(TENANT_UUID),
                database_uuid=str(DATABASE_UUID),
                schema_generation=SCHEMA_GENERATION,
            )
        )
        device = Device(name="历史设备", model="x200u")
        rental = Rental(
            device=device,
            start_date=date(2026, 8, 1),
            end_date=date(2026, 8, 3),
            customer_name="历史客户",
            status="shipped",
            ship_out_tracking_no="SF-LEGACY-001",
            ship_out_time=datetime(2026, 8, 1, 9, 30),
        )
        session.add_all((device, rental))
        session.flush()
        session.add(
            AuditLog(
                rental_id=rental.id,
                action="print_waybill",
                description="must not migrate to execution authority",
                created_at=datetime(2026, 8, 1, 9, 35),
            )
        )
        return rental.id


def _backfill(database):
    with database.new_session() as session, session.begin():
        return LegacyUnattributedHistoryBackfillService().backfill(
            session,
            manifest=_manifest(),
            expected_schema_generation=SCHEMA_GENERATION,
            historical_boundary=_boundary(),
        )


def test_d68_backfill_replays_and_only_returns_read_only_display_dtos(
    mysql_routed_database,
) -> None:
    database = mysql_routed_database
    rental_id = _seed(database)

    first = _backfill(database)
    replay = _backfill(database)

    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    assert first.result_digest == replay.result_digest
    assert dict(first.counts) == {
        "legacy_print_snapshots": 1,
        "legacy_shipment_snapshots": 1,
    }

    with database.new_session() as session:
        page = LegacyUnattributedHistoryQueryService(session).list_history()
        assert len(page.shipment_items) == 1
        assert len(page.print_items) == 1
        shipment = page.shipment_items[0]
        print_occurrence = page.print_items[0]
        assert shipment.record_kind == "legacy_unattributed"
        assert shipment.rental_id == rental_id
        assert shipment.ship_out_tracking_no == "SF-LEGACY-001"
        assert shipment.actionable is False
        assert shipment.available_actions == ()
        assert print_occurrence.record_kind == "legacy_unattributed"
        assert print_occurrence.actionable is False
        assert print_occurrence.available_actions == ()
        assert session.scalar(sa.select(sa.func.count()).select_from(OutboundShipment)) == 0
        assert session.scalar(sa.select(sa.func.count()).select_from(ProviderOperationAttempt)) == 0
        assert session.scalar(sa.select(sa.func.count()).select_from(WaybillPrintJob)) == 0

    forbidden_authority_fields = {
        "integration_uuid",
        "provider_account_uuid",
        "integration_secret_revision_uuid",
        "provider_account_secret_revision_uuid",
        "provider_order_id",
        "printer_sn",
        "provider_task_id",
    }
    assert forbidden_authority_fields.isdisjoint(
        LegacyUnattributedShipmentSnapshot.__table__.columns.keys()
    )
    assert forbidden_authority_fields.isdisjoint(
        LegacyUnattributedPrintSnapshot.__table__.columns.keys()
    )
    assert forbidden_authority_fields.isdisjoint(
        {item.name for item in fields(LegacyShipmentHistorySummary)}
    )
    assert forbidden_authority_fields.isdisjoint(
        {item.name for item in fields(LegacyPrintHistorySummary)}
    )


def test_legacy_snapshot_ids_are_rejected_by_all_core_action_planners(
    mysql_routed_database,
) -> None:
    database = mysql_routed_database
    rental_id = _seed(database)
    _backfill(database)
    with database.new_session() as session:
        snapshot_id = session.scalar(
            sa.select(LegacyUnattributedShipmentSnapshot.id)
        )

    with database.new_session() as session:
        with pytest.raises(TrackingShipmentUnavailableError):
            ShipmentTrackingQueryService(session).plan_historical_batches(
                shipment_ids=(snapshot_id,)
            )

    with database.new_session() as session, session.begin():
        service = ShippingExecutionService(session)
        with pytest.raises(ShippingNotFoundError):
            service.prepare_provider_attempt(
                shipment_id=snapshot_id,
                operation="cancel_waybill",
                idempotency_key="legacy-cancel-rejected",
            )

    with database.new_session() as session, session.begin():
        service = ShippingExecutionService(session)
        with pytest.raises(ShippingNotFoundError):
            service.request_cancellation(
                shipment_id=snapshot_id,
                expected_status="submitted",
                requested_at=datetime(2026, 8, 2, 10, 0),
            )

    with database.new_session() as session, session.begin():
        service = ShippingExecutionService(session)
        with pytest.raises(ShippingNotFoundError):
            service.prepare_paired_print_jobs(
                shipment_id=snapshot_id,
                rental_id=rental_id,
                first_label_warehouse_uuid=(
                    "94000000-0000-4000-8000-000000000010"
                ),
                return_warehouse_id=1,
                return_warehouse_uuid=(
                    "94000000-0000-4000-8000-000000000011"
                ),
                return_contact_snapshot={"name": "不可执行"},
                operator_user_uuid=(
                    "94000000-0000-4000-8000-000000000012"
                ),
                idempotency_key="legacy-print-rejected",
            )


def test_source_drift_conflicts_and_adapter_is_boundary_bound(
    mysql_routed_database,
) -> None:
    database = mysql_routed_database
    rental_id = _seed(database)
    _backfill(database)

    step = VerifiedLegacyUnattributedHistoricalSnapshotsStep(
        tenant_session_factory=database.new_session,
        expected_schema_generation=SCHEMA_GENERATION,
        historical_boundary=_boundary(),
        approved_historical_boundary_digest=_boundary().digest,
    )
    first_evidence = step.execute(_invocation())
    replay_evidence = step.execute(_invocation())
    assert first_evidence == replay_evidence
    assert first_evidence.executor_reference == (
        "verified-legacy-unattributed-history:historical_snapshots"
    )

    with database.new_session() as session, session.begin():
        rental = session.get(Rental, rental_id)
        rental.ship_out_tracking_no = "SF-LEGACY-CHANGED"

    with pytest.raises(LegacyUnattributedHistoryConflictError):
        _backfill(database)

    with database.new_session() as session:
        snapshot = session.scalar(
            sa.select(LegacyUnattributedShipmentSnapshot)
        )
        assert snapshot.ship_out_tracking_no == "SF-LEGACY-001"
        assert session.scalar(sa.select(sa.func.count()).select_from(OutboundShipment)) == 0
