"""Pure fleet-wide schema-operation lease protocol.

The lease serializes operations that can change or require a stable view of
the database fleet.  This module performs no SQL, DDL, filesystem, provider,
or network work.  Callers persist the returned state and use the fencing token
at every external boundary.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from inventory_control.evidence import canonical_json_sha256


_TECHNICAL_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_SHA256_BYTES = 32


class SchemaOperationPurpose(str, Enum):
    """Closed Core purpose set for the one fleet-wide mutex."""

    PROVISIONING = "provisioning"
    FLEET_MIGRATION = "fleet_migration"
    BACKUP = "backup"
    RESTORE = "restore"
    DELETION = "deletion"
    ACCOUNT_MUTATION = "account_mutation"


class SchemaOperationLeaseState(str, Enum):
    AVAILABLE = "available"
    HELD = "held"


class SchemaOperationLeaseEffect(str, Enum):
    CLAIMED = "claimed"
    RENEWED = "renewed"
    RELEASED = "released"


class SchemaOperationLeaseError(RuntimeError):
    """Stable error that never incorporates caller or persisted values."""

    code = "SCHEMA_OPERATION_LEASE_REJECTED"
    public_message = "the schema operation lease request was rejected"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class SchemaOperationLeaseInvalid(SchemaOperationLeaseError):
    code = "SCHEMA_OPERATION_LEASE_INVALID"
    public_message = "the schema operation lease request is invalid"


class SchemaOperationLeaseUnavailable(SchemaOperationLeaseError):
    code = "SCHEMA_OPERATION_LEASE_UNAVAILABLE"
    public_message = "the schema operation lease is unavailable"


class SchemaOperationLeaseExpired(SchemaOperationLeaseError):
    code = "SCHEMA_OPERATION_LEASE_EXPIRED"
    public_message = "the schema operation lease expired"


class SchemaOperationLeaseFenceConflict(SchemaOperationLeaseError):
    code = "SCHEMA_OPERATION_LEASE_FENCE_CONFLICT"
    public_message = "the schema operation lease changed"


class SchemaOperationLeaseIdempotencyConflict(SchemaOperationLeaseError):
    code = "SCHEMA_OPERATION_LEASE_IDEMPOTENCY_CONFLICT"
    public_message = "the schema operation lease replay conflicts"


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaOperationLease:
    """Persisted singleton state with monotonic acquisition and row fences."""

    state: SchemaOperationLeaseState
    generation: int
    fencing_token: int
    row_version: int
    observed_at: datetime
    owner_id: str | None = None
    claim_id: UUID | None = None
    purpose: SchemaOperationPurpose | None = None
    acquired_at: datetime | None = None
    expires_at: datetime | None = None
    last_claim_id: UUID | None = None
    last_effect: SchemaOperationLeaseEffect | None = None
    last_request_digest: bytes | None = None

    def __post_init__(self) -> None:
        try:
            state = SchemaOperationLeaseState(self.state)
        except (TypeError, ValueError):
            _invalid()
        object.__setattr__(self, "state", state)
        _nonnegative(self.generation)
        _nonnegative(self.fencing_token)
        _positive(self.row_version)
        object.__setattr__(self, "observed_at", _utc(self.observed_at))

        if self.last_claim_id is not None:
            _uuid(self.last_claim_id)
        if self.last_effect is not None:
            try:
                effect = SchemaOperationLeaseEffect(self.last_effect)
            except (TypeError, ValueError):
                _invalid()
            object.__setattr__(self, "last_effect", effect)
        if self.last_request_digest is not None:
            _digest(self.last_request_digest)
        if (self.last_effect is None) != (self.last_request_digest is None):
            _invalid()

        if self.generation == 0:
            if (
                self.fencing_token != 0
                or self.last_claim_id is not None
                or self.last_effect is not None
                or state is not SchemaOperationLeaseState.AVAILABLE
            ):
                _invalid()
        elif (
            self.fencing_token <= 0
            or self.last_claim_id is None
            or self.last_effect is None
        ):
            _invalid()

        ownership = (
            self.owner_id,
            self.claim_id,
            self.purpose,
            self.acquired_at,
            self.expires_at,
        )
        if state is SchemaOperationLeaseState.AVAILABLE:
            if any(value is not None for value in ownership):
                _invalid()
            if self.generation > 0 and (
                self.last_effect is not SchemaOperationLeaseEffect.RELEASED
            ):
                _invalid()
            return

        if any(value is None for value in ownership):
            _invalid()
        _owner(self.owner_id)
        _uuid(self.claim_id)
        try:
            purpose = SchemaOperationPurpose(self.purpose)
        except (TypeError, ValueError):
            _invalid()
        object.__setattr__(self, "purpose", purpose)
        acquired = _utc(self.acquired_at)
        expires = _utc(self.expires_at)
        if (
            self.generation <= 0
            or self.fencing_token <= 0
            or self.last_claim_id != self.claim_id
            or self.last_effect
            not in (
                SchemaOperationLeaseEffect.CLAIMED,
                SchemaOperationLeaseEffect.RENEWED,
            )
            or acquired > self.observed_at
            or self.observed_at >= expires
        ):
            _invalid()
        object.__setattr__(self, "acquired_at", acquired)
        object.__setattr__(self, "expires_at", expires)

    @classmethod
    def available(cls, *, observed_at: datetime) -> "SchemaOperationLease":
        return cls(
            state=SchemaOperationLeaseState.AVAILABLE,
            generation=0,
            fencing_token=0,
            row_version=1,
            observed_at=observed_at,
        )

    def active_at(self, database_now: datetime) -> bool:
        now = _utc(database_now)
        return bool(
            self.state is SchemaOperationLeaseState.HELD
            and self.expires_at is not None
            and self.expires_at > now
        )


@dataclass(frozen=True, slots=True)
class SchemaOperationLeaseTransition:
    lease: SchemaOperationLease
    effect: SchemaOperationLeaseEffect
    idempotent_replay: bool


def claim_schema_operation_lease(
    current: SchemaOperationLease,
    *,
    claim_id: UUID,
    owner_id: str,
    purpose: SchemaOperationPurpose,
    expected_row_version: int,
    lease_expires_at: datetime,
    database_now: datetime,
) -> SchemaOperationLeaseTransition:
    """Claim, exactly replay, or take over the expired singleton lease."""

    _lease(current)
    _uuid(claim_id)
    _owner(owner_id)
    selected_purpose = _purpose(purpose)
    _positive(expected_row_version)
    expires = _utc(lease_expires_at)
    now = _database_now(current, database_now)
    if expires <= now:
        raise SchemaOperationLeaseInvalid()
    digest = _request_digest(
        effect=SchemaOperationLeaseEffect.CLAIMED,
        claim_id=claim_id,
        owner_id=owner_id,
        purpose=selected_purpose,
        expected_row_version=expected_row_version,
        fencing_token=None,
        lease_expires_at=expires,
    )

    if current.state is SchemaOperationLeaseState.HELD and current.claim_id == claim_id:
        if not current.active_at(now):
            raise SchemaOperationLeaseExpired()
        return _replay(
            current,
            effect=SchemaOperationLeaseEffect.CLAIMED,
            digest=digest,
            expected_row_version=expected_row_version,
        )

    if current.state is SchemaOperationLeaseState.HELD and current.active_at(now):
        raise SchemaOperationLeaseUnavailable()
    if current.last_claim_id == claim_id:
        raise SchemaOperationLeaseIdempotencyConflict()
    _expected_version(current, expected_row_version)

    selected = SchemaOperationLease(
        state=SchemaOperationLeaseState.HELD,
        generation=current.generation + 1,
        fencing_token=current.fencing_token + 1,
        row_version=current.row_version + 1,
        observed_at=now,
        owner_id=owner_id,
        claim_id=claim_id,
        purpose=selected_purpose,
        acquired_at=now,
        expires_at=expires,
        last_claim_id=claim_id,
        last_effect=SchemaOperationLeaseEffect.CLAIMED,
        last_request_digest=digest,
    )
    return SchemaOperationLeaseTransition(
        selected,
        SchemaOperationLeaseEffect.CLAIMED,
        False,
    )


def renew_schema_operation_lease(
    current: SchemaOperationLease,
    *,
    claim_id: UUID,
    owner_id: str,
    purpose: SchemaOperationPurpose,
    fencing_token: int,
    expected_row_version: int,
    lease_expires_at: datetime,
    database_now: datetime,
) -> SchemaOperationLeaseTransition:
    """Extend only the exact live owner without advancing its fence."""

    _lease(current)
    _uuid(claim_id)
    _owner(owner_id)
    selected_purpose = _purpose(purpose)
    _positive(fencing_token)
    _positive(expected_row_version)
    expires = _utc(lease_expires_at)
    now = _database_now(current, database_now)
    digest = _request_digest(
        effect=SchemaOperationLeaseEffect.RENEWED,
        claim_id=claim_id,
        owner_id=owner_id,
        purpose=selected_purpose,
        expected_row_version=expected_row_version,
        fencing_token=fencing_token,
        lease_expires_at=expires,
    )

    _require_held_identity(
        current,
        claim_id=claim_id,
        owner_id=owner_id,
        purpose=selected_purpose,
        fencing_token=fencing_token,
    )
    if not current.active_at(now):
        raise SchemaOperationLeaseExpired()
    replay = _optional_replay(
        current,
        effect=SchemaOperationLeaseEffect.RENEWED,
        digest=digest,
        expected_row_version=expected_row_version,
    )
    if replay is not None:
        return replay
    _expected_version(current, expected_row_version)
    if current.expires_at is None or expires <= current.expires_at:
        raise SchemaOperationLeaseInvalid()

    selected = replace(
        current,
        row_version=current.row_version + 1,
        observed_at=now,
        expires_at=expires,
        last_effect=SchemaOperationLeaseEffect.RENEWED,
        last_request_digest=digest,
    )
    return SchemaOperationLeaseTransition(
        selected,
        SchemaOperationLeaseEffect.RENEWED,
        False,
    )


def release_schema_operation_lease(
    current: SchemaOperationLease,
    *,
    claim_id: UUID,
    owner_id: str,
    purpose: SchemaOperationPurpose,
    fencing_token: int,
    expected_row_version: int,
    database_now: datetime,
) -> SchemaOperationLeaseTransition:
    """Release the exact claim; a stale release cannot clear a new owner."""

    _lease(current)
    _uuid(claim_id)
    _owner(owner_id)
    selected_purpose = _purpose(purpose)
    _positive(fencing_token)
    _positive(expected_row_version)
    now = _database_now(current, database_now)
    digest = _request_digest(
        effect=SchemaOperationLeaseEffect.RELEASED,
        claim_id=claim_id,
        owner_id=owner_id,
        purpose=selected_purpose,
        expected_row_version=expected_row_version,
        fencing_token=fencing_token,
        lease_expires_at=None,
    )

    if current.state is SchemaOperationLeaseState.AVAILABLE:
        return _replay(
            current,
            effect=SchemaOperationLeaseEffect.RELEASED,
            digest=digest,
            expected_row_version=expected_row_version,
        )
    _require_held_identity(
        current,
        claim_id=claim_id,
        owner_id=owner_id,
        purpose=selected_purpose,
        fencing_token=fencing_token,
    )
    _expected_version(current, expected_row_version)
    selected = SchemaOperationLease(
        state=SchemaOperationLeaseState.AVAILABLE,
        generation=current.generation,
        fencing_token=current.fencing_token,
        row_version=current.row_version + 1,
        observed_at=now,
        last_claim_id=current.claim_id,
        last_effect=SchemaOperationLeaseEffect.RELEASED,
        last_request_digest=digest,
    )
    return SchemaOperationLeaseTransition(
        selected,
        SchemaOperationLeaseEffect.RELEASED,
        False,
    )


def require_live_schema_operation_fence(
    current: SchemaOperationLease,
    *,
    claim_id: UUID,
    owner_id: str,
    purpose: SchemaOperationPurpose,
    generation: int,
    fencing_token: int,
    expected_row_version: int,
    database_now: datetime,
) -> SchemaOperationLease:
    """Validate the exact live holder for a final current-read fence.

    This read-only check is intended to run after the caller has locked its
    operation-specific control rows and then locked the singleton lease row.
    It authorizes no external work after the lease expires or any field drifts.
    """

    _lease(current)
    _uuid(claim_id)
    _owner(owner_id)
    selected_purpose = _purpose(purpose)
    _positive(generation)
    _positive(fencing_token)
    _positive(expected_row_version)
    now = _database_now(current, database_now)
    _require_held_identity(
        current,
        claim_id=claim_id,
        owner_id=owner_id,
        purpose=selected_purpose,
        fencing_token=fencing_token,
    )
    if current.generation != generation or current.row_version != expected_row_version:
        raise SchemaOperationLeaseFenceConflict()
    if not current.active_at(now):
        raise SchemaOperationLeaseExpired()
    return current


def _require_held_identity(
    current: SchemaOperationLease,
    *,
    claim_id: UUID,
    owner_id: str,
    purpose: SchemaOperationPurpose,
    fencing_token: int,
) -> None:
    if (
        current.state is not SchemaOperationLeaseState.HELD
        or current.claim_id != claim_id
        or current.owner_id != owner_id
        or current.purpose is not purpose
        or current.fencing_token != fencing_token
    ):
        raise SchemaOperationLeaseFenceConflict()


def _optional_replay(
    current: SchemaOperationLease,
    *,
    effect: SchemaOperationLeaseEffect,
    digest: bytes,
    expected_row_version: int,
) -> SchemaOperationLeaseTransition | None:
    if current.row_version != expected_row_version + 1:
        return None
    return _replay(
        current,
        effect=effect,
        digest=digest,
        expected_row_version=expected_row_version,
    )


def _replay(
    current: SchemaOperationLease,
    *,
    effect: SchemaOperationLeaseEffect,
    digest: bytes,
    expected_row_version: int,
) -> SchemaOperationLeaseTransition:
    if current.row_version != expected_row_version + 1:
        raise SchemaOperationLeaseFenceConflict()
    if current.last_effect is not effect or current.last_request_digest != digest:
        raise SchemaOperationLeaseIdempotencyConflict()
    return SchemaOperationLeaseTransition(current, effect, True)


def _expected_version(
    current: SchemaOperationLease,
    expected_row_version: int,
) -> None:
    if current.row_version != expected_row_version:
        raise SchemaOperationLeaseFenceConflict()


def _database_now(
    current: SchemaOperationLease,
    value: datetime,
) -> datetime:
    now = _utc(value)
    if now < current.observed_at:
        raise SchemaOperationLeaseFenceConflict()
    return now


def _request_digest(
    *,
    effect: SchemaOperationLeaseEffect,
    claim_id: UUID,
    owner_id: str,
    purpose: SchemaOperationPurpose,
    expected_row_version: int,
    fencing_token: int | None,
    lease_expires_at: datetime | None,
) -> bytes:
    payload = {
        "claim_id": str(claim_id),
        "effect": effect.value,
        "expected_row_version": expected_row_version,
        "fencing_token": fencing_token,
        "lease_expires_at": (
            lease_expires_at.isoformat(timespec="microseconds")
            if lease_expires_at is not None
            else None
        ),
        "owner_id": owner_id,
        "purpose": purpose.value,
        "version": 1,
    }
    return canonical_json_sha256(
        payload,
        allow_nan=True,
    )


def _lease(value: object) -> SchemaOperationLease:
    if not isinstance(value, SchemaOperationLease):
        raise SchemaOperationLeaseInvalid()
    return value


def _purpose(value: object) -> SchemaOperationPurpose:
    try:
        return SchemaOperationPurpose(value)
    except (TypeError, ValueError):
        raise SchemaOperationLeaseInvalid() from None


def _owner(value: object) -> str:
    if not isinstance(value, str) or _TECHNICAL_OWNER.fullmatch(value) is None:
        raise SchemaOperationLeaseInvalid()
    return value


def _uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise SchemaOperationLeaseInvalid()
    return value


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise SchemaOperationLeaseInvalid()
    return value


def _nonnegative(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise SchemaOperationLeaseInvalid()
    return value


def _digest(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != _SHA256_BYTES:
        raise SchemaOperationLeaseInvalid()
    return value


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise SchemaOperationLeaseInvalid()
    return value.astimezone(timezone.utc)


def _invalid() -> None:
    raise SchemaOperationLeaseInvalid()


__all__ = [
    "SchemaOperationLease",
    "SchemaOperationLeaseEffect",
    "SchemaOperationLeaseError",
    "SchemaOperationLeaseExpired",
    "SchemaOperationLeaseFenceConflict",
    "SchemaOperationLeaseIdempotencyConflict",
    "SchemaOperationLeaseInvalid",
    "SchemaOperationLeaseState",
    "SchemaOperationLeaseTransition",
    "SchemaOperationLeaseUnavailable",
    "SchemaOperationPurpose",
    "claim_schema_operation_lease",
    "release_schema_operation_lease",
    "require_live_schema_operation_fence",
    "renew_schema_operation_lease",
]
