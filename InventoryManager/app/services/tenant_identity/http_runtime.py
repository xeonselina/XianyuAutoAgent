"""Fail-closed control-database runtime for tenant session self-service."""

from __future__ import annotations

from datetime import datetime, timezone
from dataclasses import dataclass
import os
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable
from uuid import UUID, uuid4

from flask import Request, current_app
import sqlalchemy as sa

from inventory_control.crypto import RootKeyLoadError, SqlAlchemyRootKeyRegistry
from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.domain.rbac import Capability
from inventory_control.identity import (
    PhoneNormalizationError,
    SessionIssueError,
    SessionService,
    SessionTargetNotFound,
    TenantBrowserSessionPolicy,
    TenantLoginService,
    build_tenant_login_sms_context,
)
from inventory_control.models import (
    SmsChallenge,
    Tenant,
    TenantAuthSecurityEvent,
    TenantMembership,
    TenantUserSession,
    User,
)
from inventory_control.sms import (
    CanonicalSmsPhone,
    SmsChallengeService,
    SmsPolicy,
    SmsProvider,
    SmsSendRejected,
    TrustedSourceBucket,
)
from inventory_control.sensitive_actions import SensitiveActionIntentService
from .phone_change_runtime import (
    TenantPhoneChangeConflict,
    TenantPhoneChangeInputRejected,
    TenantPhoneChangeRuntime,
    TenantPhoneChangeVerificationRejected,
    translate_phone_change_error,
)
from .sms_runtime import TenantSmsDeliveryRuntime
from inventory_control.tenant_http import (
    TENANT_SESSION_COOKIE_NAME,
    TenantHttpBoundary,
    TenantHttpError,
)


TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION = (
    "inventory_tenant_identity_http_runtime"
)


@dataclass(frozen=True, slots=True, repr=False)
class TenantLoginRuntimeSettings:
    """Explicit provider/source/session policy required to enable OTP login."""

    sms_provider: SmsProvider
    sms_policy: SmsPolicy
    session_policy: TenantBrowserSessionPolicy
    trusted_source_resolver: object

    def __post_init__(self) -> None:
        if not callable(getattr(self.sms_provider, "send_verification", None)):
            raise TypeError("sms_provider must implement send_verification")
        if not isinstance(self.sms_policy, SmsPolicy):
            raise TypeError("sms_policy must be an SmsPolicy")
        if not isinstance(
            self.session_policy, TenantBrowserSessionPolicy
        ):
            raise TypeError(
                "session_policy must be a TenantBrowserSessionPolicy"
            )
        if not callable(self.trusted_source_resolver):
            raise TypeError("trusted_source_resolver must be callable")
        validate_provider_policy = getattr(
            self.sms_provider,
            "validate_sms_policy",
            None,
        )
        if callable(validate_provider_policy):
            validate_provider_policy(self.sms_policy)

    def __repr__(self) -> str:
        return "TenantLoginRuntimeSettings(<provider-and-policy-configured>)"


class TenantIdentityRuntimeUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("TENANT_IDENTITY_RUNTIME_UNAVAILABLE")


class TenantSessionTargetUnavailable(TenantHttpError):
    status_code = 404
    code = "TENANT_SESSION_TARGET_UNAVAILABLE"
    public_message = "The tenant session target is unavailable."


class TenantLoginInputRejected(TenantHttpError):
    status_code = 400
    code = "TENANT_LOGIN_INPUT_INVALID"
    public_message = "Core currently supports mainland-China mobile numbers."


class TenantLoginVerificationRejected(TenantHttpError):
    status_code = 401
    code = "TENANT_LOGIN_REJECTED"
    public_message = "The login verification was rejected."


class TenantSmsRateLimited(TenantHttpError):
    status_code = 429
    code = "TENANT_SMS_RATE_LIMITED"
    public_message = "SMS verification is temporarily unavailable."

    def __init__(self, *, retry_after_seconds: int) -> None:
        super().__init__()
        self.retry_after_seconds = max(1, retry_after_seconds)


