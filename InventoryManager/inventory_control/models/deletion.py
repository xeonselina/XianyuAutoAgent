"""Durable D26 tenant-deletion aggregates, work facts, and receipts.

Only :class:`TenantDeletionTombstone` is a permanent deletion ledger record.
It intentionally has no foreign key to a tenant, request, user, or database
route so later minimization cannot remove it or make a deleted UUID reusable.
The remaining rows are bounded control-plane workflow data and contain no
free-form customer or provider payloads.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from .base import ControlBase


def _new_uuid() -> str:
    return str(uuid4())


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")


class TenantDeletionRequest(ControlBase):
    """One persisted reducer aggregate plus its current executor lease."""

    __tablename__ = "tenant_deletion_requests"
    __table_args__ = (
        sa.UniqueConstraint(
            "active_tenant_id",
            name="uq_tenant_deletion_requests_active_tenant",
        ),
        sa.UniqueConstraint(
            "request_challenge_id",
            name="uq_tenant_deletion_requests_request_challenge",
        ),
        sa.UniqueConstraint(
            "cancel_challenge_id",
            name="uq_tenant_deletion_requests_cancel_challenge",
        ),
        sa.CheckConstraint(
            "status IN ('pending_review', 'rejected', 'cooling_off', "
            "'cancelled', 'committing', 'awaiting_offsite_ack', "
            "'releasing_claims', 'dropping', 'completed', 'failed')",
            name="status_valid",
        ),
        sa.CheckConstraint("request_revision >= 1", name="revision_positive"),
        sa.CheckConstraint(
            "execution_generation >= 1", name="generation_positive"
        ),
        sa.CheckConstraint(
            "executor_fencing_token >= 1", name="fencing_token_positive"
        ),
        sa.CheckConstraint(
            "committed_tenant_access_version >= 1",
            name="access_version_positive",
        ),
        sa.CheckConstraint(
            "published_dml_generation >= 1",
            name="published_dml_generation_positive",
        ),
        sa.CheckConstraint(
            "latest_dml_generation >= published_dml_generation",
            name="dml_generation_order_valid",
        ),
        sa.CheckConstraint(
            "candidate_dml_generation IS NULL OR "
            "candidate_dml_generation > latest_dml_generation",
            name="candidate_dml_generation_valid",
        ),
        sa.CheckConstraint(
            "desired_dml_login_state IN ('active', 'locked')",
            name="desired_dml_state_valid",
        ),
        sa.CheckConstraint(
            "pre_freeze_tenant_status IS NULL OR pre_freeze_tenant_status IN "
            "('active', 'expired', 'suspending', 'suspended', 'resuming')",
            name="pre_freeze_tenant_status_valid",
        ),
        sa.CheckConstraint(
            "pre_freeze_suspension_phase IS NULL OR "
            "pre_freeze_suspension_phase IN "
            "('freezing', 'active', 'failed', 'resolving')",
            name="pre_freeze_suspension_phase_valid",
        ),
        sa.CheckConstraint(
            "failure_resume_status IS NULL OR failure_resume_status IN "
            "('committing', 'awaiting_offsite_ack', 'releasing_claims', "
            "'dropping')",
            name="failure_resume_status_valid",
        ),
        sa.CheckConstraint(
            "((status = 'failed' AND failure_resume_status IS NOT NULL "
            "AND failure_code IS NOT NULL) OR "
            "(status <> 'failed' AND failure_resume_status IS NULL "
            "AND failure_code IS NULL))",
            name="failure_state_complete",
        ),
        sa.CheckConstraint(
            "execute_not_before IS NULL OR reviewed_at IS NOT NULL",
            name="cooling_time_has_review",
        ),
        sa.CheckConstraint(
            "((executor_lease_owner IS NULL "
            "AND executor_lease_token_digest IS NULL "
            "AND executor_lease_expires_at IS NULL "
            "AND executor_lease_recovery_run_id IS NULL) OR "
            "(executor_lease_owner IS NOT NULL "
            "AND executor_lease_token_digest IS NOT NULL "
            "AND executor_lease_expires_at IS NOT NULL "
            "AND executor_lease_recovery_run_id IS NOT NULL))",
            name="executor_lease_complete",
        ),
        sa.CheckConstraint(
            "executor_lease_token_digest IS NULL OR "
            "length(executor_lease_token_digest) = 32",
            name="executor_lease_digest_length",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.Index(
            "ix_tenant_deletion_requests_tenant_status",
            "tenant_id",
            "status",
            "request_revision",
        ),
        sa.Index(
            "ix_tenant_deletion_requests_executor_lease",
            "status",
            "executor_lease_expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    # Deliberately no tenant/database FK.  D26 explicitly removes those rows.
    tenant_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    database_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    active_tenant_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.Computed(
            "CASE WHEN status IN ('pending_review', 'cooling_off', "
            "'committing', 'awaiting_offsite_ack', 'releasing_claims', "
            "'dropping', 'failed') THEN tenant_id ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
    requested_by_user_id: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    request_challenge_id: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    status: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    request_revision: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    execution_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    executor_fencing_token: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    current_action_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    committed_tenant_access_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    desired_dml_login_state: Mapped[str] = mapped_column(
        sa.String(16), nullable=False
    )
    published_dml_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    latest_dml_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    candidate_dml_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    recovery_dispositions_required: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False
    )
    reviewed_by_platform_admin_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    cancelled_by_user_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    cancel_challenge_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    pre_freeze_tenant_status: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    pre_freeze_suspension_phase: Mapped[str | None] = mapped_column(
        sa.String(24), nullable=True
    )
    failure_resume_status: Mapped[str | None] = mapped_column(
        sa.String(24), nullable=True
    )
    failure_code: Mapped[str | None] = mapped_column(sa.String(96), nullable=True)
    executor_lease_owner: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    executor_lease_token_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    executor_lease_expires_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    executor_lease_recovery_run_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    requested_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    execute_not_before: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    cancelled_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
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


class TenantDeletionAction(ControlBase):
    """Stable authorization/idempotency identity for one reducer action."""

    __tablename__ = "tenant_deletion_actions"
    __table_args__ = (
        sa.UniqueConstraint(
            "deletion_request_id",
            "idempotency_key",
            name="uq_tenant_deletion_actions_request_idempotency",
        ),
        sa.CheckConstraint(
            "kind IN ('request', 'review_approve', 'review_reject', "
            "'cancel', 'commit')",
            name="kind_valid",
        ),
        sa.CheckConstraint(
            "outcome IN ('running', 'succeeded', 'failed')",
            name="outcome_valid",
        ),
        sa.CheckConstraint(
            "execution_generation >= 1", name="generation_positive"
        ),
        sa.CheckConstraint(
            "executor_fencing_token >= 1", name="fencing_token_positive"
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32", name="request_digest_length"
        ),
        sa.CheckConstraint(
            "((outcome = 'failed' AND failure_code IS NOT NULL) OR "
            "(outcome <> 'failed' AND failure_code IS NULL))",
            name="failure_outcome_complete",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.ForeignKeyConstraint(
            ["deletion_request_id"],
            ["tenant_deletion_requests.id"],
            name="fk_tenant_deletion_actions_request",
            ondelete="CASCADE",
        ),
        sa.Index(
            "ix_tenant_deletion_actions_request_kind",
            "deletion_request_id",
            "kind",
            "execution_generation",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    deletion_request_id: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    kind: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    execution_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    executor_fencing_token: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(191), nullable=False)
    request_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    outcome: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    failure_code: Mapped[str | None] = mapped_column(sa.String(96), nullable=True)
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )


class TenantDeletionEffect(ControlBase):
    """Durable, non-executing work fact emitted by the pure reducer."""

    __tablename__ = "tenant_deletion_effects"
    __table_args__ = (
        sa.UniqueConstraint(
            "deletion_request_id",
            "action_id",
            "execution_generation",
            "effect_kind",
            "tombstone_sequence",
            name="uq_tenant_deletion_effects_generation_kind",
        ),
        sa.CheckConstraint(
            "state IN ('pending', 'succeeded', 'failed', 'superseded')",
            name="state_valid",
        ),
        sa.CheckConstraint(
            "execution_generation >= 1", name="generation_positive"
        ),
        sa.CheckConstraint(
            "executor_fencing_token >= 1", name="fencing_token_positive"
        ),
        sa.CheckConstraint(
            "tenant_access_version >= 1", name="access_version_positive"
        ),
        sa.CheckConstraint(
            "dml_generation IS NULL OR dml_generation >= 1",
            name="dml_generation_positive",
        ),
        sa.CheckConstraint(
            "tombstone_sequence IS NULL OR tombstone_sequence >= 1",
            name="tombstone_sequence_positive",
        ),
        sa.CheckConstraint(
            "result_digest IS NULL OR length(result_digest) = 32",
            name="result_digest_length",
        ),
        sa.CheckConstraint(
            "((state = 'pending' AND completed_at IS NULL "
            "AND result_digest IS NULL AND safe_outcome_code IS NULL) OR "
            "(state <> 'pending' AND completed_at IS NOT NULL "
            "AND result_digest IS NOT NULL AND safe_outcome_code IS NOT NULL))",
            name="terminal_result_complete",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.ForeignKeyConstraint(
            ["deletion_request_id"],
            ["tenant_deletion_requests.id"],
            name="fk_tenant_deletion_effects_request",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["tenant_deletion_actions.id"],
            name="fk_tenant_deletion_effects_action",
            ondelete="CASCADE",
        ),
        sa.Index(
            "ix_tenant_deletion_effects_pending",
            "state",
            "effect_kind",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    deletion_request_id: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    action_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    effect_kind: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    execution_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    executor_fencing_token: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    tenant_access_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    dml_generation: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    tombstone_sequence: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    state: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'pending'")
    )
    result_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    safe_outcome_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class TenantDeletionEvidenceReceipt(ControlBase):
    """Bounded proof that a reducer barrier was verified by a trusted reader."""

    __tablename__ = "tenant_deletion_evidence_receipts"
    __table_args__ = (
        sa.UniqueConstraint(
            "deletion_request_id",
            "action_id",
            "execution_generation",
            "receipt_kind",
            name="uq_tenant_deletion_receipts_generation_kind",
        ),
        sa.CheckConstraint(
            "receipt_kind IN ('lockdown', 'cancellation', 'isolation', "
            "'executor_fence', 'offsite_ack', 'claim_release', "
            "'destructive_cleanup')",
            name="kind_valid",
        ),
        sa.CheckConstraint(
            "verifier_kind IN ('control_current_read', "
            "'nas_authenticated_ack', 'provider_claim_current_read', "
            "'destructive_current_read')",
            name="verifier_kind_valid",
        ),
        sa.CheckConstraint(
            "evidence_schema_version = 1", name="schema_version_supported"
        ),
        sa.CheckConstraint(
            "execution_generation >= 1", name="generation_positive"
        ),
        sa.CheckConstraint(
            "executor_fencing_token >= 1", name="fencing_token_positive"
        ),
        sa.CheckConstraint(
            "tenant_access_version >= 1", name="access_version_positive"
        ),
        sa.CheckConstraint(
            "length(evidence_digest) = 32", name="evidence_digest_length"
        ),
        sa.CheckConstraint(
            "tombstone_sequence IS NULL OR tombstone_sequence >= 1",
            name="tombstone_sequence_positive",
        ),
        sa.CheckConstraint(
            "tombstone_head_hash IS NULL OR length(tombstone_head_hash) = 32",
            name="tombstone_head_hash_length",
        ),
        sa.CheckConstraint(
            "recovery_disposition_digest IS NULL OR "
            "length(recovery_disposition_digest) = 32",
            name="recovery_disposition_digest_length",
        ),
        sa.CheckConstraint(
            "((recovery_run_id IS NULL AND recovery_hold_id IS NULL "
            "AND recovery_hold_revision IS NULL "
            "AND recovery_disposition_digest IS NULL) OR "
            "(recovery_run_id IS NOT NULL AND recovery_hold_id IS NOT NULL "
            "AND recovery_hold_revision IS NOT NULL "
            "AND recovery_hold_revision >= 1 "
            "AND recovery_disposition_digest IS NOT NULL))",
            name="recovery_disposition_anchor_complete",
        ),
        sa.ForeignKeyConstraint(
            ["deletion_request_id"],
            ["tenant_deletion_requests.id"],
            name="fk_tenant_deletion_receipts_request",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["action_id"],
            ["tenant_deletion_actions.id"],
            name="fk_tenant_deletion_receipts_action",
            ondelete="CASCADE",
        ),
        sa.Index(
            "ix_tenant_deletion_receipts_request_kind",
            "deletion_request_id",
            "receipt_kind",
            "verified_at",
        ),
    )

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    deletion_request_id: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    action_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    receipt_kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    verifier_kind: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    evidence_schema_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("1")
    )
    evidence_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    execution_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    executor_fencing_token: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    tenant_access_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    tombstone_sequence: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    tombstone_head_hash: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    recovery_run_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    recovery_hold_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    recovery_hold_revision: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    recovery_disposition_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    verified_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


class TenantDeletionTombstone(ControlBase):
    """Permanent, privacy-minimized restore-exclusion ledger entry."""

    __tablename__ = "tenant_deletion_tombstones"
    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_id", name="uq_tenant_deletion_tombstones_tenant"
        ),
        sa.UniqueConstraint(
            "database_uuid", name="uq_tenant_deletion_tombstones_database"
        ),
        sa.UniqueConstraint(
            "ledger_sequence", name="uq_tenant_deletion_tombstones_sequence"
        ),
        sa.CheckConstraint("ledger_sequence >= 1", name="sequence_positive"),
        sa.CheckConstraint(
            "previous_hash IS NULL OR length(previous_hash) = 32",
            name="previous_hash_length",
        ),
        sa.CheckConstraint("length(record_hash) = 32", name="record_hash_length"),
        sa.CheckConstraint("length(head_hash) = 32", name="head_hash_length"),
        sa.CheckConstraint(
            "checkpoint_root_key_version >= 1",
            name="checkpoint_key_version_positive",
        ),
        sa.CheckConstraint(
            "length(checkpoint_mac) = 32", name="checkpoint_mac_length"
        ),
        sa.CheckConstraint(
            "offsite_artifact_checksum IS NULL OR "
            "length(offsite_artifact_checksum) = 32",
            name="offsite_checksum_length",
        ),
        sa.CheckConstraint(
            "((offsite_acknowledged_at IS NULL "
            "AND offsite_artifact_checksum IS NULL "
            "AND offsite_authenticated = 0 "
            "AND offsite_durably_persisted = 0 "
            "AND offsite_checksum_verified = 0 "
            "AND offsite_chain_verified = 0) OR "
            "(offsite_acknowledged_at IS NOT NULL "
            "AND offsite_artifact_checksum IS NOT NULL "
            "AND offsite_authenticated = 1 "
            "AND offsite_durably_persisted = 1 "
            "AND offsite_checksum_verified = 1 "
            "AND offsite_chain_verified = 1))",
            name="offsite_ack_complete",
        ),
    )

    # request UUID is retained as an opaque deletion UUID, not an FK.
    deletion_request_id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True
    )
    tenant_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    database_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    ledger_sequence: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    previous_hash: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    record_hash: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    head_hash: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    checkpoint_root_key_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    checkpoint_mac: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    offsite_artifact_checksum: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    offsite_acknowledged_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    offsite_authenticated: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    offsite_durably_persisted: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    offsite_checksum_verified: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    offsite_chain_verified: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False, server_default=sa.false()
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )


__all__ = [
    "TenantDeletionAction",
    "TenantDeletionEffect",
    "TenantDeletionEvidenceReceipt",
    "TenantDeletionRequest",
    "TenantDeletionTombstone",
]
