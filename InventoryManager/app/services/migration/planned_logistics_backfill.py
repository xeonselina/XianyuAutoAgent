"""Manifest-bound planned-logistics backfill for reliable legacy rentals."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Final

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.database_identity import TenantDatabaseIdentity
from app.models.rental import Rental
from app.services.scheduling.overlap_policy import (
    ACTIVE_RENTAL_STATUSES,
    ScheduleOverlapPolicy,
    ScheduleValidationError,
)
from inventory_control.default_migration import DefaultTenantMigrationManifest
from inventory_control.transactions import require_caller_transaction

PLANNED_LOGISTICS_BACKFILL_POLICY_REVISION: Final = 2
_SAFE_KEY: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}")
_RENTAL_STATUSES: Final = frozenset(ACTIVE_RENTAL_STATUSES | {"completed", "cancelled"})


class PlannedLogisticsBackfillError(RuntimeError):
    code = "PLANNED_LOGISTICS_BACKFILL_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class PlannedLogisticsBackfillInputError(PlannedLogisticsBackfillError):
    code = "PLANNED_LOGISTICS_BACKFILL_INPUT_INVALID"


class PlannedLogisticsBackfillTransactionError(PlannedLogisticsBackfillError):
    code = "PLANNED_LOGISTICS_BACKFILL_TRANSACTION_INVALID"


class PlannedLogisticsBackfillIdentityMismatchError(PlannedLogisticsBackfillError):
    code = "PLANNED_LOGISTICS_BACKFILL_IDENTITY_MISMATCH"


class PlannedLogisticsBackfillConflictError(PlannedLogisticsBackfillError):
    code = "PLANNED_LOGISTICS_BACKFILL_CONFLICT"


class PlannedLogisticsBackfillPersistenceError(PlannedLogisticsBackfillError):
    code = "PLANNED_LOGISTICS_BACKFILL_PERSISTENCE_FAILED"


def legacy_logistics_source_digest(
    *,
    ship_out_time: datetime | None,
    ship_in_time: datetime | None,
    scheduled_ship_time: datetime | None,
) -> bytes:
    values = {
        "scheduled_ship_time": scheduled_ship_time,
        "ship_in_time": ship_in_time,
        "ship_out_time": ship_out_time,
    }
    if any(
        value is not None and not isinstance(value, datetime)
        for value in values.values()
    ):
        raise PlannedLogisticsBackfillInputError()
    return hashlib.sha256(
        json.dumps(
            {
                key: None if value is None else value.isoformat(timespec="microseconds")
                for key, value in values.items()
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).digest()


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedLogisticsChildSourceFact:
    rental_id: int
    expected_device_id: int
    expected_start_date: date
    expected_end_date: date
    expected_status: str

    def __post_init__(self) -> None:
        for value in (self.rental_id, self.expected_device_id):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PlannedLogisticsBackfillInputError()
        if (
            not isinstance(self.expected_start_date, date)
            or not isinstance(self.expected_end_date, date)
            or self.expected_start_date > self.expected_end_date
            or self.expected_status not in _RENTAL_STATUSES
        ):
            raise PlannedLogisticsBackfillInputError()


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedLogisticsBackfillEntry:
    rental_id: int
    expected_device_id: int
    expected_start_date: date
    expected_end_date: date
    expected_status: str
    logistics_days: int
    expected_child_rental_ids: tuple[int, ...] = ()
    child_fact_authority: str = "strict_match"
    expected_child_source_facts: tuple[PlannedLogisticsChildSourceFact, ...] = ()
    expected_legacy_logistics_digest: bytes | None = None

    def __post_init__(self) -> None:
        for value in (self.rental_id, self.expected_device_id):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise PlannedLogisticsBackfillInputError()
        if (
            not isinstance(self.expected_start_date, date)
            or not isinstance(self.expected_end_date, date)
            or self.expected_start_date > self.expected_end_date
            or self.expected_status not in ACTIVE_RENTAL_STATUSES
            or isinstance(self.logistics_days, bool)
            or not isinstance(self.logistics_days, int)
            or not 0 <= self.logistics_days <= 7
            or not isinstance(self.expected_child_rental_ids, tuple)
            or any(
                isinstance(item, bool) or not isinstance(item, int) or item < 1
                for item in self.expected_child_rental_ids
            )
            or self.expected_child_rental_ids
            != tuple(sorted(set(self.expected_child_rental_ids)))
            or self.rental_id in self.expected_child_rental_ids
            or self.child_fact_authority not in {"strict_match", "main_rental"}
            or not isinstance(self.expected_child_source_facts, tuple)
            or not all(
                isinstance(item, PlannedLogisticsChildSourceFact)
                for item in self.expected_child_source_facts
            )
            or (
                self.expected_legacy_logistics_digest is not None
                and (
                    not isinstance(self.expected_legacy_logistics_digest, bytes)
                    or len(self.expected_legacy_logistics_digest) != 32
                )
            )
        ):
            raise PlannedLogisticsBackfillInputError()
        source_ids = tuple(item.rental_id for item in self.expected_child_source_facts)
        if (
            source_ids != tuple(sorted(set(source_ids)))
            or (self.child_fact_authority == "strict_match" and source_ids)
            or (
                self.child_fact_authority == "main_rental"
                and source_ids != self.expected_child_rental_ids
            )
        ):
            raise PlannedLogisticsBackfillInputError()


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedLogisticsBackfillPlan:
    parent_manifest_digest: bytes
    migration_idempotency_key: str
    entries: tuple[PlannedLogisticsBackfillEntry, ...]
    policy_revision: int = PLANNED_LOGISTICS_BACKFILL_POLICY_REVISION

    def __post_init__(self) -> None:
        if (
            not isinstance(self.parent_manifest_digest, bytes)
            or len(self.parent_manifest_digest) != 32
            or not isinstance(self.migration_idempotency_key, str)
            or _SAFE_KEY.fullmatch(self.migration_idempotency_key) is None
            or self.policy_revision != PLANNED_LOGISTICS_BACKFILL_POLICY_REVISION
            or not isinstance(self.entries, tuple)
            or not self.entries
            or not all(
                isinstance(item, PlannedLogisticsBackfillEntry) for item in self.entries
            )
        ):
            raise PlannedLogisticsBackfillInputError()
        rental_ids = tuple(item.rental_id for item in self.entries)
        if rental_ids != tuple(sorted(set(rental_ids))):
            raise PlannedLogisticsBackfillInputError()
        child_ids = tuple(
            child for entry in self.entries for child in entry.expected_child_rental_ids
        )
        if len(child_ids) != len(set(child_ids)) or set(rental_ids) & set(child_ids):
            raise PlannedLogisticsBackfillInputError()

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(self.canonical_bytes()).digest()

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            {
                "entries": [
                    {
                        "expected_child_rental_ids": list(
                            item.expected_child_rental_ids
                        ),
                        "child_fact_authority": item.child_fact_authority,
                        "expected_child_source_facts": [
                            {
                                "expected_device_id": child.expected_device_id,
                                "expected_end_date": (
                                    child.expected_end_date.isoformat()
                                ),
                                "expected_start_date": (
                                    child.expected_start_date.isoformat()
                                ),
                                "expected_status": child.expected_status,
                                "rental_id": child.rental_id,
                            }
                            for child in item.expected_child_source_facts
                        ],
                        "expected_device_id": item.expected_device_id,
                        "expected_legacy_logistics_digest": (
                            None
                            if item.expected_legacy_logistics_digest is None
                            else item.expected_legacy_logistics_digest.hex()
                        ),
                        "expected_end_date": item.expected_end_date.isoformat(),
                        "expected_start_date": (item.expected_start_date.isoformat()),
                        "expected_status": item.expected_status,
                        "logistics_days": item.logistics_days,
                        "rental_id": item.rental_id,
                    }
                    for item in self.entries
                ],
                "migration_idempotency_key": self.migration_idempotency_key,
                "parent_manifest_digest": self.parent_manifest_digest.hex(),
                "policy_revision": self.policy_revision,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")


@dataclass(frozen=True, slots=True, kw_only=True)
class PlannedLogisticsBackfillResult:
    plan_digest: bytes
    result_digest: bytes
    main_rental_count: int
    child_rental_count: int
    updated_row_count: int
    idempotent_replay: bool


class PlannedLogisticsBackfillService:
    """Apply one explicit reliable plan inside an already routed transaction."""

    _schedule_policy = ScheduleOverlapPolicy()

    def backfill(
        self,
        session: Session,
        *,
        manifest: DefaultTenantMigrationManifest,
        expected_schema_generation: int,
        plan: PlannedLogisticsBackfillPlan,
    ) -> PlannedLogisticsBackfillResult:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or not isinstance(plan, PlannedLogisticsBackfillPlan)
            or plan.parent_manifest_digest != manifest.digest
            or plan.migration_idempotency_key != manifest.migration_idempotency_key
        ):
            raise PlannedLogisticsBackfillInputError()
        generation = _positive(expected_schema_generation)
        require_caller_transaction(
            session,
            PlannedLogisticsBackfillTransactionError,
        )
        try:
            identities = tuple(
                session.scalars(
                    sa.select(TenantDatabaseIdentity)
                    .order_by(TenantDatabaseIdentity.singleton_key)
                    .with_for_update()
                    .execution_options(autoflush=False, populate_existing=True)
                )
            )
            if len(identities) != 1:
                raise PlannedLogisticsBackfillIdentityMismatchError()
            identity = identities[0]
            if (
                identity.singleton_key != 1
                or identity.tenant_id != str(manifest.tenant_uuid)
                or identity.database_uuid != str(manifest.database_uuid)
                or identity.schema_generation != generation
            ):
                raise PlannedLogisticsBackfillIdentityMismatchError()

            expected_ids = tuple(
                sorted(
                    {entry.rental_id for entry in plan.entries}
                    | {
                        child
                        for entry in plan.entries
                        for child in entry.expected_child_rental_ids
                    }
                )
            )
            rentals = tuple(
                session.scalars(
                    sa.select(Rental)
                    .where(Rental.id.in_(expected_ids))
                    .order_by(Rental.id)
                    .with_for_update()
                    .execution_options(autoflush=False, populate_existing=True)
                )
            )
            by_id = {item.id: item for item in rentals}
            if tuple(sorted(by_id)) != expected_ids:
                raise PlannedLogisticsBackfillConflictError()

            actual_children = tuple(
                session.scalars(
                    sa.select(Rental)
                    .where(
                        Rental.parent_rental_id.in_(
                            tuple(item.rental_id for item in plan.entries)
                        )
                    )
                    .order_by(Rental.parent_rental_id, Rental.id)
                    .with_for_update()
                    .execution_options(autoflush=False, populate_existing=True)
                )
            )
            children_by_parent: dict[int, tuple[int, ...]] = {}
            for entry in plan.entries:
                children_by_parent[entry.rental_id] = tuple(
                    item.id
                    for item in actual_children
                    if item.parent_rental_id == entry.rental_id
                )

            updated = 0
            result_rows: list[dict[str, object]] = []
            for entry in plan.entries:
                main = by_id[entry.rental_id]
                if (
                    main.parent_rental_id is not None
                    or main.device_id != entry.expected_device_id
                    or main.start_date != entry.expected_start_date
                    or main.end_date != entry.expected_end_date
                    or main.status != entry.expected_status
                    or children_by_parent[entry.rental_id]
                    != entry.expected_child_rental_ids
                    or (
                        entry.expected_legacy_logistics_digest is not None
                        and legacy_logistics_source_digest(
                            ship_out_time=main.ship_out_time,
                            ship_in_time=main.ship_in_time,
                            scheduled_ship_time=main.scheduled_ship_time,
                        )
                        != entry.expected_legacy_logistics_digest
                    )
                ):
                    raise PlannedLogisticsBackfillConflictError()
                try:
                    window = self._schedule_policy.calculate_planned_window(
                        start_date=entry.expected_start_date,
                        end_date=entry.expected_end_date,
                        logistics_days=entry.logistics_days,
                        tenant_timezone="Asia/Shanghai",
                    )
                except ScheduleValidationError:
                    raise PlannedLogisticsBackfillInputError() from None
                group = (main,) + tuple(
                    by_id[item] for item in entry.expected_child_rental_ids
                )
                child_source_by_id = {
                    item.rental_id: item for item in entry.expected_child_source_facts
                }
                for rental in group:
                    if rental is not main:
                        if rental.parent_rental_id != main.id:
                            raise PlannedLogisticsBackfillConflictError()
                        if entry.child_fact_authority == "strict_match":
                            if (
                                rental.start_date != main.start_date
                                or rental.end_date != main.end_date
                                or rental.status != main.status
                            ):
                                raise PlannedLogisticsBackfillConflictError()
                        else:
                            expected_source = child_source_by_id[rental.id]
                            if (
                                rental.device_id != expected_source.expected_device_id
                                or rental.start_date
                                != expected_source.expected_start_date
                                or rental.end_date != expected_source.expected_end_date
                                or rental.status != expected_source.expected_status
                            ):
                                raise PlannedLogisticsBackfillConflictError()
                    expected = (
                        entry.logistics_days,
                        window.planned_ship_out_date,
                        window.planned_return_date,
                    )
                    existing = (
                        rental.logistics_days,
                        rental.planned_ship_out_date,
                        rental.planned_return_date,
                    )
                    if existing == (None, None, None):
                        rental.logistics_days = expected[0]
                        rental.planned_ship_out_date = expected[1]
                        rental.planned_return_date = expected[2]
                        updated += 1
                    elif existing != expected:
                        raise PlannedLogisticsBackfillConflictError()
                    result_rows.append(
                        {
                            "logistics_days": expected[0],
                            "planned_return_date": expected[2].isoformat(),
                            "planned_ship_out_date": expected[1].isoformat(),
                            "rental_id": rental.id,
                        }
                    )
            session.flush()
        except PlannedLogisticsBackfillError:
            raise
        except SQLAlchemyError:
            raise PlannedLogisticsBackfillPersistenceError() from None

        result_digest = hashlib.sha256(
            json.dumps(
                result_rows,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).digest()
        return PlannedLogisticsBackfillResult(
            plan_digest=plan.digest,
            result_digest=result_digest,
            main_rental_count=len(plan.entries),
            child_rental_count=sum(
                len(item.expected_child_rental_ids) for item in plan.entries
            ),
            updated_row_count=updated,
            idempotent_replay=updated == 0,
        )


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PlannedLogisticsBackfillInputError()
    return value


__all__ = [
    "PlannedLogisticsChildSourceFact",
    "PLANNED_LOGISTICS_BACKFILL_POLICY_REVISION",
    "PlannedLogisticsBackfillConflictError",
    "PlannedLogisticsBackfillEntry",
    "PlannedLogisticsBackfillError",
    "PlannedLogisticsBackfillIdentityMismatchError",
    "PlannedLogisticsBackfillInputError",
    "PlannedLogisticsBackfillPersistenceError",
    "PlannedLogisticsBackfillPlan",
    "PlannedLogisticsBackfillResult",
    "PlannedLogisticsBackfillService",
    "PlannedLogisticsBackfillTransactionError",
    "legacy_logistics_source_digest",
]
