"""Control-only redemption-code list, generation, reveal, and revocation."""

from __future__ import annotations

import csv
import os
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Iterator, Mapping, Protocol, runtime_checkable
from uuid import UUID

import sqlalchemy as sa
from flask import Request, current_app
from sqlalchemy.orm import Session

from app.services.platform_control import build_platform_control_audit
from app.services.platform_identity import PlatformLoginRuntimeSettings
from inventory_control import ControlDatabase
from inventory_control.crypto import RootKeyRing, SqlAlchemyRootKeyRegistry
from inventory_control.database import read_database_utc_value
from inventory_control.domain import Capability
from inventory_control.models import (
    DisasterRecoveryRun,
    PlanRevision,
    PlatformAuditLog,
)
from inventory_control.platform_http import (
    PlatformAuthContext,
    PlatformHttpBoundary,
    PlatformHttpError,
    resolve_platform_device_id,
)
from inventory_control.platform_identity import (
    PlatformAdminRateLimiter,
    PlatformRateLimitBlocked,
    PlatformRateLimitPolicy,
    PlatformRateLimitSubjects,
)
from inventory_control.redemption import (
    RedemptionBatchConflictError,
    RedemptionCodeManagementService,
    RedemptionCodeNotFound,
    RedemptionCodeRevisionConflict,
    RedemptionCodeService,
    RedemptionGenerationDenied,
)
from inventory_control.sms import TrustedSourceBucket


PLATFORM_REDEMPTION_HTTP_RUNTIME_EXTENSION = (
    "inventory_platform_redemption_http_runtime"
)


class PlatformRedemptionRuntimeUnavailable(RuntimeError):
    def __init__(self) -> None:
        super().__init__("PLATFORM_REDEMPTION_RUNTIME_UNAVAILABLE")


class PlatformRedemptionHttpInvalid(PlatformHttpError):
    status_code = 400
    code = "PLATFORM_REDEMPTION_INVALID"
    public_message = "The redemption-code request is invalid."


class PlatformRedemptionHttpConflict(PlatformHttpError):
    status_code = 409
    code = "PLATFORM_REDEMPTION_CONFLICT"
    public_message = "The redemption-code state changed; reload and retry."


class PlatformRedemptionHttpNotFound(PlatformHttpError):
    status_code = 404
    code = "PLATFORM_REDEMPTION_NOT_FOUND"
    public_message = "The redemption code is unavailable."


class PlatformRedemptionHttpRateLimited(PlatformHttpError):
    status_code = 429
    code = "PLATFORM_REDEMPTION_RATE_LIMITED"
    public_message = "Redemption-code reveal is temporarily limited."


@dataclass(frozen=True, slots=True, repr=False)
class PlatformRedemptionRuntimeSettings:
    reveal_rate_limit: PlatformRateLimitPolicy

    def __post_init__(self) -> None:
        if not isinstance(self.reveal_rate_limit, PlatformRateLimitPolicy):
            raise TypeError("reveal_rate_limit must be a platform policy")
        if self.reveal_rate_limit.scopes != frozenset({"code_reveal"}):
            raise ValueError("reveal rate-limit policy has invalid scopes")

    def __repr__(self) -> str:
        return "PlatformRedemptionRuntimeSettings(<explicit-policy>)"


@runtime_checkable
class PlatformRedemptionHttpRuntime(Protocol):
    def list_codes(
        self,
        *,
        flask_request: Request,
        page: object,
        page_size: object,
        status: object,
    ) -> Mapping[str, object]: ...

    def generate_batch(
        self,
        *,
        flask_request: Request,
        generation_request_id: object,
        name: object,
        quantity: object,
        service_duration_days: object,
        redeem_before: object,
        channel: object,
        internal_note: object,
    ) -> Mapping[str, object]: ...

    def reveal_code(
        self,
        *,
        flask_request: Request,
        code_id: object,
    ) -> Mapping[str, object]: ...

    def revoke_code(
        self,
        *,
        flask_request: Request,
        code_id: object,
        expected_row_version: object,
        reason_code: object,
    ) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class _ControlScope:
    session: Session
    context: PlatformAuthContext
    database_now: datetime
    trusted_source: str
    root_key_ring: RootKeyRing | None


