"""Immutable redemption-code entitlement snapshots and encrypted bearers."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import ControlBase


def _new_uuid() -> str:
    return str(uuid4())


SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
AES_GCM_NONCE_TYPE = sa.LargeBinary(12).with_variant(mysql.BINARY(12), "mysql")


class RedemptionCodeBatch(ControlBase):
    __tablename__ = "redemption_code_batches"
    __table_args__ = (
        sa.UniqueConstraint(
            "generation_request_uuid",
            name="uq_redemption_batches_generation_request",
        ),
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
            name="fk_redemption_batches_plan_snapshot",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("length(trim(name)) >= 1", name="name_nonempty"),
        sa.CheckConstraint(
            "channel IS NULL OR length(trim(channel)) >= 1",
            name="channel_nonempty",
        ),
        sa.CheckConstraint(
            "internal_note IS NULL OR length(trim(internal_note)) >= 1",
            name="internal_note_nonempty",
        ),
        sa.CheckConstraint("quantity >= 1", name="quantity_positive"),
        sa.CheckConstraint(
            "length(request_digest) = 32", name="request_digest_length"
        ),
        sa.CheckConstraint(
            "entitlements_schema_version >= 1",
            name="entitlements_schema_version_positive",
        ),
        sa.CheckConstraint(
            "length(entitlements_digest) = 32",
            name="entitlements_digest_length",
        ),
        sa.CheckConstraint(
            "service_duration_seconds >= 1",
            name="service_duration_seconds_positive",
        ),
        sa.CheckConstraint(
            "plaintext_exported_at IS NULL OR plaintext_exported_at >= created_at",
            name="plaintext_export_after_creation",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    generation_request_uuid: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    request_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    name: Mapped[str] = mapped_column(sa.String(160), nullable=False)
    channel: Mapped[str | None] = mapped_column(sa.String(64), nullable=True)
    internal_note: Mapped[str | None] = mapped_column(
        sa.String(500), nullable=True
    )
    quantity: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    plan_revision_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    entitlements_schema_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    entitlements_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    entitlements_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    service_duration_seconds: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    default_redeem_before: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    created_by_platform_admin_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "platform_admins.id",
            name="fk_redemption_batches_creator",
            ondelete="RESTRICT",
        ),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    plaintext_exported_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )

    codes: Mapped[list[RedemptionCode]] = relationship(back_populates="batch")


class RedemptionCode(ControlBase):
    __tablename__ = "redemption_codes"
    __table_args__ = (
        sa.UniqueConstraint("crypto_context_uuid", name="uq_redemption_codes_crypto_context"),
        sa.UniqueConstraint("lookup_hash", name="uq_redemption_codes_lookup_hash"),
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
            name="fk_redemption_codes_plan_snapshot",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("length(code_prefix) = 4", name="code_prefix_length"),
        sa.CheckConstraint("length(lookup_hash) = 32", name="lookup_hash_length"),
        sa.CheckConstraint("length(code_nonce) = 12", name="code_nonce_length"),
        sa.CheckConstraint(
            "length(code_ciphertext) >= 42", name="ciphertext_contains_code_and_tag"
        ),
        sa.CheckConstraint("secret_revision >= 1", name="secret_revision_positive"),
        sa.CheckConstraint("root_key_version >= 1", name="root_key_version_positive"),
        sa.CheckConstraint("crypto_version >= 1", name="crypto_version_positive"),
        sa.CheckConstraint("aad_version >= 1", name="aad_version_positive"),
        sa.CheckConstraint(
            "status IN ('active', 'reserved', 'redeemed', 'revoked', "
            "'expired', 'recovery_revoked')",
            name="status_valid",
        ),
        sa.CheckConstraint(
            "entitlements_schema_version >= 1",
            name="entitlements_schema_version_positive",
        ),
        sa.CheckConstraint(
            "length(entitlements_digest) = 32",
            name="entitlements_digest_length",
        ),
        sa.CheckConstraint(
            "service_duration_seconds >= 1",
            name="service_duration_seconds_positive",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "((reserved_registration_attempt_uuid IS NULL "
            "AND reserved_user_uuid IS NULL) OR "
            "(reserved_registration_attempt_uuid IS NOT NULL "
            "AND reserved_user_uuid IS NOT NULL))",
            name="reservation_binding_complete",
        ),
        sa.CheckConstraint(
            "(status <> 'reserved' OR "
            "(reserved_registration_attempt_uuid IS NOT NULL "
            "AND reserved_user_uuid IS NOT NULL))",
            name="reserved_status_has_binding",
        ),
        sa.CheckConstraint(
            "(status NOT IN ('active', 'expired') OR "
            "(reserved_registration_attempt_uuid IS NULL "
            "AND reserved_user_uuid IS NULL))",
            name="unowned_status_has_no_reservation",
        ),
        sa.CheckConstraint(
            "((redeemed_registration_attempt_uuid IS NULL "
            "AND registration_commit_uuid IS NULL) OR "
            "(redeemed_registration_attempt_uuid IS NOT NULL "
            "AND registration_commit_uuid IS NOT NULL))",
            name="registration_redemption_binding_complete",
        ),
        sa.CheckConstraint(
            "((status = 'redeemed' AND redeemed_tenant_uuid IS NOT NULL "
            "AND redeemed_at IS NOT NULL) OR "
            "(status <> 'redeemed' AND redeemed_tenant_uuid IS NULL "
            "AND redeemed_at IS NULL "
            "AND redeemed_registration_attempt_uuid IS NULL "
            "AND registration_commit_uuid IS NULL))",
            name="redemption_fields_match_status",
        ),
        sa.CheckConstraint(
            "((status = 'revoked' AND revoked_at IS NOT NULL "
            "AND revocation_reason_code IS NOT NULL) OR "
            "(status <> 'revoked' AND revoked_at IS NULL "
            "AND revocation_reason_code IS NULL))",
            name="revocation_fields_match_status",
        ),
        sa.CheckConstraint(
            "((status = 'expired' AND expired_at IS NOT NULL) OR "
            "(status <> 'expired' AND expired_at IS NULL))",
            name="expired_at_matches_status",
        ),
        sa.CheckConstraint(
            "((status = 'recovery_revoked' "
            "AND recovery_revoked_by_run_uuid IS NOT NULL "
            "AND recovery_revoked_at IS NOT NULL) OR "
            "(status <> 'recovery_revoked' "
            "AND recovery_revoked_by_run_uuid IS NULL "
            "AND recovery_revoked_at IS NULL))",
            name="recovery_revocation_matches_status",
        ),
        sa.Index("ix_redemption_codes_status_deadline", "status", "redeem_before"),
        sa.Index("ix_redemption_codes_batch", "batch_id", "id"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    crypto_context_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    batch_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("redemption_code_batches.id", ondelete="RESTRICT"),
        nullable=False,
    )
    code_prefix: Mapped[str] = mapped_column(sa.String(4), nullable=False)
    lookup_hash: Mapped[bytes] = mapped_column(SHA256_DIGEST_TYPE, nullable=False)
    code_ciphertext: Mapped[bytes] = mapped_column(sa.LargeBinary, nullable=False)
    code_nonce: Mapped[bytes] = mapped_column(AES_GCM_NONCE_TYPE, nullable=False)
    secret_revision: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    root_key_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    crypto_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    aad_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(24), nullable=False, server_default=sa.text("'active'")
    )
    plan_revision_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    entitlements_schema_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    entitlements_json: Mapped[dict[str, Any]] = mapped_column(sa.JSON, nullable=False)
    entitlements_digest: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    service_duration_seconds: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    redeem_before: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    reserved_registration_attempt_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    reserved_user_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    redeemed_tenant_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    redeemed_registration_attempt_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    registration_commit_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    redeemed_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    revocation_reason_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
    expired_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_under_recovery_run_uuid: Mapped[str] = mapped_column(
        sa.String(36), nullable=False
    )
    recovery_revoked_by_run_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    recovery_revoked_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )

    batch: Mapped[RedemptionCodeBatch] = relationship(back_populates="codes")
