"""Non-secret control-plane state for per-tenant schema migrations."""

from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.dialects import mysql
from sqlalchemy.orm import Mapped, mapped_column

from inventory_control.sql_defaults import MicrosecondCurrentTimestamp

from .base import ControlBase


FLEET_MIGRATION_DIGEST_TYPE = sa.LargeBinary(32).with_variant(
    mysql.BINARY(32),
    "mysql",
)
FLEET_MIGRATION_TIMESTAMP_TYPE = sa.DateTime(timezone=True).with_variant(
    mysql.DATETIME(fsp=6),
    "mysql",
)


class TenantFleetMigration(ControlBase):
    """One durable N-1 to N migration target for one registered database."""

    __tablename__ = "tenant_fleet_migrations"
    __table_args__ = (
        sa.ForeignKeyConstraint(
            ["tenant_id", "database_uuid"],
            [
                "tenant_databases.tenant_id",
                "tenant_databases.database_uuid",
            ],
            name="fk_fleet_migrations_route_identity",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "database_uuid",
            "target_schema_generation",
            name="uq_fleet_migrations_target_generation",
        ),
        sa.CheckConstraint(
            "state IN ('queued', 'running', 'succeeded', 'failed')",
            name="state_valid",
        ),
        sa.CheckConstraint(
            "route_disposition IN "
            "('routable_current', 'routable_previous', "
            "'hold_identity_mismatch', 'hold_schema_drift', "
            "'hold_unsupported_schema', 'hold_unverified_schema')",
            name="route_disposition_valid",
        ),
        sa.CheckConstraint(
            "last_transition IN ('queue', 'begin', 'succeed', 'fail', 'retry')",
            name="last_transition_valid",
        ),
        sa.CheckConstraint(
            "source_schema_generation >= 1 AND "
            "target_schema_generation = source_schema_generation + 1",
            name="schema_generations_adjacent",
        ),
        sa.CheckConstraint(
            "length(trim(source_schema_revision)) > 0 AND "
            "length(trim(target_schema_revision)) > 0",
            name="schema_revisions_nonempty",
        ),
        sa.CheckConstraint(
            "length(source_schema_sha256) = 32 AND "
            "length(target_schema_sha256) = 32 AND "
            "length(queue_request_digest) = 32 AND "
            "length(last_request_digest) = 32",
            name="required_digests_valid",
        ),
        sa.CheckConstraint(
            "((last_observed_tenant_uuid IS NULL "
            "AND last_observed_database_uuid IS NULL "
            "AND last_observed_schema_generation IS NULL "
            "AND last_observed_schema_revision IS NULL "
            "AND last_observed_schema_sha256 IS NULL "
            "AND last_observed_at IS NULL) OR "
            "(last_observed_tenant_uuid IS NOT NULL "
            "AND last_observed_database_uuid IS NOT NULL "
            "AND last_observed_schema_generation >= 1 "
            "AND last_observed_schema_revision IS NOT NULL "
            "AND last_observed_schema_sha256 IS NOT NULL "
            "AND length(last_observed_schema_sha256) = 32 "
            "AND last_observed_at IS NOT NULL))",
            name="observation_complete",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND operation_generation = attempt_count "
            "AND row_version >= 1 "
            "AND last_transition_from_row_version = row_version - 1",
            name="versions_nonnegative",
        ),
        sa.CheckConstraint(
            "((schema_operation_claim_uuid IS NULL "
            "AND schema_operation_owner_id IS NULL "
            "AND schema_operation_generation IS NULL "
            "AND schema_operation_fencing_token IS NULL "
            "AND schema_operation_row_version IS NULL) OR "
            "(schema_operation_claim_uuid IS NOT NULL "
            "AND schema_operation_owner_id IS NOT NULL "
            "AND schema_operation_generation >= 1 "
            "AND schema_operation_fencing_token >= 1 "
            "AND schema_operation_row_version >= 1))",
            name="schema_operation_fence_complete",
        ),
        sa.CheckConstraint(
            "((state = 'queued' AND attempt_count = 0 "
            "AND operation_generation = 0 AND row_version = 1 "
            "AND started_at IS NULL AND completed_at IS NULL "
            "AND safe_error_code IS NULL "
            "AND last_transition = 'queue' "
            "AND last_transition_from_row_version = 0 "
            "AND last_observed_tenant_uuid IS NULL "
            "AND last_observed_schema_generation IS NULL "
            "AND schema_operation_claim_uuid IS NULL) OR "
            "(state = 'running' AND attempt_count >= 1 "
            "AND operation_generation >= 1 AND started_at IS NOT NULL "
            "AND completed_at IS NULL AND safe_error_code IS NULL "
            "AND last_transition IN ('begin', 'retry') "
            "AND last_observed_tenant_uuid = tenant_id "
            "AND last_observed_database_uuid = database_uuid "
            "AND last_observed_schema_generation = source_schema_generation "
            "AND last_observed_schema_revision = source_schema_revision "
            "AND last_observed_schema_sha256 = source_schema_sha256 "
            "AND schema_operation_claim_uuid IS NOT NULL) OR "
            "(state = 'succeeded' AND attempt_count >= 1 "
            "AND operation_generation >= 1 AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND safe_error_code IS NULL "
            "AND last_transition IN ('begin', 'succeed', 'fail') "
            "AND route_disposition = 'routable_current' "
            "AND last_observed_tenant_uuid = tenant_id "
            "AND last_observed_database_uuid = database_uuid "
            "AND last_observed_schema_generation = target_schema_generation "
            "AND last_observed_schema_revision = target_schema_revision "
            "AND last_observed_schema_sha256 = target_schema_sha256 "
            "AND schema_operation_claim_uuid IS NOT NULL) OR "
            "(state = 'failed' AND attempt_count >= 1 "
            "AND operation_generation >= 1 AND started_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND safe_error_code IS NOT NULL "
            "AND last_transition = 'fail' "
            "AND last_observed_tenant_uuid IS NOT NULL "
            "AND last_observed_schema_generation IS NOT NULL "
            "AND schema_operation_claim_uuid IS NOT NULL))",
            name="state_payload_complete",
        ),
        sa.CheckConstraint(
            "started_at IS NULL OR started_at >= queued_at",
            name="started_after_queue",
        ),
        sa.CheckConstraint(
            "completed_at IS NULL OR "
            "(started_at IS NOT NULL AND completed_at >= started_at)",
            name="completed_after_start",
        ),
        sa.Index(
            "ix_fleet_migrations_state_target",
            "state",
            "target_schema_generation",
            "tenant_id",
        ),
    )

    migration_uuid: Mapped[str] = mapped_column(sa.String(36), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    database_uuid: Mapped[str] = mapped_column(sa.String(36), nullable=False)
    source_schema_generation: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    source_schema_revision: Mapped[str] = mapped_column(
        sa.String(128),
        nullable=False,
    )
    source_schema_sha256: Mapped[bytes] = mapped_column(
        FLEET_MIGRATION_DIGEST_TYPE,
        nullable=False,
    )
    target_schema_generation: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    target_schema_revision: Mapped[str] = mapped_column(
        sa.String(128),
        nullable=False,
    )
    target_schema_sha256: Mapped[bytes] = mapped_column(
        FLEET_MIGRATION_DIGEST_TYPE,
        nullable=False,
    )
    last_observed_tenant_uuid: Mapped[str | None] = mapped_column(
        sa.String(36),
        nullable=True,
    )
    last_observed_database_uuid: Mapped[str | None] = mapped_column(
        sa.String(36),
        nullable=True,
    )
    last_observed_schema_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        nullable=True,
    )
    last_observed_schema_revision: Mapped[str | None] = mapped_column(
        sa.String(128),
        nullable=True,
    )
    last_observed_schema_sha256: Mapped[bytes | None] = mapped_column(
        FLEET_MIGRATION_DIGEST_TYPE,
        nullable=True,
    )
    state: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    route_disposition: Mapped[str] = mapped_column(
        sa.String(32),
        nullable=False,
    )
    attempt_count: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    operation_generation: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    row_version: Mapped[int] = mapped_column(sa.BigInteger, nullable=False)
    last_transition: Mapped[str] = mapped_column(sa.String(16), nullable=False)
    last_transition_from_row_version: Mapped[int] = mapped_column(
        sa.BigInteger,
        nullable=False,
    )
    queue_request_digest: Mapped[bytes] = mapped_column(
        FLEET_MIGRATION_DIGEST_TYPE,
        nullable=False,
    )
    last_request_digest: Mapped[bytes] = mapped_column(
        FLEET_MIGRATION_DIGEST_TYPE,
        nullable=False,
    )
    schema_operation_claim_uuid: Mapped[str | None] = mapped_column(
        sa.String(36),
        nullable=True,
    )
    schema_operation_owner_id: Mapped[str | None] = mapped_column(
        sa.String(128),
        nullable=True,
    )
    schema_operation_generation: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        nullable=True,
    )
    schema_operation_fencing_token: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        nullable=True,
    )
    schema_operation_row_version: Mapped[int | None] = mapped_column(
        sa.BigInteger,
        nullable=True,
    )
    safe_error_code: Mapped[str | None] = mapped_column(
        sa.String(64),
        nullable=True,
    )
    queued_at: Mapped[datetime] = mapped_column(
        FLEET_MIGRATION_TIMESTAMP_TYPE,
        nullable=False,
    )
    started_at: Mapped[datetime | None] = mapped_column(
        FLEET_MIGRATION_TIMESTAMP_TYPE,
        nullable=True,
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        FLEET_MIGRATION_TIMESTAMP_TYPE,
        nullable=True,
    )
    last_observed_at: Mapped[datetime | None] = mapped_column(
        FLEET_MIGRATION_TIMESTAMP_TYPE,
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        FLEET_MIGRATION_TIMESTAMP_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        FLEET_MIGRATION_TIMESTAMP_TYPE,
        nullable=False,
        server_default=MicrosecondCurrentTimestamp(),
    )


__all__ = ["TenantFleetMigration"]
