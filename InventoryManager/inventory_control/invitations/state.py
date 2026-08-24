"""Pure invitation aggregate and first-membership-wins transitions.

Callers are responsible for executing the returned lock plan and persisting a
transition atomically.  This module performs no database, SMS, or provider IO.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID

from inventory_control.identity.errors import PhoneNormalizationError
from inventory_control.identity.phone import normalize_tenant_phone
from inventory_control.subscriptions.seats import CORE_MEMBER_SEAT_CAP

from .tokens import (
    IssuedInvitationToken,
    InvitationTokenGeneration,
    issue_invitation_token,
    rotate_invitation_token,
    verify_invitation_token,
)


class InvitationRole(str, Enum):
    ADMIN = "admin"
    OPERATOR = "operator"


class InvitationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    REVOKED = "revoked"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"


class CoordinatingUserStatus(str, Enum):
    UNVERIFIED = "unverified"
    ACTIVE = "active"
    DISABLED = "disabled"


class InvitationActionKind(str, Enum):
    CREATE_OR_ROTATE = "create_or_rotate"
    REVOKE = "revoke"
    EXPIRE = "expire"
    ACCEPT = "accept"


class InvitationLockKind(str, Enum):
    PHONE_IDENTITY = "phone_identity"
    INVITATION = "invitation"
    TENANT = "tenant"
    MEMBER_SEAT_GUARD = "member_seat_guard"
    CHALLENGE = "challenge"
    MEMBERSHIP = "membership"


class InvitationStateError(ValueError):
    """Stable non-enumerating domain rejection."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class InvitationRecord:
    invitation_id: UUID
    tenant_id: UUID
    canonical_phone: str
    role: InvitationRole
    status: InvitationStatus
    token: InvitationTokenGeneration
    coordinating_user_id: Optional[UUID]
    revision: int = 1
    terminal_at: Optional[datetime] = None
    terminal_action_id: Optional[UUID] = None
    accepted_membership_id: Optional[UUID] = None

    def __post_init__(self) -> None:
        _require_uuid("invitation_id", self.invitation_id)
        _require_uuid("tenant_id", self.tenant_id)
        _require_canonical_phone(self.canonical_phone)
        if not isinstance(self.role, InvitationRole):
            raise TypeError("role must be an InvitationRole")
        if not isinstance(self.status, InvitationStatus):
            raise TypeError("status must be an InvitationStatus")
        if not isinstance(self.token, InvitationTokenGeneration):
            raise TypeError("token must be an InvitationTokenGeneration")
        _require_aware_datetime("token expiry", self.token.expires_at)
        _require_positive_integer("revision", self.revision)

        if self.status is InvitationStatus.PENDING:
            _require_uuid("coordinating_user_id", self.coordinating_user_id)
            if any(
                value is not None
                for value in (
                    self.terminal_at,
                    self.terminal_action_id,
                    self.accepted_membership_id,
                )
            ):
                raise ValueError("pending invitation cannot have terminal facts")
            return

        if self.coordinating_user_id is not None:
            raise ValueError("terminal invitation must clear coordinating user")
        _require_aware_datetime("terminal_at", self.terminal_at)
        _require_uuid("terminal_action_id", self.terminal_action_id)
        if self.status is InvitationStatus.ACCEPTED:
            _require_uuid(
                "accepted_membership_id", self.accepted_membership_id
            )
        elif self.accepted_membership_id is not None:
            raise ValueError("only accepted invitation can name a membership")

    @property
    def expires_at(self) -> datetime:
        return self.token.expires_at

    @property
    def token_generation(self) -> int:
        return self.token.generation


@dataclass(frozen=True, slots=True)
class MembershipClaim:
    membership_id: UUID
    tenant_id: UUID
    user_id: UUID
    canonical_phone: str
    role: InvitationRole
    source_invitation_id: UUID
    accepted_action_id: UUID

    def __post_init__(self) -> None:
        _require_uuid("membership_id", self.membership_id)
        _require_uuid("tenant_id", self.tenant_id)
        _require_uuid("user_id", self.user_id)
        _require_canonical_phone(self.canonical_phone)
        if not isinstance(self.role, InvitationRole):
            raise TypeError("role must be an InvitationRole")
        _require_uuid("source_invitation_id", self.source_invitation_id)
        _require_uuid("accepted_action_id", self.accepted_action_id)


@dataclass(frozen=True, slots=True)
class InvitationActionReceipt:
    action_id: UUID
    kind: InvitationActionKind
    idempotency_key: str
    request_digest: bytes
    primary_invitation_id: UUID
    result_membership_id: Optional[UUID] = None

    def __post_init__(self) -> None:
        _require_uuid("action_id", self.action_id)
        if not isinstance(self.kind, InvitationActionKind):
            raise TypeError("kind must be an InvitationActionKind")
        _require_idempotency_key(self.idempotency_key)
        _require_request_digest(self.request_digest)
        _require_uuid("primary_invitation_id", self.primary_invitation_id)
        if self.result_membership_id is not None:
            _require_uuid("result_membership_id", self.result_membership_id)


