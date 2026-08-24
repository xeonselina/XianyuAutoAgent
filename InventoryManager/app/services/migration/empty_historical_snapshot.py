"""Fail-closed proof for a source with no historical shipping/print facts.

This adapter deliberately handles only the zero-history case.  It does not
invent a credential revision for legacy SF/Kuaimai facts and never creates a
shipment, provider attempt, print job, credential revision, or provider call.
Any durable hint that shipping or printing may have occurred rejects this
path so a separately approved non-empty historical adapter remains required.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from app.models.audit_log import AuditLog
from app.models.database_identity import TenantDatabaseIdentity
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
from inventory_control.default_migration import (
    DefaultTenantMigrationManifest,
)


EMPTY_HISTORICAL_SNAPSHOT_POLICY_REVISION: Final = 1


class EmptyHistoricalSnapshotError(RuntimeError):
    code = "EMPTY_HISTORICAL_SNAPSHOT_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class EmptyHistoricalSnapshotInputError(EmptyHistoricalSnapshotError):
    code = "EMPTY_HISTORICAL_SNAPSHOT_INPUT_INVALID"


class EmptyHistoricalSnapshotTransactionError(EmptyHistoricalSnapshotError):
    code = "EMPTY_HISTORICAL_SNAPSHOT_TRANSACTION_INVALID"


class EmptyHistoricalSnapshotIdentityError(EmptyHistoricalSnapshotError):
    code = "EMPTY_HISTORICAL_SNAPSHOT_IDENTITY_MISMATCH"


class HistoricalSnapshotNotEmptyError(EmptyHistoricalSnapshotError):
    code = "HISTORICAL_SNAPSHOT_REQUIRES_APPROVED_NONEMPTY_ADAPTER"


class EmptyHistoricalSnapshotPersistenceError(EmptyHistoricalSnapshotError):
    code = "EMPTY_HISTORICAL_SNAPSHOT_PERSISTENCE_FAILED"


@dataclass(frozen=True, slots=True)
class EmptyHistoricalSnapshotResult:
    manifest_digest: bytes
    source_snapshot_digest: bytes
    result_digest: bytes
    counts: tuple[tuple[str, int], ...]
    verification_passed: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.manifest_digest, bytes)
            or len(self.manifest_digest) != 32
            or not isinstance(self.source_snapshot_digest, bytes)
            or len(self.source_snapshot_digest) != 32
            or not isinstance(self.result_digest, bytes)
            or len(self.result_digest) != 32
            or not isinstance(self.counts, tuple)
            or tuple(sorted(self.counts)) != self.counts
            or len({key for key, _count in self.counts}) != len(self.counts)
            or any(
                not isinstance(key, str)
                or not key
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
                for key, count in self.counts
            )
            or self.verification_passed is not True
            or any(count != 0 for _key, count in self.counts)
        ):
            raise EmptyHistoricalSnapshotPersistenceError()

    def safe_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "manifest_digest": self.manifest_digest.hex(),
                "result_digest": self.result_digest.hex(),
                "counts": MappingProxyType(dict(self.counts)),
                "verification_passed": True,
            }
        )


class EmptyHistoricalSnapshotVerifier:
    """Prove a bound tenant schema has no migratable history at all."""

    def verify(
        self,
        session: Session,
        *,
        manifest: DefaultTenantMigrationManifest,
        expected_schema_generation: int,
    ) -> EmptyHistoricalSnapshotResult:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or isinstance(expected_schema_generation, bool)
            or not isinstance(expected_schema_generation, int)
            or expected_schema_generation < 1
        ):
            raise EmptyHistoricalSnapshotInputError()
        _prepare_session(session)
        _verify_database_identity(
            session,
            tenant_uuid=manifest.tenant_uuid,
            database_uuid=manifest.database_uuid,
            schema_generation=expected_schema_generation,
        )
        counts = _collect_counts(session)
        if any(count != 0 for _key, count in counts):
            raise HistoricalSnapshotNotEmptyError()
        result_digest = hashlib.sha256(
            b"inventory-manager/empty-historical-snapshot/v1\x00"
            + json.dumps(
                {
                    "counts": list(counts),
                    "database_uuid": str(manifest.database_uuid),
                    "manifest_digest": manifest.digest.hex(),
                    "policy_revision": (
                        EMPTY_HISTORICAL_SNAPSHOT_POLICY_REVISION
                    ),
                    "schema_generation": expected_schema_generation,
                    "source_snapshot_digest": (
                        manifest.source_snapshot_digest.hex()
                    ),
                    "tenant_uuid": str(manifest.tenant_uuid),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).digest()
        return EmptyHistoricalSnapshotResult(
            manifest_digest=manifest.digest,
            source_snapshot_digest=manifest.source_snapshot_digest,
            result_digest=result_digest,
            counts=counts,
            verification_passed=True,
        )


def _prepare_session(session: Session) -> None:
    if not isinstance(session, Session):
        raise EmptyHistoricalSnapshotInputError()
    transaction = session.get_transaction()
    dirty = any(
        session.is_modified(instance, include_collections=True)
        for instance in session.dirty
    )
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        or session.new
        or session.deleted
        or dirty
    ):
        raise EmptyHistoricalSnapshotTransactionError()
    try:
        connection = session.connection()
        if connection.dialect.name == "sqlite":
            driver = getattr(
                connection.connection,
                "driver_connection",
                None,
            )
            if driver is not None and not driver.in_transaction:
                connection.exec_driver_sql("BEGIN IMMEDIATE")
    except EmptyHistoricalSnapshotError:
        raise
    except SQLAlchemyError:
        raise EmptyHistoricalSnapshotPersistenceError() from None


def _verify_database_identity(
    session: Session,
    *,
    tenant_uuid: UUID,
    database_uuid: UUID,
    schema_generation: int,
) -> None:
    try:
        rows = tuple(
            session.scalars(
                sa.select(TenantDatabaseIdentity)
                .order_by(TenantDatabaseIdentity.singleton_key)
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
        )
    except SQLAlchemyError:
        raise EmptyHistoricalSnapshotPersistenceError() from None
    if len(rows) != 1:
        raise EmptyHistoricalSnapshotIdentityError()
    row = rows[0]
    if (
        row.singleton_key != 1
        or row.tenant_id != str(tenant_uuid)
        or row.database_uuid != str(database_uuid)
        or row.schema_generation != schema_generation
    ):
        raise EmptyHistoricalSnapshotIdentityError()


def _collect_counts(session: Session) -> tuple[tuple[str, int], ...]:
    historical_status = sa.or_(
        Rental.status.in_(("shipped", "returned", "completed")),
        Rental.actual_shipped_at.is_not(None),
        Rental.actual_returned_at.is_not(None),
    )
    legacy_tracking = sa.or_(
        Rental.ship_out_tracking_no.is_not(None),
        Rental.ship_in_tracking_no.is_not(None),
    )
    print_audit = sa.or_(
        sa.func.lower(AuditLog.action).like("%print%"),
        AuditLog.action.like("%打印%"),
    )
    statements = {
        "legacy_historical_rentals": (
            sa.select(sa.func.count()).select_from(Rental).where(
                historical_status
            )
        ),
        "legacy_print_audits": (
            sa.select(sa.func.count()).select_from(AuditLog).where(print_audit)
        ),
        "legacy_tracking_rows": (
            sa.select(sa.func.count()).select_from(Rental).where(
                legacy_tracking
            )
        ),
        "legacy_unattributed_prints": (
            sa.select(sa.func.count()).select_from(
                LegacyUnattributedPrintSnapshot
            )
        ),
        "legacy_unattributed_shipments": (
            sa.select(sa.func.count()).select_from(
                LegacyUnattributedShipmentSnapshot
            )
        ),
        "outbound_shipments": (
            sa.select(sa.func.count()).select_from(OutboundShipment)
        ),
        "provider_operation_attempts": (
            sa.select(sa.func.count()).select_from(ProviderOperationAttempt)
        ),
        "waybill_print_jobs": (
            sa.select(sa.func.count()).select_from(WaybillPrintJob)
        ),
    }
    try:
        values = tuple(
            sorted(
                (key, session.scalar(statement))
                for key, statement in statements.items()
            )
        )
    except SQLAlchemyError:
        raise EmptyHistoricalSnapshotPersistenceError() from None
    if any(
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for _key, value in values
    ):
        raise EmptyHistoricalSnapshotPersistenceError()
    return values


__all__ = [
    "EMPTY_HISTORICAL_SNAPSHOT_POLICY_REVISION",
    "EmptyHistoricalSnapshotError",
    "EmptyHistoricalSnapshotIdentityError",
    "EmptyHistoricalSnapshotInputError",
    "EmptyHistoricalSnapshotPersistenceError",
    "EmptyHistoricalSnapshotResult",
    "EmptyHistoricalSnapshotTransactionError",
    "EmptyHistoricalSnapshotVerifier",
    "HistoricalSnapshotNotEmptyError",
]
