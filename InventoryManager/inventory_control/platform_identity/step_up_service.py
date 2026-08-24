"""Recent-MFA session rotation for D52 and D58 platform actions."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.crypto import RootKeyRing
from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.models import PlatformAdminSession

from .factor_service import (
    PlatformCurrentFactorService,
    PlatformFactorRejected,
    PlatformRecoveryCodeService,
    PlatformTotpService,
)
from .login_service import PlatformLoginPolicy
from .rate_limit import (
    PlatformAuthRateLimiter,
    PlatformRateLimitBlocked,
    PlatformRateLimitSubjects,
)
from .session_service import (
    IssuedPlatformAdminSession,
    PlatformAdminSessionService,
    PlatformCsrfAuthenticationError,
    PlatformSessionAuthenticationError,
)


_REQUEST_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}", re.ASCII)
_FACTOR_METHODS = frozenset({"totp", "recovery_code"})


class PlatformStepUpRejected(RuntimeError):
    """One fixed rejection for an authenticated but invalid MFA attempt."""

    code = "PLATFORM_FACTOR_INVALID"

    def __init__(self) -> None:
        super().__init__("The platform administrator factor is invalid.")


@dataclass(frozen=True, slots=True)
class PlatformStepUpAuditEvent:
    request_id: str
    platform_admin_id: str
    actor_session_id: str
    replacement_session_id: str | None
    outcome: str
    factor_method: str | None
    occurred_at: datetime


class PlatformStepUpAuditRecorder(Protocol):
    def record(
        self,
        session: Session,
        *,
        event: PlatformStepUpAuditEvent,
    ) -> None: ...


class PlatformAdminStepUpService:
    """Verify current MFA and rotate, rather than mutate, the platform session.

    Platform session rows intentionally require ``mfa_verified_at <= created_at``.
    A successful recent-MFA operation therefore creates a fresh bearer/CSRF row,
    preserves the original absolute-expiry ceiling, and revokes the old row in
    the same control transaction as factor replay protection and audit.
    """

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        root_key_provider: Callable[[Session], RootKeyRing],
        policy: PlatformLoginPolicy,
        audit_recorder: PlatformStepUpAuditRecorder,
        totp_service: PlatformTotpService | None = None,
        recovery_code_service: PlatformRecoveryCodeService | None = None,
        session_service: PlatformAdminSessionService | None = None,
        database_clock: Callable[[Session], object] = read_database_utc_value,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        if not callable(root_key_provider):
            raise TypeError("root_key_provider must be callable")
        if not isinstance(policy, PlatformLoginPolicy):
            raise TypeError("policy must be a PlatformLoginPolicy")
        if not callable(getattr(audit_recorder, "record", None)):
            raise TypeError("audit_recorder must implement record")
        if not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._control_database = control_database
        self._root_key_provider = root_key_provider
        self._policy = policy
        self._audit_recorder = audit_recorder
        self._factor_service = PlatformCurrentFactorService(
            totp_service=totp_service,
            recovery_code_service=recovery_code_service,
        )
        self._session_service = session_service or PlatformAdminSessionService()
        self._database_clock = database_clock

    def step_up(
        self,
        *,
        presented_session_token: object,
        presented_csrf: object,
        factor_method: object,
        factor_value: object,
        source_ip: str,
        device_id: str,
        request_id: str,
        user_agent_summary: str | None = None,
    ) -> IssuedPlatformAdminSession:
        if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
            raise ValueError("request_id is invalid")
        if not isinstance(source_ip, str) or not 1 <= len(source_ip) <= 64:
            raise ValueError("source_ip is invalid")
        if not isinstance(device_id, str) or not 1 <= len(device_id) <= 255:
            raise ValueError("device_id is invalid")
        if user_agent_summary is not None and (
            not isinstance(user_agent_summary, str)
            or len(user_agent_summary) > 255
        ):
            raise ValueError("user_agent_summary is invalid")
        selected_method = (
            factor_method
            if isinstance(factor_method, str) and factor_method in _FACTOR_METHODS
            else None
        )
        issued: IssuedPlatformAdminSession | None = None

        with self._control_database.transaction() as session:
            now = _as_utc(self._database_clock(session))
            key_ring = self._root_key_provider(session)
            if not isinstance(key_ring, RootKeyRing):
                raise RuntimeError("platform root key provider returned invalid data")
            auth = self._session_service.resolve(
                session,
                presented_session_token,
                ip_summary=source_ip,
                now=now,
            )
            self._session_service.verify_csrf(
                session,
                auth=auth,
                presented_csrf=presented_csrf,
                now=now,
            )
            old_row = session.scalar(
                sa.select(PlatformAdminSession)
                .where(
                    PlatformAdminSession.id == auth.session_id,
                    PlatformAdminSession.platform_admin_id
                    == auth.platform_admin_id,
                )
                .with_for_update()
            )
            if old_row is None or old_row.revoked_at is not None:
                raise PlatformSessionAuthenticationError()

            subjects = PlatformRateLimitSubjects(
                username=auth.username_canonical,
                ip=source_ip,
                device=device_id,
            )
            limiter = PlatformAuthRateLimiter(
                policy=self._policy.rate_limit,
                root_key=key_ring.active_key,
            )
            try:
                limiter.check(
                    session,
                    scope="mfa",
                    subjects=subjects,
                    now=now,
                )
            except PlatformRateLimitBlocked:
                self._record(
                    session,
                    auth=auth,
                    request_id=request_id,
                    outcome="rate_limited",
                    factor_method=selected_method,
                    replacement_session_id=None,
                    now=now,
                )
            else:
                try:
                    factor = self._factor_service.verify(
                        session,
                        platform_admin_id=auth.platform_admin_id,
                        factor_method=selected_method,
                        factor_value=factor_value,
                        key_ring=key_ring,
                        now=now,
                        allowed_totp_drift_steps=(
                            self._policy.allowed_totp_drift_steps
                        ),
                    )
                except PlatformFactorRejected:
                    limiter.record_failure(
                        session,
                        scope="mfa",
                        subjects=subjects,
                        now=now,
                    )
                    self._record(
                        session,
                        auth=auth,
                        request_id=request_id,
                        outcome="rejected",
                        factor_method=selected_method,
                        replacement_session_id=None,
                        now=now,
                    )
                else:
                    remaining_seconds = int(
                        (_as_utc(auth.absolute_expires_at) - now).total_seconds()
                    )
                    if remaining_seconds < 1:
                        raise PlatformSessionAuthenticationError()
                    absolute_seconds = min(
                        remaining_seconds,
                        int(self._policy.absolute_timeout.total_seconds()),
                    )
                    idle_seconds = min(
                        absolute_seconds,
                        int(self._policy.idle_timeout.total_seconds()),
                    )
                    issued = self._session_service.issue(
                        session,
                        factor=factor,
                        idle_timeout=timedelta(seconds=idle_seconds),
                        absolute_timeout=timedelta(seconds=absolute_seconds),
                        factor_max_age=self._policy.factor_max_age,
                        policy_version=self._policy.session_policy_version,
                        device_name=old_row.device_name,
                        user_agent_summary=(
                            user_agent_summary or old_row.user_agent_summary
                        ),
                        ip_summary=source_ip,
                        now=now,
                    )
                    old_row.revoked_at = now
                    old_row.revoked_reason_code = "step_up_rotated"
                    old_row.revoked_by_session_id = issued.auth.session_id
                    self._record(
                        session,
                        auth=auth,
                        request_id=request_id,
                        outcome="succeeded",
                        factor_method=selected_method,
                        replacement_session_id=issued.auth.session_id,
                        now=now,
                    )
                    session.flush()

        if issued is None:
            raise PlatformStepUpRejected()
        return issued

    def _record(
        self,
        session: Session,
        *,
        auth,
        request_id: str,
        outcome: str,
        factor_method: str | None,
        replacement_session_id: str | None,
        now: datetime,
    ) -> None:
        self._audit_recorder.record(
            session,
            event=PlatformStepUpAuditEvent(
                request_id=request_id,
                platform_admin_id=auth.platform_admin_id,
                actor_session_id=auth.session_id,
                replacement_session_id=replacement_session_id,
                outcome=outcome,
                factor_method=factor_method,
                occurred_at=now,
            ),
        )


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("control database did not return a datetime clock")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "PlatformAdminStepUpService",
    "PlatformStepUpAuditEvent",
    "PlatformStepUpAuditRecorder",
    "PlatformStepUpRejected",
]
