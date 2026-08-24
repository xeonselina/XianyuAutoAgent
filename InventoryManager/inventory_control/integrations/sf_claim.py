"""Pure global SF monthly-account claim transitions.

The permanent claim row contains only a keyed fingerprint and technical owner
identifiers.  Provider validation, OTP consumption, and persistence happen at
adapters; this reducer validates the already trusted facts and emits an
append-only event value suitable for the same control transaction.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from inventory_control.crypto import ProviderAccountFingerprint
from inventory_control.domain import EffectiveTenantGate, TenantRole


_ZERO_HASH = b"\x00" * 32


class SfClaimError(RuntimeError):
    code = "SF_CLAIM_ERROR"
    public_message = "the SF account claim operation failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class SfClaimUnavailable(SfClaimError):
    code = "SF_ACCOUNT_UNAVAILABLE"
    public_message = "the SF account is unavailable"


class SfClaimAuthorityDenied(SfClaimError):
    code = "SF_CLAIM_AUTHORITY_DENIED"
    public_message = "the SF account action is not permitted"


class SfClaimFenceConflict(SfClaimError):
    code = "SF_CLAIM_FENCE_CONFLICT"
    public_message = "the SF account claim changed"


class SfClaimIdempotencyConflict(SfClaimError):
    code = "SF_CLAIM_IDEMPOTENCY_CONFLICT"
    public_message = "the SF account request conflicts with an earlier request"


class SfClaimState(str, Enum):
    RELEASED = "released"
    RESERVED = "reserved"
    ACTIVE = "active"


class SfClaimEventKind(str, Enum):
    RESERVED = "reserved"
    ACTIVATED = "activated"
    RELEASED_BY_ADMIN = "released_by_admin"
    RELEASED_BY_DELETION = "released_by_deletion"


@dataclass(frozen=True, slots=True)
class SfClaimOwner:
    tenant_uuid: UUID
    provider_account_uuid: UUID
    warehouse_uuid: UUID

    def __post_init__(self) -> None:
        _uuid(self.tenant_uuid)
        _uuid(self.provider_account_uuid)
        _uuid(self.warehouse_uuid)


@dataclass(frozen=True, slots=True)
class SfAdminClaimProof:
    """Trusted result of current session/RBAC/gate and D48 OTP checks."""

    tenant_uuid: UUID
    actor_user_uuid: UUID
    actor_session_uuid: UUID
    role: TenantRole
    effective_gate: EffectiveTenantGate
    tenant_access_version: int
    otp_challenge_uuid: UUID
    otp_purpose: str
    otp_action_uuid: UUID
    otp_request_digest: bytes
    otp_consumed: bool

    def __post_init__(self) -> None:
        for value in (
            self.tenant_uuid,
            self.actor_user_uuid,
            self.actor_session_uuid,
            self.otp_challenge_uuid,
            self.otp_action_uuid,
        ):
            _uuid(value)
        if not isinstance(self.role, TenantRole):
            raise TypeError("role must be a TenantRole")
        if not isinstance(self.effective_gate, EffectiveTenantGate):
            raise TypeError("effective_gate must be an EffectiveTenantGate")
        _positive(self.tenant_access_version)
        if self.otp_purpose not in {
            "sf_account_bind",
            "sf_account_unbind",
            "sf_account_rebind",
        }:
            raise ValueError("OTP purpose is invalid")
        _digest(self.otp_request_digest)
        if not isinstance(self.otp_consumed, bool):
            raise TypeError("otp_consumed must be a bool")


@dataclass(frozen=True, slots=True)
class SfDeletionClaimProof:
    """Trusted, irreversible D26 claim-release authority."""

    tenant_uuid: UUID
    deletion_request_uuid: UUID
    action_uuid: UUID
    execution_generation: int
    fencing_token: int
    tombstone_sequence: int
    tombstone_record_hash: bytes
    offsite_acknowledged: bool
    irreversible_deletion: bool

    def __post_init__(self) -> None:
        for value in (
            self.tenant_uuid,
            self.deletion_request_uuid,
            self.action_uuid,
        ):
            _uuid(value)
        for value in (
            self.execution_generation,
            self.fencing_token,
            self.tombstone_sequence,
        ):
            _positive(value)
        _digest(self.tombstone_record_hash)
        if not isinstance(self.offsite_acknowledged, bool) or not isinstance(
            self.irreversible_deletion, bool
        ):
            raise TypeError("deletion authority flags must be bools")


@dataclass(frozen=True, slots=True)
class SfAccountClaim:
    claim_uuid: UUID
    fingerprint: ProviderAccountFingerprint
    state: SfClaimState
    generation: int
    row_version: int
    owner: SfClaimOwner | None
    reservation_action_uuid: UUID | None
    reservation_request_digest: bytes | None
    reservation_expires_at: datetime | None
    active_binding_revision: int | None
    last_action_uuid: UUID | None
    last_request_digest: bytes | None
    event_sequence: int
    event_head_hash: bytes

    def __post_init__(self) -> None:
        _uuid(self.claim_uuid)
        if not isinstance(self.fingerprint, ProviderAccountFingerprint):
            raise TypeError("fingerprint must be a ProviderAccountFingerprint")
        if not isinstance(self.state, SfClaimState):
            raise TypeError("state must be an SfClaimState")
        _positive(self.generation)
        _positive(self.row_version)
        if not isinstance(self.event_sequence, int) or self.event_sequence < 0:
            raise ValueError("event_sequence must be non-negative")
        _digest(self.event_head_hash)
        _optional_action_pair(self.last_action_uuid, self.last_request_digest)

        if self.state is SfClaimState.RELEASED:
            if any(
                value is not None
                for value in (
                    self.owner,
                    self.reservation_action_uuid,
                    self.reservation_request_digest,
                    self.reservation_expires_at,
                    self.active_binding_revision,
                )
            ):
                raise ValueError("released claim cannot retain an owner")
        elif self.state is SfClaimState.RESERVED:
            if not isinstance(self.owner, SfClaimOwner):
                raise ValueError("reserved claim requires an owner")
            _optional_action_pair(
                self.reservation_action_uuid,
                self.reservation_request_digest,
                required=True,
            )
            _utc(self.reservation_expires_at)
            if self.active_binding_revision is not None:
                raise ValueError("reserved claim cannot have a binding revision")
        else:
            if not isinstance(self.owner, SfClaimOwner):
                raise ValueError("active claim requires an owner")
            if any(
                value is not None
                for value in (
                    self.reservation_action_uuid,
                    self.reservation_request_digest,
                    self.reservation_expires_at,
                )
            ):
                raise ValueError("active claim cannot retain reservation fields")
            _positive(self.active_binding_revision)

    @classmethod
    def unowned(
        cls,
        *,
        claim_uuid: UUID,
        fingerprint: ProviderAccountFingerprint,
    ) -> "SfAccountClaim":
        return cls(
            claim_uuid=claim_uuid,
            fingerprint=fingerprint,
            state=SfClaimState.RELEASED,
            generation=1,
            row_version=1,
            owner=None,
            reservation_action_uuid=None,
            reservation_request_digest=None,
            reservation_expires_at=None,
            active_binding_revision=None,
            last_action_uuid=None,
            last_request_digest=None,
            event_sequence=0,
            event_head_hash=_ZERO_HASH,
        )


@dataclass(frozen=True, slots=True)
class SfClaimEvent:
    claim_uuid: UUID
    event_kind: SfClaimEventKind
    before_state: SfClaimState
    after_state: SfClaimState
    generation: int
    sequence: int
    action_uuid: UUID
    actor_type: str
    tenant_uuid: UUID
    provider_account_uuid: UUID
    warehouse_uuid: UUID
    occurred_at: datetime
    previous_hash: bytes
    record_hash: bytes

    def __post_init__(self) -> None:
        for value in (
            self.claim_uuid,
            self.action_uuid,
            self.tenant_uuid,
            self.provider_account_uuid,
            self.warehouse_uuid,
        ):
            _uuid(value)
        if not isinstance(self.event_kind, SfClaimEventKind):
            raise TypeError("event_kind must be an SfClaimEventKind")
        if not isinstance(self.before_state, SfClaimState) or not isinstance(
            self.after_state, SfClaimState
        ):
            raise TypeError("claim event states are invalid")
        _positive(self.generation)
        _positive(self.sequence)
        if self.actor_type not in {"tenant_admin", "system_deletion"}:
            raise ValueError("claim event actor type is invalid")
        object.__setattr__(self, "occurred_at", _utc(self.occurred_at))
        _digest(self.previous_hash)
        _digest(self.record_hash)


@dataclass(frozen=True, slots=True)
class SfClaimTransition:
    claim: SfAccountClaim
    event: SfClaimEvent | None
    idempotent_replay: bool


def reserve_sf_claim(
    current: SfAccountClaim,
    *,
    owner: SfClaimOwner,
    proof: SfAdminClaimProof,
    expected_generation: int,
    expected_row_version: int,
    action_uuid: UUID,
    request_digest: bytes,
    reservation_expires_at: datetime,
    database_now: datetime,
) -> SfClaimTransition:
    now = _utc(database_now)
    expires = _utc(reservation_expires_at)
    _uuid(action_uuid)
    _digest(request_digest)
    _require_admin(proof, owner=owner, purpose={"sf_account_bind", "sf_account_rebind"})
    _require_action_binding(proof, action_uuid, request_digest)
    replay = _replay(current, action_uuid=action_uuid, request_digest=request_digest)
    if replay:
        if current.state in {SfClaimState.RESERVED, SfClaimState.ACTIVE} and (
            current.owner == owner
        ):
            return SfClaimTransition(current, None, True)
        raise SfClaimIdempotencyConflict()
    _require_fence(current, expected_generation, expected_row_version)
    if expires <= now:
        raise SfClaimFenceConflict()
    if current.state is SfClaimState.ACTIVE:
        raise SfClaimUnavailable()
    if (
        current.state is SfClaimState.RESERVED
        and _utc(current.reservation_expires_at) > now
    ):
        raise SfClaimUnavailable()

    after = replace(
        current,
        state=SfClaimState.RESERVED,
        generation=current.generation + 1,
        row_version=current.row_version + 1,
        owner=owner,
        reservation_action_uuid=action_uuid,
        reservation_request_digest=bytes(request_digest),
        reservation_expires_at=expires,
        active_binding_revision=None,
        last_action_uuid=action_uuid,
        last_request_digest=bytes(request_digest),
    )
    return _with_event(
        before=current,
        after=after,
        kind=SfClaimEventKind.RESERVED,
        action_uuid=action_uuid,
        actor_type="tenant_admin",
        owner=owner,
        occurred_at=now,
    )


def activate_sf_claim(
    current: SfAccountClaim,
    *,
    owner: SfClaimOwner,
    proof: SfAdminClaimProof,
    expected_generation: int,
    expected_row_version: int,
    action_uuid: UUID,
    request_digest: bytes,
    binding_revision: int,
    database_now: datetime,
) -> SfClaimTransition:
    now = _utc(database_now)
    _uuid(action_uuid)
    _digest(request_digest)
    _positive(binding_revision)
    _require_admin(proof, owner=owner, purpose={"sf_account_bind", "sf_account_rebind"})
    _require_action_binding(proof, action_uuid, request_digest)
    replay = _replay(current, action_uuid=action_uuid, request_digest=request_digest)
    if replay and current.state is SfClaimState.ACTIVE:
        if current.owner == owner and current.active_binding_revision == binding_revision:
            return SfClaimTransition(current, None, True)
        raise SfClaimIdempotencyConflict()
    _require_fence(current, expected_generation, expected_row_version)
    if (
        current.state is not SfClaimState.RESERVED
        or current.owner != owner
        or current.reservation_action_uuid != action_uuid
        or not hmac.compare_digest(
            current.reservation_request_digest or b"", request_digest
        )
        or _utc(current.reservation_expires_at) <= now
    ):
        raise SfClaimFenceConflict()
    after = replace(
        current,
        state=SfClaimState.ACTIVE,
        generation=current.generation + 1,
        row_version=current.row_version + 1,
        reservation_action_uuid=None,
        reservation_request_digest=None,
        reservation_expires_at=None,
        active_binding_revision=binding_revision,
        last_action_uuid=action_uuid,
        last_request_digest=bytes(request_digest),
    )
    return _with_event(
        before=current,
        after=after,
        kind=SfClaimEventKind.ACTIVATED,
        action_uuid=action_uuid,
        actor_type="tenant_admin",
        owner=owner,
        occurred_at=now,
    )


def release_sf_claim(
    current: SfAccountClaim,
    *,
    proof: SfAdminClaimProof | SfDeletionClaimProof,
    expected_generation: int,
    expected_row_version: int,
    action_uuid: UUID,
    request_digest: bytes,
    database_now: datetime,
) -> SfClaimTransition:
    now = _utc(database_now)
    _uuid(action_uuid)
    _digest(request_digest)
    replay = _replay(current, action_uuid=action_uuid, request_digest=request_digest)
    if replay and current.state is SfClaimState.RELEASED:
        return SfClaimTransition(current, None, True)
    _require_fence(current, expected_generation, expected_row_version)
    if current.state is SfClaimState.RELEASED or current.owner is None:
        raise SfClaimFenceConflict()
    owner = current.owner

    if isinstance(proof, SfAdminClaimProof):
        _require_admin(proof, owner=owner, purpose={"sf_account_unbind"})
        _require_action_binding(proof, action_uuid, request_digest)
        kind = SfClaimEventKind.RELEASED_BY_ADMIN
        actor_type = "tenant_admin"
    elif isinstance(proof, SfDeletionClaimProof):
        if (
            proof.tenant_uuid != owner.tenant_uuid
            or proof.action_uuid != action_uuid
            or not proof.offsite_acknowledged
            or not proof.irreversible_deletion
        ):
            raise SfClaimAuthorityDenied()
        kind = SfClaimEventKind.RELEASED_BY_DELETION
        actor_type = "system_deletion"
    else:
        raise TypeError("proof must be an SF claim authority proof")

    after = replace(
        current,
        state=SfClaimState.RELEASED,
        generation=current.generation + 1,
        row_version=current.row_version + 1,
        owner=None,
        reservation_action_uuid=None,
        reservation_request_digest=None,
        reservation_expires_at=None,
        active_binding_revision=None,
        last_action_uuid=action_uuid,
        last_request_digest=bytes(request_digest),
    )
    return _with_event(
        before=current,
        after=after,
        kind=kind,
        action_uuid=action_uuid,
        actor_type=actor_type,
        owner=owner,
        occurred_at=now,
    )


def _with_event(
    *,
    before: SfAccountClaim,
    after: SfAccountClaim,
    kind: SfClaimEventKind,
    action_uuid: UUID,
    actor_type: str,
    owner: SfClaimOwner,
    occurred_at: datetime,
) -> SfClaimTransition:
    sequence = before.event_sequence + 1
    payload = {
        "claim_uuid": str(before.claim_uuid),
        "fingerprint_sha256": before.fingerprint.digest.hex(),
        "fingerprint_version": before.fingerprint.fingerprint_version,
        "root_key_version": before.fingerprint.root_key_version,
        "event_kind": kind.value,
        "before_state": before.state.value,
        "after_state": after.state.value,
        "generation": after.generation,
        "sequence": sequence,
        "action_uuid": str(action_uuid),
        "actor_type": actor_type,
        "tenant_uuid": str(owner.tenant_uuid),
        "provider_account_uuid": str(owner.provider_account_uuid),
        "warehouse_uuid": str(owner.warehouse_uuid),
        "occurred_at": occurred_at.isoformat(),
        "previous_hash": before.event_head_hash.hex(),
    }
    record_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).digest()
    event = SfClaimEvent(
        claim_uuid=before.claim_uuid,
        event_kind=kind,
        before_state=before.state,
        after_state=after.state,
        generation=after.generation,
        sequence=sequence,
        action_uuid=action_uuid,
        actor_type=actor_type,
        tenant_uuid=owner.tenant_uuid,
        provider_account_uuid=owner.provider_account_uuid,
        warehouse_uuid=owner.warehouse_uuid,
        occurred_at=occurred_at,
        previous_hash=before.event_head_hash,
        record_hash=record_hash,
    )
    sealed = replace(
        after,
        event_sequence=sequence,
        event_head_hash=record_hash,
    )
    return SfClaimTransition(sealed, event, False)


def _require_admin(
    proof: SfAdminClaimProof,
    *,
    owner: SfClaimOwner,
    purpose: set[str],
) -> None:
    if not isinstance(proof, SfAdminClaimProof):
        raise TypeError("proof must be an SfAdminClaimProof")
    if (
        proof.tenant_uuid != owner.tenant_uuid
        or proof.role is not TenantRole.ADMIN
        or proof.effective_gate is not EffectiveTenantGate.ACTIVE
        or not proof.otp_consumed
        or proof.otp_purpose not in purpose
    ):
        raise SfClaimAuthorityDenied()


def _require_action_binding(
    proof: SfAdminClaimProof,
    action_uuid: UUID,
    request_digest: bytes,
) -> None:
    if proof.otp_action_uuid != action_uuid or not hmac.compare_digest(
        proof.otp_request_digest, request_digest
    ):
        raise SfClaimAuthorityDenied()


def _require_fence(current: SfAccountClaim, generation: int, row_version: int) -> None:
    if not isinstance(current, SfAccountClaim):
        raise TypeError("current must be an SfAccountClaim")
    _positive(generation)
    _positive(row_version)
    if current.generation != generation or current.row_version != row_version:
        raise SfClaimFenceConflict()


def _replay(
    current: SfAccountClaim,
    *,
    action_uuid: UUID,
    request_digest: bytes,
) -> bool:
    if current.last_action_uuid != action_uuid:
        return False
    if not hmac.compare_digest(current.last_request_digest or b"", request_digest):
        raise SfClaimIdempotencyConflict()
    return True


def _optional_action_pair(
    action_uuid: UUID | None,
    request_digest: bytes | None,
    *,
    required: bool = False,
) -> None:
    if (action_uuid is None) != (request_digest is None) or (
        required and action_uuid is None
    ):
        raise ValueError("action identity is incomplete")
    if action_uuid is not None:
        _uuid(action_uuid)
        _digest(request_digest)


def _uuid(value: object) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError("technical identity must be a non-nil UUID")


def _positive(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("version must be positive")


def _digest(value: object) -> None:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError("digest must contain 32 bytes")


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("time must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "SfAccountClaim",
    "SfAdminClaimProof",
    "SfClaimAuthorityDenied",
    "SfClaimError",
    "SfClaimEvent",
    "SfClaimEventKind",
    "SfClaimFenceConflict",
    "SfClaimIdempotencyConflict",
    "SfClaimOwner",
    "SfClaimState",
    "SfClaimTransition",
    "SfClaimUnavailable",
    "SfDeletionClaimProof",
    "activate_sf_claim",
    "release_sf_claim",
    "reserve_sf_claim",
]
