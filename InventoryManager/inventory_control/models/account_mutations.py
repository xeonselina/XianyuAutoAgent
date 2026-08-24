"""Non-secret tenant database account-mutation persistence records.

The lease table is deliberately independent from tenant and route foreign
keys.  A lease claim or renewal must be a short transaction that touches only
one lease row.  Rotation rows retain technical lineage and reducer state, but
never database passwords, password hashes, ciphertext, or connection strings.
"""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp

from .base import ControlBase


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
LEASE_EXPIRY_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


def _new_uuid() -> str:
    return str(uuid4())


class TenantDatabaseAccountMutationLease(ControlBase):
    """One fencing lease for one tenant and account purpose."""

    __tablename__ = "tenant_database_account_mutation_leases"
    __table_args__ = (
        sa.CheckConstraint(
            "account_kind IN ('dml', 'platform_read')",
            name="account_kind_valid",
        ),
        sa.CheckConstraint(
            "fencing_token >= 0",
            name="fencing_nonnegative",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "((lease_owner IS NULL AND lease_purpose IS NULL "
            "AND lease_expires_at IS NULL) OR "
            "(lease_owner IS NOT NULL AND lease_purpose IS NOT NULL "
            "AND lease_expires_at IS NOT NULL AND fencing_token >= 1))",
            name="ownership_complete",
        ),
        sa.Index(
            "ix_account_mutation_leases_expiry",
            "account_kind",
            "lease_expires_at",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True
    )
    account_kind: Mapped[str] = mapped_column(
        sa.String(24), primary_key=True
    )
    fencing_token: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("0")
    )
    lease_owner: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    lease_purpose: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        LEASE_EXPIRY_TYPE, nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        LEASE_EXPIRY_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        LEASE_EXPIRY_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )


class TenantDatabaseAccountRotation(ControlBase):
    """One reducer-backed, non-secret account generation transition."""

    __tablename__ = "tenant_database_account_rotations"
    __table_args__ = (
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
        sa.CheckConstraint(
            "account_kind IN ('dml', 'platform_read')",
            name="account_kind_valid",
        ),
        sa.CheckConstraint(
            "purpose IN ('standard', 'root_key_rotation', "
            "'recovery_release', 'suspension_resolve', 'deletion_cancel')",
            name="purpose_valid",
        ),
        sa.CheckConstraint(
            "state IN ('preparing', 'prepared_locked', "
            "'candidate_testing', 'verified', 'switched', 'draining', "
            "'revoked', 'failed')",
            name="state_valid",
        ),
        sa.CheckConstraint(
            "inherited_desired_login_state IN ('active', 'locked')",
            name="desired_state_valid",
        ),
        sa.CheckConstraint(
            "last_action IN ('start', 'prepare_locked', "
            "'begin_candidate_testing', 'verify_candidate', "
            "'switch_candidate', 'begin_draining', "
            "'revoke_previous', 'fail')",
            name="last_action_valid",
        ),
        sa.CheckConstraint(
            "length(last_request_digest) = 32",
            name="request_digest_length",
        ),
        sa.CheckConstraint(
            "from_username <> to_username",
            name="usernames_distinct",
        ),
        sa.CheckConstraint(
            "from_credential_generation >= 1 AND "
            "to_credential_generation > from_credential_generation AND "
            "from_root_key_version >= 1 AND to_root_key_version >= 1 AND "
            "from_derivation_version >= 1 AND to_derivation_version >= 1",
            name="generation_lineage_valid",
        ),
        sa.CheckConstraint(
            "expected_tenant_access_version >= 1 AND "
            "expected_route_version >= 1 AND "
            "expected_login_state_version >= 1 AND "
            "lease_fencing_token >= 1",
            name="fences_positive",
        ),
        sa.CheckConstraint(
            "transition_sequence >= 1 AND row_version >= 1",
            name="row_versions_positive",
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
            name="state_facts_valid",
        ),
        sa.CheckConstraint(
            "((state = 'revoked' AND previous_revoked = 1) OR "
            "(state <> 'revoked' AND previous_revoked = 0))",
            name="revocation_fact_valid",
        ),
        sa.CheckConstraint(
            "((state = 'failed' AND safe_error_code IS NOT NULL) OR "
            "(state <> 'failed' AND safe_error_code IS NULL))",
            name="failure_fact_valid",
        ),
        sa.Index(
            "ix_account_rotations_tenant_kind_state",
            "tenant_id",
            "account_kind",
            "state",
        ),
    )

    id: Mapped[str] = mapped_column(
        sa.String(36), primary_key=True, default=_new_uuid
    )
    rotation_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    tenant_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    database_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    account_kind: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    purpose: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    from_username: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    from_credential_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    from_root_key_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    from_derivation_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    to_username: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    to_credential_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    to_root_key_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    to_derivation_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    inherited_desired_login_state: Mapped[str] = mapped_column(
        sa.String(16), nullable=False
    )
    expected_tenant_access_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    expected_route_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    expected_login_state_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    lease_owner: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    lease_purpose: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    lease_fencing_token: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    state: Mapped[str] = mapped_column(sa.String(24), nullable=False)
    candidate_locked: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    candidate_published: Mapped[bool] = mapped_column(
        sa.Boolean, nullable=False
    )
    previous_locked: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    previous_revoked: Mapped[bool] = mapped_column(sa.Boolean, nullable=False)
    transition_sequence: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    last_action: Mapped[str] = mapped_column(sa.String(32), nullable=False)
    last_request_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    safe_error_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        LEASE_EXPIRY_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        LEASE_EXPIRY_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )


__all__ = [
    "TenantDatabaseAccountMutationLease",
    "TenantDatabaseAccountRotation",
]
