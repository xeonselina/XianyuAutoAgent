"""Fail-closed control-database runtime for tenant subscription renewal."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Mapping, Protocol, runtime_checkable
from uuid import UUID

from flask import Request, current_app
import sqlalchemy as sa

from inventory_control.database import ControlDatabase, read_database_utc_value
from inventory_control.domain import EffectiveTenantGate, TenantRole
from inventory_control.domain.rbac import Capability
from inventory_control.models import DisasterRecoveryRun, Subscription, Tenant
from inventory_control.redemption import (
    InvalidRedemptionCodeError,
    canonicalize_redemption_code,
)
from inventory_control.subscriptions import (
    SqlAlchemySubscriptionRenewalGate,
    SubscriptionRenewalAuthorizationError,
    SubscriptionRenewalCodeError,
    SubscriptionRenewalConflictError,
    SubscriptionRenewalGateError,
    SubscriptionRenewalService,
    SubscriptionRenewalTransactionError,
)
from inventory_control.tenant_http import (
    TenantHttpBoundary,
    TenantHttpError,
)


TENANT_SUBSCRIPTION_HTTP_RUNTIME_EXTENSION = (
    "inventory_tenant_subscription_http_runtime"
)


class TenantSubscriptionRuntimeUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("TENANT_SUBSCRIPTION_RUNTIME_UNAVAILABLE")


class TenantSubscriptionInputRejected(TenantHttpError):
    status_code = 400
    code = "SUBSCRIPTION_RENEWAL_INPUT_INVALID"
    public_message = "The subscription renewal request is invalid."


class TenantSubscriptionCodeRejected(TenantHttpError):
    status_code = 422
    code = "CODE_NOT_REDEEMABLE"
    public_message = "The redemption code cannot be used."


class TenantSubscriptionConflict(TenantHttpError):
    status_code = 409
    code = "SUBSCRIPTION_RENEWAL_CONFLICT"
    public_message = "The subscription changed; refresh and try again."


@runtime_checkable
class TenantSubscriptionHttpRuntime(Protocol):
    def status(
        self,
        *,
        flask_request: Request,
    ) -> Mapping[str, object]: ...

    def redeem(
        self,
        *,
        flask_request: Request,
        raw_code: object,
        idempotency_key: object,
        expected_subscription_row_version: object,
    ) -> Mapping[str, object]: ...


class SqlAlchemyTenantSubscriptionHttpRuntime:
    """Expose only the closed expired-page status and renewal loop."""

    __slots__ = (
        "_control_database",
        "_tenant_http_boundary",
        "_renewal_service",
    )

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        tenant_http_boundary: TenantHttpBoundary,
        renewal_service: SubscriptionRenewalService | None = None,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        if not isinstance(tenant_http_boundary, TenantHttpBoundary):
            raise TypeError("tenant_http_boundary must be a TenantHttpBoundary")
        if renewal_service is not None and not isinstance(
            renewal_service, SubscriptionRenewalService
        ):
            raise TypeError(
                "renewal_service must be a SubscriptionRenewalService"
            )
        self._control_database = control_database
        self._tenant_http_boundary = tenant_http_boundary
        self._renewal_service = renewal_service or SubscriptionRenewalService(
            gate_current_read=SqlAlchemySubscriptionRenewalGate()
        )

    @property
    def control_database(self) -> ControlDatabase:
        return self._control_database

    @property
    def tenant_http_boundary(self) -> TenantHttpBoundary:
        return self._tenant_http_boundary

    def status(self, *, flask_request: Request) -> Mapping[str, object]:
        try:
            with self._control_database.transaction() as control_session:
                database_now = _database_utc_now(control_session)
                context = self._tenant_http_boundary.authorize(
                    control_session,
                    flask_request,
                    capability=Capability.TENANT_EXPIRED_STATUS_READ,
                    now=database_now,
                )
                row = control_session.execute(
                    sa.select(
                        Subscription.id,
                        Subscription.expires_at,
                        Subscription.row_version,
                    ).where(Subscription.tenant_id == context.tenant_id)
                ).one_or_none()
                if row is None:
                    raise TenantSubscriptionRuntimeUnavailable()
                expires_at = _as_utc(row.expires_at)
                return {
                    "effective_status": (
                        "active" if expires_at > database_now else "expired"
                    ),
                    "expires_at": _utc_iso(expires_at),
                    "subscription_row_version": row.row_version,
                    "can_redeem": context.role is TenantRole.ADMIN,
                }
        except TenantHttpError:
            raise
        except TenantSubscriptionRuntimeUnavailable:
            raise
        except Exception:
            raise TenantSubscriptionRuntimeUnavailable() from None

    def redeem(
        self,
        *,
        flask_request: Request,
        raw_code: object,
        idempotency_key: object,
        expected_subscription_row_version: object,
    ) -> Mapping[str, object]:
        try:
            with self._control_database.transaction() as control_session:
                database_now = _database_utc_now(control_session)
                context = self._tenant_http_boundary.authorize(
                    control_session,
                    flask_request,
                    capability=Capability.TENANT_SUBSCRIPTION_REDEEM,
                    now=database_now,
                )
                canonical_code = canonicalize_redemption_code(raw_code)
                revision = _positive_int(expected_subscription_row_version)
                key = _idempotency_key(idempotency_key)

                tenant = control_session.scalar(
                    sa.select(Tenant)
                    .where(Tenant.id == context.tenant_id)
                    .with_for_update()
                )
                if tenant is None:
                    raise SubscriptionRenewalGateError(
                        "tenant is unavailable"
                    )
                runs = tuple(
                    control_session.scalars(
                        sa.select(DisasterRecoveryRun)
                        .where(
                            DisasterRecoveryRun.current_run_marker == "current"
                        )
                        .order_by(DisasterRecoveryRun.id)
                        .limit(2)
                        .with_for_update()
                    )
                )
                if len(runs) != 1 or runs[0].status != "completed":
                    raise SubscriptionRenewalGateError(
                        "current recovery run is unavailable"
                    )
                try:
                    current_run_uuid = UUID(runs[0].id)
                except (TypeError, ValueError, AttributeError):
                    raise TenantSubscriptionRuntimeUnavailable() from None
                result = self._renewal_service.renew(
                    control_session,
                    tenant_uuid=context.tenant_id,
                    membership_uuid=context.membership_id,
                    code_lookup_hash=canonical_code.lookup_hash,
                    idempotency_key=key,
                    current_recovery_run_uuid=current_run_uuid,
                    expected_tenant_access_version=(
                        context.tenant_access_version
                    ),
                    expected_subscription_row_version=revision,
                )
                return {
                    "effective_status": result.after_status,
                    "expires_at": _utc_iso(result.after_expires_at),
                    "subscription_row_version": (
                        result.resulting_subscription_row_version
                    ),
                    "idempotent_replay": not result.created,
                }
        except TenantHttpError:
            raise
        except InvalidRedemptionCodeError:
            raise TenantSubscriptionCodeRejected() from None
        except (ValueError, TypeError):
            raise TenantSubscriptionInputRejected() from None
        except SubscriptionRenewalCodeError:
            raise TenantSubscriptionCodeRejected() from None
        except SubscriptionRenewalAuthorizationError:
            raise TenantSubscriptionConflict() from None
        except (
            SubscriptionRenewalConflictError,
            SubscriptionRenewalGateError,
        ):
            raise TenantSubscriptionConflict() from None
        except SubscriptionRenewalTransactionError:
            raise TenantSubscriptionRuntimeUnavailable() from None
        except TenantSubscriptionRuntimeUnavailable:
            raise
        except Exception:
            raise TenantSubscriptionRuntimeUnavailable() from None

    def __repr__(self) -> str:
        return "SqlAlchemyTenantSubscriptionHttpRuntime(control_only=True)"


def require_tenant_subscription_http_runtime() -> TenantSubscriptionHttpRuntime:
    runtime = current_app.extensions.get(
        TENANT_SUBSCRIPTION_HTTP_RUNTIME_EXTENSION
    )
    if not isinstance(runtime, TenantSubscriptionHttpRuntime):
        raise TenantSubscriptionRuntimeUnavailable()
    return runtime


def _database_utc_now(control_session) -> datetime:
    return _as_utc(read_database_utc_value(control_session))


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise TenantSubscriptionRuntimeUnavailable()
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_iso(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


def _positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError("subscription revision is invalid")
    return value


def _idempotency_key(value: object) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not 1 <= len(value) <= 128
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("idempotency key is invalid")
    return value


__all__ = [
    "TENANT_SUBSCRIPTION_HTTP_RUNTIME_EXTENSION",
    "SqlAlchemyTenantSubscriptionHttpRuntime",
    "TenantSubscriptionCodeRejected",
    "TenantSubscriptionConflict",
    "TenantSubscriptionHttpRuntime",
    "TenantSubscriptionInputRejected",
    "TenantSubscriptionRuntimeUnavailable",
    "require_tenant_subscription_http_runtime",
]