@runtime_checkable
class TenantIdentityHttpRuntime(Protocol):
    def request_login_code(
        self,
        *,
        flask_request: Request,
        raw_phone: object,
    ) -> Mapping[str, object]: ...

    def complete_login(
        self,
        *,
        flask_request: Request,
        raw_phone: object,
        challenge_id: object,
        plaintext_code: object,
        device_name: object = None,
    ): ...

    def session_status(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]: ...

    def logout(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]: ...

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

    def request_phone_change_challenges(
        self,
        *,
        flask_request: Request,
        raw_new_phone: object,
        action_id: object,
    ) -> Mapping[str, object]: ...

    def confirm_phone_change(
        self,
        *,
        flask_request: Request,
        raw_new_phone: object,
        action_id: object,
        old_challenge_id: object,
        old_plaintext_code: object,
        new_challenge_id: object,
        new_plaintext_code: object,
    ) -> Mapping[str, object]: ...


class SqlAlchemyTenantIdentityHttpRuntime:
    """Authenticate and revoke sessions without opening a tenant database."""

    __slots__ = (
        "_control_database",
        "_tenant_http_boundary",
        "_session_service",
        "_root_key_directory",
        "_sms_provider",
        "_sms_policy",
        "_session_policy",
        "_trusted_source_resolver",
        "_sms_challenge_service",
        "_sms_delivery_runtime",
        "_login_service",
        "_phone_change_runtime",
    )

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        tenant_http_boundary: TenantHttpBoundary,
        session_service: SessionService,
        root_key_directory: str | os.PathLike[str] | None = None,
        sms_provider: SmsProvider | None = None,
        sms_policy: SmsPolicy | None = None,
        session_policy: TenantBrowserSessionPolicy | None = None,
        trusted_source_resolver=None,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        if not isinstance(tenant_http_boundary, TenantHttpBoundary):
            raise TypeError("tenant_http_boundary must be a TenantHttpBoundary")
        if not isinstance(session_service, SessionService):
            raise TypeError("session_service must be a SessionService")
        if tenant_http_boundary.session_service is not session_service:
            raise ValueError("identity runtime must share one SessionService")
        if root_key_directory is not None:
            try:
                raw_root_directory = os.fspath(root_key_directory)
            except TypeError:
                raise TypeError(
                    "root_key_directory must be an absolute path"
                ) from None
            if (
                not isinstance(raw_root_directory, str)
                or not Path(raw_root_directory).is_absolute()
            ):
                raise ValueError(
                    "root_key_directory must be an absolute path"
                )
        else:
            raw_root_directory = None
        if sms_provider is not None and not callable(
            getattr(sms_provider, "send_verification", None)
        ):
            raise TypeError("sms_provider must implement send_verification")
        if sms_policy is not None and not isinstance(sms_policy, SmsPolicy):
            raise TypeError("sms_policy must be an SmsPolicy")
        if session_policy is not None and not isinstance(
            session_policy, TenantBrowserSessionPolicy
        ):
            raise TypeError(
                "session_policy must be a TenantBrowserSessionPolicy"
            )
        if trusted_source_resolver is not None and not callable(
            trusted_source_resolver
        ):
            raise TypeError("trusted_source_resolver must be callable")
        self._control_database = control_database
        self._tenant_http_boundary = tenant_http_boundary
        self._session_service = session_service
        self._root_key_directory = raw_root_directory
        self._sms_provider = sms_provider
        self._sms_policy = sms_policy
        self._session_policy = session_policy
        self._trusted_source_resolver = trusted_source_resolver
        self._sms_challenge_service = SmsChallengeService()
        self._sms_delivery_runtime = TenantSmsDeliveryRuntime(
            control_database=control_database,
            root_key_directory=raw_root_directory,
            provider=sms_provider,
            policy=sms_policy,
            trusted_source_resolver=trusted_source_resolver,
            challenge_service=self._sms_challenge_service,
        )
        self._login_service = TenantLoginService(
            sms_challenge_service=self._sms_challenge_service,
            session_service=session_service,
        )
        self._phone_change_runtime = (
            TenantPhoneChangeRuntime(
                control_database=control_database,
                tenant_http_boundary=tenant_http_boundary,
                root_key_directory=raw_root_directory,
                trusted_source_resolver=trusted_source_resolver,
                delivery=self._sms_delivery_runtime,
                intent_service=SensitiveActionIntentService(
                    sms_challenge_service=self._sms_challenge_service
                ),
            )
            if (
                raw_root_directory is not None
                and sms_provider is not None
                and sms_policy is not None
                and trusted_source_resolver is not None
            )
            else None
        )

    @property
    def control_database(self) -> ControlDatabase:
        return self._control_database

    @property
    def tenant_http_boundary(self) -> TenantHttpBoundary:
        return self._tenant_http_boundary

    @property
    def session_service(self) -> SessionService:
        return self._session_service

    @property
    def login_is_configured(self) -> bool:
        return bool(
            self._root_key_directory is not None
            and self._sms_provider is not None
            and self._sms_policy is not None
            and self._session_policy is not None
            and self._trusted_source_resolver is not None
        )

    def request_login_code(self, *, flask_request, raw_phone):
        try:
            self._require_login_configuration()
            phone = _canonical_phone(raw_phone)
            receipt = self._sms_delivery_runtime.issue(
                flask_request=flask_request,
                context_factory=lambda session, _now: (
                    _current_login_sms_context(session, phone=phone)
                ),
            )
            return {
                "challenge_id": receipt.challenge_id,
                "expires_in_seconds": receipt.expires_in_seconds,
                "resend_after_seconds": receipt.resend_after_seconds,
            }
        except PhoneNormalizationError:
            raise TenantLoginInputRejected() from None
        except SmsSendRejected as exc:
            raise TenantSmsRateLimited(
                retry_after_seconds=exc.retry_after_seconds
            ) from None
        except TenantHttpError:
            raise
        except TenantIdentityRuntimeUnavailable:
            raise
        except Exception:
            raise TenantIdentityRuntimeUnavailable() from None

    def complete_login(
        self,
        *,
        flask_request,
        raw_phone,
        challenge_id,
        plaintext_code,
        device_name=None,
    ):
        try:
            self._require_login_configuration()
            phone = _canonical_phone(raw_phone)
            selected_device_name = _safe_device_name(device_name)
            trusted_source = self._trusted_source_resolver(flask_request)
            if not isinstance(trusted_source, TrustedSourceBucket):
                raise TenantIdentityRuntimeUnavailable()
            presented_session_token = _single_session_cookie(flask_request)
            issued_session = None
            with self._control_database.transaction() as control_session:
                database_now = _database_utc_now(control_session)
                key_ring = SqlAlchemyRootKeyRegistry(
                    session=control_session
                ).load(self._root_key_directory)
                root_version = control_session.scalar(
                    sa.select(SmsChallenge.root_key_version).where(
                        SmsChallenge.id == challenge_id
                    )
                )
                if root_version is None:
                    raise TenantLoginVerificationRejected()
                root_key = key_ring.key_for_existing_reference(root_version)
                result = self._login_service.complete(
                    control_session,
                    challenge_id=challenge_id,
                    phone=phone,
                    plaintext_code=plaintext_code,
                    root_key=root_key,
                    session_policy=self._session_policy,
                    presented_session_token=presented_session_token,
                    device_name=selected_device_name,
                    user_agent_summary=_safe_user_agent_summary(
                        flask_request
                    ),
                    ip_summary=trusted_source.value,
                    request_id=f"identity-login:{uuid4()}",
                    now=database_now,
                )
                if result.accepted:
                    issued_session = result.issued_session
            if issued_session is None:
                raise TenantLoginVerificationRejected()
            return issued_session
        except PhoneNormalizationError:
            raise TenantLoginInputRejected() from None
        except TenantHttpError:
            raise
        except (RootKeyLoadError, SessionIssueError):
            raise TenantIdentityRuntimeUnavailable() from None
        except TenantIdentityRuntimeUnavailable:
            raise
        except Exception:
            raise TenantIdentityRuntimeUnavailable() from None

    def _require_login_configuration(self) -> None:
        if not self.login_is_configured:
            raise TenantIdentityRuntimeUnavailable()

    def session_status(self, *, flask_request):
        try:
            with self._control_database.transaction() as control_session:
                database_now = _database_utc_now(control_session)
                context = self._tenant_http_boundary.authenticate(
                    control_session,
                    flask_request,
                    now=database_now,
                )
                return {
                    "authenticated": True,
                    "session_id": context.session_id,
                    "tenant_id": context.tenant_id,
                    "role": context.role.value,
                    "effective_gate": context.effective_gate.value,
                    "tenant_timezone": context.tenant_timezone,
                }
        except TenantHttpError:
            raise
        except TenantIdentityRuntimeUnavailable:
            raise
        except Exception:
            raise TenantIdentityRuntimeUnavailable() from None

    def logout(self, *, flask_request):
        try:
            with self._control_database.transaction() as control_session:
                database_now = _database_utc_now(control_session)
                context = self._tenant_http_boundary.authorize(
                    control_session,
                    flask_request,
                    capability=Capability.SESSION_LOGOUT,
                    now=database_now,
                )
                try:
                    revoked = self._session_service.revoke_one(
                        control_session,
                        user_id=context.user_id,
                        target_session_id=context.session_id,
                        reason_code="user_logout",
                        revoked_by_session_id=context.session_id,
                        now=database_now,
                    )
                except SessionTargetNotFound:
                    raise TenantIdentityRuntimeUnavailable() from None
                if revoked:
                    _append_security_event(
                        control_session,
                        tenant_id=context.tenant_id,
                        user_id=context.user_id,
                        actor_session_id=context.session_id,
                        target_session_id=context.session_id,
                        event_type="logout_current",
                        reason_code="user_logout",
                        created_at=database_now,
                    )
                return {"logged_out": True, "revoked": revoked}
        except TenantHttpError:
            raise
        except TenantIdentityRuntimeUnavailable:
            raise
        except Exception:
            raise TenantIdentityRuntimeUnavailable() from None

    def list_sessions(self, *, flask_request):
        try:
            with self._control_database.transaction() as control_session:
                database_now = _database_utc_now(control_session)
                context = self._tenant_http_boundary.authorize(
                    control_session,
                    flask_request,
                    capability=Capability.SESSION_SELF_READ,
                    now=database_now,
                )
                rows = control_session.execute(
                    sa.select(
                        TenantUserSession.id,
                        TenantUserSession.device_name,
                        TenantUserSession.user_agent_summary,
                        TenantUserSession.created_at,
                        TenantUserSession.last_seen_at,
                    )
                    .where(
                        TenantUserSession.user_id == context.user_id,
                        TenantUserSession.revoked_at.is_(None),
                        TenantUserSession.idle_expires_at > database_now,
                        TenantUserSession.absolute_expires_at > database_now,
                        TenantUserSession.auth_version_at_issue
                        == context.user_auth_version,
                        TenantUserSession.tenant_access_version_at_issue
                        == context.tenant_access_version,
                    )
                    .order_by(
                        TenantUserSession.last_seen_at.desc(),
                        TenantUserSession.id,
                    )
                    .limit(100)
                ).all()
                return {
                    "sessions": [
                        {
                            "session_id": row.id,
                            "device_summary": _device_summary(
                                row.device_name,
                                row.user_agent_summary,
                            ),
                            "created_at": _utc_iso(row.created_at),
                            "last_seen_at": _utc_iso(row.last_seen_at),
                            "is_current": row.id == context.session_id,
                        }
                        for row in rows
                    ]
                }
        except TenantHttpError:
            raise
        except TenantIdentityRuntimeUnavailable:
            raise
        except Exception:
            raise TenantIdentityRuntimeUnavailable() from None

    def revoke_session(self, *, flask_request, target_session_id):
        try:
            with self._control_database.transaction() as control_session:
                database_now = _database_utc_now(control_session)
                context = self._tenant_http_boundary.authorize(
                    control_session,
                    flask_request,
                    capability=Capability.SESSION_SELF_REVOKE,
                    now=database_now,
                )
                target_id = _canonical_uuid(target_session_id)
                try:
                    revoked = self._session_service.revoke_one(
                        control_session,
                        user_id=context.user_id,
                        target_session_id=target_id,
                        reason_code="user_revoke_device",
                        revoked_by_session_id=context.session_id,
                        now=database_now,
                    )
                except SessionTargetNotFound:
                    raise TenantSessionTargetUnavailable() from None
                if revoked:
                    _append_security_event(
                        control_session,
                        tenant_id=context.tenant_id,
                        user_id=context.user_id,
                        actor_session_id=context.session_id,
                        target_session_id=target_id,
                        event_type="revoke_target",
                        reason_code="user_revoke_device",
                        created_at=database_now,
                    )
                return {
                    "revoked": revoked,
                    "current_session_revoked": (
                        target_id == context.session_id
                    ),
                }
        except TenantHttpError:
            raise
        except TenantIdentityRuntimeUnavailable:
            raise
        except ValueError:
            raise TenantSessionTargetUnavailable() from None
        except Exception:
            raise TenantIdentityRuntimeUnavailable() from None

    def revoke_all_sessions(self, *, flask_request):
        try:
            with self._control_database.transaction() as control_session:
                database_now = _database_utc_now(control_session)
                context = self._tenant_http_boundary.authorize(
                    control_session,
                    flask_request,
                    capability=Capability.SESSION_SELF_REVOKE,
                    now=database_now,
                )
                result = self._session_service.revoke_all(
                    control_session,
                    user_id=context.user_id,
                    reason_code="user_revoke_all_devices",
                    revoked_by_session_id=context.session_id,
                    now=database_now,
                )
                _append_security_event(
                    control_session,
                    tenant_id=context.tenant_id,
                    user_id=context.user_id,
                    actor_session_id=context.session_id,
                    target_session_id=None,
                    event_type="revoke_all",
                    reason_code="user_revoke_all_devices",
                    created_at=database_now,
                )
                return {
                    "revoked_count": result.revoked_count,
                    "all_sessions_revoked": True,
                }
        except TenantHttpError:
            raise
        except TenantIdentityRuntimeUnavailable:
            raise
        except SessionTargetNotFound:
            raise TenantIdentityRuntimeUnavailable() from None
        except Exception:
            raise TenantIdentityRuntimeUnavailable() from None

    def request_phone_change_challenges(
        self,
        *,
        flask_request,
        raw_new_phone,
        action_id,
    ):
        try:
            return self._require_phone_change_runtime().request_challenges(
                flask_request=flask_request,
                raw_new_phone=raw_new_phone,
                action_id=action_id,
            )
        except TenantHttpError:
            raise
        except Exception as exc:
            translated = translate_phone_change_error(exc)
            if isinstance(translated, TenantHttpError):
                raise translated from None
            raise TenantIdentityRuntimeUnavailable() from None

    def confirm_phone_change(
        self,
        *,
        flask_request,
        raw_new_phone,
        action_id,
        old_challenge_id,
        old_plaintext_code,
        new_challenge_id,
        new_plaintext_code,
    ):
        try:
            return self._require_phone_change_runtime().confirm(
                flask_request=flask_request,
                raw_new_phone=raw_new_phone,
                action_id=action_id,
                old_challenge_id=old_challenge_id,
                old_plaintext_code=old_plaintext_code,
                new_challenge_id=new_challenge_id,
                new_plaintext_code=new_plaintext_code,
            )
        except TenantHttpError:
            raise
        except Exception as exc:
            translated = translate_phone_change_error(exc)
            if isinstance(translated, TenantHttpError):
                raise translated from None
            raise TenantIdentityRuntimeUnavailable() from None

    def _require_phone_change_runtime(self) -> TenantPhoneChangeRuntime:
        if not isinstance(self._phone_change_runtime, TenantPhoneChangeRuntime):
            raise TenantIdentityRuntimeUnavailable()
        return self._phone_change_runtime

    def __repr__(self) -> str:
        return "SqlAlchemyTenantIdentityHttpRuntime(control_only=True)"


