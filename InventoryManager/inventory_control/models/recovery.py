"""Host-recovery epoch, per-tenant hold, and release-action records.

The recovery overlay is intentionally independent from ``Tenant.status``.
Rows retain only immutable technical identifiers and bounded evidence so a
later tenant deletion can preserve recovery coverage without retaining PII.
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


class DisasterRecoveryRun(ControlBase):
    """One authoritative installation or host-restore recovery epoch."""

    __tablename__ = "disaster_recovery_runs"
    __table_args__ = (
        sa.UniqueConstraint(
            "current_run_marker",
            name="uq_disaster_recovery_runs_current_marker",
        ),
        sa.CheckConstraint(
            "kind IN ('initial_baseline', 'host_restore')",
            name="kind_valid",
        ),
        sa.CheckConstraint(
            "status IN ('installing', 'reviewing', 'completed', "
            "'failed_closed', 'superseded')",
            name="status_valid",
        ),
        sa.CheckConstraint("policy_version >= 1", name="policy_version_positive"),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "expected_survivor_count >= 0",
            name="expected_survivor_count_nonnegative",
        ),
        sa.CheckConstraint(
            "actual_survivor_count >= 0",
            name="actual_survivor_count_nonnegative",
        ),
        sa.CheckConstraint(
            "source_manifest_digest IS NULL OR "
            "length(source_manifest_digest) = 32",
            name="source_manifest_digest_length",
        ),
        sa.CheckConstraint(
            "sealed_coverage_digest IS NULL OR "
            "length(sealed_coverage_digest) = 32",
            name="sealed_coverage_digest_length",
        ),
        sa.CheckConstraint(
            "final_coverage_digest IS NULL OR "
            "length(final_coverage_digest) = 32",
            name="final_coverage_digest_length",
        ),
        sa.CheckConstraint(
            "applied_tombstone_head_digest IS NULL OR "
            "length(applied_tombstone_head_digest) = 32",
            name="tombstone_head_digest_length",
        ),
        sa.CheckConstraint(
            "length(host_installation_fingerprint) = 64",
            name="host_fingerprint_length",
        ),
        sa.CheckConstraint(
            "length(deployment_marker_fingerprint) = 64",
            name="marker_fingerprint_length",
        ),
        sa.CheckConstraint(
            "status NOT IN ('reviewing', 'completed') OR reviewing_at IS NOT NULL",
            name="reviewing_status_has_time",
        ),
        sa.CheckConstraint(
            "status <> 'completed' OR completed_at IS NOT NULL",
            name="completed_status_has_time",
        ),
        sa.CheckConstraint(
            "status <> 'superseded' OR superseded_at IS NOT NULL",
            name="superseded_status_has_time",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    kind: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    source_manifest_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    source_snapshot_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    applied_tombstone_head_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    policy_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    current_run_marker: Mapped[str | None] = mapped_column(
        sa.String(16),
        sa.Computed(
            "CASE WHEN status = 'superseded' THEN NULL ELSE 'current' END",
            persisted=True,
        ),
        nullable=True,
    )
    expected_survivor_count: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )
    actual_survivor_count: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )
    sealed_coverage_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    final_coverage_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    accepted_smoke_evidence_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    host_installation_fingerprint: Mapped[str] = mapped_column(
        sa.String(64), nullable=False
    )
    deployment_marker_fingerprint: Mapped[str] = mapped_column(
        sa.String(64), nullable=False
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    started_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    reviewing_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
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


class TenantRecoveryHold(ControlBase):
    """The independent D58 overlay for one tenant in one recovery run."""

    __tablename__ = "tenant_recovery_holds"
    __table_args__ = (
        sa.UniqueConstraint(
            "recovery_run_id",
            "tenant_id",
            name="uq_tenant_recovery_holds_run_tenant",
        ),
        sa.CheckConstraint(
            "state IN ('held', 'reviewing', 'released', 'kept_closed', "
            "'tombstoned')",
            name="state_valid",
        ),
        sa.CheckConstraint(
            "snapshot_underlying_status IN ('provisioning', 'active', 'expired', "
            "'suspending', 'suspended', 'resuming', 'deletion_cooling_off', "
            "'deletion_committing', 'deleted')",
            name="snapshot_underlying_status_valid",
        ),
        sa.CheckConstraint(
            "dml_convergence_status IN "
            "('pending_lock', 'locked', 'active', 'failed_closed')",
            name="dml_convergence_status_valid",
        ),
        sa.CheckConstraint("hold_revision >= 1", name="hold_revision_positive"),
        sa.CheckConstraint(
            "snapshot_access_version >= 1",
            name="snapshot_access_version_positive",
        ),
        sa.CheckConstraint(
            "expected_dml_login_state_version >= 1",
            name="dml_version_positive",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "((created_from_registration_commit_uuid IS NULL "
            "AND initial_hold_revision IS NULL) OR "
            "(created_from_registration_commit_uuid IS NOT NULL "
            "AND initial_hold_revision IS NOT NULL "
            "AND initial_hold_revision >= 1))",
            name="registration_anchor_complete",
        ),
        sa.CheckConstraint(
            "state <> 'released' OR released_at IS NOT NULL",
            name="released_state_has_time",
        ),
        sa.CheckConstraint(
            "((state = 'tombstoned' "
            "AND terminal_reason_code = 'superseded_by_deletion' "
            "AND deletion_request_uuid IS NOT NULL "
            "AND tombstone_ledger_sequence IS NOT NULL "
            "AND tombstone_record_hash IS NOT NULL "
            "AND tombstoned_at IS NOT NULL) OR "
            "(state <> 'tombstoned' AND terminal_reason_code IS NULL "
            "AND tombstone_ledger_sequence IS NULL "
            "AND tombstone_record_hash IS NULL "
            "AND tombstoned_at IS NULL))",
            name="tombstone_evidence_matches_state",
        ),
        sa.CheckConstraint(
            "tombstone_record_hash IS NULL OR length(tombstone_record_hash) = 32",
            name="tombstone_record_hash_length",
        ),
        sa.Index(
            "ix_tenant_recovery_holds_tenant_state",
            "tenant_id",
            "state",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    recovery_run_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "disaster_recovery_runs.id",
            name="fk_recovery_holds_run",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    # Deliberately no tenant/database FK: the minimal hold survives D26 deletion.
    tenant_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    database_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    created_from_registration_commit_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    initial_hold_revision: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    state: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    terminal_reason_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    hold_revision: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    snapshot_underlying_status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False
    )
    snapshot_access_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    expected_dml_login_state_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    dml_convergence_status: Mapped[str] = mapped_column(
        sa.String(24), nullable=False
    )
    review_reason_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    review_evidence_type: Mapped[str | None] = mapped_column(
        sa.String(32), nullable=True
    )
    review_evidence_reference: Mapped[str | None] = mapped_column(
        sa.String(160), nullable=True
    )
    reviewed_by_platform_admin_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    reviewed_by_platform_session_id: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    released_by_action_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True, unique=True
    )
    deletion_request_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    tombstone_ledger_sequence: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    tombstone_record_hash: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    held_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    released_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    tombstoned_at: Mapped[datetime | None] = mapped_column(
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


class DisasterRecoveryReleaseAction(ControlBase):
    """One tenant-scoped, MFA-bound recovery review decision."""

    __tablename__ = "disaster_recovery_release_actions"
    __table_args__ = (
        sa.UniqueConstraint(
            "recovery_run_id",
            "tenant_id",
            "platform_admin_id",
            "idempotency_key",
            name="uq_dr_release_actions_actor_idempotency",
        ),
        sa.CheckConstraint(
            "decision IN ('release', 'keep_closed')", name="decision_valid"
        ),
        sa.CheckConstraint(
            "state IN ('requested', 'running', 'succeeded', 'failed', "
            "'superseded')",
            name="state_valid",
        ),
        sa.CheckConstraint(
            "recent_mfa_method IN ('totp', 'recovery_code')",
            name="recent_mfa_method_valid",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32", name="request_digest_length"
        ),
        sa.CheckConstraint("expected_hold_revision >= 1", name="hold_revision_positive"),
        sa.CheckConstraint("expected_tenant_row_version >= 1", name="tenant_row_version_positive"),
        sa.CheckConstraint("expected_access_version >= 1", name="access_version_positive"),
        sa.CheckConstraint("expected_dml_login_state_version >= 1", name="dml_login_version_positive"),
        sa.CheckConstraint("expected_published_route_version >= 1", name="route_version_positive"),
        sa.CheckConstraint("candidate_generation IS NULL OR candidate_generation >= 1", name="candidate_positive"),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "state NOT IN ('succeeded', 'failed', 'superseded') "
            "OR completed_at IS NOT NULL",
            name="terminal_state_has_time",
        ),
        sa.Index(
            "ix_dr_release_actions_run_tenant_state",
            "recovery_run_id",
            "tenant_id",
            "state",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    recovery_run_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "disaster_recovery_runs.id",
            name="fk_dr_release_run",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    hold_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "tenant_recovery_holds.id",
            name="fk_dr_release_hold",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    tenant_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    decision: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    expected_hold_revision: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    expected_tenant_row_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    expected_access_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    expected_dml_login_state_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    expected_published_route_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    candidate_generation: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    platform_admin_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "platform_admins.id",
            name="fk_dr_release_admin",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    platform_session_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "platform_admin_sessions.id",
            name="fk_dr_release_session",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    recent_mfa_method: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    recent_mfa_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    reason_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    evidence_type: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    evidence_reference: Mapped[str | None] = mapped_column(
        sa.String(160), nullable=True
    )
    idempotency_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    request_digest: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    state: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    safe_outcome_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    requested_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    started_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
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
