from __future__ import annotations

import hashlib
from uuid import UUID

import pytest
import sqlalchemy as sa

from app.services.migration.integration_metadata_backfill import (
    IntegrationMetadataBackfillEntry,
    IntegrationMetadataBackfillInputError,
    IntegrationMetadataBackfillPlan,
    IntegrationMetadataBackfillService,
)
from inventory_control import ControlBase, ControlDatabase
from inventory_control.default_migration import DefaultTenantMigrationManifest
from inventory_control.models import Tenant
from inventory_control.models.integrations import (
    TenantIntegration,
    TenantIntegrationSecretRevision,
)


TENANT_UUID = UUID("60000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("60000000-0000-4000-8000-000000000002")


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest(*, bundle="bundle") -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-integrations-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID(
            "60000000-0000-4000-8000-000000000003"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest(bundle),
        display_name_input_commitment=_digest("name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


def _plan(manifest, *, config=None):
    return IntegrationMetadataBackfillPlan(
        parent_manifest_digest=manifest.digest,
        migration_idempotency_key=manifest.migration_idempotency_key,
        entries=(
            IntegrationMetadataBackfillEntry(
                provider="kuaimai",
                name="default-kuaimai",
                config={},
            ),
            IntegrationMetadataBackfillEntry(
                provider="sf",
                name="default-sf",
                config=config or {},
            ),
            IntegrationMetadataBackfillEntry(
                provider="xianyu",
                name="default-xianyu",
                config={},
            ),
        ),
    )


@pytest.fixture
def control_database(mysql_control_database):
    with mysql_control_database.transaction() as session:
        session.add(Tenant(id=str(TENANT_UUID), status="provisioning"))
    return mysql_control_database


def test_metadata_only_backfill_creates_three_unconfigured_rows_and_replays(
    control_database,
) -> None:
    manifest = _manifest()
    plan = _plan(manifest)
    with control_database.transaction() as session:
        first = IntegrationMetadataBackfillService().backfill(
            session,
            manifest=manifest,
            plan=plan,
        )
    with control_database.transaction() as session:
        replay = IntegrationMetadataBackfillService().backfill(
            session,
            manifest=manifest,
            plan=plan,
        )

    assert first.created_count == 3
    assert first.replayed_count == 0
    assert replay.created_count == 0
    assert replay.replayed_count == 3
    assert replay.plan_digest == first.plan_digest
    with control_database.new_session() as session:
        integrations = tuple(
            session.scalars(
                sa.select(TenantIntegration).order_by(TenantIntegration.provider)
            )
        )
        assert [item.provider for item in integrations] == [
            "kuaimai",
            "sf",
            "xianyu",
        ]
        assert all(item.status == "unconfigured" for item in integrations)
        assert all(item.current_secret_revision_id is None for item in integrations)
        assert session.scalar(
            sa.select(sa.func.count()).select_from(
                TenantIntegrationSecretRevision
            )
        ) == 0


@pytest.mark.parametrize(
    "config",
    [
        {"password": "legacy-value"},
        {"api_key": "legacy-value"},
        {"partner_id": "legacy-value"},
        {"nested": {"token": "legacy-value"}},
        {"billing_mode": "monthly"},
    ],
)
def test_legacy_secret_shaped_config_is_rejected_and_transaction_rolls_back(
    control_database,
    config,
) -> None:
    manifest = _manifest()

    with pytest.raises(IntegrationMetadataBackfillInputError) as caught:
        with control_database.transaction() as session:
            IntegrationMetadataBackfillService().backfill(
                session,
                manifest=manifest,
                plan=_plan(manifest, config=config),
            )

    assert "legacy-value" not in str(caught.value)
    with control_database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(TenantIntegration)
        ) == 0


def test_plan_from_changed_manifest_is_rejected_before_write(control_database) -> None:
    original = _manifest()
    changed = _manifest(bundle="changed")

    with control_database.transaction() as session:
        with pytest.raises(IntegrationMetadataBackfillInputError):
            IntegrationMetadataBackfillService().backfill(
                session,
                manifest=changed,
                plan=_plan(original),
            )

    with control_database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(TenantIntegration)
        ) == 0
