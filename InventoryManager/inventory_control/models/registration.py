"""Fenced registration, immutable commit, replacement, and incident records."""

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
REGISTRATION_LEASE_EXPIRY_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


class TenantRegistrationAttempt(ControlBase):
    __tablename__ = "tenant_registration_attempts"
    __table_args__ = (
        sa.UniqueConstraint(
            "redemption_code_id", name="uq_registration_attempts_code"
        ),
        sa.UniqueConstraint(
            "idempotency_key", name="uq_registration_attempts_idempotency"
        ),
        sa.UniqueConstraint(
            "registration_commit_uuid", name="uq_registration_attempts_commit"
        ),
        sa.UniqueConstraint(
            "superseded_by_replacement_uuid",
            name="uq_registration_attempts_replacement",
        ),
        sa.CheckConstraint(
            "status IN ('otp_verified', 'reserved', 'provisioning', 'ready', "
            "'committing', 'active', 'failed', 'identity_conflict', "
            "'security_blocked', 'superseded_by_replacement', "
            "'integrity_blocked', 'recovery_review')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "provisioning_execution_generation >= 1",
            name="provisioning_generation_positive",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "requested_tenant_name IS NULL OR "
            "length(trim(requested_tenant_name)) BETWEEN 1 AND 255",
            name="requested_tenant_name_bounded",
        ),
        sa.CheckConstraint(
            "length(request_digest) = 32", name="request_digest_length"
        ),
        sa.CheckConstraint(
            "((status IN ('provisioning', 'ready', 'committing') "
            "AND lease_owner IS NOT NULL AND lease_token IS NOT NULL "
            "AND lease_expires_at IS NOT NULL) OR "
            "(status NOT IN ('provisioning', 'ready', 'committing') "
            "AND lease_owner IS NULL AND lease_token IS NULL "
            "AND lease_expires_at IS NULL))",
            name="lease_matches_status",
        ),
        sa.CheckConstraint(
            "((status = 'active' AND registration_commit_uuid IS NOT NULL) OR "
            "(status <> 'active' AND registration_commit_uuid IS NULL))",
            name="commit_matches_active_status",
        ),
        sa.CheckConstraint(
            "((status = 'superseded_by_replacement' "
            "AND superseded_by_replacement_uuid IS NOT NULL "
            "AND superseded_at IS NOT NULL) OR "
            "(status <> 'superseded_by_replacement' "
            "AND superseded_by_replacement_uuid IS NULL "
            "AND superseded_at IS NULL))",
            name="replacement_status_match",
        ),
        sa.Index(
            "ix_registration_attempts_status_lease",
            "status",
            "lease_expires_at",
        ),
        sa.Index(
            "ix_registration_attempts_user_status",
            "user_id",
            "status",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    user_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    redemption_code_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "redemption_codes.id",
            name="fk_reg_attempt_code",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    requested_tenant_name: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True
    )
    provisional_tenant_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    provisional_database_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    registration_commit_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    superseded_by_replacement_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    status: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    request_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    provisioning_execution_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    lease_owner: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        REGISTRATION_LEASE_EXPIRY_TYPE, nullable=True
    )
    attempt_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    last_safe_error_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    recovery_run_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class TenantRegistrationProvisioningProof(ControlBase):
    """Immutable terminal result for one fenced provisioning worker lease."""

    __tablename__ = "tenant_registration_provisioning_proofs"
    __table_args__ = (
        sa.UniqueConstraint(
            "attempt_uuid",
            "provisioning_execution_generation",
            "worker_lease_token_digest",
            name="uq_registration_proof_worker_fence",
        ),
        sa.CheckConstraint(
            "outcome IN ('ready', 'failed')",
            name="outcome_valid",
        ),
        sa.CheckConstraint(
            "provisioning_execution_generation >= 1 "
            "AND expected_attempt_row_version >= 1 "
            "AND proof_policy_version >= 1",
            name="versions_positive",
        ),
        sa.CheckConstraint(
            "length(worker_lease_token_digest) = 32 "
            "AND length(result_request_digest) = 32",
            name="worker_and_request_digests_valid",
        ),
        sa.CheckConstraint(
            "worker_lease_expires_at > recorded_at",
            name="worker_lease_window_valid",
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
            name="outcome_payload_complete",
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
            name="ready_versions_positive",
        ),
        sa.Index(
            "ix_registration_proofs_attempt_outcome",
            "attempt_uuid",
            "outcome",
            "provisioning_execution_generation",
        ),
    )

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    attempt_uuid: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "tenant_registration_attempts.id",
            name="fk_registration_proof_attempt",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    user_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    tenant_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    database_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    recovery_run_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    provisioning_execution_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    expected_attempt_row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    worker_lease_owner: Mapped[str] = mapped_column(
        sa.String(128), nullable=False
    )
    worker_lease_token_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    worker_lease_expires_at: Mapped[datetime] = mapped_column(
        REGISTRATION_LEASE_EXPIRY_TYPE, nullable=False
    )
    outcome: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    safe_error_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    result_request_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    schema_operation_claim_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    schema_operation_owner_id: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    schema_operation_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    schema_operation_fencing_token: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    schema_operation_row_version: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    schema_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    schema_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    database_identity_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    route_version: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    initial_credential_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    dml_login_state_version: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    default_warehouse_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    default_warehouse_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    smoke_proof_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    advisory_lock_proof_digest: Mapped[bytes | None] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=True
    )
    proof_policy_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        REGISTRATION_LEASE_EXPIRY_TYPE, nullable=False
    )


