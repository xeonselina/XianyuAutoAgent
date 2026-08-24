"""Minimal installation, tenant, route, and identity control records."""

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


class Installation(ControlBase):
    __tablename__ = "control_installations"
    __table_args__ = (
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    marker_fingerprint: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, unique=True
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )


class Tenant(ControlBase):
    __tablename__ = "tenants"
    __table_args__ = (
        sa.CheckConstraint("access_version >= 1", name="access_version_positive"),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "status IN ('provisioning', 'active', 'expired', 'suspending', "
            "'suspended', 'resuming', 'deletion_cooling_off', "
            "'deletion_committing', 'deleted')",
            name="status_valid",
        ),
    )

    id: Mapped[str] = mapped_column(sa.String(36), primary_key=True, default=_new_uuid)
    name: Mapped[str | None] = mapped_column(sa.String(255), nullable=True)
    slug: Mapped[str | None] = mapped_column(
        sa.String(255), nullable=True, unique=True
    )
    public_identity_published_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, server_default=sa.text("'provisioning'")
    )
    access_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    timezone: Mapped[str] = mapped_column(
        sa.String(64), nullable=False, server_default=sa.text("'Asia/Shanghai'")
    )
    locale: Mapped[str] = mapped_column(
        sa.String(16), nullable=False, server_default=sa.text("'zh-CN'")
    )
    settings_json: Mapped[dict[str, Any] | None] = mapped_column(
        sa.JSON, nullable=True
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

    database_route: Mapped[TenantDatabase | None] = relationship(
        back_populates="tenant", uselist=False
    )


class TenantDatabase(ControlBase):
    __tablename__ = "tenant_databases"
    __table_args__ = (
        sa.UniqueConstraint(
            "database_instance_key",
            "database_name",
            name="uq_tenant_databases_instance_name",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "database_uuid",
            name="uq_tenant_databases_tenant_database",
        ),
        sa.CheckConstraint("route_version >= 1", name="route_version_positive"),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
        sa.CheckConstraint(
            "((activated_by_registration_commit_uuid IS NULL "
            "AND activation_route_version IS NULL "
            "AND activation_credential_generation IS NULL) OR "
            "(activated_by_registration_commit_uuid IS NOT NULL "
            "AND activation_route_version IS NOT NULL "
            "AND activation_route_version >= 1 "
            "AND activation_credential_generation IS NOT NULL "
            "AND activation_credential_generation >= 1))",
            name="activation_anchor_complete",
        ),
        sa.CheckConstraint(
            "(dml_credential_generation IS NULL OR "
            "dml_credential_generation >= 1) AND "
            "(dml_root_key_version IS NULL OR dml_root_key_version >= 1) AND "
            "(dml_derivation_version IS NULL OR dml_derivation_version >= 1) AND "
            "(dml_login_state_version IS NULL OR "
            "dml_login_state_version >= 1) AND "
            "(platform_read_credential_generation IS NULL OR "
            "platform_read_credential_generation >= 1) AND "
            "(platform_read_root_key_version IS NULL OR "
            "platform_read_root_key_version >= 1) AND "
            "(platform_read_derivation_version IS NULL OR "
            "platform_read_derivation_version >= 1) AND "
            "(platform_read_route_version IS NULL OR "
            "platform_read_route_version >= 1)",
            name="version_fields_positive",
        ),
        sa.CheckConstraint(
            "(dml_desired_login_state IS NULL OR "
            "dml_desired_login_state IN ('active', 'locked')) AND "
            "(dml_observed_login_state IS NULL OR "
            "dml_observed_login_state IN ('active', 'locked'))",
            name="login_states_valid",
        ),
        sa.CheckConstraint(
            "status <> 'ready' OR ("
            "schema_version IS NOT NULL AND length(trim(schema_version)) > 0 "
            "AND activated_by_registration_commit_uuid IS NOT NULL "
            "AND activation_route_version IS NOT NULL "
            "AND activation_route_version >= 1 "
            "AND activation_credential_generation IS NOT NULL "
            "AND activation_credential_generation >= 1 "
            "AND dml_username IS NOT NULL "
            "AND length(trim(dml_username)) > 0 "
            "AND dml_credential_generation IS NOT NULL "
            "AND dml_credential_generation >= 1 "
            "AND dml_root_key_version IS NOT NULL "
            "AND dml_root_key_version >= 1 "
            "AND dml_derivation_version IS NOT NULL "
            "AND dml_derivation_version >= 1 "
            "AND dml_desired_login_state IS NOT NULL "
            "AND dml_observed_login_state IS NOT NULL "
            "AND dml_login_state_version IS NOT NULL "
            "AND dml_login_state_version >= 1 "
            "AND platform_read_username IS NOT NULL "
            "AND length(trim(platform_read_username)) > 0 "
            "AND platform_read_credential_generation IS NOT NULL "
            "AND platform_read_credential_generation >= 1 "
            "AND platform_read_root_key_version IS NOT NULL "
            "AND platform_read_root_key_version >= 1 "
            "AND platform_read_derivation_version IS NOT NULL "
            "AND platform_read_derivation_version >= 1 "
            "AND platform_read_route_version IS NOT NULL "
            "AND platform_read_route_version >= 1)",
            name="ready_metadata_complete",
        ),
        sa.CheckConstraint(
            "status IN ('provisional', 'ready', 'failed', 'retired')",
            name="status_valid",
        ),
    )

    tenant_id: Mapped[str] = mapped_column(
        sa.String(36),
        sa.ForeignKey("tenants.id", ondelete="RESTRICT"),
        primary_key=True,
    )
    database_uuid: Mapped[str] = mapped_column(
        sa.String(36), nullable=False, unique=True, default=_new_uuid
    )
    database_instance_key: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    database_name: Mapped[str] = mapped_column(sa.String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        sa.String(32), nullable=False, server_default=sa.text("'provisional'")
    )
    schema_version: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    activated_by_registration_commit_uuid: Mapped[str | None] = mapped_column(
        sa.String(36), nullable=True
    )
    activation_route_version: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    activation_credential_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    dml_username: Mapped[str | None] = mapped_column(sa.String(128), nullable=True)
    dml_credential_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    dml_root_key_version: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True
    )
    dml_derivation_version: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True
    )
    route_version: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False, server_default=sa.text("1")
    )
    dml_desired_login_state: Mapped[str | None] = mapped_column(
        sa.String(16), nullable=True
    )
    dml_observed_login_state: Mapped[str | None] = mapped_column(
        sa.String(16), nullable=True
    )
    dml_login_state_version: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    dml_desired_state_recovery_run_id: Mapped[str | None] = mapped_column(
        sa.String(36),
        sa.ForeignKey(
            "disaster_recovery_runs.id",
            name="fk_tenant_databases_dml_recovery_run",
            ondelete="RESTRICT",
        ),
        nullable=True,
    )
    platform_read_username: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    platform_read_credential_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    platform_read_root_key_version: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True
    )
    platform_read_derivation_version: Mapped[int | None] = mapped_column(
        sa.Integer, nullable=True
    )
    platform_read_route_version: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
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

    tenant: Mapped[Tenant] = relationship(back_populates="database_route")
    identity_record: Mapped[DatabaseIdentityControlRecord | None] = relationship(
        back_populates="database_route", uselist=False
    )