@dataclass(frozen=True, slots=True)
class PhoneInvitationAggregate:
    """All invitation and membership facts for one canonical phone."""

    canonical_phone: str
    coordinating_user_id: UUID
    user_status: CoordinatingUserStatus
    invitations: tuple[InvitationRecord, ...] = ()
    membership: Optional[MembershipClaim] = None
    action_receipts: tuple[InvitationActionReceipt, ...] = ()

    def __post_init__(self) -> None:
        _require_canonical_phone(self.canonical_phone)
        _require_uuid("coordinating_user_id", self.coordinating_user_id)
        if not isinstance(self.user_status, CoordinatingUserStatus):
            raise TypeError("user_status must be a CoordinatingUserStatus")
        if not isinstance(self.invitations, tuple) or not all(
            isinstance(invitation, InvitationRecord)
            for invitation in self.invitations
        ):
            raise TypeError("invitations must be immutable InvitationRecords")
        if self.membership is not None and not isinstance(
            self.membership, MembershipClaim
        ):
            raise TypeError("membership must be a MembershipClaim or None")
        if not isinstance(self.action_receipts, tuple) or not all(
            isinstance(receipt, InvitationActionReceipt)
            for receipt in self.action_receipts
        ):
            raise TypeError("action_receipts must be immutable receipts")
        self._validate_identity_and_uniqueness()

    @classmethod
    def empty(
        cls,
        *,
        canonical_phone: str,
        coordinating_user_id: UUID,
        user_status: CoordinatingUserStatus = CoordinatingUserStatus.UNVERIFIED,
    ) -> PhoneInvitationAggregate:
        return cls(
            canonical_phone=canonical_phone,
            coordinating_user_id=coordinating_user_id,
            user_status=user_status,
        )

    def _validate_identity_and_uniqueness(self) -> None:
        invitation_ids: set[UUID] = set()
        pending_tenants: set[UUID] = set()
        accepted: dict[UUID, InvitationRecord] = {}
        for invitation in self.invitations:
            if invitation.canonical_phone != self.canonical_phone:
                raise ValueError("invitation phone must match aggregate")
            if invitation.invitation_id in invitation_ids:
                raise ValueError("invitation IDs must be unique")
            invitation_ids.add(invitation.invitation_id)
            if invitation.status is InvitationStatus.PENDING:
                if invitation.tenant_id in pending_tenants:
                    raise ValueError("one tenant can have only one pending invitation")
                pending_tenants.add(invitation.tenant_id)
                if invitation.coordinating_user_id != self.coordinating_user_id:
                    raise ValueError("pending invitation must bind coordinating user")
            elif invitation.status is InvitationStatus.ACCEPTED:
                accepted[invitation.invitation_id] = invitation

        if self.membership is not None:
            if (
                self.membership.canonical_phone != self.canonical_phone
                or self.membership.user_id != self.coordinating_user_id
            ):
                raise ValueError("membership must bind aggregate identity")
            source = accepted.get(self.membership.source_invitation_id)
            if (
                source is None
                or source.accepted_membership_id != self.membership.membership_id
                or source.tenant_id != self.membership.tenant_id
                or source.role is not self.membership.role
            ):
                raise ValueError("membership must match its accepted invitation")
            if pending_tenants:
                raise ValueError("claimed phone cannot retain pending invitations")
            if self.user_status is not CoordinatingUserStatus.ACTIVE:
                raise ValueError("invitation membership requires active user")
        elif accepted:
            raise ValueError("accepted invitation requires membership claim")

        action_ids: set[UUID] = set()
        idempotency_scopes: set[tuple[InvitationActionKind, str]] = set()
        for receipt in self.action_receipts:
            if receipt.action_id in action_ids:
                raise ValueError("action IDs must be unique")
            action_ids.add(receipt.action_id)
            scope = (receipt.kind, receipt.idempotency_key)
            if scope in idempotency_scopes:
                raise ValueError("idempotency scope must be unique")
            idempotency_scopes.add(scope)


@dataclass(frozen=True, slots=True)
class TenantSeatSnapshot:
    """One locking/current-read member-seat count under the tenant guard."""

    tenant_id: UUID
    active_memberships: int
    unexpired_pending_invitations: int
    guard_revision: int
    counted_at: datetime

    def __post_init__(self) -> None:
        _require_uuid("tenant_id", self.tenant_id)
        _require_non_negative_integer(
            "active_memberships", self.active_memberships
        )
        _require_non_negative_integer(
            "unexpired_pending_invitations",
            self.unexpired_pending_invitations,
        )
        _require_positive_integer("guard_revision", self.guard_revision)
        normalized = _normalize_aware_datetime("counted_at", self.counted_at)
        object.__setattr__(self, "counted_at", normalized)

    @property
    def occupied_seats(self) -> int:
        return self.active_memberships + self.unexpired_pending_invitations