@dataclass(frozen=True, slots=True)
class _AuditOperation:
    route_template: str
    action: str


_AUDIT_OPERATIONS = {
    "list": _AuditOperation(
        route_template="GET /platform/api/redemption-codes",
        action="platform.redemption_codes.list",
    ),
    "generate": _AuditOperation(
        route_template="POST /platform/api/redemption-code-batches",
        action="platform.redemption_codes.generate",
    ),
    "export": _AuditOperation(
        route_template="POST /platform/api/redemption-code-batches",
        action="platform.redemption_codes.export",
    ),
    "reveal": _AuditOperation(
        route_template="POST /platform/api/redemption-codes/<code_id>/reveal",
        action="platform.redemption_codes.reveal",
    ),
    "revoke": _AuditOperation(
        route_template="POST /platform/api/redemption-codes/<code_id>/revoke",
        action="platform.redemption_codes.revoke",
    ),
}


class SqlAlchemyPlatformRedemptionHttpRuntime:
    """Reuse one authorization/transaction scope across every code operation."""

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        platform_boundary: PlatformHttpBoundary,
        root_key_directory: str | os.PathLike[str],
        login_settings: PlatformLoginRuntimeSettings,
        runtime_settings: PlatformRedemptionRuntimeSettings,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise TypeError("control_database must be a ControlDatabase")
        if not isinstance(platform_boundary, PlatformHttpBoundary):
            raise TypeError("platform_boundary must be a PlatformHttpBoundary")
        if not isinstance(login_settings, PlatformLoginRuntimeSettings):
            raise TypeError("login_settings must be PlatformLoginRuntimeSettings")
        if not isinstance(runtime_settings, PlatformRedemptionRuntimeSettings):
            raise TypeError(
                "runtime_settings must be PlatformRedemptionRuntimeSettings"
            )
        try:
            root_directory = os.fspath(root_key_directory)
        except TypeError:
            raise TypeError("root_key_directory must be an absolute path") from None
        if (
            not isinstance(root_directory, str)
            or not Path(root_directory).is_absolute()
        ):
            raise ValueError("root_key_directory must be an absolute path")
        self._control_database = control_database
        self._platform_boundary = platform_boundary
        self._root_key_directory = root_directory
        self._login_settings = login_settings
        self._runtime_settings = runtime_settings
        self._management = RedemptionCodeManagementService()
        self._generation = RedemptionCodeService()

    @property
    def control_database(self) -> ControlDatabase:
        return self._control_database

    @property
    def platform_boundary(self) -> PlatformHttpBoundary:
        return self._platform_boundary

    def list_codes(
        self,
        *,
        flask_request: Request,
        page: object,
        page_size: object,
        status: object,
    ) -> Mapping[str, object]:
        try:
            with self._scope(flask_request) as scope:
                result = self._management.list_codes(
                    scope.session,
                    database_now=scope.database_now,
                    page=_integer(page),
                    page_size=_integer(page_size),
                    status=_optional_status(status),
                )
                scope.session.add(
                    self._audit(
                        scope,
                        operation="list",
                        reason_code="redemption_codes.listed",
                        outcome="succeeded",
                        result_count=len(result.items),
                    )
                )
                scope.session.flush()
            return {
                "items": [_list_payload(item) for item in result.items],
                "page": result.page,
                "page_size": result.page_size,
                "total": result.total,
                "pages": (result.total + result.page_size - 1) // result.page_size,
            }
        except PlatformHttpError:
            raise
        except (TypeError, ValueError):
            self._record_rejection(
                flask_request,
                operation="list",
                reason_code="redemption_codes.list_rejected",
            )
            raise PlatformRedemptionHttpInvalid() from None
        except Exception:
            raise PlatformRedemptionRuntimeUnavailable() from None

    def generate_batch(
        self,
        *,
        flask_request: Request,
        generation_request_id: object,
        name: object,
        quantity: object,
        service_duration_days: object,
        redeem_before: object,
        channel: object,
        internal_note: object,
    ) -> Mapping[str, object]:
        try:
            request_uuid = _uuid(generation_request_id)
            selected_name = _text(name)
            selected_quantity = _bounded_integer(quantity, maximum=1_000)
            duration_days = _bounded_integer(
                service_duration_days,
                maximum=3_650_000,
            )
            deadline = _datetime(redeem_before)
            selected_channel = _optional_text(channel)
            selected_note = _optional_text(internal_note)
            with self._scope(flask_request, load_root_keys=True) as scope:
                run = _current_completed_run(scope.session, locking=True)
                plan = _current_core_plan(scope.session, locking=True)
                if scope.root_key_ring is None:
                    raise PlatformRedemptionRuntimeUnavailable()
                generated = self._generation.generate_batch(
                    scope.session,
                    root_key=scope.root_key_ring.active_key,
                    current_recovery_run_uuid=UUID(run.id),
                    recovery_run_completed=True,
                    platform_admin_uuid=UUID(scope.context.platform_admin_id),
                    generation_request_uuid=request_uuid,
                    plan_revision_uuid=UUID(plan.id),
                    name=selected_name,
                    quantity=selected_quantity,
                    service_duration=timedelta(days=duration_days),
                    redeem_before=deadline,
                    database_now=scope.database_now,
                    channel=selected_channel,
                    internal_note=selected_note,
                )
                export_csv = (
                    _initial_csv(
                        generated.issued_codes,
                        batch_name=selected_name,
                        duration_days=duration_days,
                        redeem_before=deadline,
                        channel=selected_channel,
                    )
                    if generated.created
                    else None
                )
                scope.session.add(
                    self._audit(
                        scope,
                        operation="generate",
                        reason_code=(
                            "redemption_codes.generated"
                            if generated.created
                            else "redemption_codes.generation_replayed"
                        ),
                        outcome="succeeded",
                        result_count=len(generated.issued_codes),
                        target_resource_type="redemption_code_batch",
                        target_resource_id=str(generated.batch_uuid),
                    )
                )
                if generated.created:
                    scope.session.add(
                        self._audit(
                            scope,
                            operation="export",
                            reason_code="redemption_codes.initial_exported",
                            outcome="succeeded",
                            result_count=len(generated.issued_codes),
                            target_resource_type="redemption_code_batch",
                            target_resource_id=str(generated.batch_uuid),
                        )
                    )
                scope.session.flush()
            return {
                "batch_id": str(generated.batch_uuid),
                "created": generated.created,
                "quantity": len(generated.issued_codes),
                "export_filename": (
                    f"redemption-codes-{generated.batch_uuid}.csv"
                    if generated.created
                    else None
                ),
                "export_csv": export_csv,
            }
        except PlatformHttpError:
            raise
        except RedemptionBatchConflictError:
            self._record_rejection(
                flask_request,
                operation="generate",
                reason_code="redemption_codes.generation_conflict",
                target_resource_type="redemption_generation_request",
                target_resource_id=_safe_uuid_text(generation_request_id),
            )
            raise PlatformRedemptionHttpConflict() from None
        except RedemptionGenerationDenied:
            self._record_rejection(
                flask_request,
                operation="generate",
                reason_code="redemption_codes.generation_denied",
                target_resource_type="redemption_generation_request",
                target_resource_id=_safe_uuid_text(generation_request_id),
            )
            raise PlatformRedemptionHttpConflict() from None
        except (TypeError, ValueError, OverflowError):
            self._record_rejection(
                flask_request,
                operation="generate",
                reason_code="redemption_codes.generation_rejected",
                target_resource_type="redemption_generation_request",
                target_resource_id=_safe_uuid_text(generation_request_id),
            )
            raise PlatformRedemptionHttpInvalid() from None
        except Exception:
            raise PlatformRedemptionRuntimeUnavailable() from None

    def reveal_code(
        self,
        *,
        flask_request: Request,
        code_id: object,
    ) -> Mapping[str, object]:
        try:
            device_id, _ = resolve_platform_device_id(flask_request)
            revealed = None
            response_error: PlatformHttpError | None = None
            with self._scope(flask_request, load_root_keys=True) as scope:
                if scope.root_key_ring is None:
                    raise PlatformRedemptionRuntimeUnavailable()
                subjects = PlatformRateLimitSubjects(
                    username=scope.context.username_canonical,
                    ip=scope.trusted_source,
                    device=device_id,
                )
                limiter = PlatformAdminRateLimiter(
                    policy=self._runtime_settings.reveal_rate_limit,
                    root_key=scope.root_key_ring.active_key,
                )
                try:
                    limiter.check(
                        scope.session,
                        scope="code_reveal",
                        subjects=subjects,
                        now=scope.database_now,
                    )
                except PlatformRateLimitBlocked:
                    response_error = PlatformRedemptionHttpRateLimited()
                    scope.session.add(
                        self._audit(
                            scope,
                            operation="reveal",
                            reason_code="redemption_code.reveal_rate_limited",
                            outcome="rate_limited",
                            result_count=0,
                            target_resource_type="redemption_code",
                            target_resource_id=_safe_uuid_text(code_id),
                        )
                    )
                else:
                    limiter.record_attempt(
                        scope.session,
                        scope="code_reveal",
                        subjects=subjects,
                        now=scope.database_now,
                    )
                    try:
                        code_uuid = _uuid(code_id)
                        revealed = self._management.reveal_code(
                            scope.session,
                            code_uuid=code_uuid,
                            root_key_ring=scope.root_key_ring,
                        )
                    except RedemptionCodeNotFound:
                        response_error = PlatformRedemptionHttpNotFound()
                    except (TypeError, ValueError):
                        response_error = PlatformRedemptionHttpInvalid()
                    if response_error is not None:
                        scope.session.add(
                            self._audit(
                                scope,
                                operation="reveal",
                                reason_code="redemption_code.reveal_rejected",
                                outcome="rejected",
                                result_count=0,
                                target_resource_type="redemption_code",
                                target_resource_id=_safe_uuid_text(code_id),
                            )
                        )
                    else:
                        scope.session.add(
                            self._audit(
                                scope,
                                operation="reveal",
                                reason_code="redemption_code.revealed",
                                outcome="succeeded",
                                result_count=1,
                                target_resource_type="redemption_code",
                                target_resource_id=str(code_uuid),
                            )
                        )
                scope.session.flush()
            if response_error is not None:
                raise response_error
            if revealed is None:
                raise PlatformRedemptionRuntimeUnavailable()
            return {
                "code_id": str(revealed.code_uuid),
                "code": revealed.plaintext.value,
                "status": revealed.status,
                "row_version": revealed.row_version,
            }
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformRedemptionRuntimeUnavailable() from None

    def revoke_code(
        self,
        *,
        flask_request: Request,
        code_id: object,
        expected_row_version: object,
        reason_code: object,
    ) -> Mapping[str, object]:
        try:
            code_uuid = _uuid(code_id)
            revision = _bounded_integer(
                expected_row_version,
                maximum=9_223_372_036_854_775_807,
            )
            selected_reason = _text(reason_code)
            with self._scope(flask_request) as scope:
                result = self._management.revoke_code(
                    scope.session,
                    code_uuid=code_uuid,
                    expected_row_version=revision,
                    reason_code=selected_reason,
                    database_now=scope.database_now,
                )
                scope.session.add(
                    self._audit(
                        scope,
                        operation="revoke",
                        reason_code=(
                            result.denial_reason
                            or (
                                "redemption_code.revoked"
                                if result.changed
                                else "redemption_code.revocation_replayed"
                            )
                        ),
                        outcome=(
                            "rejected"
                            if result.denial_reason is not None
                            else "succeeded"
                        ),
                        result_count=1 if result.changed else 0,
                        target_resource_type="redemption_code",
                        target_resource_id=str(code_uuid),
                    )
                )
                scope.session.flush()
            if result.denial_reason is not None:
                raise PlatformRedemptionHttpConflict()
            return {
                "code_id": str(result.code_uuid),
                "status": result.status,
                "row_version": result.row_version,
                "changed": result.changed,
            }
        except PlatformHttpError:
            raise
        except RedemptionCodeNotFound:
            self._record_rejection(
                flask_request,
                operation="revoke",
                reason_code="redemption_code.revocation_rejected",
                target_resource_type="redemption_code",
                target_resource_id=_safe_uuid_text(code_id),
            )
            raise PlatformRedemptionHttpNotFound() from None
        except RedemptionCodeRevisionConflict:
            self._record_rejection(
                flask_request,
                operation="revoke",
                reason_code="redemption_code.revision_conflict",
                target_resource_type="redemption_code",
                target_resource_id=_safe_uuid_text(code_id),
            )
            raise PlatformRedemptionHttpConflict() from None
        except (TypeError, ValueError):
            self._record_rejection(
                flask_request,
                operation="revoke",
                reason_code="redemption_code.revocation_rejected",
                target_resource_type="redemption_code",
                target_resource_id=_safe_uuid_text(code_id),
            )
            raise PlatformRedemptionHttpInvalid() from None
        except Exception:
            raise PlatformRedemptionRuntimeUnavailable() from None

    @contextmanager
    def _scope(
        self,
        flask_request: Request,
        *,
        load_root_keys: bool = False,
    ) -> Iterator[_ControlScope]:
        source = self._trusted_source(flask_request)
        with self._control_database.transaction() as session:
            now = _database_now(session)
            context = self._platform_boundary.authorize(
                session,
                flask_request,
                capability=Capability.PLATFORM_REDEMPTION_CODES_MANAGE,
                now=now,
                ip_summary=source.value,
            )
            key_ring = (
                SqlAlchemyRootKeyRegistry(session=session).load(
                    self._root_key_directory
                )
                if load_root_keys
                else None
            )
            yield _ControlScope(
                session=session,
                context=context,
                database_now=now,
                trusted_source=source.value,
                root_key_ring=key_ring,
            )

    @staticmethod
    def _audit(
        scope: _ControlScope,
        *,
        operation: str,
        reason_code: str,
        outcome: str,
        result_count: int,
        target_resource_type: str | None = None,
        target_resource_id: str | None = None,
    ) -> PlatformAuditLog:
        definition = _AUDIT_OPERATIONS[operation]
        return build_platform_control_audit(
            context=scope.context,
            route_template=definition.route_template,
            action=definition.action,
            outcome=outcome,
            reason_code=reason_code,
            created_at=scope.database_now,
            request_id_prefix="platform-redemption",
            ip_summary=scope.trusted_source,
            result_count=result_count,
            target_resource_type=target_resource_type,
            target_resource_id=target_resource_id,
        )

    def _trusted_source(self, flask_request: Request) -> TrustedSourceBucket:
        try:
            source = self._login_settings.trusted_source_resolver(flask_request)
        except Exception:
            raise PlatformRedemptionRuntimeUnavailable() from None
        if not isinstance(source, TrustedSourceBucket):
            raise PlatformRedemptionRuntimeUnavailable()
        return source

    def _record_rejection(
        self,
        flask_request: Request,
        *,
        operation: str,
        reason_code: str,
        target_resource_type: str | None = None,
        target_resource_id: str | None = None,
    ) -> None:
        try:
            with self._scope(flask_request) as scope:
                scope.session.add(
                    self._audit(
                        scope,
                        operation=operation,
                        reason_code=reason_code,
                        outcome="rejected",
                        result_count=0,
                        target_resource_type=target_resource_type,
                        target_resource_id=target_resource_id,
                    )
                )
                scope.session.flush()
        except PlatformHttpError:
            raise
        except Exception:
            raise PlatformRedemptionRuntimeUnavailable() from None


