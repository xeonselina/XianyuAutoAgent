"""Atomic tenant OTP consumption and opaque browser-session issuance."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.crypto import RootKey
from inventory_control.models import (
    SmsChallenge,
    Tenant,
    TenantMembership,
    TenantAuthSecurityEvent,
    TenantUserSession,
    User,
)
from inventory_control.sms import (
    CanonicalActionPayload,
    CanonicalSmsPhone,
    SmsChallengeContext,
    SmsChallengeService,
    SmsPurpose,
)

from .errors import InvalidOpaqueTokenError
from .session_service import (
    IssuedAuthSession,
    SessionService,
    TenantBrowserSessionPolicy,
)
from .tokens import digest_session_token


_LOGIN_ACTION_PAYLOAD = CanonicalActionPayload.from_value(
    {"action": "tenant_login", "protocol_version": 1}
)


@dataclass(frozen=True, slots=True, repr=False)
class TenantLoginCompletion:
    accepted: bool
    issued_session: IssuedAuthSession | None

    def __post_init__(self) -> None:
        if self.accepted is (self.issued_session is None):
            raise ValueError("tenant login completion is inconsistent")

    def __repr__(self) -> str:
        state = "accepted" if self.accepted else "rejected"
        return f"TenantLoginCompletion(state={state!r}, <redacted>)"


def build_tenant_login_sms_context(
    *,
    phone: CanonicalSmsPhone,
    user_id: str | None,
    tenant_id: str | None,
    user_auth_version: int | None,
) -> SmsChallengeContext:
    """Create the sole deterministic login-HMAC context."""

    eligible = (
        user_id is not None
        and tenant_id is not None
        and isinstance(user_auth_version, int)
        and not isinstance(user_auth_version, bool)
        and user_auth_version >= 1
    )
    if eligible:
        revision = f"tenant-login-user-auth:{user_auth_version}"
    elif user_id is None and tenant_id is None and user_auth_version is None:
        revision = "tenant-login-unavailable:v1"
    else:
        raise ValueError("tenant login SMS identity is inconsistent")
    return SmsChallengeContext(
        purpose=SmsPurpose.LOGIN,
        phone=phone,
        action_payload=_LOGIN_ACTION_PAYLOAD,
        authoritative_revision=revision,
        user_id=user_id,
        tenant_id=tenant_id,
    )


class TenantLoginService:
    """Consume one login challenge and issue one anchored fresh session."""

    __slots__ = ("_sms", "_sessions")

    def __init__(
        self,
        *,
        sms_challenge_service: SmsChallengeService,
        session_service: SessionService,
    ) -> None:
        if not isinstance(sms_challenge_service, SmsChallengeService):
            raise TypeError(
                "sms_challenge_service must be an SmsChallengeService"
            )
        if not isinstance(session_service, SessionService):
            raise TypeError("session_service must be a SessionService")
        self._sms = sms_challenge_service
        self._sessions = session_service

    def complete(
        self,
        session: Session,
        *,
        challenge_id: object,
        phone: CanonicalSmsPhone,
        plaintext_code: object,
        root_key: RootKey,
        session_policy: TenantBrowserSessionPolicy,
        presented_session_token: object = None,
        device_name: str | None = None,
        user_agent_summary: str | None = None,
        ip_summary: str | None = None,
        request_id: str | None = None,
        now: datetime | None = None,
    ) -> TenantLoginCompletion:
        if (
            not isinstance(session, Session)
            or not isinstance(phone, CanonicalSmsPhone)
            or not isinstance(root_key, RootKey)
            or not isinstance(session_policy, TenantBrowserSessionPolicy)
        ):
            raise TypeError("tenant login completion inputs are invalid")
        current_time = _as_utc(now or datetime.now(timezone.utc))
        selected_request_id = request_id or f"tenant-login:{uuid4()}"
        if (
            not isinstance(selected_request_id, str)
            or not 1 <= len(selected_request_id) <= 80
        ):
            raise ValueError("tenant login request_id is invalid")
        located = session.execute(
            sa.select(
                SmsChallenge.id,
                SmsChallenge.user_id,
                SmsChallenge.tenant_id,
                SmsChallenge.canonical_phone_e164,
                SmsChallenge.authoritative_revision,
            ).where(SmsChallenge.id == challenge_id)
        ).one_or_none()
        if located is None or located.canonical_phone_e164 != phone.e164:
            return _rejected()

        user = (
            session.scalar(
                sa.select(User)
                .where(User.id == located.user_id)
                .with_for_update()
            )
            if located.user_id is not None
            else None
        )
        membership = (
            session.scalar(
                sa.select(TenantMembership)
                .where(TenantMembership.claimed_user_id == located.user_id)
                .with_for_update()
            )
            if user is not None
            else None
        )
        tenant = (
            session.scalar(
                sa.select(Tenant)
                .where(Tenant.id == membership.tenant_id)
                .with_for_update()
            )
            if membership is not None
            else None
        )
        eligible = bool(
            user is not None
            and (
                user.status == "active"
                or (
                    user.status == "unverified"
                    and user.phone_verified_at is None
                    and membership is not None
                    and membership.source_type == "migration"
                )
            )
            and user.phone_e164 == phone.e164
            and membership is not None
            and membership.status == "active"
            and membership.released_at is None
            and tenant is not None
            and located.tenant_id == tenant.id
        )
        context = build_tenant_login_sms_context(
            phone=phone,
            user_id=user.id if eligible else None,
            tenant_id=tenant.id if eligible else None,
            user_auth_version=user.auth_version if eligible else None,
        )
        if context.authoritative_revision != located.authoritative_revision:
            return _rejected()
        verification = self._sms.verify_and_consume(
            session,
            challenge_id=located.id,
            context=context,
            plaintext_code=plaintext_code,
            root_key=root_key,
            now=current_time,
        )
        if not verification.accepted or not eligible:
            return _rejected()

        if user.phone_verified_at is None:
            user.phone_verified_at = current_time
        if user.status == "unverified":
            user.status = "active"

        replaced = _lock_presented_session(
            session,
            presented_session_token=presented_session_token,
            user_id=user.id,
        )
        if replaced is not None and replaced.revoked_at is None:
            replaced.revoked_at = current_time
            replaced.revoked_reason_code = "login_replaced"

        issued = self._sessions.issue(
            session,
            user_id=user.id,
            idle_timeout=session_policy.idle_timeout,
            absolute_timeout=session_policy.absolute_timeout,
            policy_version=session_policy.version,
            device_name=device_name,
            user_agent_summary=user_agent_summary,
            ip_summary=ip_summary,
            created_from_challenge_id=located.id,
            rotated_from_session_id=(
                replaced.id if replaced is not None else None
            ),
            now=current_time,
        )
        if replaced is not None:
            replaced.replaced_by_session_id = issued.auth.session_id
            replaced.revoked_by_session_id = issued.auth.session_id
        session.add(
            TenantAuthSecurityEvent(
                tenant_id=tenant.id,
                user_id=user.id,
                actor_session_id=issued.auth.session_id,
                target_session_id=(
                    replaced.id
                    if replaced is not None
                    else issued.auth.session_id
                ),
                event_type=(
                    "login_session_rotated"
                    if replaced is not None
                    else "login_session_created"
                ),
                reason_code=(
                    "login_replaced"
                    if replaced is not None
                    else "otp_login"
                ),
                request_id=selected_request_id,
                created_at=current_time,
            )
        )
        session.flush()
        return TenantLoginCompletion(
            accepted=True,
            issued_session=issued,
        )


def _lock_presented_session(
    session: Session,
    *,
    presented_session_token: object,
    user_id: str,
) -> TenantUserSession | None:
    try:
        digest = digest_session_token(presented_session_token)
    except (InvalidOpaqueTokenError, TypeError):
        return None
    located = session.scalar(
        sa.select(TenantUserSession).where(
            TenantUserSession.token_digest_sha256 == digest
        )
    )
    if located is None or located.user_id != user_id:
        return None
    return session.scalar(
        sa.select(TenantUserSession)
        .where(TenantUserSession.id == located.id)
        .with_for_update()
    )


def _rejected() -> TenantLoginCompletion:
    return TenantLoginCompletion(accepted=False, issued_session=None)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "TenantLoginCompletion",
    "TenantLoginService",
    "build_tenant_login_sms_context",
]
