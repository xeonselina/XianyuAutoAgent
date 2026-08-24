"""Versioned default-tenant reconciliation policy and concrete SQL registry."""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models.accessory_inventory import (
    AccessoryType,
    AccessoryUnit,
    AccessoryUnitEvent,
    RentalAccessoryRequest,
    RentalAccessoryUnitLink,
)
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.models.rental_accessory import RentalAccessory
from app.models.rental_relay_case import RentalRelayCase
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
    WaybillPrintJob,
)
from app.models.warehouse import Warehouse
from inventory_control.models.integrations import (
    TenantIntegrationSecretRevision,
)

from .collection import (
    DefaultMigrationReconciliationCollector,
    MigrationReconciliationCollectionError,
)
from .manifest import DefaultTenantMigrationManifest
from .reconciliation import (
    ReconciliationPolicy,
    ReconciliationRequirement,
    ReconciliationScope,
    ReconciliationValueKind,
)
from .sqlalchemy_collection import SqlAlchemyScalarReconciliationCollector


DEFAULT_TENANT_RECONCILIATION_POLICY_VERSION = 1


@dataclass(frozen=True, slots=True, kw_only=True)
class DefaultTenantReconciliationExpectedFacts:
    """Source-snapshot facts fixed before any backfill mutation."""

    accessory_links: int
    credential_revisions: int
    device_warehouse_links: int
    legacy_double_count: int
    rental_total_minor: int
    orphan_count: int
    rental_device_links: int
    schema_digest: bytes
    schema_generation: int
    historical_waybills: int
    device_rows: int
    default_warehouse_count: int

    def __post_init__(self) -> None:
        for name in (
            "accessory_links",
            "credential_revisions",
            "device_warehouse_links",
            "legacy_double_count",
            "rental_total_minor",
            "orphan_count",
            "rental_device_links",
            "historical_waybills",
            "device_rows",
            "default_warehouse_count",
        ):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise MigrationReconciliationCollectionError()
        if self.legacy_double_count != 0:
            raise MigrationReconciliationCollectionError()
        if (
            isinstance(self.schema_generation, bool)
            or not isinstance(self.schema_generation, int)
            or self.schema_generation < 1
            or not isinstance(self.schema_digest, bytes)
            or len(self.schema_digest) != 32
        ):
            raise MigrationReconciliationCollectionError()


def build_default_tenant_reconciliation_policy(
    facts: DefaultTenantReconciliationExpectedFacts,
) -> ReconciliationPolicy:
    if not isinstance(facts, DefaultTenantReconciliationExpectedFacts):
        raise MigrationReconciliationCollectionError()
    definitions = (
        (
            "accessories.links",
            ReconciliationScope.ACCESSORY_ASSOCIATION,
            ReconciliationValueKind.NONNEGATIVE_INTEGER,
            facts.accessory_links,
            False,
        ),
        (
            "credentials.revisions",
            ReconciliationScope.CREDENTIAL_REVISION,
            ReconciliationValueKind.NONNEGATIVE_INTEGER,
            facts.credential_revisions,
            False,
        ),
        (
            "devices.warehouse_links",
            ReconciliationScope.DEVICE_ASSOCIATION,
            ReconciliationValueKind.NONNEGATIVE_INTEGER,
            facts.device_warehouse_links,
            False,
        ),
        (
            "legacy.double_count",
            ReconciliationScope.LEGACY_DOUBLE_COUNT,
            ReconciliationValueKind.NONNEGATIVE_INTEGER,
            facts.legacy_double_count,
            False,
        ),
        (
            "money.rental_total_minor",
            ReconciliationScope.MONETARY_AMOUNT,
            ReconciliationValueKind.NONNEGATIVE_INTEGER,
            facts.rental_total_minor,
            False,
        ),
        (
            "orphans.foreign_keys",
            ReconciliationScope.ORPHAN_COUNT,
            ReconciliationValueKind.NONNEGATIVE_INTEGER,
            facts.orphan_count,
            True,
        ),
        (
            "rentals.device_links",
            ReconciliationScope.RENTAL_ASSOCIATION,
            ReconciliationValueKind.NONNEGATIVE_INTEGER,
            facts.rental_device_links,
            False,
        ),
        (
            "schema.digest",
            ReconciliationScope.SCHEMA_DIGEST,
            ReconciliationValueKind.SHA256_DIGEST,
            facts.schema_digest,
            False,
        ),
        (
            "schema.generation",
            ReconciliationScope.SCHEMA_GENERATION,
            ReconciliationValueKind.POSITIVE_INTEGER,
            facts.schema_generation,
            False,
        ),
        (
            "shipments.historical_waybills",
            ReconciliationScope.HISTORICAL_WAYBILL,
            ReconciliationValueKind.NONNEGATIVE_INTEGER,
            facts.historical_waybills,
            False,
        ),
        (
            "tables.devices.rows",
            ReconciliationScope.TABLE_ROW_COUNT,
            ReconciliationValueKind.NONNEGATIVE_INTEGER,
            facts.device_rows,
            False,
        ),
        (
            "warehouses.default_count",
            ReconciliationScope.DEFAULT_WAREHOUSE,
            ReconciliationValueKind.NONNEGATIVE_INTEGER,
            facts.default_warehouse_count,
            False,
        ),
    )
    return ReconciliationPolicy(
        policy_version=DEFAULT_TENANT_RECONCILIATION_POLICY_VERSION,
        requirements=tuple(
            ReconciliationRequirement(
                key=key,
                scope=scope,
                value_kind=kind,
                expected=expected,
                tolerance=0,
                disposition_allowed=disposition_allowed,
            )
            for key, scope, kind, expected, disposition_allowed in definitions
        ),
    )


