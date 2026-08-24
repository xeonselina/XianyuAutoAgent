"""Caller-transactional lifecycle operations for platform root-key metadata.

Only non-secret version numbers, SHA-256 fingerprints, and lifecycle states
are persisted here.  Mounted key material remains an external, root-owned
concern.  Reference writers are expected to lock the selected registry row;
retirement takes the same registry lock and locking-reads every authoritative
online reference before making a legacy version unavailable to the runtime.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.database import read_database_utc_value
from inventory_control.models.base import ControlBase
from inventory_control.models.root_keys import PlatformRootKeyVersion
from inventory_control.transactions import require_caller_transaction

from .keyring import RootKeyLifecycle


_REFERENCE_COLUMN_NAMES = frozenset(
    {
        "root_key_version",
        "dml_root_key_version",
        "platform_read_root_key_version",
        "fingerprint_root_key_version",
        "checkpoint_root_key_version",
    }
)


class RootKeyLifecycleError(RuntimeError):
    """Stable, non-sensitive root-key lifecycle rejection."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RootKeyLifecycleTransactionError(RootKeyLifecycleError):
    pass


class RootKeyLifecycleConflictError(RootKeyLifecycleError):
    pass


class RootKeyReferenceError(RootKeyLifecycleError):
    def __init__(self, inventory: "RootKeyReferenceInventory") -> None:
        self.inventory = inventory
        super().__init__("ROOT_KEY_VERSION_STILL_REFERENCED")


@dataclass(frozen=True, slots=True)
class RootKeyReferenceCount:
    table_name: str
    column_name: str
    count: int

    def __post_init__(self) -> None:
        if not self.table_name or not self.column_name:
            raise ValueError("reference identity must be present")
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise TypeError("reference count must be an integer")
        if self.count < 1:
            raise ValueError("reference count must be positive")


@dataclass(frozen=True, slots=True)
class RootKeyReferenceInventory:
    version: int
    references: tuple[RootKeyReferenceCount, ...]

    def __post_init__(self) -> None:
        _positive_version(self.version)
        if not isinstance(self.references, tuple) or any(
            not isinstance(item, RootKeyReferenceCount) for item in self.references
        ):
            raise TypeError("references must be an immutable inventory")
        identities = {(item.table_name, item.column_name) for item in self.references}
        if len(identities) != len(self.references):
            raise ValueError("reference inventory contains duplicate identities")

    @property
    def total_references(self) -> int:
        return sum(item.count for item in self.references)

    @property
    def clear(self) -> bool:
        return not self.references


@dataclass(frozen=True, slots=True)
class RootKeyLifecycleResult:
    version: int
    status: RootKeyLifecycle
    previous_active_version: int | None
    activated_at: datetime
    retired_at: datetime | None
    replayed: bool


DatabaseClock = Callable[[Session], datetime]


