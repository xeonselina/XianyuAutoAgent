"""D53 preview and commit boundary with fresh-factor atomicity."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Mapping, Protocol, runtime_checkable
from uuid import UUID, uuid4

from flask import Request, current_app

from app.services.platform_identity import PlatformLoginRuntimeSettings
from inventory_control import ControlDatabase
from inventory_control.crypto import RootKeyRing, SqlAlchemyRootKeyRegistry
from inventory_control.database import read_database_utc_value
from inventory_control.domain import Capability
from inventory_control.models import PlatformAuditLog
from app.services.platform_control import build_platform_control_audit
from inventory_control.platform_http import (
    PlatformAuthContext,
    PlatformHttpBoundary,
    PlatformHttpError,
    resolve_platform_device_id,
)
from inventory_control.platform_identity import (
    PlatformAuthRateLimiter,
    PlatformRateLimitBlocked,
    PlatformRateLimitSubjects,
)
from inventory_control.proofs import (
    SubscriptionAdjustmentConfirmationError,
    issue_subscription_adjustment_confirmation,
    subscription_adjustment_preview_digest,
    verify_subscription_adjustment_confirmation,
)
from inventory_control.subscriptions import (
    PlatformSubscriptionAdjustmentService,
    ServicePeriodAdjustment,
    SqlAlchemySubscriptionAdjustmentGate,
    SubscriptionAdjustmentAuthenticationError,
    SubscriptionAdjustmentConflictError,
    SubscriptionAdjustmentGateError,
    SubscriptionAdjustmentMetadata,
    SubscriptionAdjustmentResult,
    SubscriptionRuleError,
    calculate_service_period_adjustment,
    read_subscription_adjustment_snapshot,
    service_period_calculation_base,
    service_period_effective_status,
    subscription_adjustment_request_digest,
    validate_subscription_adjustment_gate_status,
)
from inventory_control.sms import TrustedSourceBucket


PLATFORM_SUBSCRIPTION_ADJUSTMENT_HTTP_RUNTIME_EXTENSION = (
    "inventory_platform_subscription_adjustment_http_runtime"
)
_IDEMPOTENCY_KEY = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")


class PlatformSubscriptionAdjustmentRuntimeUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("PLATFORM_SUBSCRIPTION_ADJUSTMENT_RUNTIME_UNAVAILABLE")


class PlatformSubscriptionAdjustmentHttpInvalid(PlatformHttpError):
    status_code = 400
    code = "PLATFORM_SUBSCRIPTION_ADJUSTMENT_INVALID"
    public_message = "The service-period adjustment request is invalid."


class PlatformSubscriptionAdjustmentHttpConflict(PlatformHttpError):
    status_code = 409
    code = "PLATFORM_SUBSCRIPTION_ADJUSTMENT_CONFLICT"
    public_message = "The tenant state changed; request a new preview."


class PlatformSubscriptionAdjustmentHttpRejected(PlatformHttpError):
    status_code = 401
    code = "PLATFORM_SUBSCRIPTION_ADJUSTMENT_FACTOR_REJECTED"
    public_message = "The platform administrator factor is invalid."


@runtime_checkable
class PlatformSubscriptionAdjustmentHttpRuntime(Protocol):
    def preview(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        operation: object,
        days: object,
        reason_code: object,
        note: object,
        offline_reference: object,
        idempotency_key: object,
    ) -> Mapping[str, object]: ...

    def commit(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        operation: object,
        days: object,
        reason_code: object,
        note: object,
        offline_reference: object,
        idempotency_key: object,
        action_id: object,
        expected_subscription_row_version: object,
        confirmation_token: object,
        factor_method: object,
        factor_value: object,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class _AttemptAuthority:
    context: PlatformAuthContext
    key_ring: RootKeyRing
    subjects: PlatformRateLimitSubjects
    database_now: datetime
    trusted_source: str


class SqlAlchemyPlatformSubscriptionAdjustmentHttpRuntime:
    """Keep preview, fresh MFA, mutation, event, and audit boundaries explicit."""

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        platform_boundary: PlatformHttpBoundary,
        root_key_directory: str | os.PathLike[str],
        login_settings: PlatformLoginRuntimeSettings,
        confirmation_ttl: timedelta = timedelta(minutes=5),
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        if not isinstance(platform_boundary, PlatformHttpBoundary):
            raise TypeError("platform_boundary must be a PlatformHttpBoundary")
        if not isinstance(login_settings, PlatformLoginRuntimeSettings):
            raise TypeError("login_settings must be PlatformLoginRuntimeSettings")
        try:
            root_directory = os.fspath(root_key_directory)
        except TypeError:
            raise TypeError("root_key_directory must be an absolute path") from None
        if not isinstance(root_directory, str) or not Path(root_directory).is_absolute():
            raise ValueError("root_key_directory must be an absolute path")
        if (
            not isinstance(confirmation_ttl, timedelta)
            or confirmation_ttl <= timedelta(0)
            or confirmation_ttl > timedelta(minutes=5)
            or confirmation_ttl.microseconds != 0
        ):
            raise ValueError("confirmation_ttl is invalid")
        self._control_database = control_database
        self._platform_boundary = platform_boundary
        self._root_key_directory = root_directory
        self._login_settings = login_settings
        self._confirmation_ttl = confirmation_ttl

    @property
    def control_database(self) -> ControlDatabase:
        return self._control_database

    @property
    def platform_boundary(self) -> PlatformHttpBoundary:
        return self._platform_boundary

    def preview(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        operation: object,
        days: object,
        reason_code: object,
        note: object,
        offline_reference: object,
        idempotency_key: object,
    ) -> Mapping[str, object]:
        try:
            tenant_uuid = _uuid(tenant_id)
            adjustment = _adjustment(operation=operation, days=days)
            metadata = SubscriptionAdjustmentMetadata.from_values(
                reason_code=reason_code,
                note=note,
                offline_reference=offline_reference,
            )
            key = _idempotency_key(idempotency_key)
            authority = self._authorize(flask_request, check_factor_limit=False)
            action_uuid = uuid4()
            with self._control_database.transaction() as session:
                database_now = _database_now(session)
                snapshot = read_subscription_adjustment_snapshot(
                    session,
                    tenant_uuid=tenant_uuid,
                )
                validate_subscription_adjustment_gate_status(
                    tenant_status=snapshot.tenant_status,
                    gate=snapshot.gate,
                    adjustment=adjustment,
                )
                calculation = calculate_service_period_adjustment(
                    adjustment=adjustment,
                    current_expires_at=snapshot.subscription_expires_at,
                    database_now=database_now,
                )
                before_status = service_period_effective_status(
                    snapshot.subscription_expires_at,
                    database_now,
                )
                after_status = service_period_effective_status(
                    calculation.new_expires_at,
                    database_now,
                )
                calculation_base = service_period_calculation_base(
                    adjustment=adjustment,
                    current_expires_at=snapshot.subscription_expires_at,
                    database_now=database_now,
                )
                # Revision is part of the canonical request.  Recalculate after
                # reading the authoritative subscription instead of trusting a
                # client-supplied value.
                request_digest = subscription_adjustment_request_digest(
                    tenant_uuid=str(tenant_uuid),
                    platform_actor_uuid=authority.context.platform_admin_id,
                    platform_session_uuid=authority.context.session_id,
                    action_uuid=str(action_uuid),
                    idempotency_key=key,
                    expected_subscription_row_version=(
                        snapshot.fences.subscription_row_version
                    ),
                    adjustment=adjustment,
                    reason_code=metadata.reason_code,
                    note=metadata.note,
                    offline_reference=metadata.offline_reference,
                )
                preview_digest = subscription_adjustment_preview_digest(
                    database_effective_at=database_now,
                    calculation_base_at=calculation_base,
                    before_expires_at=snapshot.subscription_expires_at,
                    after_expires_at=calculation.new_expires_at,
                    before_status=before_status,
                    after_status=after_status,
                )
                token = issue_subscription_adjustment_confirmation(
                    root_key=authority.key_ring.active_key,
                    fences=snapshot.fences,
                    platform_actor_uuid=UUID(
                        authority.context.platform_admin_id
                    ),
                    platform_session_uuid=UUID(authority.context.session_id),
                    platform_auth_version=authority.context.admin_auth_version,
                    request_digest=request_digest,
                    preview_digest=preview_digest,
                    database_now=database_now,
                    ttl=self._confirmation_ttl,
                    action_uuid=action_uuid,
                )
            return {
                "action_id": str(action_uuid),
                "confirmation_token": token,
                "operation": adjustment.action.value,
                "days": _days(adjustment),
                "database_effective_at": _iso(database_now),
                "calculation_base_at": _iso(calculation_base),
                "before_expires_at": _iso(snapshot.subscription_expires_at),
                "after_expires_at": _iso(calculation.new_expires_at),
                "before_status": before_status,
                "after_status": after_status,
                "expected_tenant_row_version": snapshot.fences.tenant_row_version,
                "expected_subscription_row_version": (
                    snapshot.fences.subscription_row_version
                ),
                "expires_at": _iso(database_now + self._confirmation_ttl),
            }
        except PlatformHttpError:
            raise
        except (
            SubscriptionAdjustmentGateError,
            SubscriptionRuleError,
        ):
            raise PlatformSubscriptionAdjustmentHttpConflict() from None
        except (TypeError, ValueError):
            raise PlatformSubscriptionAdjustmentHttpInvalid() from None
        except Exception:
            raise PlatformSubscriptionAdjustmentRuntimeUnavailable() from None

    def commit(
        self,
        *,
        flask_request: Request,
        tenant_id: object,
        operation: object,
        days: object,
        reason_code: object,
        note: object,
        offline_reference: object,
        idempotency_key: object,
        action_id: object,
        expected_subscription_row_version: object,
        confirmation_token: object,
        factor_method: object,
        factor_value: object,
    ) -> Mapping[str, object]:
        try:
            tenant_uuid = _uuid(tenant_id)
            action_uuid = _uuid(action_id)
            expected_revision = _positive_int(
                expected_subscription_row_version
            )
            adjustment = _adjustment(operation=operation, days=days)
            metadata = SubscriptionAdjustmentMetadata.from_values(
                reason_code=reason_code,
                note=note,
                offline_reference=offline_reference,
            )
            key = _idempotency_key(idempotency_key)
            authority = self._authorize(flask_request, check_factor_limit=True)
            try:
                selected_factor_method = _factor_method(factor_method)
            except ValueError:
                self._record_factor_failure(
                    authority=authority,
                    tenant_uuid=tenant_uuid,
                    factor_method=factor_method,
                )
                raise PlatformSubscriptionAdjustmentHttpRejected() from None
            request_digest = subscription_adjustment_request_digest(
                tenant_uuid=str(tenant_uuid),
                platform_actor_uuid=authority.context.platform_admin_id,
                platform_session_uuid=authority.context.session_id,
                action_uuid=str(action_uuid),
                idempotency_key=key,
                expected_subscription_row_version=expected_revision,
                adjustment=adjustment,
                reason_code=metadata.reason_code,
                note=metadata.note,
                offline_reference=metadata.offline_reference,
            )
            try:
                confirmation = verify_subscription_adjustment_confirmation(
                    token=confirmation_token,
                    root_key=authority.key_ring.active_key,
                    expected_platform_actor_uuid=UUID(
                        authority.context.platform_admin_id
                    ),
                    expected_platform_session_uuid=UUID(
                        authority.context.session_id
                    ),
                    expected_platform_auth_version=(
                        authority.context.admin_auth_version
                    ),
                    expected_request_digest=request_digest,
                    database_now=authority.database_now,
                )
                if (
                    confirmation.action_uuid != action_uuid
                    or confirmation.fences.tenant_uuid != tenant_uuid
                    or confirmation.fences.subscription_row_version
                    != expected_revision
                ):
                    raise SubscriptionAdjustmentConfirmationError(
                        "adjustment confirmation is invalid or stale"
                    )
            except SubscriptionAdjustmentConfirmationError:
                replay = self._try_replay(
                    authority=authority,
                    tenant_uuid=tenant_uuid,
                    action_uuid=action_uuid,
                    idempotency_key=key,
                    expected_revision=expected_revision,
                    adjustment=adjustment,
                    metadata=metadata,
                )
                if replay is not None:
                    return _result_payload(replay)
                self._record_rejection(
                    authority=authority,
                    tenant_uuid=tenant_uuid,
                    outcome="rejected",
                    reason_code="subscription_adjustment.confirmation_rejected",
                    factor_method=None,
                )
                raise PlatformSubscriptionAdjustmentHttpConflict() from None

            service = PlatformSubscriptionAdjustmentService(
                gate_current_read=SqlAlchemySubscriptionAdjustmentGate(
                    expected_fences=confirmation.fences
                ),
                allowed_totp_drift_steps=(
                    self._login_settings.policy.allowed_totp_drift_steps
                ),
            )
            with self._control_database.transaction() as session:
                result = service.adjust(
                    session,
                    tenant_uuid=tenant_uuid,
                    platform_actor_uuid=authority.context.platform_admin_id,
                    platform_session_uuid=authority.context.session_id,
                    action_uuid=action_uuid,
                    idempotency_key=key,
                    expected_subscription_row_version=expected_revision,
                    adjustment=adjustment,
                    reason_code=metadata.reason_code,
                    note=metadata.note,
                    offline_reference=metadata.offline_reference,
                    factor_method=selected_factor_method,
                    presented_factor=factor_value,
                    root_key_ring=authority.key_ring,
                )
                if result.created:
                    session.add(
                        _audit(
                            authority=authority,
                            tenant_uuid=tenant_uuid,
                            outcome="succeeded",
                            reason_code="subscription_adjustment.succeeded",
                            factor_method=selected_factor_method,
                            result_count=1,
                            target_resource_id=result.event_uuid,
                            created_at=result.database_effective_at,
                        )
                    )
                    session.flush()
            return _result_payload(result)
        except PlatformSubscriptionAdjustmentHttpRejected:
            raise
        except SubscriptionAdjustmentAuthenticationError:
            if "authority" in locals():
                self._record_factor_failure(
                    authority=authority,
                    tenant_uuid=tenant_uuid,
                    factor_method=factor_method,
                )
            raise PlatformSubscriptionAdjustmentHttpRejected() from None
        except (SubscriptionAdjustmentConflictError, SubscriptionAdjustmentGateError):
            if "authority" in locals():
                self._record_rejection(
                    authority=authority,
                    tenant_uuid=tenant_uuid,
                    outcome="rejected",
                    reason_code="subscription_adjustment.state_changed",
                    factor_method=None,
                )
            raise PlatformSubscriptionAdjustmentHttpConflict() from None
        except PlatformHttpError:
            raise
        except (SubscriptionRuleError, TypeError, ValueError):
            raise PlatformSubscriptionAdjustmentHttpInvalid() from None
        except Exception:
            raise PlatformSubscriptionAdjustmentRuntimeUnavailable() from None

    def _authorize(
        self,
        flask_request: Request,
        *,
        check_factor_limit: bool,
    ) -> _AttemptAuthority:
        device_id, _ = resolve_platform_device_id(flask_request)
        trusted_source = self._trusted_source(flask_request)
        blocked = False
        authority = None
        with self._control_database.transaction() as session:
            now = _database_now(session)
            context = self._platform_boundary.authorize(
                session,
                flask_request,
                capability=Capability.PLATFORM_SUBSCRIPTION_ADJUST,
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
            if check_factor_limit:
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
                    blocked = True
                    session.add(
                        _audit(
                            authority=_AttemptAuthority(
                                context=context,
                                key_ring=key_ring,
                                subjects=subjects,
                                database_now=now,
                                trusted_source=trusted_source.value,
                            ),
                            tenant_uuid=None,
                            outcome="rate_limited",
                            reason_code=(
                                "subscription_adjustment.factor_rate_limited"
                            ),
                            factor_method=None,
                            result_count=0,
                            created_at=now,
                        )
                    )
                    session.flush()
            authority = _AttemptAuthority(
                context=context,
                key_ring=key_ring,
                subjects=subjects,
                database_now=now,
                trusted_source=trusted_source.value,
            )
        if blocked or authority is None:
            raise PlatformSubscriptionAdjustmentHttpRejected()
        return authority

    def _try_replay(
        self,
        *,
        authority: _AttemptAuthority,
        tenant_uuid: UUID,
        action_uuid: UUID,
        idempotency_key: str,
        expected_revision: int,
        adjustment: ServicePeriodAdjustment,
        metadata: SubscriptionAdjustmentMetadata,
    ) -> SubscriptionAdjustmentResult | None:
        def deny_non_replay(_session, _tenant, _database_now):
            raise SubscriptionAdjustmentConflictError(
                "adjustment was not previously committed"
            )

        service = PlatformSubscriptionAdjustmentService(
            gate_current_read=deny_non_replay
        )
        try:
            with self._control_database.transaction() as session:
                return service.adjust(
                    session,
                    tenant_uuid=tenant_uuid,
                    platform_actor_uuid=authority.context.platform_admin_id,
                    platform_session_uuid=authority.context.session_id,
                    action_uuid=action_uuid,
                    idempotency_key=idempotency_key,
                    expected_subscription_row_version=expected_revision,
                    adjustment=adjustment,
                    reason_code=metadata.reason_code,
                    note=metadata.note,
                    offline_reference=metadata.offline_reference,
                    factor_method="recovery_code",
                    presented_factor=None,
                )
        except SubscriptionAdjustmentConflictError:
            return None

    def _record_factor_failure(
        self,
        *,
        authority: _AttemptAuthority,
        tenant_uuid: UUID,
        factor_method: object,
    ) -> None:
        selected_method = (
            factor_method
            if factor_method in {"totp", "recovery_code"}
            else None
        )
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                key_ring = SqlAlchemyRootKeyRegistry(session=session).load(
                    self._root_key_directory
                )
                PlatformAuthRateLimiter(
                    policy=self._login_settings.policy.rate_limit,
                    root_key=key_ring.active_key,
                ).record_failure(
                    session,
                    scope="mfa",
                    subjects=authority.subjects,
                    now=now,
                )
                session.add(
                    _audit(
                        authority=authority,
                        tenant_uuid=tenant_uuid,
                        outcome="rejected",
                        reason_code="subscription_adjustment.factor_rejected",
                        factor_method=selected_method,
                        result_count=0,
                        created_at=now,
                    )
                )
                session.flush()
        except Exception:
            raise PlatformSubscriptionAdjustmentRuntimeUnavailable() from None

    def _record_rejection(
        self,
        *,
        authority: _AttemptAuthority,
        tenant_uuid: UUID,
        outcome: str,
        reason_code: str,
        factor_method: str | None,
    ) -> None:
        try:
            with self._control_database.transaction() as session:
                now = _database_now(session)
                session.add(
                    _audit(
                        authority=authority,
                        tenant_uuid=tenant_uuid,
                        outcome=outcome,
                        reason_code=reason_code,
                        factor_method=factor_method,
                        result_count=0,
                        created_at=now,
                    )
                )
                session.flush()
        except Exception:
            raise PlatformSubscriptionAdjustmentRuntimeUnavailable() from None

    def _trusted_source(self, flask_request: Request) -> TrustedSourceBucket:
        try:
            source = self._login_settings.trusted_source_resolver(flask_request)
        except Exception:
            raise PlatformSubscriptionAdjustmentRuntimeUnavailable() from None
        if not isinstance(source, TrustedSourceBucket):
            raise PlatformSubscriptionAdjustmentRuntimeUnavailable()
        return source


def install_platform_subscription_adjustment_http_runtime(
    app,
    *,
    runtime: PlatformSubscriptionAdjustmentHttpRuntime,
) -> None:
    if PLATFORM_SUBSCRIPTION_ADJUSTMENT_HTTP_RUNTIME_EXTENSION in app.extensions:
        raise RuntimeError(
            "platform subscription adjustment runtime is already installed"
        )
    if not isinstance(runtime, PlatformSubscriptionAdjustmentHttpRuntime):
        raise TypeError(
            "runtime must implement PlatformSubscriptionAdjustmentHttpRuntime"
        )
    app.extensions[PLATFORM_SUBSCRIPTION_ADJUSTMENT_HTTP_RUNTIME_EXTENSION] = runtime


def require_platform_subscription_adjustment_http_runtime(
) -> PlatformSubscriptionAdjustmentHttpRuntime:
    runtime = current_app.extensions.get(
        PLATFORM_SUBSCRIPTION_ADJUSTMENT_HTTP_RUNTIME_EXTENSION
    )
    if not isinstance(runtime, PlatformSubscriptionAdjustmentHttpRuntime):
        raise PlatformSubscriptionAdjustmentRuntimeUnavailable()
    return runtime


def _adjustment(*, operation: object, days: object) -> ServicePeriodAdjustment:
    if operation == "add_days":
        return ServicePeriodAdjustment(add_days=_positive_int(days))
    if operation == "subtract_days":
        return ServicePeriodAdjustment(subtract_days=_positive_int(days))
    if operation == "expire_now" and days is None:
        return ServicePeriodAdjustment(expire_now=True)
    raise ValueError("adjustment operation is invalid")


def _days(adjustment: ServicePeriodAdjustment) -> int | None:
    return adjustment.add_days or adjustment.subtract_days


def _uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValueError("UUID is invalid")


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("positive integer is required")
    return value


def _idempotency_key(value: object) -> str:
    if not isinstance(value, str) or _IDEMPOTENCY_KEY.fullmatch(value) is None:
        raise ValueError("idempotency key is invalid")
    return value


def _factor_method(value: object) -> str:
    if value not in {"totp", "recovery_code"}:
        raise ValueError("factor method is invalid")
    return value


def _database_now(session) -> datetime:
    value = read_database_utc_value(session)
    if not isinstance(value, datetime):
        raise RuntimeError("control database clock is invalid")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _result_payload(result: SubscriptionAdjustmentResult) -> Mapping[str, object]:
    return {
        "tenant_id": result.tenant_uuid,
        "subscription_id": result.subscription_uuid,
        "event_id": result.event_uuid,
        "action_id": result.action_uuid,
        "operation": result.action.value,
        "signed_delta_days": result.signed_delta_days,
        "database_effective_at": _iso(result.database_effective_at),
        "calculation_base_at": _iso(result.calculation_base_at),
        "before_expires_at": _iso(result.before_expires_at),
        "after_expires_at": _iso(result.after_expires_at),
        "before_status": result.before_status,
        "after_status": result.after_status,
        "resulting_subscription_row_version": (
            result.resulting_subscription_row_version
        ),
        "created": result.created,
        "refund_disclaimer": (
            "This service-period record does not prove that funds were refunded."
        ),
    }


def _audit(
    *,
    authority: _AttemptAuthority,
    tenant_uuid: UUID | None,
    outcome: str,
    reason_code: str,
    factor_method: object,
    result_count: int,
    created_at: datetime,
    target_resource_id: str | None = None,
) -> PlatformAuditLog:
    selected_method = (
        factor_method if factor_method in {"totp", "recovery_code"} else None
    )
    return build_platform_control_audit(
        context=authority.context,
        target_tenant_id=(
            str(tenant_uuid) if tenant_uuid is not None else None
        ),
        target_resource_type="subscription_event",
        target_resource_id=target_resource_id,
        route_template=(
            "POST /platform/api/tenants/<tenant_id>/subscription-adjustments"
        ),
        action="platform.subscription.adjust",
        outcome=outcome,
        reason_code=reason_code,
        authentication_factor=selected_method,
        result_count=result_count,
        request_id_prefix="platform-d53",
        ip_summary=authority.trusted_source,
        created_at=created_at,
    )


__all__ = [
    "PLATFORM_SUBSCRIPTION_ADJUSTMENT_HTTP_RUNTIME_EXTENSION",
    "PlatformSubscriptionAdjustmentHttpConflict",
    "PlatformSubscriptionAdjustmentHttpInvalid",
    "PlatformSubscriptionAdjustmentHttpRejected",
    "PlatformSubscriptionAdjustmentHttpRuntime",
    "PlatformSubscriptionAdjustmentRuntimeUnavailable",
    "SqlAlchemyPlatformSubscriptionAdjustmentHttpRuntime",
    "install_platform_subscription_adjustment_http_runtime",
    "require_platform_subscription_adjustment_http_runtime",
]
