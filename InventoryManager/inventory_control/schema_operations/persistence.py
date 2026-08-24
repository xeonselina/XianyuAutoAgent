"""Caller-owned control-DB persistence for the schema-operation lease.

The service touches only the singleton lease row.  It never connects to a
tenant schema, runs DDL, acquires a MySQL advisory lock, or performs an
external side effect.  Such executors must carry the returned generation and
fencing token and revalidate them around every physical operation.

Integration is deliberately a later step: provisioning, fleet migration,
backup, restore, deletion, and account-mutation orchestrators will acquire
this lease in a short committed control transaction before taking their
per-database advisory locks.  The existing 0017 backup-specific lease remains
untouched until those consumers can switch together without opening a mixed
locking window.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from inventory_control.models.schema_operations import (
    PlatformSchemaOperationLease,
)

from .domain import (
    SchemaOperationLease,
    SchemaOperationLeaseEffect,
    SchemaOperationLeaseError,
    SchemaOperationLeaseState,
    SchemaOperationLeaseTransition,
    SchemaOperationPurpose,
    claim_schema_operation_lease,
    release_schema_operation_lease,
    require_live_schema_operation_fence as _require_live_schema_operation_fence,
    renew_schema_operation_lease,
)


SCHEMA_OPERATION_LEASE_KEY = "fleet_schema_operation"


class SchemaOperationPersistenceError(SchemaOperationLeaseError):
    code = "SCHEMA_OPERATION_PERSISTENCE_FAILED"
    public_message = "the schema operation lease could not be persisted"


class SchemaOperationTransactionError(SchemaOperationPersistenceError):
    code = "SCHEMA_OPERATION_TRANSACTION_INVALID"
    public_message = "an explicit clean caller-owned transaction is required"


class SchemaOperationStoredStateError(SchemaOperationPersistenceError):
    code = "SCHEMA_OPERATION_STORED_STATE_INVALID"
    public_message = "the schema operation lease state is invalid"


DatabaseClock = Callable[[Session], datetime]


class SchemaOperationLeasePersistenceService:
    """Persist pure lease transitions inside a caller-owned transaction."""

    __slots__ = ("_database_clock", "_session")

    def __init__(
        self,
        session: Session,
        *,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not isinstance(session, Session):
            raise SchemaOperationTransactionError()
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._session = session
        self._database_clock = database_clock or _read_database_utc_now

    def claim(
        self,
        *,
        claim_id: UUID,
        owner_id: str,
        purpose: SchemaOperationPurpose,
        expected_row_version: int,
        lease_expires_at: datetime,
    ) -> SchemaOperationLeaseTransition:
        """Claim or take over the expired global mutex."""

        self._prepare()
        row = self._lock_row()
        # The database clock is intentionally sampled only after FOR UPDATE.
        # A timestamp read before a lock wait could authorize an expired owner.
        now = self._now()
        return self._apply(
            row,
            claim_schema_operation_lease(
                _domain_lease(row),
                claim_id=claim_id,
                owner_id=owner_id,
                purpose=purpose,
                expected_row_version=expected_row_version,
                lease_expires_at=lease_expires_at,
                database_now=now,
            ),
        )

    def renew(
        self,
        *,
        claim_id: UUID,
        owner_id: str,
        purpose: SchemaOperationPurpose,
        fencing_token: int,
        expected_row_version: int,
        lease_expires_at: datetime,
    ) -> SchemaOperationLeaseTransition:
        """Renew only the exact current generation and fencing identity."""

        self._prepare()
        row = self._lock_row()
        now = self._now()
        return self._apply(
            row,
            renew_schema_operation_lease(
                _domain_lease(row),
                claim_id=claim_id,
                owner_id=owner_id,
                purpose=purpose,
                fencing_token=fencing_token,
                expected_row_version=expected_row_version,
                lease_expires_at=lease_expires_at,
                database_now=now,
            ),
        )

    def release(
        self,
        *,
        claim_id: UUID,
        owner_id: str,
        purpose: SchemaOperationPurpose,
        fencing_token: int,
        expected_row_version: int,
    ) -> SchemaOperationLeaseTransition:
        """Release without allowing a stale request to clear a new owner."""

        self._prepare()
        row = self._lock_row()
        now = self._now()
        return self._apply(
            row,
            release_schema_operation_lease(
                _domain_lease(row),
                claim_id=claim_id,
                owner_id=owner_id,
                purpose=purpose,
                fencing_token=fencing_token,
                expected_row_version=expected_row_version,
                database_now=now,
            ),
        )

    def require_live_schema_operation_fence(
        self,
        *,
        claim_id: UUID,
        owner_id: str,
        purpose: SchemaOperationPurpose,
        generation: int,
        fencing_token: int,
        expected_row_version: int,
    ) -> SchemaOperationLease:
        """Lock and validate the exact live holder as a final fence."""

        self._prepare()
        row = self._lock_row()
        # The final current-read fence must use a clock sampled after the row
        # lock, otherwise a lock wait can make a previously live lease stale.
        now = self._now()
        return _require_live_schema_operation_fence(
            _domain_lease(row),
            claim_id=claim_id,
            owner_id=owner_id,
            purpose=purpose,
            generation=generation,
            fencing_token=fencing_token,
            expected_row_version=expected_row_version,
            database_now=now,
        )

    claim_lease = claim
    renew_lease = renew
    release_lease = release
    require_live_fence = require_live_schema_operation_fence

    def _prepare(self) -> None:
        transaction = self._session.get_transaction()
        if (
            transaction is None
            or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        ):
            raise SchemaOperationTransactionError()
        dirty = any(
            self._session.is_modified(instance, include_collections=True)
            for instance in self._session.dirty
        )
        if self._session.new or self._session.deleted or dirty:
            raise SchemaOperationTransactionError()
        _materialize_sqlite_outer_transaction(self._session)

    def _lock_row(self) -> PlatformSchemaOperationLease:
        try:
            row = self._session.scalar(
                sa.select(PlatformSchemaOperationLease)
                .where(
                    PlatformSchemaOperationLease.lease_key
                    == SCHEMA_OPERATION_LEASE_KEY
                )
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
        except SQLAlchemyError:
            raise SchemaOperationPersistenceError() from None
        if row is None:
            raise SchemaOperationStoredStateError()
        return row

    def _now(self) -> datetime:
        try:
            return _as_utc(self._database_clock(self._session))
        except SchemaOperationPersistenceError:
            raise
        except Exception:
            raise SchemaOperationStoredStateError() from None

    def _apply(
        self,
        row: PlatformSchemaOperationLease,
        transition: SchemaOperationLeaseTransition,
    ) -> SchemaOperationLeaseTransition:
        if transition.idempotent_replay:
            return transition
        before = _domain_lease(row)
        after = transition.lease
        _verify_transition(before, after, transition.effect)
        try:
            changed = self._session.execute(
                sa.update(PlatformSchemaOperationLease)
                .where(
                    PlatformSchemaOperationLease.lease_key
                    == SCHEMA_OPERATION_LEASE_KEY,
                    PlatformSchemaOperationLease.row_version
                    == before.row_version,
                    PlatformSchemaOperationLease.generation
                    == before.generation,
                    PlatformSchemaOperationLease.fencing_token
                    == before.fencing_token,
                )
                .values(
                    state=after.state.value,
                    generation=after.generation,
                    fencing_token=after.fencing_token,
                    row_version=after.row_version,
                    observed_at=after.observed_at,
                    owner_id=after.owner_id,
                    claim_id=_optional_uuid_text(after.claim_id),
                    purpose=(
                        None if after.purpose is None else after.purpose.value
                    ),
                    acquired_at=after.acquired_at,
                    expires_at=after.expires_at,
                    last_claim_id=_optional_uuid_text(after.last_claim_id),
                    last_effect=(
                        None
                        if after.last_effect is None
                        else after.last_effect.value
                    ),
                    last_request_digest=after.last_request_digest,
                )
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise SchemaOperationPersistenceError()
            self._session.flush()
        except SchemaOperationPersistenceError:
            raise
        except SQLAlchemyError:
            raise SchemaOperationPersistenceError() from None
        self._session.expire(row)
        return transition


def _domain_lease(row: PlatformSchemaOperationLease) -> SchemaOperationLease:
    try:
        return SchemaOperationLease(
            state=SchemaOperationLeaseState(row.state),
            generation=row.generation,
            fencing_token=row.fencing_token,
            row_version=row.row_version,
            observed_at=_as_utc(row.observed_at),
            owner_id=row.owner_id,
            claim_id=_optional_uuid(row.claim_id),
            purpose=(
                None
                if row.purpose is None
                else SchemaOperationPurpose(row.purpose)
            ),
            acquired_at=_optional_utc(row.acquired_at),
            expires_at=_optional_utc(row.expires_at),
            last_claim_id=_optional_uuid(row.last_claim_id),
            last_effect=(
                None
                if row.last_effect is None
                else SchemaOperationLeaseEffect(row.last_effect)
            ),
            last_request_digest=(
                None
                if row.last_request_digest is None
                else bytes(row.last_request_digest)
            ),
        )
    except SchemaOperationStoredStateError:
        raise
    except (SchemaOperationLeaseError, TypeError, ValueError):
        raise SchemaOperationStoredStateError() from None


def _verify_transition(
    before: SchemaOperationLease,
    after: SchemaOperationLease,
    effect: SchemaOperationLeaseEffect,
) -> None:
    if (
        after.row_version != before.row_version + 1
        or after.generation < before.generation
        or after.fencing_token < before.fencing_token
        or after.observed_at < before.observed_at
    ):
        raise SchemaOperationPersistenceError()
    if effect is SchemaOperationLeaseEffect.CLAIMED:
        if (
            after.generation != before.generation + 1
            or after.fencing_token != before.fencing_token + 1
        ):
            raise SchemaOperationPersistenceError()
    elif (
        after.generation != before.generation
        or after.fencing_token != before.fencing_token
    ):
        raise SchemaOperationPersistenceError()


def _read_database_utc_now(session: Session) -> datetime:
    if session.get_bind().dialect.name in {"mysql", "mariadb"}:
        return _as_utc(session.scalar(sa.text("SELECT UTC_TIMESTAMP(6)")))
    return _as_utc(session.scalar(sa.select(sa.func.current_timestamp())))


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise SchemaOperationStoredStateError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _optional_utc(value: object | None) -> datetime | None:
    return None if value is None else _as_utc(value)


def _optional_uuid(value: object | None) -> UUID | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("invalid technical identity")
    selected = UUID(value)
    if str(selected) != value:
        raise ValueError("invalid technical identity")
    return selected


def _optional_uuid_text(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def _materialize_sqlite_outer_transaction(session: Session) -> None:
    connection = session.connection()
    if connection.dialect.name != "sqlite":
        return
    driver_connection = getattr(connection.connection, "driver_connection", None)
    if driver_connection is not None and not driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")


__all__ = [
    "SCHEMA_OPERATION_LEASE_KEY",
    "SchemaOperationLeasePersistenceService",
    "SchemaOperationPersistenceError",
    "SchemaOperationStoredStateError",
    "SchemaOperationTransactionError",
]
