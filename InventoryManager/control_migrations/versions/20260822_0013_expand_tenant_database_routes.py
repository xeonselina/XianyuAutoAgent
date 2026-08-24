"""Expand tenant routes with purpose-separated published account metadata.

Revision ID: 202608220013
Revises: 202608220012
Create Date: 2026-08-22
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "202608220013"
down_revision = "202608220012"
branch_labels = None
depends_on = None


_ACTIVATION_ANCHOR_CHECK = (
    "((activated_by_registration_commit_uuid IS NULL "
    "AND activation_route_version IS NULL "
    "AND activation_credential_generation IS NULL) OR "
    "(activated_by_registration_commit_uuid IS NOT NULL "
    "AND activation_route_version IS NOT NULL "
    "AND activation_route_version >= 1 "
    "AND activation_credential_generation IS NOT NULL "
    "AND activation_credential_generation >= 1))"
)

_VERSION_FIELDS_CHECK = (
    "(dml_credential_generation IS NULL OR dml_credential_generation >= 1) AND "
    "(dml_root_key_version IS NULL OR dml_root_key_version >= 1) AND "
    "(dml_derivation_version IS NULL OR dml_derivation_version >= 1) AND "
    "(dml_login_state_version IS NULL OR dml_login_state_version >= 1) AND "
    "(platform_read_credential_generation IS NULL OR "
    "platform_read_credential_generation >= 1) AND "
    "(platform_read_root_key_version IS NULL OR "
    "platform_read_root_key_version >= 1) AND "
    "(platform_read_derivation_version IS NULL OR "
    "platform_read_derivation_version >= 1) AND "
    "(platform_read_route_version IS NULL OR platform_read_route_version >= 1)"
)

_LOGIN_STATES_CHECK = (
    "(dml_desired_login_state IS NULL OR "
    "dml_desired_login_state IN ('active', 'locked')) AND "
    "(dml_observed_login_state IS NULL OR "
    "dml_observed_login_state IN ('active', 'locked'))"
)

_READY_METADATA_CHECK = (
    "status <> 'ready' OR ("
    "schema_version IS NOT NULL AND length(trim(schema_version)) > 0 "
    "AND activated_by_registration_commit_uuid IS NOT NULL "
    "AND activation_route_version IS NOT NULL "
    "AND activation_route_version >= 1 "
    "AND activation_credential_generation IS NOT NULL "
    "AND activation_credential_generation >= 1 "
    "AND dml_username IS NOT NULL "
    "AND length(trim(dml_username)) > 0 "
    "AND dml_credential_generation IS NOT NULL "
    "AND dml_credential_generation >= 1 "
    "AND dml_root_key_version IS NOT NULL "
    "AND dml_root_key_version >= 1 "
    "AND dml_derivation_version IS NOT NULL "
    "AND dml_derivation_version >= 1 "
    "AND dml_desired_login_state IS NOT NULL "
    "AND dml_observed_login_state IS NOT NULL "
    "AND dml_login_state_version IS NOT NULL "
    "AND dml_login_state_version >= 1 "
    "AND platform_read_username IS NOT NULL "
    "AND length(trim(platform_read_username)) > 0 "
    "AND platform_read_credential_generation IS NOT NULL "
    "AND platform_read_credential_generation >= 1 "
    "AND platform_read_root_key_version IS NOT NULL "
    "AND platform_read_root_key_version >= 1 "
    "AND platform_read_derivation_version IS NOT NULL "
    "AND platform_read_derivation_version >= 1 "
    "AND platform_read_route_version IS NOT NULL "
    "AND platform_read_route_version >= 1)"
)


def upgrade() -> None:
    with op.batch_alter_table("tenant_databases", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column(
                "activated_by_registration_commit_uuid",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("activation_route_version", sa.BigInteger(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "activation_credential_generation",
                sa.BigInteger(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("dml_username", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(
            sa.Column("dml_credential_generation", sa.BigInteger(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("dml_root_key_version", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("dml_derivation_version", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("dml_desired_login_state", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(
            sa.Column("dml_observed_login_state", sa.String(length=16), nullable=True)
        )
        batch_op.add_column(
            sa.Column("dml_login_state_version", sa.BigInteger(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "dml_desired_state_recovery_run_id",
                sa.String(length=36),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("platform_read_username", sa.String(length=128), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "platform_read_credential_generation",
                sa.BigInteger(),
                nullable=True,
            )
        )
        batch_op.add_column(
            sa.Column("platform_read_root_key_version", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("platform_read_derivation_version", sa.Integer(), nullable=True)
        )
        batch_op.add_column(
            sa.Column("platform_read_route_version", sa.BigInteger(), nullable=True)
        )
        batch_op.add_column(
            sa.Column(
                "row_version",
                sa.BigInteger(),
                server_default=sa.text("1"),
                nullable=False,
            )
        )
        batch_op.create_foreign_key(
            "fk_tenant_databases_dml_recovery_run",
            "disaster_recovery_runs",
            ["dml_desired_state_recovery_run_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        batch_op.create_check_constraint(
            "ck_tenant_databases_row_version_positive",
            "row_version >= 1",
        )
        batch_op.create_check_constraint(
            "ck_tenant_databases_activation_anchor_complete",
            _ACTIVATION_ANCHOR_CHECK,
        )
        batch_op.create_check_constraint(
            "ck_tenant_databases_version_fields_positive",
            _VERSION_FIELDS_CHECK,
        )
        batch_op.create_check_constraint(
            "ck_tenant_databases_login_states_valid",
            _LOGIN_STATES_CHECK,
        )
        batch_op.create_check_constraint(
            "ck_tenant_databases_ready_metadata_complete",
            _READY_METADATA_CHECK,
        )


def downgrade() -> None:
    with op.batch_alter_table("tenant_databases", schema=None) as batch_op:
        batch_op.drop_constraint(
            op.f("ck_tenant_databases_ready_metadata_complete"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_tenant_databases_login_states_valid"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_tenant_databases_version_fields_positive"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_tenant_databases_activation_anchor_complete"),
            type_="check",
        )
        batch_op.drop_constraint(
            op.f("ck_tenant_databases_row_version_positive"),
            type_="check",
        )
        batch_op.drop_constraint(
            "fk_tenant_databases_dml_recovery_run",
            type_="foreignkey",
        )
        batch_op.drop_column("row_version")
        batch_op.drop_column("platform_read_route_version")
        batch_op.drop_column("platform_read_derivation_version")
        batch_op.drop_column("platform_read_root_key_version")
        batch_op.drop_column("platform_read_credential_generation")
        batch_op.drop_column("platform_read_username")
        batch_op.drop_column("dml_desired_state_recovery_run_id")
        batch_op.drop_column("dml_login_state_version")
        batch_op.drop_column("dml_observed_login_state")
        batch_op.drop_column("dml_desired_login_state")
        batch_op.drop_column("dml_derivation_version")
        batch_op.drop_column("dml_root_key_version")
        batch_op.drop_column("dml_credential_generation")
        batch_op.drop_column("dml_username")
        batch_op.drop_column("activation_credential_generation")
        batch_op.drop_column("activation_route_version")
        batch_op.drop_column("activated_by_registration_commit_uuid")
