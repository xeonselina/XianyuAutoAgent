"""Pure tenant-database account-mutation lease and rotation protocol.

This module deliberately knows nothing about SQLAlchemy, MySQL connections,
advisory locks, passwords, or deployment.  Persistence adapters own CAS and
external executors own physical account operations.  The reducers only decide
immutable state and the fail-closed effects that an executor must converge.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Iterable
from uuid import UUID

from .identity import AccountKind
from .router import AccountLoginState


_SAFE_TECHNICAL_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}$")
_SAFE_ERROR_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,63}$")


class AccountRotationState(str, Enum):
    PREPARING = "preparing"
    PREPARED_LOCKED = "prepared_locked"
    CANDIDATE_TESTING = "candidate_testing"
    VERIFIED = "verified"
    SWITCHED = "switched"
    DRAINING = "draining"
    REVOKED = "revoked"
    FAILED = "failed"


class AccountRotationPurpose(str, Enum):
    STANDARD = "standard"
    ROOT_KEY_ROTATION = "root_key_rotation"
    RECOVERY_RELEASE = "recovery_release"
    SUSPENSION_RESOLVE = "suspension_resolve"
    DELETION_CANCEL = "deletion_cancel"


class AccountUnlockAuthority(str, Enum):
    ACTIVE_ROTATION = "active_rotation"
    RECOVERY_RELEASE = "recovery_release"
    SUSPENSION_RESOLVE = "suspension_resolve"
    DELETION_CANCEL = "deletion_cancel"


class AccountLeaseEffectKind(str, Enum):
    NONE = "none"
    CLAIMED = "claimed"
    RENEWED = "renewed"
    RELEASED = "released"


class AccountRotationAction(str, Enum):
    START = "start"
    PREPARE_LOCKED = "prepare_locked"
    BEGIN_CANDIDATE_TESTING = "begin_candidate_testing"
    VERIFY_CANDIDATE = "verify_candidate"
    SWITCH_CANDIDATE = "switch_candidate"
    BEGIN_DRAINING = "begin_draining"
    REVOKE_PREVIOUS = "revoke_previous"
    FAIL = "fail"


@dataclass(frozen=True, slots=True)
class AccountMutationEffects:
    """Non-secret physical convergence facts emitted by a reducer."""

    create_candidate_locked: bool = False
    unlock_candidate_for_testing: bool = False
    lock_candidate: bool = False
    candidate_must_remain_unpublished: bool = False
    publish_candidate: bool = False
    lock_other_generations: bool = False
    drain_previous_generation: bool = False
    revoke_previous_generation: bool = False
    dispose_candidate_engine: bool = False
    route_must_remain_denied: bool = False
    resulting_route_version: int | None = None
    safe_outcome_code: str = "ACCOUNT_MUTATION_NO_CHANGE"

    def __post_init__(self) -> None:
        for value in (
            self.create_candidate_locked,
            self.unlock_candidate_for_testing,
            self.lock_candidate,
            self.candidate_must_remain_unpublished,
            self.publish_candidate,
            self.lock_other_generations,
            self.drain_previous_generation,
            self.revoke_previous_generation,
            self.dispose_candidate_engine,
            self.route_must_remain_denied,
        ):
            if not isinstance(value, bool):
                raise TypeError("account mutation effect flags must be bools")
        if self.publish_candidate and self.candidate_must_remain_unpublished:
            raise ValueError("a candidate cannot be published and unpublished")
        if self.unlock_candidate_for_testing and self.lock_candidate:
            raise ValueError("candidate lock effects conflict")
        if self.resulting_route_version is not None:
            _positive(self.resulting_route_version, "resulting_route_version")
            if not self.publish_candidate:
                raise ValueError("a route version requires candidate publication")
        _safe_error_code(self.safe_outcome_code)


class AccountMutationError(RuntimeError):
    code = "ACCOUNT_MUTATION_REJECTED"
    public_message = "the database account mutation was rejected"

    def __init__(
        self,
        effects: AccountMutationEffects | None = None,
    ) -> None:
        self.effects = effects or _DEFAULT_FAILURE_EFFECTS
        super().__init__(self.public_message)


class AccountMutationLeaseUnavailable(AccountMutationError):
    code = "ACCOUNT_MUTATION_LEASE_UNAVAILABLE"
    public_message = "the database account mutation lease is unavailable"


class AccountMutationLeaseExpired(AccountMutationError):
    code = "ACCOUNT_MUTATION_LEASE_EXPIRED"
    public_message = "the database account mutation lease expired"


class AccountMutationFenceConflict(AccountMutationError):
    code = "ACCOUNT_MUTATION_FENCE_CONFLICT"
    public_message = "the database account mutation changed"


class AccountMutationStateConflict(AccountMutationError):
    code = "ACCOUNT_MUTATION_STATE_CONFLICT"
    public_message = "the database account mutation is out of order"


class AccountMutationProofRejected(AccountMutationError):
    code = "ACCOUNT_MUTATION_PROOF_REJECTED"
    public_message = "the database account proof was rejected"


class AccountMutationIdempotencyConflict(AccountMutationError):
    code = "ACCOUNT_MUTATION_IDEMPOTENCY_CONFLICT"
    public_message = "the database account replay conflicts"


class AccountMutationOrderError(AccountMutationError):
    code = "ACCOUNT_MUTATION_ORDER_INVALID"
    public_message = "the database account mutation order is invalid"


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountMutationLease:
    tenant_uuid: UUID
    account_kind: AccountKind
    fencing_token: int
    owner: str | None
    purpose: str | None
    expires_at: datetime | None
    row_version: int

    def __post_init__(self) -> None:
        _uuid(self.tenant_uuid, "tenant_uuid")
        object.__setattr__(self, "account_kind", _account_kind(self.account_kind))
        _nonnegative(self.fencing_token, "fencing_token")
        _positive(self.row_version, "row_version")
        present = (
            self.owner is not None,
            self.purpose is not None,
            self.expires_at is not None,
        )
        if any(present) and not all(present):
            raise ValueError("lease ownership fields are incomplete")
        if self.owner is not None:
            _technical_text(self.owner, "owner")
            _technical_text(self.purpose, "purpose")
            object.__setattr__(self, "expires_at", _utc(self.expires_at))

    @classmethod
    def unclaimed(
        cls,
        *,
        tenant_uuid: UUID,
        account_kind: AccountKind,
        row_version: int = 1,
    ) -> "AccountMutationLease":
        return cls(
            tenant_uuid=tenant_uuid,
            account_kind=account_kind,
            fencing_token=0,
            owner=None,
            purpose=None,
            expires_at=None,
            row_version=row_version,
        )

    def active_at(self, database_now: datetime) -> bool:
        now = _utc(database_now)
        return bool(
            self.owner is not None
            and self.expires_at is not None
            and self.expires_at > now
        )


@dataclass(frozen=True, slots=True)
class AccountLeaseTransition:
    lease: AccountMutationLease
    effect: AccountLeaseEffectKind
    idempotent_replay: bool


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountGeneration:
    username: str
    credential_generation: int
    root_key_version: int
    derivation_version: int

    def __post_init__(self) -> None:
        _technical_text(self.username, "username")
        _positive(self.credential_generation, "credential_generation")
        _positive(self.root_key_version, "root_key_version")
        _positive(self.derivation_version, "derivation_version")


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountCandidatePreparationProof:
    rotation_uuid: UUID
    tenant_uuid: UUID
    database_uuid: UUID
    account_kind: AccountKind
    candidate: AccountGeneration
    candidate_created: bool
    candidate_locked: bool
    candidate_unpublished: bool

    def __post_init__(self) -> None:
        _uuid(self.rotation_uuid, "rotation_uuid")
        _uuid(self.tenant_uuid, "tenant_uuid")
        _uuid(self.database_uuid, "database_uuid")
        object.__setattr__(self, "account_kind", _account_kind(self.account_kind))
        if not isinstance(self.candidate, AccountGeneration):
            raise TypeError("candidate must be an AccountGeneration")
        _bools(
            self.candidate_created,
            self.candidate_locked,
            self.candidate_unpublished,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountUnlockAuthorityProof:
    """Trusted result of identity, permission, isolation, and lock checks."""

    rotation_uuid: UUID
    tenant_uuid: UUID
    database_uuid: UUID
    account_kind: AccountKind
    previous: AccountGeneration
    candidate: AccountGeneration
    authority: AccountUnlockAuthority
    expected_tenant_access_version: int
    expected_route_version: int
    expected_login_state_version: int
    lease_owner: str
    lease_fencing_token: int
    database_identity_verified: bool
    positive_permissions_verified: bool
    cross_schema_rejected: bool
    candidate_unpublished: bool
    other_generations_locked: bool
    advisory_lock_held: bool
    application_route_denied: bool

    def __post_init__(self) -> None:
        _uuid(self.rotation_uuid, "rotation_uuid")
        _uuid(self.tenant_uuid, "tenant_uuid")
        _uuid(self.database_uuid, "database_uuid")
        object.__setattr__(self, "account_kind", _account_kind(self.account_kind))
        if not isinstance(self.previous, AccountGeneration) or not isinstance(
            self.candidate, AccountGeneration
        ):
            raise TypeError("account generations are invalid")
        try:
            authority = AccountUnlockAuthority(self.authority)
        except (TypeError, ValueError):
            raise ValueError("unlock authority is invalid") from None
        object.__setattr__(self, "authority", authority)
        for value, name in (
            (self.expected_tenant_access_version, "expected_tenant_access_version"),
            (self.expected_route_version, "expected_route_version"),
            (self.expected_login_state_version, "expected_login_state_version"),
            (self.lease_fencing_token, "lease_fencing_token"),
        ):
            _positive(value, name)
        _technical_text(self.lease_owner, "lease_owner")
        _bools(
            self.database_identity_verified,
            self.positive_permissions_verified,
            self.cross_schema_rejected,
            self.candidate_unpublished,
            self.other_generations_locked,
            self.advisory_lock_held,
            self.application_route_denied,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountRevocationProof:
    rotation_uuid: UUID
    tenant_uuid: UUID
    database_uuid: UUID
    account_kind: AccountKind
    previous: AccountGeneration
    candidate: AccountGeneration
    lease_owner: str
    lease_fencing_token: int
    candidate_published: bool
    previous_locked: bool
    previous_connections_drained: bool
    previous_revoked: bool

    def __post_init__(self) -> None:
        _uuid(self.rotation_uuid, "rotation_uuid")
        _uuid(self.tenant_uuid, "tenant_uuid")
        _uuid(self.database_uuid, "database_uuid")
        object.__setattr__(self, "account_kind", _account_kind(self.account_kind))
        if not isinstance(self.previous, AccountGeneration) or not isinstance(
            self.candidate, AccountGeneration
        ):
            raise TypeError("account generations are invalid")
        _technical_text(self.lease_owner, "lease_owner")
        _positive(self.lease_fencing_token, "lease_fencing_token")
        _bools(
            self.candidate_published,
            self.previous_locked,
            self.previous_connections_drained,
            self.previous_revoked,
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class AccountRotation:
    rotation_uuid: UUID
    tenant_uuid: UUID
    database_uuid: UUID
    account_kind: AccountKind
    purpose: AccountRotationPurpose
    previous: AccountGeneration
    candidate: AccountGeneration
    inherited_desired_login_state: AccountLoginState
    expected_tenant_access_version: int
    expected_route_version: int
    expected_login_state_version: int
    lease_owner: str
    lease_purpose: str
    lease_fencing_token: int
    state: AccountRotationState
    candidate_locked: bool
    candidate_published: bool
    previous_locked: bool
    previous_revoked: bool
    transition_sequence: int
    last_action: AccountRotationAction | None
    last_request_digest: bytes | None
    safe_error_code: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.rotation_uuid, "rotation_uuid")
        _uuid(self.tenant_uuid, "tenant_uuid")
        _uuid(self.database_uuid, "database_uuid")
        object.__setattr__(self, "account_kind", _account_kind(self.account_kind))
        try:
            purpose = AccountRotationPurpose(self.purpose)
            state = AccountRotationState(self.state)
        except (TypeError, ValueError):
            raise ValueError("account rotation enum is invalid") from None
        object.__setattr__(self, "purpose", purpose)
        object.__setattr__(self, "state", state)
        if not isinstance(self.previous, AccountGeneration) or not isinstance(
            self.candidate, AccountGeneration
        ):
            raise TypeError("account generations are invalid")
        if (
            self.previous.username == self.candidate.username
            or self.candidate.credential_generation
            <= self.previous.credential_generation
        ):
            raise ValueError("candidate must be a distinct later generation")
        try:
            desired = AccountLoginState(self.inherited_desired_login_state)
        except (TypeError, ValueError):
            raise ValueError("inherited desired login state is invalid") from None
        object.__setattr__(self, "inherited_desired_login_state", desired)
        for value, name in (
            (self.expected_tenant_access_version, "expected_tenant_access_version"),
            (self.expected_route_version, "expected_route_version"),
            (self.expected_login_state_version, "expected_login_state_version"),
            (self.lease_fencing_token, "lease_fencing_token"),
        ):
            _positive(value, name)
        _technical_text(self.lease_owner, "lease_owner")
        _technical_text(self.lease_purpose, "lease_purpose")
        _nonnegative(self.transition_sequence, "transition_sequence")
        _bools(
            self.candidate_locked,
            self.candidate_published,
            self.previous_locked,
            self.previous_revoked,
        )
        if self.last_action is not None:
            try:
                last_action = AccountRotationAction(self.last_action)
            except (TypeError, ValueError):
                raise ValueError(
                    "last account rotation action is invalid"
                ) from None
            object.__setattr__(self, "last_action", last_action)
        _optional_action_pair(self.last_action, self.last_request_digest)
        if self.safe_error_code is not None:
            _safe_error_code(self.safe_error_code)

        if state in {
            AccountRotationState.PREPARING,
            AccountRotationState.PREPARED_LOCKED,
        } and (not self.candidate_locked or self.candidate_published):
            raise ValueError("preparing candidate must be locked and unpublished")
        if state in {
            AccountRotationState.CANDIDATE_TESTING,
            AccountRotationState.VERIFIED,
        } and (self.candidate_locked or self.candidate_published):
            raise ValueError("testing candidate must be unpublished")
        if state in {
            AccountRotationState.SWITCHED,
            AccountRotationState.DRAINING,
            AccountRotationState.REVOKED,
        } and (
            self.candidate_locked
            or not self.candidate_published
            or not self.previous_locked
        ):
            raise ValueError("switched rotation facts are inconsistent")
        if state is AccountRotationState.REVOKED and not self.previous_revoked:
            raise ValueError("revoked rotation requires previous revocation")
        if state is not AccountRotationState.REVOKED and self.previous_revoked:
            raise ValueError("previous generation was revoked out of order")
        if state is AccountRotationState.FAILED:
            if not self.candidate_locked or not self.previous_locked:
                raise ValueError("failed rotation must converge locked")
            if self.safe_error_code is None:
                raise ValueError("failed rotation requires a safe error code")
        elif self.safe_error_code is not None:
            raise ValueError("only failed rotations contain an error code")

    @property
    def from_username(self) -> str:
        return self.previous.username

    @property
    def to_username(self) -> str:
        return self.candidate.username

    @property
    def from_generation(self) -> int:
        return self.previous.credential_generation

    @property
    def to_generation(self) -> int:
        return self.candidate.credential_generation

    @property
    def from_root_key_version(self) -> int:
        return self.previous.root_key_version

    @property
    def to_root_key_version(self) -> int:
        return self.candidate.root_key_version

    @property
    def from_derivation_version(self) -> int:
        return self.previous.derivation_version

    @property
    def to_derivation_version(self) -> int:
        return self.candidate.derivation_version


@dataclass(frozen=True, slots=True)
class AccountRotationTransition:
    rotation: AccountRotation
    effects: AccountMutationEffects
    idempotent_replay: bool


ACCOUNT_MUTATION_ACCOUNT_ORDER = (
    AccountKind.DML,
    AccountKind.PLATFORM_READ,
)


def order_account_kinds(
    account_kinds: Iterable[AccountKind],
) -> tuple[AccountKind, ...]:
    selected = tuple(_account_kind(value) for value in account_kinds)
    if len(set(selected)) != len(selected):
        raise AccountMutationOrderError()
    selected_set = set(selected)
    return tuple(
        kind
        for kind in ACCOUNT_MUTATION_ACCOUNT_ORDER
        if kind in selected_set
    )


def require_account_kind_order(
    account_kinds: Iterable[AccountKind],
) -> tuple[AccountKind, ...]:
    selected = tuple(_account_kind(value) for value in account_kinds)
    if selected != order_account_kinds(selected):
        raise AccountMutationOrderError()
    return selected


def claim_account_mutation_lease(
    current: AccountMutationLease,
    *,
    owner: str,
    purpose: str,
    expected_row_version: int,
    lease_expires_at: datetime,
    database_now: datetime,
) -> AccountLeaseTransition:
    _lease(current)
    selected_owner = _technical_text(owner, "owner")
    selected_purpose = _technical_text(purpose, "purpose")
    expected = _positive(expected_row_version, "expected_row_version")
    now = _utc(database_now)
    expires = _utc(lease_expires_at)
    if expires <= now:
        raise AccountMutationLeaseExpired()

    if current.active_at(now):
        if (
            current.owner == selected_owner
            and current.purpose == selected_purpose
            and current.expires_at == expires
        ):
            return AccountLeaseTransition(
                current,
                AccountLeaseEffectKind.NONE,
                True,
            )
        raise AccountMutationLeaseUnavailable()
    if current.row_version != expected:
        raise AccountMutationFenceConflict()

    after = replace(
        current,
        fencing_token=current.fencing_token + 1,
        owner=selected_owner,
        purpose=selected_purpose,
        expires_at=expires,
        row_version=current.row_version + 1,
    )
    return AccountLeaseTransition(after, AccountLeaseEffectKind.CLAIMED, False)


def renew_account_mutation_lease(
    current: AccountMutationLease,
    *,
    owner: str,
    fencing_token: int,
    expected_row_version: int,
    lease_expires_at: datetime,
    database_now: datetime,
) -> AccountLeaseTransition:
    _lease(current)
    selected_owner = _technical_text(owner, "owner")
    token = _positive(fencing_token, "fencing_token")
    expected = _positive(expected_row_version, "expected_row_version")
    now = _utc(database_now)
    expires = _utc(lease_expires_at)
    if current.owner != selected_owner or current.fencing_token != token:
        raise AccountMutationFenceConflict()
    if not current.active_at(now):
        raise AccountMutationLeaseExpired()
    if expires == current.expires_at:
        return AccountLeaseTransition(current, AccountLeaseEffectKind.NONE, True)
    if expires <= now or expires < current.expires_at:
        raise AccountMutationLeaseExpired()
    if current.row_version != expected:
        raise AccountMutationFenceConflict()
    after = replace(
        current,
        expires_at=expires,
        row_version=current.row_version + 1,
    )
    return AccountLeaseTransition(after, AccountLeaseEffectKind.RENEWED, False)


def release_account_mutation_lease(
    current: AccountMutationLease,
    *,
    owner: str,
    fencing_token: int,
    expected_row_version: int,
    database_now: datetime,
) -> AccountLeaseTransition:
    _lease(current)
    selected_owner = _technical_text(owner, "owner")
    token = _positive(fencing_token, "fencing_token")
    expected = _positive(expected_row_version, "expected_row_version")
    now = _utc(database_now)
    if current.owner is None:
        if current.fencing_token == token:
            return AccountLeaseTransition(current, AccountLeaseEffectKind.NONE, True)
        raise AccountMutationFenceConflict()
    if current.owner != selected_owner or current.fencing_token != token:
        raise AccountMutationFenceConflict()
    if not current.active_at(now):
        raise AccountMutationLeaseExpired()
    if current.row_version != expected:
        raise AccountMutationFenceConflict()
    after = replace(
        current,
        owner=None,
        purpose=None,
        expires_at=None,
        row_version=current.row_version + 1,
    )
    return AccountLeaseTransition(after, AccountLeaseEffectKind.RELEASED, False)


def start_account_rotation(
    *,
    current: AccountRotation | None = None,
    rotation_uuid: UUID,
    tenant_uuid: UUID,
    database_uuid: UUID,
    account_kind: AccountKind,
    purpose: AccountRotationPurpose,
    previous: AccountGeneration,
    candidate: AccountGeneration,
    inherited_desired_login_state: AccountLoginState,
    expected_tenant_access_version: int,
    expected_route_version: int,
    expected_login_state_version: int,
    lease: AccountMutationLease,
    database_now: datetime,
) -> AccountRotationTransition:
    now = _utc(database_now)
    selected_purpose = _rotation_purpose(purpose)
    try:
        selected_desired = AccountLoginState(inherited_desired_login_state)
    except (TypeError, ValueError):
        raise ValueError("inherited desired login state is invalid") from None
    digest = _start_digest(
        rotation_uuid=rotation_uuid,
        tenant_uuid=tenant_uuid,
        database_uuid=database_uuid,
        account_kind=account_kind,
        purpose=selected_purpose,
        previous=previous,
        candidate=candidate,
        inherited_desired_login_state=selected_desired,
        expected_tenant_access_version=expected_tenant_access_version,
        expected_route_version=expected_route_version,
        expected_login_state_version=expected_login_state_version,
        lease=lease,
    )
    if current is not None:
        _rotation(current)
        if (
            current.rotation_uuid == rotation_uuid
            and current.last_action is AccountRotationAction.START
            and hmac.compare_digest(current.last_request_digest or b"", digest)
        ):
            return AccountRotationTransition(
                current,
                _no_change_effects("ACCOUNT_ROTATION_START_REPLAY"),
                True,
            )
        raise AccountMutationIdempotencyConflict(_fail_closed_effects(current))

    _require_active_lease(
        lease,
        tenant_uuid=tenant_uuid,
        account_kind=account_kind,
        database_now=now,
    )
    if lease.purpose != selected_purpose.value:
        raise AccountMutationFenceConflict()

    rotation = AccountRotation(
        rotation_uuid=rotation_uuid,
        tenant_uuid=tenant_uuid,
        database_uuid=database_uuid,
        account_kind=account_kind,
        purpose=selected_purpose,
        previous=previous,
        candidate=candidate,
        inherited_desired_login_state=selected_desired,
        expected_tenant_access_version=expected_tenant_access_version,
        expected_route_version=expected_route_version,
        expected_login_state_version=expected_login_state_version,
        lease_owner=lease.owner,
        lease_purpose=lease.purpose,
        lease_fencing_token=lease.fencing_token,
        state=AccountRotationState.PREPARING,
        candidate_locked=True,
        candidate_published=False,
        previous_locked=(selected_desired is AccountLoginState.LOCKED),
        previous_revoked=False,
        transition_sequence=1,
        last_action=AccountRotationAction.START,
        last_request_digest=digest,
    )
    effects = AccountMutationEffects(
        create_candidate_locked=True,
        lock_candidate=True,
        candidate_must_remain_unpublished=True,
        route_must_remain_denied=(
            rotation.inherited_desired_login_state is AccountLoginState.LOCKED
        ),
        safe_outcome_code="ACCOUNT_CANDIDATE_CREATE_LOCKED",
    )
    return AccountRotationTransition(rotation, effects, False)


def mark_account_candidate_prepared(
    current: AccountRotation,
    *,
    lease: AccountMutationLease,
    proof: AccountCandidatePreparationProof,
    database_now: datetime,
) -> AccountRotationTransition:
    _rotation(current)
    digest = _preparation_digest(proof)
    replay = _rotation_replay(
        current,
        destination=AccountRotationState.PREPARED_LOCKED,
        action=AccountRotationAction.PREPARE_LOCKED,
        digest=digest,
    )
    if replay is not None:
        return replay
    _require_state(current, AccountRotationState.PREPARING)
    _require_rotation_lease(current, lease, database_now=database_now)
    if (
        proof.rotation_uuid != current.rotation_uuid
        or proof.tenant_uuid != current.tenant_uuid
        or proof.database_uuid != current.database_uuid
        or proof.account_kind is not current.account_kind
        or proof.candidate != current.candidate
        or not proof.candidate_created
        or not proof.candidate_locked
        or not proof.candidate_unpublished
    ):
        raise AccountMutationProofRejected(_fail_closed_effects(current))
    after = _advance(
        current,
        state=AccountRotationState.PREPARED_LOCKED,
        action=AccountRotationAction.PREPARE_LOCKED,
        digest=digest,
        candidate_locked=True,
        candidate_published=False,
    )
    return AccountRotationTransition(
        after,
        AccountMutationEffects(
            lock_candidate=True,
            candidate_must_remain_unpublished=True,
            route_must_remain_denied=(
                current.inherited_desired_login_state
                is AccountLoginState.LOCKED
            ),
            safe_outcome_code="ACCOUNT_CANDIDATE_PREPARED_LOCKED",
        ),
        False,
    )


def begin_account_candidate_testing(
    current: AccountRotation,
    *,
    lease: AccountMutationLease,
    proof: AccountUnlockAuthorityProof,
    database_now: datetime,
) -> AccountRotationTransition:
    return _unlock_transition(
        current,
        lease=lease,
        proof=proof,
        database_now=database_now,
        source=AccountRotationState.PREPARED_LOCKED,
        destination=AccountRotationState.CANDIDATE_TESTING,
        action=AccountRotationAction.BEGIN_CANDIDATE_TESTING,
        effects=AccountMutationEffects(
            unlock_candidate_for_testing=True,
            candidate_must_remain_unpublished=True,
            lock_other_generations=True,
            route_must_remain_denied=True,
            safe_outcome_code="ACCOUNT_CANDIDATE_TESTING_AUTHORIZED",
        ),
    )


def verify_account_candidate(
    current: AccountRotation,
    *,
    lease: AccountMutationLease,
    proof: AccountUnlockAuthorityProof,
    database_now: datetime,
) -> AccountRotationTransition:
    return _unlock_transition(
        current,
        lease=lease,
        proof=proof,
        database_now=database_now,
        source=AccountRotationState.CANDIDATE_TESTING,
        destination=AccountRotationState.VERIFIED,
        action=AccountRotationAction.VERIFY_CANDIDATE,
        effects=AccountMutationEffects(
            candidate_must_remain_unpublished=True,
            lock_other_generations=True,
            route_must_remain_denied=True,
            safe_outcome_code="ACCOUNT_CANDIDATE_VERIFIED_UNPUBLISHED",
        ),
    )


def switch_account_candidate(
    current: AccountRotation,
    *,
    lease: AccountMutationLease,
    proof: AccountUnlockAuthorityProof,
    database_now: datetime,
) -> AccountRotationTransition:
    return _unlock_transition(
        current,
        lease=lease,
        proof=proof,
        database_now=database_now,
        source=AccountRotationState.VERIFIED,
        destination=AccountRotationState.SWITCHED,
        action=AccountRotationAction.SWITCH_CANDIDATE,
        effects=AccountMutationEffects(
            publish_candidate=True,
            lock_other_generations=True,
            resulting_route_version=current.expected_route_version + 1,
            safe_outcome_code="ACCOUNT_CANDIDATE_SWITCHED",
        ),
    )


def begin_previous_account_draining(
    current: AccountRotation,
    *,
    lease: AccountMutationLease,
    database_now: datetime,
) -> AccountRotationTransition:
    _rotation(current)
    digest = _simple_action_digest(
        current,
        AccountRotationAction.BEGIN_DRAINING,
    )
    replay = _rotation_replay(
        current,
        destination=AccountRotationState.DRAINING,
        action=AccountRotationAction.BEGIN_DRAINING,
        digest=digest,
    )
    if replay is not None:
        return replay
    _require_state(current, AccountRotationState.SWITCHED)
    _require_rotation_lease(current, lease, database_now=database_now)
    after = _advance(
        current,
        state=AccountRotationState.DRAINING,
        action=AccountRotationAction.BEGIN_DRAINING,
        digest=digest,
    )
    return AccountRotationTransition(
        after,
        AccountMutationEffects(
            lock_other_generations=True,
            drain_previous_generation=True,
            safe_outcome_code="ACCOUNT_PREVIOUS_DRAINING",
        ),
        False,
    )


def revoke_previous_account(
    current: AccountRotation,
    *,
    lease: AccountMutationLease,
    proof: AccountRevocationProof,
    database_now: datetime,
) -> AccountRotationTransition:
    _rotation(current)
    digest = _revocation_digest(proof)
    replay = _rotation_replay(
        current,
        destination=AccountRotationState.REVOKED,
        action=AccountRotationAction.REVOKE_PREVIOUS,
        digest=digest,
    )
    if replay is not None:
        return replay
    _require_state(current, AccountRotationState.DRAINING)
    _require_rotation_lease(current, lease, database_now=database_now)
    if (
        proof.rotation_uuid != current.rotation_uuid
        or proof.tenant_uuid != current.tenant_uuid
        or proof.database_uuid != current.database_uuid
        or proof.account_kind is not current.account_kind
        or proof.previous != current.previous
        or proof.candidate != current.candidate
        or proof.lease_owner != current.lease_owner
        or proof.lease_fencing_token != current.lease_fencing_token
        or not proof.candidate_published
        or not proof.previous_locked
        or not proof.previous_connections_drained
        or not proof.previous_revoked
    ):
        raise AccountMutationProofRejected(_fail_closed_effects(current))
    after = _advance(
        current,
        state=AccountRotationState.REVOKED,
        action=AccountRotationAction.REVOKE_PREVIOUS,
        digest=digest,
        previous_revoked=True,
    )
    return AccountRotationTransition(
        after,
        AccountMutationEffects(
            lock_other_generations=True,
            revoke_previous_generation=True,
            safe_outcome_code="ACCOUNT_PREVIOUS_REVOKED",
        ),
        False,
    )


def fail_account_rotation(
    current: AccountRotation,
    *,
    lease: AccountMutationLease,
    safe_error_code: str,
    database_now: datetime,
) -> AccountRotationTransition:
    _rotation(current)
    error_code = _safe_error_code(safe_error_code)
    digest = _failure_digest(current, error_code)
    replay = _rotation_replay(
        current,
        destination=AccountRotationState.FAILED,
        action=AccountRotationAction.FAIL,
        digest=digest,
    )
    if replay is not None:
        return replay
    if current.state is AccountRotationState.REVOKED:
        raise AccountMutationStateConflict(_fail_closed_effects(current))
    _require_rotation_lease(current, lease, database_now=database_now)
    after = _advance(
        current,
        state=AccountRotationState.FAILED,
        action=AccountRotationAction.FAIL,
        digest=digest,
        candidate_locked=True,
        previous_locked=True,
        safe_error_code=error_code,
    )
    return AccountRotationTransition(after, _fail_closed_effects(after), False)


def _unlock_transition(
    current: AccountRotation,
    *,
    lease: AccountMutationLease,
    proof: AccountUnlockAuthorityProof,
    database_now: datetime,
    source: AccountRotationState,
    destination: AccountRotationState,
    action: AccountRotationAction,
    effects: AccountMutationEffects,
) -> AccountRotationTransition:
    _rotation(current)
    digest = _unlock_digest(proof, action=action)
    replay = _rotation_replay(
        current,
        destination=destination,
        action=action,
        digest=digest,
    )
    if replay is not None:
        return replay
    _require_state(current, source)
    _require_rotation_lease(current, lease, database_now=database_now)
    _require_unlock_proof(current, proof)

    changes: dict[str, object] = {
        "candidate_locked": False,
        "previous_locked": True,
    }
    if destination is AccountRotationState.SWITCHED:
        changes["candidate_published"] = True
    after = _advance(
        current,
        state=destination,
        action=action,
        digest=digest,
        **changes,
    )
    return AccountRotationTransition(after, effects, False)


def _require_unlock_proof(
    current: AccountRotation,
    proof: AccountUnlockAuthorityProof,
) -> None:
    expected_authority = _expected_unlock_authority(current)
    if (
        proof.rotation_uuid != current.rotation_uuid
        or proof.tenant_uuid != current.tenant_uuid
        or proof.database_uuid != current.database_uuid
        or proof.account_kind is not current.account_kind
        or proof.previous != current.previous
        or proof.candidate != current.candidate
        or proof.authority is not expected_authority
        or proof.expected_tenant_access_version
        != current.expected_tenant_access_version
        or proof.expected_route_version != current.expected_route_version
        or proof.expected_login_state_version
        != current.expected_login_state_version
        or proof.lease_owner != current.lease_owner
        or proof.lease_fencing_token != current.lease_fencing_token
        or not proof.database_identity_verified
        or not proof.positive_permissions_verified
        or not proof.cross_schema_rejected
        or not proof.candidate_unpublished
        or not proof.other_generations_locked
        or not proof.advisory_lock_held
        or not proof.application_route_denied
        or current.candidate_published
    ):
        raise AccountMutationProofRejected(_fail_closed_effects(current))


def _expected_unlock_authority(
    rotation: AccountRotation,
) -> AccountUnlockAuthority:
    if rotation.purpose is AccountRotationPurpose.RECOVERY_RELEASE:
        return AccountUnlockAuthority.RECOVERY_RELEASE
    if rotation.purpose is AccountRotationPurpose.SUSPENSION_RESOLVE:
        return AccountUnlockAuthority.SUSPENSION_RESOLVE
    if rotation.purpose is AccountRotationPurpose.DELETION_CANCEL:
        return AccountUnlockAuthority.DELETION_CANCEL
    if rotation.inherited_desired_login_state is AccountLoginState.LOCKED:
        # Standard/root-key rotation while locked is intentionally terminal at
        # prepared_locked.  A caller cannot manufacture an unlock proof for it.
        raise AccountMutationStateConflict(_fail_closed_effects(rotation))
    return AccountUnlockAuthority.ACTIVE_ROTATION


def _require_active_lease(
    lease: AccountMutationLease,
    *,
    tenant_uuid: UUID,
    account_kind: AccountKind,
    database_now: datetime,
) -> None:
    _lease(lease)
    if (
        lease.tenant_uuid != tenant_uuid
        or lease.account_kind is not _account_kind(account_kind)
        or lease.owner is None
    ):
        raise AccountMutationFenceConflict()
    if not lease.active_at(database_now):
        raise AccountMutationLeaseExpired()


def _require_rotation_lease(
    rotation: AccountRotation,
    lease: AccountMutationLease,
    *,
    database_now: datetime,
) -> None:
    try:
        _require_active_lease(
            lease,
            tenant_uuid=rotation.tenant_uuid,
            account_kind=rotation.account_kind,
            database_now=_utc(database_now),
        )
    except AccountMutationError as exc:
        raise type(exc)(_fail_closed_effects(rotation)) from None
    if (
        lease.owner != rotation.lease_owner
        or lease.purpose != rotation.lease_purpose
        or lease.fencing_token != rotation.lease_fencing_token
    ):
        raise AccountMutationFenceConflict(_fail_closed_effects(rotation))


def _require_state(
    rotation: AccountRotation,
    expected: AccountRotationState,
) -> None:
    if rotation.state is not expected:
        raise AccountMutationStateConflict(_fail_closed_effects(rotation))


def _rotation_replay(
    current: AccountRotation,
    *,
    destination: AccountRotationState,
    action: AccountRotationAction,
    digest: bytes,
) -> AccountRotationTransition | None:
    if current.state is not destination:
        return None
    if (
        current.last_action is not action
        or not hmac.compare_digest(current.last_request_digest or b"", digest)
    ):
        raise AccountMutationIdempotencyConflict(_fail_closed_effects(current))
    return AccountRotationTransition(
        current,
        _no_change_effects("ACCOUNT_ROTATION_REPLAY"),
        True,
    )


def _advance(
    current: AccountRotation,
    *,
    state: AccountRotationState,
    action: AccountRotationAction,
    digest: bytes,
    **changes: object,
) -> AccountRotation:
    return replace(
        current,
        state=state,
        transition_sequence=current.transition_sequence + 1,
        last_action=action,
        last_request_digest=digest,
        **changes,
    )


def _fail_closed_effects(rotation: AccountRotation) -> AccountMutationEffects:
    return AccountMutationEffects(
        lock_candidate=True,
        candidate_must_remain_unpublished=not rotation.candidate_published,
        lock_other_generations=True,
        dispose_candidate_engine=True,
        route_must_remain_denied=True,
        safe_outcome_code="ACCOUNT_MUTATION_REJECTED_LOCKED",
    )


def _no_change_effects(code: str) -> AccountMutationEffects:
    return AccountMutationEffects(safe_outcome_code=code)


def _start_digest(**values: object) -> bytes:
    lease = values.pop("lease")
    assert isinstance(lease, AccountMutationLease)
    payload = {
        **values,
        "lease_owner": lease.owner,
        "lease_purpose": lease.purpose,
        "lease_fencing_token": lease.fencing_token,
    }
    return _digest_payload("start", payload)


def _preparation_digest(proof: AccountCandidatePreparationProof) -> bytes:
    return _digest_payload(
        AccountRotationAction.PREPARE_LOCKED.value,
        {
            "rotation_uuid": proof.rotation_uuid,
            "tenant_uuid": proof.tenant_uuid,
            "database_uuid": proof.database_uuid,
            "account_kind": proof.account_kind,
            "candidate": proof.candidate,
            "candidate_created": proof.candidate_created,
            "candidate_locked": proof.candidate_locked,
            "candidate_unpublished": proof.candidate_unpublished,
        },
    )


def _unlock_digest(
    proof: AccountUnlockAuthorityProof,
    *,
    action: AccountRotationAction,
) -> bytes:
    return _digest_payload(
        action.value,
        {
            "rotation_uuid": proof.rotation_uuid,
            "tenant_uuid": proof.tenant_uuid,
            "database_uuid": proof.database_uuid,
            "account_kind": proof.account_kind,
            "previous": proof.previous,
            "candidate": proof.candidate,
            "authority": proof.authority,
            "expected_tenant_access_version": (
                proof.expected_tenant_access_version
            ),
            "expected_route_version": proof.expected_route_version,
            "expected_login_state_version": proof.expected_login_state_version,
            "lease_owner": proof.lease_owner,
            "lease_fencing_token": proof.lease_fencing_token,
            "database_identity_verified": proof.database_identity_verified,
            "positive_permissions_verified": (
                proof.positive_permissions_verified
            ),
            "cross_schema_rejected": proof.cross_schema_rejected,
            "candidate_unpublished": proof.candidate_unpublished,
            "other_generations_locked": proof.other_generations_locked,
            "advisory_lock_held": proof.advisory_lock_held,
            "application_route_denied": proof.application_route_denied,
        },
    )


def _revocation_digest(proof: AccountRevocationProof) -> bytes:
    return _digest_payload(
        AccountRotationAction.REVOKE_PREVIOUS.value,
        {
            "rotation_uuid": proof.rotation_uuid,
            "tenant_uuid": proof.tenant_uuid,
            "database_uuid": proof.database_uuid,
            "account_kind": proof.account_kind,
            "previous": proof.previous,
            "candidate": proof.candidate,
            "lease_owner": proof.lease_owner,
            "lease_fencing_token": proof.lease_fencing_token,
            "candidate_published": proof.candidate_published,
            "previous_locked": proof.previous_locked,
            "previous_connections_drained": (
                proof.previous_connections_drained
            ),
            "previous_revoked": proof.previous_revoked,
        },
    )


def _simple_action_digest(
    rotation: AccountRotation,
    action: AccountRotationAction,
) -> bytes:
    return _digest_payload(
        action.value,
        {
            "rotation_uuid": rotation.rotation_uuid,
            "tenant_uuid": rotation.tenant_uuid,
            "database_uuid": rotation.database_uuid,
            "account_kind": rotation.account_kind,
            "lease_owner": rotation.lease_owner,
            "lease_fencing_token": rotation.lease_fencing_token,
        },
    )


def _failure_digest(rotation: AccountRotation, safe_error_code: str) -> bytes:
    return _digest_payload(
        AccountRotationAction.FAIL.value,
        {
            "rotation_uuid": rotation.rotation_uuid,
            "tenant_uuid": rotation.tenant_uuid,
            "database_uuid": rotation.database_uuid,
            "account_kind": rotation.account_kind,
            "lease_owner": rotation.lease_owner,
            "lease_fencing_token": rotation.lease_fencing_token,
            "safe_error_code": safe_error_code,
        },
    )


def _digest_payload(action: str, values: dict[str, object]) -> bytes:
    payload = {
        "domain": "inventory-manager/account-mutation/v1",
        "action": action,
        **{key: _json_value(value) for key, value in values.items()},
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "ascii"
        )
    ).digest()


def _json_value(value: object) -> object:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, AccountGeneration):
        return {
            "username": value.username,
            "credential_generation": value.credential_generation,
            "root_key_version": value.root_key_version,
            "derivation_version": value.derivation_version,
        }
    return value


def _optional_action_pair(
    action: AccountRotationAction | None,
    digest: bytes | None,
) -> None:
    if (action is None) != (digest is None):
        raise ValueError("last account rotation action is incomplete")
    if action is not None:
        _digest(digest)


def _lease(value: object) -> AccountMutationLease:
    if not isinstance(value, AccountMutationLease):
        raise TypeError("current must be an AccountMutationLease")
    return value


def _rotation(value: object) -> AccountRotation:
    if not isinstance(value, AccountRotation):
        raise TypeError("current must be an AccountRotation")
    return value


def _account_kind(value: object) -> AccountKind:
    try:
        return AccountKind(value)
    except (TypeError, ValueError):
        raise ValueError("account kind is unsupported") from None


def _rotation_purpose(value: object) -> AccountRotationPurpose:
    try:
        return AccountRotationPurpose(value)
    except (TypeError, ValueError):
        raise ValueError("account rotation purpose is invalid") from None


def _uuid(value: object, name: str) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise ValueError(f"{name} is invalid")
    return value


def _technical_text(value: object, name: str) -> str:
    if not isinstance(value, str) or _SAFE_TECHNICAL_TEXT.fullmatch(value) is None:
        raise ValueError(f"{name} is invalid")
    return value


def _safe_error_code(value: object) -> str:
    if not isinstance(value, str) or _SAFE_ERROR_CODE.fullmatch(value) is None:
        raise ValueError("safe error code is invalid")
    return value


def _positive(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be positive")
    return value


def _nonnegative(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be non-negative")
    return value


def _digest(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError("digest must contain 32 bytes")
    return value


def _bools(*values: object) -> None:
    if any(not isinstance(value, bool) for value in values):
        raise TypeError("proof flags must be bools")


def _utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise ValueError("time must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


_DEFAULT_FAILURE_EFFECTS = AccountMutationEffects(
    lock_candidate=True,
    candidate_must_remain_unpublished=True,
    lock_other_generations=True,
    dispose_candidate_engine=True,
    route_must_remain_denied=True,
    safe_outcome_code="ACCOUNT_MUTATION_REJECTED_LOCKED",
)


# Readable aliases for orchestration code.
prepare_account_rotation = mark_account_candidate_prepared
begin_account_rotation_candidate_testing = begin_account_candidate_testing
verify_account_rotation_candidate = verify_account_candidate
switch_account_rotation_candidate = switch_account_candidate


__all__ = [
    "ACCOUNT_MUTATION_ACCOUNT_ORDER",
    "AccountCandidatePreparationProof",
    "AccountGeneration",
    "AccountLeaseEffectKind",
    "AccountLeaseTransition",
    "AccountMutationEffects",
    "AccountMutationError",
    "AccountMutationFenceConflict",
    "AccountMutationIdempotencyConflict",
    "AccountMutationLease",
    "AccountMutationLeaseExpired",
    "AccountMutationLeaseUnavailable",
    "AccountMutationOrderError",
    "AccountMutationProofRejected",
    "AccountMutationStateConflict",
    "AccountRevocationProof",
    "AccountRotation",
    "AccountRotationAction",
    "AccountRotationPurpose",
    "AccountRotationState",
    "AccountRotationTransition",
    "AccountUnlockAuthority",
    "AccountUnlockAuthorityProof",
    "begin_account_candidate_testing",
    "begin_account_rotation_candidate_testing",
    "begin_previous_account_draining",
    "claim_account_mutation_lease",
    "fail_account_rotation",
    "mark_account_candidate_prepared",
    "order_account_kinds",
    "prepare_account_rotation",
    "release_account_mutation_lease",
    "renew_account_mutation_lease",
    "require_account_kind_order",
    "revoke_previous_account",
    "start_account_rotation",
    "switch_account_candidate",
    "switch_account_rotation_candidate",
    "verify_account_candidate",
    "verify_account_rotation_candidate",
]
