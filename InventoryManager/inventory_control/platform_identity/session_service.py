"""Opaque, caller-transactional sessions for independent platform admins."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.models.platform_identity import (
    PlatformAdmin,
    PlatformAdminRecoveryCode,
    PlatformAdminSession,
    PlatformAdminTotpCredential,
)

from .factor_service import VerifiedPlatformFactor
from .tokens import (
    PlatformCredentialError,
    digest_platform_session_token,
    issue_platform_csrf_token,
    issue_platform_session_token,
    verify_platform_csrf_token,
    verify_platform_session_token,
)


_REASON_CODE = re.compile(r"[A-Za-z0-9_.:-]{1,64}", re.ASCII)


class PlatformSessionAuthenticationError(RuntimeError):
    """Fixed rejection for every absent, malformed, stale, or expired session."""

    code = "PLATFORM_SESSION_INVALID"

    def __init__(self) -> None:
        super().__init__("The platform administrator session is invalid.")


class PlatformSessionIssueError(RuntimeError):
    """Fixed rejection when current platform identity facts forbid issuance."""

    code = "PLATFORM_SESSION_ISSUE_REJECTED"

    def __init__(self) -> None:
        super().__init__("The platform administrator session cannot be issued.")


class PlatformCsrfAuthenticationError(RuntimeError):
    """Fixed rejection for malformed, stale, or cross-session CSRF material."""

    code = "PLATFORM_CSRF_INVALID"

    def __init__(self) -> None:
        super().__init__("The platform administrator CSRF proof is invalid.")


class PlatformSessionTargetUnavailable(RuntimeError):
    """Do not disclose whether a requested session belongs to another admin."""

    code = "PLATFORM_SESSION_TARGET_UNAVAILABLE"

    def __init__(self) -> None:
        super().__init__("The platform administrator session is unavailable.")


@dataclass(frozen=True, slots=True)
class PlatformAuthSession:
    session_id: str
    platform_admin_id: str
    username_canonical: str
    admin_auth_version: int
    admin_setup_version: int
    csrf_generation: int
    mfa_method: str
    mfa_verified_at: datetime
    idle_expires_at: datetime
    absolute_expires_at: datetime


@dataclass(frozen=True, slots=True, repr=False)
class IssuedPlatformAdminSession:
    auth: PlatformAuthSession
    session_token: str
    csrf_token: str

    def __repr__(self) -> str:
        return "IssuedPlatformAdminSession(<redacted>)"


@dataclass(frozen=True, slots=True)
class PlatformRevokeAllResult:
    revoked_count: int
    new_auth_version: int


class PlatformAdminSessionService:
    """Operate platform sessions without committing the caller's transaction."""

    def issue(
        self,
        session: Session,
        *,
        factor: VerifiedPlatformFactor,
        idle_timeout: timedelta,
        absolute_timeout: timedelta,
        factor_max_age: timedelta = timedelta(minutes=5),
        policy_version: int = 1,
        device_name: str | None = None,
        user_agent_summary: str | None = None,
        ip_summary: str | None = None,
        now: datetime | None = None,
    ) -> IssuedPlatformAdminSession:
        idle_seconds = _timeout_seconds(idle_timeout, "idle_timeout")
        absolute_seconds = _timeout_seconds(absolute_timeout, "absolute_timeout")
        if idle_seconds > absolute_seconds:
            raise ValueError("idle_timeout must not exceed absolute_timeout")
        max_factor_age_seconds = _timeout_seconds(
            factor_max_age, "factor_max_age"
        )
        if isinstance(policy_version, bool) or policy_version < 1:
            raise ValueError("policy_version must be positive")
        _validate_optional_summary(device_name, "device_name", 100)
        _validate_optional_summary(user_agent_summary, "user_agent_summary", 255)
        _validate_optional_summary(ip_summary, "ip_summary", 64)
        current_time = _as_utc(now or _utc_now())

        if not isinstance(factor, VerifiedPlatformFactor):
            raise PlatformSessionIssueError()
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == factor.platform_admin_id)
            .with_for_update()
        )
        if (
            admin is None
            or admin.status != "active"
            or admin.password_hash_encoded is None
            or admin.password_hash_algorithm is None
            or admin.password_hash_version is None
            or not _factor_time_is_current(
                factor.verified_at,
                now=current_time,
                max_age_seconds=max_factor_age_seconds,
            )
            or not self._factor_record_is_current(session, admin, factor)
        ):
            raise PlatformSessionIssueError()

        # The proof stays available through validation but is consumed before any
        # bearer is minted. It cannot issue a second session in this process.
        try:
            factor._claim()
        except RuntimeError:
            raise PlatformSessionIssueError() from None

        bearer = issue_platform_session_token()
        csrf = issue_platform_csrf_token()
        absolute_expires_at = current_time + timedelta(seconds=absolute_seconds)
        idle_expires_at = min(
            current_time + timedelta(seconds=idle_seconds),
            absolute_expires_at,
        )
        row = PlatformAdminSession(
            platform_admin_id=admin.id,
            token_digest_sha256=bearer.digest_sha256,
            csrf_digest_sha256=csrf.digest_sha256,
            auth_version_at_issue=admin.auth_version,
            setup_version_at_issue=admin.setup_version,
            mfa_method=factor.method,
            mfa_verified_at=_as_utc(factor.verified_at),
            totp_credential_id=(
                factor.factor_record_id if factor.method == "totp" else None
            ),
            totp_time_step=(
                factor.totp_time_step if factor.method == "totp" else None
            ),
            recovery_code_id=(
                factor.factor_record_id
                if factor.method == "recovery_code"
                else None
            ),
            policy_version=policy_version,
            csrf_generation=1,
            idle_timeout_seconds=idle_seconds,
            created_at=current_time,
            last_seen_at=current_time,
            idle_expires_at=idle_expires_at,
            absolute_expires_at=absolute_expires_at,
            device_name=device_name,
            user_agent_summary=user_agent_summary,
            first_ip_summary=ip_summary,
            last_ip_summary=ip_summary,
        )
        session.add(row)
        session.flush()
        return IssuedPlatformAdminSession(
            auth=self._to_auth(row, admin),
            session_token=bearer.plaintext,
            csrf_token=csrf.plaintext,
        )

    def resolve(
        self,
        session: Session,
        presented_token: object,
        *,
        ip_summary: str | None = None,
        now: datetime | None = None,
    ) -> PlatformAuthSession:
        _validate_optional_summary(ip_summary, "ip_summary", 64)
        current_time = _as_utc(now or _utc_now())
        try:
            token_digest = digest_platform_session_token(presented_token)
        except (PlatformCredentialError, TypeError, ValueError):
            token_digest = bytes(32)
            token_has_shape = False
        else:
            token_has_shape = True

        summary = session.execute(
            sa.select(
                PlatformAdminSession.id,
                PlatformAdminSession.platform_admin_id,
            ).where(PlatformAdminSession.token_digest_sha256 == token_digest)
        ).one_or_none()
        if summary is None:
            raise PlatformSessionAuthenticationError()

        # Every mutating path uses the same global order: admin, then session.
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == summary.platform_admin_id)
            .with_for_update()
        )
        row = session.scalar(
            sa.select(PlatformAdminSession)
            .where(
                PlatformAdminSession.id == summary.id,
                PlatformAdminSession.platform_admin_id
                == summary.platform_admin_id,
            )
            .with_for_update()
        )
        if not (
            token_has_shape
            and row is not None
            and admin is not None
            and verify_platform_session_token(
                presented_token, row.token_digest_sha256
            )
            and self._is_current(row, admin, current_time)
        ):
            raise PlatformSessionAuthenticationError()

        row.last_seen_at = current_time
        row.idle_expires_at = min(
            current_time + timedelta(seconds=row.idle_timeout_seconds),
            _as_utc(row.absolute_expires_at),
        )
        if ip_summary is not None:
            row.last_ip_summary = ip_summary
        session.flush()
        return self._to_auth(row, admin)

    def verify_csrf(
        self,
        session: Session,
        *,
        auth: PlatformAuthSession,
        presented_csrf: object,
        now: datetime | None = None,
    ) -> None:
        current_time = _as_utc(now or _utc_now())
        if not isinstance(auth, PlatformAuthSession):
            raise PlatformCsrfAuthenticationError()
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == auth.platform_admin_id)
            .with_for_update()
        )
        row = session.scalar(
            sa.select(PlatformAdminSession)
            .where(
                PlatformAdminSession.id == auth.session_id,
                PlatformAdminSession.platform_admin_id
                == auth.platform_admin_id,
            )
            .with_for_update()
        )
        snapshot_matches = bool(
            admin is not None
            and row is not None
            and auth.username_canonical == admin.username_canonical
            and auth.admin_auth_version == admin.auth_version
            and auth.admin_setup_version == admin.setup_version
            and auth.csrf_generation == row.csrf_generation
            and auth.mfa_method == row.mfa_method
        )
        if not (
            snapshot_matches
            and self._is_current(row, admin, current_time)
            and verify_platform_csrf_token(
                presented_csrf, row.csrf_digest_sha256
            )
        ):
            raise PlatformCsrfAuthenticationError()

    def revoke_one(
        self,
        session: Session,
        *,
        platform_admin_id: str,
        target_session_id: str,
        reason_code: str,
        revoked_by_session_id: str | None = None,
        now: datetime | None = None,
    ) -> bool:
        _validate_reason(reason_code)
        current_time = _as_utc(now or _utc_now())
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == platform_admin_id)
            .with_for_update()
        )
        if admin is None:
            raise PlatformSessionTargetUnavailable()
        requested_ids = {target_session_id}
        if revoked_by_session_id is not None:
            requested_ids.add(revoked_by_session_id)
        rows = list(
            session.scalars(
                sa.select(PlatformAdminSession)
                .where(PlatformAdminSession.id.in_(requested_ids))
                .order_by(PlatformAdminSession.id)
                .with_for_update()
            )
        )
        by_id = {row.id: row for row in rows}
        target = by_id.get(target_session_id)
        actor = (
            by_id.get(revoked_by_session_id)
            if revoked_by_session_id is not None
            else None
        )
        if (
            target is None
            or target.platform_admin_id != admin.id
            or (
                revoked_by_session_id is not None
                and (actor is None or actor.platform_admin_id != admin.id)
            )
        ):
            raise PlatformSessionTargetUnavailable()
        if target.revoked_at is not None:
            return False
        target.revoked_at = current_time
        target.revoked_reason_code = reason_code
        target.revoked_by_session_id = revoked_by_session_id
        session.flush()
        return True

    def revoke_all(
        self,
        session: Session,
        *,
        platform_admin_id: str,
        reason_code: str,
        revoked_by_session_id: str | None = None,
        now: datetime | None = None,
    ) -> PlatformRevokeAllResult:
        _validate_reason(reason_code)
        current_time = _as_utc(now or _utc_now())
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == platform_admin_id)
            .with_for_update()
        )
        if admin is None:
            raise PlatformSessionTargetUnavailable()
        rows = list(
            session.scalars(
                sa.select(PlatformAdminSession)
                .where(PlatformAdminSession.platform_admin_id == admin.id)
                .order_by(PlatformAdminSession.id)
                .with_for_update()
            )
        )
        by_id = {row.id: row for row in rows}
        if revoked_by_session_id is not None:
            actor = by_id.get(revoked_by_session_id)
            if actor is None or actor.platform_admin_id != admin.id:
                raise PlatformSessionTargetUnavailable()
        admin.auth_version += 1
        admin.row_version += 1
        admin.updated_at = current_time
        revoked_count = 0
        for row in rows:
            if row.revoked_at is None:
                row.revoked_at = current_time
                row.revoked_reason_code = reason_code
                row.revoked_by_session_id = revoked_by_session_id
                revoked_count += 1
        session.flush()
        return PlatformRevokeAllResult(
            revoked_count=revoked_count,
            new_auth_version=admin.auth_version,
        )

    @staticmethod
    def _factor_record_is_current(
        session: Session,
        admin: PlatformAdmin,
        factor: VerifiedPlatformFactor,
    ) -> bool:
        if factor.method == "totp" and factor.totp_time_step is not None:
            credential = session.scalar(
                sa.select(PlatformAdminTotpCredential)
                .where(PlatformAdminTotpCredential.id == factor.factor_record_id)
                .with_for_update()
            )
            return bool(
                credential is not None
                and credential.platform_admin_id == admin.id
                and credential.status == "confirmed"
                and credential.generation == admin.totp_generation
                and credential.last_accepted_time_step == factor.totp_time_step
            )
        if factor.method == "recovery_code" and factor.totp_time_step is None:
            recovery_code = session.scalar(
                sa.select(PlatformAdminRecoveryCode)
                .where(PlatformAdminRecoveryCode.id == factor.factor_record_id)
                .with_for_update()
            )
            return bool(
                recovery_code is not None
                and recovery_code.platform_admin_id == admin.id
                and recovery_code.generation == admin.recovery_code_generation
                and recovery_code.state == "consumed"
                and recovery_code.consumed_at is not None
                and _as_utc(recovery_code.consumed_at)
                == _as_utc(factor.verified_at)
            )
        return False

    @staticmethod
    def _is_current(
        row: PlatformAdminSession,
        admin: PlatformAdmin,
        now: datetime,
    ) -> bool:
        return bool(
            row.revoked_at is None
            and _as_utc(row.created_at) <= now
            and _as_utc(row.last_seen_at) <= now
            and _as_utc(row.idle_expires_at) > now
            and _as_utc(row.absolute_expires_at) > now
            and admin.status == "active"
            and row.platform_admin_id == admin.id
            and row.auth_version_at_issue == admin.auth_version
            and row.setup_version_at_issue == admin.setup_version
        )

    @staticmethod
    def _to_auth(
        row: PlatformAdminSession, admin: PlatformAdmin
    ) -> PlatformAuthSession:
        return PlatformAuthSession(
            session_id=row.id,
            platform_admin_id=admin.id,
            username_canonical=admin.username_canonical,
            admin_auth_version=admin.auth_version,
            admin_setup_version=admin.setup_version,
            csrf_generation=row.csrf_generation,
            mfa_method=row.mfa_method,
            mfa_verified_at=row.mfa_verified_at,
            idle_expires_at=row.idle_expires_at,
            absolute_expires_at=row.absolute_expires_at,
        )


def _timeout_seconds(value: timedelta, field: str) -> int:
    if not isinstance(value, timedelta):
        raise TypeError(f"{field} must be a timedelta")
    seconds = value.total_seconds()
    if seconds < 1 or seconds > 31_536_000 or not seconds.is_integer():
        raise ValueError(f"{field} must be whole seconds between 1 and 31536000")
    return int(seconds)


def _factor_time_is_current(
    verified_at: datetime,
    *,
    now: datetime,
    max_age_seconds: int,
) -> bool:
    try:
        normalized = _as_utc(verified_at)
    except (AttributeError, TypeError, ValueError):
        return False
    return normalized <= now < normalized + timedelta(seconds=max_age_seconds)


def _validate_optional_summary(
    value: str | None, field: str, maximum_length: int
) -> None:
    if value is not None and (
        not isinstance(value, str) or len(value) > maximum_length
    ):
        raise ValueError(f"{field} is invalid")


def _validate_reason(reason_code: str) -> None:
    if not isinstance(reason_code, str) or _REASON_CODE.fullmatch(reason_code) is None:
        raise ValueError("reason_code is invalid")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
