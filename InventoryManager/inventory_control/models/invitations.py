"""Tenant invitation persistence and database-enforced pending-seat identity."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import ControlBase


def _new_uuid() -> str:
    return str(uuid4())


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(
    mysql.VARBINARY(32),
    "mysql",
)
INVITATION_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


class TenantInvitation(ControlBase):
    __tablename__ = "tenant_invitations"
    __table_args__ = (
        sa.UniqueConstraint(
            "tenant_id",
            "pending_user_id",
            name="uq_tenant_invitations_pending_tenant_user",
        ),
        sa.UniqueConstraint(
            "token_hash", name="uq_tenant_invitations_token_hash"
        ),
        sa.CheckConstraint("phone_region_iso2 = 'CN'", name="phone_region_cn"),
        sa.CheckConstraint(
            "phone_e164 LIKE '+86%' AND length(phone_e164) = 14",
            name="phone_e164_canonical_shape",
        ),
        sa.CheckConstraint(
            "phone_normalization_version >= 1",
            name="phone_normalization_version_positive",
        ),
        sa.CheckConstraint(
            "role_key IN ('admin', 'operator')", name="role_key_valid"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'accepted', 'revoked', 'expired', 'superseded')",
            name="status_valid",
        ),
        sa.CheckConstraint("token_generation >= 1", name="token_generation_positive"),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "length(token_hash) = 32", name="token_hash_length"
        ),
        sa.CheckConstraint(
            "((status = 'pending' AND user_id IS NOT NULL) OR "
            "(status <> 'pending' AND user_id IS NULL))",
            name="user_matches_pending_status",
        ),
        sa.CheckConstraint(
            "((status = 'accepted' AND accepted_at IS NOT NULL) OR "
            "(status <> 'accepted' AND accepted_at IS NULL))",
            name="accepted_at_matches_status",
        ),
        sa.CheckConstraint(
            "((status = 'superseded' AND superseded_at IS NOT NULL) OR "
            "(status <> 'superseded' AND superseded_at IS NULL))",
            name="superseded_at_matches_status",
        ),
        sa.CheckConstraint(
            "((status IN ('revoked', 'expired', 'superseded') "
            "AND terminal_reason_code IS NOT NULL) OR "
            "(status IN ('pending', 'accepted') "
            "AND terminal_reason_code IS NULL))",
            name="terminal_reason_matches_status",
        ),
        sa.Index(
            "ix_tenant_invitations_user_status_expiry",
            "user_id",
            "status",
            "expires_at",
            "id",
        ),
        sa.Index(
            "ix_tenant_invitations_tenant_status_expiry",
            "tenant_id",
            "status",
            "expires_at",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    tenant_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=False,
    )
    user_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    phone_region_iso2: Mapped[str] = mapped_column(
        sa.String(2), nullable=False, server_default=sa.text("'CN'")
    )
    phone_e164: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    phone_normalization_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    role_key: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    token_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    status: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'pending'")
    )
    pending_user_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.Computed(
            "CASE WHEN status = 'pending' THEN user_id ELSE NULL END",
            persisted=True,
        ),
        nullable=True,
    )
    expires_at: Mapped[datetime] = mapped_column(
        INVITATION_TIMESTAMP_TYPE, nullable=False
    )
    accepted_at: Mapped[datetime | None] = mapped_column(
        INVITATION_TIMESTAMP_TYPE, nullable=True
    )
    superseded_at: Mapped[datetime | None] = mapped_column(
        INVITATION_TIMESTAMP_TYPE, nullable=True
    )
    terminal_reason_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        INVITATION_TIMESTAMP_TYPE,
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    updated_at: Mapped[datetime] = mapped_column(
        INVITATION_TIMESTAMP_TYPE,
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

    user = relationship("User")
    tenant = relationship("Tenant")
