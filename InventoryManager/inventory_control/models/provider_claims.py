"""Permanent global provider-account claims and append-only transitions."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from .base import ControlBase


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")


def _new_uuid() -> str:
    return str(uuid4())


class ProviderAccountClaim(ControlBase):
    """One permanent keyed-fingerprint row with one current owner triple."""

    __tablename__ = "provider_account_claims"
    __table_args__ = (
        sa.UniqueConstraint(
            "provider",
            "account_fingerprint",
            name="uq_provider_claims_provider_fingerprint",
        ),
        sa.CheckConstraint("provider = 'sf'", name="provider_sf"),
        sa.CheckConstraint(
            "length(account_fingerprint) = 32", name="fingerprint_length"
        ),
        sa.CheckConstraint(
            "fingerprint_version = 1", name="fingerprint_version_supported"
        ),
        sa.CheckConstraint(
            "fingerprint_root_key_version >= 1", name="fingerprint_key_positive"
        ),
        sa.CheckConstraint(
            "claim_status IN ('released', 'reserved', 'active')",
            name="status_valid",
        ),
        sa.CheckConstraint("claim_generation >= 1", name="generation_positive"),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint("event_sequence >= 0", name="event_sequence_nonnegative"),
        sa.CheckConstraint("length(event_head_hash) = 32", name="event_hash_length"),
        sa.CheckConstraint(
            "reservation_request_digest IS NULL OR "
            "length(reservation_request_digest) = 32",
            name="reservation_digest_length",
        ),
        sa.CheckConstraint(
            "last_request_digest IS NULL OR length(last_request_digest) = 32",
            name="last_digest_length",
        ),
        sa.CheckConstraint(
            "((last_action_uuid IS NULL AND last_request_digest IS NULL) OR "
            "(last_action_uuid IS NOT NULL AND last_request_digest IS NOT NULL))",
            name="last_action_complete",
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
            name="state_owner_fields_valid",
        ),
        sa.Index(
            "ix_provider_claims_current_owner",
            "current_tenant_id",
            "claim_status",
            "claim_generation",
        ),
    )

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    provider: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    account_fingerprint: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    fingerprint_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    fingerprint_root_key_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    current_provider_account_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    current_tenant_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    current_warehouse_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    claim_status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    claim_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    reservation_action_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    reservation_request_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    reservation_expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    active_binding_revision: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    last_action_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    last_request_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    last_transition_event_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    event_sequence: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )
    event_head_hash: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    row_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


class ProviderAccountClaimEvent(ControlBase):
    """Permanent technical snapshot for one monotonic claim generation."""

    __tablename__ = "provider_account_claim_events"
    __table_args__ = (
        sa.UniqueConstraint(
            "provider_account_claim_id",
            "claim_generation",
            name="uq_provider_claim_events_claim_generation",
        ),
        sa.ForeignKeyConstraint(
            ["provider_account_claim_id"],
            ["provider_account_claims.id"],
            name="fk_provider_claim_events_claim",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("claim_generation >= 2", name="generation_after_initial"),
        sa.CheckConstraint("event_sequence >= 1", name="event_sequence_positive"),
        sa.CheckConstraint(
            "from_status IN ('released', 'reserved', 'active')",
            name="from_status_valid",
        ),
        sa.CheckConstraint(
            "to_status IN ('released', 'reserved', 'active')",
            name="to_status_valid",
        ),
        sa.CheckConstraint(
            "actor_type IN ('tenant_admin', 'system_deletion', "
            "'system_reconciler')",
            name="actor_type_valid",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32", name="request_digest_length"
        ),
        sa.CheckConstraint(
            "length(transition_digest) = 32", name="transition_digest_length"
        ),
        sa.CheckConstraint(
            "length(previous_event_hash) = 32", name="previous_hash_length"
        ),
        sa.CheckConstraint("length(record_hash) = 32", name="record_hash_length"),
        sa.CheckConstraint(
            "tombstone_record_hash IS NULL OR length(tombstone_record_hash) = 32",
            name="tombstone_hash_length",
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
            name="actor_provenance_valid",
        ),
        sa.CheckConstraint(
            "((new_provider_account_id IS NULL "
            "AND new_tenant_id IS NULL "
            "AND new_warehouse_uuid IS NULL) OR "
            "(new_provider_account_id IS NOT NULL "
            "AND new_tenant_id IS NOT NULL "
            "AND new_warehouse_uuid IS NOT NULL))",
            name="new_owner_complete",
        ),
        sa.CheckConstraint(
            "((previous_provider_account_id IS NULL "
            "AND previous_tenant_id IS NULL "
            "AND previous_warehouse_uuid IS NULL) OR "
            "(previous_provider_account_id IS NOT NULL "
            "AND previous_tenant_id IS NOT NULL "
            "AND previous_warehouse_uuid IS NOT NULL))",
            name="previous_owner_complete",
        ),
    )

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    provider_account_claim_id: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    claim_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    event_sequence: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    from_status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    to_status: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    previous_provider_account_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    previous_tenant_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    previous_warehouse_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    new_provider_account_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    new_tenant_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    new_warehouse_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    actor_type: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    actor_user_uuid: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    actor_session_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    otp_challenge_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    source_action_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    request_digest: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    deletion_request_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    deletion_execution_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    tombstone_sequence: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    tombstone_record_hash: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    transition_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    previous_event_hash: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    record_hash: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    safe_reason_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    safe_outcome_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
