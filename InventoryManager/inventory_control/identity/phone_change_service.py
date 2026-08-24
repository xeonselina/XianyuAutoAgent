"""D47/D48 self-service tenant phone ownership transfer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.orm.session import SessionTransactionOrigin

from inventory_control.models import (
    MemberSeatGuard,
    SmsChallenge,
    Tenant,
    TenantAuthSecurityEvent,
    TenantInvitation,
    TenantMembership,
    TenantRegistrationAttempt,
    TenantSensitiveActionIntent,
    TenantSensitiveActionIntentChallenge,
    TenantUserSession,
    User,
)
from inventory_control.sms import CanonicalSmsPhone


class PhoneChangeError(RuntimeError):
    pass


class PhoneChangeInputError(PhoneChangeError):
    pass


class PhoneChangeConflictError(PhoneChangeError):
    pass


@dataclass(frozen=True, slots=True, repr=False)
class PhoneChangeAuthorizationProof:
    tenant_uuid: UUID
    user_uuid: UUID
    actor_session_uuid: UUID
    change_uuid: UUID
    old_challenge_uuid: UUID
    new_challenge_uuid: UUID
    expected_auth_version: int
    old_phone_e164: str
    new_phone_e164: str

    def __repr__(self) -> str:
        return (
            f"PhoneChangeAuthorizationProof(change_uuid={self.change_uuid!r}, "
            "<phone-and-challenge-proof-redacted>)"
        )


@dataclass(frozen=True, slots=True)
class PhoneChangeResult:
    user_uuid: UUID
    auth_version: int
    sessions_revoked: int
    invitations_superseded: int


@dataclass(frozen=True, slots=True, repr=False)
class LockedPhoneChangeScope:
    tenant: Tenant
    current_user: User
    coordinating_user: User
    membership: TenantMembership
    invitations: tuple[TenantInvitation, ...]
    challenges: tuple[SmsChallenge, ...]
    sessions: tuple[TenantUserSession, ...]
    change_uuid: UUID
    actor_session_uuid: UUID
    old_challenge_uuid: UUID
    new_challenge_uuid: UUID

    def __repr__(self) -> str:
        return (
            f"LockedPhoneChangeScope(change_uuid={self.change_uuid!r}, "
            "<identity-scope-redacted>)"
        )


class TenantPhoneChangeService:
    """Coordinate a phone claim without merging two historical identities."""

    def ensure_candidate_available(
        self,
        session: Session,
        *,
        current_user_uuid: UUID,
        new_phone: CanonicalSmsPhone,
    ) -> None:
        """Fast issue-time check; the final transaction repeats it under locks."""

        _require_session(session)
        current_user_id = _uuid_text(current_user_uuid)
        if not isinstance(new_phone, CanonicalSmsPhone):
            raise PhoneChangeInputError()
        current = session.get(User, current_user_id)
        if current is None or current.phone_e164 == new_phone.e164:
            raise PhoneChangeConflictError()
        candidate = session.scalar(
            sa.select(User).where(User.phone_e164 == new_phone.e164)
        )
        if candidate is None:
            return
        self._require_disposable_coordinator(session, candidate=candidate)

    def lock_scope(
        self,
        session: Session,
        *,
        tenant_uuid: UUID,
        current_user_uuid: UUID,
        actor_session_uuid: UUID,
        change_uuid: UUID,
        expected_auth_version: int,
        expected_tenant_access_version: int,
        old_phone: CanonicalSmsPhone,
        new_phone: CanonicalSmsPhone,
        old_challenge_uuid: UUID,
        new_challenge_uuid: UUID,
        database_now: datetime,
    ) -> LockedPhoneChangeScope:
        """Acquire the canonical-user → invitations → tenants lock prefix."""

        _prepare(session)
        tenant_id = _uuid_text(tenant_uuid)
        current_user_id = _uuid_text(current_user_uuid)
        actor_session_id = _uuid_text(actor_session_uuid)
        _uuid_text(change_uuid)
        _uuid_text(old_challenge_uuid)
        new_challenge_id = _uuid_text(new_challenge_uuid)
        expected_auth = _positive(expected_auth_version)
        expected_access = _positive(expected_tenant_access_version)
        if (
            not isinstance(old_phone, CanonicalSmsPhone)
            or not isinstance(new_phone, CanonicalSmsPhone)
            or old_phone.e164 == new_phone.e164
        ):
            raise PhoneChangeInputError()
        now = _as_utc(database_now)

        summary = session.execute(
            sa.select(User.phone_e164).where(User.id == current_user_id)
        ).one_or_none()
        if summary is None or summary.phone_e164 != old_phone.e164:
            raise PhoneChangeConflictError()
        candidate_id = session.scalar(
            sa.select(User.id).where(User.phone_e164 == new_phone.e164)
        )
        if candidate_id is None:
            candidate_id = str(uuid4())
            try:
                with session.begin_nested():
                    session.add(
                        User(
                            id=candidate_id,
                            phone_region_iso2="CN",
                            phone_e164=new_phone.e164,
                            phone_normalization_version=(
                                new_phone.normalization_version
                            ),
                            phone_metadata_version=new_phone.metadata_version,
                            phone_verified_at=None,
                            status="unverified",
                            auth_version=1,
                            created_at=now,
                            updated_at=now,
                        )
                    )
                    session.flush()
            except IntegrityError:
                session.expire_all()
            candidate_id = session.scalar(
                sa.select(User.id).where(User.phone_e164 == new_phone.e164)
            )
        if candidate_id is None or candidate_id == current_user_id:
            raise PhoneChangeConflictError()

        users = tuple(
            session.scalars(
                sa.select(User)
                .where(User.id.in_((current_user_id, candidate_id)))
                .order_by(User.phone_e164, User.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        if {row.id for row in users} != {current_user_id, candidate_id}:
            raise PhoneChangeConflictError()
        current = next(row for row in users if row.id == current_user_id)
        candidate = next(row for row in users if row.id == candidate_id)

        invitations = tuple(
            session.scalars(
                sa.select(TenantInvitation)
                .where(TenantInvitation.phone_e164 == new_phone.e164)
                .order_by(TenantInvitation.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        tenant_ids = tuple(
            sorted({tenant_id, *(row.tenant_id for row in invitations)})
        )
        tenants = tuple(
            session.scalars(
                sa.select(Tenant)
                .where(Tenant.id.in_(tenant_ids))
                .order_by(Tenant.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        guards = tuple(
            session.scalars(
                sa.select(MemberSeatGuard)
                .where(
                    MemberSeatGuard.tenant_id.in_(tenant_ids),
                    MemberSeatGuard.quota_key == "member_seats",
                )
                .order_by(MemberSeatGuard.tenant_id)
                .with_for_update()
            )
        )
        if (
            tuple(row.id for row in tenants) != tenant_ids
            or tuple(row.tenant_id for row in guards) != tenant_ids
        ):
            raise PhoneChangeConflictError()
        tenant = next(row for row in tenants if row.id == tenant_id)

        memberships = tuple(
            session.scalars(
                sa.select(TenantMembership)
                .where(
                    TenantMembership.user_id.in_(
                        (current_user_id, candidate_id)
                    )
                )
                .order_by(TenantMembership.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        attempts = tuple(
            session.scalars(
                sa.select(TenantRegistrationAttempt)
                .where(TenantRegistrationAttempt.user_id == candidate_id)
                .order_by(TenantRegistrationAttempt.id)
                .with_for_update()
            )
        )
        related_intent_ids = tuple(
            session.scalars(
                sa.select(TenantSensitiveActionIntentChallenge.intent_id)
                .join(
                    SmsChallenge,
                    SmsChallenge.id
                    == TenantSensitiveActionIntentChallenge.challenge_id,
                )
                .where(
                    SmsChallenge.canonical_phone_e164 == new_phone.e164,
                    SmsChallenge.purpose == "phone_change_new",
                )
                .order_by(TenantSensitiveActionIntentChallenge.intent_id)
            )
        )
        related_intent_id_set = frozenset(related_intent_ids)
        related_intents = tuple(
            session.scalars(
                sa.select(TenantSensitiveActionIntent)
                .where(
                    sa.or_(
                        TenantSensitiveActionIntent.id.in_(
                            related_intent_id_set
                        ),
                        TenantSensitiveActionIntent.actor_user_id
                        == candidate_id,
                    )
                )
                .order_by(TenantSensitiveActionIntent.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        challenges = tuple(
            session.scalars(
                sa.select(SmsChallenge)
                .where(
                    sa.or_(
                        SmsChallenge.user_id == candidate_id,
                        SmsChallenge.canonical_phone_e164 == new_phone.e164,
                    )
                )
                .order_by(SmsChallenge.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        sessions = tuple(
            session.scalars(
                sa.select(TenantUserSession)
                .where(
                    TenantUserSession.user_id.in_(
                        (current_user_id, candidate_id)
                    )
                )
                .order_by(TenantUserSession.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )

        membership = _current_membership(
            memberships,
            current_user_id=current_user_id,
            tenant_id=tenant_id,
        )
        if (
            current.status != "active"
            or current.phone_e164 != old_phone.e164
            or current.auth_version != expected_auth
            or tenant.access_version != expected_access
            or tenant.status not in {"active", "suspended"}
            or not any(
                row.id == actor_session_id
                and row.user_id == current_user_id
                and row.revoked_at is None
                for row in sessions
            )
        ):
            raise PhoneChangeConflictError()
        if attempts:
            raise PhoneChangeConflictError()
        self._require_disposable_coordinator(
            session,
            candidate=candidate,
            memberships=memberships,
            sessions=sessions,
            related_intents=related_intents,
        )
        if any(
            row.status == "pending" and row.user_id != candidate.id
            for row in invitations
        ):
            raise PhoneChangeConflictError()
        expected_challenge = next(
            (row for row in challenges if row.id == new_challenge_id), None
        )
        if (
            expected_challenge is None
            or expected_challenge.purpose != "phone_change_new"
            or expected_challenge.user_id != current_user_id
        ):
            raise PhoneChangeConflictError()
        if any(
            row.id != new_challenge_id
            and row.purpose in {"register", "phone_change_new"}
            and row.verification_state in {"pending_delivery", "active"}
            for row in challenges
        ):
            raise PhoneChangeConflictError()
        if any(
            row.id in related_intent_id_set
            and row.id != str(change_uuid)
            and row.status in {"pending_verification", "authorized", "executing"}
            for row in related_intents
        ):
            raise PhoneChangeConflictError()

        return LockedPhoneChangeScope(
            tenant=tenant,
            current_user=current,
            coordinating_user=candidate,
            membership=membership,
            invitations=invitations,
            challenges=challenges,
            sessions=sessions,
            change_uuid=change_uuid,
            actor_session_uuid=actor_session_uuid,
            old_challenge_uuid=old_challenge_uuid,
            new_challenge_uuid=new_challenge_uuid,
        )

    def apply_locked(
        self,
        session: Session,
        *,
        scope: LockedPhoneChangeScope,
        proof: PhoneChangeAuthorizationProof,
        new_phone: CanonicalSmsPhone,
        database_now: datetime,
    ) -> PhoneChangeResult:
        """Apply the claim after both fixed-role challenges were consumed."""

        if (
            not isinstance(session, Session)
            or not isinstance(scope, LockedPhoneChangeScope)
            or not isinstance(proof, PhoneChangeAuthorizationProof)
            or not isinstance(new_phone, CanonicalSmsPhone)
        ):
            raise PhoneChangeInputError()
        now = _as_utc(database_now)
        expected = PhoneChangeAuthorizationProof(
            tenant_uuid=UUID(scope.tenant.id),
            user_uuid=UUID(scope.current_user.id),
            actor_session_uuid=scope.actor_session_uuid,
            change_uuid=scope.change_uuid,
            old_challenge_uuid=scope.old_challenge_uuid,
            new_challenge_uuid=scope.new_challenge_uuid,
            expected_auth_version=scope.current_user.auth_version,
            old_phone_e164=scope.current_user.phone_e164,
            new_phone_e164=new_phone.e164,
        )
        if proof != expected:
            raise PhoneChangeConflictError()

        candidate = scope.coordinating_user
        for invitation in scope.invitations:
            if invitation.status == "pending":
                invitation.status = "superseded"
                invitation.user_id = None
                invitation.superseded_at = now
                invitation.terminal_reason_code = "phone_claimed"
                invitation.row_version += 1
                invitation.updated_at = now
        superseded = sum(
            1 for row in scope.invitations if row.terminal_reason_code == "phone_claimed"
        )

        for challenge in scope.challenges:
            if challenge.user_id != candidate.id:
                continue
            if challenge.purpose != "accept_invitation":
                raise PhoneChangeConflictError()
            if challenge.verification_state == "consumed":
                raise PhoneChangeConflictError()
            if challenge.verification_state in {"pending_delivery", "active"}:
                challenge.verification_state = "invalidated"
                challenge.invalidated_at = now
                challenge.invalidated_reason_code = "phone_claimed"
                challenge.row_version += 1
            challenge.user_id = None

        session.flush()
        session.delete(candidate)
        session.flush()
        current = scope.current_user
        current.phone_e164 = new_phone.e164
        current.phone_normalization_version = new_phone.normalization_version
        current.phone_metadata_version = new_phone.metadata_version
        current.phone_verified_at = now
        current.auth_version += 1
        current.updated_at = now
        revoked = 0
        for browser_session in scope.sessions:
            if browser_session.user_id == current.id and browser_session.revoked_at is None:
                browser_session.revoked_at = now
                browser_session.revoked_reason_code = "phone_changed"
                browser_session.revoked_by_session_id = str(
                    proof.actor_session_uuid
                )
                revoked += 1
        session.add(
            TenantAuthSecurityEvent(
                tenant_id=scope.tenant.id,
                user_id=current.id,
                actor_session_id=str(proof.actor_session_uuid),
                target_session_id=None,
                target_resource_type="tenant_user",
                target_resource_id=current.id,
                expected_target_revision=(
                    f"auth:{proof.expected_auth_version}"
                ),
                intent_id=str(proof.change_uuid),
                action_subtype="identity.phone_change",
                idempotency_reference=f"phone-change:{proof.change_uuid}",
                safe_outcome="sessions_revoked",
                event_type="security_invalidated",
                reason_code="phone_changed",
                request_id=f"phone-change:{proof.change_uuid}",
                created_at=now,
            )
        )
        session.flush()
        return PhoneChangeResult(
            user_uuid=UUID(current.id),
            auth_version=current.auth_version,
            sessions_revoked=revoked,
            invitations_superseded=superseded,
        )

    @staticmethod
    def _require_disposable_coordinator(
        session: Session,
        *,
        candidate: User,
        memberships: tuple[TenantMembership, ...] | None = None,
        sessions: tuple[TenantUserSession, ...] | None = None,
        related_intents: tuple[TenantSensitiveActionIntent, ...] | None = None,
    ) -> None:
        if (
            candidate.status != "unverified"
            or candidate.phone_verified_at is not None
            or candidate.auth_version != 1
        ):
            raise PhoneChangeConflictError()
        candidate_memberships = memberships
        if candidate_memberships is None:
            candidate_memberships = tuple(
                session.scalars(
                    sa.select(TenantMembership).where(
                        TenantMembership.user_id == candidate.id
                    )
                )
            )
        if any(row.user_id == candidate.id for row in candidate_memberships):
            raise PhoneChangeConflictError()
        candidate_sessions = sessions
        if candidate_sessions is None:
            candidate_sessions = tuple(
                session.scalars(
                    sa.select(TenantUserSession).where(
                        TenantUserSession.user_id == candidate.id
                    )
                )
            )
        if any(row.user_id == candidate.id for row in candidate_sessions):
            raise PhoneChangeConflictError()
        if session.scalar(
            sa.select(sa.func.count(TenantRegistrationAttempt.id)).where(
                TenantRegistrationAttempt.user_id == candidate.id
            )
        ):
            raise PhoneChangeConflictError()
        intents = related_intents
        if intents is None:
            intents = tuple(
                session.scalars(
                    sa.select(TenantSensitiveActionIntent).where(
                        TenantSensitiveActionIntent.actor_user_id == candidate.id
                    )
                )
            )
        if any(row.actor_user_id == candidate.id for row in intents) or session.scalar(
            sa.select(sa.func.count(TenantAuthSecurityEvent.id)).where(
                TenantAuthSecurityEvent.user_id == candidate.id
            )
        ):
            raise PhoneChangeConflictError()


def _current_membership(
    memberships: tuple[TenantMembership, ...],
    *,
    current_user_id: str,
    tenant_id: str,
) -> TenantMembership:
    matching = [
        row
        for row in memberships
        if row.user_id == current_user_id
        and row.tenant_id == tenant_id
        and row.status == "active"
        and row.released_at is None
    ]
    if len(matching) != 1:
        raise PhoneChangeConflictError()
    return matching[0]


def _prepare(session: Session) -> None:
    _require_session(session)
    transaction = session.get_transaction()
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        or session.new
        or session.deleted
        or any(
            session.is_modified(row, include_collections=True)
            for row in session.dirty
        )
    ):
        raise PhoneChangeInputError()
    connection = session.connection()
    if connection.dialect.name == "sqlite":
        driver = getattr(connection.connection, "driver_connection", None)
        if driver is not None and not driver.in_transaction:
            connection.exec_driver_sql("BEGIN IMMEDIATE")


def _require_session(session: object) -> None:
    if not isinstance(session, Session):
        raise PhoneChangeInputError()


def _uuid_text(value: object) -> str:
    if not isinstance(value, UUID):
        raise PhoneChangeInputError()
    return str(value)


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PhoneChangeInputError()
    return value


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise PhoneChangeInputError()
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "LockedPhoneChangeScope",
    "PhoneChangeAuthorizationProof",
    "PhoneChangeConflictError",
    "PhoneChangeError",
    "PhoneChangeInputError",
    "PhoneChangeResult",
    "TenantPhoneChangeService",
]