@dataclass(frozen=True, slots=True)
class DefaultTenantReconciliationSqlRegistry:
    """Nine fixed non-locking queries over already-bound control/tenant DBs."""

    manifest: DefaultTenantMigrationManifest
    tenant_session: Session
    control_session: Session

    def __post_init__(self) -> None:
        if (
            not isinstance(self.manifest, DefaultTenantMigrationManifest)
            or not isinstance(self.tenant_session, Session)
            or not isinstance(self.control_session, Session)
            or self.tenant_session is self.control_session
        ):
            raise MigrationReconciliationCollectionError()

    def collectors(
        self,
    ) -> tuple[SqlAlchemyScalarReconciliationCollector, ...]:
        tenant_statements = {
            "accessories.links": _accessory_links_statement(),
            "devices.warehouse_links": _device_warehouse_links_statement(),
            "money.rental_total_minor": _rental_total_minor_statement(),
            "orphans.foreign_keys": _orphan_count_statement(),
            "rentals.device_links": _rental_device_links_statement(),
            "shipments.historical_waybills": _historical_waybills_statement(),
            "tables.devices.rows": sa.select(sa.func.count()).select_from(
                Device
            ),
            "warehouses.default_count": _default_warehouse_statement(),
        }
        selected = [
            SqlAlchemyScalarReconciliationCollector(
                key=key,
                session=self.tenant_session,
                statement=statement,
            )
            for key, statement in tenant_statements.items()
        ]
        selected.append(
            SqlAlchemyScalarReconciliationCollector(
                key="credentials.revisions",
                session=self.control_session,
                statement=sa.select(sa.func.count())
                .select_from(TenantIntegrationSecretRevision)
                .where(
                    TenantIntegrationSecretRevision.tenant_id
                    == str(self.manifest.tenant_uuid)
                ),
            )
        )
        return tuple(sorted(selected, key=lambda item: item.key))


def compose_default_tenant_reconciliation_collectors(
    *,
    policy: ReconciliationPolicy,
    sql_registry: DefaultTenantReconciliationSqlRegistry,
    supplemental_collectors: tuple[
        DefaultMigrationReconciliationCollector, ...
    ],
) -> tuple[DefaultMigrationReconciliationCollector, ...]:
    """Require schema and authority-boundary collectors to close coverage."""

    if (
        not isinstance(policy, ReconciliationPolicy)
        or not isinstance(sql_registry, DefaultTenantReconciliationSqlRegistry)
        or not isinstance(supplemental_collectors, tuple)
    ):
        raise MigrationReconciliationCollectionError()
    try:
        selected = tuple(
            sorted(
                sql_registry.collectors() + supplemental_collectors,
                key=lambda item: item.key,
            )
        )
        keys = tuple(item.key for item in selected)
    except Exception:
        raise MigrationReconciliationCollectionError() from None
    required = tuple(item.key for item in policy.requirements)
    if keys != required or len(keys) != len(set(keys)):
        raise MigrationReconciliationCollectionError()
    return selected


def _accessory_links_statement() -> sa.sql.Select:
    link = RentalAccessoryUnitLink.__table__
    request = RentalAccessoryRequest.__table__
    unit = AccessoryUnit.__table__
    return sa.select(sa.func.count()).select_from(
        link.join(
            request,
            sa.and_(
                request.c.rental_id == link.c.rental_id,
                request.c.accessory_type_id == link.c.accessory_type_id,
            ),
        ).join(
            unit,
            sa.and_(
                unit.c.id == link.c.accessory_unit_id,
                unit.c.accessory_type_id == link.c.accessory_type_id,
            ),
        )
    )


def _device_warehouse_links_statement() -> sa.sql.Select:
    device = Device.__table__
    warehouse = Warehouse.__table__
    return sa.select(sa.func.count()).select_from(
        device.join(warehouse, warehouse.c.id == device.c.warehouse_id)
    )


def _rental_device_links_statement() -> sa.sql.Select:
    rental = Rental.__table__
    device = Device.__table__
    return sa.select(sa.func.count()).select_from(
        rental.join(device, device.c.id == rental.c.device_id)
    )


