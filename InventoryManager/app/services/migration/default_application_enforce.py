"""Fail-closed publication for the default migration application phase.

The service owns no database discovery, deployment mutation, provider client,
or printer.  A caller supplies an already-bound control Session and a
machine-produced negative-test receipt tied to the immutable manifest.  The
single control transaction writes/replays D60 and publishes only the exact
provisional route whose schema identity still matches its post-DDL record.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from inventory_control.default_migration import (
    DefaultTenantMigrationGrantWriter,
    DefaultTenantMigrationManifest,
    MigrationJournal,
    MigrationPhase,
)
from inventory_control.models import (
    DatabaseIdentityControlRecord,
    Tenant,
    TenantDatabase,
)


class DefaultApplicationEnforcementError(RuntimeError):
    code = "DEFAULT_APPLICATION_ENFORCEMENT_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class DefaultApplicationEnforcementInputError(
    DefaultApplicationEnforcementError
):
    code = "DEFAULT_APPLICATION_ENFORCEMENT_INPUT_INVALID"


class DefaultApplicationEnforcementConflictError(
    DefaultApplicationEnforcementError
):
    code = "DEFAULT_APPLICATION_ENFORCEMENT_CONFLICT"


class DefaultApplicationEnforcementPersistenceError(
    DefaultApplicationEnforcementError
):
    code = "DEFAULT_APPLICATION_ENFORCEMENT_PERSISTENCE_FAILED"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultApplicationEnforcementEvidence:
    """Machine evidence from an isolated application/runtime test bundle."""

    manifest_digest: bytes
    implementation_identity_digest: bytes
    migration_bundle_digest: bytes
    trusted_route_matrix_digest: bytes
    identity_namespace_matrix_digest: bytes
    effective_gate_matrix_digest: bytes
    legacy_surface_negative_digest: bytes
    production_write_identity_used: bool = False
    provider_side_effect_count: int = 0
    print_side_effect_count: int = 0

    def __post_init__(self) -> None:
        if (
            any(
                not isinstance(value, bytes) or len(value) != 32
                for value in (
                    self.manifest_digest,
                    self.implementation_identity_digest,
                    self.migration_bundle_digest,
                    self.trusted_route_matrix_digest,
                    self.identity_namespace_matrix_digest,
                    self.effective_gate_matrix_digest,
                    self.legacy_surface_negative_digest,
                )
            )
            or not isinstance(self.production_write_identity_used, bool)
            or self.production_write_identity_used
            or isinstance(self.provider_side_effect_count, bool)
            or not isinstance(self.provider_side_effect_count, int)
            or self.provider_side_effect_count != 0
            or isinstance(self.print_side_effect_count, bool)
            or not isinstance(self.print_side_effect_count, int)
            or self.print_side_effect_count != 0
        ):
            raise DefaultApplicationEnforcementInputError()

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(
            json.dumps(
                {
                    "effective_gate_matrix_digest": (
                        self.effective_gate_matrix_digest.hex()
                    ),
                    "identity_namespace_matrix_digest": (
                        self.identity_namespace_matrix_digest.hex()
                    ),
                    "implementation_identity_digest": (
                        self.implementation_identity_digest.hex()
                    ),
                    "legacy_surface_negative_digest": (
                        self.legacy_surface_negative_digest.hex()
                    ),
                    "manifest_digest": self.manifest_digest.hex(),
                    "migration_bundle_digest": (
                        self.migration_bundle_digest.hex()
                    ),
                    "print_side_effect_count": self.print_side_effect_count,
                    "production_write_identity_used": (
                        self.production_write_identity_used
                    ),
                    "provider_side_effect_count": (
                        self.provider_side_effect_count
                    ),
                    "trusted_route_matrix_digest": (
                        self.trusted_route_matrix_digest.hex()
                    ),
                    "version": 1,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).digest()

    def require_manifest(
        self,
        manifest: DefaultTenantMigrationManifest,
    ) -> None:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or self.manifest_digest != manifest.digest
            or self.implementation_identity_digest
            != manifest.implementation_identity_digest
            or self.migration_bundle_digest
            != manifest.migration_bundle_digest
        ):
            raise DefaultApplicationEnforcementInputError()

    def __repr__(self) -> str:
        return (
            "DefaultApplicationEnforcementEvidence("
            f"digest={self.digest.hex()!r}, side_effects=0)"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class DefaultApplicationEnforcementResult:
    tenant_id: str
    database_uuid: str
    subscription_uuid: str
    subscription_event_uuid: str
    route_version: int
    tenant_row_version: int
    route_row_version: int
    schema_generation: int
    schema_digest: bytes
    evidence_digest: bytes
    created: bool

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(
            json.dumps(
                {
                    "database_uuid": self.database_uuid,
                    "evidence_digest": self.evidence_digest.hex(),
                    "route_row_version": self.route_row_version,
                    "route_version": self.route_version,
                    "schema_digest": self.schema_digest.hex(),
                    "schema_generation": self.schema_generation,
                    "subscription_event_uuid": self.subscription_event_uuid,
                    "subscription_uuid": self.subscription_uuid,
                    "tenant_id": self.tenant_id,
                    "tenant_row_version": self.tenant_row_version,
                    "version": 1,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).digest()


class DefaultTenantApplicationEnforcementService:
    """Publish the verified default route and D60 grant atomically."""

    def __init__(
        self,
        *,
        grant_writer: DefaultTenantMigrationGrantWriter | None = None,
    ) -> None:
        if grant_writer is not None and not isinstance(
            grant_writer,
            DefaultTenantMigrationGrantWriter,
        ):
            raise TypeError("grant writer is invalid")
        self._grant_writer = grant_writer or DefaultTenantMigrationGrantWriter()

    def publish(
        self,
        session: Session,
        *,
        manifest: DefaultTenantMigrationManifest,
        journal: MigrationJournal,
        evidence: DefaultApplicationEnforcementEvidence,
    ) -> DefaultApplicationEnforcementResult:
        _require_transaction(session)
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or not isinstance(journal, MigrationJournal)
            or journal.manifest_digest != manifest.digest
            or tuple(item.phase for item in journal.completed)
            != (MigrationPhase.EXPAND, MigrationPhase.BACKFILL_VERIFY)
            or not isinstance(evidence, DefaultApplicationEnforcementEvidence)
        ):
            raise DefaultApplicationEnforcementInputError()
        evidence.require_manifest(manifest)
        tenant_id = str(manifest.tenant_uuid)
        database_uuid = str(manifest.database_uuid)
        try:
            tenant = session.scalar(
                sa.select(Tenant)
                .where(Tenant.id == tenant_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            route = session.scalar(
                sa.select(TenantDatabase)
                .where(TenantDatabase.tenant_id == tenant_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            identity = session.scalar(
                sa.select(DatabaseIdentityControlRecord)
                .where(DatabaseIdentityControlRecord.tenant_id == tenant_id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            _require_authority(
                tenant,
                route,
                identity,
                manifest=manifest,
            )
            assert tenant is not None
            assert route is not None
            assert identity is not None
            grant = self._grant_writer.write(
                session,
                manifest=manifest,
                journal=journal,
            )
            created = route.status == "provisional"
            if created:
                route.status = "ready"
                route.row_version += 1
                tenant.status = "active"
                tenant.row_version += 1
            session.flush()
        except DefaultApplicationEnforcementError:
            raise
        except IntegrityError:
            raise DefaultApplicationEnforcementConflictError() from None
        except SQLAlchemyError:
            raise DefaultApplicationEnforcementPersistenceError() from None
        return DefaultApplicationEnforcementResult(
            tenant_id=tenant_id,
            database_uuid=database_uuid,
            subscription_uuid=grant.subscription_uuid,
            subscription_event_uuid=grant.event_uuid,
            route_version=route.route_version,
            tenant_row_version=tenant.row_version,
            route_row_version=route.row_version,
            schema_generation=identity.observed_schema_generation,
            schema_digest=identity.observed_schema_sha256,
            evidence_digest=evidence.digest,
            created=created,
        )


def _require_authority(
    tenant: Tenant | None,
    route: TenantDatabase | None,
    identity: DatabaseIdentityControlRecord | None,
    *,
    manifest: DefaultTenantMigrationManifest,
) -> None:
    paired_state = (
        None if tenant is None or route is None else (tenant.status, route.status)
    )
    if (
        tenant is None
        or route is None
        or identity is None
        or paired_state not in {
            ("provisioning", "provisional"),
            ("active", "ready"),
        }
        or route.database_uuid != str(manifest.database_uuid)
        or route.database_name != manifest.source_schema_name
        or route.schema_version != manifest.tenant_schema_head
        or route.activated_by_registration_commit_uuid is None
        or route.dml_username is None
        or route.platform_read_username is None
        or route.dml_username == route.platform_read_username
        or route.dml_desired_login_state != "active"
        or route.dml_observed_login_state != "active"
        or identity.database_uuid != str(manifest.database_uuid)
        or identity.expected_schema_generation
        != identity.observed_schema_generation
        or identity.expected_schema_revision != manifest.tenant_schema_head
        or identity.observed_schema_revision != manifest.tenant_schema_head
        or identity.expected_schema_sha256 is None
        or identity.expected_schema_sha256 != identity.observed_schema_sha256
    ):
        raise DefaultApplicationEnforcementConflictError()


def _require_transaction(session: Session) -> None:
    if (
        not isinstance(session, Session)
        or not session.in_transaction()
        or session.get_transaction() is None
        or session.get_transaction().origin
        is not SessionTransactionOrigin.BEGIN
    ):
        raise DefaultApplicationEnforcementInputError()


__all__ = [
    "DefaultApplicationEnforcementConflictError",
    "DefaultApplicationEnforcementError",
    "DefaultApplicationEnforcementEvidence",
    "DefaultApplicationEnforcementInputError",
    "DefaultApplicationEnforcementPersistenceError",
    "DefaultApplicationEnforcementResult",
    "DefaultTenantApplicationEnforcementService",
]
