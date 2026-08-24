"""Control-database subscription, entitlement, and member-seat facts."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import ControlBase


def _new_uuid() -> str:
    return str(uuid4())


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
SUBSCRIPTION_PROTOCOL_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


class PlanRevision(ControlBase):
    """One immutable entitlement revision; ``active`` selects new issuance."""

    __tablename__ = "plans"
    __table_args__ = (
        sa.UniqueConstraint("code", "revision", name="uq_plans_code_revision"),
        sa.UniqueConstraint(
            "id",
            "entitlements_schema_version",
            "entitlements_digest",
            name="uq_plans_snapshot_identity",
        ),
        sa.CheckConstraint("length(trim(code)) >= 1", name="code_nonempty"),
        sa.CheckConstraint("length(trim(name)) >= 1", name="name_nonempty"),
        sa.CheckConstraint("revision >= 1", name="revision_positive"),
        sa.CheckConstraint(
            "entitlements_schema_version >= 1",
            name="entitlements_schema_version_positive",
        ),
        sa.CheckConstraint(
            "length(entitlements_digest) = 32",
            name="entitlements_digest_length",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    revision: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    entitlements_schema_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    entitlements_json: Mapped[dict[str, Any]] = mapped_column(
        sa.JSON, nullable=False
    )
    entitlements_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    active: Mapped[bool] = mapped_column(
        sa.Boolean,
        nullable=False,
        default=True,
        server_default=sa.true(),
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

    subscriptions: Mapped[list[Subscription]] = relationship(
        back_populates="plan_revision"
    )


class MemberSeatGuard(ControlBase):
    """Per-tenant row lock for realtime member-seat recounts.

    The guard deliberately stores no occupied-seat counter or cached usage.
    """

    __tablename__ = "tenant_quota_guards"
    __table_args__ = (
        sa.CheckConstraint(
            "quota_key = 'member_seats'", name="quota_key_member_seats"
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
    )

    tenant_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    quota_key: Mapped[str] = mapped_column(
        sa.String(32),
        primary_key=True,
        default="member_seats",
        server_default=sa.text("'member_seats'"),
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


class Subscription(ControlBase):
    """The one current subscription projection for a tenant."""

    __tablename__ = "subscriptions"
    __table_args__ = (
        sa.UniqueConstraint("tenant_id", name="uq_subscriptions_tenant_id"),
        sa.UniqueConstraint(
            "id", "tenant_id", name="uq_subscriptions_id_tenant"
        ),
        sa.UniqueConstraint(
            "created_from_registration_commit_uuid",
            name="uq_subscriptions_registration_commit",
        ),
        sa.ForeignKeyConstraint(
            [
                "plan_revision_uuid",
                "entitlements_schema_version",
                "entitlements_digest",
            ],
            [
                "plans.id",
                "plans.entitlements_schema_version",
                "plans.entitlements_digest",
            ],
            name="fk_subscriptions_plan_snapshot",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "entitlements_schema_version >= 1",
            name="entitlements_schema_version_positive",
        ),
        sa.CheckConstraint(
            "length(entitlements_digest) = 32",
            name="entitlements_digest_length",
        ),
        sa.CheckConstraint(
            "status IN ('active', 'expired')", name="status_valid"
        ),
        sa.CheckConstraint(
            "provider IN ('manual', 'stripe', 'wechat', 'alipay')",
            name="provider_valid",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "provider_ref IS NULL OR length(provider_ref) <= 128",
            name="provider_ref_bounded",
        ),
        sa.CheckConstraint(
            "created_from_registration_commit_uuid IS NULL OR "
            "length(created_from_registration_commit_uuid) = 36",
            name="registration_commit_uuid_shape",
        ),
        sa.Index("ix_subscriptions_status_expiry", "status", "expires_at"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    plan_revision_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    entitlements_schema_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    entitlements_json: Mapped[dict[str, Any]] = mapped_column(
        sa.JSON, nullable=False
    )
    entitlements_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        SUBSCRIPTION_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    provider: Mapped[str] = mapped_column(
        sa.String(16),
        nullable=False,
        default="manual",
        server_default=sa.text("'manual'"),
    )
    provider_ref: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    created_from_registration_commit_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

    plan_revision: Mapped[PlanRevision] = relationship(
        back_populates="subscriptions"
    )
    events: Mapped[list[SubscriptionEvent]] = relationship(
        back_populates="subscription"
    )


class SubscriptionEvent(ControlBase):
    """Immutable subscription ledger entry with complete calculation facts."""

    __tablename__ = "subscription_events"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["subscription_id", "tenant_id"],
            ["subscriptions.id", "subscriptions.tenant_id"],
            name="fk_subscription_events_subscription_tenant",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["before_plan_revision_uuid"],
            ["plans.id"],
            name="fk_subscription_events_before_plan",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["after_plan_revision_uuid"],
            ["plans.id"],
            name="fk_subscription_events_after_plan",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "source_uuid", name="uq_subscription_events_source_uuid"
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_subscription_events_idempotency_key"
        ),
        sa.CheckConstraint(
            "event_type IN ('activated', 'renewed', 'days_adjusted', "
            "'expired_now', 'migration_granted')",
            name="event_type_valid",
        ),
        sa.CheckConstraint(
            "source_type IN ('registration', 'redemption', "
            "'platform_adjustment', 'migration_grant')",
            name="source_type_valid",
        ),
        sa.CheckConstraint(
            "((source_type = 'registration' AND event_type = 'activated') OR "
            "(source_type = 'redemption' AND event_type = 'renewed') OR "
            "(source_type = 'platform_adjustment' AND event_type IN "
            "('days_adjusted', 'expired_now')) OR "
            "(source_type = 'migration_grant' "
            "AND event_type = 'migration_granted'))",
            name="source_event_match",
        ),
        sa.CheckConstraint(
            "length(source_uuid) = 36", name="source_uuid_shape"
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32", name="request_digest_length"
        ),
        sa.CheckConstraint(
            "length(trim(idempotency_key)) >= 1 "
            "AND length(idempotency_key) <= 128",
            name="idempotency_key_bounded",
        ),
        sa.CheckConstraint(
            "canonicalization_version >= 1",
            name="canonicalization_version_positive",
        ),
        sa.CheckConstraint(
            "before_entitlements_digest IS NULL OR "
            "length(before_entitlements_digest) = 32",
            name="before_digest_length",
        ),
        sa.CheckConstraint(
            "length(after_entitlements_digest) = 32",
            name="after_digest_length",
        ),
        sa.CheckConstraint(
            "before_status IS NULL OR before_status IN ('active', 'expired')",
            name="before_status_valid",
        ),
        sa.CheckConstraint(
            "after_status IN ('active', 'expired')", name="after_status_valid"
        ),
        sa.CheckConstraint(
            "((before_plan_revision_uuid IS NULL "
            "AND before_entitlements_digest IS NULL "
            "AND before_expires_at IS NULL AND before_status IS NULL) OR "
            "(before_plan_revision_uuid IS NOT NULL "
            "AND before_entitlements_digest IS NOT NULL "
            "AND before_expires_at IS NOT NULL AND before_status IS NOT NULL))",
            name="before_snapshot_match",
        ),
        sa.CheckConstraint(
            "((source_type IN ('registration', 'migration_grant') "
            "AND before_plan_revision_uuid IS NULL) OR "
            "(source_type IN ('redemption', 'platform_adjustment') "
            "AND before_plan_revision_uuid IS NOT NULL))",
            name="source_before_snapshot_match",
        ),
        sa.CheckConstraint(
            "((source_type IN ('registration', 'redemption', "
            "'migration_grant') AND exact_duration_seconds > 0 "
            "AND signed_delta_days IS NULL) OR "
            "(source_type = 'platform_adjustment' "
            "AND event_type = 'days_adjusted' "
            "AND exact_duration_seconds IS NULL "
            "AND signed_delta_days <> 0) OR "
            "(source_type = 'platform_adjustment' "
            "AND event_type = 'expired_now' "
            "AND exact_duration_seconds IS NULL "
            "AND signed_delta_days IS NULL))",
            name="term_input_match",
        ),
        sa.CheckConstraint(
            "((source_type IN ('registration', 'redemption') "
            "AND consumed_code_uuid IS NOT NULL) OR "
            "(source_type IN ('platform_adjustment', 'migration_grant') "
            "AND consumed_code_uuid IS NULL))",
            name="consumed_code_match",
        ),
        sa.CheckConstraint(
            "consumed_code_uuid IS NULL OR length(consumed_code_uuid) = 36",
            name="consumed_code_uuid_shape",
        ),
        sa.CheckConstraint(
            "expected_subscription_row_version IS NULL OR "
            "expected_subscription_row_version >= 1",
            name="expected_revision_positive",
        ),
        sa.CheckConstraint(
            "factor_method IS NULL OR factor_method IN ('totp', 'recovery_code')",
            name="factor_method_valid",
        ),
        sa.CheckConstraint(
            "platform_actor_id IS NULL OR length(platform_actor_id) = 36",
            name="platform_actor_uuid_shape",
        ),
        sa.CheckConstraint(
            "platform_session_id IS NULL OR length(platform_session_id) = 36",
            name="platform_session_uuid_shape",
        ),
        sa.CheckConstraint(
            "((source_type = 'platform_adjustment' "
            "AND platform_actor_id IS NOT NULL "
            "AND platform_session_id IS NOT NULL "
            "AND factor_method IS NOT NULL "
            "AND factor_accepted_at IS NOT NULL) OR "
            "(source_type <> 'platform_adjustment' "
            "AND platform_actor_id IS NULL "
            "AND platform_session_id IS NULL "
            "AND factor_method IS NULL AND factor_accepted_at IS NULL))",
            name="platform_evidence_match",
        ),
        sa.CheckConstraint(
            "source_type <> 'platform_adjustment' OR "
            "(before_plan_revision_uuid = after_plan_revision_uuid "
            "AND before_entitlements_digest = after_entitlements_digest)",
            name="platform_snapshot_same",
        ),
        sa.CheckConstraint(
            "source_type <> 'migration_grant' OR "
            "exact_duration_seconds = 3153600000",
            name="migration_duration_exact",
        ),
        sa.CheckConstraint(
            "length(trim(reason_code)) >= 1 AND length(reason_code) <= 64",
            name="reason_code_bounded",
        ),
        sa.CheckConstraint(
            "note IS NULL OR length(note) <= 500", name="note_bounded"
        ),
        sa.CheckConstraint(
            "offline_reference IS NULL OR length(offline_reference) <= 128",
            name="offline_reference_bounded",
        ),
        sa.CheckConstraint(
            "offline_reference IS NULL OR source_type = 'platform_adjustment'",
            name="offline_ref_source",
        ),
        sa.Index(
            "ix_subscription_events_tenant_effective",
            "tenant_id",
            "database_effective_at",
            "id",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    subscription_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    source_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    source_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    consumed_code_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    before_plan_revision_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    after_plan_revision_uuid: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    before_entitlements_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    after_entitlements_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    exact_duration_seconds: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    signed_delta_days: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True
    )
    calculation_base_at: Mapped[datetime] = mapped_column(
        SUBSCRIPTION_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
    database_effective_at: Mapped[datetime] = mapped_column(
        SUBSCRIPTION_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
    before_expires_at: Mapped[datetime | None] = mapped_column(
        SUBSCRIPTION_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    after_expires_at: Mapped[datetime] = mapped_column(
        SUBSCRIPTION_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
    before_status: Mapped[str | None] = mapped_column(
        sa.String(16), nullable=True
    )
    after_status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    expected_subscription_row_version: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    request_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    canonicalization_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    platform_actor_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    platform_session_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    factor_method: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    factor_accepted_at: Mapped[datetime | None] = mapped_column(
        SUBSCRIPTION_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    reason_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(sa.String(500), nullable=True)
    offline_reference: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

    subscription: Mapped[Subscription] = relationship(back_populates="events")
    before_plan_revision: Mapped[PlanRevision | None] = relationship(
        foreign_keys=[before_plan_revision_uuid]
    )
    after_plan_revision: Mapped[PlanRevision] = relationship(
        foreign_keys=[after_plan_revision_uuid]
    )
