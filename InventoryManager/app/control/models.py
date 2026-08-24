"""Models stored in the SaaS control database."""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class ControlBase(DeclarativeBase):
    """Declarative base used only by the control database."""


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        server_default=func.current_timestamp(),
        onupdate=func.current_timestamp(),
    )


class PlatformAdmin(TimestampMixin, ControlBase):
    __tablename__ = "platform_admins"
    __table_args__ = (
        UniqueConstraint("username", name="uq_platform_admins_username"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    username: Mapped[str] = mapped_column(String(64), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    totp_secret_ciphertext: Mapped[str | None] = mapped_column(
        Text, nullable=True
    )


class Tenant(TimestampMixin, ControlBase):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            "status IN ('active', 'suspended')",
            name="ck_tenants_status",
        ),
        CheckConstraint(
            "provisioning_status IN ('provisioning', 'active', 'failed')",
            name="ck_tenants_provisioning_status",
        ),
        UniqueConstraint("db_name", name="uq_tenants_db_name"),
        UniqueConstraint("db_username", name="uq_tenants_db_username"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    db_name: Mapped[str] = mapped_column(String(64), nullable=False)
    db_username: Mapped[str] = mapped_column(String(64), nullable=False)
    db_password_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    provisioning_status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="provisioning"
    )
    provisioning_error: Mapped[str | None] = mapped_column(Text, nullable=True)


class TenantMember(TimestampMixin, ControlBase):
    __tablename__ = "tenant_members"
    __table_args__ = (
        CheckConstraint(
            "role IN ('admin', 'operator')", name="ck_tenant_members_role"
        ),
        CheckConstraint(
            "status IN ('active', 'disabled')",
            name="ck_tenant_members_status",
        ),
        UniqueConstraint("phone", name="uq_tenant_members_phone"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    tenant_id: Mapped[int] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False
    )
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active"
    )


class AuthSession(ControlBase):
    __tablename__ = "auth_sessions"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('platform', 'tenant')", name="ck_auth_sessions_kind"
        ),
        UniqueConstraint("token_hash", name="uq_auth_sessions_token_hash"),
    )

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    subject_id: Mapped[int] = mapped_column(Integer, nullable=False)
    tenant_id: Mapped[int | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=True
    )
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    csrf_token_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )


class SmsLoginCode(ControlBase):
    __tablename__ = "sms_login_codes"

    id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )
    phone: Mapped[str] = mapped_column(String(32), nullable=False)
    code_digest: Mapped[str] = mapped_column(String(64), nullable=False)
    requested_ip: Mapped[str] = mapped_column(String(45), nullable=False)
    send_succeeded: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    attempt_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    expires_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    consumed_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.current_timestamp()
    )
