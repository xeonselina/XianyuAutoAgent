"""add tenant-bound Xianyu synchronization state

Revision ID: 20260823_xianyu_sync_state
Revises: 20260822_shipping_ledgers
Create Date: 2026-08-23
"""

from alembic import op
import sqlalchemy as sa


revision = "20260823_xianyu_sync_state"
down_revision = "20260822_shipping_ledgers"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("xianyu_order_alerts") as batch_op:
        batch_op.add_column(
            sa.Column("integration_uuid", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("secret_revision_uuid", sa.String(length=36), nullable=True)
        )
        batch_op.create_index(
            "ix_xianyu_order_alerts_integration_uuid",
            ["integration_uuid"],
            unique=False,
        )

    with op.batch_alter_table("xianyu_order_sync_state") as batch_op:
        batch_op.add_column(
            sa.Column(
                "snapshot_revision",
                sa.BigInteger(),
                nullable=False,
                server_default=sa.text("0"),
            )
        )
        batch_op.add_column(
            sa.Column(
                "sync_status",
                sa.String(length=32),
                nullable=False,
                server_default=sa.text("'never'"),
            )
        )
        batch_op.add_column(
            sa.Column("current_job_uuid", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("last_applied_job_uuid", sa.String(length=36), nullable=True)
        )
        batch_op.add_column(
            sa.Column("updated_at", sa.DateTime(), nullable=True)
        )
        batch_op.create_check_constraint(
            "ck_xianyu_sync_snapshot_revision_nonnegative",
            "snapshot_revision >= 0",
        )
        batch_op.create_check_constraint(
            "ck_xianyu_sync_status_valid",
            "sync_status IN ('never', 'syncing', 'succeeded', "
            "'partial_failure', 'failed', 'rate_limited')",
        )
        batch_op.create_unique_constraint(
            "uq_xianyu_sync_last_applied_job_uuid",
            ["last_applied_job_uuid"],
        )

    op.execute(
        sa.text(
            "UPDATE xianyu_order_sync_state "
            "SET updated_at = COALESCE(last_attempt_at, CURRENT_TIMESTAMP) "
            "WHERE updated_at IS NULL"
        )
    )
    with op.batch_alter_table("xianyu_order_sync_state") as batch_op:
        batch_op.alter_column(
            "updated_at",
            existing_type=sa.DateTime(),
            nullable=False,
        )

    op.create_table(
        "xianyu_connection_sync_states",
        sa.Column("integration_uuid", sa.String(length=36), nullable=False),
        sa.Column("secret_revision_uuid", sa.String(length=36), nullable=False),
        sa.Column(
            "snapshot_revision",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("0"),
        ),
        sa.Column(
            "sync_status",
            sa.String(length=32),
            nullable=False,
            server_default=sa.text("'never'"),
        ),
        sa.Column("last_job_uuid", sa.String(length=36), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.Column("retry_after_at", sa.DateTime(), nullable=True),
        sa.Column("provider_cursor", sa.String(length=512), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            nullable=False,
            server_default=sa.text("1"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.CheckConstraint(
            "snapshot_revision >= 0",
            name="ck_xianyu_connection_snapshot_revision_nonnegative",
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name="ck_xianyu_connection_row_version_positive",
        ),
        sa.CheckConstraint(
            "sync_status IN ('never', 'syncing', 'succeeded', "
            "'failed', 'rate_limited')",
            name="ck_xianyu_connection_sync_status_valid",
        ),
        sa.PrimaryKeyConstraint("integration_uuid"),
    )
    op.create_index(
        "ix_xianyu_connection_sync_status",
        "xianyu_connection_sync_states",
        ["sync_status", "last_attempt_at"],
        unique=False,
    )


def downgrade():
    op.drop_table("xianyu_connection_sync_states")

    with op.batch_alter_table("xianyu_order_sync_state") as batch_op:
        batch_op.drop_constraint(
            "uq_xianyu_sync_last_applied_job_uuid", type_="unique"
        )
        batch_op.drop_constraint("ck_xianyu_sync_status_valid", type_="check")
        batch_op.drop_constraint(
            "ck_xianyu_sync_snapshot_revision_nonnegative", type_="check"
        )
        batch_op.drop_column("updated_at")
        batch_op.drop_column("last_applied_job_uuid")
        batch_op.drop_column("current_job_uuid")
        batch_op.drop_column("sync_status")
        batch_op.drop_column("snapshot_revision")

    with op.batch_alter_table("xianyu_order_alerts") as batch_op:
        batch_op.drop_index("ix_xianyu_order_alerts_integration_uuid")
        batch_op.drop_column("secret_revision_uuid")
        batch_op.drop_column("integration_uuid")
