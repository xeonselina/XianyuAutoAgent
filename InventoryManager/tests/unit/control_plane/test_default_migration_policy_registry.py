from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from datetime import date
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental
from app.models.warehouse import Warehouse
from inventory_control.default_migration import (
    DefaultLegacyAuthorityBoundaryEvidence,
    DefaultLegacyDoubleCountCollector,
    DefaultMigrationReconciliationRunner,
    DefaultTenantMigrationManifest,
    DefaultTenantReconciliationExpectedFacts,
    DefaultTenantReconciliationSqlRegistry,
    MigrationReconciliationCollectionError,
    ReconciliationObservation,
    build_default_tenant_reconciliation_policy,
    compose_default_tenant_reconciliation_collectors,
)
from inventory_control.models import ControlBase
from tests.support.test_database import build_mysql_test_config


TENANT_UUID = UUID("53000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("53000000-0000-4000-8000-000000000002")


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-policy-v1",
        tenant_uuid=TENANT_UUID,
        database_uuid=DATABASE_UUID,
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID("53000000-0000-4000-8000-000000000003"),
        control_schema_head="202608220026",
        tenant_schema_head="rev_9",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("name"),
        first_admin_phone_input_commitment=_digest("phone"),
    )


@dataclass(frozen=True)
class _SupplementalCollector:
    key: str
    observed: int | bytes

    def collect(self, *, manifest, requirement):
        assert manifest == _manifest()
        assert requirement.key == self.key
        return ReconciliationObservation(key=self.key, observed=self.observed)


@pytest.fixture
def databases(mysql_routed_database):
    app = create_app(build_mysql_test_config())
    with app.app_context():
        warehouse = Warehouse(
            name="default",
            status="active",
            setup_state="ready",
            is_default=True,
            default_slot=1,
            contact_name="fixture",
            contact_phone="13800000000",
            province="北京市",
            city="北京市",
            district="朝阳区",
            address_detail="fixture",
        )
        first = Device(name="first", model="x200u", warehouse=warehouse)
        second = Device(name="second", model="x200u", warehouse=warehouse)
        rental = Rental(
            device=first,
            start_date=date(2026, 9, 10),
            end_date=date(2026, 9, 12),
            customer_name="fixture",
            order_amount="12.34",
            status="not_shipped",
        )
        db.session.add_all((warehouse, first, second, rental))
        db.session.commit()
        with mysql_routed_database.new_session() as control_session:
            try:
                yield db.session(), control_session
            finally:
                db.session.remove()


def _facts():
    return DefaultTenantReconciliationExpectedFacts(
        accessory_links=0,
        credential_revisions=0,
        device_warehouse_links=2,
        legacy_double_count=0,
        rental_total_minor=1234,
        orphan_count=0,
        rental_device_links=1,
        schema_digest=_digest("schema-9"),
        schema_generation=9,
        historical_waybills=0,
        device_rows=2,
        default_warehouse_count=1,
    )


def _legacy_authority_evidence(manifest):
    return DefaultLegacyAuthorityBoundaryEvidence(
        manifest_digest=manifest.digest,
        source_snapshot_digest=manifest.source_snapshot_digest,
        implementation_identity_digest=(manifest.implementation_identity_digest),
        migration_bundle_digest=manifest.migration_bundle_digest,
        legacy_quantity_negative_digest=_digest("legacy-quantity-negative"),
        legacy_child_rental_negative_digest=_digest("legacy-child-rental-negative"),
        legacy_global_provider_negative_digest=_digest(
            "legacy-global-provider-negative"
        ),
        legacy_shipment_writer_negative_digest=_digest(
            "legacy-shipment-writer-negative"
        ),
    )


def test_policy_and_registry_run_exact_cross_database_queries(databases) -> None:
    tenant_session, control_session = databases
    policy = build_default_tenant_reconciliation_policy(_facts())
    registry = DefaultTenantReconciliationSqlRegistry(
        manifest=_manifest(),
        tenant_session=tenant_session,
        control_session=control_session,
    )
    supplemental = (
        DefaultLegacyDoubleCountCollector(_legacy_authority_evidence(_manifest())),
        _SupplementalCollector("schema.digest", _digest("schema-9")),
        _SupplementalCollector("schema.generation", 9),
    )
    collectors = compose_default_tenant_reconciliation_collectors(
        policy=policy,
        sql_registry=registry,
        supplemental_collectors=supplemental,
    )

    report = DefaultMigrationReconciliationRunner(collectors).collect_and_evaluate(
        manifest=_manifest(), policy=policy
    )

    assert report.passed is True
    assert tuple(item.key for item in registry.collectors()) == (
        "accessories.links",
        "credentials.revisions",
        "devices.warehouse_links",
        "money.rental_total_minor",
        "orphans.foreign_keys",
        "rentals.device_links",
        "shipments.historical_waybills",
        "tables.devices.rows",
        "warehouses.default_count",
    )
    orphan_collector = next(
        item for item in registry.collectors() if item.key == "orphans.foreign_keys"
    )
    assert "rental_accessories" not in str(orphan_collector.statement)


def test_legacy_authority_evidence_is_manifest_bound_and_nonzero_fails_closed():
    manifest = _manifest()
    policy = build_default_tenant_reconciliation_policy(_facts())
    requirement = next(
        item for item in policy.requirements if item.key == "legacy.double_count"
    )
    evidence = _legacy_authority_evidence(manifest)
    collector = DefaultLegacyDoubleCountCollector(evidence)

    assert (
        collector.collect(
            manifest=manifest,
            requirement=requirement,
        ).observed
        == 0
    )
    assert "legacy-quantity-negative" not in repr(evidence)

    changed_manifest = replace(
        manifest,
        source_snapshot_digest=_digest("other-source"),
    )
    with pytest.raises(MigrationReconciliationCollectionError):
        collector.collect(
            manifest=changed_manifest,
            requirement=requirement,
        )
    with pytest.raises(MigrationReconciliationCollectionError):
        replace(evidence, legacy_shipment_writer_authority_count=1)


def test_policy_rejects_nonzero_double_count_and_composition_gaps(
    databases,
) -> None:
    with pytest.raises(MigrationReconciliationCollectionError):
        replace(_facts(), legacy_double_count=1)

    tenant_session, control_session = databases
    policy = build_default_tenant_reconciliation_policy(_facts())
    registry = DefaultTenantReconciliationSqlRegistry(
        manifest=_manifest(),
        tenant_session=tenant_session,
        control_session=control_session,
    )
    with pytest.raises(MigrationReconciliationCollectionError):
        compose_default_tenant_reconciliation_collectors(
            policy=policy,
            sql_registry=registry,
            supplemental_collectors=(),
        )
