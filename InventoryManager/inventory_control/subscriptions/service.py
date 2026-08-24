"""Caller-transaction subscription ledger operations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.crypto import CryptoCodecV1
from inventory_control.database import read_database_utc_value
from inventory_control.models import (
    MemberSeatGuard,
    PlanRevision,
    Subscription,
    SubscriptionEvent,
    Tenant,
    TenantDatabase,
)

from .entitlements import InvalidEntitlementSnapshotError, parse_core_entitlements
from .migration_grant import calculate_default_tenant_migration_grant


class SubscriptionLedgerError(RuntimeError):
    pass


class SubscriptionLedgerConflictError(SubscriptionLedgerError):
    pass


class SubscriptionLedgerTransactionError(SubscriptionLedgerError):
    pass


class SubscriptionPlanInvalidError(SubscriptionLedgerError):
    pass


DatabaseClock = Callable[[Session], datetime]


@dataclass(frozen=True, slots=True)
class DefaultTenantGrantResult:
    subscription_uuid: str
    event_uuid: str
    source_uuid: str
    expires_at: datetime
    created: bool


class SubscriptionLedgerService:
    """Subscription writes that never commit or roll back their caller."""

    def __init__(self, *, database_clock: DatabaseClock | None = None) -> None:
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._database_clock = database_clock or _read_database_utc_now

    def record_default_tenant_migration_grant(
        self,
        session: Session,
        *,
        tenant_uuid: str | UUID,
        database_uuid: str | UUID,
        baseline_migration_id: str,
        migration_idempotency_key: str,
        plan_revision_uuid: str | UUID,
    ) -> DefaultTenantGrantResult:
        if not isinstance(session, Session) or not session.in_transaction():
            raise SubscriptionLedgerTransactionError(
                "an explicit caller-owned transaction is required"
            )
        tenant_identity = _uuid(tenant_uuid, "tenant_uuid")
        database_identity = _uuid(database_uuid, "database_uuid")
        plan_identity = _uuid(plan_revision_uuid, "plan_revision_uuid")

        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == str(tenant_identity))
            .with_for_update()
        )
        if tenant is None:
            raise SubscriptionLedgerConflictError("tenant is unavailable")
        route = session.scalar(
            sa.select(TenantDatabase)
            .where(TenantDatabase.tenant_id == str(tenant_identity))
            .with_for_update()
        )
        if route is None or route.database_uuid != str(database_identity):
            raise SubscriptionLedgerConflictError(
                "tenant database identity is unavailable"
            )

        database_now = _as_database_utc(self._database_clock(session))
        grant = calculate_default_tenant_migration_grant(
            tenant_uuid=tenant_identity,
            database_uuid=database_identity,
            baseline_migration_id=baseline_migration_id,
            migration_idempotency_key=migration_idempotency_key,
            database_now=database_now,
        )
        request_digest = _grant_request_digest(
            grant_digest=grant.source_identity_digest,
            plan_revision_uuid=plan_identity,
            migration_idempotency_key=migration_idempotency_key,
        )

        existing_event = session.scalar(
            sa.select(SubscriptionEvent).where(
                sa.or_(
                    SubscriptionEvent.source_uuid == str(grant.source_uuid),
                    SubscriptionEvent.idempotency_key == migration_idempotency_key,
                )
            ).with_for_update()
        )
        if existing_event is not None:
            return self._existing_grant_result(
                session,
                event=existing_event,
                tenant_uuid=str(tenant_identity),
                plan_revision_uuid=str(plan_identity),
                source_uuid=str(grant.source_uuid),
                idempotency_key=migration_idempotency_key,
                request_digest=request_digest,
            )

        if session.scalar(
            sa.select(Subscription.id)
            .where(Subscription.tenant_id == str(tenant_identity))
            .with_for_update()
        ) is not None:
            raise SubscriptionLedgerConflictError(
                "tenant subscription already exists without this grant"
            )

        plan = session.get(PlanRevision, str(plan_identity))
        if plan is None:
            raise SubscriptionPlanInvalidError("plan revision is unavailable")
        snapshot = _validated_plan_snapshot(plan)

        guard = session.get(
            MemberSeatGuard,
            {
                "tenant_id": str(tenant_identity),
                "quota_key": "member_seats",
            },
        )
        if guard is None:
            session.add(
                MemberSeatGuard(
                    tenant_id=str(tenant_identity),
                    quota_key="member_seats",
                )
            )

        subscription = Subscription(
            tenant_id=str(tenant_identity),
            plan_revision_uuid=str(plan_identity),
            entitlements_schema_version=snapshot.schema_version,
            entitlements_json={
                "features": dict(snapshot.features),
                "limits": {"member_seats": snapshot.member_seats},
            },
            entitlements_digest=snapshot.digest_sha256,
            status="active",
            expires_at=grant.expires_at,
            provider="manual",
        )
        session.add(subscription)
        session.flush()

        event = SubscriptionEvent(
            tenant_id=str(tenant_identity),
            subscription_id=subscription.id,
            event_type="migration_granted",
            source_type="migration_grant",
            source_uuid=str(grant.source_uuid),
            consumed_code_uuid=None,
            before_plan_revision_uuid=None,
            after_plan_revision_uuid=str(plan_identity),
            before_entitlements_digest=None,
            after_entitlements_digest=snapshot.digest_sha256,
            exact_duration_seconds=int(grant.duration.total_seconds()),
            signed_delta_days=None,
            calculation_base_at=grant.effective_at,
            database_effective_at=grant.effective_at,
            before_expires_at=None,
            after_expires_at=grant.expires_at,
            before_status=None,
            after_status="active",
            expected_subscription_row_version=None,
            idempotency_key=migration_idempotency_key,
            request_digest=request_digest,
            canonicalization_version=1,
            platform_actor_id=None,
            platform_session_id=None,
            factor_method=None,
            factor_accepted_at=None,
            reason_code="default_tenant_migration_grant",
            note=None,
            offline_reference=None,
        )
        session.add(event)
        session.flush()
        return DefaultTenantGrantResult(
            subscription_uuid=subscription.id,
            event_uuid=event.id,
            source_uuid=str(grant.source_uuid),
            expires_at=grant.expires_at,
            created=True,
        )

    def _existing_grant_result(
        self,
        session: Session,
        *,
        event: SubscriptionEvent,
        tenant_uuid: str,
        plan_revision_uuid: str,
        source_uuid: str,
        idempotency_key: str,
        request_digest: bytes,
    ) -> DefaultTenantGrantResult:
        if (
            event.source_type != "migration_grant"
            or event.event_type != "migration_granted"
            or event.tenant_id != tenant_uuid
            or event.after_plan_revision_uuid != plan_revision_uuid
            or event.source_uuid != source_uuid
            or event.idempotency_key != idempotency_key
            or event.request_digest != request_digest
            or event.exact_duration_seconds != 3_153_600_000
        ):
            raise SubscriptionLedgerConflictError(
                "migration grant idempotency conflict"
            )
        subscription = session.get(Subscription, event.subscription_id)
        if (
            subscription is None
            or subscription.tenant_id != tenant_uuid
            or subscription.plan_revision_uuid != plan_revision_uuid
            or subscription.expires_at != event.after_expires_at
        ):
            raise SubscriptionLedgerConflictError(
                "migration grant ledger is inconsistent"
            )
        return DefaultTenantGrantResult(
            subscription_uuid=subscription.id,
            event_uuid=event.id,
            source_uuid=source_uuid,
            expires_at=subscription.expires_at,
            created=False,
        )


def _validated_plan_snapshot(plan: PlanRevision):
    try:
        snapshot = parse_core_entitlements(
            schema_version=plan.entitlements_schema_version,
            entitlements=plan.entitlements_json,
        )
    except InvalidEntitlementSnapshotError:
        raise SubscriptionPlanInvalidError("plan entitlement snapshot is invalid") from None
    if snapshot.digest_sha256 != plan.entitlements_digest:
        raise SubscriptionPlanInvalidError("plan entitlement digest is invalid")
    return snapshot


def _uuid(value: str | UUID, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValueError(f"{field_name} is invalid")


def _grant_request_digest(
    *,
    grant_digest: bytes,
    plan_revision_uuid: UUID,
    migration_idempotency_key: str,
) -> bytes:
    encoded = CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain("inventory-manager/default-tenant-grant-request/v1"),
        grant_digest,
        CryptoCodecV1.uuid_bytes(plan_revision_uuid),
        CryptoCodecV1.ascii_text(migration_idempotency_key),
    )
    return hashlib.sha256(encoded).digest()


def _read_database_utc_now(session: Session) -> datetime:
    return _as_database_utc(read_database_utc_value(session))


def _as_database_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise SubscriptionLedgerTransactionError(
            "database clock did not return a datetime"
        )
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