def require_platform_redemption_http_runtime() -> PlatformRedemptionHttpRuntime:
    runtime = current_app.extensions.get(
        PLATFORM_REDEMPTION_HTTP_RUNTIME_EXTENSION
    )
    if not isinstance(runtime, PlatformRedemptionHttpRuntime):
        raise PlatformRedemptionRuntimeUnavailable()
    return runtime


def install_platform_redemption_http_runtime(
    app,
    *,
    runtime: PlatformRedemptionHttpRuntime,
) -> None:
    if PLATFORM_REDEMPTION_HTTP_RUNTIME_EXTENSION in app.extensions:
        raise RuntimeError("platform redemption runtime is already installed")
    if not isinstance(runtime, PlatformRedemptionHttpRuntime):
        raise TypeError("runtime must implement PlatformRedemptionHttpRuntime")
    app.extensions[PLATFORM_REDEMPTION_HTTP_RUNTIME_EXTENSION] = runtime


def _current_completed_run(session: Session, *, locking: bool):
    statement = (
        sa.select(DisasterRecoveryRun)
        .where(DisasterRecoveryRun.current_run_marker == "current")
        .order_by(DisasterRecoveryRun.id)
        .limit(2)
    )
    if locking:
        statement = statement.with_for_update()
    runs = tuple(session.scalars(statement))
    if len(runs) != 1 or runs[0].status != "completed":
        raise RedemptionGenerationDenied("RECOVERY_NOT_COMPLETED")
    return runs[0]