@dataclass(frozen=True, slots=True)
class TenantSeatProjection:
    tenant_id: UUID
    active_memberships_before: int
    pending_invitations_before: int
    active_memberships_after: int
    pending_invitations_after: int
    guard_revision: int

    def __post_init__(self) -> None:
        _require_uuid("tenant_id", self.tenant_id)
        for name in (
            "active_memberships_before",
            "pending_invitations_before",
            "active_memberships_after",
            "pending_invitations_after",
        ):
            _require_non_negative_integer(name, getattr(self, name))
        _require_positive_integer("guard_revision", self.guard_revision)

    @property
    def occupied_before(self) -> int:
        return self.active_memberships_before + self.pending_invitations_before

    @property
    def occupied_after(self) -> int:
        return self.active_memberships_after + self.pending_invitations_after


@dataclass(frozen=True, slots=True)
class AcceptanceChallengeProof:
    """No OTP value: only current, action-bound verification facts."""

    challenge_id: UUID
    invitation_id: UUID
    token_generation: int
    canonical_phone: str
    verified: bool
    unconsumed: bool

    def __post_init__(self) -> None:
        _require_uuid("challenge_id", self.challenge_id)
        _require_uuid("invitation_id", self.invitation_id)
        _require_positive_integer("token_generation", self.token_generation)
        _require_canonical_phone(self.canonical_phone)
        if not isinstance(self.verified, bool) or not isinstance(
            self.unconsumed, bool
        ):
            raise TypeError("challenge state must use booleans")


@dataclass(frozen=True, slots=True)
class InvitationLockTarget:
    kind: InvitationLockKind
    resource_id: str

    def __post_init__(self) -> None:
        if not isinstance(self.kind, InvitationLockKind):
            raise TypeError("kind must be an InvitationLockKind")
        if not isinstance(self.resource_id, str) or not self.resource_id:
            raise ValueError("lock resource_id must be non-empty")


@dataclass(frozen=True, slots=True)
class InvitationAcceptanceLockPlan:
    """D47 global order: user, invitations, tenants, guards, challenge/member."""

    targets: tuple[InvitationLockTarget, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.targets, tuple) or not all(
            isinstance(target, InvitationLockTarget) for target in self.targets
        ):
            raise TypeError("targets must be immutable InvitationLockTargets")
        kinds = tuple(target.kind for target in self.targets)
        rank = {
            InvitationLockKind.PHONE_IDENTITY: 0,
            InvitationLockKind.INVITATION: 1,
            InvitationLockKind.TENANT: 2,
            InvitationLockKind.MEMBER_SEAT_GUARD: 3,
            InvitationLockKind.CHALLENGE: 4,
            InvitationLockKind.MEMBERSHIP: 5,
        }
        if tuple(rank[kind] for kind in kinds) != tuple(
            sorted(rank[kind] for kind in kinds)
        ):
            raise ValueError("invitation acceptance lock order is invalid")


@dataclass(frozen=True, slots=True)
class InvitationTransition:
    aggregate: PhoneInvitationAggregate
    primary_invitation_id: UUID
    seat_projections: tuple[TenantSeatProjection, ...] = ()
    issued_token: Optional[IssuedInvitationToken] = None
    lock_plan: Optional[InvitationAcceptanceLockPlan] = None
    membership_created: bool = False
    challenge_consumed: bool = False
    converted_reservations: int = 0
    released_reservations: int = 0
    invalidated_invitation_ids: tuple[UUID, ...] = ()
    idempotent: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.aggregate, PhoneInvitationAggregate):
            raise TypeError("aggregate must be a PhoneInvitationAggregate")
        _require_uuid("primary_invitation_id", self.primary_invitation_id)
        if not isinstance(self.seat_projections, tuple) or not all(
            isinstance(projection, TenantSeatProjection)
            for projection in self.seat_projections
        ):
            raise TypeError("seat_projections must be immutable projections")
        if self.issued_token is not None and not isinstance(
            self.issued_token, IssuedInvitationToken
        ):
            raise TypeError("issued_token must be an IssuedInvitationToken or None")
        if self.lock_plan is not None and not isinstance(
            self.lock_plan, InvitationAcceptanceLockPlan
        ):
            raise TypeError("lock_plan must be an InvitationAcceptanceLockPlan")
        for name in ("membership_created", "challenge_consumed", "idempotent"):
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")
        _require_non_negative_integer(
            "converted_reservations", self.converted_reservations
        )
        _require_non_negative_integer(
            "released_reservations", self.released_reservations
        )
        if not isinstance(self.invalidated_invitation_ids, tuple) or not all(
            isinstance(invitation_id, UUID)
            for invitation_id in self.invalidated_invitation_ids
        ):
            raise TypeError("invalidated invitation IDs must be immutable UUIDs")

    @property
    def primary_invitation(self) -> InvitationRecord:
        return _find_invitation(self.aggregate, self.primary_invitation_id)


