"""Low-cardinality current operational state and append-only alert events."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from .base import ControlBase


OPERATIONAL_SIGNAL_KEYS = (
    "backup.dump_duration",
    "backup.verified_freshness",
    "cloud_sync.freshness",
    "control_db.connection_capacity",
    "control_db.connectivity",
    "evaluator.heartbeat",
    "kuaimai.aggregate",
    "notification.delivery",
    "queue.consecutive_failures",
    "queue.oldest_wait",
    "sf.aggregate",
    "sms.aggregate",
    "web.heartbeat",
    "worker.heartbeat",
    "xianyu.aggregate",
)
OPERATIONAL_ENVIRONMENTS = (
    "development",
    "production",
    "staging",
    "test",
)
OPERATIONAL_SOURCES = (
    "control_db",
    "evaluator",
    "nas",
    "notification_adapter",
    "provider_aggregate",
    "web",
    "worker",
)
OPERATIONAL_COMPONENTS = (
    "backup",
    "cloud_sync",
    "evaluator",
    "kuaimai",
    "mysql",
    "notification",
    "queue",
    "sf",
    "sms",
    "web",
    "worker",
    "xianyu",
)
OBSERVATION_STATUSES = ("failure", "ok")
EFFECTIVE_SIGNAL_STATUSES = (
    "degraded",
    "healthy",
    "unhealthy",
    "unknown",
)
OPERATIONAL_SEVERITIES = ("p1", "p2")
OPERATIONAL_RESULT_CLASSES = (
    "authentication_failure",
    "capacity_high",
    "delivery_failure",
    "heartbeat",
    "ok",
    "persistent_failure",
    "provider_error",
    "rate_limited",
    "stale",
    "threshold_exceeded",
    "unavailable",
    "unknown",
    "verified",
)
ALERT_LIFECYCLE_EVENT_TYPES = (
    "recovery",
    "repeat",
    "suppressed",
    "trigger",
)

OPERATIONAL_PROTOCOL_TIMESTAMP_TYPE = sa.DateTime(
    timezone=True
).with_variant(mysql.DATETIME(fsp=6), "mysql")


def _new_uuid() -> str:
    return str(uuid4())


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class PlatformOperationalSignal(ControlBase):
    """One current row per fixed, platform-wide operational signal."""

    __tablename__ = "platform_operational_signals"
    __table_args__ = (
        sa.CheckConstraint(
            f"signal_key IN ({_sql_values(OPERATIONAL_SIGNAL_KEYS)})",
            name="signal_key_valid",
        ),
        sa.CheckConstraint(
            f"environment IN ({_sql_values(OPERATIONAL_ENVIRONMENTS)})",
            name="environment_valid",
        ),
        sa.CheckConstraint(
            f"source IN ({_sql_values(OPERATIONAL_SOURCES)})",
            name="source_valid",
        ),
        sa.CheckConstraint(
            f"component IN ({_sql_values(OPERATIONAL_COMPONENTS)})",
            name="component_valid",
        ),
        sa.CheckConstraint(
            f"observed_status IN ({_sql_values(OBSERVATION_STATUSES)})",
            name="observed_status_valid",
        ),
        sa.CheckConstraint(
            "effective_status IN "
            f"({_sql_values(EFFECTIVE_SIGNAL_STATUSES)})",
            name="effective_status_valid",
        ),
        sa.CheckConstraint(
            f"severity IN ({_sql_values(OPERATIONAL_SEVERITIES)})",
            name="severity_valid",
        ),
        sa.CheckConstraint(
            "observed_result_class IN "
            f"({_sql_values(OPERATIONAL_RESULT_CLASSES)})",
            name="observed_result_valid",
        ),
        sa.CheckConstraint(
            "((observed_status = 'ok' AND observed_result_class IN "
            "('heartbeat', 'ok', 'verified')) OR "
            "(observed_status = 'failure' AND observed_result_class IN "
            "('authentication_failure', 'capacity_high', 'delivery_failure', "
            "'persistent_failure', 'provider_error', 'rate_limited', "
            "'threshold_exceeded', 'unavailable', 'unknown')))",
            name="observation_result_match",
        ),
        sa.CheckConstraint(
            "result_class IN "
            f"({_sql_values(OPERATIONAL_RESULT_CLASSES)})",
            name="result_class_valid",
        ),
        sa.CheckConstraint("policy_version >= 1", name="policy_version_positive"),
        sa.CheckConstraint(
            "failure_threshold >= 1", name="failure_threshold_positive"
        ),
        sa.CheckConstraint(
            "recovery_threshold >= 1", name="recovery_threshold_positive"
        ),
        sa.CheckConstraint(
            "freshness_window_seconds >= 1",
            name="freshness_window_positive",
        ),
        sa.CheckConstraint(
            "repeat_interval_seconds >= 1",
            name="repeat_interval_positive",
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0", name="failures_nonnegative"
        ),
        sa.CheckConstraint(
            "consecutive_recoveries >= 0", name="recoveries_nonnegative"
        ),
        sa.CheckConstraint(
            "state_generation >= 1", name="state_generation_positive"
        ),
        sa.CheckConstraint(
            "alert_generation >= 0", name="alert_generation_nonnegative"
        ),
        sa.CheckConstraint(
            "lifecycle_sequence >= 0", name="lifecycle_sequence_nonnegative"
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "freshness_deadline_at > observed_at",
            name="freshness_after_observation",
        ),
        sa.CheckConstraint(
            "active_alert_fingerprint IS NULL OR "
            "length(active_alert_fingerprint) = 64",
            name="active_fingerprint_length",
        ),
        sa.CheckConstraint(
            "((effective_status IN ('unhealthy', 'unknown') "
            "AND active_alert_fingerprint IS NOT NULL "
            "AND alert_generation >= 1 AND next_repeat_at IS NOT NULL) OR "
            "(effective_status IN ('healthy', 'degraded') "
            "AND active_alert_fingerprint IS NULL "
            "AND alert_triggered_at IS NULL AND next_repeat_at IS NULL))",
            name="active_alert_matches_status",
        ),
        sa.Index(
            "ix_operational_signals_evaluation",
            "effective_status",
            "freshness_deadline_at",
            "next_repeat_at",
        ),
    )

    signal_key: Mapped[str] = mapped_column(sa.String(64), primary_key=True)
    environment: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    source: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    component: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    severity: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    policy_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    failure_threshold: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    recovery_threshold: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    freshness_window_seconds: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    repeat_interval_seconds: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    observed_status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    observed_result_class: Mapped[str] = mapped_column(
        sa.String(32), nullable=False
    )
    effective_status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    result_class: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    consecutive_failures: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    consecutive_recoveries: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    state_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    alert_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )
    lifecycle_sequence: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    active_alert_fingerprint: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    alert_triggered_at: Mapped[datetime | None] = mapped_column(
        OPERATIONAL_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    next_repeat_at: Mapped[datetime | None] = mapped_column(
        OPERATIONAL_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    observed_at: Mapped[datetime] = mapped_column(
        OPERATIONAL_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
    freshness_deadline_at: Mapped[datetime] = mapped_column(
        OPERATIONAL_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        OPERATIONAL_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        OPERATIONAL_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        OPERATIONAL_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )


class PlatformAlertLifecycleEvent(ControlBase):
    """Privacy-safe append-only lifecycle of one aggregated alert root."""

    __tablename__ = "platform_alert_lifecycle_events"
    __table_args__ = (
        sa.CheckConstraint(
            f"environment IN ({_sql_values(OPERATIONAL_ENVIRONMENTS)})",
            name="environment_valid",
        ),
        sa.CheckConstraint(
            f"source IN ({_sql_values(OPERATIONAL_SOURCES)})",
            name="source_valid",
        ),
        sa.CheckConstraint(
            f"component IN ({_sql_values(OPERATIONAL_COMPONENTS)})",
            name="component_valid",
        ),
        sa.CheckConstraint(
            f"severity IN ({_sql_values(OPERATIONAL_SEVERITIES)})",
            name="severity_valid",
        ),
        sa.CheckConstraint(
            "result_class IN "
            f"({_sql_values(OPERATIONAL_RESULT_CLASSES)})",
            name="result_class_valid",
        ),
        sa.CheckConstraint(
            "event_type IN "
            f"({_sql_values(ALERT_LIFECYCLE_EVENT_TYPES)})",
            name="event_type_valid",
        ),
        sa.CheckConstraint(
            "effective_status IN ('healthy', 'unhealthy', 'unknown')",
            name="effective_status_valid",
        ),
        sa.CheckConstraint("policy_version >= 1", name="policy_version_positive"),
        sa.CheckConstraint(
            "signal_state_generation >= 1",
            name="state_generation_positive",
        ),
        sa.CheckConstraint(
            "alert_generation >= 1", name="alert_generation_positive"
        ),
        sa.CheckConstraint(
            "lifecycle_sequence >= 1", name="lifecycle_sequence_positive"
        ),
        sa.CheckConstraint(
            "fingerprint_version = 1", name="fingerprint_version_valid"
        ),
        sa.CheckConstraint(
            "length(alert_fingerprint) = 64", name="fingerprint_length"
        ),
        sa.CheckConstraint(
            "((event_type = 'recovery' AND effective_status = 'healthy') OR "
            "(event_type <> 'recovery' "
            "AND effective_status IN ('unhealthy', 'unknown')))",
            name="event_status_valid",
        ),
        sa.CheckConstraint(
            "((event_type = 'suppressed' AND suppressed_until IS NOT NULL) OR "
            "(event_type <> 'suppressed' AND suppressed_until IS NULL))",
            name="suppression_matches_type",
        ),
        sa.ForeignKeyConstraint(
            ["signal_key"],
            ["platform_operational_signals.signal_key"],
            name="fk_alert_events_signal",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "alert_fingerprint",
            "alert_generation",
            "lifecycle_sequence",
            name="uq_alert_events_lifecycle",
        ),
        sa.Index(
            "ix_alert_events_signal_time",
            "signal_key",
            "occurred_at",
        ),
        sa.Index(
            "ix_alert_events_fingerprint",
            "alert_fingerprint",
            "alert_generation",
        ),
    )

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    signal_key: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    environment: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    source: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    component: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    severity: Mapped[str] = mapped_column(sa.String(8), nullable=False)
    event_type: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    effective_status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    result_class: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    policy_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    signal_state_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    alert_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    lifecycle_sequence: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    fingerprint_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("1")
    )
    alert_fingerprint: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    suppressed_until: Mapped[datetime | None] = mapped_column(
        OPERATIONAL_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    occurred_at: Mapped[datetime] = mapped_column(
        OPERATIONAL_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
