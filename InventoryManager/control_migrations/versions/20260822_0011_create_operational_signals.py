"""Create low-cardinality operational signals and alert lifecycle events."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202608220011"
down_revision = "202608220010"
branch_labels = None
depends_on = None


SIGNAL_KEYS = (
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
ENVIRONMENTS = ("development", "production", "staging", "test")
SOURCES = (
    "control_db",
    "evaluator",
    "nas",
    "notification_adapter",
    "provider_aggregate",
    "web",
    "worker",
)
COMPONENTS = (
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
RESULT_CLASSES = (
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


def _sql_values(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "platform_operational_signals",
        sa.Column("signal_key", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("component", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("failure_threshold", sa.Integer(), nullable=False),
        sa.Column("recovery_threshold", sa.Integer(), nullable=False),
        sa.Column("freshness_window_seconds", sa.Integer(), nullable=False),
        sa.Column("repeat_interval_seconds", sa.Integer(), nullable=False),
        sa.Column("observed_status", sa.String(length=16), nullable=False),
        sa.Column("observed_result_class", sa.String(length=32), nullable=False),
        sa.Column("effective_status", sa.String(length=16), nullable=False),
        sa.Column("result_class", sa.String(length=32), nullable=False),
        sa.Column(
            "consecutive_failures",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "consecutive_recoveries",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "state_generation",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "alert_generation",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "lifecycle_sequence",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "active_alert_fingerprint", sa.String(length=64), nullable=True
        ),
        sa.Column(
            "alert_triggered_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("next_repeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "freshness_deadline_at", sa.DateTime(timezone=True), nullable=False
        ),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"signal_key IN ({_sql_values(SIGNAL_KEYS)})",
            name=op.f("ck_platform_operational_signals_signal_key_valid"),
        ),
        sa.CheckConstraint(
            f"environment IN ({_sql_values(ENVIRONMENTS)})",
            name=op.f("ck_platform_operational_signals_environment_valid"),
        ),
        sa.CheckConstraint(
            f"source IN ({_sql_values(SOURCES)})",
            name=op.f("ck_platform_operational_signals_source_valid"),
        ),
        sa.CheckConstraint(
            f"component IN ({_sql_values(COMPONENTS)})",
            name=op.f("ck_platform_operational_signals_component_valid"),
        ),
        sa.CheckConstraint(
            "observed_status IN ('failure', 'ok')",
            name=op.f("ck_platform_operational_signals_observed_status_valid"),
        ),
        sa.CheckConstraint(
            "effective_status IN "
            "('degraded', 'healthy', 'unhealthy', 'unknown')",
            name=op.f("ck_platform_operational_signals_effective_status_valid"),
        ),
        sa.CheckConstraint(
            "severity IN ('p1', 'p2')",
            name=op.f("ck_platform_operational_signals_severity_valid"),
        ),
        sa.CheckConstraint(
            f"observed_result_class IN ({_sql_values(RESULT_CLASSES)})",
            name=op.f(
                "ck_platform_operational_signals_observed_result_valid"
            ),
        ),
        sa.CheckConstraint(
            "((observed_status = 'ok' AND observed_result_class IN "
            "('heartbeat', 'ok', 'verified')) OR "
            "(observed_status = 'failure' AND observed_result_class IN "
            "('authentication_failure', 'capacity_high', 'delivery_failure', "
            "'persistent_failure', 'provider_error', 'rate_limited', "
            "'threshold_exceeded', 'unavailable', 'unknown')))",
            name=op.f(
                "ck_platform_operational_signals_observation_result_match"
            ),
        ),
        sa.CheckConstraint(
            f"result_class IN ({_sql_values(RESULT_CLASSES)})",
            name=op.f("ck_platform_operational_signals_result_class_valid"),
        ),
        sa.CheckConstraint(
            "policy_version >= 1",
            name=op.f("ck_platform_operational_signals_policy_version_positive"),
        ),
        sa.CheckConstraint(
            "failure_threshold >= 1",
            name=op.f(
                "ck_platform_operational_signals_failure_threshold_positive"
            ),
        ),
        sa.CheckConstraint(
            "recovery_threshold >= 1",
            name=op.f(
                "ck_platform_operational_signals_recovery_threshold_positive"
            ),
        ),
        sa.CheckConstraint(
            "freshness_window_seconds >= 1",
            name=op.f(
                "ck_platform_operational_signals_freshness_window_positive"
            ),
        ),
        sa.CheckConstraint(
            "repeat_interval_seconds >= 1",
            name=op.f(
                "ck_platform_operational_signals_repeat_interval_positive"
            ),
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name=op.f("ck_platform_operational_signals_failures_nonnegative"),
        ),
        sa.CheckConstraint(
            "consecutive_recoveries >= 0",
            name=op.f("ck_platform_operational_signals_recoveries_nonnegative"),
        ),
        sa.CheckConstraint(
            "state_generation >= 1",
            name=op.f("ck_platform_operational_signals_state_generation_positive"),
        ),
        sa.CheckConstraint(
            "alert_generation >= 0",
            name=op.f("ck_platform_operational_signals_alert_generation_nonnegative"),
        ),
        sa.CheckConstraint(
            "lifecycle_sequence >= 0",
            name=op.f(
                "ck_platform_operational_signals_lifecycle_sequence_nonnegative"
            ),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_platform_operational_signals_row_version_positive"),
        ),
        sa.CheckConstraint(
            "freshness_deadline_at > observed_at",
            name=op.f(
                "ck_platform_operational_signals_freshness_after_observation"
            ),
        ),
        sa.CheckConstraint(
            "active_alert_fingerprint IS NULL OR "
            "length(active_alert_fingerprint) = 64",
            name=op.f(
                "ck_platform_operational_signals_active_fingerprint_length"
            ),
        ),
        sa.CheckConstraint(
            "((effective_status IN ('unhealthy', 'unknown') "
            "AND active_alert_fingerprint IS NOT NULL "
            "AND alert_generation >= 1 AND next_repeat_at IS NOT NULL) OR "
            "(effective_status IN ('healthy', 'degraded') "
            "AND active_alert_fingerprint IS NULL "
            "AND alert_triggered_at IS NULL AND next_repeat_at IS NULL))",
            name=op.f(
                "ck_platform_operational_signals_active_alert_matches_status"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "signal_key", name=op.f("pk_platform_operational_signals")
        ),
    )
    op.create_index(
        "ix_operational_signals_evaluation",
        "platform_operational_signals",
        ["effective_status", "freshness_deadline_at", "next_repeat_at"],
        unique=False,
    )

    op.create_table(
        "platform_alert_lifecycle_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("signal_key", sa.String(length=64), nullable=False),
        sa.Column("environment", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("component", sa.String(length=32), nullable=False),
        sa.Column("severity", sa.String(length=8), nullable=False),
        sa.Column("event_type", sa.String(length=16), nullable=False),
        sa.Column("effective_status", sa.String(length=16), nullable=False),
        sa.Column("result_class", sa.String(length=32), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("signal_state_generation", sa.BigInteger(), nullable=False),
        sa.Column("alert_generation", sa.BigInteger(), nullable=False),
        sa.Column("lifecycle_sequence", sa.Integer(), nullable=False),
        sa.Column(
            "fingerprint_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("alert_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "suppressed_until", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            f"environment IN ({_sql_values(ENVIRONMENTS)})",
            name=op.f("ck_platform_alert_lifecycle_events_environment_valid"),
        ),
        sa.CheckConstraint(
            f"source IN ({_sql_values(SOURCES)})",
            name=op.f("ck_platform_alert_lifecycle_events_source_valid"),
        ),
        sa.CheckConstraint(
            f"component IN ({_sql_values(COMPONENTS)})",
            name=op.f("ck_platform_alert_lifecycle_events_component_valid"),
        ),
        sa.CheckConstraint(
            "severity IN ('p1', 'p2')",
            name=op.f("ck_platform_alert_lifecycle_events_severity_valid"),
        ),
        sa.CheckConstraint(
            f"result_class IN ({_sql_values(RESULT_CLASSES)})",
            name=op.f("ck_platform_alert_lifecycle_events_result_class_valid"),
        ),
        sa.CheckConstraint(
            "event_type IN ('recovery', 'repeat', 'suppressed', 'trigger')",
            name=op.f("ck_platform_alert_lifecycle_events_event_type_valid"),
        ),
        sa.CheckConstraint(
            "effective_status IN ('healthy', 'unhealthy', 'unknown')",
            name=op.f(
                "ck_platform_alert_lifecycle_events_effective_status_valid"
            ),
        ),
        sa.CheckConstraint(
            "policy_version >= 1",
            name=op.f(
                "ck_platform_alert_lifecycle_events_policy_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "signal_state_generation >= 1",
            name=op.f(
                "ck_platform_alert_lifecycle_events_state_generation_positive"
            ),
        ),
        sa.CheckConstraint(
            "alert_generation >= 1",
            name=op.f(
                "ck_platform_alert_lifecycle_events_alert_generation_positive"
            ),
        ),
        sa.CheckConstraint(
            "lifecycle_sequence >= 1",
            name=op.f(
                "ck_platform_alert_lifecycle_events_lifecycle_sequence_positive"
            ),
        ),
        sa.CheckConstraint(
            "fingerprint_version = 1",
            name=op.f(
                "ck_platform_alert_lifecycle_events_fingerprint_version_valid"
            ),
        ),
        sa.CheckConstraint(
            "length(alert_fingerprint) = 64",
            name=op.f("ck_platform_alert_lifecycle_events_fingerprint_length"),
        ),
        sa.CheckConstraint(
            "((event_type = 'recovery' AND effective_status = 'healthy') OR "
            "(event_type <> 'recovery' "
            "AND effective_status IN ('unhealthy', 'unknown')))",
            name=op.f("ck_platform_alert_lifecycle_events_event_status_valid"),
        ),
        sa.CheckConstraint(
            "((event_type = 'suppressed' AND suppressed_until IS NOT NULL) OR "
            "(event_type <> 'suppressed' AND suppressed_until IS NULL))",
            name=op.f(
                "ck_platform_alert_lifecycle_events_suppression_matches_type"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["signal_key"],
            ["platform_operational_signals.signal_key"],
            name="fk_alert_events_signal",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_platform_alert_lifecycle_events")
        ),
        sa.UniqueConstraint(
            "alert_fingerprint",
            "alert_generation",
            "lifecycle_sequence",
            name="uq_alert_events_lifecycle",
        ),
    )
    op.create_index(
        "ix_alert_events_fingerprint",
        "platform_alert_lifecycle_events",
        ["alert_fingerprint", "alert_generation"],
        unique=False,
    )
    op.create_index(
        "ix_alert_events_signal_time",
        "platform_alert_lifecycle_events",
        ["signal_key", "occurred_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("platform_alert_lifecycle_events")
    op.drop_table("platform_operational_signals")
