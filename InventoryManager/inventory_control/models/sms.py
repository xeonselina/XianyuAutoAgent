"""Control-database records for purpose-bound tenant SMS challenges."""

from __future__ import annotations

from datetime import datetime
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from .base import ControlBase


def _new_uuid() -> str:
    return str(uuid4())


HMAC_SHA256_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
SHA256_DIGEST_TYPE = sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql")
SMS_PROTOCOL_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


class SmsRateLimitSubject(ControlBase):
    """A stable row used to serialize quota decisions for one trusted subject."""

    __tablename__ = "sms_rate_limit_subjects"
    __table_args__ = (
        sa.CheckConstraint(
            "subject_type IN ('phone', 'source')", name="subject_type_valid"
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
    )

    subject_type: Mapped[str] = mapped_column(sa.String(16), primary_key=True)
    subject_bucket: Mapped[str] = mapped_column(sa.String(128), primary_key=True)
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


class SmsChallenge(ControlBase):
    """One immutable-context OTP whose plaintext is never persisted."""

    __tablename__ = "sms_challenges"
    __table_args__ = (
        sa.CheckConstraint(
            "purpose IN ("
            "'register', 'login', 'accept_invitation', "
            "'integration_credential_change', 'sf_account_bind', "
            "'sf_account_unbind', 'sf_account_rebind', 'admin_invitation', "
            "'grant_admin', 'revoke_admin', 'tenant_delete', "
            "'tenant_delete_cancel', 'phone_change_old', 'phone_change_new')",
            name="purpose_valid",
        ),
        sa.CheckConstraint(
            "canonical_phone_e164 LIKE '+86%' "
            "AND length(canonical_phone_e164) = 14",
            name="canonical_phone_shape",
        ),
        sa.CheckConstraint(
            "phone_normalization_version >= 1",
            name="phone_normalization_version_positive",
        ),
        sa.CheckConstraint(
            "length(action_payload_digest_sha256) = 32",
            name="action_payload_digest_sha256_length",
        ),
        sa.CheckConstraint(
            "length(code_hmac_sha256) = 32", name="code_hmac_sha256_length"
        ),
        sa.CheckConstraint("root_key_version >= 1", name="root_key_version_positive"),
        sa.CheckConstraint(
            "hmac_protocol_version >= 1", name="hmac_protocol_version_positive"
        ),
        sa.CheckConstraint("policy_version >= 1", name="policy_version_positive"),
        sa.CheckConstraint(
            "length(authoritative_revision) BETWEEN 1 AND 128",
            name="authoritative_revision_present",
        ),
        sa.CheckConstraint(
            "max_wrong_attempts >= 1 AND max_wrong_attempts <= 5",
            name="max_wrong_attempts_bounded",
        ),
        sa.CheckConstraint(
            "delivery_state IN ('committed', 'sent', 'send_unknown', 'failed')",
            name="delivery_state_valid",
        ),
        sa.CheckConstraint(
            "verification_state IN "
            "('pending_delivery', 'active', 'consumed', 'locked', 'invalidated')",
            name="verification_state_valid",
        ),
        sa.CheckConstraint(
            "wrong_attempt_count >= 0 AND wrong_attempt_count <= 5",
            name="wrong_attempt_count_bounded",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint("expires_at > created_at", name="expiry_after_creation"),
        sa.CheckConstraint(
            "((delivery_state = 'committed' AND delivery_recorded_at IS NULL) OR "
            "(delivery_state <> 'committed' AND delivery_recorded_at IS NOT NULL))",
            name="delivery_recorded_at_matches_state",
        ),
        sa.CheckConstraint(
            "((verification_state = 'pending_delivery' "
            "AND delivery_state = 'committed') OR "
            "verification_state <> 'pending_delivery')",
            name="pending_delivery_matches_delivery_state",
        ),
        sa.CheckConstraint(
            "(verification_state NOT IN ('active', 'consumed', 'locked') OR "
            "delivery_state IN ('sent', 'send_unknown'))",
            name="verifiable_state_matches_delivery",
        ),
        sa.CheckConstraint(
            "((verification_state = 'locked' "
            "AND wrong_attempt_count = max_wrong_attempts) OR "
            "verification_state <> 'locked')",
            name="locked_at_attempt_limit",
        ),
        sa.CheckConstraint(
            "((verification_state = 'consumed' AND consumed_at IS NOT NULL) OR "
            "(verification_state <> 'consumed' AND consumed_at IS NULL))",
            name="consumed_at_matches_state",
        ),
        sa.CheckConstraint(
            "((verification_state = 'locked' AND locked_at IS NOT NULL) OR "
            "(verification_state <> 'locked' AND locked_at IS NULL))",
            name="locked_at_matches_state",
        ),
        sa.CheckConstraint(
            "((verification_state = 'invalidated' "
            "AND invalidated_at IS NOT NULL "
            "AND invalidated_reason_code IS NOT NULL) OR "
            "(verification_state <> 'invalidated' "
            "AND invalidated_at IS NULL "
            "AND invalidated_reason_code IS NULL))",
            name="invalidation_fields_match_state",
        ),
        sa.Index(
            "ix_sms_challenges_phone_rate_window",
            "canonical_phone_e164",
            "delivery_state",
            "created_at",
        ),
        sa.Index(
            "ix_sms_challenges_source_rate_window",
            "trusted_source_bucket",
            "delivery_state",
            "created_at",
        ),
        sa.Index(
            "ix_sms_challenges_phone_purpose_current",
            "canonical_phone_e164",
            "purpose",
            "verification_state",
            "created_at",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    purpose: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    canonical_phone_e164: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    phone_normalization_version: Mapped[int] = mapped_column(
        sa.Integer, nullable=False
    )
    phone_metadata_version: Mapped[str] = mapped_column(sa.String(64), nullable=False)
    user_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=True,
    )
    tenant_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        nullable=True,
    )
    actor_session_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenant_user_sessions.id", ondelete="RESTRICT"),
        nullable=True,
    )
    action_payload_digest_sha256: Mapped[bytes] = mapped_column(
        SHA256_DIGEST_TYPE, nullable=False
    )
    authoritative_revision: Mapped[str] = mapped_column(
        sa.String(128), nullable=False
    )
    code_hmac_sha256: Mapped[bytes] = mapped_column(
        HMAC_SHA256_TYPE, nullable=False
    )
    root_key_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    hmac_protocol_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    policy_version: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    max_wrong_attempts: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    trusted_source_bucket: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    delivery_state: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'committed'")
    )
    verification_state: Mapped[str] = mapped_column(
        sa.String(24),
        nullable=False,
        server_default=sa.text("'pending_delivery'"),
    )
    wrong_attempt_count: Mapped[int] = mapped_column(
        sa.Integer, nullable=False, server_default=sa.text("0")
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        SMS_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
    expires_at: Mapped[datetime] = mapped_column(
        SMS_PROTOCOL_TIMESTAMP_TYPE, nullable=False
    )
    delivery_recorded_at: Mapped[datetime | None] = mapped_column(
        SMS_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    consumed_at: Mapped[datetime | None] = mapped_column(
        SMS_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    locked_at: Mapped[datetime | None] = mapped_column(
        SMS_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    invalidated_at: Mapped[datetime | None] = mapped_column(
        SMS_PROTOCOL_TIMESTAMP_TYPE, nullable=True
    )
    invalidated_reason_code: Mapped[str | None] = mapped_column(
        sa.String(64), nullable=True
    )
