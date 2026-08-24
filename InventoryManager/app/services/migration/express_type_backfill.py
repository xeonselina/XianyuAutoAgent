"""Fail-closed canonical express-type backfill for one tenant database.

The caller supplies an already routed tenant ``Session`` and owns its outer
transaction.  This module neither selects a database nor calls a carrier.  An
immutable manifest binds the locked database identity, current schema facts,
and both sides of the only permitted transformation: ``NULL`` to integer ``2``.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Callable, Final, Iterable, Mapping
from uuid import UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransaction, SessionTransactionOrigin

from app.models.database_identity import TenantDatabaseIdentity
from app.models.rental import Rental


EXPRESS_TYPE_BACKFILL_POLICY_REVISION: Final = 1
TENANT_IDENTITY_DIGEST_REVISION: Final = 1
_DIGEST_BYTES: Final = 32
_SAFE_ID: Final = re.compile(r"[a-z0-9][a-z0-9_.:/+-]{0,127}", re.ASCII)
_SCHEMA_REVISION: Final = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}", re.ASCII
)
_OPERATION_DOMAIN: Final = "inventory-manager/express-type-backfill/v1/"
_IDENTITY_DOMAIN: Final = b"inventory-manager/tenant-database-identity/v1\x00"
_SNAPSHOT_DOMAIN: Final = b"inventory-manager/express-type-snapshot/v1\x00"
_REPORT_DOMAIN: Final = b"inventory-manager/express-type-report/v1\x00"


class ExpressTypeBackfillError(RuntimeError):
    """Stable failure that never includes a rental value or customer fact."""

    code = "EXPRESS_TYPE_BACKFILL_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class ExpressTypeBackfillInputError(ExpressTypeBackfillError):
    code = "EXPRESS_TYPE_BACKFILL_INPUT_INVALID"


class ExpressTypeBackfillTransactionError(ExpressTypeBackfillError):
    code = "EXPRESS_TYPE_BACKFILL_TRANSACTION_INVALID"


class ExpressTypeBackfillIdentityMismatchError(ExpressTypeBackfillError):
    code = "EXPRESS_TYPE_BACKFILL_IDENTITY_MISMATCH"


class ExpressTypeBackfillSchemaMismatchError(ExpressTypeBackfillError):
    code = "EXPRESS_TYPE_BACKFILL_SCHEMA_MISMATCH"


class ExpressTypeBackfillConflictError(ExpressTypeBackfillError):
    code = "EXPRESS_TYPE_BACKFILL_SNAPSHOT_CONFLICT"


class ExpressTypeBackfillPersistenceError(ExpressTypeBackfillError):
    code = "EXPRESS_TYPE_BACKFILL_PERSISTENCE_FAILED"


class ExpressTypeState(str, Enum):
    CANONICAL_1 = "canonical_1"
    CANONICAL_2 = "canonical_2"
    CANONICAL_263 = "canonical_263"
    HISTORICAL_NULL = "historical_null"
    LEGACY_6 = "legacy_6"
    UNSUPPORTED = "unsupported"


_STATE_ORDER: Final = tuple(ExpressTypeState)


@dataclass(frozen=True, slots=True, repr=False)
class ExpressTypeSourceSnapshot:
    """Log-safe source/result commitments and source state counts."""

    total_count: int
    state_counts: tuple[tuple[str, int], ...]
    source_digest: bytes
    expected_result_digest: bytes

    def __post_init__(self) -> None:
        _nonnegative_integer(self.total_count)
        normalized = _validated_state_counts(self.state_counts)
        if sum(count for _, count in normalized) != self.total_count:
            raise ExpressTypeBackfillInputError()
        _digest(self.source_digest)
        _digest(self.expected_result_digest)

    def count(self, state: ExpressTypeState) -> int:
        return dict(self.state_counts)[state.value]

    @property
    def expected_state_counts(self) -> tuple[tuple[str, int], ...]:
        source = dict(self.state_counts)
        return tuple(
            (
                state.value,
                (
                    0
                    if state is ExpressTypeState.HISTORICAL_NULL
                    else source[state.value]
                    + (
                        source[ExpressTypeState.HISTORICAL_NULL.value]
                        if state is ExpressTypeState.CANONICAL_2
                        else 0
                    )
                ),
            )
            for state in _STATE_ORDER
        )

    def __repr__(self) -> str:
        return (
            "ExpressTypeSourceSnapshot("
            f"total_count={self.total_count}, state_counts={self.state_counts!r}, "
            "digests='<sha256>')"
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class ExpressTypeBackfillManifest:
    """Immutable authority and idempotency identity for one backfill slice."""

    migration_idempotency_key: str
    parent_manifest_digest: bytes
    tenant_uuid: UUID
    database_uuid: UUID
    schema_generation: int
    tenant_identity_digest: bytes
    schema_revision: str
    schema_digest: bytes
    source_snapshot: ExpressTypeSourceSnapshot
    policy_revision: int = EXPRESS_TYPE_BACKFILL_POLICY_REVISION
    identity_digest_revision: int = TENANT_IDENTITY_DIGEST_REVISION

    def __post_init__(self) -> None:
        _safe_id(self.migration_idempotency_key)
        _digest(self.parent_manifest_digest)
        _required_uuid(self.tenant_uuid)
        _required_uuid(self.database_uuid)
        if self.tenant_uuid == self.database_uuid:
            raise ExpressTypeBackfillInputError()
        _positive_integer(self.schema_generation)
        _digest(self.tenant_identity_digest)
        if (
            not isinstance(self.schema_revision, str)
            or _SCHEMA_REVISION.fullmatch(self.schema_revision) is None
        ):
            raise ExpressTypeBackfillInputError()
        _digest(self.schema_digest)
        if not isinstance(self.source_snapshot, ExpressTypeSourceSnapshot):
            raise ExpressTypeBackfillInputError()
        if (
            self.policy_revision != EXPRESS_TYPE_BACKFILL_POLICY_REVISION
            or self.identity_digest_revision
            != TENANT_IDENTITY_DIGEST_REVISION
        ):
            raise ExpressTypeBackfillInputError()

    @property
    def digest(self) -> bytes:
        payload = {
            "database_uuid": str(self.database_uuid),
            "identity_digest_revision": self.identity_digest_revision,
            "migration_idempotency_key": self.migration_idempotency_key,
            "parent_manifest_digest": self.parent_manifest_digest.hex(),
            "policy_revision": self.policy_revision,
            "schema_digest": self.schema_digest.hex(),
            "schema_generation": self.schema_generation,
            "schema_revision": self.schema_revision,
            "source_expected_result_digest": (
                self.source_snapshot.expected_result_digest.hex()
            ),
            "source_snapshot_digest": self.source_snapshot.source_digest.hex(),
            "source_state_counts": list(self.source_snapshot.state_counts),
            "source_total_count": self.source_snapshot.total_count,
            "tenant_identity_digest": self.tenant_identity_digest.hex(),
            "tenant_uuid": str(self.tenant_uuid),
        }
        return hashlib.sha256(_canonical_json(payload)).digest()

    @property
    def operation_uuid(self) -> UUID:
        return uuid5(
            self.database_uuid,
            f"{_OPERATION_DOMAIN}{self.digest.hex()}",
        )

    def __repr__(self) -> str:
        return (
            "ExpressTypeBackfillManifest("
            f"operation_uuid={self.operation_uuid!s}, "
            f"manifest_digest={self.digest.hex()!r}, inputs='<committed>')"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantSchemaAuthorityFacts:
    """Trusted current-read facts returned after the identity row is locked."""

    tenant_uuid: UUID
    database_uuid: UUID
    schema_generation: int
    schema_revision: str
    schema_digest: bytes

    def __post_init__(self) -> None:
        _required_uuid(self.tenant_uuid)
        _required_uuid(self.database_uuid)
        _positive_integer(self.schema_generation)
        if (
            not isinstance(self.schema_revision, str)
            or _SCHEMA_REVISION.fullmatch(self.schema_revision) is None
        ):
            raise ExpressTypeBackfillInputError()
        _digest(self.schema_digest)


TenantSchemaAuthorityCurrentRead = Callable[
    [Session, TenantDatabaseIdentity], TenantSchemaAuthorityFacts
]


@dataclass(frozen=True, slots=True)
class ExpressTypeBackfillResult:
    operation_uuid: UUID
    manifest_digest: bytes
    source_snapshot_digest: bytes
    result_snapshot_digest: bytes
    report_digest: bytes
    source_state_counts: tuple[tuple[str, int], ...]
    updated_count: int
    verification_passed: bool
    safe_status: str
    idempotent_replay: bool

    def __post_init__(self) -> None:
        _required_uuid(self.operation_uuid)
        for value in (
            self.manifest_digest,
            self.source_snapshot_digest,
            self.result_snapshot_digest,
            self.report_digest,
        ):
            _digest(value)
        counts = _validated_state_counts(self.source_state_counts)
        _nonnegative_integer(self.updated_count)
        if not isinstance(self.verification_passed, bool):
            raise ExpressTypeBackfillPersistenceError()
        if self.safe_status not in {
            "verified",
            "blocked_legacy_6",
            "blocked_unsupported",
            "blocked_legacy_and_unsupported",
        }:
            raise ExpressTypeBackfillPersistenceError()
        if not isinstance(self.idempotent_replay, bool):
            raise ExpressTypeBackfillPersistenceError()
        if self.updated_count > dict(counts)[ExpressTypeState.HISTORICAL_NULL.value]:
            raise ExpressTypeBackfillPersistenceError()

    def safe_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "operation_uuid": str(self.operation_uuid),
                "manifest_digest": self.manifest_digest.hex(),
                "report_digest": self.report_digest.hex(),
                "source_state_counts": MappingProxyType(
                    dict(self.source_state_counts)
                ),
                "updated_count": self.updated_count,
                "verification_passed": self.verification_passed,
                "safe_status": self.safe_status,
                "idempotent_replay": self.idempotent_replay,
            }
        )


def build_express_type_source_snapshot(
    rows: Iterable[tuple[int, object]],
) -> ExpressTypeSourceSnapshot:
    """Build safe commitments without returning rental IDs or raw values."""

    materialized = _materialize_rows(rows)
    state_counts = _count_states(materialized)
    expected = tuple(
        (row_id, 2 if value is None else value)
        for row_id, value in materialized
    )
    return ExpressTypeSourceSnapshot(
        total_count=len(materialized),
        state_counts=state_counts,
        source_digest=_snapshot_digest(materialized),
        expected_result_digest=_snapshot_digest(expected),
    )


def tenant_database_identity_digest(
    *,
    tenant_uuid: UUID,
    database_uuid: UUID,
    created_at: datetime,
    schema_generation: int,
) -> bytes:
    """Commit to every immutable field in the singleton identity row."""

    selected_tenant = _required_uuid(tenant_uuid)
    selected_database = _required_uuid(database_uuid)
    if selected_tenant == selected_database:
        raise ExpressTypeBackfillInputError()
    generation = _positive_integer(schema_generation)
    canonical_created_at = _canonical_datetime(created_at)
    payload = {
        "created_at": canonical_created_at,
        "database_uuid": str(selected_database),
        "digest_revision": TENANT_IDENTITY_DIGEST_REVISION,
        "schema_generation": generation,
        "singleton_key": 1,
        "tenant_uuid": str(selected_tenant),
    }
    return hashlib.sha256(_IDENTITY_DOMAIN + _canonical_json(payload)).digest()


class ExpressTypeBackfillService:
    """Lock, verify and apply only the documented ``NULL`` to ``2`` rule."""

    def __init__(
        self,
        schema_current_read: TenantSchemaAuthorityCurrentRead,
    ) -> None:
        if not callable(schema_current_read):
            raise ExpressTypeBackfillInputError()
        self._schema_current_read = schema_current_read

    def backfill(
        self,
        session: Session,
        *,
        manifest: ExpressTypeBackfillManifest,
    ) -> ExpressTypeBackfillResult:
        if not isinstance(manifest, ExpressTypeBackfillManifest):
            raise ExpressTypeBackfillInputError()
        outer_transaction = _prepare_session(session)
        identity = _verified_identity(_lock_identity(session), manifest)
        schema_facts = _read_schema_facts(
            self._schema_current_read,
            session,
            identity,
        )
        _verify_schema_facts(schema_facts, manifest)
        _require_same_transaction(session, outer_transaction)
        _require_clean_session(session)
        rentals = _lock_rentals(session)
        current_rows = tuple(
            (rental.id, rental.express_type_id) for rental in rentals
        )
        current = build_express_type_source_snapshot(current_rows)
        source = manifest.source_snapshot

        if _snapshot_matches_source(current, source):
            replay = source.source_digest == source.expected_result_digest
            updated_count = 0
            if not replay:
                try:
                    with session.begin_nested():
                        for rental in rentals:
                            if rental.express_type_id is None:
                                rental.express_type_id = 2
                                updated_count += 1
                        session.flush()
                        post_rows = tuple(
                            (rental.id, rental.express_type_id)
                            for rental in rentals
                        )
                        post = build_express_type_source_snapshot(post_rows)
                        if not _snapshot_matches_result(post, source):
                            raise ExpressTypeBackfillConflictError()
                except ExpressTypeBackfillError:
                    raise
                except SQLAlchemyError:
                    raise ExpressTypeBackfillPersistenceError() from None
        elif _snapshot_matches_result(current, source):
            replay = True
            updated_count = 0
        else:
            raise ExpressTypeBackfillConflictError()

        legacy_count = source.count(ExpressTypeState.LEGACY_6)
        unsupported_count = source.count(ExpressTypeState.UNSUPPORTED)
        verification_passed = legacy_count == 0 and unsupported_count == 0
        safe_status = _safe_status(legacy_count, unsupported_count)
        report_digest = _report_digest(
            manifest=manifest,
            verification_passed=verification_passed,
            safe_status=safe_status,
        )
        return ExpressTypeBackfillResult(
            operation_uuid=manifest.operation_uuid,
            manifest_digest=manifest.digest,
            source_snapshot_digest=source.source_digest,
            result_snapshot_digest=source.expected_result_digest,
            report_digest=report_digest,
            source_state_counts=source.state_counts,
            updated_count=updated_count,
            verification_passed=verification_passed,
            safe_status=safe_status,
            idempotent_replay=replay,
        )


def _lock_identity(session: Session) -> tuple[TenantDatabaseIdentity, ...]:
    try:
        return tuple(
            session.scalars(
                _identity_lock_statement()
                .execution_options(autoflush=False, populate_existing=True)
            )
        )
    except SQLAlchemyError:
        raise ExpressTypeBackfillPersistenceError() from None


def _verified_identity(
    identities: tuple[TenantDatabaseIdentity, ...],
    manifest: ExpressTypeBackfillManifest,
) -> TenantDatabaseIdentity:
    if len(identities) != 1:
        raise ExpressTypeBackfillIdentityMismatchError()
    identity = identities[0]
    try:
        stored_tenant = UUID(identity.tenant_id)
        stored_database = UUID(identity.database_uuid)
        stored_digest = tenant_database_identity_digest(
            tenant_uuid=stored_tenant,
            database_uuid=stored_database,
            created_at=identity.created_at,
            schema_generation=identity.schema_generation,
        )
    except (AttributeError, TypeError, ValueError, ExpressTypeBackfillError):
        raise ExpressTypeBackfillIdentityMismatchError() from None
    if (
        identity.singleton_key != 1
        or str(stored_tenant) != identity.tenant_id
        or str(stored_database) != identity.database_uuid
        or stored_tenant != manifest.tenant_uuid
        or stored_database != manifest.database_uuid
        or identity.schema_generation != manifest.schema_generation
        or not hmac.compare_digest(
            stored_digest,
            manifest.tenant_identity_digest,
        )
    ):
        raise ExpressTypeBackfillIdentityMismatchError()
    return identity


def _read_schema_facts(
    reader: TenantSchemaAuthorityCurrentRead,
    session: Session,
    identity: TenantDatabaseIdentity,
) -> TenantSchemaAuthorityFacts:
    try:
        facts = reader(session, identity)
    except ExpressTypeBackfillError:
        raise
    except Exception:
        raise ExpressTypeBackfillSchemaMismatchError() from None
    if not isinstance(facts, TenantSchemaAuthorityFacts):
        raise ExpressTypeBackfillSchemaMismatchError()
    return facts


def _verify_schema_facts(
    facts: TenantSchemaAuthorityFacts,
    manifest: ExpressTypeBackfillManifest,
) -> None:
    if (
        facts.tenant_uuid != manifest.tenant_uuid
        or facts.database_uuid != manifest.database_uuid
        or facts.schema_generation != manifest.schema_generation
        or facts.schema_revision != manifest.schema_revision
        or not hmac.compare_digest(facts.schema_digest, manifest.schema_digest)
    ):
        raise ExpressTypeBackfillSchemaMismatchError()


def _lock_rentals(session: Session) -> tuple[Rental, ...]:
    try:
        return tuple(
            session.scalars(
                _rental_lock_statement()
                .execution_options(autoflush=False, populate_existing=True)
            )
        )
    except SQLAlchemyError:
        raise ExpressTypeBackfillPersistenceError() from None


def _identity_lock_statement() -> sa.Select[tuple[TenantDatabaseIdentity]]:
    return (
        sa.select(TenantDatabaseIdentity)
        .order_by(TenantDatabaseIdentity.singleton_key)
        .with_for_update()
    )


def _rental_lock_statement() -> sa.Select[tuple[Rental]]:
    return sa.select(Rental).order_by(Rental.id).with_for_update()


def _snapshot_matches_source(
    current: ExpressTypeSourceSnapshot,
    source: ExpressTypeSourceSnapshot,
) -> bool:
    return (
        current.total_count == source.total_count
        and current.state_counts == source.state_counts
        and current.source_digest == source.source_digest
        and current.expected_result_digest == source.expected_result_digest
    )


def _snapshot_matches_result(
    current: ExpressTypeSourceSnapshot,
    source: ExpressTypeSourceSnapshot,
) -> bool:
    return (
        current.total_count == source.total_count
        and current.state_counts == source.expected_state_counts
        and current.source_digest == source.expected_result_digest
        and current.expected_result_digest == source.expected_result_digest
    )


def _prepare_session(session: Session) -> SessionTransaction:
    if not isinstance(session, Session):
        raise ExpressTypeBackfillInputError()
    transaction = session.get_transaction()
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
    ):
        raise ExpressTypeBackfillTransactionError()
    _require_clean_session(session)
    try:
        connection = session.connection()
        if connection.dialect.name != "sqlite":
            return transaction
        driver = getattr(connection.connection, "driver_connection", None)
        if driver is not None and not driver.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")
    except ExpressTypeBackfillError:
        raise
    except SQLAlchemyError:
        raise ExpressTypeBackfillPersistenceError() from None
    return transaction


def _require_same_transaction(
    session: Session,
    expected: SessionTransaction,
) -> None:
    if not expected.is_active or session.get_transaction() is not expected:
        raise ExpressTypeBackfillTransactionError()


def _require_clean_session(session: Session) -> None:
    dirty = any(
        session.is_modified(instance, include_collections=True)
        for instance in session.dirty
    )
    if session.new or session.deleted or dirty:
        raise ExpressTypeBackfillTransactionError()


def _materialize_rows(
    rows: Iterable[tuple[int, object]],
) -> tuple[tuple[int, object], ...]:
    try:
        materialized = tuple(rows)
    except (TypeError, ValueError):
        raise ExpressTypeBackfillInputError() from None
    normalized: list[tuple[int, object]] = []
    for row in materialized:
        if not isinstance(row, tuple) or len(row) != 2:
            raise ExpressTypeBackfillInputError()
        row_id, value = row
        if (
            not isinstance(row_id, int)
            or isinstance(row_id, bool)
            or row_id <= 0
        ):
            raise ExpressTypeBackfillInputError()
        _encoded_value(value)
        normalized.append((row_id, value))
    normalized.sort(key=lambda item: item[0])
    if len({row_id for row_id, _ in normalized}) != len(normalized):
        raise ExpressTypeBackfillInputError()
    return tuple(normalized)


def _count_states(
    rows: tuple[tuple[int, object], ...],
) -> tuple[tuple[str, int], ...]:
    counts = {state: 0 for state in _STATE_ORDER}
    for _, value in rows:
        counts[_state(value)] += 1
    return tuple((state.value, counts[state]) for state in _STATE_ORDER)


def _state(value: object) -> ExpressTypeState:
    if value is None:
        return ExpressTypeState.HISTORICAL_NULL
    if type(value) is int:
        if value == 1:
            return ExpressTypeState.CANONICAL_1
        if value == 2:
            return ExpressTypeState.CANONICAL_2
        if value == 263:
            return ExpressTypeState.CANONICAL_263
        if value == 6:
            return ExpressTypeState.LEGACY_6
    return ExpressTypeState.UNSUPPORTED


def _snapshot_digest(rows: tuple[tuple[int, object], ...]) -> bytes:
    hasher = hashlib.sha256(_SNAPSHOT_DOMAIN)
    for row_id, value in rows:
        encoded = _encoded_value(value)
        hasher.update(row_id.to_bytes(8, "big", signed=False))
        hasher.update(len(encoded).to_bytes(8, "big", signed=False))
        hasher.update(encoded)
    return hasher.digest()


def _encoded_value(value: object) -> bytes:
    if value is None:
        return b"n"
    if type(value) is bool:
        return b"b1" if value else b"b0"
    if type(value) is int:
        return b"i" + str(value).encode("ascii")
    if type(value) is float:
        return b"f" + value.hex().encode("ascii")
    if type(value) is str:
        return b"s" + value.encode("utf-8")
    if type(value) is bytes:
        return b"x" + value
    raise ExpressTypeBackfillInputError()


def _report_digest(
    *,
    manifest: ExpressTypeBackfillManifest,
    verification_passed: bool,
    safe_status: str,
) -> bytes:
    payload = {
        "expected_result_digest": (
            manifest.source_snapshot.expected_result_digest.hex()
        ),
        "manifest_digest": manifest.digest.hex(),
        "safe_status": safe_status,
        "source_state_counts": list(manifest.source_snapshot.state_counts),
        "verification_passed": verification_passed,
    }
    return hashlib.sha256(_REPORT_DOMAIN + _canonical_json(payload)).digest()


def _safe_status(legacy_count: int, unsupported_count: int) -> str:
    if legacy_count and unsupported_count:
        return "blocked_legacy_and_unsupported"
    if legacy_count:
        return "blocked_legacy_6"
    if unsupported_count:
        return "blocked_unsupported"
    return "verified"


def _validated_state_counts(
    value: object,
) -> tuple[tuple[str, int], ...]:
    expected_keys = tuple(state.value for state in _STATE_ORDER)
    if not isinstance(value, tuple) or len(value) != len(expected_keys):
        raise ExpressTypeBackfillInputError()
    keys: list[str] = []
    normalized: list[tuple[str, int]] = []
    for item in value:
        if not isinstance(item, tuple) or len(item) != 2:
            raise ExpressTypeBackfillInputError()
        key, count = item
        if not isinstance(key, str):
            raise ExpressTypeBackfillInputError()
        _nonnegative_integer(count)
        keys.append(key)
        normalized.append((key, count))
    if tuple(keys) != expected_keys:
        raise ExpressTypeBackfillInputError()
    return tuple(normalized)


def _canonical_datetime(value: object) -> str:
    if not isinstance(value, datetime):
        raise ExpressTypeBackfillInputError()
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value.isoformat(timespec="microseconds") + "Z"


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _safe_id(value: object) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise ExpressTypeBackfillInputError()
    return value


def _required_uuid(value: object) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise ExpressTypeBackfillInputError()
    return value


def _positive_integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ExpressTypeBackfillInputError()
    return value


def _nonnegative_integer(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ExpressTypeBackfillInputError()
    return value


def _digest(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != _DIGEST_BYTES:
        raise ExpressTypeBackfillInputError()
    return value


__all__ = [
    "EXPRESS_TYPE_BACKFILL_POLICY_REVISION",
    "TENANT_IDENTITY_DIGEST_REVISION",
    "ExpressTypeBackfillConflictError",
    "ExpressTypeBackfillError",
    "ExpressTypeBackfillIdentityMismatchError",
    "ExpressTypeBackfillInputError",
    "ExpressTypeBackfillManifest",
    "ExpressTypeBackfillPersistenceError",
    "ExpressTypeBackfillResult",
    "ExpressTypeBackfillSchemaMismatchError",
    "ExpressTypeBackfillService",
    "ExpressTypeBackfillTransactionError",
    "ExpressTypeSourceSnapshot",
    "ExpressTypeState",
    "TenantSchemaAuthorityCurrentRead",
    "TenantSchemaAuthorityFacts",
    "build_express_type_source_snapshot",
    "tenant_database_identity_digest",
]