class SqlAlchemyRootKeyLifecycleService:
    """Mutate the non-secret registry inside one clean caller transaction."""

    def __init__(
        self,
        *,
        session: Session,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._session = session
        self._database_clock = database_clock or _read_database_utc_now

    def bootstrap(
        self,
        *,
        version: int,
        fingerprint_sha256: bytes,
    ) -> RootKeyLifecycleResult:
        """Create the first active registry row, or return its exact replay."""

        _require_clean_explicit_transaction(self._session)
        selected_version = _positive_version(version)
        fingerprint = _fingerprint(fingerprint_sha256)
        rows = self._lock_registry()
        if rows:
            if (
                len(rows) == 1
                and rows[0].version == selected_version
                and rows[0].status == RootKeyLifecycle.ACTIVE.value
                and _same_fingerprint(rows[0].fingerprint_sha256, fingerprint)
            ):
                return _result(rows[0], previous_active=None, replayed=True)
            raise RootKeyLifecycleConflictError(
                "ROOT_KEY_REGISTRY_ALREADY_BOOTSTRAPPED"
            )

        row = PlatformRootKeyVersion(
            version=selected_version,
            fingerprint_sha256=fingerprint,
            status=RootKeyLifecycle.ACTIVE.value,
            activated_at=self._now(),
            retired_at=None,
        )
        self._session.add(row)
        self._session.flush()
        return _result(row, previous_active=None, replayed=False)

    def activate_new(
        self,
        *,
        expected_active_version: int,
        new_version: int,
        fingerprint_sha256: bytes,
    ) -> RootKeyLifecycleResult:
        """Atomically demote the current active version and register its successor."""

        _require_clean_explicit_transaction(self._session)
        expected = _positive_version(expected_active_version)
        selected_version = _positive_version(new_version)
        fingerprint = _fingerprint(fingerprint_sha256)
        if selected_version <= expected:
            raise RootKeyLifecycleConflictError("ROOT_KEY_VERSION_NOT_MONOTONIC")

        rows = self._lock_registry()
        active = _single_active(rows)
        existing = next(
            (row for row in rows if row.version == selected_version),
            None,
        )
        if existing is not None:
            prior = next(
                (row for row in rows if row.version == expected),
                None,
            )
            if (
                existing is active
                and existing.status == RootKeyLifecycle.ACTIVE.value
                and _same_fingerprint(existing.fingerprint_sha256, fingerprint)
                and prior is not None
                and prior.status == RootKeyLifecycle.LEGACY.value
            ):
                return _result(
                    existing,
                    previous_active=expected,
                    replayed=True,
                )
            raise RootKeyLifecycleConflictError("ROOT_KEY_VERSION_ALREADY_EXISTS")
        if active.version != expected:
            raise RootKeyLifecycleConflictError("ROOT_KEY_ACTIVE_VERSION_CHANGED")
        if selected_version <= max(row.version for row in rows):
            raise RootKeyLifecycleConflictError("ROOT_KEY_VERSION_NOT_MONOTONIC")
        if any(_same_fingerprint(row.fingerprint_sha256, fingerprint) for row in rows):
            raise RootKeyLifecycleConflictError("ROOT_KEY_FINGERPRINT_ALREADY_EXISTS")

        active.status = RootKeyLifecycle.LEGACY.value
        self._session.flush()
        successor = PlatformRootKeyVersion(
            version=selected_version,
            fingerprint_sha256=fingerprint,
            status=RootKeyLifecycle.ACTIVE.value,
            activated_at=self._now(),
            retired_at=None,
        )
        self._session.add(successor)
        self._session.flush()
        return _result(
            successor,
            previous_active=expected,
            replayed=False,
        )

    def inspect_references(self, *, version: int) -> RootKeyReferenceInventory:
        """Return a locking inventory of authoritative online references."""

        _require_clean_explicit_transaction(self._session)
        selected_version = _positive_version(version)
        rows = self._lock_registry()
        if not any(row.version == selected_version for row in rows):
            raise RootKeyLifecycleConflictError("ROOT_KEY_VERSION_NOT_FOUND")
        return self._scan_references(selected_version)

    def retire(
        self,
        *,
        version: int,
        expected_active_version: int,
    ) -> RootKeyLifecycleResult:
        """Retire one unreferenced legacy version without deleting its metadata."""

        _require_clean_explicit_transaction(self._session)
        selected_version = _positive_version(version)
        expected_active = _positive_version(expected_active_version)
        rows = self._lock_registry()
        active = _single_active(rows)
        if active.version != expected_active:
            raise RootKeyLifecycleConflictError("ROOT_KEY_ACTIVE_VERSION_CHANGED")
        target = next(
            (row for row in rows if row.version == selected_version),
            None,
        )
        if target is None:
            raise RootKeyLifecycleConflictError("ROOT_KEY_VERSION_NOT_FOUND")
        if target.status == RootKeyLifecycle.RETIRED.value:
            return _result(
                target,
                previous_active=active.version,
                replayed=True,
            )
        if target.status != RootKeyLifecycle.LEGACY.value:
            raise RootKeyLifecycleConflictError("ROOT_KEY_VERSION_NOT_LEGACY")

        inventory = self._scan_references(selected_version)
        if not inventory.clear:
            raise RootKeyReferenceError(inventory)
        target.status = RootKeyLifecycle.RETIRED.value
        target.retired_at = self._now()
        self._session.flush()
        return _result(
            target,
            previous_active=active.version,
            replayed=False,
        )

    def _lock_registry(self) -> tuple[PlatformRootKeyVersion, ...]:
        return tuple(
            self._session.scalars(
                sa.select(PlatformRootKeyVersion)
                .order_by(PlatformRootKeyVersion.version)
                .execution_options(autoflush=False, populate_existing=True)
                .with_for_update()
            )
        )

    def _scan_references(self, version: int) -> RootKeyReferenceInventory:
        references: list[RootKeyReferenceCount] = []
        for table in sorted(
            ControlBase.metadata.tables.values(), key=lambda item: item.name
        ):
            if table is PlatformRootKeyVersion.__table__:
                continue
            primary_key = tuple(table.primary_key.columns)
            if not primary_key:
                raise RootKeyLifecycleConflictError("ROOT_KEY_REFERENCE_SCHEMA_INVALID")
            for column in sorted(table.columns, key=lambda item: item.name):
                if column.name not in _REFERENCE_COLUMN_NAMES:
                    continue
                statement = (
                    sa.select(*primary_key)
                    .where(column == version)
                    .execution_options(autoflush=False)
                    .with_for_update()
                )
                count = sum(1 for _row in self._session.execute(statement))
                if count:
                    references.append(
                        RootKeyReferenceCount(
                            table_name=table.name,
                            column_name=column.name,
                            count=count,
                        )
                    )
        return RootKeyReferenceInventory(
            version=version,
            references=tuple(references),
        )

    def _now(self) -> datetime:
        return _aware_utc(self._database_clock(self._session))


def _single_active(
    rows: tuple[PlatformRootKeyVersion, ...],
) -> PlatformRootKeyVersion:
    active = tuple(row for row in rows if row.status == RootKeyLifecycle.ACTIVE.value)
    if len(active) != 1:
        raise RootKeyLifecycleConflictError("ROOT_KEY_ACTIVE_VERSION_INVALID")
    return active[0]


def _result(
    row: PlatformRootKeyVersion,
    *,
    previous_active: int | None,
    replayed: bool,
) -> RootKeyLifecycleResult:
    return RootKeyLifecycleResult(
        version=row.version,
        status=RootKeyLifecycle(row.status),
        previous_active_version=previous_active,
        activated_at=_aware_utc(row.activated_at),
        retired_at=(_aware_utc(row.retired_at) if row.retired_at is not None else None),
        replayed=replayed,
    )


def _require_clean_explicit_transaction(session: Session) -> None:
    require_caller_transaction(
        session,
        lambda: RootKeyLifecycleTransactionError(
            "ROOT_KEY_EXPLICIT_TRANSACTION_REQUIRED"
        ),
        clean=True,
        dirty_error=lambda: RootKeyLifecycleTransactionError(
            "ROOT_KEY_CLEAN_TRANSACTION_REQUIRED"
        ),
    )


def _positive_version(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("root key version must be a positive integer")
    return value


def _fingerprint(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError("root key fingerprint must be 32 bytes")
    return value


def _same_fingerprint(left: bytes, right: bytes) -> bool:
    import hmac

    return hmac.compare_digest(bytes(left), right)


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("database clock must return a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _read_database_utc_now(session: Session) -> datetime:
    value = read_database_utc_value(session)
    if not isinstance(value, datetime):
        raise RootKeyLifecycleConflictError("ROOT_KEY_DATABASE_CLOCK_INVALID")
    return _aware_utc(value)


__all__ = [
    "RootKeyLifecycleConflictError",
    "RootKeyLifecycleError",
    "RootKeyLifecycleResult",
    "RootKeyLifecycleTransactionError",
    "RootKeyReferenceCount",
    "RootKeyReferenceError",
    "RootKeyReferenceInventory",
    "SqlAlchemyRootKeyLifecycleService",
]