def _rental_total_minor_statement() -> sa.sql.Select:
    amount_minor = sa.cast(
        sa.func.coalesce(Rental.order_amount, 0) * 100,
        sa.BigInteger,
    )
    # MySQL returns DECIMAL for SUM(BIGINT).  Cast the aggregate, not only
    # each row, so the scalar collector receives the policy's integer type on
    # both MySQL and SQLite.
    return sa.select(
        sa.cast(
            sa.func.coalesce(sa.func.sum(amount_minor), 0),
            sa.BigInteger,
        )
    )


def _historical_waybills_statement() -> sa.sql.Select:
    return (
        sa.select(sa.func.count())
        .select_from(OutboundShipment)
        .where(OutboundShipment.waybill_no.is_not(None))
    )


def _default_warehouse_statement() -> sa.sql.Select:
    return (
        sa.select(sa.func.count())
        .select_from(Warehouse)
        .where(Warehouse.is_default.is_(True), Warehouse.default_slot == 1)
    )


def _orphan_count_statement() -> sa.sql.Select:
    device = Device.__table__
    device_model = DeviceModel.__table__
    warehouse = Warehouse.__table__
    rental = Rental.__table__
    legacy_accessory = RentalAccessory.__table__
    accessory_type = AccessoryType.__table__
    unit = AccessoryUnit.__table__
    request = RentalAccessoryRequest.__table__
    link = RentalAccessoryUnitLink.__table__
    event = AccessoryUnitEvent.__table__
    relay_case = RentalRelayCase.__table__
    shipment = OutboundShipment.__table__
    attempt = ProviderOperationAttempt.__table__
    print_job = WaybillPrintJob.__table__

    counts = (
        _missing_reference(device, device.c.model_id, device_model),
        _missing_reference(device, device.c.warehouse_id, warehouse),
        _missing_reference(rental, rental.c.device_id, device),
        _missing_reference(rental, rental.c.parent_rental_id, rental),
        _missing_reference(
            rental, rental.c.preferred_warehouse_id, warehouse
        ),
        _missing_reference(
            rental,
            rental.c.logistics_estimate_origin_warehouse_id,
            warehouse,
        ),
        _missing_reference(
            legacy_accessory, legacy_accessory.c.rental_id, rental
        ),
        _missing_reference(
            legacy_accessory, legacy_accessory.c.device_id, device
        ),
        _missing_reference(unit, unit.c.accessory_type_id, accessory_type),
        _missing_reference(unit, unit.c.warehouse_id, warehouse),
        _missing_reference(unit, unit.c.current_holder_rental_id, rental),
        _missing_reference(request, request.c.rental_id, rental),
        _missing_reference(
            request, request.c.accessory_type_id, accessory_type
        ),
        _missing_reference(link, link.c.rental_id, rental),
        _missing_reference(link, link.c.accessory_type_id, accessory_type),
        _missing_reference(link, link.c.accessory_unit_id, unit),
        _missing_reference(
            link, link.c.source_relay_case_id, relay_case
        ),
        _missing_reference(event, event.c.unit_id, unit),
        _missing_reference(event, event.c.main_device_id, device),
        _missing_reference(event, event.c.rental_id, rental),
        _missing_reference(event, event.c.relay_case_id, relay_case),
        _missing_reference(event, event.c.from_warehouse_id, warehouse),
        _missing_reference(event, event.c.to_warehouse_id, warehouse),
        _missing_reference(shipment, shipment.c.rental_id, rental),
        _missing_reference(
            shipment, shipment.c.origin_warehouse_id, warehouse
        ),
        _missing_reference(attempt, attempt.c.shipment_id, shipment),
        _missing_reference(print_job, print_job.c.shipment_id, shipment),
        _missing_reference(print_job, print_job.c.rental_id, rental),
        _missing_reference(
            print_job, print_job.c.return_warehouse_id, warehouse
        ),
        _orphan_scalar(
            link.join(unit, unit.c.id == link.c.accessory_unit_id),
            unit.c.accessory_type_id != link.c.accessory_type_id,
        ),
    )
    total = counts[0]
    for count in counts[1:]:
        total = total + count
    return sa.select(sa.func.coalesce(total, 0))


def _orphan_scalar(from_clause: object, predicate: object):
    return (
        sa.select(sa.func.count())
        .select_from(from_clause)
        .where(predicate)
        .scalar_subquery()
    )


def _missing_reference(
    child: sa.Table,
    foreign_key: sa.Column,
    parent: sa.Table,
):
    parent_view = parent.alias()
    parent_key = parent_view.c[parent.primary_key.columns.values()[0].name]
    return _orphan_scalar(
        child.outerjoin(parent_view, parent_key == foreign_key),
        sa.and_(foreign_key.is_not(None), parent_key.is_(None)),
    )


__all__ = [
    "DEFAULT_TENANT_RECONCILIATION_POLICY_VERSION",
    "DefaultTenantReconciliationExpectedFacts",
    "DefaultTenantReconciliationSqlRegistry",
    "build_default_tenant_reconciliation_policy",
    "compose_default_tenant_reconciliation_collectors",
]