class TenantRegistrationCommit(ControlBase):
    __tablename__ = "tenant_registration_commits"
    __table_args__ = (
        sa.UniqueConstraint("attempt_uuid", name="uq_registration_commits_attempt"),
        sa.UniqueConstraint("code_uuid", name="uq_registration_commits_code"),
        sa.UniqueConstraint("tenant_uuid", name="uq_registration_commits_tenant"),
        sa.UniqueConstraint("database_uuid", name="uq_registration_commits_database"),
        sa.UniqueConstraint("membership_uuid", name="uq_registration_commits_membership"),
        sa.UniqueConstraint("subscription_uuid", name="uq_registration_commits_subscription"),
        sa.UniqueConstraint("subscription_event_uuid", name="uq_registration_commits_event"),
        sa.ForeignKeyConstraint(
            [
                "plan_revision_uuid",
                "entitlements_schema_version",
                "entitlements_digest",
            ],
            [
                "plans.id",
                "plans.entitlements_schema_version",
                "plans.entitlements_digest",
            ],
            name="fk_registration_commits_plan_digest",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "provisioning_execution_generation_at_commit >= 1",
            name="provisioning_generation_positive",
        ),
        sa.CheckConstraint(
            "entitlements_schema_version >= 1",
            name="ent_schema_positive",
        ),
        sa.CheckConstraint("length(entitlements_digest) = 32", name="entitlements_digest_length"),
        sa.CheckConstraint("service_duration_seconds >= 1", name="service_duration_positive"),
        sa.CheckConstraint("length(published_tenant_name_digest) = 32", name="tenant_name_digest_length"),
        sa.CheckConstraint("length(published_slug_digest) = 32", name="slug_digest_length"),
        sa.CheckConstraint("schema_generation >= 1", name="schema_generation_positive"),
        sa.CheckConstraint("length(database_identity_digest) = 32", name="database_identity_digest_length"),
        sa.CheckConstraint("released_hold_revision_at_commit >= 1", name="released_hold_revision_positive"),
        sa.CheckConstraint("initial_route_version >= 1", name="initial_route_version_positive"),
        sa.CheckConstraint("initial_credential_generation >= 1", name="initial_credential_positive"),
        sa.CheckConstraint("commit_policy_version >= 1", name="commit_policy_version_positive"),
        sa.CheckConstraint("length(entity_link_digest) = 32", name="entity_link_digest_length"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    attempt_uuid: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "tenant_registration_attempts.id",
            name="fk_reg_commit_attempt",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    code_uuid: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("redemption_codes.id", ondelete="RESTRICT"),
        nullable=False,
    )
    tenant_uuid: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    database_uuid: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenant_databases.database_uuid", ondelete="RESTRICT"),
        nullable=False,
    )
    user_uuid: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
    )
    membership_uuid: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "tenant_memberships.id",
            name="fk_reg_commit_membership",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    subscription_uuid: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("subscriptions.id", ondelete="RESTRICT"),
        nullable=False,
    )
    subscription_event_uuid: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "subscription_events.id",
            name="fk_reg_commit_subscription_event",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    recovery_run_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    provisioning_execution_generation_at_commit: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    plan_revision_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    entitlements_schema_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    entitlements_digest: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    service_duration_seconds: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    published_tenant_name_digest: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    published_slug_digest: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    schema_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    database_identity_digest: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    released_hold_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    released_hold_revision_at_commit: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    initial_route_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    initial_credential_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    commit_policy_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    entity_link_digest: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    committed_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class RedemptionCodeReplacement(ControlBase):
    __tablename__ = "redemption_code_replacements"
    __table_args__ = (
        sa.UniqueConstraint("source_code_uuid", name="uq_code_replacements_source_code"),
        sa.UniqueConstraint("replacement_code_uuid", name="uq_code_replacements_replacement_code"),
        sa.UniqueConstraint("source_attempt_uuid", name="uq_code_replacements_source_attempt"),
        sa.UniqueConstraint("cleanup_outbox_event_uuid", name="uq_code_replacements_cleanup_outbox"),
        sa.UniqueConstraint("platform_audit_uuid", name="uq_code_replacements_platform_audit"),
        sa.UniqueConstraint("idempotency_key", name="uq_code_replacements_idempotency"),
        sa.CheckConstraint("source_code_uuid <> replacement_code_uuid", name="source_differs_from_replacement"),
        sa.CheckConstraint("chain_generation >= 1", name="chain_generation_positive"),
        sa.CheckConstraint("entitlements_schema_version >= 1", name="ent_schema_positive"),
        sa.CheckConstraint("length(entitlements_digest) = 32", name="entitlements_digest_length"),
        sa.CheckConstraint("service_duration_seconds >= 1", name="service_duration_positive"),
        sa.CheckConstraint("fenced_provisioning_generation IS NULL OR fenced_provisioning_generation >= 1", name="fenced_generation_positive"),
        sa.CheckConstraint("expected_source_code_row_version >= 1", name="source_code_revision_positive"),
        sa.CheckConstraint("expected_source_attempt_row_version IS NULL OR expected_source_attempt_row_version >= 1", name="source_attempt_revision_positive"),
        sa.CheckConstraint("length(request_digest) = 32", name="request_digest_length"),
        sa.CheckConstraint("length(trim(reason_code)) >= 1", name="reason_code_nonempty"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    source_code_uuid: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("redemption_codes.id", name="fk_code_replacement_source", ondelete="RESTRICT"), nullable=False)
    replacement_code_uuid: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("redemption_codes.id", name="fk_code_replacement_successor", ondelete="RESTRICT"), nullable=False)
    source_attempt_uuid: Mapped[str | None] = mapped_column(sa.String(36), sa.ForeignKey("tenant_registration_attempts.id", name="fk_code_replacement_attempt", ondelete="RESTRICT"), nullable=True)
    source_user_uuid: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    source_provisional_tenant_uuid: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    source_provisional_database_uuid: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    chain_root_code_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    chain_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    plan_revision_uuid: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False)
    entitlements_schema_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    entitlements_digest: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    service_duration_seconds: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    replacement_redeem_before: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    fenced_provisioning_generation: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    platform_admin_uuid: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("platform_admins.id", name="fk_code_replacement_admin", ondelete="RESTRICT"), nullable=False)
    platform_session_uuid: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("platform_admin_sessions.id", name="fk_code_replacement_session", ondelete="RESTRICT"), nullable=False)
    reason_code: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    request_digest: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    expected_source_code_row_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    expected_source_attempt_row_version: Mapped[int | None] = mapped_column(sa.BigInteger, nullable=True)
    current_recovery_run_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    cleanup_outbox_event_uuid: Mapped[str | None] = mapped_column(sa.String(36), sa.ForeignKey("control_outbox_events.id", name="fk_code_replacement_cleanup", ondelete="RESTRICT"), nullable=True)
    platform_audit_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)


