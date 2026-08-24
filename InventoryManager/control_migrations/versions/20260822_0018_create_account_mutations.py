"""Create tenant database account-mutation leases and rotations."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp


revision = "202608220018"
down_revision = "202608220017"
branch_labels = None
depends_on = None


DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
LEASE_EXPIRY_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


def upgrade() -> None:
    op.create_table(
        "tenant_database_account_mutation_leases",
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("account_kind", sa.String(length=24), nullable=False),
        sa.Column(
            "fencing_token",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_purpose", sa.String(length=128), nullable=True),
        sa.Column(
            "lease_expires_at",
            LEASE_EXPIRY_TYPE,
            nullable=True,
        ),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            LEASE_EXPIRY_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            LEASE_EXPIRY_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "account_kind IN ('dml', 'platform_read')",
            name=op.f(
                "ck_tenant_database_account_mutation_leases_account_kind_valid"
            ),
        ),
        sa.CheckConstraint(
            "fencing_token >= 0",
            name=op.f(
                "ck_tenant_database_account_mutation_leases_fencing_nonnegative"
            ),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f(
                "ck_tenant_database_account_mutation_leases_row_version_positive"
            ),
        ),
        sa.CheckConstraint(
            "((lease_owner IS NULL AND lease_purpose IS NULL "
            "AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_purpose IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND fencing_token >= 1))",
            name=op.f(
                "ck_tenant_database_account_mutation_leases_ownership_complete"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "tenant_id",
            "account_kind",
            name=op.f("pk_tenant_database_account_mutation_leases"),
        ),
    )
    op.create_index(
        "ix_account_mutation_leases_expiry",
        "tenant_database_account_mutation_leases",
        ["account_kind", "lease_expires_at"],
        unique=False,
    )

    op.create_table(
        "tenant_database_account_rotations",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("rotation_id", sa.String(length=36), nullable=False),
        sa.Column("tenant_id", sa.String(length=36), nullable=False),
        sa.Column("database_uuid", sa.String(length=36), nullable=False),
        sa.Column("account_kind", sa.String(length=24), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("from_username", sa.String(length=128), nullable=False),
        sa.Column(
            "from_credential_generation", sa.BigInteger(), nullable=False
        ),
        sa.Column("from_root_key_version", sa.BigInteger(), nullable=False),
        sa.Column("from_derivation_version", sa.BigInteger(), nullable=False),
        sa.Column("to_username", sa.String(length=128), nullable=False),
        sa.Column(
            "to_credential_generation", sa.BigInteger(), nullable=False
        ),
        sa.Column("to_root_key_version", sa.BigInteger(), nullable=False),
        sa.Column("to_derivation_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "inherited_desired_login_state",
            sa.String(length=16),
            nullable=False,
        ),
        sa.Column(
            "expected_tenant_access_version",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("expected_route_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "expected_login_state_version", sa.BigInteger(), nullable=False
        ),
        sa.Column("lease_owner", sa.String(length=128), nullable=False),
        sa.Column("lease_purpose", sa.String(length=128), nullable=False),
        sa.Column("lease_fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("state", sa.String(length=24), nullable=False),
        sa.Column("candidate_locked", sa.Boolean(), nullable=False),
        sa.Column("candidate_published", sa.Boolean(), nullable=False),
        sa.Column("previous_locked", sa.Boolean(), nullable=False),
        sa.Column("previous_revoked", sa.Boolean(), nullable=False),
        sa.Column("transition_sequence", sa.BigInteger(), nullable=False),
        sa.Column("last_action", sa.String(length=32), nullable=False),
        sa.Column("last_request_digest", DIGEST_TYPE, nullable=False),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.Column(
            "row_version",
            sa.BigInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            LEASE_EXPIRY_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            LEASE_EXPIRY_TYPE,
            server_default=MicrosecondCurrentTimestamp(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "account_kind IN ('dml', 'platform_read')",
            name=op.f(
                "ck_tenant_database_account_rotations_account_kind_valid"
            ),
        ),
        sa.CheckConstraint(
            "purpose IN ('standard', 'root_key_rotation', "
            "'recovery_release', 'suspension_resolve', 'deletion_cancel')",
            name=op.f("ck_tenant_database_account_rotations_purpose_valid"),
        ),
        sa.CheckConstraint(
            "state IN ('preparing', 'prepared_locked', "
            "'candidate_testing', 'verified', 'switched', 'draining', "
            "'revoked', 'failed')",
            name=op.f("ck_tenant_database_account_rotations_state_valid"),
        ),
        sa.CheckConstraint(
            "inherited_desired_login_state IN ('active', 'locked')",
            name=op.f(
                "ck_tenant_database_account_rotations_desired_state_valid"
            ),
        ),
        sa.CheckConstraint(
            "last_action IN ('start', 'prepare_locked', "
            "'begin_candidate_testing', 'verify_candidate', "
            "'switch_candidate', 'begin_draining', "
            "'revoke_previous', 'fail')",
            name=op.f(
                "ck_tenant_database_account_rotations_last_action_valid"
            ),
        ),
        sa.CheckConstraint(
            "length(last_request_digest) = 32",
            name=op.f(
                "ck_tenant_database_account_rotations_request_digest_length"
            ),
        ),
        sa.CheckConstraint(
            "from_username <> to_username",
            name=op.f(
                "ck_tenant_database_account_rotations_usernames_distinct"
            ),
        ),
        sa.CheckConstraint(
            "from_credential_generation >= 1 AND "
            "to_credential_generation > from_credential_generation AND "
            "from_root_key_version >= 1 AND to_root_key_version >= 1 AND "
            "from_derivation_version >= 1 AND to_derivation_version >= 1",
            name=op.f(
                "ck_tenant_database_account_rotations_generation_lineage_valid"
            ),
        ),
        sa.CheckConstraint(
            "expected_tenant_access_version >= 1 AND "
            "expected_route_version >= 1 AND "
            "expected_login_state_version >= 1 AND "
            "lease_fencing_token >= 1",
            name=op.f(
                "ck_tenant_database_account_rotations_fences_positive"
            ),
        ),
        sa.CheckConstraint(
            "transition_sequence >= 1 AND row_version >= 1",
            name=op.f(
                "ck_tenant_database_account_rotations_row_versions_positive"
            ),
        ),
        sa.CheckConstraint(
            "((state IN ('preparing', 'prepared_locked') "
            "AND candidate_locked = 1 AND candidate_published = 0) OR "
            "(state IN ('candidate_testing', 'verified') "
            "AND candidate_locked = 0 AND candidate_published = 0 "
            "AND previous_locked = 1) OR "
            "(state IN ('switched', 'draining', 'revoked') "
            "AND candidate_locked = 0 AND candidate_published = 1 "
            "AND previous_locked = 1) OR "
            "(state = 'failed' AND candidate_locked = 1 "
            "AND previous_locked = 1))",
            name=op.f(
                "ck_tenant_database_account_rotations_state_facts_valid"
            ),
        ),
        sa.CheckConstraint(
            "((state = 'revoked' AND previous_revoked = 1) OR "
            "(state <> 'revoked' AND previous_revoked = 0))",
            name=op.f(
                "ck_tenant_database_account_rotations_revocation_fact_valid"
            ),
        ),
        sa.CheckConstraint(
            "((state = 'failed' AND safe_error_code IS NOT NULL) OR "
            "(state <> 'failed' AND safe_error_code IS NULL))",
            name=op.f(
                "ck_tenant_database_account_rotations_failure_fact_valid"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_tenant_database_account_rotations")
        ),
        sa.UniqueConstraint(
            "rotation_id",
            name="uq_account_rotations_rotation_id",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "account_kind",
            "to_credential_generation",
            name="uq_account_rotations_candidate_generation",
        ),
    )
    op.create_index(
        "ix_account_rotations_tenant_kind_state",
        "tenant_database_account_rotations",
        ["tenant_id", "account_kind", "state"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("tenant_database_account_rotations")
    op.drop_table("tenant_database_account_mutation_leases")
