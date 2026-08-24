"""Create the fleet-wide schema-operation fencing lease."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp


revision = "202608220020"
down_revision = "202608220019"
branch_labels = None
depends_on = None


SCHEMA_OPERATION_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)
SCHEMA_OPERATION_DIGEST_TYPE = sa.LargeBinary(32).with_variant(
    mysql.BINARY(32),
    "mysql",
)


def upgrade() -> None:
    op.create_table(
        "platform_schema_operation_leases",
        sa.Column("lease_key", sa.String(length=32), nullable=False),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column(
            "generation",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "fencing_token",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "observed_at",
            SCHEMA_OPERATION_TIMESTAMP_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column("owner_id", sa.String(length=128), nullable=True),
        sa.Column("claim_id", sa.String(length=36), nullable=True),
        sa.Column("purpose", sa.String(length=32), nullable=True),
        sa.Column(
            "acquired_at",
            SCHEMA_OPERATION_TIMESTAMP_TYPE,
            nullable=True,
        ),
        sa.Column(
            "expires_at",
            SCHEMA_OPERATION_TIMESTAMP_TYPE,
            nullable=True,
        ),
        sa.Column("last_claim_id", sa.String(length=36), nullable=True),
        sa.Column("last_effect", sa.String(length=16), nullable=True),
        sa.Column(
            "last_request_digest",
            SCHEMA_OPERATION_DIGEST_TYPE,
            nullable=True,
        ),
        sa.CheckConstraint(
            "lease_key = 'fleet_schema_operation'",
            name=op.f(
                "ck_platform_schema_operation_leases_scope_fixed"
            ),
        ),
        sa.CheckConstraint(
            "state IN ('available', 'held')",
            name=op.f(
                "ck_platform_schema_operation_leases_state_valid"
            ),
        ),
        sa.CheckConstraint(
            "purpose IS NULL OR purpose IN "
            "('provisioning', 'fleet_migration', 'backup', 'restore', "
            "'deletion', 'account_mutation')",
            name=op.f(
                "ck_platform_schema_operation_leases_purpose_valid"
            ),
        ),
        sa.CheckConstraint(
            "last_effect IS NULL OR last_effect IN "
            "('claimed', 'renewed', 'released')",
            name=op.f(
                "ck_platform_schema_operation_leases_last_effect_valid"
            ),
        ),
        sa.CheckConstraint(
            "generation >= 0 AND fencing_token >= 0 AND row_version >= 1",
            name=op.f(
                "ck_platform_schema_operation_leases_versions_valid"
            ),
        ),
        sa.CheckConstraint(
            "((last_effect IS NULL AND last_request_digest IS NULL) OR "
            "(last_effect IS NOT NULL AND last_request_digest IS NOT NULL "
            "AND length(last_request_digest) = 32))",
            name=op.f(
                "ck_platform_schema_operation_leases_request_replay_complete"
            ),
        ),
        sa.CheckConstraint(
            "((generation = 0 AND fencing_token = 0 "
            "AND last_claim_id IS NULL AND last_effect IS NULL) OR "
            "(generation >= 1 AND fencing_token >= 1 "
            "AND last_claim_id IS NOT NULL AND last_effect IS NOT NULL))",
            name=op.f(
                "ck_platform_schema_operation_leases_generation_lineage_complete"
            ),
        ),
        sa.CheckConstraint(
            "((state = 'available' AND owner_id IS NULL AND claim_id IS NULL "
            "AND purpose IS NULL AND acquired_at IS NULL AND expires_at IS NULL "
            "AND (generation = 0 OR last_effect = 'released')) OR "
            "(state = 'held' AND owner_id IS NOT NULL AND claim_id IS NOT NULL "
            "AND purpose IS NOT NULL AND acquired_at IS NOT NULL "
            "AND expires_at IS NOT NULL AND last_claim_id = claim_id "
            "AND last_effect IN ('claimed', 'renewed'))) ",
            name=op.f(
                "ck_platform_schema_operation_leases_state_complete"
            ),
        ),
        sa.CheckConstraint(
            "acquired_at IS NULL OR expires_at > acquired_at",
            name=op.f(
                "ck_platform_schema_operation_leases_window_valid"
            ),
        ),
        sa.CheckConstraint(
            "state <> 'held' OR "
            "(observed_at >= acquired_at AND observed_at < expires_at)",
            name=op.f(
                "ck_platform_schema_operation_leases_observation_in_window"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "lease_key",
            name=op.f("pk_platform_schema_operation_leases"),
        ),
    )
    lease_table = sa.table(
        "platform_schema_operation_leases",
        sa.column("lease_key", sa.String(length=32)),
        sa.column("state", sa.String(length=16)),
        sa.column("generation", sa.BigInteger()),
        sa.column("fencing_token", sa.BigInteger()),
        sa.column("row_version", sa.BigInteger()),
    )
    op.bulk_insert(
        lease_table,
        [
            {
                "lease_key": "fleet_schema_operation",
                "state": "available",
                "generation": 0,
                "fencing_token": 0,
                "row_version": 1,
            }
        ],
    )


def downgrade() -> None:
    op.drop_table("platform_schema_operation_leases")