class DatabaseIdentityControlRecord(ControlBase):
    __tablename__ = "database_identity_control_records"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["tenant_id", "database_uuid"],
            [
                "tenant_databases.tenant_id",
                "tenant_databases.database_uuid",
            ],
            name=(
                "fk_database_identity_control_records_route_identity"
            ),
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "expected_schema_generation >= 1",
            name="expected_schema_generation_positive",
        ),
        sa.CheckConstraint(
            "observed_schema_generation IS NULL OR observed_schema_generation >= 1",
            name="observed_schema_generation_positive",
        ),
        sa.CheckConstraint(
            "((expected_schema_revision IS NULL "
            "AND expected_schema_sha256 IS NULL) OR "
            "(expected_schema_revision IS NOT NULL "
            "AND expected_schema_sha256 IS NOT NULL "
            "AND length(expected_schema_sha256) = 32))",
            name="expected_metadata_complete",
        ),
        sa.CheckConstraint(
            "((observed_schema_revision IS NULL "
            "AND observed_schema_sha256 IS NULL) OR "
            "(observed_schema_revision IS NOT NULL "
            "AND observed_schema_sha256 IS NOT NULL "
            "AND length(observed_schema_sha256) = 32))",
            name="observed_metadata_complete",
        ),
        sa.CheckConstraint("row_version >= 1", name="row_version_positive"),
    )

    tenant_id: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    database_uuid: Mapped[str] = mapped_column(
        sa.String(36), nullable=False, unique=True
    )
    expected_schema_generation: Mapped[int] = mapped_column(
        sa.BigInteger, nullable=False
    )
    observed_schema_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger, nullable=True
    )
    expected_schema_revision: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    expected_schema_sha256: Mapped[bytes | None] = mapped_column(
        sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql"),
        nullable=True,
    )
    observed_schema_revision: Mapped[str | None] = mapped_column(
        sa.String(128), nullable=True
    )
    observed_schema_sha256: Mapped[bytes | None] = mapped_column(
        sa.LargeBinary(32).with_variant(mysql.BINARY(32), "mysql"),
        nullable=True,
    )
    row_version: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
        server_default=sa.text("1"),
    )
    identity_created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True), nullable=False
    )
    last_verified_at: Mapped[datetime | None] = mapped_column(
        sa.DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("CURRENT_TIMESTAMP"),
    )

    database_route: Mapped[TenantDatabase] = relationship(
        back_populates="identity_record"
    )


# Transitional source compatibility while callers move to the design table
# name.  Both names refer to the same mapped class and metadata table.
TenantDatabaseRoute = TenantDatabase