class RegistrationIntegrityIncident(ControlBase):
    __tablename__ = "registration_integrity_incidents"
    __table_args__ = (
        sa.UniqueConstraint("open_attempt_uuid", name="uq_registration_incidents_open_attempt"),
        sa.CheckConstraint(
            "state IN ('open', 'resolved_committed', 'resolved_absent', "
            "'recovery_cleanup_pending', 'recovery_cleaned')",
            name="state_valid",
        ),
        sa.CheckConstraint("provisioning_generation >= 1", name="provision_positive"),
        sa.CheckConstraint("length(presence_digest) = 32", name="presence_digest_length"),
        sa.CheckConstraint("marker_generation >= 1", name="marker_generation_positive"),
        sa.CheckConstraint("evidence_policy_version >= 1", name="evidence_policy_positive"),
        sa.CheckConstraint("decision_digest IS NULL OR length(decision_digest) = 32", name="decision_digest_length"),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "((state IN ('open', 'recovery_cleanup_pending') AND resolved_at IS NULL) OR "
            "(state NOT IN ('open', 'recovery_cleanup_pending') AND resolved_at IS NOT NULL))",
            name="resolved_at_matches_state",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    attempt_uuid: Mapped[str] = mapped_column(sa.String(36), sa.ForeignKey("tenant_registration_attempts.id", name="fk_reg_incident_attempt", ondelete="RESTRICT"), nullable=False)
    open_attempt_uuid: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.Computed("CASE WHEN state IN ('open', 'recovery_cleanup_pending') THEN attempt_uuid ELSE NULL END", persisted=True),
        nullable=True,
    )
    code_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    user_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    provisional_tenant_uuid: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    provisional_database_uuid: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    detected_attempt_status: Mapped[str] = mapped_column(sa.String(40), nullable=False)
    detected_replacement_uuid: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    provisioning_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    presence_bitmap: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    presence_digest: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    current_recovery_run_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    marker_generation: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    state: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    resolution_source: Mapped[str | None] = mapped_column(sa.String(32), nullable=True)
    evidence_policy_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    safe_evidence_reference: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    decision_digest: Mapped[bytes | None] = mapped_column(SHA256_DIGEST_TYPE, nullable=True)
    platform_audit_uuid: Mapped[str | None] = mapped_column(sa.String(36), nullable=True)
    row_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, server_default=sa.text("1"))
    detected_at: Mapped[datetime] = mapped_column(sa.DateTime(timezone=True), nullable=False)
    resolved_at: Mapped[datetime | None] = mapped_column(sa.DateTime(timezone=True), nullable=True)
