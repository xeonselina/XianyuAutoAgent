"""Create D52 tenant suspension aggregates and actions."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp


revision = "202608220019"
down_revision = "202608220018"
branch_labels = None
depends_on = None


MICROSECOND_DATETIME = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)
DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")


def upgrade() -> None:
    op.create_table(
        "tenant_suspensions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "active_tenant_id",
            sa.String(length=36),
            sa.Computed(
                "CASE WHEN state = 'resolved' THEN NULL ELSE tenant_id END",
                persisted=True,
            ),
            nullable=True,
        ),
        sa.Column("initial_reason_code", sa.String(length=64), nullable=False),
        sa.Column("initial_safe_note", sa.String(length=500), nullable=True),
        sa.Column("barrier_generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "committed_tenant_row_version",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "committed_access_version",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("requested_at", MICROSECOND_DATETIME, nullable=False),
        sa.Column("frozen_at", MICROSECOND_DATETIME, nullable=True),
        sa.Column("resolving_at", MICROSECOND_DATETIME, nullable=True),
        sa.Column("resolved_at", MICROSECOND_DATETIME, nullable=True),
        sa.Column("safe_failure_code", sa.String(length=64), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            MICROSECOND_DATETIME,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            MICROSECOND_DATETIME,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('freezing', 'active', 'resolving', 'resolved', 'failed')",
            name=op.f("ck_tenant_suspensions_state_valid"),
        ),
        sa.CheckConstraint(
            "barrier_generation >= 1 AND committed_tenant_row_version >= 1 "
            "AND committed_access_version >= 1 AND row_version >= 1",
            name=op.f("ck_tenant_suspensions_versions_positive"),
        ),
        sa.CheckConstraint(
            "((state = 'freezing' AND frozen_at IS NULL "
            "AND resolving_at IS NULL AND resolved_at IS NULL "
            "AND safe_failure_code IS NULL) OR "
            "(state = 'active' AND frozen_at IS NOT NULL "
            "AND resolving_at IS NULL AND resolved_at IS NULL "
            "AND safe_failure_code IS NULL) OR "
            "(state = 'resolving' AND frozen_at IS NOT NULL "
            "AND resolving_at IS NOT NULL AND resolved_at IS NULL "
            "AND safe_failure_code IS NULL) OR "
            "(state = 'resolved' AND frozen_at IS NOT NULL "
            "AND resolving_at IS NOT NULL AND resolved_at IS NOT NULL "
            "AND safe_failure_code IS NULL) OR "
            "(state = 'failed' AND resolved_at IS NULL "
            "AND safe_failure_code IS NOT NULL))",
            name=op.f("ck_tenant_suspensions_state_facts_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.id"],
            name=op.f("fk_tenant_suspensions_tenant"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_tenant_suspensions"),
        ),
        sa.UniqueConstraint(
            "active_tenant_id",
            name="uq_tenant_suspensions_active_tenant",
        ),
    )
    op.create_index(
        "ix_tenant_suspensions_tenant_state",
        "tenant_suspensions",
        ["tenant_id", "state", "barrier_generation"],
        unique=False,
    )

    op.create_table(
        "tenant_suspension_actions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("suspension_id", sa.String(length=36), nullable=False),
        sa.Column("direction", sa.String(length=24), nullable=False),
        sa.Column("generation", sa.BigInteger(), nullable=False),
        sa.Column("actor_type", sa.String(length=24), nullable=False),
        sa.Column("platform_admin_id", sa.String(length=36), nullable=True),
        sa.Column("platform_session_id", sa.String(length=36), nullable=True),
        sa.Column("recent_step_up_method", sa.String(length=24), nullable=True),
        sa.Column("recent_step_up_at", MICROSECOND_DATETIME, nullable=True),
        sa.Column("authorization_source", sa.String(length=32), nullable=False),
        sa.Column("authorization_source_uuid", sa.String(length=36), nullable=True),
        sa.Column("safe_correlation", sa.String(length=160), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=False),
        sa.Column("safe_note", sa.String(length=500), nullable=True),
        sa.Column("idempotency_key", sa.String(length=160), nullable=False),
        sa.Column("request_digest", DIGEST_TYPE, nullable=False),
        sa.Column(
            "expected_suspension_row_version",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "expected_tenant_row_version",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("expected_access_version", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("safe_outcome_code", sa.String(length=64), nullable=True),
        sa.Column("safe_failure_code", sa.String(length=64), nullable=True),
        sa.Column("requested_at", MICROSECOND_DATETIME, nullable=False),
        sa.Column("started_at", MICROSECOND_DATETIME, nullable=True),
        sa.Column("completed_at", MICROSECOND_DATETIME, nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            MICROSECOND_DATETIME,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            MICROSECOND_DATETIME,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "direction IN ('freeze', 'resolve', 'enforce_locked')",
            name=op.f("ck_tenant_suspension_actions_direction_valid"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('platform_admin', 'system')",
            name=op.f("ck_tenant_suspension_actions_actor_type_valid"),
        ),
        sa.CheckConstraint(
            "authorization_source IN "
            "('user_step_up', 'deletion_request', 'dr_recovery')",
            name=op.f(
                "ck_tenant_suspension_actions_authorization_source_valid"
            ),
        ),
        sa.CheckConstraint(
            "state IN ('requested', 'running', 'succeeded', "
            "'superseded', 'failed')",
            name=op.f("ck_tenant_suspension_actions_state_valid"),
        ),
        sa.CheckConstraint(
            "recent_step_up_method IS NULL OR "
            "recent_step_up_method IN ('totp', 'recovery_code')",
            name=op.f("ck_tenant_suspension_actions_step_up_method_valid"),
        ),
        sa.CheckConstraint(
            "generation >= 1 AND expected_suspension_row_version >= 0 "
            "AND expected_tenant_row_version >= 1 "
            "AND expected_access_version >= 1 AND row_version >= 1",
            name=op.f("ck_tenant_suspension_actions_versions_valid"),
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32",
            name=op.f("ck_tenant_suspension_actions_request_digest_length"),
        ),
        sa.CheckConstraint(
            "((direction IN ('freeze', 'resolve') "
            "AND actor_type = 'platform_admin' "
            "AND platform_admin_id IS NOT NULL "
            "AND platform_session_id IS NOT NULL "
            "AND recent_step_up_method IS NOT NULL "
            "AND recent_step_up_at IS NOT NULL "
            "AND authorization_source = 'user_step_up' "
            "AND authorization_source_uuid IS NULL) OR "
            "(direction = 'enforce_locked' AND actor_type = 'system' "
            "AND platform_admin_id IS NULL AND platform_session_id IS NULL "
            "AND recent_step_up_method IS NULL AND recent_step_up_at IS NULL "
            "AND authorization_source IN ('deletion_request', 'dr_recovery') "
            "AND authorization_source_uuid IS NOT NULL))",
            name=op.f(
                "ck_tenant_suspension_actions_authority_provenance_complete"
            ),
        ),
        sa.CheckConstraint(
            "((state IN ('succeeded', 'superseded', 'failed') "
            "AND completed_at IS NOT NULL AND safe_outcome_code IS NOT NULL) "
            "OR (state IN ('requested', 'running') "
            "AND completed_at IS NULL AND safe_outcome_code IS NULL))",
            name=op.f(
                "ck_tenant_suspension_actions_terminal_outcome_complete"
            ),
        ),
        sa.CheckConstraint(
            "((state = 'failed' AND safe_failure_code IS NOT NULL) OR "
            "(state <> 'failed' AND safe_failure_code IS NULL))",
            name=op.f(
                "ck_tenant_suspension_actions_failure_state_complete"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["suspension_id"],
            ["tenant_suspensions.id"],
            name=op.f("fk_suspension_actions_suspension"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["platform_admin_id"],
            ["platform_admins.id"],
            name=op.f("fk_suspension_actions_admin"),
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["platform_session_id"],
            ["platform_admin_sessions.id"],
            name=op.f("fk_suspension_actions_session"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_tenant_suspension_actions"),
        ),
        sa.UniqueConstraint(
            "suspension_id",
            "generation",
            name="uq_suspension_actions_suspension_generation",
        ),
        sa.UniqueConstraint(
            "suspension_id",
            "idempotency_key",
            name="uq_suspension_actions_suspension_idempotency",
        ),
    )
    op.create_index(
        "ix_suspension_actions_suspension_state",
        "tenant_suspension_actions",
        ["suspension_id", "state", "generation"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("tenant_suspension_actions")
    op.drop_table("tenant_suspensions")
