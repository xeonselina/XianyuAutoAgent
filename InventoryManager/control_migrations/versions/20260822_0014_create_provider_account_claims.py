"""Create permanent provider-account claims and transition events."""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql


revision = "202608220014"
down_revision = "202608220013"
branch_labels = None
depends_on = None


DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")


def upgrade() -> None:
    op.create_table(
        "provider_account_claims",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider", sa.String(length=16), nullable=False),
        sa.Column("account_fingerprint", DIGEST_TYPE, nullable=False),
        sa.Column("fingerprint_version", sa.Integer(), nullable=False),
        sa.Column(
            "fingerprint_root_key_version", sa.BigInteger(), nullable=False
        ),
        sa.Column("current_provider_account_id", sa.String(length=36), nullable=True),
        sa.Column("current_tenant_id", sa.String(length=36), nullable=True),
        sa.Column("current_warehouse_uuid", sa.String(length=36), nullable=True),
        sa.Column("claim_status", sa.String(length=16), nullable=False),
        sa.Column("claim_generation", sa.BigInteger(), nullable=False),
        sa.Column("reservation_action_uuid", sa.String(length=36), nullable=True),
        sa.Column("reservation_request_digest", DIGEST_TYPE, nullable=True),
        sa.Column(
            "reservation_expires_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("active_binding_revision", sa.BigInteger(), nullable=True),
        sa.Column("last_action_uuid", sa.String(length=36), nullable=True),
        sa.Column("last_request_digest", DIGEST_TYPE, nullable=True),
        sa.Column("last_transition_event_id", sa.String(length=36), nullable=True),
        sa.Column(
            "event_sequence",
            sa.BigInteger(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("event_head_hash", DIGEST_TYPE, nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "provider = 'sf'", name=op.f("ck_provider_account_claims_provider_sf")
        ),
        sa.CheckConstraint(
            "length(account_fingerprint) = 32",
            name=op.f("ck_provider_account_claims_fingerprint_length"),
        ),
        sa.CheckConstraint(
            "fingerprint_version = 1",
            name=op.f("ck_provider_account_claims_fingerprint_version_supported"),
        ),
        sa.CheckConstraint(
            "fingerprint_root_key_version >= 1",
            name=op.f("ck_provider_account_claims_fingerprint_key_positive"),
        ),
        sa.CheckConstraint(
            "claim_status IN ('released', 'reserved', 'active')",
            name=op.f("ck_provider_account_claims_status_valid"),
        ),
        sa.CheckConstraint(
            "claim_generation >= 1",
            name=op.f("ck_provider_account_claims_generation_positive"),
        ),
        sa.CheckConstraint(
            "row_version >= 1",
            name=op.f("ck_provider_account_claims_row_version_positive"),
        ),
        sa.CheckConstraint(
            "event_sequence >= 0",
            name=op.f("ck_provider_account_claims_event_sequence_nonnegative"),
        ),
        sa.CheckConstraint(
            "length(event_head_hash) = 32",
            name=op.f("ck_provider_account_claims_event_hash_length"),
        ),
        sa.CheckConstraint(
            "reservation_request_digest IS NULL OR "
            "length(reservation_request_digest) = 32",
            name=op.f("ck_provider_account_claims_reservation_digest_length"),
        ),
        sa.CheckConstraint(
            "last_request_digest IS NULL OR length(last_request_digest) = 32",
            name=op.f("ck_provider_account_claims_last_digest_length"),
        ),
        sa.CheckConstraint(
            "((last_action_uuid IS NULL AND last_request_digest IS NULL) OR "
            "(last_action_uuid IS NOT NULL AND last_request_digest IS NOT NULL))",
            name=op.f("ck_provider_account_claims_last_action_complete"),
        ),
        sa.CheckConstraint(
            "((claim_status = 'released' "
            "AND current_provider_account_id IS NULL "
            "AND current_tenant_id IS NULL "
            "AND current_warehouse_uuid IS NULL "
            "AND reservation_action_uuid IS NULL "
            "AND reservation_request_digest IS NULL "
            "AND reservation_expires_at IS NULL "
            "AND active_binding_revision IS NULL) OR "
            "(claim_status = 'reserved' "
            "AND current_provider_account_id IS NOT NULL "
            "AND current_tenant_id IS NOT NULL "
            "AND current_warehouse_uuid IS NOT NULL "
            "AND reservation_action_uuid IS NOT NULL "
            "AND reservation_request_digest IS NOT NULL "
            "AND reservation_expires_at IS NOT NULL "
            "AND active_binding_revision IS NULL) OR "
            "(claim_status = 'active' "
            "AND current_provider_account_id IS NOT NULL "
            "AND current_tenant_id IS NOT NULL "
            "AND current_warehouse_uuid IS NOT NULL "
            "AND reservation_action_uuid IS NULL "
            "AND reservation_request_digest IS NULL "
            "AND reservation_expires_at IS NULL "
            "AND active_binding_revision IS NOT NULL "
            "AND active_binding_revision >= 1))",
            name=op.f("ck_provider_account_claims_state_owner_fields_valid"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_provider_account_claims")),
        sa.UniqueConstraint(
            "provider",
            "account_fingerprint",
            name=op.f("uq_provider_claims_provider_fingerprint"),
        ),
    )
    op.create_index(
        "ix_provider_claims_current_owner",
        "provider_account_claims",
        ["current_tenant_id", "claim_status", "claim_generation"],
        unique=False,
    )

    op.create_table(
        "provider_account_claim_events",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("provider_account_claim_id", sa.String(length=36), nullable=False),
        sa.Column("claim_generation", sa.BigInteger(), nullable=False),
        sa.Column("event_sequence", sa.BigInteger(), nullable=False),
        sa.Column("from_status", sa.String(length=16), nullable=False),
        sa.Column("to_status", sa.String(length=16), nullable=False),
        sa.Column("previous_provider_account_id", sa.String(length=36), nullable=True),
        sa.Column("previous_tenant_id", sa.String(length=36), nullable=True),
        sa.Column("previous_warehouse_uuid", sa.String(length=36), nullable=True),
        sa.Column("new_provider_account_id", sa.String(length=36), nullable=True),
        sa.Column("new_tenant_id", sa.String(length=36), nullable=True),
        sa.Column("new_warehouse_uuid", sa.String(length=36), nullable=True),
        sa.Column("actor_type", sa.String(length=24), nullable=False),
        sa.Column("actor_user_uuid", sa.String(length=36), nullable=True),
        sa.Column("actor_session_uuid", sa.String(length=36), nullable=True),
        sa.Column("otp_challenge_uuid", sa.String(length=36), nullable=True),
        sa.Column("source_action_uuid", sa.String(length=36), nullable=False),
        sa.Column("request_digest", DIGEST_TYPE, nullable=False),
        sa.Column("deletion_request_uuid", sa.String(length=36), nullable=True),
        sa.Column("deletion_execution_generation", sa.BigInteger(), nullable=True),
        sa.Column("tombstone_sequence", sa.BigInteger(), nullable=True),
        sa.Column("tombstone_record_hash", DIGEST_TYPE, nullable=True),
        sa.Column("transition_digest", DIGEST_TYPE, nullable=False),
        sa.Column("previous_event_hash", DIGEST_TYPE, nullable=False),
        sa.Column("record_hash", DIGEST_TYPE, nullable=False),
        sa.Column("safe_reason_code", sa.String(length=64), nullable=False),
        sa.Column("safe_outcome_code", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "claim_generation >= 2",
            name=op.f("ck_provider_account_claim_events_generation_after_initial"),
        ),
        sa.CheckConstraint(
            "event_sequence >= 1",
            name=op.f("ck_provider_account_claim_events_event_sequence_positive"),
        ),
        sa.CheckConstraint(
            "from_status IN ('released', 'reserved', 'active')",
            name=op.f("ck_provider_account_claim_events_from_status_valid"),
        ),
        sa.CheckConstraint(
            "to_status IN ('released', 'reserved', 'active')",
            name=op.f("ck_provider_account_claim_events_to_status_valid"),
        ),
        sa.CheckConstraint(
            "actor_type IN ('tenant_admin', 'system_deletion', "
            "'system_reconciler')",
            name=op.f("ck_provider_account_claim_events_actor_type_valid"),
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32",
            name=op.f("ck_provider_account_claim_events_request_digest_length"),
        ),
        sa.CheckConstraint(
            "length(transition_digest) = 32",
            name=op.f("ck_provider_account_claim_events_transition_digest_length"),
        ),
        sa.CheckConstraint(
            "length(previous_event_hash) = 32",
            name=op.f("ck_provider_account_claim_events_previous_hash_length"),
        ),
        sa.CheckConstraint(
            "length(record_hash) = 32",
            name=op.f("ck_provider_account_claim_events_record_hash_length"),
        ),
        sa.CheckConstraint(
            "tombstone_record_hash IS NULL OR length(tombstone_record_hash) = 32",
            name=op.f("ck_provider_account_claim_events_tombstone_hash_length"),
        ),
        sa.CheckConstraint(
            "((actor_type = 'tenant_admin' "
            "AND actor_user_uuid IS NOT NULL "
            "AND actor_session_uuid IS NOT NULL "
            "AND otp_challenge_uuid IS NOT NULL "
            "AND deletion_request_uuid IS NULL "
            "AND deletion_execution_generation IS NULL "
            "AND tombstone_sequence IS NULL "
            "AND tombstone_record_hash IS NULL) OR "
            "(actor_type = 'system_deletion' "
            "AND actor_user_uuid IS NULL "
            "AND actor_session_uuid IS NULL "
            "AND otp_challenge_uuid IS NULL "
            "AND deletion_request_uuid IS NOT NULL "
            "AND deletion_execution_generation IS NOT NULL "
            "AND deletion_execution_generation >= 1 "
            "AND tombstone_sequence IS NOT NULL "
            "AND tombstone_sequence >= 1 "
            "AND tombstone_record_hash IS NOT NULL) OR "
            "(actor_type = 'system_reconciler' "
            "AND actor_user_uuid IS NULL "
            "AND actor_session_uuid IS NULL "
            "AND otp_challenge_uuid IS NULL))",
            name=op.f("ck_provider_account_claim_events_actor_provenance_valid"),
        ),
        sa.CheckConstraint(
            "((new_provider_account_id IS NULL "
            "AND new_tenant_id IS NULL "
            "AND new_warehouse_uuid IS NULL) OR "
            "(new_provider_account_id IS NOT NULL "
            "AND new_tenant_id IS NOT NULL "
            "AND new_warehouse_uuid IS NOT NULL))",
            name=op.f("ck_provider_account_claim_events_new_owner_complete"),
        ),
        sa.CheckConstraint(
            "((previous_provider_account_id IS NULL "
            "AND previous_tenant_id IS NULL "
            "AND previous_warehouse_uuid IS NULL) OR "
            "(previous_provider_account_id IS NOT NULL "
            "AND previous_tenant_id IS NOT NULL "
            "AND previous_warehouse_uuid IS NOT NULL))",
            name=op.f("ck_provider_account_claim_events_previous_owner_complete"),
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_claim_id"],
            ["provider_account_claims.id"],
            name=op.f("fk_provider_claim_events_claim"),
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "id", name=op.f("pk_provider_account_claim_events")
        ),
        sa.UniqueConstraint(
            "provider_account_claim_id",
            "claim_generation",
            name=op.f("uq_provider_claim_events_claim_generation"),
        ),
    )


def downgrade() -> None:
    op.drop_table("provider_account_claim_events")
    op.drop_table("provider_account_claims")
