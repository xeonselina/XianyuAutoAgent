"""Caller-transactional persistence for tenant invitations.

The service deliberately owns no transaction boundary and performs no provider
I/O.  Every mutation follows D47's global order::

    canonical user -> invitations (UUID) -> affected tenants (UUID)
    -> member-seat guards (same tenant order) -> challenges -> memberships

The member-seat guard protects a realtime recount; it is not a cached counter.
Consequently a resend neither allocates nor releases a second seat, and every
terminal transition becomes visible to the next recount in the same commit.
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from inventory_control.crypto.root_key import RootKey
from inventory_control.models.foundation import Tenant
from inventory_control.models.identity import TenantMembership, User
from inventory_control.models.invitations import TenantInvitation
from inventory_control.models.sms import SmsChallenge
from inventory_control.models.subscriptions import MemberSeatGuard
from inventory_control.sms import (
    CanonicalActionPayload,
    CanonicalSmsPhone,
    SmsChallengeContext,
    SmsChallengeService,
    SmsPurpose,
)
from inventory_control.subscriptions.seats import CORE_MEMBER_SEAT_CAP

from .state import InvitationRole
from .tokens import (
    INVITATION_DEFAULT_LIFETIME,
    InvitationToken,
    InvitationTokenError,
)


INVITATION_PERSISTENCE_LOCK_ORDER = (
    "canonical_user",
    "invitations_by_uuid",
    "affected_tenants_by_uuid",
    "member_seat_guards_by_tenant_uuid",
    "challenges_by_uuid",
    "memberships_by_tenant_uuid_and_uuid",
)

_TERMINAL_REVOKED = "revoked_by_tenant_admin"
_TERMINAL_EXPIRED = "invitation_expired"
_TERMINAL_SUPERSEDED = "membership_claimed_elsewhere"


class InvitationPersistenceError(RuntimeError):
    """Stable, non-enumerating invitation rejection."""

    code = "INVITATION_REJECTED"
    public_message = "the invitation request could not be completed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class InvitationTransactionError(InvitationPersistenceError):
    code = "INVITATION_TRANSACTION_INVALID"


class InvitationConflictError(InvitationPersistenceError):
    code = "INVITATION_CONFLICT"


class InvitationIdentityError(InvitationPersistenceError):
    code = "INVITATION_IDENTITY_INELIGIBLE"


class InvitationTenantGateError(InvitationPersistenceError):
    code = "INVITATION_TENANT_INELIGIBLE"


class InvitationSeatLimitError(InvitationPersistenceError):
    code = "MEMBER_SEAT_LIMIT_EXCEEDED"


class InvitationCredentialError(InvitationPersistenceError):
    code = "INVITATION_CREDENTIAL_INVALID"


class InvitationChallengeRejectedError(InvitationCredentialError):
    """The submitted OTP was not consumable in the protected transaction."""


class InvitationStaleRevisionError(InvitationPersistenceError):
    code = "STALE_INVITATION_REVISION"


@dataclass(frozen=True, slots=True)
class InvitationJoinGateFacts:
    """Current join decision returned from the trusted gate reader."""

    tenant_uuid: UUID
    access_version: int
    join_allowed: bool

    def __post_init__(self) -> None:
        _uuid(self.tenant_uuid, "tenant_uuid")
        _positive(self.access_version, "access_version")
        if not isinstance(self.join_allowed, bool):
            raise TypeError("join_allowed must be a bool")


class InvitationJoinGateCurrentRead(Protocol):
    """Re-read the winning tenant gate in the caller-owned transaction.

    Implementations receive the already locked tenant and caller Session.  They
    must not commit, roll back, or stage writes.
    """

    def __call__(
        self,
        session: Session,
        *,
        tenant: Tenant,
        database_now: datetime,
    ) -> InvitationJoinGateFacts: ...


DatabaseClock = Callable[[Session], datetime]


@dataclass(frozen=True, slots=True)
class AdminInvitationPermissionProof:
    """Internal-only result of an exact D48 Admin-invitation verification."""

    tenant_uuid: UUID
    actor_user_uuid: UUID
    actor_session_uuid: UUID
    invitation_uuid: UUID
    target_phone_e164: str = field(repr=False)
    expected_tenant_access_version: int

    def __post_init__(self) -> None:
        for name, value in (
            ("tenant_uuid", self.tenant_uuid),
            ("actor_user_uuid", self.actor_user_uuid),
            ("actor_session_uuid", self.actor_session_uuid),
            ("invitation_uuid", self.invitation_uuid),
        ):
            _uuid(value, name)
        CanonicalSmsPhone.from_input(self.target_phone_e164)
        _positive(
            self.expected_tenant_access_version,
            "expected_tenant_access_version",
        )


class AdminInvitationAuthorizer(Protocol):
    """Verify D48 only after invitation ownership and seat locks are held."""

    def __call__(
        self, session: Session, *, database_now: datetime
    ) -> AdminInvitationPermissionProof: ...


@dataclass(frozen=True, slots=True, repr=False)
class InvitationChallengeSubmission:
    challenge_uuid: UUID
    plaintext_code: object = field(repr=False)
    root_key: RootKey = field(repr=False)
    actor_session_uuid: UUID | None = None

    def __post_init__(self) -> None:
        _uuid(self.challenge_uuid, "challenge_uuid")
        if self.actor_session_uuid is not None:
            _uuid(self.actor_session_uuid, "actor_session_uuid")
        if not isinstance(self.root_key, RootKey):
            raise TypeError("root_key must be a RootKey")


@dataclass(frozen=True, slots=True, repr=False)
class InvitationIssueResult:
    invitation_uuid: UUID
    coordinating_user_uuid: UUID
    tenant_uuid: UUID
    status: str
    role: InvitationRole
    token_generation: int
    expires_at: datetime
    row_version: int
    token: InvitationToken = field(repr=False)
    created: bool
    rotated: bool
    idempotent: bool


@dataclass(frozen=True, slots=True)
class InvitationTerminalResult:
    invitation_uuid: UUID
    tenant_uuid: UUID
    status: str
    row_version: int
    idempotent: bool


@dataclass(frozen=True, slots=True)
class InvitationAcceptanceResult:
    invitation_uuid: UUID
    membership_uuid: UUID
    tenant_uuid: UUID
    user_uuid: UUID
    status: str
    membership_status: str
    invitation_row_version: int
    superseded_count: int
    expired_count: int
    created: bool
    idempotent: bool


class InvitationPersistenceService:
    """Persist invitation transitions inside one clean caller transaction."""

    def __init__(
        self,
        *,
        join_gate_current_read: InvitationJoinGateCurrentRead,
        sms_challenge_service: SmsChallengeService | None = None,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not callable(join_gate_current_read):
            raise TypeError("join_gate_current_read must be callable")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        if sms_challenge_service is not None and not isinstance(
            sms_challenge_service, SmsChallengeService
        ):
            raise TypeError("sms_challenge_service must be an SmsChallengeService")
        self._join_gate_current_read = join_gate_current_read
        self._sms = sms_challenge_service or SmsChallengeService()
        self._database_clock = database_clock or _read_database_utc_now

    def create_or_resend(
        self,
        session: Session,
        *,
        tenant_uuid: str | UUID,
        raw_phone: str,
        role: str | InvitationRole,
        proposed_token: InvitationToken,
        proposed_invitation_uuid: str | UUID,
        proposed_user_uuid: str | UUID,
        expected_tenant_access_version: int,
        expected_invitation_row_version: int | None,
        admin_challenge: InvitationChallengeSubmission | None = None,
        admin_actor_phone: CanonicalSmsPhone | None = None,
        admin_authorizer: AdminInvitationAuthorizer | None = None,
    ) -> InvitationIssueResult:
        """Create one seven-day reservation or rotate its current token.

        ``proposed_token`` is generated by the application immediately before
        entering this service and is reused across a deadlock retry.  Only its
        SHA-256 digest is persisted.
        """

        self._prepare(session)
        tenant_id = str(_uuid(tenant_uuid, "tenant_uuid"))
        invitation_id = str(
            _uuid(proposed_invitation_uuid, "proposed_invitation_uuid")
        )
        user_id = str(_uuid(proposed_user_uuid, "proposed_user_uuid"))
        phone = CanonicalSmsPhone.from_input(raw_phone)
        selected_role = _role(role)
        token = _token(proposed_token)
        tenant_access_version = _positive(
            expected_tenant_access_version,
            "expected_tenant_access_version",
        )
        expected_revision = _optional_positive(
            expected_invitation_row_version,
            "expected_invitation_row_version",
        )
        if admin_authorizer is not None and not callable(admin_authorizer):
            raise TypeError("admin_authorizer must be callable")
        if admin_authorizer is not None and admin_challenge is not None:
            raise InvitationCredentialError()

        user = self._lock_or_create_user(
            session,
            phone=phone,
            proposed_user_uuid=user_id,
        )
        invitations = self._lock_phone_invitations(session, phone.e164)
        pending = _pending_for_tenant(invitations, tenant_id)
        tenant = self._lock_tenants(session, (tenant_id,))[0]
        self._lock_guards(session, (tenant_id,))

        challenge_digests: set[bytes] = set()
        if pending is not None:
            challenge_digests.add(_accept_payload_digest(pending))
        challenge_ids = (
            (str(admin_challenge.challenge_uuid),)
            if admin_challenge is not None
            else ()
        )
        challenge_phones = {phone.e164}
        if admin_actor_phone is not None:
            if not isinstance(admin_actor_phone, CanonicalSmsPhone):
                raise TypeError("admin_actor_phone must be a CanonicalSmsPhone")
            challenge_phones.add(admin_actor_phone.e164)
        challenges = self._lock_challenges(
            session,
            phones=tuple(sorted(challenge_phones)),
            challenge_ids=challenge_ids,
            action_digests=challenge_digests,
        )
        memberships = self._lock_user_memberships(session, user.id)
        now = self._now(session)
        self._require_user_available(user, memberships)

        replay = _issue_replay(
            invitations,
            invitation_id=invitation_id,
            tenant_id=tenant_id,
            user_id=user.id,
            role=selected_role,
            token=token,
            expected_revision=expected_revision,
        )
        if replay is not None:
            return _issue_result(
                replay,
                user=user,
                token=token,
                created=False,
                rotated=replay.token_generation > 1,
                idempotent=True,
            )

        self._require_join_gate(
            session,
            tenant=tenant,
            expected_access_version=tenant_access_version,
            database_now=now,
        )
        # The trusted gate reader may itself wait while locking lifecycle rows.
        # Refresh server UTC only after that wait and re-read the already locked
        # gate facts so expiry and token decisions never use a pre-wait clock.
        now = self._now(session)
        self._require_join_gate(
            session,
            tenant=tenant,
            expected_access_version=tenant_access_version,
            database_now=now,
        )
        active_count, pending_count = self._seat_usage(
            session,
            tenant_id=tenant_id,
            database_now=now,
        )
        if active_count + pending_count > CORE_MEMBER_SEAT_CAP:
            raise InvitationSeatLimitError()

        if pending is not None:
            if expected_revision is None or pending.row_version != expected_revision:
                raise InvitationStaleRevisionError()
            if pending.role_key != selected_role.value:
                raise InvitationConflictError()
            if _as_utc(pending.expires_at) > now:
                if pending_count < 1:
                    raise InvitationConflictError()
                old_digest = _accept_payload_digest(pending)
                pending.token_hash = token.digest_sha256
                pending.token_generation += 1
                pending.expires_at = now + INVITATION_DEFAULT_LIFETIME
                pending.row_version += 1
                pending.updated_at = now
                _invalidate_matching_challenges(
                    challenges,
                    digests={old_digest},
                    database_now=now,
                    reason="invitation_token_rotated",
                )
                session.flush()
                return _issue_result(
                    pending,
                    user=user,
                    token=token,
                    created=False,
                    rotated=True,
                    idempotent=False,
                )

            old_digest = _accept_payload_digest(pending)
            _terminalize(
                pending,
                status="expired",
                reason=_TERMINAL_EXPIRED,
                database_now=now,
            )
            _invalidate_matching_challenges(
                challenges,
                digests={old_digest},
                database_now=now,
                reason="invitation_expired",
            )
        elif expected_revision is not None:
            raise InvitationStaleRevisionError()

        # An expired pending row was excluded by the realtime count, so both
        # the ordinary and replacement paths allocate exactly one new seat.
        if active_count + pending_count + 1 > CORE_MEMBER_SEAT_CAP:
            raise InvitationSeatLimitError()
        if selected_role is InvitationRole.ADMIN:
            if admin_authorizer is not None:
                proof = admin_authorizer(session, database_now=now)
                _require_admin_invitation_proof(
                    proof,
                    tenant_uuid=UUID(tenant_id),
                    invitation_uuid=UUID(invitation_id),
                    target_phone=phone,
                    expected_tenant_access_version=tenant_access_version,
                )
            else:
                if admin_challenge is None or admin_actor_phone is None:
                    raise InvitationCredentialError()
                expected_context = admin_invitation_challenge_context(
                    actor_phone=admin_actor_phone,
                    target_phone=phone,
                    tenant_uuid=UUID(tenant_id),
                    actor_session_uuid=admin_challenge.actor_session_uuid,
                    expected_tenant_access_version=tenant_access_version,
                )
                self._consume_challenge(
                    session,
                    challenges=challenges,
                    submission=admin_challenge,
                    expected_context=expected_context,
                    database_now=now,
                )

        row = TenantInvitation(
            id=invitation_id,
            tenant_id=tenant_id,
            user_id=user.id,
            phone_region_iso2="CN",
            phone_e164=phone.e164,
            phone_normalization_version=phone.normalization_version,
            role_key=selected_role.value,
            token_hash=token.digest_sha256,
            token_generation=1,
            status="pending",
            expires_at=now + INVITATION_DEFAULT_LIFETIME,
            row_version=1,
            created_at=now,
            updated_at=now,
        )
        try:
            session.add(row)
            session.flush()
        except IntegrityError:
            # The outer caller transaction is now unusable and must roll back;
            # translate without attempting a second, out-of-order read.
            raise InvitationConflictError() from None
        return _issue_result(
            row,
            user=user,
            token=token,
            created=True,
            rotated=False,
            idempotent=False,
        )

    def revoke(
        self,
        session: Session,
        *,
        invitation_uuid: str | UUID,
        expected_invitation_row_version: int,
    ) -> InvitationTerminalResult:
        return self._terminalize_pending(
            session,
            invitation_uuid=invitation_uuid,
            expected_invitation_row_version=expected_invitation_row_version,
            operation="revoke",
        )

    def expire(
        self,
        session: Session,
        *,
        invitation_uuid: str | UUID,
        expected_invitation_row_version: int,
    ) -> InvitationTerminalResult:
        return self._terminalize_pending(
            session,
            invitation_uuid=invitation_uuid,
            expected_invitation_row_version=expected_invitation_row_version,
            operation="expire",
        )

    def accept(
        self,
        session: Session,
        *,
        invitation_uuid: str | UUID,
        submitted_token: object,
        submitted_generation: int,
        expected_invitation_row_version: int,
        expected_winning_tenant_access_version: int,
        proposed_membership_uuid: str | UUID,
        challenge: InvitationChallengeSubmission,
    ) -> InvitationAcceptanceResult:
        """Consume the bound OTP, create membership, and close every loser."""

        self._prepare(session)
        invitation_id = str(_uuid(invitation_uuid, "invitation_uuid"))
        membership_id = str(
            _uuid(proposed_membership_uuid, "proposed_membership_uuid")
        )
        generation = _positive(submitted_generation, "submitted_generation")
        expected_revision = _positive(
            expected_invitation_row_version,
            "expected_invitation_row_version",
        )
        tenant_access_version = _positive(
            expected_winning_tenant_access_version,
            "expected_winning_tenant_access_version",
        )
        if not isinstance(challenge, InvitationChallengeSubmission):
            raise TypeError("challenge must be an InvitationChallengeSubmission")

        summary = session.execute(
            sa.select(TenantInvitation.phone_e164)
            .where(TenantInvitation.id == invitation_id)
        ).one_or_none()
        if summary is None:
            raise InvitationCredentialError()
        phone_value = summary.phone_e164
        user = self._lock_user_by_phone(session, phone_value)
        invitations = self._lock_phone_invitations(session, phone_value)
        target = _find_invitation(invitations, invitation_id)
        if target is None:
            raise InvitationCredentialError()

        pending = tuple(row for row in invitations if row.status == "pending")
        tenant_ids = tuple(
            sorted({row.tenant_id for row in pending} | {target.tenant_id})
        )
        tenants = self._lock_tenants(session, tenant_ids)
        self._lock_guards(session, tenant_ids)
        # Keep the target digest in the lock set after it becomes terminal so
        # an exact replay can prove the same consumed challenge rather than
        # trusting a caller-supplied challenge UUID.
        action_digests = {_accept_payload_digest(row) for row in pending}
        action_digests.add(
            _accept_payload_digest_from_values(
                invitation_uuid=target.id,
                token_generation=target.token_generation,
                invitation_row_version=expected_revision,
            )
        )
        challenges = self._lock_challenges(
            session,
            phones=(phone_value,),
            challenge_ids=(str(challenge.challenge_uuid),),
            action_digests=action_digests,
        )
        memberships = self._lock_user_memberships(session, user.id)
        now = self._now(session)

        try:
            token = InvitationToken(submitted_token)
        except InvitationTokenError:
            raise InvitationCredentialError() from None
        if (
            target.token_generation != generation
            or not hmac.compare_digest(
                token.digest_sha256,
                bytes(target.token_hash),
            )
        ):
            raise InvitationCredentialError()

        replay = _acceptance_replay(
            target=target,
            invitations=invitations,
            memberships=memberships,
            expected_revision=expected_revision,
            membership_id=membership_id,
            user=user,
            challenges=challenges,
            challenge_id=str(challenge.challenge_uuid),
        )
        if replay is not None:
            return replay

        if (
            target.status != "pending"
            or target.user_id != user.id
            or target.row_version != expected_revision
            or _as_utc(target.expires_at) <= now
        ):
            raise InvitationCredentialError()
        self._require_user_available(user, memberships)

        tenant_map = {row.id: row for row in tenants}
        winning_tenant = tenant_map[target.tenant_id]
        self._require_join_gate(
            session,
            tenant=winning_tenant,
            expected_access_version=tenant_access_version,
            database_now=now,
        )
        now = self._now(session)
        self._require_join_gate(
            session,
            tenant=winning_tenant,
            expected_access_version=tenant_access_version,
            database_now=now,
        )
        if _as_utc(target.expires_at) <= now:
            raise InvitationCredentialError()
        for tenant_id in tenant_ids:
            active_count, pending_count = self._seat_usage(
                session,
                tenant_id=tenant_id,
                database_now=now,
            )
            expected_pending = sum(
                1
                for row in pending
                if row.tenant_id == tenant_id
                and _as_utc(row.expires_at) > now
            )
            if pending_count < expected_pending:
                raise InvitationConflictError()
            if tenant_id == target.tenant_id and (
                active_count + pending_count > CORE_MEMBER_SEAT_CAP
            ):
                raise InvitationSeatLimitError()

        expected_context = accept_invitation_challenge_context(
            phone=_phone_from_user(user),
            user_uuid=UUID(user.id),
            tenant_uuid=UUID(target.tenant_id),
            invitation_uuid=UUID(target.id),
            token_generation=target.token_generation,
            invitation_row_version=target.row_version,
        )
        self._consume_challenge(
            session,
            challenges=challenges,
            submission=challenge,
            expected_context=expected_context,
            database_now=now,
        )

        membership = TenantMembership(
            id=membership_id,
            tenant_id=target.tenant_id,
            user_id=user.id,
            role_key=target.role_key,
            status="active",
            source_type="invitation",
            source_uuid=target.id,
            registration_commit_uuid=None,
            row_version=1,
            created_at=now,
            updated_at=now,
        )
        try:
            session.add(membership)
            session.flush()
        except IntegrityError:
            raise InvitationConflictError() from None

        if user.status == "unverified":
            user.status = "active"
        user.phone_verified_at = now
        user.updated_at = now

        superseded_count = 0
        expired_count = 0
        terminal_digests: set[bytes] = set()
        for row in pending:
            terminal_digests.add(_accept_payload_digest(row))
            if row.id == target.id:
                _terminalize(
                    row,
                    status="accepted",
                    reason=None,
                    database_now=now,
                )
            elif _as_utc(row.expires_at) <= now:
                _terminalize(
                    row,
                    status="expired",
                    reason=_TERMINAL_EXPIRED,
                    database_now=now,
                )
                expired_count += 1
            else:
                _terminalize(
                    row,
                    status="superseded",
                    reason=_TERMINAL_SUPERSEDED,
                    database_now=now,
                )
                superseded_count += 1
        _invalidate_matching_challenges(
            challenges,
            digests=terminal_digests,
            database_now=now,
            reason="invitation_terminal",
        )
        session.flush()
        return InvitationAcceptanceResult(
            invitation_uuid=UUID(target.id),
            membership_uuid=UUID(membership.id),
            tenant_uuid=UUID(membership.tenant_id),
            user_uuid=UUID(user.id),
            status=target.status,
            membership_status=membership.status,
            invitation_row_version=target.row_version,
            superseded_count=superseded_count,
            expired_count=expired_count,
            created=True,
            idempotent=False,
        )

    def _terminalize_pending(
        self,
        session: Session,
        *,
        invitation_uuid: str | UUID,
        expected_invitation_row_version: int,
        operation: str,
    ) -> InvitationTerminalResult:
        self._prepare(session)
        invitation_id = str(_uuid(invitation_uuid, "invitation_uuid"))
        expected_revision = _positive(
            expected_invitation_row_version,
            "expected_invitation_row_version",
        )
        summary = session.execute(
            sa.select(TenantInvitation.phone_e164)
            .where(TenantInvitation.id == invitation_id)
        ).one_or_none()
        if summary is None:
            raise InvitationConflictError()
        user = self._lock_user_by_phone(session, summary.phone_e164)
        invitations = self._lock_phone_invitations(session, summary.phone_e164)
        target = _find_invitation(invitations, invitation_id)
        if target is None:
            raise InvitationConflictError()
        self._lock_tenants(session, (target.tenant_id,))
        self._lock_guards(session, (target.tenant_id,))
        digest = _accept_payload_digest_from_values(
            invitation_uuid=target.id,
            token_generation=target.token_generation,
            invitation_row_version=expected_revision,
        )
        challenges = self._lock_challenges(
            session,
            phones=(summary.phone_e164,),
            challenge_ids=(),
            action_digests={digest},
        )
        self._lock_user_memberships(session, user.id)
        now = self._now(session)

        desired_status = "revoked" if operation == "revoke" else "expired"
        desired_reason = (
            _TERMINAL_REVOKED if operation == "revoke" else _TERMINAL_EXPIRED
        )
        if (
            target.status == desired_status
            and target.row_version == expected_revision + 1
            and target.terminal_reason_code == desired_reason
            and target.user_id is None
        ):
            return _terminal_result(target, idempotent=True)
        if target.status != "pending" or target.user_id != user.id:
            raise InvitationConflictError()
        if target.row_version != expected_revision:
            raise InvitationStaleRevisionError()
        expires_at = _as_utc(target.expires_at)
        if operation == "revoke" and expires_at <= now:
            raise InvitationConflictError()
        if operation == "expire" and expires_at > now:
            raise InvitationConflictError()

        _terminalize(
            target,
            status=desired_status,
            reason=desired_reason,
            database_now=now,
        )
        _invalidate_matching_challenges(
            challenges,
            digests={digest},
            database_now=now,
            reason=f"invitation_{desired_status}",
        )
        session.flush()
        return _terminal_result(target, idempotent=False)

    def _prepare(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise InvitationTransactionError()
        transaction = session.get_transaction()
        if (
            transaction is None
            or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        ):
            raise InvitationTransactionError()
        if session.new or session.deleted or any(
            session.is_modified(row, include_collections=True)
            for row in session.dirty
        ):
            raise InvitationTransactionError()
        _materialize_sqlite_outer_transaction(session)

    def _now(self, session: Session) -> datetime:
        return _as_utc(self._database_clock(session))

    def _lock_or_create_user(
        self,
        session: Session,
        *,
        phone: CanonicalSmsPhone,
        proposed_user_uuid: str,
    ) -> User:
        existing_id = session.scalar(
            sa.select(User.id).where(User.phone_e164 == phone.e164)
        )
        if existing_id is None:
            try:
                with session.begin_nested():
                    session.add(
                        User(
                            id=proposed_user_uuid,
                            phone_region_iso2="CN",
                            phone_e164=phone.e164,
                            phone_normalization_version=(
                                phone.normalization_version
                            ),
                            phone_metadata_version=phone.metadata_version,
                            status="unverified",
                            auth_version=1,
                        )
                    )
                    session.flush()
            except IntegrityError:
                session.expire_all()
        return self._lock_user_by_phone(session, phone.e164)

    @staticmethod
    def _lock_user_by_phone(session: Session, phone: str) -> User:
        user = session.scalar(
            sa.select(User)
            .where(User.phone_e164 == phone)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if user is None:
            raise InvitationIdentityError()
        return user

    @staticmethod
    def _lock_phone_invitations(
        session: Session,
        phone: str,
    ) -> tuple[TenantInvitation, ...]:
        return tuple(
            session.scalars(
                sa.select(TenantInvitation)
                .where(TenantInvitation.phone_e164 == phone)
                .order_by(TenantInvitation.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    @staticmethod
    def _lock_tenants(
        session: Session,
        tenant_ids: tuple[str, ...],
    ) -> tuple[Tenant, ...]:
        ordered = tuple(sorted(set(tenant_ids)))
        tenants = tuple(
            session.scalars(
                sa.select(Tenant)
                .where(Tenant.id.in_(ordered))
                .order_by(Tenant.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if tuple(row.id for row in tenants) != ordered:
            raise InvitationTenantGateError()
        return tenants

    @staticmethod
    def _lock_guards(
        session: Session,
        tenant_ids: tuple[str, ...],
    ) -> tuple[MemberSeatGuard, ...]:
        ordered = tuple(sorted(set(tenant_ids)))
        guards = tuple(
            session.scalars(
                sa.select(MemberSeatGuard)
                .where(
                    MemberSeatGuard.tenant_id.in_(ordered),
                    MemberSeatGuard.quota_key == "member_seats",
                )
                .order_by(MemberSeatGuard.tenant_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if tuple(row.tenant_id for row in guards) != ordered:
            raise InvitationConflictError()
        return guards

    @staticmethod
    def _lock_challenges(
        session: Session,
        *,
        phones: tuple[str, ...],
        challenge_ids: tuple[str, ...],
        action_digests: set[bytes],
    ) -> tuple[SmsChallenge, ...]:
        predicates = []
        if challenge_ids:
            predicates.append(SmsChallenge.id.in_(tuple(sorted(challenge_ids))))
        if action_digests:
            predicates.append(
                SmsChallenge.action_payload_digest_sha256.in_(
                    tuple(sorted(action_digests))
                )
            )
        if not predicates:
            return ()
        selected_phones = tuple(sorted(set(phones)))
        if not selected_phones:
            return ()
        return tuple(
            session.scalars(
                sa.select(SmsChallenge)
                .where(
                    SmsChallenge.canonical_phone_e164.in_(selected_phones),
                    SmsChallenge.purpose.in_(
                        ("accept_invitation", "admin_invitation")
                    ),
                    sa.or_(*predicates),
                )
                .order_by(SmsChallenge.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    @staticmethod
    def _lock_user_memberships(
        session: Session,
        user_id: str,
    ) -> tuple[TenantMembership, ...]:
        return tuple(
            session.scalars(
                sa.select(TenantMembership)
                .where(TenantMembership.user_id == user_id)
                .order_by(TenantMembership.tenant_id, TenantMembership.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

    @staticmethod
    def _require_user_available(
        user: User,
        memberships: tuple[TenantMembership, ...],
    ) -> None:
        try:
            _phone_from_user(user)
        except ValueError:
            raise InvitationIdentityError() from None
        if (
            user.status not in {"unverified", "active"}
            or any(row.status != "released" for row in memberships)
        ):
            raise InvitationIdentityError()

    def _require_join_gate(
        self,
        session: Session,
        *,
        tenant: Tenant,
        expected_access_version: int,
        database_now: datetime,
    ) -> None:
        transaction = session.get_transaction()
        try:
            facts = self._join_gate_current_read(
                session,
                tenant=tenant,
                database_now=database_now,
            )
        except Exception:
            raise InvitationTenantGateError() from None
        if (
            session.get_transaction() is not transaction
            or not isinstance(facts, InvitationJoinGateFacts)
            or str(facts.tenant_uuid) != tenant.id
            or facts.access_version != expected_access_version
            or tenant.access_version != expected_access_version
            or not facts.join_allowed
        ):
            raise InvitationTenantGateError()

    @staticmethod
    def _seat_usage(
        session: Session,
        *,
        tenant_id: str,
        database_now: datetime,
    ) -> tuple[int, int]:
        active = session.scalar(
            sa.select(sa.func.count())
            .select_from(TenantMembership)
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.status == "active",
            )
        )
        pending = session.scalar(
            sa.select(sa.func.count())
            .select_from(TenantInvitation)
            .where(
                TenantInvitation.tenant_id == tenant_id,
                TenantInvitation.status == "pending",
                TenantInvitation.expires_at > database_now,
            )
        )
        return int(active or 0), int(pending or 0)

    def _consume_challenge(
        self,
        session: Session,
        *,
        challenges: tuple[SmsChallenge, ...],
        submission: InvitationChallengeSubmission,
        expected_context: SmsChallengeContext,
        database_now: datetime,
    ) -> None:
        challenge_id = str(submission.challenge_uuid)
        if not any(row.id == challenge_id for row in challenges):
            raise InvitationCredentialError()
        outcome = self._sms.verify_and_consume(
            session,
            challenge_id=challenge_id,
            context=expected_context,
            plaintext_code=submission.plaintext_code,
            root_key=submission.root_key,
            now=database_now,
        )
        if not outcome.accepted:
            raise InvitationChallengeRejectedError()


def admin_invitation_challenge_context(
    *,
    actor_phone: CanonicalSmsPhone,
    target_phone: CanonicalSmsPhone,
    tenant_uuid: UUID,
    actor_session_uuid: UUID | None,
    expected_tenant_access_version: int,
) -> SmsChallengeContext:
    """Build the sole accepted D48 context for creating an Admin invite."""

    if not isinstance(actor_phone, CanonicalSmsPhone) or not isinstance(
        target_phone, CanonicalSmsPhone
    ):
        raise TypeError("actor_phone and target_phone must be canonical phones")
    _uuid(tenant_uuid, "tenant_uuid")
    access_version = _positive(
        expected_tenant_access_version,
        "expected_tenant_access_version",
    )
    if actor_session_uuid is None:
        raise ValueError("actor_session_uuid is required")
    _uuid(actor_session_uuid, "actor_session_uuid")
    return SmsChallengeContext(
        purpose=SmsPurpose.ADMIN_INVITATION,
        phone=actor_phone,
        action_payload=CanonicalActionPayload.from_value(
            {
                "expected_absent_target": True,
                "role": "admin",
                "target_phone_e164": target_phone.e164,
                "tenant_uuid": str(tenant_uuid),
            }
        ),
        authoritative_revision=f"tenant-access:{access_version}",
        user_id=None,
        tenant_id=str(tenant_uuid),
        actor_session_id=str(actor_session_uuid),
    )


def _require_admin_invitation_proof(
    proof: object,
    *,
    tenant_uuid: UUID,
    invitation_uuid: UUID,
    target_phone: CanonicalSmsPhone,
    expected_tenant_access_version: int,
) -> None:
    if (
        not isinstance(proof, AdminInvitationPermissionProof)
        or proof.tenant_uuid != tenant_uuid
        or proof.invitation_uuid != invitation_uuid
        or proof.target_phone_e164 != target_phone.e164
        or proof.expected_tenant_access_version
        != expected_tenant_access_version
    ):
        raise InvitationCredentialError()


def accept_invitation_challenge_context(
    *,
    phone: CanonicalSmsPhone,
    user_uuid: UUID,
    tenant_uuid: UUID,
    invitation_uuid: UUID,
    token_generation: int,
    invitation_row_version: int,
) -> SmsChallengeContext:
    """Build the action-bound context for one invitation generation."""

    for value, name in (
        (user_uuid, "user_uuid"),
        (tenant_uuid, "tenant_uuid"),
        (invitation_uuid, "invitation_uuid"),
    ):
        _uuid(value, name)
    generation = _positive(token_generation, "token_generation")
    row_version = _positive(invitation_row_version, "invitation_row_version")
    return SmsChallengeContext(
        purpose=SmsPurpose.ACCEPT_INVITATION,
        phone=phone,
        action_payload=CanonicalActionPayload.from_value(
            {
                "invitation_uuid": str(invitation_uuid),
                "token_generation": generation,
            }
        ),
        authoritative_revision=(
            f"invitation:{invitation_uuid}:g:{generation}:r:{row_version}"
        ),
        user_id=str(user_uuid),
        tenant_id=str(tenant_uuid),
        actor_session_id=None,
    )


def _accept_payload_digest(invitation: TenantInvitation) -> bytes:
    return _accept_payload_digest_from_values(
        invitation_uuid=invitation.id,
        token_generation=invitation.token_generation,
        invitation_row_version=invitation.row_version,
    )


def _accept_payload_digest_from_values(
    *,
    invitation_uuid: str,
    token_generation: int,
    invitation_row_version: int,
) -> bytes:
    del invitation_row_version  # revision is stored separately on SmsChallenge
    return CanonicalActionPayload.from_value(
        {
            "invitation_uuid": invitation_uuid,
            "token_generation": token_generation,
        }
    ).digest_sha256


def _phone_from_user(user: User) -> CanonicalSmsPhone:
    return CanonicalSmsPhone(
        e164=user.phone_e164,
        normalization_version=user.phone_normalization_version,
        metadata_version=user.phone_metadata_version,
    )


def _pending_for_tenant(
    invitations: tuple[TenantInvitation, ...],
    tenant_id: str,
) -> TenantInvitation | None:
    matches = [
        row
        for row in invitations
        if row.tenant_id == tenant_id and row.status == "pending"
    ]
    if len(matches) > 1:
        raise InvitationConflictError()
    return matches[0] if matches else None


def _find_invitation(
    invitations: tuple[TenantInvitation, ...],
    invitation_id: str,
) -> TenantInvitation | None:
    return next((row for row in invitations if row.id == invitation_id), None)


def _issue_replay(
    invitations: tuple[TenantInvitation, ...],
    *,
    invitation_id: str,
    tenant_id: str,
    user_id: str,
    role: InvitationRole,
    token: InvitationToken,
    expected_revision: int | None,
) -> TenantInvitation | None:
    row = _find_invitation(invitations, invitation_id)
    if row is None or row.status != "pending":
        return None
    common = bool(
        row.tenant_id == tenant_id
        and row.user_id == user_id
        and row.role_key == role.value
        and hmac.compare_digest(bytes(row.token_hash), token.digest_sha256)
    )
    if not common:
        return None
    if expected_revision is None and row.row_version == 1 and row.token_generation == 1:
        return row
    if (
        expected_revision is not None
        and row.row_version == expected_revision + 1
        and row.token_generation >= 2
    ):
        return row
    return None


def _acceptance_replay(
    *,
    target: TenantInvitation,
    invitations: tuple[TenantInvitation, ...],
    memberships: tuple[TenantMembership, ...],
    expected_revision: int,
    membership_id: str,
    user: User,
    challenges: tuple[SmsChallenge, ...],
    challenge_id: str,
) -> InvitationAcceptanceResult | None:
    if target.status != "accepted":
        return None
    matching = [row for row in memberships if row.id == membership_id]
    expected_revision_value = (
        f"invitation:{target.id}:g:{target.token_generation}:r:{expected_revision}"
    )
    challenge_matches = any(
        row.id == challenge_id
        and row.purpose == "accept_invitation"
        and row.verification_state == "consumed"
        and row.consumed_at is not None
        and row.user_id == user.id
        and row.tenant_id == target.tenant_id
        and row.canonical_phone_e164 == user.phone_e164
        and row.authoritative_revision == expected_revision_value
        and hmac.compare_digest(
            bytes(row.action_payload_digest_sha256),
            _accept_payload_digest_from_values(
                invitation_uuid=target.id,
                token_generation=target.token_generation,
                invitation_row_version=expected_revision,
            ),
        )
        for row in challenges
    )
    if (
        target.row_version != expected_revision + 1
        or target.user_id is not None
        or target.accepted_at is None
        or target.terminal_reason_code is not None
        or len(matching) != 1
        or matching[0].tenant_id != target.tenant_id
        or matching[0].user_id != user.id
        or matching[0].role_key != target.role_key
        or matching[0].source_type != "invitation"
        or matching[0].source_uuid != target.id
        or any(row.status == "pending" for row in invitations)
        or not challenge_matches
    ):
        raise InvitationConflictError()
    membership = matching[0]
    return InvitationAcceptanceResult(
        invitation_uuid=UUID(target.id),
        membership_uuid=UUID(membership.id),
        tenant_uuid=UUID(membership.tenant_id),
        user_uuid=UUID(user.id),
        status=target.status,
        membership_status=membership.status,
        invitation_row_version=target.row_version,
        superseded_count=0,
        expired_count=0,
        created=False,
        idempotent=True,
    )


def _terminalize(
    invitation: TenantInvitation,
    *,
    status: str,
    reason: str | None,
    database_now: datetime,
) -> None:
    invitation.status = status
    invitation.user_id = None
    invitation.accepted_at = database_now if status == "accepted" else None
    invitation.superseded_at = (
        database_now if status == "superseded" else None
    )
    invitation.terminal_reason_code = reason
    invitation.row_version += 1
    invitation.updated_at = database_now


def _invalidate_matching_challenges(
    challenges: tuple[SmsChallenge, ...],
    *,
    digests: set[bytes],
    database_now: datetime,
    reason: str,
) -> None:
    for challenge in challenges:
        if (
            challenge.purpose == "accept_invitation"
            and challenge.verification_state in {"pending_delivery", "active"}
            and any(
                hmac.compare_digest(
                    bytes(challenge.action_payload_digest_sha256), digest
                )
                for digest in digests
            )
        ):
            challenge.verification_state = "invalidated"
            challenge.invalidated_at = database_now
            challenge.invalidated_reason_code = reason
            challenge.row_version += 1


def _issue_result(
    invitation: TenantInvitation,
    *,
    user: User,
    token: InvitationToken,
    created: bool,
    rotated: bool,
    idempotent: bool,
) -> InvitationIssueResult:
    return InvitationIssueResult(
        invitation_uuid=UUID(invitation.id),
        coordinating_user_uuid=UUID(user.id),
        tenant_uuid=UUID(invitation.tenant_id),
        status=invitation.status,
        role=InvitationRole(invitation.role_key),
        token_generation=invitation.token_generation,
        expires_at=_as_utc(invitation.expires_at),
        row_version=invitation.row_version,
        token=token,
        created=created,
        rotated=rotated,
        idempotent=idempotent,
    )


def _terminal_result(
    invitation: TenantInvitation,
    *,
    idempotent: bool,
) -> InvitationTerminalResult:
    return InvitationTerminalResult(
        invitation_uuid=UUID(invitation.id),
        tenant_uuid=UUID(invitation.tenant_id),
        status=invitation.status,
        row_version=invitation.row_version,
        idempotent=idempotent,
    )


def _read_database_utc_now(session: Session) -> datetime:
    dialect_name = session.get_bind().dialect.name
    statement = _database_utc_now_statement(dialect_name)
    return _as_utc(session.scalar(statement))


def _database_utc_now_statement(dialect_name: str):
    if dialect_name in {"mysql", "mariadb"}:
        return sa.text("SELECT UTC_TIMESTAMP(6)")
    return sa.select(sa.func.current_timestamp())


def _materialize_sqlite_outer_transaction(session: Session) -> None:
    connection = session.connection()
    if connection.dialect.name != "sqlite":
        return
    driver_connection = getattr(connection.connection, "driver_connection", None)
    if driver_connection is not None and not driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise InvitationTransactionError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            parsed = UUID(value)
        except ValueError:
            pass
        else:
            if str(parsed) == value.lower():
                return parsed
    raise ValueError(f"{field_name} is invalid")


def _positive(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _optional_positive(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _positive(value, field_name)


def _role(value: object) -> InvitationRole:
    try:
        return InvitationRole(value)
    except (TypeError, ValueError):
        raise ValueError("role is invalid") from None


def _token(value: object) -> InvitationToken:
    if not isinstance(value, InvitationToken):
        raise TypeError("proposed_token must be an InvitationToken")
    return value
