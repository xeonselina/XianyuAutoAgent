"""D03/D06 redemption-code renewal in one caller-owned transaction.

The service consumes no middleware decision.  It locks the tenant first, asks
the lifecycle repository for current recovery/hold/deletion/suspension facts,
then current-reads the Admin membership, redemption code, and subscription.
The caller owns commit/rollback and must enter with a clean unit of work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inventory_control.database import read_database_utc_value
from inventory_control.evidence import canonical_json_sha256
from inventory_control.models.foundation import Tenant
from inventory_control.models.identity import TenantMembership
from inventory_control.models.redemption import RedemptionCode
from inventory_control.models.subscriptions import Subscription, SubscriptionEvent

from .entitlements import InvalidEntitlementSnapshotError, parse_core_entitlements
from .periods import calculate_renewal


RENEWAL_CANONICALIZATION_VERSION = 1


class SubscriptionRenewalError(RuntimeError):
    """Base class for stable, non-enumerating renewal failures."""

    code = "SUBSCRIPTION_RENEWAL_REJECTED"


class SubscriptionRenewalConflictError(SubscriptionRenewalError):
    code = "SUBSCRIPTION_RENEWAL_CONFLICT"


class SubscriptionRenewalGateError(SubscriptionRenewalError):
    code = "SUBSCRIPTION_RENEWAL_GATE_DENIED"


class SubscriptionRenewalAuthorizationError(SubscriptionRenewalError):
    code = "SUBSCRIPTION_RENEWAL_NOT_AUTHORIZED"


class SubscriptionRenewalCodeError(SubscriptionRenewalError):
    code = "CODE_NOT_REDEEMABLE"


class SubscriptionRenewalTransactionError(SubscriptionRenewalError):
    code = "SUBSCRIPTION_RENEWAL_TRANSACTION_INVALID"


@dataclass(frozen=True, slots=True)
class SubscriptionRenewalGate:
    """Complete current-read lifecycle facts, obtained after locking tenant."""

    recovery_run_completed: bool
    tenant_hold_released: bool
    no_unresolved_deletion: bool
    no_unresolved_suspension: bool


class RenewalGateCurrentRead(Protocol):
    def __call__(
        self,
        session: Session,
        tenant: Tenant,
        current_recovery_run_uuid: UUID,
        database_now: datetime,
    ) -> SubscriptionRenewalGate:
        ...


DatabaseClock = Callable[[Session], datetime]


@dataclass(frozen=True, slots=True)
class SubscriptionRenewalResult:
    tenant_uuid: str
    membership_uuid: str
    subscription_uuid: str
    code_uuid: str
    event_uuid: str
    calculation_base_at: datetime
    database_effective_at: datetime
    before_expires_at: datetime
    after_expires_at: datetime
    before_status: str
    after_status: str
    expected_tenant_access_version: int
    expected_subscription_row_version: int
    resulting_subscription_row_version: int
    created: bool


class SubscriptionRenewalService:
    """Consume one current-run code and renew an active/expired tenant."""

    def __init__(
        self,
        *,
        gate_current_read: RenewalGateCurrentRead,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not callable(gate_current_read):
            raise TypeError("gate_current_read must be callable")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._gate_current_read = gate_current_read
        self._database_clock = database_clock or _read_database_utc_now

    def renew(
        self,
        session: Session,
        *,
        tenant_uuid: str | UUID,
        membership_uuid: str | UUID,
        code_lookup_hash: bytes,
        idempotency_key: str,
        current_recovery_run_uuid: str | UUID,
        expected_tenant_access_version: int,
        expected_subscription_row_version: int,
    ) -> SubscriptionRenewalResult:
        if not isinstance(session, Session) or not session.in_transaction():
            raise SubscriptionRenewalTransactionError(
                "an explicit caller-owned transaction is required"
            )
        _require_clean_unit_of_work(session)

        tenant_id = str(_uuid(tenant_uuid, "tenant_uuid"))
        membership_id = str(_uuid(membership_uuid, "membership_uuid"))
        run_uuid = _uuid(current_recovery_run_uuid, "current_recovery_run_uuid")
        lookup_hash = _lookup_hash(code_lookup_hash)
        key = _idempotency_key(idempotency_key)
        tenant_access_version = _positive_integer(
            expected_tenant_access_version,
            "expected_tenant_access_version",
        )
        subscription_revision = _positive_integer(
            expected_subscription_row_version,
            "expected_subscription_row_version",
        )
        request_digest = _request_digest(
            tenant_uuid=tenant_id,
            membership_uuid=membership_id,
            code_lookup_hash=lookup_hash,
            idempotency_key=key,
            current_recovery_run_uuid=str(run_uuid),
            expected_tenant_access_version=tenant_access_version,
            expected_subscription_row_version=subscription_revision,
        )

        # Shared tenant-scoped control mutation prefix starts with this row.
        tenant = session.scalar(
            sa.select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        if tenant is None:
            raise SubscriptionRenewalGateError("tenant is unavailable")

        # A successful retry may return from the immutable event without
        # re-opening lifecycle authority or re-locking the consumed code.  Its
        # request digest authenticates the originally submitted lookup hash.
        existing = _find_event_by_idempotency_key(session, idempotency_key=key)
        if existing is not None:
            return _existing_result(
                event=existing,
                tenant_uuid=tenant_id,
                membership_uuid=membership_id,
                code_uuid=existing.source_uuid,
                idempotency_key=key,
                expected_tenant_access_version=tenant_access_version,
                expected_subscription_row_version=subscription_revision,
                request_digest=request_digest,
            )

        database_now = _as_database_utc(self._database_clock(session))
        gate = self._gate_current_read(session, tenant, run_uuid, database_now)
        _require_gate(
            tenant,
            gate,
            expected_tenant_access_version=tenant_access_version,
        )

        # Code and subscription follow the shared lifecycle lock prefix.  This
        # ordering prevents renewal from deadlocking a suspension/deletion
        # transaction that already owns the current-run or hold rows.
        code = session.scalar(
            sa.select(RedemptionCode)
            .where(RedemptionCode.lookup_hash == lookup_hash)
            .with_for_update()
        )
        if code is None:
            raise SubscriptionRenewalCodeError("code is not redeemable")
        existing = _find_existing_event(
            session,
            code_uuid=code.id,
            idempotency_key=key,
        )
        if existing is not None:
            return _existing_result(
                event=existing,
                tenant_uuid=tenant_id,
                membership_uuid=membership_id,
                code_uuid=code.id,
                idempotency_key=key,
                expected_tenant_access_version=tenant_access_version,
                expected_subscription_row_version=subscription_revision,
                request_digest=request_digest,
            )

        _require_redeemable_code(
            code,
            current_recovery_run_uuid=run_uuid,
            database_now=database_now,
        )
        snapshot = _validated_code_snapshot(code)

        membership = session.scalar(
            sa.select(TenantMembership)
            .where(TenantMembership.id == membership_id)
            .with_for_update()
        )
        if (
            membership is None
            or membership.tenant_id != tenant_id
            or membership.status != "active"
            or membership.role_key != "admin"
        ):
            raise SubscriptionRenewalAuthorizationError(
                "active tenant Admin membership is required"
            )

        subscription = session.scalar(
            sa.select(Subscription)
            .where(Subscription.tenant_id == tenant_id)
            .with_for_update()
        )
        if subscription is None or subscription.row_version != subscription_revision:
            raise SubscriptionRenewalConflictError("subscription revision changed")

        before_expires_at = _as_database_utc(subscription.expires_at)
        before_status = _effective_status(before_expires_at, database_now)
        try:
            service_duration = timedelta(seconds=code.service_duration_seconds)
        except OverflowError:
            raise SubscriptionRenewalCodeError("code terms are invalid") from None
        calculation = calculate_renewal(
            current_expires_at=before_expires_at,
            database_now=database_now,
            service_duration=service_duration,
        )

        code_revision = code.row_version
        tenant_row_version = tenant.row_version
        event: SubscriptionEvent | None = None
        try:
            with session.begin_nested():
                code_changed = session.execute(
                    sa.update(RedemptionCode)
                    .where(
                        RedemptionCode.id == code.id,
                        RedemptionCode.status == "active",
                        RedemptionCode.row_version == code_revision,
                        RedemptionCode.created_under_recovery_run_uuid == str(run_uuid),
                    )
                    .values(
                        status="redeemed",
                        redeemed_tenant_uuid=tenant_id,
                        redeemed_at=database_now,
                        row_version=code_revision + 1,
                        updated_at=database_now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if code_changed.rowcount != 1:
                    raise SubscriptionRenewalConflictError("code redemption conflicted")

                subscription_changed = session.execute(
                    sa.update(Subscription)
                    .where(
                        Subscription.id == subscription.id,
                        Subscription.tenant_id == tenant_id,
                        Subscription.row_version == subscription_revision,
                    )
                    .values(
                        plan_revision_uuid=code.plan_revision_uuid,
                        entitlements_schema_version=snapshot.schema_version,
                        entitlements_json=code.entitlements_json,
                        entitlements_digest=snapshot.digest_sha256,
                        status="active",
                        expires_at=calculation.new_expires_at,
                        row_version=subscription_revision + 1,
                        updated_at=database_now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if subscription_changed.rowcount != 1:
                    raise SubscriptionRenewalConflictError(
                        "subscription revision changed"
                    )

                if tenant.status == "expired":
                    tenant_changed = session.execute(
                        sa.update(Tenant)
                        .where(
                            Tenant.id == tenant_id,
                            Tenant.status == "expired",
                            Tenant.row_version == tenant_row_version,
                            Tenant.access_version == tenant_access_version,
                        )
                        .values(
                            status="active",
                            row_version=tenant_row_version + 1,
                            updated_at=database_now,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if tenant_changed.rowcount != 1:
                        raise SubscriptionRenewalConflictError("tenant state changed")

                event = SubscriptionEvent(
                    tenant_id=tenant_id,
                    subscription_id=subscription.id,
                    event_type="renewed",
                    source_type="redemption",
                    source_uuid=code.id,
                    consumed_code_uuid=code.id,
                    before_plan_revision_uuid=subscription.plan_revision_uuid,
                    after_plan_revision_uuid=code.plan_revision_uuid,
                    before_entitlements_digest=subscription.entitlements_digest,
                    after_entitlements_digest=snapshot.digest_sha256,
                    exact_duration_seconds=code.service_duration_seconds,
                    signed_delta_days=None,
                    calculation_base_at=calculation.calculation_base,
                    database_effective_at=database_now,
                    before_expires_at=before_expires_at,
                    after_expires_at=calculation.new_expires_at,
                    before_status=before_status,
                    after_status="active",
                    expected_subscription_row_version=subscription_revision,
                    idempotency_key=key,
                    request_digest=request_digest,
                    canonicalization_version=RENEWAL_CANONICALIZATION_VERSION,
                    platform_actor_id=None,
                    platform_session_id=None,
                    factor_method=None,
                    factor_accepted_at=None,
                    reason_code="redemption_code_renewal",
                    note=None,
                    offline_reference=None,
                )
                session.add(event)
                session.flush()
        except IntegrityError:
            concurrent = _find_existing_event(
                session,
                code_uuid=code.id,
                idempotency_key=key,
            )
            if concurrent is not None:
                return _existing_result(
                    event=concurrent,
                    tenant_uuid=tenant_id,
                    membership_uuid=membership_id,
                    code_uuid=code.id,
                    idempotency_key=key,
                    expected_tenant_access_version=tenant_access_version,
                    expected_subscription_row_version=subscription_revision,
                    request_digest=request_digest,
                )
            raise SubscriptionRenewalConflictError(
                "subscription renewal conflicted"
            ) from None

        if event is None or event.id is None:  # pragma: no cover - defensive
            raise RuntimeError("renewal event was not persisted")
        session.expire(tenant)
        session.expire(code)
        session.expire(subscription)
        return _result_from_event(
            event=event,
            membership_uuid=membership_id,
            expected_tenant_access_version=tenant_access_version,
            created=True,
        )


def _read_database_utc_now(session: Session) -> datetime:
    return _as_database_utc(read_database_utc_value(session))


def _as_database_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise SubscriptionRenewalTransactionError(
            "database clock did not return a datetime"
        )
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValueError(f"{field_name} is invalid")


def _lookup_hash(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise SubscriptionRenewalCodeError("code is not redeemable")
    return value


def _idempotency_key(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 128
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("idempotency_key is invalid")
    return value


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _request_digest(**values: object) -> bytes:
    encoded = {
        key: value.hex() if isinstance(value, bytes) else value
        for key, value in values.items()
    }
    return canonical_json_sha256(encoded)


def _require_clean_unit_of_work(session: Session) -> None:
    dirty = any(
        session.is_modified(instance, include_collections=True)
        for instance in session.dirty
    )
    if session.new or session.deleted or dirty:
        raise SubscriptionRenewalTransactionError(
            "renewal requires a clean caller unit of work"
        )


def _require_gate(
    tenant: Tenant,
    gate: object,
    *,
    expected_tenant_access_version: int,
) -> None:
    if not isinstance(gate, SubscriptionRenewalGate):
        raise SubscriptionRenewalGateError(
            "lifecycle gate did not return complete facts"
        )
    if (
        gate.recovery_run_completed is not True
        or gate.tenant_hold_released is not True
        or gate.no_unresolved_deletion is not True
        or gate.no_unresolved_suspension is not True
        or tenant.status not in {"active", "expired"}
        or tenant.access_version != expected_tenant_access_version
    ):
        raise SubscriptionRenewalGateError("lifecycle gate denies renewal")


def _require_redeemable_code(
    code: RedemptionCode,
    *,
    current_recovery_run_uuid: UUID,
    database_now: datetime,
) -> None:
    if (
        code.status != "active"
        or code.created_under_recovery_run_uuid != str(current_recovery_run_uuid)
        or _as_database_utc(code.redeem_before) <= database_now
        or code.reserved_registration_attempt_uuid is not None
        or code.reserved_user_uuid is not None
        or code.service_duration_seconds < 1
    ):
        raise SubscriptionRenewalCodeError("code is not redeemable")


def _validated_code_snapshot(code: RedemptionCode):
    try:
        snapshot = parse_core_entitlements(
            schema_version=code.entitlements_schema_version,
            entitlements=code.entitlements_json,
        )
    except InvalidEntitlementSnapshotError:
        raise SubscriptionRenewalCodeError("code terms are invalid") from None
    if snapshot.digest_sha256 != bytes(code.entitlements_digest):
        raise SubscriptionRenewalCodeError("code terms are invalid")
    return snapshot


def _find_existing_event(
    session: Session,
    *,
    code_uuid: str,
    idempotency_key: str,
) -> SubscriptionEvent | None:
    matches = list(
        session.scalars(
            sa.select(SubscriptionEvent).where(
                sa.or_(
                    SubscriptionEvent.source_uuid == code_uuid,
                    SubscriptionEvent.idempotency_key == idempotency_key,
                )
            )
        )
    )
    if not matches:
        return None
    if len(matches) != 1:
        raise SubscriptionRenewalConflictError(
            "renewal idempotency identities disagree"
        )
    return matches[0]


def _find_event_by_idempotency_key(
    session: Session,
    *,
    idempotency_key: str,
) -> SubscriptionEvent | None:
    return session.scalar(
        sa.select(SubscriptionEvent).where(
            SubscriptionEvent.idempotency_key == idempotency_key
        )
    )


def _existing_result(
    *,
    event: SubscriptionEvent,
    tenant_uuid: str,
    membership_uuid: str,
    code_uuid: str,
    idempotency_key: str,
    expected_tenant_access_version: int,
    expected_subscription_row_version: int,
    request_digest: bytes,
) -> SubscriptionRenewalResult:
    if (
        event.source_type != "redemption"
        or event.event_type != "renewed"
        or event.tenant_id != tenant_uuid
        or event.source_uuid != code_uuid
        or event.consumed_code_uuid != code_uuid
        or event.idempotency_key != idempotency_key
        or bytes(event.request_digest) != request_digest
        or event.canonicalization_version != RENEWAL_CANONICALIZATION_VERSION
        or event.expected_subscription_row_version != expected_subscription_row_version
        or event.before_expires_at is None
        or event.before_status is None
        or event.exact_duration_seconds is None
        or event.exact_duration_seconds < 1
        or event.after_status != "active"
    ):
        raise SubscriptionRenewalConflictError("renewal idempotency conflict")
    return _result_from_event(
        event=event,
        membership_uuid=membership_uuid,
        expected_tenant_access_version=expected_tenant_access_version,
        created=False,
    )


def _result_from_event(
    *,
    event: SubscriptionEvent,
    membership_uuid: str,
    expected_tenant_access_version: int,
    created: bool,
) -> SubscriptionRenewalResult:
    expected_revision = event.expected_subscription_row_version
    if expected_revision is None:  # pragma: no cover - protected by caller
        raise SubscriptionRenewalConflictError("renewal event is incomplete")
    return SubscriptionRenewalResult(
        tenant_uuid=event.tenant_id,
        membership_uuid=membership_uuid,
        subscription_uuid=event.subscription_id,
        code_uuid=event.source_uuid,
        event_uuid=event.id,
        calculation_base_at=_as_database_utc(event.calculation_base_at),
        database_effective_at=_as_database_utc(event.database_effective_at),
        before_expires_at=_as_database_utc(event.before_expires_at),
        after_expires_at=_as_database_utc(event.after_expires_at),
        before_status=event.before_status,
        after_status=event.after_status,
        expected_tenant_access_version=expected_tenant_access_version,
        expected_subscription_row_version=expected_revision,
        resulting_subscription_row_version=expected_revision + 1,
        created=created,
    )


def _effective_status(expires_at: datetime, database_now: datetime) -> str:
    return "active" if expires_at > database_now else "expired"
