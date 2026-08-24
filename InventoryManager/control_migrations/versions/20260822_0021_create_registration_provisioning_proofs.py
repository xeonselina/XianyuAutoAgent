"""Create immutable registration provisioning outcome proofs.

Revision ID: 202608220021
Revises: 202608220020
Create Date: 2026-08-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220021"
down_revision = "202608220020"
branch_labels = None
depends_on = None


PROOF_DIGEST = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
PROOF_TIMESTAMP = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


def upgrade() -> None:
    op.create_table(
        "tenant_registration_provisioning_proofs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("attempt_uuid", sa.String(length=36), nullable=False),
        sa.Column("user_uuid", sa.String(length=36), nullable=False),
        sa.Column("tenant_uuid", sa.String(length=36), nullable=False),
        sa.Column("database_uuid", sa.String(length=36), nullable=False),
        sa.Column("recovery_run_uuid", sa.String(length=36), nullable=False),
        sa.Column(
            "provisioning_execution_generation",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column(
            "expected_attempt_row_version",
            sa.BigInteger(),
            nullable=False,
        ),
        sa.Column("worker_lease_owner", sa.String(length=128), nullable=False),
        sa.Column("worker_lease_token_digest", PROOF_DIGEST, nullable=False),
        sa.Column(
            "worker_lease_expires_at",
            PROOF_TIMESTAMP,
            nullable=False,
        ),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("safe_error_code", sa.String(length=64), nullable=True),
        sa.Column("result_request_digest", PROOF_DIGEST, nullable=False),
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
        sa.Column("schema_generation", sa.BigInteger(), nullable=True),
        sa.Column("schema_digest", PROOF_DIGEST, nullable=True),
        sa.Column("database_identity_digest", PROOF_DIGEST, nullable=True),
        sa.Column("route_version", sa.BigInteger(), nullable=True),
        sa.Column(
            "initial_credential_generation",
            sa.BigInteger(),
            nullable=True,
        ),
        sa.Column("dml_login_state_version", sa.BigInteger(), nullable=True),
        sa.Column(
            "default_warehouse_uuid",
            sa.String(length=36),
            nullable=True,
        ),
        sa.Column("default_warehouse_digest", PROOF_DIGEST, nullable=True),
        sa.Column("smoke_proof_digest", PROOF_DIGEST, nullable=True),
        sa.Column("advisory_lock_proof_digest", PROOF_DIGEST, nullable=True),
        sa.Column("proof_policy_version", sa.Integer(), nullable=False),
        sa.Column("recorded_at", PROOF_TIMESTAMP, nullable=False),
        sa.CheckConstraint(
            "outcome IN ('ready', 'failed')",
            name=op.f(
                "ck_tenant_registration_provisioning_proofs_outcome_valid"
            ),
        ),
        sa.CheckConstraint(
            "provisioning_execution_generation >= 1 "
            "AND expected_attempt_row_version >= 1 "
            "AND proof_policy_version >= 1",
            name=op.f(
                "ck_tenant_registration_provisioning_proofs_versions_positive"
            ),
        ),
        sa.CheckConstraint(
            "length(worker_lease_token_digest) = 32 "
            "AND length(result_request_digest) = 32",
            name=op.f(
                "ck_tenant_registration_provisioning_proofs_worker_and_request_digests_valid"
            ),
        ),
        sa.CheckConstraint(
            "worker_lease_expires_at > recorded_at",
            name=op.f(
                "ck_tenant_registration_provisioning_proofs_worker_lease_window_valid"
            ),
        ),
        sa.CheckConstraint(
            "((outcome = 'ready' AND safe_error_code IS NULL "
            "AND schema_operation_claim_uuid IS NOT NULL "
            "AND schema_operation_owner_id IS NOT NULL "
            "AND schema_operation_generation IS NOT NULL "
            "AND schema_operation_fencing_token IS NOT NULL "
            "AND schema_operation_row_version IS NOT NULL "
            "AND schema_generation IS NOT NULL "
            "AND schema_digest IS NOT NULL AND length(schema_digest) = 32 "
            "AND database_identity_digest IS NOT NULL "
            "AND length(database_identity_digest) = 32 "
            "AND route_version IS NOT NULL "
            "AND initial_credential_generation IS NOT NULL "
            "AND dml_login_state_version IS NOT NULL "
            "AND default_warehouse_uuid IS NOT NULL "
            "AND default_warehouse_digest IS NOT NULL "
            "AND length(default_warehouse_digest) = 32 "
            "AND smoke_proof_digest IS NOT NULL "
            "AND length(smoke_proof_digest) = 32 "
            "AND advisory_lock_proof_digest IS NOT NULL "
            "AND length(advisory_lock_proof_digest) = 32) OR "
            "(outcome = 'failed' AND safe_error_code IS NOT NULL "
            "AND schema_operation_claim_uuid IS NULL "
            "AND schema_operation_owner_id IS NULL "
            "AND schema_operation_generation IS NULL "
            "AND schema_operation_fencing_token IS NULL "
            "AND schema_operation_row_version IS NULL "
            "AND schema_generation IS NULL AND schema_digest IS NULL "
            "AND database_identity_digest IS NULL "
            "AND route_version IS NULL "
            "AND initial_credential_generation IS NULL "
            "AND dml_login_state_version IS NULL "
            "AND default_warehouse_uuid IS NULL "
            "AND default_warehouse_digest IS NULL "
            "AND smoke_proof_digest IS NULL "
            "AND advisory_lock_proof_digest IS NULL))",
            name=op.f(
                "ck_tenant_registration_provisioning_proofs_outcome_payload_complete"
            ),
        ),
        sa.CheckConstraint(
            "schema_operation_generation IS NULL OR "
            "(schema_operation_generation >= 1 "
            "AND schema_operation_fencing_token >= 1 "
            "AND schema_operation_row_version >= 1 "
            "AND schema_generation >= 1 "
            "AND route_version >= 1 "
            "AND initial_credential_generation >= 1 "
            "AND dml_login_state_version >= 1)",
            name=op.f(
                "ck_tenant_registration_provisioning_proofs_ready_versions_positive"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["attempt_uuid"],
            ["tenant_registration_attempts.id"],
            name=op.f("fk_registration_proof_attempt"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id",
            name=op.f("pk_tenant_registration_provisioning_proofs"),
        ),
        sa.UniqueConstraint(
            "attempt_uuid",
            "provisioning_execution_generation",
            "worker_lease_token_digest",
            name=op.f("uq_registration_proof_worker_fence"),
        ),
    )
    op.create_index(
        "ix_registration_proofs_attempt_outcome",
        "tenant_registration_provisioning_proofs",
        ["attempt_uuid", "outcome", "provisioning_execution_generation"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("tenant_registration_provisioning_proofs")
