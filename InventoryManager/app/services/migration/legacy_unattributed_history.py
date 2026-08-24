"""D68 migration of legacy logistics facts without execution authority."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final, Mapping
from uuid import uuid5

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from app.models.audit_log import AuditLog
from app.models.database_identity import TenantDatabaseIdentity
from app.models.legacy_unattributed_history import (
    LEGACY_UNATTRIBUTED_KIND,
    LegacyUnattributedPrintSnapshot,
    LegacyUnattributedShipmentSnapshot,
)
from app.models.rental import Rental
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
    WaybillPrintJob,
)
from inventory_control.default_migration import DefaultTenantMigrationManifest
from inventory_control.default_migration.historical_boundary import (
    DefaultHistoricalSnapshotBoundaryEvidence,
    DefaultHistoricalBoundaryError,
    HistoricalSnapshotDisposition,
)


LEGACY_UNATTRIBUTED_HISTORY_POLICY_REVISION: Final = 1
_SHIPMENT_UUID_DOMAIN: Final = "legacy-unattributed-shipment:rental:"
_PRINT_UUID_DOMAIN: Final = "legacy-unattributed-print:audit:"
_LIFECYCLE_STATUSES: Final = frozenset(
    {"shipped", "returned", "completed"}
)
_VALID_RENTAL_STATUSES: Final = frozenset(
    {
        "not_shipped",
        "scheduled_for_shipping",
        "shipped",
        "returned",
        "completed",
        "cancelled",
    }
)


class LegacyUnattributedHistoryError(RuntimeError):
    code = "LEGACY_UNATTRIBUTED_HISTORY_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class LegacyUnattributedHistoryInputError(LegacyUnattributedHistoryError):
    code = "LEGACY_UNATTRIBUTED_HISTORY_INPUT_INVALID"


class LegacyUnattributedHistoryTransactionError(
    LegacyUnattributedHistoryError
):
    code = "LEGACY_UNATTRIBUTED_HISTORY_TRANSACTION_INVALID"


class LegacyUnattributedHistoryIdentityError(
    LegacyUnattributedHistoryError
):
    code = "LEGACY_UNATTRIBUTED_HISTORY_IDENTITY_MISMATCH"


class LegacyUnattributedHistoryBoundaryError(
    LegacyUnattributedHistoryError
):
    code = "LEGACY_UNATTRIBUTED_HISTORY_BOUNDARY_MISMATCH"


class LegacyUnattributedHistoryConflictError(
    LegacyUnattributedHistoryError
):
    code = "LEGACY_UNATTRIBUTED_HISTORY_CONFLICT"


class LegacyUnattributedHistoryPersistenceError(
    LegacyUnattributedHistoryError
):
    code = "LEGACY_UNATTRIBUTED_HISTORY_PERSISTENCE_FAILED"


@dataclass(frozen=True, slots=True)
class LegacyUnattributedHistoryResult:
    manifest_digest: bytes
    source_snapshot_digest: bytes
    result_digest: bytes
    counts: tuple[tuple[str, int], ...]
    idempotent_replay: bool
    verification_passed: bool

    def __post_init__(self) -> None:
        if (
            not _digest(self.manifest_digest)
            or not _digest(self.source_snapshot_digest)
            or not _digest(self.result_digest)
            or not isinstance(self.counts, tuple)
            or tuple(sorted(self.counts)) != self.counts
            or len({key for key, _count in self.counts})
            != len(self.counts)
            or any(
                not isinstance(key, str)
                or not key
                or isinstance(count, bool)
                or not isinstance(count, int)
                or count < 0
                for key, count in self.counts
            )
            or not isinstance(self.idempotent_replay, bool)
            or self.verification_passed is not True
        ):
            raise LegacyUnattributedHistoryPersistenceError()

    def safe_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "counts": MappingProxyType(dict(self.counts)),
                "idempotent_replay": self.idempotent_replay,
                "manifest_digest": self.manifest_digest.hex(),
                "result_digest": self.result_digest.hex(),
                "verification_passed": True,
            }
        )


class LegacyUnattributedHistoryBackfillService:
    """Copy display facts into non-executable snapshots in one transaction."""

    def backfill(
        self,
        session: Session,
        *,
        manifest: DefaultTenantMigrationManifest,
        expected_schema_generation: int,
        historical_boundary: DefaultHistoricalSnapshotBoundaryEvidence,
    ) -> LegacyUnattributedHistoryResult:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or isinstance(expected_schema_generation, bool)
            or not isinstance(expected_schema_generation, int)
            or expected_schema_generation < 1
            or not isinstance(
                historical_boundary,
                DefaultHistoricalSnapshotBoundaryEvidence,
            )
            or historical_boundary.disposition
            is not HistoricalSnapshotDisposition.REQUIRES_APPROVED_NONEMPTY_ADAPTER
        ):
            raise LegacyUnattributedHistoryInputError()
        try:
            historical_boundary.require_manifest(manifest)
        except DefaultHistoricalBoundaryError:
            raise LegacyUnattributedHistoryBoundaryError() from None

        _require_explicit_transaction(session)
        try:
            _verify_identity(
                session,
                manifest=manifest,
                expected_schema_generation=expected_schema_generation,
            )
            rentals = _load_source_rentals(session)
            print_audits = _load_source_print_audits(session)
            source_counts = _source_counts(session, rentals, print_audits)
            if source_counts != historical_boundary.counts:
                raise LegacyUnattributedHistoryBoundaryError()

            created = 0
            shipment_rows: list[dict[str, object]] = []
            shipment_by_rental: dict[int, str] = {}
            for rental in rentals:
                expected = _shipment_values(manifest, rental)
                snapshot = session.get(
                    LegacyUnattributedShipmentSnapshot,
                    expected["id"],
                    with_for_update=True,
                )
                if snapshot is None:
                    snapshot = LegacyUnattributedShipmentSnapshot(**expected)
                    session.add(snapshot)
                    created += 1
                elif not _shipment_matches(snapshot, expected):
                    raise LegacyUnattributedHistoryConflictError()
                shipment_by_rental[rental.id] = snapshot.id
                shipment_rows.append(_shipment_evidence(expected))

            print_rows: list[dict[str, object]] = []
            for audit in print_audits:
                expected = _print_values(
                    manifest,
                    audit,
                    shipment_by_rental=shipment_by_rental,
                )
                snapshot = session.get(
                    LegacyUnattributedPrintSnapshot,
                    expected["id"],
                    with_for_update=True,
                )
                if snapshot is None:
                    snapshot = LegacyUnattributedPrintSnapshot(**expected)
                    session.add(snapshot)
                    created += 1
                elif not _print_matches(snapshot, expected):
                    raise LegacyUnattributedHistoryConflictError()
                print_rows.append(_print_evidence(expected))

            session.flush()
            _verify_persisted_counts(
                session,
                shipment_count=len(rentals),
                print_count=len(print_audits),
            )
        except LegacyUnattributedHistoryError:
            raise
        except IntegrityError:
            raise LegacyUnattributedHistoryConflictError() from None
        except SQLAlchemyError:
            raise LegacyUnattributedHistoryPersistenceError() from None

        counts = tuple(
            sorted(
                (
                    ("legacy_print_snapshots", len(print_rows)),
                    ("legacy_shipment_snapshots", len(shipment_rows)),
                )
            )
        )
        result_digest = _canonical_digest(
            {
                "counts": list(counts),
                "database_uuid": str(manifest.database_uuid),
                "manifest_digest": manifest.digest.hex(),
                "policy_revision": (
                    LEGACY_UNATTRIBUTED_HISTORY_POLICY_REVISION
                ),
                "prints": print_rows,
                "shipments": shipment_rows,
                "source_snapshot_digest": (
                    manifest.source_snapshot_digest.hex()
                ),
                "tenant_uuid": str(manifest.tenant_uuid),
            }
        )
        return LegacyUnattributedHistoryResult(
            manifest_digest=manifest.digest,
            source_snapshot_digest=manifest.source_snapshot_digest,
            result_digest=result_digest,
            counts=counts,
            idempotent_replay=created == 0,
            verification_passed=True,
        )


def _require_explicit_transaction(session: Session) -> None:
    if not isinstance(session, Session):
        raise LegacyUnattributedHistoryInputError()
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
        raise LegacyUnattributedHistoryTransactionError()


def _verify_identity(
    session: Session,
    *,
    manifest: DefaultTenantMigrationManifest,
    expected_schema_generation: int,
) -> None:
    rows = tuple(
        session.scalars(
            sa.select(TenantDatabaseIdentity)
            .order_by(TenantDatabaseIdentity.singleton_key)
            .with_for_update()
            .execution_options(autoflush=False, populate_existing=True)
        )
    )
    if len(rows) != 1:
        raise LegacyUnattributedHistoryIdentityError()
    row = rows[0]
    if (
        row.singleton_key != 1
        or row.tenant_id != str(manifest.tenant_uuid)
        or row.database_uuid != str(manifest.database_uuid)
        or row.schema_generation != expected_schema_generation
    ):
        raise LegacyUnattributedHistoryIdentityError()


def _historical_lifecycle() -> sa.ColumnElement[bool]:
    return sa.or_(
        Rental.status.in_(_LIFECYCLE_STATUSES),
        Rental.ship_out_time.is_not(None),
        Rental.ship_in_time.is_not(None),
        Rental.actual_shipped_at.is_not(None),
        Rental.actual_returned_at.is_not(None),
    )


def _legacy_tracking() -> sa.ColumnElement[bool]:
    return sa.or_(
        Rental.ship_out_tracking_no.is_not(None),
        Rental.ship_in_tracking_no.is_not(None),
    )


def _print_audit() -> sa.ColumnElement[bool]:
    return sa.or_(
        sa.func.lower(AuditLog.action).like("%print%"),
        AuditLog.action.like("%打印%"),
    )


def _load_source_rentals(session: Session) -> tuple[Rental, ...]:
    return tuple(
        session.scalars(
            sa.select(Rental)
            .where(sa.or_(_historical_lifecycle(), _legacy_tracking()))
            .order_by(Rental.id)
            .with_for_update()
            .execution_options(autoflush=False, populate_existing=True)
        )
    )


def _load_source_print_audits(session: Session) -> tuple[AuditLog, ...]:
    return tuple(
        session.scalars(
            sa.select(AuditLog)
            .where(_print_audit())
            .order_by(AuditLog.id)
            .with_for_update()
            .execution_options(autoflush=False, populate_existing=True)
        )
    )


def _source_counts(
    session: Session,
    rentals: tuple[Rental, ...],
    print_audits: tuple[AuditLog, ...],
) -> tuple[tuple[str, int], ...]:
    lifecycle_count = sum(
        rental.status in _LIFECYCLE_STATUSES
        or rental.ship_out_time is not None
        or rental.ship_in_time is not None
        or rental.actual_shipped_at is not None
        or rental.actual_returned_at is not None
        for rental in rentals
    )
    tracking_count = sum(
        rental.ship_out_tracking_no is not None
        or rental.ship_in_tracking_no is not None
        for rental in rentals
    )
    core_counts = {
        "outbound_shipments": session.scalar(
            sa.select(sa.func.count()).select_from(OutboundShipment)
        ),
        "provider_operation_attempts": session.scalar(
            sa.select(sa.func.count()).select_from(ProviderOperationAttempt)
        ),
        "waybill_print_jobs": session.scalar(
            sa.select(sa.func.count()).select_from(WaybillPrintJob)
        ),
    }
    if any(value != 0 for value in core_counts.values()):
        raise LegacyUnattributedHistoryBoundaryError()
    return tuple(
        sorted(
            {
                "legacy_historical_rentals": lifecycle_count,
                "legacy_print_audits": len(print_audits),
                "legacy_tracking_rows": tracking_count,
                **core_counts,
            }.items()
        )
    )


def _shipment_values(
    manifest: DefaultTenantMigrationManifest,
    rental: Rental,
) -> dict[str, object]:
    status = rental.status
    if hasattr(status, "value"):
        status = status.value
    if not isinstance(status, str) or status not in _VALID_RENTAL_STATUSES:
        raise LegacyUnattributedHistoryConflictError()
    ship_out_tracking_no = _tracking(rental.ship_out_tracking_no)
    ship_in_tracking_no = _tracking(rental.ship_in_tracking_no)
    shipped_at = rental.actual_shipped_at or rental.ship_out_time
    returned_at = rental.actual_returned_at or rental.ship_in_time
    source = {
        "lifecycle_status": status,
        "rental_id": rental.id,
        "returned_at": _datetime_text(returned_at),
        "ship_in_tracking_no": ship_in_tracking_no,
        "ship_out_tracking_no": ship_out_tracking_no,
        "shipped_at": _datetime_text(shipped_at),
    }
    return {
        "id": str(uuid5(manifest.database_uuid, _SHIPMENT_UUID_DOMAIN + str(rental.id))),
        "snapshot_kind": LEGACY_UNATTRIBUTED_KIND,
        "source_rental_id": rental.id,
        "rental_id": rental.id,
        "lifecycle_status": status,
        "ship_out_tracking_no": ship_out_tracking_no,
        "ship_in_tracking_no": ship_in_tracking_no,
        "shipped_at": shipped_at,
        "returned_at": returned_at,
        "source_digest": _canonical_digest(source).hex(),
        "migration_manifest_digest": manifest.digest.hex(),
    }


def _print_values(
    manifest: DefaultTenantMigrationManifest,
    audit: AuditLog,
    *,
    shipment_by_rental: Mapping[int, str],
) -> dict[str, object]:
    source = {
        "audit_id": audit.id,
        "occurred_at": _datetime_text(audit.created_at),
        "rental_id": audit.rental_id,
    }
    return {
        "id": str(uuid5(manifest.database_uuid, _PRINT_UUID_DOMAIN + str(audit.id))),
        "snapshot_kind": LEGACY_UNATTRIBUTED_KIND,
        "source_audit_id": audit.id,
        "rental_id": audit.rental_id,
        "shipment_snapshot_id": shipment_by_rental.get(audit.rental_id),
        "occurred_at": audit.created_at,
        "source_digest": _canonical_digest(source).hex(),
        "migration_manifest_digest": manifest.digest.hex(),
    }


def _shipment_matches(
    row: LegacyUnattributedShipmentSnapshot,
    expected: Mapping[str, object],
) -> bool:
    return all(
        getattr(row, key) == value
        for key, value in expected.items()
    )


def _print_matches(
    row: LegacyUnattributedPrintSnapshot,
    expected: Mapping[str, object],
) -> bool:
    return all(getattr(row, key) == value for key, value in expected.items())


def _shipment_evidence(expected: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": expected["id"],
        "source_digest": expected["source_digest"],
        "source_rental_id": expected["source_rental_id"],
    }


def _print_evidence(expected: Mapping[str, object]) -> dict[str, object]:
    return {
        "id": expected["id"],
        "source_audit_id": expected["source_audit_id"],
        "source_digest": expected["source_digest"],
    }


def _verify_persisted_counts(
    session: Session,
    *,
    shipment_count: int,
    print_count: int,
) -> None:
    counts = {
        "legacy_shipments": session.scalar(
            sa.select(sa.func.count()).select_from(
                LegacyUnattributedShipmentSnapshot
            )
        ),
        "legacy_prints": session.scalar(
            sa.select(sa.func.count()).select_from(
                LegacyUnattributedPrintSnapshot
            )
        ),
        "outbound_shipments": session.scalar(
            sa.select(sa.func.count()).select_from(OutboundShipment)
        ),
        "provider_operation_attempts": session.scalar(
            sa.select(sa.func.count()).select_from(ProviderOperationAttempt)
        ),
        "waybill_print_jobs": session.scalar(
            sa.select(sa.func.count()).select_from(WaybillPrintJob)
        ),
    }
    if counts != {
        "legacy_shipments": shipment_count,
        "legacy_prints": print_count,
        "outbound_shipments": 0,
        "provider_operation_attempts": 0,
        "waybill_print_jobs": 0,
    }:
        raise LegacyUnattributedHistoryConflictError()


def _tracking(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) > 64
        or any(ord(character) < 32 or ord(character) == 127 for character in value)
    ):
        raise LegacyUnattributedHistoryConflictError()
    return value


def _datetime_text(value: datetime | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, datetime):
        raise LegacyUnattributedHistoryConflictError()
    return value.isoformat(timespec="microseconds")


def _canonical_digest(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise LegacyUnattributedHistoryConflictError() from None
    return hashlib.sha256(encoded).digest()


def _digest(value: object) -> bool:
    return isinstance(value, bytes) and len(value) == 32


__all__ = [
    "LEGACY_UNATTRIBUTED_HISTORY_POLICY_REVISION",
    "LegacyUnattributedHistoryBackfillService",
    "LegacyUnattributedHistoryBoundaryError",
    "LegacyUnattributedHistoryConflictError",
    "LegacyUnattributedHistoryError",
    "LegacyUnattributedHistoryIdentityError",
    "LegacyUnattributedHistoryInputError",
    "LegacyUnattributedHistoryPersistenceError",
    "LegacyUnattributedHistoryResult",
    "LegacyUnattributedHistoryTransactionError",
]