def create_or_rotate_invitation(
    aggregate: PhoneInvitationAggregate,
    *,
    tenant_id: UUID,
    new_invitation_id: UUID,
    role: InvitationRole,
    tenant_allows_invitations: bool,
    seat_snapshot: TenantSeatSnapshot,
    database_now: datetime,
    action_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
    expected_invitation_revision: Optional[int],
) -> InvitationTransition:
    """Create one reservation or rotate the existing tenant/phone token."""

    _require_aggregate(aggregate)
    retry = _action_retry(
        aggregate,
        kind=InvitationActionKind.CREATE_OR_ROTATE,
        action_id=action_id,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    if retry is not None:
        return retry
    _require_uuid("tenant_id", tenant_id)
    _require_uuid("new_invitation_id", new_invitation_id)
    if not isinstance(role, InvitationRole):
        raise TypeError("role must be an InvitationRole")
    _require_gate("tenant_allows_invitations", tenant_allows_invitations)
    if not tenant_allows_invitations:
        raise InvitationStateError("INVITATION_TENANT_INELIGIBLE")
    now = _normalize_aware_datetime("database_now", database_now)
    _require_seat_snapshot(seat_snapshot, tenant_id=tenant_id, database_now=now)
    if aggregate.user_status is CoordinatingUserStatus.DISABLED:
        raise InvitationStateError("INVITATION_IDENTITY_INELIGIBLE")
    if aggregate.membership is not None:
        raise InvitationStateError("PHONE_MEMBERSHIP_ALREADY_CLAIMED")

    invitations = list(aggregate.invitations)
    pending = _pending_for_tenant(aggregate, tenant_id)
    expired_during_create: list[UUID] = []
    expired_revision_verified = False
    if pending is not None and pending.expires_at <= now:
        _require_expected_revision(pending, expected_invitation_revision)
        expired_revision_verified = True
        invitations = [
            _terminalize(
                invitation,
                status=InvitationStatus.EXPIRED,
                action_id=action_id,
                database_now=now,
            )
            if invitation.invitation_id == pending.invitation_id
            else invitation
            for invitation in invitations
        ]
        expired_during_create.append(pending.invitation_id)
        pending = None

    if pending is not None:
        _require_expected_revision(pending, expected_invitation_revision)
        if pending.role is not role:
            raise InvitationStateError("INVITATION_ROLE_IMMUTABLE")
        _require_target_reservation_counted(seat_snapshot, count=1)
        _require_valid_occupied_count(seat_snapshot)
        issued = rotate_invitation_token(pending.token, database_now=now)
        invitations = [
            replace(
                invitation,
                token=issued.persisted,
                revision=invitation.revision + 1,
            )
            if invitation.invitation_id == pending.invitation_id
            else invitation
            for invitation in invitations
        ]
        primary_id = pending.invitation_id
        projection = _seat_projection(seat_snapshot)
    else:
        if (
            expected_invitation_revision is not None
            and not expired_revision_verified
        ):
            raise InvitationStateError("STALE_INVITATION_REVISION")
        if any(
            invitation.invitation_id == new_invitation_id
            for invitation in invitations
        ):
            raise InvitationStateError("INVITATION_ID_CONFLICT")
        if seat_snapshot.occupied_seats + 1 > CORE_MEMBER_SEAT_CAP:
            raise InvitationStateError("MEMBER_SEAT_LIMIT_EXCEEDED")
        issued = issue_invitation_token(database_now=now)
        record = InvitationRecord(
            invitation_id=new_invitation_id,
            tenant_id=tenant_id,
            canonical_phone=aggregate.canonical_phone,
            role=role,
            status=InvitationStatus.PENDING,
            token=issued.persisted,
            coordinating_user_id=aggregate.coordinating_user_id,
        )
        invitations.append(record)
        primary_id = new_invitation_id
        projection = _seat_projection(seat_snapshot, pending_delta=1)

    receipt = InvitationActionReceipt(
        action_id=action_id,
        kind=InvitationActionKind.CREATE_OR_ROTATE,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        primary_invitation_id=primary_id,
    )
    result = replace(
        aggregate,
        invitations=_sorted_invitations(invitations),
        action_receipts=aggregate.action_receipts + (receipt,),
    )
    return InvitationTransition(
        aggregate=result,
        primary_invitation_id=primary_id,
        seat_projections=(projection,),
        issued_token=issued,
        released_reservations=len(expired_during_create),
        invalidated_invitation_ids=tuple(expired_during_create),
    )


def revoke_invitation(
    aggregate: PhoneInvitationAggregate,
    *,
    invitation_id: UUID,
    seat_snapshot: TenantSeatSnapshot,
    database_now: datetime,
    action_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
    expected_invitation_revision: int,
) -> InvitationTransition:
    """Irreversibly revoke one unexpired pending invitation and release its seat."""

    _require_aggregate(aggregate)
    retry = _action_retry(
        aggregate,
        kind=InvitationActionKind.REVOKE,
        action_id=action_id,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    if retry is not None:
        return retry
    invitation = _require_pending_invitation(aggregate, invitation_id)
    _require_expected_revision(invitation, expected_invitation_revision)
    now = _normalize_aware_datetime("database_now", database_now)
    if invitation.expires_at <= now:
        raise InvitationStateError("INVITATION_EXPIRED")
    _require_seat_snapshot(
        seat_snapshot,
        tenant_id=invitation.tenant_id,
        database_now=now,
    )
    _require_target_reservation_counted(seat_snapshot, count=1)
    projection = _seat_projection(seat_snapshot, pending_delta=-1)
    terminal = _terminalize(
        invitation,
        status=InvitationStatus.REVOKED,
        action_id=action_id,
        database_now=now,
    )
    receipt = InvitationActionReceipt(
        action_id=action_id,
        kind=InvitationActionKind.REVOKE,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        primary_invitation_id=invitation_id,
    )
    result = replace(
        aggregate,
        invitations=_replace_invitation(aggregate, terminal),
        action_receipts=aggregate.action_receipts + (receipt,),
    )
    return InvitationTransition(
        aggregate=result,
        primary_invitation_id=invitation_id,
        seat_projections=(projection,),
        released_reservations=1,
        invalidated_invitation_ids=(invitation_id,),
    )


def expire_invitation(
    aggregate: PhoneInvitationAggregate,
    *,
    invitation_id: UUID,
    seat_snapshot: TenantSeatSnapshot,
    database_now: datetime,
    action_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
    expected_invitation_revision: int,
) -> InvitationTransition:
    """Mark due pending state terminal; realtime quota already excludes it."""

    _require_aggregate(aggregate)
    retry = _action_retry(
        aggregate,
        kind=InvitationActionKind.EXPIRE,
        action_id=action_id,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    if retry is not None:
        return retry
    invitation = _require_pending_invitation(aggregate, invitation_id)
    _require_expected_revision(invitation, expected_invitation_revision)
    now = _normalize_aware_datetime("database_now", database_now)
    if invitation.expires_at > now:
        raise InvitationStateError("INVITATION_NOT_EXPIRED")
    _require_seat_snapshot(
        seat_snapshot,
        tenant_id=invitation.tenant_id,
        database_now=now,
    )
    projection = _seat_projection(seat_snapshot)
    terminal = _terminalize(
        invitation,
        status=InvitationStatus.EXPIRED,
        action_id=action_id,
        database_now=now,
    )
    receipt = InvitationActionReceipt(
        action_id=action_id,
        kind=InvitationActionKind.EXPIRE,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        primary_invitation_id=invitation_id,
    )
    result = replace(
        aggregate,
        invitations=_replace_invitation(aggregate, terminal),
        action_receipts=aggregate.action_receipts + (receipt,),
    )
    return InvitationTransition(
        aggregate=result,
        primary_invitation_id=invitation_id,
        seat_projections=(projection,),
        released_reservations=1,
        invalidated_invitation_ids=(invitation_id,),
    )


def accept_invitation(
    aggregate: PhoneInvitationAggregate,
    *,
    invitation_id: UUID,
    submitted_token: object,
    submitted_generation: object,
    challenge: AcceptanceChallengeProof,
    membership_id: UUID,
    winning_tenant_join_allowed: bool,
    seat_snapshots: tuple[TenantSeatSnapshot, ...],
    database_now: datetime,
    action_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
    expected_invitation_revision: int,
) -> InvitationTransition:
    """Atomically accept one invitation and supersede every losing tenant."""

    _require_aggregate(aggregate)
    retry = _action_retry(
        aggregate,
        kind=InvitationActionKind.ACCEPT,
        action_id=action_id,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    if retry is not None:
        return retry
    _require_uuid("membership_id", membership_id)
    _require_gate("winning_tenant_join_allowed", winning_tenant_join_allowed)
    if aggregate.membership is not None:
        raise InvitationStateError("PHONE_MEMBERSHIP_ALREADY_CLAIMED")
    if aggregate.user_status is CoordinatingUserStatus.DISABLED:
        raise InvitationStateError("INVITATION_IDENTITY_INELIGIBLE")
    invitation = _require_pending_invitation(aggregate, invitation_id)
    _require_expected_revision(invitation, expected_invitation_revision)
    now = _normalize_aware_datetime("database_now", database_now)
    if invitation.expires_at <= now:
        raise InvitationStateError("INVITATION_EXPIRED")
    if not winning_tenant_join_allowed:
        raise InvitationStateError("INVITATION_TENANT_INELIGIBLE")
    _require_acceptance_challenge(challenge, invitation)
    if not verify_invitation_token(
        submitted_token=submitted_token,
        submitted_generation=submitted_generation,
        current=invitation.token,
        database_now=now,
    ):
        raise InvitationStateError("INVITATION_CREDENTIAL_INVALID")

    pending = tuple(
        record
        for record in aggregate.invitations
        if record.status is InvitationStatus.PENDING
    )
    affected_tenants = tuple(
        sorted({record.tenant_id for record in pending}, key=str)
    )
    snapshots = _seat_snapshot_map(
        seat_snapshots,
        expected_tenants=affected_tenants,
        database_now=now,
    )
    unexpired_per_tenant: dict[UUID, int] = {}
    for record in pending:
        if record.expires_at > now:
            unexpired_per_tenant[record.tenant_id] = (
                unexpired_per_tenant.get(record.tenant_id, 0) + 1
            )
    for tenant_id, count in unexpired_per_tenant.items():
        _require_target_reservation_counted(snapshots[tenant_id], count=count)
    winner_snapshot = snapshots[invitation.tenant_id]
    _require_valid_occupied_count(winner_snapshot)

    projections: list[TenantSeatProjection] = []
    for tenant_id in affected_tenants:
        snapshot = snapshots[tenant_id]
        unexpired_count = unexpired_per_tenant.get(tenant_id, 0)
        if tenant_id == invitation.tenant_id:
            projection = _seat_projection(
                snapshot,
                active_delta=1,
                pending_delta=-1,
            )
            if projection.occupied_after > CORE_MEMBER_SEAT_CAP:
                raise InvitationStateError("MEMBER_SEAT_LIMIT_EXCEEDED")
        else:
            projection = _seat_projection(
                snapshot,
                pending_delta=-unexpired_count,
            )
        projections.append(projection)

    membership = MembershipClaim(
        membership_id=membership_id,
        tenant_id=invitation.tenant_id,
        user_id=aggregate.coordinating_user_id,
        canonical_phone=aggregate.canonical_phone,
        role=invitation.role,
        source_invitation_id=invitation.invitation_id,
        accepted_action_id=action_id,
    )
    transitioned: list[InvitationRecord] = []
    invalidated: list[UUID] = []
    released = 0
    for record in aggregate.invitations:
        if record.status is not InvitationStatus.PENDING:
            transitioned.append(record)
        elif record.invitation_id == invitation.invitation_id:
            transitioned.append(
                _terminalize(
                    record,
                    status=InvitationStatus.ACCEPTED,
                    action_id=action_id,
                    database_now=now,
                    accepted_membership_id=membership_id,
                )
            )
        elif record.expires_at <= now:
            transitioned.append(
                _terminalize(
                    record,
                    status=InvitationStatus.EXPIRED,
                    action_id=action_id,
                    database_now=now,
                )
            )
            invalidated.append(record.invitation_id)
            released += 1
        else:
            transitioned.append(
                _terminalize(
                    record,
                    status=InvitationStatus.SUPERSEDED,
                    action_id=action_id,
                    database_now=now,
                )
            )
            invalidated.append(record.invitation_id)
            released += 1

    receipt = InvitationActionReceipt(
        action_id=action_id,
        kind=InvitationActionKind.ACCEPT,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
        primary_invitation_id=invitation_id,
        result_membership_id=membership_id,
    )
    result = replace(
        aggregate,
        user_status=CoordinatingUserStatus.ACTIVE,
        invitations=_sorted_invitations(transitioned),
        membership=membership,
        action_receipts=aggregate.action_receipts + (receipt,),
    )
    lock_plan = _acceptance_lock_plan(
        aggregate=aggregate,
        pending=pending,
        affected_tenants=affected_tenants,
        challenge_id=challenge.challenge_id,
        membership_id=membership_id,
    )
    return InvitationTransition(
        aggregate=result,
        primary_invitation_id=invitation_id,
        seat_projections=tuple(projections),
        lock_plan=lock_plan,
        membership_created=True,
        challenge_consumed=True,
        converted_reservations=1,
        released_reservations=released,
        invalidated_invitation_ids=tuple(sorted(invalidated, key=str)),
    )


def _action_retry(
    aggregate: PhoneInvitationAggregate,
    *,
    kind: InvitationActionKind,
    action_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
) -> Optional[InvitationTransition]:
    _require_uuid("action_id", action_id)
    _require_idempotency_key(idempotency_key)
    _require_request_digest(request_digest)
    matches = [
        receipt
        for receipt in aggregate.action_receipts
        if receipt.action_id == action_id
        or receipt.idempotency_key == idempotency_key
    ]
    if not matches:
        return None
    if len(matches) != 1:
        raise InvitationStateError("INVITATION_IDEMPOTENCY_CONFLICT")
    receipt = matches[0]
    if (
        receipt.kind is not kind
        or receipt.idempotency_key != idempotency_key
        or receipt.request_digest != request_digest
    ):
        raise InvitationStateError("INVITATION_IDEMPOTENCY_CONFLICT")
    return InvitationTransition(
        aggregate=aggregate,
        primary_invitation_id=receipt.primary_invitation_id,
        membership_created=False,
        challenge_consumed=False,
        idempotent=True,
    )


def _acceptance_lock_plan(
    *,
    aggregate: PhoneInvitationAggregate,
    pending: tuple[InvitationRecord, ...],
    affected_tenants: tuple[UUID, ...],
    challenge_id: UUID,
    membership_id: UUID,
) -> InvitationAcceptanceLockPlan:
    targets = [
        InvitationLockTarget(
            InvitationLockKind.PHONE_IDENTITY,
            str(aggregate.coordinating_user_id),
        )
    ]
    targets.extend(
        InvitationLockTarget(InvitationLockKind.INVITATION, str(record.invitation_id))
        for record in sorted(pending, key=lambda item: str(item.invitation_id))
    )
    targets.extend(
        InvitationLockTarget(InvitationLockKind.TENANT, str(tenant_id))
        for tenant_id in affected_tenants
    )
    targets.extend(
        InvitationLockTarget(
            InvitationLockKind.MEMBER_SEAT_GUARD,
            f"{tenant_id}:member_seats",
        )
        for tenant_id in affected_tenants
    )
    targets.extend(
        (
            InvitationLockTarget(
                InvitationLockKind.CHALLENGE, str(challenge_id)
            ),
            InvitationLockTarget(
                InvitationLockKind.MEMBERSHIP, str(membership_id)
            ),
        )
    )
    return InvitationAcceptanceLockPlan(tuple(targets))


def _terminalize(
    invitation: InvitationRecord,
    *,
    status: InvitationStatus,
    action_id: UUID,
    database_now: datetime,
    accepted_membership_id: Optional[UUID] = None,
) -> InvitationRecord:
    if status is InvitationStatus.PENDING:
        raise ValueError("terminal status is required")
    return replace(
        invitation,
        status=status,
        coordinating_user_id=None,
        revision=invitation.revision + 1,
        terminal_at=database_now,
        terminal_action_id=action_id,
        accepted_membership_id=accepted_membership_id,
    )


def _seat_projection(
    snapshot: TenantSeatSnapshot,
    *,
    active_delta: int = 0,
    pending_delta: int = 0,
) -> TenantSeatProjection:
    active_after = snapshot.active_memberships + active_delta
    pending_after = snapshot.unexpired_pending_invitations + pending_delta
    if active_after < 0 or pending_after < 0:
        raise InvitationStateError("SEAT_SNAPSHOT_INCONSISTENT")
    return TenantSeatProjection(
        tenant_id=snapshot.tenant_id,
        active_memberships_before=snapshot.active_memberships,
        pending_invitations_before=snapshot.unexpired_pending_invitations,
        active_memberships_after=active_after,
        pending_invitations_after=pending_after,
        guard_revision=snapshot.guard_revision,
    )


def _seat_snapshot_map(
    snapshots: tuple[TenantSeatSnapshot, ...],
    *,
    expected_tenants: tuple[UUID, ...],
    database_now: datetime,
) -> dict[UUID, TenantSeatSnapshot]:
    if not isinstance(snapshots, tuple) or not all(
        isinstance(snapshot, TenantSeatSnapshot) for snapshot in snapshots
    ):
        raise TypeError("seat_snapshots must be immutable TenantSeatSnapshots")
    mapped = {snapshot.tenant_id: snapshot for snapshot in snapshots}
    if len(mapped) != len(snapshots) or set(mapped) != set(expected_tenants):
        raise InvitationStateError("SEAT_SNAPSHOT_INCOMPLETE")
    for tenant_id, snapshot in mapped.items():
        _require_seat_snapshot(
            snapshot,
            tenant_id=tenant_id,
            database_now=database_now,
        )
    return mapped


def _require_seat_snapshot(
    snapshot: TenantSeatSnapshot,
    *,
    tenant_id: UUID,
    database_now: datetime,
) -> None:
    if not isinstance(snapshot, TenantSeatSnapshot):
        raise TypeError("seat_snapshot must be a TenantSeatSnapshot")
    if snapshot.tenant_id != tenant_id or snapshot.counted_at != database_now:
        raise InvitationStateError("SEAT_SNAPSHOT_STALE")


def _require_target_reservation_counted(
    snapshot: TenantSeatSnapshot,
    *,
    count: int,
) -> None:
    if snapshot.unexpired_pending_invitations < count:
        raise InvitationStateError("SEAT_SNAPSHOT_INCONSISTENT")


def _require_valid_occupied_count(snapshot: TenantSeatSnapshot) -> None:
    if snapshot.occupied_seats > CORE_MEMBER_SEAT_CAP:
        raise InvitationStateError("MEMBER_SEAT_LIMIT_EXCEEDED")


def _require_acceptance_challenge(
    challenge: AcceptanceChallengeProof,
    invitation: InvitationRecord,
) -> None:
    if not isinstance(challenge, AcceptanceChallengeProof):
        raise TypeError("challenge must be AcceptanceChallengeProof")
    if (
        challenge.invitation_id != invitation.invitation_id
        or challenge.token_generation != invitation.token_generation
        or challenge.canonical_phone != invitation.canonical_phone
        or not challenge.verified
        or not challenge.unconsumed
    ):
        raise InvitationStateError("INVITATION_CREDENTIAL_INVALID")


def _pending_for_tenant(
    aggregate: PhoneInvitationAggregate,
    tenant_id: UUID,
) -> Optional[InvitationRecord]:
    return next(
        (
            invitation
            for invitation in aggregate.invitations
            if invitation.tenant_id == tenant_id
            and invitation.status is InvitationStatus.PENDING
        ),
        None,
    )


def _require_pending_invitation(
    aggregate: PhoneInvitationAggregate,
    invitation_id: UUID,
) -> InvitationRecord:
    invitation = _find_invitation(aggregate, invitation_id)
    if invitation.status is not InvitationStatus.PENDING:
        raise InvitationStateError("INVITATION_NOT_PENDING")
    return invitation


def _find_invitation(
    aggregate: PhoneInvitationAggregate,
    invitation_id: UUID,
) -> InvitationRecord:
    _require_uuid("invitation_id", invitation_id)
    invitation = next(
        (
            record
            for record in aggregate.invitations
            if record.invitation_id == invitation_id
        ),
        None,
    )
    if invitation is None:
        raise InvitationStateError("INVITATION_NOT_AVAILABLE")
    return invitation


def _replace_invitation(
    aggregate: PhoneInvitationAggregate,
    replacement: InvitationRecord,
) -> tuple[InvitationRecord, ...]:
    return _sorted_invitations(
        replacement if record.invitation_id == replacement.invitation_id else record
        for record in aggregate.invitations
    )


def _sorted_invitations(
    invitations,
) -> tuple[InvitationRecord, ...]:
    return tuple(sorted(invitations, key=lambda invitation: str(invitation.invitation_id)))


def _require_expected_revision(
    invitation: InvitationRecord,
    expected_revision: object,
) -> None:
    if (
        isinstance(expected_revision, bool)
        or not isinstance(expected_revision, int)
        or expected_revision < 1
        or invitation.revision != expected_revision
    ):
        raise InvitationStateError("STALE_INVITATION_REVISION")


def _require_aggregate(aggregate: PhoneInvitationAggregate) -> None:
    if not isinstance(aggregate, PhoneInvitationAggregate):
        raise TypeError("aggregate must be a PhoneInvitationAggregate")


def _require_gate(name: str, value: object) -> None:
    if not isinstance(value, bool):
        raise TypeError(f"{name} must be a boolean")


def _require_uuid(name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{name} must be a UUID")


def _require_canonical_phone(value: object) -> None:
    if not isinstance(value, str):
        raise ValueError("canonical_phone is invalid")
    try:
        normalized = normalize_tenant_phone(value)
    except PhoneNormalizationError:
        raise ValueError("canonical_phone is invalid") from None
    if normalized != value:
        raise ValueError("canonical_phone must use canonical E.164")


def _require_positive_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_non_negative_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_idempotency_key(value: object) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 128:
        raise ValueError("idempotency_key must be non-empty and bounded")


def _require_request_digest(value: object) -> None:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError("request_digest must be a 32-byte digest")


def _normalize_aware_datetime(name: str, value: object) -> datetime:
    _require_aware_datetime(name, value)
    return value.astimezone(timezone.utc)


def _require_aware_datetime(name: str, value: object) -> None:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise InvitationStateError("INVITATION_TIME_MUST_BE_TIMEZONE_AWARE")
