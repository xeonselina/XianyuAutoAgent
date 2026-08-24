"""Create per-tenant fleet migration state and schema metadata.

Revision ID: 202608220022
Revises: 202608220021
Create Date: 2026-08-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp


revision = "202608220022"
down_revision = "202608220021"
branch_labels = None
depends_on = None


FLEET_DIGEST = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
FLEET_TIMESTAMP = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


def upgrade() -> None:
    with op.batch_alter_table(
        "database_identity_control_records",
        schema=None,
    ) as batch_op:
        batch_op.add_column(
            sa.Column(
                "expected_schema_revision",
                sa.String(length=128),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "expected_schema_sha256",
                FLEET_DIGEST,
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "observed_schema_revision",
                sa.String(length=128),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "observed_schema_sha256",
                FLEET_DIGEST,
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column(
                "row_version",
                sa.BigInteger(),
                server_default=sa.text("1"),
                nullable=False,
            )
        )
        batch_op.create_check_constraint(
            "ck_database_identity_control_records_expected_metadata_complete",
            "((expected_schema_revision IS NULL "
            "AND expected_schema_sha256 IS NULL) OR "
            "(expected_schema_revision IS NOT NULL "
            "AND expected_schema_sha256 IS NOT NULL "
            "AND length(expected_schema_sha256) = 32))",
        )
        batch_op.create_check_constraint(
            "ck_database_identity_control_records_observed_metadata_complete",
            "((observed_schema_revision IS NULL "
            "AND observed_schema_sha256 IS NULL) OR "
            "(observed_schema_revision IS NOT NULL "
            "AND observed_schema_sha256 IS NOT NULL "
            "AND length(observed_schema_sha256) = 32))",
        )
        batch_op.create_check_constraint(
            "ck_database_identity_control_records_row_version_positive",
            "row_version >= 1",
        )

    op.create_table(
        "tenant_fleet_migrations",
        sa.Column("migration_uuid", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("database_uuid", sa.String(length=36), nullable=False),
        sa.Column("source_schema_generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "source_schema_revision",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("source_schema_sha256", FLEET_DIGEST, nullable=False),
        sa.Column("target_schema_generation", sa.BigInteger(), nullable=False),
        sa.Column(
            "target_schema_revision",
            sa.String(length=128),
            nullable=False,
        ),
        sa.Column("target_schema_sha256", FLEET_DIGEST, nullable=False),
        sa.Column(
            "last_observed_tenant_uuid",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column(
            "last_observed_database_uuid",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column(
            "last_observed_schema_generation",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "last_observed_schema_revision",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "last_observed_schema_sha256",
            FLEET_DIGEST,
            nullable=True,
        ),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "route_disposition",
            sa.String(length=32),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.BigInteger(), nullable=False),
        sa.Column("operation_generation", sa.BigInteger(), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.Column("last_transition", sa.String(length=16), nullable=False),
        sa.Column(
            "last_transition_from_row_version",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("queue_request_digest", FLEET_DIGEST, nullable=False),
        sa.Column("last_request_digest", FLEET_DIGEST, nullable=False),
        sa.Column(
            "schema_operation_claim_uuid",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column(
            "schema_operation_owner_id",
            sa.String(length=128),
            nullable=True,
        ),
        sa.Column(
            "schema_operation_generation",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "schema_operation_fencing_token",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column(
            "schema_operation_row_version",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.Column("queued_at", FLEET_TIMESTAMP, nullable=False),
        sa.Column("started_at", FLEET_TIMESTAMP, nullable=True),
        sa.Column("completed_at", FLEET_TIMESTAMP, nullable=True),
        sa.Column("last_observed_at", FLEET_TIMESTAMP, nullable=True),
        sa.Column(
            "created_at",
            FLEET_TIMESTAMP,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            FLEET_TIMESTAMP,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed')",
            name=op.f("ck_tenant_fleet_migrations_state_valid"),
        ),
        sa.CheckConstraint(
            "route_disposition IN "
            "('routable_current', 'routable_previous', "
            "'hold_identity_mismatch', 'hold_schema_drift', "
            "'hold_unsupported_schema', 'hold_unverified_schema')",
            name=op.f(
                "ck_tenant_fleet_migrations_route_disposition_valid"
            ),
        ),
        sa.CheckConstraint(
            "last_transition IN ('queue', 'begin', 'succeed', 'fail', 'retry')",
            name=op.f(
                "ck_tenant_fleet_migrations_last_transition_valid"
            ),
        ),
        sa.CheckConstraint(
            "source_schema_generation >= 1 AND "
            "target_schema_generation = source_schema_generation + 1",
            name=op.f(
                "ck_tenant_fleet_migrations_schema_generations_adjacent"
            ),
        ),
        sa.CheckConstraint(
            "length(trim(source_schema_revision)) > 0 AND "
            "length(trim(target_schema_revision)) > 0",
            name=op.f(
                "ck_tenant_fleet_migrations_schema_revisions_nonempty"
            ),
        ),
        sa.CheckConstraint(
            "length(source_schema_sha256) = 32 AND "
            "length(target_schema_sha256) = 32 AND "
            "length(queue_request_digest) = 32 AND "
            "length(last_request_digest) = 32",
            name=op.f(
                "ck_tenant_fleet_migrations_required_digests_valid"
            ),
        ),
        sa.CheckConstraint(
            "((last_observed_tenant_uuid IS NULL "
            "AND last_observed_database_uuid IS NULL "
            "AND last_observed_schema_generation IS NULL "
            "AND last_observed_schema_revision IS NULL "
            "AND last_observed_schema_sha256 IS NULL "
            "AND last_observed_at IS NULL) OR "
            "(last_observed_tenant_uuid IS NOT NULL "
            "AND last_observed_database_uuid IS NOT NULL "
            "AND last_observed_schema_generation >= 1 "
            "AND last_observed_schema_revision IS NOT NULL "
            "AND last_observed_schema_sha256 IS NOT NULL "
            "AND length(last_observed_schema_sha256) = 32 "
            "AND last_observed_at IS NOT NULL))",
            name=op.f(
                "ck_tenant_fleet_migrations_observation_complete"
            ),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND operation_generation = attempt_count "
            "AND row_version >= 1 "
            "AND last_transition_from_row_version = row_version - 1",
            name=op.f(
                "ck_tenant_fleet_migrations_versions_nonnegative"
            ),
        ),
        sa.CheckConstraint(
            "((schema_operation_claim_uuid IS NULL "
            "AND schema_operation_owner_id IS NULL "
            "AND schema_operation_generation IS NULL "
            "AND schema_operation_fencing_token IS NULL "
            "AND schema_operation_row_version IS NULL) OR "
            "(schema_operation_claim_uuid IS NOT NULL "
            "AND schema_operation_owner_id IS NOT NULL "
            "AND schema_operation_generation >= 1 "
            "AND schema_operation_fencing_token >= 1 "
            "AND schema_operation_row_version >= 1))",
            name=op.f(
                "ck_tenant_fleet_migrations_schema_operation_fence_complete"
            ),
        ),
        sa.CheckConstraint(
            "((state = 'queued' AND attempt_count = 0 "
            "AND operation_generation = 0 AND row_version = 1 "
            "AND started_at IS NULL AND completed_at IS NULL "
            "AND safe_error_code IS NULL "
            "AND last_transition = 'queue' "
            "AND last_transition_from_row_version = 0 "
            "AND last_observed_tenant_uuid IS NULL "
            "AND last_observed_schema_generation IS NULL "
            "AND schema_operation_claim_uuid IS NULL) OR "
            "(state = 'running' AND attempt_count >= 1 "
            "AND operation_generation >= 1 AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND safe_error_code IS NULL "
            "AND last_transition IN ('begin', 'retry') "
            "AND last_observed_tenant_uuid = tenant_id "
            "AND last_observed_database_uuid = database_uuid "
            "AND last_observed_schema_generation = source_schema_generation "
            "AND last_observed_schema_revision = source_schema_revision "
            "AND last_observed_schema_sha256 = source_schema_sha256 "
            "AND schema_operation_claim_uuid IS NOT NULL) OR "
            "(state = 'succeeded' AND attempt_count >= 1 "
            "AND operation_generation >= 1 AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND safe_error_code IS NULL "
            "AND last_transition IN ('begin', 'succeed', 'fail') "
            "AND route_disposition = 'routable_current' "
            "AND last_observed_tenant_uuid = tenant_id "
            "AND last_observed_database_uuid = database_uuid "
            "AND last_observed_schema_generation = target_schema_generation "
            "AND last_observed_schema_revision = target_schema_revision "
            "AND last_observed_schema_sha256 = target_schema_sha256 "
            "AND schema_operation_claim_uuid IS NOT NULL) OR "
            "(state = 'failed' AND attempt_count >= 1 "
            "AND operation_generation >= 1 AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND safe_error_code IS NOT NULL "
            "AND last_transition = 'fail' "
            "AND last_observed_tenant_uuid IS NOT NULL "
            "AND last_observed_schema_generation IS NOT NULL "
            "AND schema_operation_claim_uuid IS NOT NULL))",
            name=op.f(
                "ck_tenant_fleet_migrations_state_payload_complete"
            ),
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= queued_at",
            name=op.f(
                "ck_tenant_fleet_migrations_started_after_queue"
            ),
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR "
            "(started_at IS NOT NULL AND completed_at >= started_at)",
            name=op.f(
                "ck_tenant_fleet_migrations_completed_after_start"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "database_uuid"],
            [
                "tenant_databases.tenant_id",
                "tenant_databases.database_uuid",
            ],
            name="fk_fleet_migrations_route_identity",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "migration_uuid",
            name=op.f("pk_tenant_fleet_migrations"),
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "database_uuid",
            "target_schema_generation",
            name="uq_fleet_migrations_target_generation",
        ),
    )
    op.create_index(
        "ix_fleet_migrations_state_target",
        "tenant_fleet_migrations",
        ["state", "target_schema_generation", "tenant_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("tenant_fleet_migrations")

    with op.batch_alter_table(
        "database_identity_control_records",
        schema=None,
    ) as batch_op:
        batch_op.drop_constraint(
            op.f(
                "ck_database_identity_control_records_row_version_positive"
            ),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f(
                "ck_database_identity_control_records_observed_metadata_complete"
            ),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f(
                "ck_database_identity_control_records_expected_metadata_complete"
            ),
            type_="check",
        )
        batch_op.drop_column("row_version")
        batch_op.drop_column("observed_schema_sha256")
        batch_op.drop_column("observed_schema_revision")
        batch_op.drop_column("expected_schema_sha256")
        batch_op.drop_column("expected_schema_revision")
