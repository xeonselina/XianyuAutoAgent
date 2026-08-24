"""Fail-closed composition of platform password, factor, throttle, and session."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.crypto import RootKeyRing
from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.models import PlatformAdmin

from .factor_service import (
    PlatformCurrentFactorService,
    PlatformFactorRejected,
    PlatformRecoveryCodeService,
    PlatformTotpService,
)
from .passwords import PlatformPasswordHasher
from .rate_limit import (
    PlatformAuthRateLimiter,
    PlatformRateLimitBlocked,
    PlatformRateLimitPolicy,
    PlatformRateLimitSubjects,
)
from .session_service import (
    IssuedPlatformAdminSession,
    PlatformAdminSessionService,
)
from .username import PlatformUsernameError, canonicalize_platform_username


_REQUEST_ID = re.compile(r"[A-Za-z0-9_.:-]{1,128}", re.ASCII)
_FACTOR_METHODS = frozenset({"totp", "recovery_code"})
_INVALID_USERNAME_SUBJECT = "invalid-platform-username"
_UNKNOWN_IP_SUBJECT = "unknown-platform-source"
_UNKNOWN_DEVICE_SUBJECT = "unknown-platform-device"


class PlatformLoginRejected(RuntimeError):
    """One fixed public rejection for identity, factor, and throttle failures."""

    code = "PLATFORM_CREDENTIAL_INVALID"

    def __init__(self) -> None:
        super().__init__("The platform administrator credential is invalid.")


@dataclass(frozen=True, slots=True)
class PlatformLoginPolicy:
    rate_limit: PlatformRateLimitPolicy
    idle_timeout: timedelta
    absolute_timeout: timedelta
    factor_max_age: timedelta
    session_policy_version: int
    allowed_totp_drift_steps: int

    def __post_init__(self) -> None:
        if not isinstance(self.rate_limit, PlatformRateLimitPolicy):
            raise TypeError("rate_limit must be a PlatformRateLimitPolicy")
        if not {"password", "mfa"}.issubset(self.rate_limit.scopes):
            raise ValueError("platform login rate-limit stages are incomplete")
        for field, value in (
            ("idle_timeout", self.idle_timeout),
            ("absolute_timeout", self.absolute_timeout),
            ("factor_max_age", self.factor_max_age),
        ):
            if not isinstance(value, timedelta):
                raise TypeError(f"{field} must be a timedelta")
            seconds = value.total_seconds()
            if not seconds.is_integer() or not 1 <= seconds <= 31_536_000:
                raise ValueError(f"{field} is invalid")
        if self.idle_timeout > self.absolute_timeout:
            raise ValueError("idle_timeout must not exceed absolute_timeout")
        if (
            isinstance(self.session_policy_version, bool)
            or not isinstance(self.session_policy_version, int)
            or self.session_policy_version < 1
        ):
            raise ValueError("session_policy_version is invalid")
        if (
            isinstance(self.allowed_totp_drift_steps, bool)
            or not isinstance(self.allowed_totp_drift_steps, int)
            or not 0 <= self.allowed_totp_drift_steps <= 1
        ):
            raise ValueError("allowed_totp_drift_steps is invalid")


@dataclass(frozen=True, slots=True)
class PlatformLoginAuditEvent:
    request_id: str
    platform_admin_id: str | None
    platform_session_id: str | None
    stage: str
    outcome: str
    factor_method: str | None
    occurred_at: datetime


class PlatformLoginAuditRecorder(Protocol):
    """Persist a credential-free immutable login event in the caller tx."""

    def record(
        self,
        session: Session,
        *,
        event: PlatformLoginAuditEvent,
    ) -> None: ...


class PlatformAdminLoginService:
    """Own the single transaction that may consume MFA and mint a bearer."""

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        root_key_provider: Callable[[Session], RootKeyRing],
        policy: PlatformLoginPolicy,
        audit_recorder: PlatformLoginAuditRecorder,
        password_hasher: PlatformPasswordHasher | None = None,
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
        self._password_hasher = password_hasher or PlatformPasswordHasher()
        self._factor_service = PlatformCurrentFactorService(
            totp_service=totp_service,
            recovery_code_service=recovery_code_service,
        )
        self._session_service = session_service or PlatformAdminSessionService()
        self._database_clock = database_clock

    def login(
        self,
        *,
        username: object,
        password: object,
        factor_method: object,
        factor_value: object,
        source_ip: object,
        device_id: object,
        request_id: str,
        device_name: str | None = None,
        user_agent_summary: str | None = None,
    ) -> IssuedPlatformAdminSession:
        """Authenticate without disclosing which stage or identity failed."""

        _validate_request_id(request_id)
        _validate_optional_summary(device_name, "device_name", 100)
        _validate_optional_summary(
            user_agent_summary, "user_agent_summary", 255
        )
        canonical_username, username_valid = _canonical_or_sentinel(username)
        subjects = PlatformRateLimitSubjects(
            username=canonical_username,
            ip=_subject_or_sentinel(
                source_ip, _UNKNOWN_IP_SUBJECT, maximum_length=64
            ),
            device=_subject_or_sentinel(
                device_id, _UNKNOWN_DEVICE_SUBJECT, maximum_length=255
            ),
        )
        public_factor_method = (
            factor_method
            if isinstance(factor_method, str)
            and factor_method in _FACTOR_METHODS
            else None
        )
        issued: IssuedPlatformAdminSession | None = None

        with self._control_database.transaction() as session:
            current_time = _as_utc(self._database_clock(session))
            key_ring = self._root_key_provider(session)
            if not isinstance(key_ring, RootKeyRing):
                raise RuntimeError("platform root key provider returned invalid data")
            rate_limiter = PlatformAuthRateLimiter(
                policy=self._policy.rate_limit,
                root_key=key_ring.active_key,
            )
            admin = (
                session.scalar(
                    sa.select(PlatformAdmin)
                    .where(
                        PlatformAdmin.username_canonical == canonical_username
                    )
                    .with_for_update()
                )
                if username_valid
                else None
            )
            try:
                rate_limiter.check(
                    session,
                    scope="password",
                    subjects=subjects,
                    now=current_time,
                )
            except PlatformRateLimitBlocked:
                self._record_audit(
                    session,
                    request_id=request_id,
                    admin=admin,
                    stage="password",
                    outcome="rate_limited",
                    factor_method=None,
                    now=current_time,
                )
            else:
                password_matches = self._password_hasher.verify(
                    password,
                    admin.password_hash_encoded if admin is not None else None,
                )
                if not (
                    username_valid
                    and admin is not None
                    and admin.status == "active"
                    and password_matches
                ):
                    rate_limiter.record_failure(
                        session,
                        scope="password",
                        subjects=subjects,
                        now=current_time,
                    )
                    self._record_audit(
                        session,
                        request_id=request_id,
                        admin=admin,
                        stage="password",
                        outcome="rejected",
                        factor_method=None,
                        now=current_time,
                    )
                else:
                    issued = self._verify_factor_and_issue(
                        session,
                        admin=admin,
                        key_ring=key_ring,
                        rate_limiter=rate_limiter,
                        password=password,
                        factor_method=public_factor_method,
                        factor_value=factor_value,
                        subjects=subjects,
                        request_id=request_id,
                        source_ip=subjects.ip,
                        device_name=device_name,
                        user_agent_summary=user_agent_summary,
                        now=current_time,
                    )

        if issued is None:
            raise PlatformLoginRejected()
        return issued

    def _verify_factor_and_issue(
        self,
        session: Session,
        *,
        admin: PlatformAdmin,
        key_ring: RootKeyRing,
        rate_limiter: PlatformAuthRateLimiter,
        password: object,
        factor_method: str | None,
        factor_value: object,
        subjects: PlatformRateLimitSubjects,
        request_id: str,
        source_ip: str,
        device_name: str | None,
        user_agent_summary: str | None,
        now: datetime,
    ) -> IssuedPlatformAdminSession | None:
        try:
            rate_limiter.check(
                session,
                scope="mfa",
                subjects=subjects,
                now=now,
            )
        except PlatformRateLimitBlocked:
            self._record_audit(
                session,
                request_id=request_id,
                admin=admin,
                stage="mfa",
                outcome="rate_limited",
                factor_method=factor_method,
                now=now,
            )
            return None

        try:
            factor = self._factor_service.verify(
                session,
                platform_admin_id=admin.id,
                factor_method=factor_method,
                factor_value=factor_value,
                key_ring=key_ring,
                now=now,
                allowed_totp_drift_steps=(
                    self._policy.allowed_totp_drift_steps
                ),
            )
        except PlatformFactorRejected:
            rate_limiter.record_failure(
                session,
                scope="mfa",
                subjects=subjects,
                now=now,
            )
            self._record_audit(
                session,
                request_id=request_id,
                admin=admin,
                stage="mfa",
                outcome="rejected",
                factor_method=factor_method,
                now=now,
            )
            return None

        if self._password_hasher.needs_rehash(admin.password_hash_encoded):
            replacement = self._password_hasher.hash(password)
            admin.password_hash_encoded = replacement.encoded
            admin.password_hash_algorithm = replacement.algorithm
            admin.password_hash_version = replacement.version
            admin.updated_at = now
            admin.row_version += 1

        issued = self._session_service.issue(
            session,
            factor=factor,
            idle_timeout=self._policy.idle_timeout,
            absolute_timeout=self._policy.absolute_timeout,
            factor_max_age=self._policy.factor_max_age,
            policy_version=self._policy.session_policy_version,
            device_name=device_name,
            user_agent_summary=user_agent_summary,
            ip_summary=source_ip,
            now=now,
        )
        self._record_audit(
            session,
            request_id=request_id,
            admin=admin,
            stage="complete",
            outcome="succeeded",
            factor_method=factor_method,
            platform_session_id=issued.auth.session_id,
            now=now,
        )
        return issued

    def _record_audit(
        self,
        session: Session,
        *,
        request_id: str,
        admin: PlatformAdmin | None,
        stage: str,
        outcome: str,
        factor_method: str | None,
        platform_session_id: str | None = None,
        now: datetime,
    ) -> None:
        self._audit_recorder.record(
            session,
            event=PlatformLoginAuditEvent(
                request_id=request_id,
                platform_admin_id=(admin.id if admin is not None else None),
                platform_session_id=platform_session_id,
                stage=stage,
                outcome=outcome,
                factor_method=factor_method,
                occurred_at=now,
            ),
        )


def _canonical_or_sentinel(username: object) -> tuple[str, bool]:
    try:
        return canonicalize_platform_username(username), True
    except PlatformUsernameError:
        return _INVALID_USERNAME_SUBJECT, False


def _subject_or_sentinel(
    value: object,
    sentinel: str,
    *,
    maximum_length: int,
) -> str:
    if (
        not isinstance(value, str)
        or not 1 <= len(value) <= maximum_length
        or "\x00" in value
    ):
        return sentinel
    return value


def _validate_request_id(request_id: str) -> None:
    if not isinstance(request_id, str) or _REQUEST_ID.fullmatch(request_id) is None:
        raise ValueError("request_id is invalid")


def _validate_optional_summary(
    value: str | None,
    field: str,
    maximum_length: int,
) -> None:
    if value is not None and (
        not isinstance(value, str) or len(value) > maximum_length
    ):
        raise ValueError(f"{field} is invalid")


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("control database did not return a datetime clock")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
