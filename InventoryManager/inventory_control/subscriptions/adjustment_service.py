"""D53 platform service-period adjustments in a caller-owned transaction.

The service deliberately owns neither transaction commit nor platform audit.  A
caller must start a clean control-database transaction, call :meth:`adjust`, add
the matching platform-audit record, and commit both together.  If any later
step fails, rolling back that outer transaction also rolls back the factor,
subscription CAS, and immutable event written here.

All fallible business and gate checks happen before factor verification.  The
factor mutation, subscription CAS, and event insert additionally live in a
SAVEPOINT, so a rejected/failed action does not consume a TOTP step or recovery
code even when the caller catches the domain error and continues its outer
transaction.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inventory_control.crypto import RootKey, RootKeyRing
from inventory_control.database import read_database_utc_value
from inventory_control.evidence import canonical_json_sha256
from inventory_control.models.foundation import Tenant
from inventory_control.models.platform_identity import (
    PlatformAdmin,
    PlatformAdminSession,
    PlatformAdminTotpCredential,
)
from inventory_control.models.subscriptions import Subscription, SubscriptionEvent
from inventory_control.platform_identity.factor_service import (
    PlatformCurrentFactorService,
    PlatformFactorRejected,
    PlatformRecoveryCodeService,
    PlatformTotpService,
    VerifiedPlatformFactor,
)

from .periods import (
    ServicePeriodAction,
    ServicePeriodAdjustment,
    calculate_service_period_adjustment,
    service_period_calculation_base,
    service_period_effective_status,
)


ADJUSTMENT_CANONICALIZATION_VERSION = 1

_ALLOWED_TENANT_STATUSES = frozenset(("active", "expired", "suspended"))
_OFFLINE_REFERENCE_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#-]{0,127}\Z")


class SubscriptionAdjustmentError(RuntimeError):
    """Base class for a stable, non-secret D53 rejection."""

    code = "SUBSCRIPTION_ADJUSTMENT_REJECTED"


class SubscriptionAdjustmentConflictError(SubscriptionAdjustmentError):
    """Expected revision or idempotency identity no longer matches."""

    code = "SUBSCRIPTION_ADJUSTMENT_CONFLICT"


class SubscriptionAdjustmentGateError(SubscriptionAdjustmentError):
    """The current recovery/deletion/suspension gate denies the action."""

    code = "SUBSCRIPTION_ADJUSTMENT_GATE_DENIED"


class SubscriptionAdjustmentAuthenticationError(SubscriptionAdjustmentError):
    """The platform session or fresh action factor is unavailable."""

    code = "SUBSCRIPTION_ADJUSTMENT_FACTOR_REJECTED"


class SubscriptionAdjustmentTransactionError(SubscriptionAdjustmentError):
    """The caller did not provide the isolated transaction boundary required."""

    code = "SUBSCRIPTION_ADJUSTMENT_TRANSACTION_INVALID"


@dataclass(frozen=True, slots=True)
class SubscriptionAdjustmentMetadata:
    """Canonical non-financial explanation shared by preview and commit."""

    reason_code: str
    note: str | None
    offline_reference: str | None

    @classmethod
    def from_values(
        cls,
        *,
        reason_code: object,
        note: object,
        offline_reference: object,
    ) -> "SubscriptionAdjustmentMetadata":
        return cls(
            reason_code=_safe_reason_code(reason_code),
            note=_safe_note(note),
            offline_reference=_safe_offline_reference(offline_reference),
        )


@dataclass(frozen=True, slots=True)
class SubscriptionAdjustmentGate:
    """Locking/current-read facts supplied by the lifecycle repository.

    ``suspension_state`` is ``None`` when no current suspension aggregate
    applies.  A suspended tenant is eligible only when it is exactly ``active``
    and its barrier is complete.  The service accepts no optimistic/default
    gate: every boolean must literally be ``True``.
    """

    recovery_run_completed: bool
    tenant_hold_released: bool
    no_unresolved_deletion: bool
    suspension_state: str | None = None
    suspension_barrier_complete: bool = False


class AdjustmentGateCurrentRead(Protocol):
    """Read lifecycle facts after the target tenant row has been locked."""

    def __call__(
        self,
        session: Session,
        tenant: Tenant,
        database_now: datetime,
    ) -> SubscriptionAdjustmentGate:
        ...


@dataclass(frozen=True, slots=True)
class SubscriptionAdjustmentResult:
    tenant_uuid: str
    subscription_uuid: str
    event_uuid: str
    action_uuid: str
    action: ServicePeriodAction
    signed_delta_days: int | None
    calculation_base_at: datetime
    database_effective_at: datetime
    before_expires_at: datetime
    after_expires_at: datetime
    before_status: str
    after_status: str
    expected_subscription_row_version: int
    resulting_subscription_row_version: int
    reason_code: str
    note: str | None
    offline_reference: str | None
    created: bool


DatabaseClock = Callable[[Session], datetime]


class PlatformSubscriptionAdjustmentService:
    """Apply one D53 mutation without committing the caller's transaction.

    The caller must:

    * enter a clean, explicit control-database transaction;
    * provide a read-only ``gate_current_read`` implementation that follows the
      tenant-first lifecycle lock order;
    * append the platform audit after this method returns; and
    * commit only when both records are ready, otherwise roll back the outer
      transaction.

    There is intentionally no target-expiry argument.  ``database_clock`` is a
    repository dependency (the default executes ``CURRENT_TIMESTAMP``), not a
    client-controlled timestamp.
    """

    def __init__(
        self,
        *,
        gate_current_read: AdjustmentGateCurrentRead,
        database_clock: DatabaseClock | None = None,
        totp_service: PlatformTotpService | None = None,
        recovery_code_service: PlatformRecoveryCodeService | None = None,
        allowed_totp_drift_steps: int = 1,
    ) -> None:
        if not callable(gate_current_read):
            raise TypeError("gate_current_read must be callable")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._gate_current_read = gate_current_read
        self._database_clock = database_clock or _read_database_utc_now
        self._totp_service = totp_service or PlatformTotpService()
        self._recovery_code_service = (
            recovery_code_service or PlatformRecoveryCodeService()
        )
        if (
            isinstance(allowed_totp_drift_steps, bool)
            or not isinstance(allowed_totp_drift_steps, int)
            or not 0 <= allowed_totp_drift_steps <= 1
        ):
            raise ValueError("allowed_totp_drift_steps is invalid")
        self._current_factor_service = PlatformCurrentFactorService(
            totp_service=self._totp_service,
            recovery_code_service=self._recovery_code_service,
        )
        self._allowed_totp_drift_steps = allowed_totp_drift_steps

    def adjust(
        self,
        session: Session,
        *,
        tenant_uuid: str | UUID,
        platform_actor_uuid: str | UUID,
        platform_session_uuid: str | UUID,
        action_uuid: str | UUID,
        idempotency_key: str,
        expected_subscription_row_version: int,
        adjustment: ServicePeriodAdjustment,
        reason_code: str,
        note: str | None,
        offline_reference: str | None,
        factor_method: str,
        presented_factor: object,
        root_key: RootKey | None = None,
        root_key_ring: RootKeyRing | None = None,
    ) -> SubscriptionAdjustmentResult:
        """Apply one adjustment and flush it, leaving commit to ``session`` owner.

        Successful idempotent retries are resolved from the immutable event
        before database time, gates, platform session, or factor are evaluated.
        The retry must use the original action UUID, key, actor/session, expected
        revision, operation, reason, note, and offline reference.
        """

        if not isinstance(session, Session) or not session.in_transaction():
            raise SubscriptionAdjustmentTransactionError(
                "an explicit caller-owned transaction is required"
            )
        _require_clean_unit_of_work(session)

        tenant_id = str(_uuid(tenant_uuid, "tenant_uuid"))
        actor_id = str(_uuid(platform_actor_uuid, "platform_actor_uuid"))
        platform_session_id = str(_uuid(platform_session_uuid, "platform_session_uuid"))
        action_id = str(_uuid(action_uuid, "action_uuid"))
        key = _bounded_required(idempotency_key, "idempotency_key", 128)
        expected_revision = _positive_integer(
            expected_subscription_row_version,
            "expected_subscription_row_version",
        )
        if not isinstance(adjustment, ServicePeriodAdjustment):
            raise TypeError("adjustment must be a ServicePeriodAdjustment")
        metadata = SubscriptionAdjustmentMetadata.from_values(
            reason_code=reason_code,
            note=note,
            offline_reference=offline_reference,
        )
        reason = metadata.reason_code
        safe_note = metadata.note
        safe_offline_reference = metadata.offline_reference
        method = _factor_method(
            factor_method,
            root_key=root_key,
            root_key_ring=root_key_ring,
        )
        signed_delta_days = _signed_delta_days(adjustment)
        request_digest = subscription_adjustment_request_digest(
            tenant_uuid=tenant_id,
            platform_actor_uuid=actor_id,
            platform_session_uuid=platform_session_id,
            action_uuid=action_id,
            idempotency_key=key,
            expected_subscription_row_version=expected_revision,
            adjustment=adjustment,
            reason_code=reason,
            note=safe_note,
            offline_reference=safe_offline_reference,
        )

        # D53 shares the tenant-first prefix with every tenant-scoped control
        # mutation.  Even an idempotency replay first locks the requested tenant.
        tenant = session.scalar(
            sa.select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        if tenant is None:
            raise SubscriptionAdjustmentGateError("tenant is unavailable")

        existing = _find_existing_event(
            session,
            action_uuid=action_id,
            idempotency_key=key,
        )
        if existing is not None:
            return _existing_result(
                event=existing,
                tenant_uuid=tenant_id,
                actor_uuid=actor_id,
                platform_session_uuid=platform_session_id,
                action_uuid=action_id,
                idempotency_key=key,
                expected_subscription_row_version=expected_revision,
                adjustment=adjustment,
                reason_code=reason,
                note=safe_note,
                offline_reference=safe_offline_reference,
                request_digest=request_digest,
            )

        database_now = _as_database_utc(self._database_clock(session))
        gate = self._gate_current_read(session, tenant, database_now)
        validate_subscription_adjustment_gate(tenant, gate, adjustment)

        subscription = session.scalar(
            sa.select(Subscription)
            .where(Subscription.tenant_id == tenant_id)
            .with_for_update()
        )
        if subscription is None:
            raise SubscriptionAdjustmentConflictError(
                "tenant subscription is unavailable"
            )
        if subscription.row_version != expected_revision:
            raise SubscriptionAdjustmentConflictError("subscription revision changed")

        before_expires_at = _as_database_utc(subscription.expires_at)
        calculation = calculate_service_period_adjustment(
            adjustment=adjustment,
            current_expires_at=before_expires_at,
            database_now=database_now,
        )
        before_status = service_period_effective_status(before_expires_at, database_now)
        after_status = service_period_effective_status(
            calculation.new_expires_at,
            database_now,
        )
        calculation_base_at = service_period_calculation_base(
            adjustment=adjustment,
            current_expires_at=before_expires_at,
            database_now=database_now,
        )

        admin, platform_session = _lock_and_validate_platform_session(
            session,
            actor_uuid=actor_id,
            platform_session_uuid=platform_session_id,
            database_now=database_now,
        )
        _lock_current_totp_credential(session, admin)
        _require_clean_unit_of_work(session)

        event: SubscriptionEvent | None = None
        try:
            # SQLAlchemy flushes before opening a nested transaction.  The clean
            # unit-of-work checks above are therefore part of the API contract:
            # no caller mutation can accidentally escape this SAVEPOINT.
            with session.begin_nested():
                proof = self._verify_fresh_factor(
                    session,
                    actor_uuid=admin.id,
                    method=method,
                    presented_factor=presented_factor,
                    root_key=root_key,
                    root_key_ring=root_key_ring,
                    database_now=database_now,
                )
                _claim_factor_proof(
                    proof,
                    actor_uuid=admin.id,
                    method=method,
                    database_now=database_now,
                )

                changed = session.execute(
                    sa.update(Subscription)
                    .where(
                        Subscription.id == subscription.id,
                        Subscription.tenant_id == tenant_id,
                        Subscription.row_version == expected_revision,
                    )
                    .values(
                        expires_at=calculation.new_expires_at,
                        status=after_status,
                        row_version=expected_revision + 1,
                        updated_at=database_now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    raise SubscriptionAdjustmentConflictError(
                        "subscription revision changed"
                    )

                event = SubscriptionEvent(
                    tenant_id=tenant_id,
                    subscription_id=subscription.id,
                    event_type=(
                        "expired_now"
                        if adjustment.action is ServicePeriodAction.EXPIRE_NOW
                        else "days_adjusted"
                    ),
                    source_type="platform_adjustment",
                    source_uuid=action_id,
                    consumed_code_uuid=None,
                    before_plan_revision_uuid=subscription.plan_revision_uuid,
                    after_plan_revision_uuid=subscription.plan_revision_uuid,
                    before_entitlements_digest=subscription.entitlements_digest,
                    after_entitlements_digest=subscription.entitlements_digest,
                    exact_duration_seconds=None,
                    signed_delta_days=signed_delta_days,
                    calculation_base_at=calculation_base_at,
                    database_effective_at=database_now,
                    before_expires_at=before_expires_at,
                    after_expires_at=calculation.new_expires_at,
                    before_status=before_status,
                    after_status=after_status,
                    expected_subscription_row_version=expected_revision,
                    idempotency_key=key,
                    request_digest=request_digest,
                    canonicalization_version=ADJUSTMENT_CANONICALIZATION_VERSION,
                    platform_actor_id=actor_id,
                    platform_session_id=platform_session.id,
                    factor_method=proof.method,
                    factor_accepted_at=_as_database_utc(proof.verified_at),
                    reason_code=reason,
                    note=safe_note,
                    offline_reference=safe_offline_reference,
                )
                session.add(event)
                session.flush()
        except PlatformFactorRejected:
            raise SubscriptionAdjustmentAuthenticationError(
                "fresh platform factor was rejected"
            ) from None
        except RuntimeError as exc:
            # A one-use proof can only fail its claim when an injected factor
            # service returned a stale/foreign proof.  Do not leak proof details.
            if str(exc) == "Platform factor proof is no longer available":
                raise SubscriptionAdjustmentAuthenticationError(
                    "fresh platform factor was rejected"
                ) from None
            raise
        except IntegrityError:
            # The SAVEPOINT has already restored the factor and subscription.
            concurrent = _find_existing_event(
                session,
                action_uuid=action_id,
                idempotency_key=key,
            )
            if concurrent is not None:
                return _existing_result(
                    event=concurrent,
                    tenant_uuid=tenant_id,
                    actor_uuid=actor_id,
                    platform_session_uuid=platform_session_id,
                    action_uuid=action_id,
                    idempotency_key=key,
                    expected_subscription_row_version=expected_revision,
                    adjustment=adjustment,
                    reason_code=reason,
                    note=safe_note,
                    offline_reference=safe_offline_reference,
                    request_digest=request_digest,
                )
            raise SubscriptionAdjustmentConflictError(
                "subscription adjustment conflicted"
            ) from None

        if event is None or event.id is None:  # pragma: no cover - defensive
            raise RuntimeError("subscription adjustment event was not persisted")
        session.expire(subscription)
        return SubscriptionAdjustmentResult(
            tenant_uuid=tenant_id,
            subscription_uuid=subscription.id,
            event_uuid=event.id,
            action_uuid=action_id,
            action=adjustment.action,
            signed_delta_days=signed_delta_days,
            calculation_base_at=calculation_base_at,
            database_effective_at=database_now,
            before_expires_at=before_expires_at,
            after_expires_at=calculation.new_expires_at,
            before_status=before_status,
            after_status=after_status,
            expected_subscription_row_version=expected_revision,
            resulting_subscription_row_version=expected_revision + 1,
            reason_code=reason,
            note=safe_note,
            offline_reference=safe_offline_reference,
            created=True,
        )

    def _verify_fresh_factor(
        self,
        session: Session,
        *,
        actor_uuid: str,
        method: str,
        presented_factor: object,
        root_key: RootKey | None,
        root_key_ring: RootKeyRing | None,
        database_now: datetime,
    ) -> VerifiedPlatformFactor:
        if root_key_ring is not None:
            return self._current_factor_service.verify(
                session,
                platform_admin_id=actor_uuid,
                factor_method=method,
                factor_value=presented_factor,
                key_ring=root_key_ring,
                now=database_now,
                allowed_totp_drift_steps=self._allowed_totp_drift_steps,
            )
        if method == "totp":
            # _factor_method has already proved this branch has a RootKey.
            return self._totp_service.verify_current(
                session,
                platform_admin_id=actor_uuid,
                presented_code=presented_factor,
                root_key=root_key,
                now=database_now,
            )
        return self._recovery_code_service.consume(
            session,
            platform_admin_id=actor_uuid,
            presented_code=presented_factor,
            now=database_now,
        )


def _read_database_utc_now(session: Session) -> datetime:
    return _as_database_utc(read_database_utc_value(session))


def _as_database_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise SubscriptionAdjustmentTransactionError(
            "database clock did not return a datetime"
        )
    if value.tzinfo is None:
        # MySQL and MariaDB control databases are required to run in UTC.
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _require_clean_unit_of_work(session: Session) -> None:
    dirty = any(
        session.is_modified(instance, include_collections=True)
        for instance in session.dirty
    )
    if session.new or session.deleted or dirty:
        raise SubscriptionAdjustmentTransactionError(
            "adjustment requires a clean caller unit of work"
        )


def _uuid(value: str | UUID, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValueError(f"{field_name} is invalid")


def _bounded_required(value: object, field_name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or not value
        or len(value) > maximum
        or _contains_disallowed_control(value)
    ):
        raise ValueError(f"{field_name} is invalid")
    return value


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _safe_reason_code(value: object) -> str:
    return _bounded_required(value, "reason_code", 64)


def _safe_note(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 500:
        raise ValueError("note is invalid")
    return value


def _safe_offline_reference(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or _OFFLINE_REFERENCE_PATTERN.fullmatch(value) is None
    ):
        raise ValueError("offline_reference is invalid")
    return value


def _contains_disallowed_control(value: str) -> bool:
    return any(unicodedata.category(character) == "Cc" for character in value)


def _factor_method(
    value: object,
    *,
    root_key: RootKey | None,
    root_key_ring: RootKeyRing | None,
) -> str:
    if value not in {"totp", "recovery_code"}:
        raise ValueError("factor_method is invalid")
    if root_key is not None and root_key_ring is not None:
        raise ValueError("only one root key source may be supplied")
    if (
        value == "totp"
        and not isinstance(root_key, RootKey)
        and not isinstance(root_key_ring, RootKeyRing)
    ):
        raise ValueError("a root key source is required for TOTP")
    return value


def _signed_delta_days(adjustment: ServicePeriodAdjustment) -> int | None:
    if adjustment.action is ServicePeriodAction.ADD_DAYS:
        return adjustment.add_days
    if adjustment.action is ServicePeriodAction.SUBTRACT_DAYS:
        return -adjustment.subtract_days
    return None


def subscription_adjustment_request_digest(
    *,
    tenant_uuid: str,
    platform_actor_uuid: str,
    platform_session_uuid: str,
    action_uuid: str,
    idempotency_key: str,
    expected_subscription_row_version: int,
    adjustment: ServicePeriodAdjustment,
    reason_code: str,
    note: str | None,
    offline_reference: str | None,
) -> bytes:
    """Return the canonical D53 request identity used by proof and ledger."""

    payload = {
        "action_uuid": action_uuid,
        "canonicalization_version": ADJUSTMENT_CANONICALIZATION_VERSION,
        "days": (
            adjustment.add_days
            if adjustment.action is ServicePeriodAction.ADD_DAYS
            else adjustment.subtract_days
        ),
        "expected_subscription_row_version": expected_subscription_row_version,
        "idempotency_key": idempotency_key,
        "note": note,
        "offline_reference": offline_reference,
        "operation": adjustment.action.value,
        "platform_actor_uuid": platform_actor_uuid,
        "platform_session_uuid": platform_session_uuid,
        "reason_code": reason_code,
        "tenant_uuid": tenant_uuid,
    }
    return canonical_json_sha256(
        payload,
        ensure_ascii=False,
        allow_nan=True,
    )


__all__ = [
    "ADJUSTMENT_CANONICALIZATION_VERSION",
    "PlatformSubscriptionAdjustmentService",
    "SubscriptionAdjustmentAuthenticationError",
    "SubscriptionAdjustmentConflictError",
    "SubscriptionAdjustmentError",
    "SubscriptionAdjustmentGate",
    "SubscriptionAdjustmentGateError",
    "SubscriptionAdjustmentMetadata",
    "SubscriptionAdjustmentResult",
    "SubscriptionAdjustmentTransactionError",
    "subscription_adjustment_request_digest",
    "validate_subscription_adjustment_gate",
    "validate_subscription_adjustment_gate_status",
]


def _find_existing_event(
    session: Session,
    *,
    action_uuid: str,
    idempotency_key: str,
) -> SubscriptionEvent | None:
    matches = list(
        session.scalars(
            sa.select(SubscriptionEvent).where(
                sa.or_(
                    SubscriptionEvent.source_uuid == action_uuid,
                    SubscriptionEvent.idempotency_key == idempotency_key,
                )
            )
        )
    )
    if not matches:
        return None
    if len(matches) != 1:
        raise SubscriptionAdjustmentConflictError(
            "adjustment idempotency identities disagree"
        )
    return matches[0]


def _existing_result(
    *,
    event: SubscriptionEvent,
    tenant_uuid: str,
    actor_uuid: str,
    platform_session_uuid: str,
    action_uuid: str,
    idempotency_key: str,
    expected_subscription_row_version: int,
    adjustment: ServicePeriodAdjustment,
    reason_code: str,
    note: str | None,
    offline_reference: str | None,
    request_digest: bytes,
) -> SubscriptionAdjustmentResult:
    expected_event_type = (
        "expired_now"
        if adjustment.action is ServicePeriodAction.EXPIRE_NOW
        else "days_adjusted"
    )
    expected_delta = _signed_delta_days(adjustment)
    if (
        event.source_type != "platform_adjustment"
        or event.event_type != expected_event_type
        or event.tenant_id != tenant_uuid
        or event.source_uuid != action_uuid
        or event.idempotency_key != idempotency_key
        or bytes(event.request_digest) != request_digest
        or event.canonicalization_version != ADJUSTMENT_CANONICALIZATION_VERSION
        or event.platform_actor_id != actor_uuid
        or event.platform_session_id != platform_session_uuid
        or event.expected_subscription_row_version != expected_subscription_row_version
        or event.signed_delta_days != expected_delta
        or event.reason_code != reason_code
        or event.note != note
        or event.offline_reference != offline_reference
        or event.before_expires_at is None
        or event.before_status is None
        or event.factor_method not in {"totp", "recovery_code"}
        or event.factor_accepted_at is None
    ):
        raise SubscriptionAdjustmentConflictError("adjustment idempotency conflict")
    return SubscriptionAdjustmentResult(
        tenant_uuid=tenant_uuid,
        subscription_uuid=event.subscription_id,
        event_uuid=event.id,
        action_uuid=action_uuid,
        action=adjustment.action,
        signed_delta_days=expected_delta,
        calculation_base_at=_as_database_utc(event.calculation_base_at),
        database_effective_at=_as_database_utc(event.database_effective_at),
        before_expires_at=_as_database_utc(event.before_expires_at),
        after_expires_at=_as_database_utc(event.after_expires_at),
        before_status=event.before_status,
        after_status=event.after_status,
        expected_subscription_row_version=expected_subscription_row_version,
        resulting_subscription_row_version=expected_subscription_row_version + 1,
        reason_code=event.reason_code,
        note=event.note,
        offline_reference=event.offline_reference,
        created=False,
    )


def validate_subscription_adjustment_gate(
    tenant: Tenant,
    gate: object,
    adjustment: ServicePeriodAdjustment,
) -> None:
    if not isinstance(tenant, Tenant):
        raise TypeError("tenant must be a Tenant")
    validate_subscription_adjustment_gate_status(
        tenant_status=tenant.status,
        gate=gate,
        adjustment=adjustment,
    )


def validate_subscription_adjustment_gate_status(
    *,
    tenant_status: object,
    gate: object,
    adjustment: ServicePeriodAdjustment,
) -> None:
    """Apply the same eligibility matrix to preview and final current reads."""

    if not isinstance(gate, SubscriptionAdjustmentGate):
        raise SubscriptionAdjustmentGateError(
            "lifecycle gate did not return complete facts"
        )
    if (
        gate.recovery_run_completed is not True
        or gate.tenant_hold_released is not True
        or gate.no_unresolved_deletion is not True
    ):
        raise SubscriptionAdjustmentGateError("lifecycle gate denies adjustment")
    if tenant_status not in _ALLOWED_TENANT_STATUSES:
        raise SubscriptionAdjustmentGateError("tenant state does not permit adjustment")
    if tenant_status == "suspended":
        if (
            gate.suspension_state != "active"
            or gate.suspension_barrier_complete is not True
        ):
            raise SubscriptionAdjustmentGateError(
                "tenant suspension is not fully established"
            )
    elif (
        gate.suspension_state is not None
        or gate.suspension_barrier_complete is not False
    ):
        raise SubscriptionAdjustmentGateError(
            "lifecycle gate is inconsistent with tenant state"
        )
    if (
        tenant_status == "expired"
        and adjustment.action is not ServicePeriodAction.ADD_DAYS
    ):
        raise SubscriptionAdjustmentGateError(
            "expired tenants can only receive added days"
        )


def _lock_and_validate_platform_session(
    session: Session,
    *,
    actor_uuid: str,
    platform_session_uuid: str,
    database_now: datetime,
) -> tuple[PlatformAdmin, PlatformAdminSession]:
    admin = session.scalar(
        sa.select(PlatformAdmin).where(PlatformAdmin.id == actor_uuid).with_for_update()
    )
    platform_session = session.scalar(
        sa.select(PlatformAdminSession)
        .where(PlatformAdminSession.id == platform_session_uuid)
        .with_for_update()
    )
    if (
        admin is None
        or platform_session is None
        or admin.status != "active"
        or admin.password_hash_encoded is None
        or admin.password_hash_algorithm is None
        or admin.password_hash_version is None
        or platform_session.platform_admin_id != admin.id
        or platform_session.auth_version_at_issue != admin.auth_version
        or platform_session.setup_version_at_issue != admin.setup_version
        or platform_session.revoked_at is not None
        or database_now >= _as_database_utc(platform_session.idle_expires_at)
        or database_now >= _as_database_utc(platform_session.absolute_expires_at)
    ):
        raise SubscriptionAdjustmentAuthenticationError(
            "platform session is unavailable"
        )
    return admin, platform_session


def _lock_current_totp_credential(
    session: Session,
    admin: PlatformAdmin,
) -> PlatformAdminTotpCredential:
    rows = list(
        session.scalars(
            sa.select(PlatformAdminTotpCredential)
            .where(
                PlatformAdminTotpCredential.platform_admin_id == admin.id,
                PlatformAdminTotpCredential.generation == admin.totp_generation,
                PlatformAdminTotpCredential.status == "confirmed",
            )
            .with_for_update()
        )
    )
    if len(rows) != 1:
        raise SubscriptionAdjustmentAuthenticationError(
            "platform authentication factors are unavailable"
        )
    return rows[0]


def _claim_factor_proof(
    proof: object,
    *,
    actor_uuid: str,
    method: str,
    database_now: datetime,
) -> None:
    if (
        not isinstance(proof, VerifiedPlatformFactor)
        or proof.platform_admin_id != actor_uuid
        or proof.method != method
        or _as_database_utc(proof.verified_at) != database_now
    ):
        raise PlatformFactorRejected()
    proof._claim()