def _current_core_plan(session: Session, *, locking: bool):
    statement = (
        sa.select(PlanRevision)
        .where(PlanRevision.code == "core", PlanRevision.active.is_(True))
        .order_by(PlanRevision.revision.desc(), PlanRevision.id)
        .limit(2)
    )
    if locking:
        statement = statement.with_for_update()
    plans = tuple(session.scalars(statement))
    if len(plans) != 1:
        raise RedemptionGenerationDenied("PLAN_NOT_ACTIVE")
    return plans[0]


def _list_payload(item) -> Mapping[str, object]:
    return {
        "code_id": str(item.code_uuid),
        "batch_id": str(item.batch_uuid),
        "batch_name": item.batch_name,
        "channel": item.channel,
        "internal_note": item.internal_note,
        "masked_code": item.masked_code,
        "status": item.status,
        "row_version": item.row_version,
        "plan_revision_id": str(item.plan_revision_uuid),
        "service_duration_seconds": item.service_duration_seconds,
        "redeem_before": _iso(item.redeem_before),
        "created_at": _iso(item.created_at),
        "reserved_attempt_id": _optional_string(item.reserved_attempt_uuid),
        "reserved_attempt_status": item.reserved_attempt_status,
        "redeemed_tenant_id": _optional_string(item.redeemed_tenant_uuid),
        "redeemed_user_id": _optional_string(item.redeemed_user_uuid),
        "redeemed_at": (
            _iso(item.redeemed_at) if item.redeemed_at is not None else None
        ),
        "revocation_reason_code": item.revocation_reason_code,
        "replacement_status": item.replacement_status,
        "replacement_code_id": _optional_string(
            item.replacement_code_uuid
        ),
    }