def require_tenant_identity_http_runtime() -> TenantIdentityHttpRuntime:
    runtime = current_app.extensions.get(
        TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION
    )
    if not isinstance(runtime, TenantIdentityHttpRuntime):
        raise TenantIdentityRuntimeUnavailable()
    return runtime


def _database_utc_now(control_session) -> datetime:
    value = read_database_utc_value(control_session)
    if not isinstance(value, datetime):
        raise TenantIdentityRuntimeUnavailable()
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _canonical_uuid(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("session target is invalid")
    parsed = UUID(value)
    canonical = str(parsed)
    if canonical != value.lower():
        raise ValueError("session target is invalid")
    return canonical


def _utc_iso(value: datetime) -> str:
    if not isinstance(value, datetime):
        raise TenantIdentityRuntimeUnavailable()
    if value.tzinfo is None or value.utcoffset() is None:
        normalized = value.replace(tzinfo=timezone.utc)
    else:
        normalized = value.astimezone(timezone.utc)
    return normalized.isoformat().replace("+00:00", "Z")


def _device_summary(device_name: object, user_agent_summary: object) -> str:
    for value in (device_name, user_agent_summary):
        if isinstance(value, str) and value.strip():
            return value.strip()[:100]
    return "未知设备"


def _canonical_phone(value: object) -> CanonicalSmsPhone:
    if not isinstance(value, str):
        raise PhoneNormalizationError()
    return CanonicalSmsPhone.from_input(value)


def _current_login_sms_context(
    control_session,
    *,
    phone: CanonicalSmsPhone,
):
    user = control_session.scalar(
        sa.select(User)
        .where(User.phone_e164 == phone.e164)
        .with_for_update()
    )
    membership = (
        control_session.scalar(
            sa.select(TenantMembership)
            .where(TenantMembership.claimed_user_id == user.id)
            .with_for_update()
        )
        if user is not None
        else None
    )
    tenant = (
        control_session.scalar(
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
        and membership is not None
        and membership.status == "active"
        and membership.released_at is None
        and tenant is not None
    )
    return build_tenant_login_sms_context(
        phone=phone,
        user_id=user.id if eligible else None,
        tenant_id=tenant.id if eligible else None,
        user_auth_version=user.auth_version if eligible else None,
    )


def _single_session_cookie(flask_request: Request) -> object:
    values = flask_request.cookies.getlist(TENANT_SESSION_COOKIE_NAME)
    return values[0] if len(values) == 1 else None


def _safe_device_name(value: object) -> str:
    if value is None:
        return "浏览器登录"
    if not isinstance(value, str):
        raise TenantLoginInputRejected()
    normalized = value.strip()
    if (
        not normalized
        or len(normalized) > 100
        or any(ord(character) < 32 for character in normalized)
    ):
        raise TenantLoginInputRejected()
    return normalized


def _safe_user_agent_summary(flask_request: Request) -> str:
    raw = flask_request.user_agent.string
    if not isinstance(raw, str) or not raw.strip():
        return "browser"
    first_product = raw.strip().split(maxsplit=1)[0]
    safe = "".join(
        character
        for character in first_product
        if character.isascii() and 32 <= ord(character) < 127
    )
    return (safe or "browser")[:80]


def _append_security_event(
    control_session,
    *,
    tenant_id: str,
    user_id: str,
    actor_session_id: str,
    target_session_id: str | None,
    event_type: str,
    reason_code: str,
    created_at: datetime,
) -> None:
    control_session.add(
        TenantAuthSecurityEvent(
            tenant_id=tenant_id,
            user_id=user_id,
            actor_session_id=actor_session_id,
            target_session_id=target_session_id,
            event_type=event_type,
            reason_code=reason_code,
            request_id=f"identity-session:{uuid4()}",
            created_at=created_at,
        )
    )
    control_session.flush()


__all__ = [
    "TENANT_IDENTITY_HTTP_RUNTIME_EXTENSION",
    "SqlAlchemyTenantIdentityHttpRuntime",
    "TenantIdentityHttpRuntime",
    "TenantIdentityRuntimeUnavailable",
    "TenantLoginInputRejected",
    "TenantLoginVerificationRejected",
    "TenantLoginRuntimeSettings",
    "TenantSmsRateLimited",
    "TenantPhoneChangeConflict",
    "TenantPhoneChangeInputRejected",
    "TenantPhoneChangeVerificationRejected",
    "TenantSessionTargetUnavailable",
    "require_tenant_identity_http_runtime",
]
