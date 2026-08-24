"""Transactional tenant browser-session issuance and validation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inventory_control.domain.rbac import TenantRole
from inventory_control.domain.tenant_gate import (
    EffectiveTenantGate,
    TenantGateDecision,
)
from inventory_control.identity.errors import InvalidOpaqueTokenError
from inventory_control.identity.tokens import (
    IssuedOpaqueToken,
    digest_session_token,
    issue_csrf_token,
    issue_session_token,
    verify_csrf_token,
    verify_session_token,
)
from inventory_control.models.foundation import Tenant
from inventory_control.models.identity import (
    TenantMembership,
    TenantUserSession,
    User,
)


class SessionAuthenticationError(RuntimeError):
    """Fixed unauthenticated result that does not disclose lookup state."""

    code = "TENANT_SESSION_INVALID"

    def __init__(self) -> None:
        super().__init__("The tenant session is invalid.")


class SessionIssueError(RuntimeError):
    """The current user/membership facts do not permit session issuance."""


class CsrfAuthenticationError(RuntimeError):
    """Fixed rejection for absent, malformed, stale, or cross-session CSRF."""

    code = "CSRF_INVALID"

    def __init__(self) -> None:
        super().__init__("The CSRF proof is invalid.")


class SessionTargetNotFound(RuntimeError):
    """A same-user session target was not found, without disclosing ownership."""

    def __init__(self) -> None:
        super().__init__("The tenant session target is unavailable.")


@dataclass(frozen=True, slots=True)
class AuthSession:
    session_id: str
    user_id: str
    membership_id: str
    tenant_id: str
    role: TenantRole
    user_auth_version: int
    tenant_access_version: int
    tenant_timezone: str
    tenant_status: str
    effective_gate: EffectiveTenantGate
    csrf_generation: int
    idle_expires_at: datetime
    absolute_expires_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class IssuedAuthSession:
    auth: AuthSession
    session_token: str
    csrf_token: str

    def __repr__(self) -> str:
        return "IssuedAuthSession(<redacted>)"


@dataclass(frozen=True, slots=True)
class RevokeAllResult:
    revoked_count: int
    new_auth_version: int


@dataclass(frozen=True, slots=True)
class TenantBrowserSessionPolicy:
    """Versioned deployment policy without product-default durations."""

    version: int
    idle_timeout: timedelta
    absolute_timeout: timedelta

    def __post_init__(self) -> None:
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or self.version < 1
            or not isinstance(self.idle_timeout, timedelta)
            or not isinstance(self.absolute_timeout, timedelta)
            or self.idle_timeout <= timedelta(0)
            or self.absolute_timeout <= timedelta(0)
            or self.idle_timeout > self.absolute_timeout
        ):
            raise ValueError("tenant browser session policy is invalid")


class SessionGateCurrentRead(Protocol):
    """Reduce current lifecycle facts after the tenant row is locked."""

    def __call__(
        self,
        session: Session,
        tenant: Tenant,
        now: datetime,
    ) -> TenantGateDecision: ...


_AUTHENTICATED_SESSION_GATES = frozenset(
    {
        EffectiveTenantGate.ACTIVE,
        EffectiveTenantGate.EXPIRED,
        EffectiveTenantGate.SUSPENDED,
    }
)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class SessionService:
    """Operate tenant sessions inside a caller-owned control transaction."""

    def __init__(
        self,
        *,
        gate_current_read: SessionGateCurrentRead,
        session_token_issuer: Callable[[], IssuedOpaqueToken] | None = None,
        csrf_token_issuer: Callable[[], IssuedOpaqueToken] | None = None,
    ) -> None:
        if not callable(gate_current_read):
            raise TypeError("gate_current_read must be callable")
        if session_token_issuer is not None and not callable(
            session_token_issuer
        ):
            raise TypeError("session_token_issuer must be callable")
        if csrf_token_issuer is not None and not callable(csrf_token_issuer):
            raise TypeError("csrf_token_issuer must be callable")
        self._gate_current_read = gate_current_read
        self._session_token_issuer = session_token_issuer or issue_session_token
        self._csrf_token_issuer = csrf_token_issuer or issue_csrf_token

    def issue(
        self,
        session: Session,
        *,
        user_id: str,
        idle_timeout: timedelta,
        absolute_timeout: timedelta,
        policy_version: int = 1,
        device_name: str | None = None,
        user_agent_summary: str | None = None,
        ip_summary: str | None = None,
        created_from_challenge_id: str | None = None,
        rotated_from_session_id: str | None = None,
        now: datetime | None = None,
    ) -> IssuedAuthSession:
        if idle_timeout <= timedelta(0):
            raise ValueError("idle_timeout must be positive")
        if absolute_timeout <= timedelta(0):
            raise ValueError("absolute_timeout must be positive")
        if idle_timeout > absolute_timeout:
            raise ValueError("idle_timeout must not exceed absolute_timeout")
        if policy_version < 1:
            raise ValueError("policy_version must be positive")
        created_from_challenge_id = _optional_canonical_uuid(
            created_from_challenge_id,
            "created_from_challenge_id",
        )
        rotated_from_session_id = _optional_canonical_uuid(
            rotated_from_session_id,
            "rotated_from_session_id",
        )
        now = _as_utc(now or _utc_now())

        user = session.scalar(
            sa.select(User).where(User.id == user_id).with_for_update()
        )
        membership = session.scalar(
            sa.select(TenantMembership)
            .where(TenantMembership.claimed_user_id == user_id)
            .with_for_update()
        )
        if (
            user is None
            or user.status != "active"
            or membership is None
            or membership.status != "active"
            or membership.released_at is not None
        ):
            raise SessionIssueError("user membership is not eligible")
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == membership.tenant_id)
            .with_for_update()
        )
        if tenant is None:
            raise SessionIssueError("tenant is unavailable")
        gate = self._read_gate(session, tenant=tenant, now=now, issue=True)

        absolute_expires_at = now + absolute_timeout
        idle_expires_at = min(now + idle_timeout, absolute_expires_at)
        row, bearer, csrf = self._insert_with_token_collision_retry(
            session,
            user=user,
            tenant=tenant,
            policy_version=policy_version,
            idle_timeout=idle_timeout,
            created_at=now,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
            device_name=device_name,
            user_agent_summary=user_agent_summary,
            ip_summary=ip_summary,
            created_from_challenge_id=created_from_challenge_id,
            rotated_from_session_id=rotated_from_session_id,
        )
        auth = self._to_auth(row, user, membership, tenant, gate)
        return IssuedAuthSession(
            auth=auth,
            session_token=bearer.plaintext,
            csrf_token=csrf.plaintext,
        )

    def _insert_with_token_collision_retry(
        self,
        session: Session,
        *,
        user: User,
        tenant: Tenant,
        policy_version: int,
        idle_timeout: timedelta,
        created_at: datetime,
        idle_expires_at: datetime,
        absolute_expires_at: datetime,
        device_name: str | None,
        user_agent_summary: str | None,
        ip_summary: str | None,
        created_from_challenge_id: str | None,
        rotated_from_session_id: str | None,
    ) -> tuple[TenantUserSession, IssuedOpaqueToken, IssuedOpaqueToken]:
        for _attempt in range(3):
            bearer = self._session_token_issuer()
            csrf = self._csrf_token_issuer()
            if not isinstance(bearer, IssuedOpaqueToken) or not isinstance(
                csrf, IssuedOpaqueToken
            ):
                raise SessionIssueError("session token issuance failed")
            row = TenantUserSession(
                id=str(uuid4()),
                user_id=user.id,
                created_from_challenge_id=created_from_challenge_id,
                rotated_from_session_id=rotated_from_session_id,
                token_digest_sha256=bearer.digest_sha256,
                csrf_digest_sha256=csrf.digest_sha256,
                auth_version_at_issue=user.auth_version,
                tenant_access_version_at_issue=tenant.access_version,
                policy_version=policy_version,
                csrf_generation=1,
                idle_timeout_seconds=int(idle_timeout.total_seconds()),
                created_at=created_at,
                last_seen_at=created_at,
                idle_expires_at=idle_expires_at,
                absolute_expires_at=absolute_expires_at,
                device_name=device_name,
                user_agent_summary=user_agent_summary,
                first_ip_summary=ip_summary,
                last_ip_summary=ip_summary,
            )
            try:
                with session.begin_nested():
                    session.add(row)
                    session.flush()
            except IntegrityError:
                if created_from_challenge_id is not None and session.scalar(
                    sa.select(TenantUserSession.id).where(
                        TenantUserSession.created_from_challenge_id
                        == created_from_challenge_id
                    )
                ) is not None:
                    raise SessionIssueError(
                        "login challenge already issued a session"
                    ) from None
                token_collision = session.scalar(
                    sa.select(TenantUserSession.id).where(
                        sa.or_(
                            TenantUserSession.token_digest_sha256
                            == bearer.digest_sha256,
                            TenantUserSession.csrf_digest_sha256
                            == csrf.digest_sha256,
                        )
                    )
                )
                if token_collision is not None:
                    continue
                raise
            return row, bearer, csrf
        raise SessionIssueError("session token issuance failed")

    def resolve(
        self,
        session: Session,
        presented_token: object,
        *,
        now: datetime | None = None,
        ip_summary: str | None = None,
    ) -> AuthSession:
        now = _as_utc(now or _utc_now())
        try:
            token_digest = digest_session_token(presented_token)
        except (InvalidOpaqueTokenError, TypeError):
            raise SessionAuthenticationError() from None

        # Locate without a row lock, then lock identity -> tenant/lifecycle ->
        # session.  Suspension/deletion owns tenant -> session, so taking the
        # bearer lock before the tenant would create a lock-order cycle.
        located = session.scalar(
            sa.select(TenantUserSession).where(
                TenantUserSession.token_digest_sha256 == token_digest
            )
        )
        if located is None or not verify_session_token(
            presented_token, located.token_digest_sha256
        ):
            raise SessionAuthenticationError()
        user = session.scalar(
            sa.select(User).where(User.id == located.user_id).with_for_update()
        )
        membership = session.scalar(
            sa.select(TenantMembership)
            .where(TenantMembership.claimed_user_id == located.user_id)
            .with_for_update()
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
        gate = self._read_gate(
            session,
            tenant=tenant,
            now=now,
            issue=False,
        )
        row = session.scalar(
            sa.select(TenantUserSession)
            .where(TenantUserSession.id == located.id)
            .with_for_update()
        )
        if not self._is_current(row, user, membership, tenant, now):
            raise SessionAuthenticationError()

        row.last_seen_at = now
        row.idle_expires_at = min(
            now + timedelta(seconds=row.idle_timeout_seconds),
            _as_utc(row.absolute_expires_at),
        )
        if ip_summary is not None:
            row.last_ip_summary = ip_summary
        session.flush()
        return self._to_auth(row, user, membership, tenant, gate)

    def revoke_one(
        self,
        session: Session,
        *,
        user_id: str,
        target_session_id: str,
        reason_code: str,
        revoked_by_session_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        self._validate_reason(reason_code)
        now = _as_utc(now or _utc_now())
        target = session.scalar(
            sa.select(TenantUserSession)
            .where(
                TenantUserSession.id == target_session_id,
                TenantUserSession.user_id == user_id,
            )
            .with_for_update()
        )
        if target is None:
            raise SessionTargetNotFound()
        if revoked_by_session_id is not None:
            self._require_same_user_session(
                session, user_id=user_id, session_id=revoked_by_session_id
            )
        if target.revoked_at is not None:
            return False
        target.revoked_at = now
        target.revoked_reason_code = reason_code
        target.revoked_by_session_id = revoked_by_session_id
        session.flush()
        return True

    def verify_csrf(
        self,
        session: Session,
        *,
        auth: AuthSession,
        presented_csrf: object,
        now: datetime | None = None,
    ) -> EffectiveTenantGate:
        """Recheck current session facts and its independent CSRF material.

        Call this in the same control transaction that authorizes a mutation.
        A previously resolved ``AuthSession`` is only a coordination snapshot;
        it cannot override a later auth/access-version or membership change.
        """

        now = _as_utc(now or _utc_now())
        # As in resolve(), defer the session row lock until after the current
        # tenant lifecycle gate has been reduced.
        located = session.get(TenantUserSession, auth.session_id)
        user = (
            session.scalar(
                sa.select(User).where(User.id == located.user_id).with_for_update()
            )
            if located is not None
            else None
        )
        membership = (
            session.scalar(
                sa.select(TenantMembership)
                .where(TenantMembership.claimed_user_id == located.user_id)
                .with_for_update()
            )
            if located is not None
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
        try:
            gate = self._read_gate(
                session,
                tenant=tenant,
                now=now,
                issue=False,
            )
        except SessionAuthenticationError:
            raise CsrfAuthenticationError() from None
        row = (
            session.scalar(
                sa.select(TenantUserSession)
                .where(TenantUserSession.id == auth.session_id)
                .with_for_update()
            )
            if located is not None
            else None
        )
        snapshot_matches = bool(
            row is not None
            and user is not None
            and membership is not None
            and tenant is not None
            and auth.user_id == user.id
            and auth.membership_id == membership.id
            and auth.tenant_id == tenant.id
            and auth.role is TenantRole(membership.role_key)
            and auth.user_auth_version == user.auth_version
            and auth.tenant_access_version == tenant.access_version
            and auth.tenant_timezone == tenant.timezone
            and auth.csrf_generation == row.csrf_generation
        )
        if not (
            snapshot_matches
            and self._is_current(row, user, membership, tenant, now)
            and verify_csrf_token(presented_csrf, row.csrf_digest_sha256)
        ):
            raise CsrfAuthenticationError()
        return gate.gate

    def revoke_all(
        self,
        session: Session,
        *,
        user_id: str,
        reason_code: str,
        revoked_by_session_id: str | None = None,
        now: datetime | None = None,
    ) -> RevokeAllResult:
        self._validate_reason(reason_code)
        now = _as_utc(now or _utc_now())
        user = session.scalar(
            sa.select(User).where(User.id == user_id).with_for_update()
        )
        if user is None:
            raise SessionTargetNotFound()
        if revoked_by_session_id is not None:
            self._require_same_user_session(
                session, user_id=user_id, session_id=revoked_by_session_id
            )

        user.auth_version += 1
        result = session.execute(
            sa.update(TenantUserSession)
            .where(
                TenantUserSession.user_id == user_id,
                TenantUserSession.revoked_at.is_(None),
            )
            .values(
                revoked_at=now,
                revoked_reason_code=reason_code,
                revoked_by_session_id=revoked_by_session_id,
            )
            .execution_options(synchronize_session=False)
        )
        session.flush()
        return RevokeAllResult(
            revoked_count=result.rowcount,
            new_auth_version=user.auth_version,
        )

    def _is_current(
        self,
        row: TenantUserSession | None,
        user: User | None,
        membership: TenantMembership | None,
        tenant: Tenant | None,
        now: datetime,
    ) -> bool:
        return bool(
            row is not None
            and row.revoked_at is None
            and _as_utc(row.idle_expires_at) > now
            and _as_utc(row.absolute_expires_at) > now
            and user is not None
            and user.status == "active"
            and row.auth_version_at_issue == user.auth_version
            and membership is not None
            and membership.status == "active"
            and membership.released_at is None
            and membership.user_id == user.id
            and tenant is not None
            and membership.tenant_id == tenant.id
            and row.tenant_access_version_at_issue == tenant.access_version
        )

    def _to_auth(
        self,
        row: TenantUserSession,
        user: User,
        membership: TenantMembership,
        tenant: Tenant,
        gate: TenantGateDecision,
    ) -> AuthSession:
        return AuthSession(
            session_id=row.id,
            user_id=user.id,
            membership_id=membership.id,
            tenant_id=tenant.id,
            role=TenantRole(membership.role_key),
            user_auth_version=user.auth_version,
            tenant_access_version=tenant.access_version,
            tenant_timezone=tenant.timezone,
            tenant_status=tenant.status,
            effective_gate=gate.gate,
            csrf_generation=row.csrf_generation,
            idle_expires_at=row.idle_expires_at,
            absolute_expires_at=row.absolute_expires_at,
        )

    def _read_gate(
        self,
        session: Session,
        *,
        tenant: Tenant | None,
        now: datetime,
        issue: bool,
    ) -> TenantGateDecision:
        if tenant is None:
            if issue:
                raise SessionIssueError("tenant is unavailable")
            raise SessionAuthenticationError()
        try:
            decision = self._gate_current_read(session, tenant, now)
        except Exception:
            if issue:
                raise SessionIssueError("tenant gate is unavailable") from None
            raise SessionAuthenticationError() from None
        if (
            not isinstance(decision, TenantGateDecision)
            or decision.gate not in _AUTHENTICATED_SESSION_GATES
        ):
            if issue:
                raise SessionIssueError("tenant gate denies session issuance")
            raise SessionAuthenticationError()
        return decision

    def _require_same_user_session(
        self, session: Session, *, user_id: str, session_id: str
    ) -> None:
        owned = session.scalar(
            sa.select(TenantUserSession.id).where(
                TenantUserSession.id == session_id,
                TenantUserSession.user_id == user_id,
            )
        )
        if owned is None:
            raise SessionTargetNotFound()

    def _validate_reason(self, reason_code: str) -> None:
        if not reason_code or len(reason_code) > 64:
            raise ValueError("reason_code must contain 1 to 64 characters")


def _optional_canonical_uuid(value: str | None, field_name: str) -> str | None:
    if value is None:
        return None
    try:
        parsed = UUID(value)
    except (AttributeError, TypeError, ValueError):
        raise ValueError(f"{field_name} must be a canonical UUID") from None
    canonical = str(parsed)
    if canonical != value.lower():
        raise ValueError(f"{field_name} must be a canonical UUID")
    return canonical
