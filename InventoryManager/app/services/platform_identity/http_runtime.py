"""Control-database-only HTTP runtime for platform login and session logout."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta, timezone
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable
from uuid import UUID, uuid4

from flask import Request, current_app
import sqlalchemy as sa

from inventory_control.crypto import SqlAlchemyRootKeyRegistry
from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.domain import Capability
from inventory_control.models import (
    PlatformAdminSession,
    PlatformAdminTotpCredential,
    PlatformAuditLog,
)
from inventory_control.platform_directory import (
    PlatformTenantDirectoryInputError,
    PlatformTenantDirectoryService,
    PlatformTenantDirectoryTargetUnavailable,
)
from inventory_control.platform_http import (
    PLATFORM_CSRF_HEADER_NAME,
    PLATFORM_SESSION_COOKIE_NAME,
    PLATFORM_SETUP_HEADER_NAME,
    PlatformAuthenticationRequired,
    PlatformCsrfDenied,
    PlatformHttpBoundary,
    PlatformHttpError,
    resolve_platform_device_id,
)
from inventory_control.platform_identity import (
    IssuedPlatformAdminSession,
    PlatformAdminLoginService,
    PlatformAdminSessionService,
    PlatformAdminSetupService,
    PlatformAdminStepUpService,
    PlatformAuthRateLimiter,
    PlatformCurrentFactorService,
    PlatformCsrfAuthenticationError,
    PlatformFactorRejected,
    PlatformLoginPolicy,
    PlatformLoginRejected,
    PlatformPasswordError,
    PlatformPasswordHasher,
    PlatformRecoveryCodeService,
    PlatformRateLimitBlocked,
    PlatformRateLimitSubjects,
    PlatformSessionTargetUnavailable,
    PlatformSessionAuthenticationError,
    PlatformStepUpRejected,
    PlatformTotpService,
    SqlAlchemyPlatformLoginAuditRecorder,
    SqlAlchemyPlatformStepUpAuditRecorder,
    activate_admin_if_ready,
)
from inventory_control.sms import TrustedSourceBucket


PLATFORM_IDENTITY_HTTP_RUNTIME_EXTENSION = (
    "inventory_platform_identity_http_runtime"
)
_PLATFORM_FACTOR_METHODS = frozenset({"totp", "recovery_code"})


@dataclass(frozen=True, slots=True, repr=False)
class PlatformLoginRuntimeSettings:
    policy: PlatformLoginPolicy
    trusted_source_resolver: object
    device_cookie_max_age_seconds: int
    setup_allowed_totp_drift_steps: int
    recovery_code_count: int
    recovery_code_ttl: timedelta | None

    def __post_init__(self) -> None:
        if not isinstance(self.policy, PlatformLoginPolicy):
            raise TypeError("policy must be a PlatformLoginPolicy")
        if not callable(self.trusted_source_resolver):
            raise TypeError("trusted_source_resolver must be callable")
        if (
            isinstance(self.device_cookie_max_age_seconds, bool)
            or not isinstance(self.device_cookie_max_age_seconds, int)
            or not 1 <= self.device_cookie_max_age_seconds <= 31_536_000
        ):
            raise ValueError("device Cookie max age is invalid")
        if (
            isinstance(self.setup_allowed_totp_drift_steps, bool)
            or not isinstance(self.setup_allowed_totp_drift_steps, int)
            or not 0 <= self.setup_allowed_totp_drift_steps <= 1
        ):
            raise ValueError("setup TOTP drift is invalid")
        if (
            isinstance(self.recovery_code_count, bool)
            or not isinstance(self.recovery_code_count, int)
            or not 6 <= self.recovery_code_count <= 20
        ):
            raise ValueError("recovery code count is invalid")
        if self.recovery_code_ttl is not None and (
            not isinstance(self.recovery_code_ttl, timedelta)
            or self.recovery_code_ttl <= timedelta(0)
        ):
            raise ValueError("recovery code TTL is invalid")

    def __repr__(self) -> str:
        return "PlatformLoginRuntimeSettings(<explicit-policy>)"


@dataclass(frozen=True, slots=True, repr=False)
class PlatformLoginHttpResult:
    issued: IssuedPlatformAdminSession
    device_id: str
    set_device_cookie: bool
    device_cookie_max_age_seconds: int

    def __repr__(self) -> str:
        return "PlatformLoginHttpResult(<credentials-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class PlatformCredentialHttpResult:
    data: Mapping[str, object]
    device_id: str
    set_device_cookie: bool
    device_cookie_max_age_seconds: int
    clear_session_cookie: bool = False

    def __repr__(self) -> str:
        return "PlatformCredentialHttpResult(<credentials-redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class _FactorActionResult:
    data: Mapping[str, object]
    result_count: int
    clear_session_cookie: bool = False


class PlatformIdentityRuntimeUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("PLATFORM_IDENTITY_RUNTIME_UNAVAILABLE")


class PlatformLoginHttpRejected(PlatformHttpError):
    status_code = 401
    code = "PLATFORM_CREDENTIAL_INVALID"
    public_message = "The platform administrator credential is invalid."

    def __init__(
        self,
        *,
        device_id: str,
        set_device_cookie: bool,
        device_cookie_max_age_seconds: int,
    ) -> None:
        super().__init__()
        self.device_id = device_id
        self.set_device_cookie = set_device_cookie
        self.device_cookie_max_age_seconds = device_cookie_max_age_seconds


class PlatformSetupHttpRejected(PlatformHttpError):
    status_code = 401
    code = "PLATFORM_SETUP_INVALID"
    public_message = "The platform setup credential or state is invalid."


class PlatformStepUpHttpRejected(PlatformHttpError):
    status_code = 401
    code = "PLATFORM_FACTOR_INVALID"
    public_message = "The platform administrator factor is invalid."

    def __init__(
        self,
        *,
        device_id: str,
        set_device_cookie: bool,
        device_cookie_max_age_seconds: int,
    ) -> None:
        super().__init__()
        self.device_id = device_id
        self.set_device_cookie = set_device_cookie
        self.device_cookie_max_age_seconds = device_cookie_max_age_seconds


class PlatformSessionTargetHttpUnavailable(PlatformHttpError):
    status_code = 404
    code = "PLATFORM_SESSION_TARGET_UNAVAILABLE"
    public_message = "The platform session target is unavailable."


class PlatformTenantQueryHttpInvalid(PlatformHttpError):
    status_code = 400
    code = "PLATFORM_TENANT_QUERY_INVALID"
    public_message = "The platform tenant query is invalid."


class PlatformTenantTargetHttpUnavailable(PlatformHttpError):
    status_code = 404
    code = "PLATFORM_TENANT_TARGET_UNAVAILABLE"
    public_message = "The platform tenant target is unavailable."


@runtime_checkable
class PlatformIdentityHttpRuntime(Protocol):
    def login(
        self,
        *,
        flask_request: Request,
        username: object,
        password: object,
        factor_method: object,
        factor_value: object,
        device_name: object = None,
    ) -> PlatformLoginHttpResult: ...

    def session_status(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]: ...

    def step_up(
        self,
        *,
        flask_request: Request,
        factor_method: object,
        factor_value: object,
    ) -> PlatformLoginHttpResult: ...

    def logout(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]: ...

    def consume_setup_token(
        self,
        *,
        flask_request: Request,
        setup_token: object,
    ) -> Mapping[str, object]: ...

    def set_setup_password(
        self,
        *,
        flask_request: Request,
        password: object,
    ) -> Mapping[str, object]: ...

    def begin_setup_totp(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]: ...

    def complete_setup(
        self,
        *,
        flask_request: Request,
        credential_id: object,
        totp_code: object,
    ) -> Mapping[str, object]: ...

    def begin_totp_replacement(
        self,
        *,
        flask_request: Request,
        factor_method: object,
        factor_value: object,
    ) -> PlatformCredentialHttpResult: ...

    def complete_totp_replacement(
        self,
        *,
        flask_request: Request,
        credential_id: object,
        totp_code: object,
    ) -> PlatformCredentialHttpResult: ...

    def regenerate_recovery_codes(
        self,
        *,
        flask_request: Request,
        factor_method: object,
        factor_value: object,
    ) -> PlatformCredentialHttpResult: ...

    def list_sessions(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]: ...

    def revoke_session(
        self,
        *,
        flask_request: Request,
        target_session_id: object,
    ) -> Mapping[str, object]: ...

    def revoke_all_sessions(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]: ...

    def list_tenants(
        self,
        *,
        flask_request: Request,
        query_arguments: object,
    ) -> Mapping[str, object]: ...

    def get_tenant(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
    ) -> Mapping[str, object]: ...


class SqlAlchemyPlatformIdentityHttpRuntime:
    """Keep every platform identity request outside tenant schemas."""

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        root_key_directory: str | os.PathLike[str],
        login_settings: PlatformLoginRuntimeSettings | None = None,
        session_service: PlatformAdminSessionService | None = None,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        try:
            root_directory = os.fspath(root_key_directory)
        except TypeError:
            raise TypeError("root_key_directory must be an absolute path") from None
        if (
            not isinstance(root_directory, str)
            or not Path(root_directory).is_absolute()
        ):
            raise ValueError("root_key_directory must be an absolute path")
        if login_settings is not None and not isinstance(
            login_settings, PlatformLoginRuntimeSettings
        ):
            raise TypeError(
                "login_settings must be PlatformLoginRuntimeSettings or None"
            )
        selected_sessions = session_service or PlatformAdminSessionService()
        if not isinstance(selected_sessions, PlatformAdminSessionService):
            raise TypeError(
                "session_service must be a PlatformAdminSessionService"
            )
        self._control_database = control_database
        self._root_key_directory = root_directory
        self._login_settings = login_settings
        self._session_service = selected_sessions
        self._boundary = PlatformHttpBoundary(selected_sessions)
        self._setup_service = PlatformAdminSetupService()
        self._password_hasher = PlatformPasswordHasher()
        self._totp_service = PlatformTotpService()
        self._recovery_code_service = PlatformRecoveryCodeService()
        self._current_factor_service = PlatformCurrentFactorService(
            totp_service=self._totp_service,
            recovery_code_service=self._recovery_code_service,
        )
        self._tenant_directory = PlatformTenantDirectoryService()
        self._login_service = (
            PlatformAdminLoginService(
                control_database=control_database,
                root_key_provider=lambda session: SqlAlchemyRootKeyRegistry(
                    session=session
                ).load(root_directory),
                policy=login_settings.policy,
                audit_recorder=SqlAlchemyPlatformLoginAuditRecorder(),
                session_service=selected_sessions,
            )
            if login_settings is not None
            else None
        )
        self._step_up_service = (
            PlatformAdminStepUpService(
                control_database=control_database,
                root_key_provider=lambda session: SqlAlchemyRootKeyRegistry(
                    session=session
                ).load(root_directory),
                policy=login_settings.policy,
                audit_recorder=SqlAlchemyPlatformStepUpAuditRecorder(),
                session_service=selected_sessions,
            )
            if login_settings is not None
            else None
        )

    @property
    def control_database(self) -> ControlDatabase:
        return self._control_database

    @property
    def boundary(self) -> PlatformHttpBoundary:
        return self._boundary

    @property
    def login_is_configured(self) -> bool:
        return self._login_service is not None

    def login(
        self,
        *,
        flask_request: Request,
        username: object,
        password: object,
        factor_method: object,
        factor_value: object,
        device_name: object = None,
    ) -> PlatformLoginHttpResult:
        if self._login_service is None or self._login_settings is None:
            raise PlatformIdentityRuntimeUnavailable()
        device_id, set_device_cookie = resolve_platform_device_id(
            flask_request
        )
        trusted_source = self._trusted_source(flask_request)
        try:
            issued = self._login_service.login(
                username=username,
                password=password,
                factor_method=factor_method,
                factor_value=factor_value,
                source_ip=trusted_source.value,
                device_id=device_id,
                request_id=f"platform-login:{uuid4()}",
                device_name=_safe_device_name(device_name),
                user_agent_summary=_safe_user_agent(flask_request),
            )
        except PlatformLoginRejected:
            raise PlatformLoginHttpRejected(
                device_id=device_id,
                set_device_cookie=set_device_cookie,
                device_cookie_max_age_seconds=(
                    self._login_settings.device_cookie_max_age_seconds
                ),
            ) from None
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None
        return PlatformLoginHttpResult(
            issued=issued,
            device_id=device_id,
            set_device_cookie=set_device_cookie,
            device_cookie_max_age_seconds=(
                self._login_settings.device_cookie_max_age_seconds
            ),
        )

    def consume_setup_token(
        self,
        *,
        flask_request: Request,
        setup_token: object,
    ) -> Mapping[str, object]:
        self._require_setup_configuration()
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                result = self._setup_service.consume(
                    session,
                    presented_token=setup_token,
                    now=now,
                )
                if not result.accepted or result.platform_admin_id is None:
                    raise PlatformSetupHttpRejected()
                self._append_setup_audit(
                    session,
                    platform_admin_id=result.platform_admin_id,
                    action="platform_admin.setup_token_consumed",
                    reason_code="platform_setup.token_consumed",
                    now=now,
                )
                return {"accepted": True}
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None

    def step_up(
        self,
        *,
        flask_request: Request,
        factor_method: object,
        factor_value: object,
    ) -> PlatformLoginHttpResult:
        if self._step_up_service is None or self._login_settings is None:
            raise PlatformIdentityRuntimeUnavailable()
        cookie_values = flask_request.cookies.getlist(
            PLATFORM_SESSION_COOKIE_NAME
        )
        csrf_values = flask_request.headers.getlist(PLATFORM_CSRF_HEADER_NAME)
        presented_session: object = (
            cookie_values[0] if len(cookie_values) == 1 else None
        )
        presented_csrf: object = (
            csrf_values[0] if len(csrf_values) == 1 else None
        )
        device_id, set_device_cookie = resolve_platform_device_id(
            flask_request
        )
        trusted_source = self._trusted_source(flask_request)
        try:
            issued = self._step_up_service.step_up(
                presented_session_token=presented_session,
                presented_csrf=presented_csrf,
                factor_method=factor_method,
                factor_value=factor_value,
                source_ip=trusted_source.value,
                device_id=device_id,
                request_id=f"platform-step-up:{uuid4()}",
                user_agent_summary=_safe_user_agent(flask_request),
            )
        except PlatformSessionAuthenticationError:
            raise PlatformAuthenticationRequired() from None
        except PlatformCsrfAuthenticationError:
            raise PlatformCsrfDenied() from None
        except PlatformStepUpRejected:
            raise PlatformStepUpHttpRejected(
                device_id=device_id,
                set_device_cookie=set_device_cookie,
                device_cookie_max_age_seconds=(
                    self._login_settings.device_cookie_max_age_seconds
                ),
            ) from None
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None
        return PlatformLoginHttpResult(
            issued=issued,
            device_id=device_id,
            set_device_cookie=set_device_cookie,
            device_cookie_max_age_seconds=(
                self._login_settings.device_cookie_max_age_seconds
            ),
        )

    def set_setup_password(
        self,
        *,
        flask_request: Request,
        password: object,
    ) -> Mapping[str, object]:
        self._require_setup_configuration()
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                authority = self._authorize_setup(
                    session, flask_request=flask_request, now=now
                )
                try:
                    self._setup_service.set_password(
                        session,
                        platform_admin_id=authority.platform_admin_id,
                        expected_setup_version=authority.setup_version,
                        password=password,
                        hasher=self._password_hasher,
                        now=now,
                    )
                except (PlatformPasswordError, RuntimeError):
                    raise PlatformSetupHttpRejected() from None
                self._append_setup_audit(
                    session,
                    platform_admin_id=authority.platform_admin_id,
                    action="platform_admin.setup_password_set",
                    reason_code="platform_setup.password_set",
                    now=now,
                )
                return {"password_set": True}
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None

    def begin_setup_totp(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]:
        self._require_setup_configuration()
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                key_ring = SqlAlchemyRootKeyRegistry(session=session).load(
                    self._root_key_directory
                )
                authority = self._authorize_setup(
                    session, flask_request=flask_request, now=now
                )
                try:
                    pending = self._totp_service.create_pending_binding(
                        session,
                        platform_admin_id=authority.platform_admin_id,
                        root_key=key_ring.active_key,
                        now=now,
                    )
                except PlatformFactorRejected:
                    raise PlatformSetupHttpRejected() from None
                seed = pending.take_base32_seed()
                self._append_setup_audit(
                    session,
                    platform_admin_id=authority.platform_admin_id,
                    action="platform_admin.setup_totp_started",
                    reason_code="platform_setup.totp_started",
                    now=now,
                )
                return {
                    "credential_id": pending.credential_id,
                    "base32_seed": seed,
                }
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None

    def complete_setup(
        self,
        *,
        flask_request: Request,
        credential_id: object,
        totp_code: object,
    ) -> Mapping[str, object]:
        self._require_setup_configuration()
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                key_ring = SqlAlchemyRootKeyRegistry(session=session).load(
                    self._root_key_directory
                )
                authority = self._authorize_setup(
                    session, flask_request=flask_request, now=now
                )
                if not isinstance(credential_id, str):
                    raise PlatformSetupHttpRejected()
                root_version = session.scalar(
                    sa.select(
                        PlatformAdminTotpCredential.root_key_version
                    ).where(
                        PlatformAdminTotpCredential.id == credential_id,
                        PlatformAdminTotpCredential.platform_admin_id
                        == authority.platform_admin_id,
                    )
                )
                if root_version is None:
                    raise PlatformSetupHttpRejected()
                try:
                    self._totp_service.confirm_pending(
                        session,
                        credential_id=credential_id,
                        presented_code=totp_code,
                        root_key=key_ring.key_for_existing_reference(
                            root_version
                        ),
                        now=now,
                        allowed_drift_steps=(
                            self._login_settings.setup_allowed_totp_drift_steps
                        ),
                    )
                    batch = self._recovery_code_service.issue_codes(
                        session,
                        platform_admin_id=authority.platform_admin_id,
                        count=self._login_settings.recovery_code_count,
                        ttl=self._login_settings.recovery_code_ttl,
                        now=now,
                    )
                    activate_admin_if_ready(
                        session,
                        platform_admin_id=authority.platform_admin_id,
                        expected_setup_version=authority.setup_version,
                        now=now,
                    )
                except PlatformFactorRejected:
                    raise PlatformSetupHttpRejected() from None
                recovery_codes = batch.take_plaintext_codes()
                self._append_setup_audit(
                    session,
                    platform_admin_id=authority.platform_admin_id,
                    action="platform_admin.setup_completed",
                    reason_code="platform_setup.completed",
                    now=now,
                )
                return {
                    "setup_completed": True,
                    "recovery_codes": recovery_codes,
                }
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None

    def begin_totp_replacement(
        self,
        *,
        flask_request: Request,
        factor_method: object,
        factor_value: object,
    ) -> PlatformCredentialHttpResult:
        def operation(session, context, key_ring, now):
            self._current_factor_service.verify(
                session,
                platform_admin_id=context.platform_admin_id,
                factor_method=factor_method,
                factor_value=factor_value,
                key_ring=key_ring,
                now=now,
                allowed_totp_drift_steps=(
                    self._login_settings.policy.allowed_totp_drift_steps
                ),
            )
            pending = self._totp_service.create_pending_replacement(
                session,
                platform_admin_id=context.platform_admin_id,
                root_key=key_ring.active_key,
                now=now,
            )
            return _FactorActionResult(
                data={
                    "credential_id": pending.credential_id,
                    "base32_seed": pending.take_base32_seed(),
                },
                result_count=1,
            )

        return self._run_factor_action(
            flask_request=flask_request,
            factor_method=factor_method,
            action="platform.factor.totp_replacement.begin",
            route_template="POST /platform/api/factors/totp/replacement",
            operation=operation,
        )

    def complete_totp_replacement(
        self,
        *,
        flask_request: Request,
        credential_id: object,
        totp_code: object,
    ) -> PlatformCredentialHttpResult:
        def operation(session, context, key_ring, now):
            if not isinstance(credential_id, str):
                raise PlatformFactorRejected()
            root_version = session.scalar(
                sa.select(
                    PlatformAdminTotpCredential.root_key_version
                ).where(
                    PlatformAdminTotpCredential.id == credential_id,
                    PlatformAdminTotpCredential.platform_admin_id
                    == context.platform_admin_id,
                    PlatformAdminTotpCredential.status == "pending",
                )
            )
            if root_version is None:
                raise PlatformFactorRejected()
            generation = self._totp_service.confirm_replacement(
                session,
                platform_admin_id=context.platform_admin_id,
                credential_id=credential_id,
                presented_code=totp_code,
                root_key=key_ring.key_for_existing_reference(root_version),
                now=now,
                allowed_drift_steps=(
                    self._login_settings.setup_allowed_totp_drift_steps
                ),
            )
            batch = self._recovery_code_service.issue_codes(
                session,
                platform_admin_id=context.platform_admin_id,
                count=self._login_settings.recovery_code_count,
                ttl=self._login_settings.recovery_code_ttl,
                now=now,
            )
            recovery_codes = batch.take_plaintext_codes()
            revoked = self._session_service.revoke_all(
                session,
                platform_admin_id=context.platform_admin_id,
                reason_code="totp_replaced",
                revoked_by_session_id=context.session_id,
                now=now,
            )
            return _FactorActionResult(
                data={
                    "totp_generation": generation,
                    "recovery_code_generation": batch.generation,
                    "recovery_codes": recovery_codes,
                    "revoked_session_count": revoked.revoked_count,
                },
                result_count=revoked.revoked_count,
                clear_session_cookie=True,
            )

        return self._run_factor_action(
            flask_request=flask_request,
            factor_method="totp",
            action="platform.factor.totp_replacement.complete",
            route_template=(
                "POST /platform/api/factors/totp/replacement/complete"
            ),
            operation=operation,
        )

    def regenerate_recovery_codes(
        self,
        *,
        flask_request: Request,
        factor_method: object,
        factor_value: object,
    ) -> PlatformCredentialHttpResult:
        def operation(session, context, key_ring, now):
            self._current_factor_service.verify(
                session,
                platform_admin_id=context.platform_admin_id,
                factor_method=factor_method,
                factor_value=factor_value,
                key_ring=key_ring,
                now=now,
                allowed_totp_drift_steps=(
                    self._login_settings.policy.allowed_totp_drift_steps
                ),
            )
            batch = self._recovery_code_service.issue_codes(
                session,
                platform_admin_id=context.platform_admin_id,
                count=self._login_settings.recovery_code_count,
                ttl=self._login_settings.recovery_code_ttl,
                now=now,
            )
            recovery_codes = batch.take_plaintext_codes()
            return _FactorActionResult(
                data={
                    "recovery_code_generation": batch.generation,
                    "recovery_codes": recovery_codes,
                },
                result_count=len(recovery_codes),
            )

        return self._run_factor_action(
            flask_request=flask_request,
            factor_method=factor_method,
            action="platform.factor.recovery_codes.regenerate",
            route_template=(
                "POST /platform/api/factors/recovery-codes/regenerate"
            ),
            operation=operation,
        )

    def session_status(self, *, flask_request: Request) -> Mapping[str, object]:
        trusted_source = self._trusted_source(flask_request)
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                context = self._boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.SESSION_SELF_READ,
                    now=now,
                    ip_summary=trusted_source.value,
                )
                return {
                    "session_id": context.session_id,
                    "platform_admin_id": context.platform_admin_id,
                    "username": context.username_canonical,
                    "role": context.role.value,
                    "mfa_method": context.mfa_method,
                }
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None

    def list_sessions(self, *, flask_request: Request) -> Mapping[str, object]:
        trusted_source = self._trusted_source(flask_request)
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                context = self._boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.SESSION_SELF_READ,
                    now=now,
                    ip_summary=trusted_source.value,
                )
                rows = session.execute(
                    sa.select(
                        PlatformAdminSession.id,
                        PlatformAdminSession.device_name,
                        PlatformAdminSession.mfa_method,
                        PlatformAdminSession.created_at,
                        PlatformAdminSession.last_seen_at,
                        PlatformAdminSession.idle_expires_at,
                        PlatformAdminSession.absolute_expires_at,
                    )
                    .where(
                        PlatformAdminSession.platform_admin_id
                        == context.platform_admin_id,
                        PlatformAdminSession.revoked_at.is_(None),
                        PlatformAdminSession.idle_expires_at > now,
                        PlatformAdminSession.absolute_expires_at > now,
                    )
                    .order_by(
                        PlatformAdminSession.created_at.desc(),
                        PlatformAdminSession.id.desc(),
                    )
                    .limit(100)
                ).all()
                return {
                    "sessions": [
                        {
                            "session_id": row.id,
                            "device_name": row.device_name,
                            "mfa_method": row.mfa_method,
                            "created_at": _iso(row.created_at),
                            "last_seen_at": _iso(row.last_seen_at),
                            "idle_expires_at": _iso(row.idle_expires_at),
                            "absolute_expires_at": _iso(
                                row.absolute_expires_at
                            ),
                            "current": row.id == context.session_id,
                        }
                        for row in rows
                    ]
                }
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None

    def revoke_session(
        self,
        *,
        flask_request: Request,
        target_session_id: object,
    ) -> Mapping[str, object]:
        trusted_source = self._trusted_source(flask_request)
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                context = self._boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.SESSION_SELF_REVOKE,
                    now=now,
                    ip_summary=trusted_source.value,
                )
                try:
                    target_id = str(UUID(str(target_session_id)))
                except (TypeError, ValueError, AttributeError):
                    raise PlatformSessionTargetHttpUnavailable() from None
                try:
                    revoked = self._session_service.revoke_one(
                        session,
                        platform_admin_id=context.platform_admin_id,
                        target_session_id=target_id,
                        reason_code="admin_revoked_device",
                        revoked_by_session_id=context.session_id,
                        now=now,
                    )
                except PlatformSessionTargetUnavailable:
                    raise PlatformSessionTargetHttpUnavailable() from None
                if revoked:
                    self._append_session_audit(
                        session,
                        context=context,
                        action="platform.session.revoke",
                        reason_code="platform_session.revoke.succeeded",
                        result_count=1,
                        now=now,
                    )
                return {
                    "revoked": revoked,
                    "current_session_revoked": (
                        revoked and target_id == context.session_id
                    ),
                }
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None

    def revoke_all_sessions(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]:
        trusted_source = self._trusted_source(flask_request)
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                context = self._boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.SESSION_SELF_REVOKE,
                    now=now,
                    ip_summary=trusted_source.value,
                )
                result = self._session_service.revoke_all(
                    session,
                    platform_admin_id=context.platform_admin_id,
                    reason_code="admin_revoked_all_devices",
                    revoked_by_session_id=context.session_id,
                    now=now,
                )
                self._append_session_audit(
                    session,
                    context=context,
                    action="platform.session.revoke_all",
                    reason_code="platform_session.revoke_all.succeeded",
                    result_count=result.revoked_count,
                    now=now,
                )
                return {"revoked_count": result.revoked_count}
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None

    def list_tenants(
        self,
        *,
        flask_request: Request,
        query_arguments: object,
    ) -> Mapping[str, object]:
        trusted_source = self._trusted_source(flask_request)
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                context = self._boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.PLATFORM_TENANTS_READ,
                    now=now,
                    ip_summary=trusted_source.value,
                )
                page, page_size, status = _tenant_list_query(
                    query_arguments
                )
                result = self._tenant_directory.list_tenants(
                    session,
                    page=page,
                    page_size=page_size,
                    status=status,
                )
                self._append_directory_audit(
                    session,
                    context=context,
                    route_template="GET /platform/api/tenants",
                    action="platform.tenants.list",
                    reason_code="platform_tenants.list.succeeded",
                    target_tenant_id=None,
                    result_count=len(result["items"]),
                    now=now,
                )
                return result
        except PlatformTenantDirectoryInputError:
            raise PlatformTenantQueryHttpInvalid() from None
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None

    def get_tenant(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
    ) -> Mapping[str, object]:
        trusted_source = self._trusted_source(flask_request)
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                context = self._boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.PLATFORM_TENANTS_READ,
                    now=now,
                    ip_summary=trusted_source.value,
                )
                result = self._tenant_directory.get_tenant(
                    session, tenant_id=tenant_id
                )
                self._append_directory_audit(
                    session,
                    context=context,
                    route_template="GET /platform/api/tenants/<tenant_id>",
                    action="platform.tenants.get",
                    reason_code="platform_tenants.get.succeeded",
                    target_tenant_id=str(result["tenant_id"]),
                    result_count=1,
                    now=now,
                )
                return result
        except PlatformTenantDirectoryTargetUnavailable:
            raise PlatformTenantTargetHttpUnavailable() from None
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None

    def logout(self, *, flask_request: Request) -> Mapping[str, object]:
        trusted_source = self._trusted_source(flask_request)
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                context = self._boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.SESSION_LOGOUT,
                    now=now,
                    ip_summary=trusted_source.value,
                )
                revoked = self._session_service.revoke_one(
                    session,
                    platform_admin_id=context.platform_admin_id,
                    target_session_id=context.session_id,
                    reason_code="logout_current",
                    revoked_by_session_id=context.session_id,
                    now=now,
                )
                session.add(
                    PlatformAuditLog(
                        actor_type="platform_admin",
                        actor_platform_admin_id=context.platform_admin_id,
                        actor_platform_session_id=context.session_id,
                        target_platform_admin_id=context.platform_admin_id,
                        route_or_command_template="POST /platform/api/logout",
                        action="platform.logout",
                        access_mode="authentication",
                        pii_revealed=False,
                        outcome="succeeded",
                        safe_reason_code="platform_logout.succeeded",
                        authentication_factor=context.mfa_method,
                        result_count=1 if revoked else 0,
                        request_id=f"platform-logout:{uuid4()}",
                        created_at=now,
                    )
                )
                session.flush()
                return {"revoked": revoked}
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None

    def _require_setup_configuration(self) -> None:
        if self._login_settings is None:
            raise PlatformIdentityRuntimeUnavailable()

    def _authorize_setup(self, session, *, flask_request: Request, now):
        values = flask_request.headers.getlist(PLATFORM_SETUP_HEADER_NAME)
        token: object = values[0] if len(values) == 1 else None
        try:
            return self._setup_service.authorize_consumed(
                session,
                presented_token=token,
                now=now,
            )
        except RuntimeError:
            raise PlatformSetupHttpRejected() from None

    def _run_factor_action(
        self,
        *,
        flask_request: Request,
        factor_method: object,
        action: str,
        route_template: str,
        operation,
    ) -> PlatformCredentialHttpResult:
        if self._login_settings is None:
            raise PlatformIdentityRuntimeUnavailable()
        device_id, set_device_cookie = resolve_platform_device_id(
            flask_request
        )
        trusted_source = self._trusted_source(flask_request)
        selected_method = (
            factor_method
            if isinstance(factor_method, str)
            and factor_method in _PLATFORM_FACTOR_METHODS
            else None
        )
        result = None
        rejected = False
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                context = self._boundary.authorize(
                    session,
                    flask_request,
                    capability=Capability.FACTOR_SELF_MANAGE,
                    now=now,
                    ip_summary=trusted_source.value,
                )
                key_ring = SqlAlchemyRootKeyRegistry(session=session).load(
                    self._root_key_directory
                )
                subjects = PlatformRateLimitSubjects(
                    username=context.username_canonical,
                    ip=trusted_source.value,
                    device=device_id,
                )
                limiter = PlatformAuthRateLimiter(
                    policy=self._login_settings.policy.rate_limit,
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
                    outcome = "rate_limited"
                    rejected = True
                else:
                    try:
                        result = operation(session, context, key_ring, now)
                    except PlatformFactorRejected:
                        limiter.record_failure(
                            session,
                            scope="mfa",
                            subjects=subjects,
                            now=now,
                        )
                        outcome = "rejected"
                        rejected = True
                    else:
                        outcome = "succeeded"
                self._append_factor_audit(
                    session,
                    context=context,
                    route_template=route_template,
                    action=action,
                    outcome=outcome,
                    factor_method=selected_method,
                    result_count=(
                        result.result_count if result is not None else 0
                    ),
                    now=now,
                )
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None
        if rejected or result is None:
            raise PlatformStepUpHttpRejected(
                device_id=device_id,
                set_device_cookie=set_device_cookie,
                device_cookie_max_age_seconds=(
                    self._login_settings.device_cookie_max_age_seconds
                ),
            )
        return PlatformCredentialHttpResult(
            data=result.data,
            device_id=device_id,
            set_device_cookie=set_device_cookie,
            device_cookie_max_age_seconds=(
                self._login_settings.device_cookie_max_age_seconds
            ),
            clear_session_cookie=result.clear_session_cookie,
        )

    @staticmethod
    def _append_session_audit(
        session,
        *,
        context,
        action: str,
        reason_code: str,
        result_count: int,
        now,
    ) -> None:
        session.add(
            PlatformAuditLog(
                actor_type="platform_admin",
                actor_platform_admin_id=context.platform_admin_id,
                actor_platform_session_id=context.session_id,
                target_platform_admin_id=context.platform_admin_id,
                route_or_command_template="POST /platform/api/sessions/...",
                action=action,
                access_mode="authentication",
                pii_revealed=False,
                outcome="succeeded",
                safe_reason_code=reason_code,
                authentication_factor=context.mfa_method,
                result_count=result_count,
                request_id=f"platform-session:{uuid4()}",
                created_at=now,
            )
        )
        session.flush()

    @staticmethod
    def _append_factor_audit(
        session,
        *,
        context,
        route_template: str,
        action: str,
        outcome: str,
        factor_method: str | None,
        result_count: int,
        now,
    ) -> None:
        session.add(
            PlatformAuditLog(
                actor_type="platform_admin",
                actor_platform_admin_id=context.platform_admin_id,
                actor_platform_session_id=context.session_id,
                target_platform_admin_id=context.platform_admin_id,
                route_or_command_template=route_template,
                action=action,
                access_mode="authentication",
                pii_revealed=False,
                outcome=outcome,
                safe_reason_code=f"platform_factor.{outcome}",
                authentication_factor=factor_method,
                result_count=result_count,
                request_id=f"platform-factor:{uuid4()}",
                created_at=now,
            )
        )
        session.flush()

    @staticmethod
    def _append_directory_audit(
        session,
        *,
        context,
        route_template: str,
        action: str,
        reason_code: str,
        target_tenant_id: str | None,
        result_count: int,
        now,
    ) -> None:
        session.add(
            PlatformAuditLog(
                actor_type="platform_admin",
                actor_platform_admin_id=context.platform_admin_id,
                actor_platform_session_id=context.session_id,
                target_tenant_id=target_tenant_id,
                route_or_command_template=route_template,
                action=action,
                access_mode="control",
                pii_revealed=False,
                outcome="succeeded",
                safe_reason_code=reason_code,
                authentication_factor=context.mfa_method,
                result_count=result_count,
                request_id=f"platform-directory:{uuid4()}",
                created_at=now,
            )
        )
        session.flush()

    @staticmethod
    def _append_setup_audit(
        session,
        *,
        platform_admin_id: str,
        action: str,
        reason_code: str,
        now,
    ) -> None:
        session.add(
            PlatformAuditLog(
                actor_type="system",
                target_platform_admin_id=platform_admin_id,
                route_or_command_template="POST /platform/api/setup/...",
                action=action,
                access_mode="authentication",
                pii_revealed=False,
                outcome="succeeded",
                safe_reason_code=reason_code,
                request_id=f"platform-setup:{uuid4()}",
                created_at=now,
            )
        )
        session.flush()

    def _trusted_source(self, flask_request: Request) -> TrustedSourceBucket:
        if self._login_settings is None:
            raise PlatformIdentityRuntimeUnavailable()
        try:
            source = self._login_settings.trusted_source_resolver(
                flask_request
            )
        except Exception:
            raise PlatformIdentityRuntimeUnavailable() from None
        if not isinstance(source, TrustedSourceBucket):
            raise PlatformIdentityRuntimeUnavailable()
        return source


def install_platform_identity_http_runtime(
    app,
    *,
    runtime: PlatformIdentityHttpRuntime,
) -> None:
    if PLATFORM_IDENTITY_HTTP_RUNTIME_EXTENSION in app.extensions:
        raise RuntimeError("platform identity HTTP runtime is already installed")
    if not isinstance(runtime, PlatformIdentityHttpRuntime):
        raise TypeError("runtime must implement PlatformIdentityHttpRuntime")
    app.extensions[PLATFORM_IDENTITY_HTTP_RUNTIME_EXTENSION] = runtime


def require_platform_identity_http_runtime() -> PlatformIdentityHttpRuntime:
    runtime = current_app.extensions.get(
        PLATFORM_IDENTITY_HTTP_RUNTIME_EXTENSION
    )
    if not isinstance(runtime, PlatformIdentityHttpRuntime):
        raise PlatformIdentityRuntimeUnavailable()
    return runtime


def _safe_device_name(value: object) -> str | None:
    if isinstance(value, str) and 1 <= len(value) <= 100:
        return value
    return None


def _safe_user_agent(request: Request) -> str | None:
    value = request.headers.get("User-Agent")
    if not isinstance(value, str) or not value:
        return None
    return value[:255]


def _database_now(session):
    value = read_database_utc_value(session)
    if not hasattr(value, "tzinfo"):
        raise RuntimeError("control database clock is invalid")
    return value


def _tenant_list_query(arguments: object) -> tuple[object, object, object]:
    if not callable(getattr(arguments, "keys", None)) or not callable(
        getattr(arguments, "getlist", None)
    ):
        raise PlatformTenantDirectoryInputError("query arguments are invalid")
    allowed = {"page", "page_size", "status"}
    if any(key not in allowed for key in arguments.keys()):
        raise PlatformTenantDirectoryInputError("query arguments are invalid")

    def one(name: str, default: object) -> object:
        values = arguments.getlist(name)
        if not values:
            return default
        if len(values) != 1:
            raise PlatformTenantDirectoryInputError(
                "query arguments are invalid"
            )
        return values[0]

    return one("page", "1"), one("page_size", "25"), one("status", None)


def _iso(value) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


__all__ = [
    "PLATFORM_IDENTITY_HTTP_RUNTIME_EXTENSION",
    "PlatformIdentityHttpRuntime",
    "PlatformIdentityRuntimeUnavailable",
    "PlatformLoginHttpRejected",
    "PlatformLoginHttpResult",
    "PlatformCredentialHttpResult",
    "PlatformLoginRuntimeSettings",
    "PlatformSetupHttpRejected",
    "PlatformSessionTargetHttpUnavailable",
    "SqlAlchemyPlatformIdentityHttpRuntime",
    "install_platform_identity_http_runtime",
    "require_platform_identity_http_runtime",
]