def _initial_csv(
    issued_codes,
    *,
    batch_name: str,
    duration_days: int,
    redeem_before: datetime,
    channel: str | None,
) -> str:
    output = StringIO(newline="")
    writer = csv.writer(output, lineterminator="\n")
    writer.writerow(
        (
            "code_id",
            "redemption_code",
            "batch_name",
            "channel",
            "service_duration_days",
            "redeem_before_utc",
        )
    )
    for issued in issued_codes:
        writer.writerow(
            (
                str(issued.code_uuid),
                issued.plaintext.value,
                batch_name,
                channel or "",
                duration_days,
                _iso(redeem_before),
            )
        )
    return output.getvalue()


def _uuid(value: object) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValueError("UUID is invalid")


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("integer is invalid")
    return value


def _bounded_integer(value: object, *, maximum: int) -> int:
    selected = _integer(value)
    if selected < 1 or selected > maximum:
        raise ValueError("bounded integer is invalid")
    return selected


def _optional_status(value: object) -> str | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError("status is invalid")
    return value


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("text is invalid")
    return value


def _optional_text(value: object) -> str | None:
    if value is None:
        return None
    return _text(value)


def _datetime(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError("datetime is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError("datetime is invalid") from None
    if parsed.tzinfo is None:
        raise ValueError("datetime is invalid")
    return parsed.astimezone(timezone.utc)


def _database_now(session: Session) -> datetime:
    value = read_database_utc_value(session)
    if not isinstance(value, datetime):
        raise RuntimeError("control database clock is invalid")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _optional_string(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _safe_uuid_text(value: object) -> str | None:
    try:
        return str(_uuid(value))
    except ValueError:
        return None


__all__ = [
    "PLATFORM_REDEMPTION_HTTP_RUNTIME_EXTENSION",
    "PlatformRedemptionHttpConflict",
    "PlatformRedemptionHttpInvalid",
    "PlatformRedemptionHttpNotFound",
    "PlatformRedemptionHttpRuntime",
    "PlatformRedemptionRuntimeUnavailable",
    "SqlAlchemyPlatformRedemptionHttpRuntime",
    "install_platform_redemption_http_runtime",
    "require_platform_redemption_http_runtime",
]
