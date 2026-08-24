"""Concrete Alembic-to-expand-evidence composition for isolated databases."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session
from inventory_control.models import Installation

from inventory_control.default_migration import (
    DefaultMigrationStepInvocation,
    DefaultMySqlTenantGrantMatrixObservation,
    DefaultSchemaApplyReceipt,
    DefaultSchemaQualificationReceipt,
    DefaultSchemaQualificationTarget,
    DefaultTenantMigrationManifest,
    ExplicitConnectionAlembicQualificationRunner,
    MigrationPhase,
)

from .default_expand_enforce import (
    DefaultControlExpandEvidence,
    DefaultExpandEnforcementInputError,
    DefaultTenantExpandEvidence,
)
from .default_tenant_registration import (
    DefaultTenantInPlaceRegistrationService,
)


ConnectionFactory = Callable[[], Connection]
DigestObserver = Callable[[Connection], bytes]
BoundDigestObserver = Callable[[], bytes]
IdentityEstablisher = Callable[
    [Connection, DefaultTenantMigrationManifest], bytes
]


class _AlembicRunner(Protocol):
    def qualify(
        self,
        connection: Connection,
        *,
        target: DefaultSchemaQualificationTarget,
    ) -> DefaultSchemaQualificationReceipt: ...

    def apply(
        self,
        connection: Connection,
        *,
        target: DefaultSchemaQualificationTarget,
    ) -> DefaultSchemaApplyReceipt: ...


class _TenantGrantMatrixVerifier(Protocol):
    def verify(self) -> DefaultMySqlTenantGrantMatrixObservation: ...


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultExpandAlembicBinding:
    """Separate destructive scratch qualification from forward-only apply."""

    qualification_connection_factory: ConnectionFactory = field(repr=False)
    qualification_target: DefaultSchemaQualificationTarget
    apply_connection_factory: ConnectionFactory = field(repr=False)
    apply_target: DefaultSchemaQualificationTarget
    runner: _AlembicRunner = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not callable(self.qualification_connection_factory)
            or not callable(self.apply_connection_factory)
            or not isinstance(
                self.qualification_target,
                DefaultSchemaQualificationTarget,
            )
            or not isinstance(self.apply_target, DefaultSchemaQualificationTarget)
            or not callable(getattr(self.runner, "qualify", None))
            or not callable(getattr(self.runner, "apply", None))
            or self.qualification_connection_factory
            is self.apply_connection_factory
        ):
            raise DefaultExpandEnforcementInputError()

    def run(
        self,
        *,
        expected_schema_head: str,
    ) -> tuple[
        DefaultSchemaQualificationReceipt,
        DefaultSchemaApplyReceipt,
        Connection,
    ]:
        if not isinstance(expected_schema_head, str) or not expected_schema_head:
            raise DefaultExpandEnforcementInputError()
        qualification_connection = self.qualification_connection_factory()
        try:
            qualification = self.runner.qualify(
                qualification_connection,
                target=self.qualification_target,
            )
        finally:
            qualification_connection.close()
        if qualification.schema_head != expected_schema_head:
            raise DefaultExpandEnforcementInputError()
        apply_connection = self.apply_connection_factory()
        try:
            applied = self.runner.apply(
                apply_connection,
                target=self.apply_target,
            )
        except Exception:
            apply_connection.close()
            raise
        if (
            applied.schema_head != expected_schema_head
            or applied.target_identity_digest
            == qualification.target_identity_digest
        ):
            apply_connection.close()
            raise DefaultExpandEnforcementInputError()
        return qualification, applied, apply_connection

    def __repr__(self) -> str:
        return "DefaultExpandAlembicBinding(connections='<bound>')"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class QualifiedDefaultControlExpandVerifier:
    alembic: DefaultExpandAlembicBinding
    control_account_grants_observer: BoundDigestObserver = field(repr=False)
    installation_marker_observer: DigestObserver = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.alembic, DefaultExpandAlembicBinding)
            or not callable(self.control_account_grants_observer)
            or not callable(self.installation_marker_observer)
        ):
            raise DefaultExpandEnforcementInputError()

    def verify(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultControlExpandEvidence:
        manifest = _manifest(invocation)
        qualification, applied, connection = self.alembic.run(
            expected_schema_head=manifest.control_schema_head,
        )
        try:
            marker = _observed_digest(
                self.installation_marker_observer,
                connection,
            )
        finally:
            connection.close()
        grants = _bound_digest(self.control_account_grants_observer)
        _require_heads(manifest.control_schema_head, qualification, applied)
        return DefaultControlExpandEvidence(
            manifest_digest=manifest.digest,
            implementation_identity_digest=(
                manifest.implementation_identity_digest
            ),
            migration_bundle_digest=manifest.migration_bundle_digest,
            schema_head=manifest.control_schema_head,
            migration_round_trip_digest=qualification.digest,
            metadata_model_match_digest=_metadata_digest(
                qualification,
                applied,
            ),
            control_account_grants_digest=grants,
            installation_marker_digest=marker,
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class QualifiedDefaultTenantExpandVerifier:
    alembic: DefaultExpandAlembicBinding
    database_identity_establisher: IdentityEstablisher = field(repr=False)
    grant_matrix_verifier: _TenantGrantMatrixVerifier = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.alembic, DefaultExpandAlembicBinding)
            or not callable(self.database_identity_establisher)
            or not callable(getattr(self.grant_matrix_verifier, "verify", None))
        ):
            raise DefaultExpandEnforcementInputError()

    def verify(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultTenantExpandEvidence:
        manifest = _manifest(invocation)
        qualification, applied, connection = self.alembic.run(
            expected_schema_head=manifest.tenant_schema_head,
        )
        try:
            identity = self.database_identity_establisher(connection, manifest)
            if not isinstance(identity, bytes) or len(identity) != 32:
                raise DefaultExpandEnforcementInputError()
        finally:
            connection.close()
        try:
            matrix = self.grant_matrix_verifier.verify()
        except Exception:
            raise DefaultExpandEnforcementInputError() from None
        if not isinstance(matrix, DefaultMySqlTenantGrantMatrixObservation):
            raise DefaultExpandEnforcementInputError()
        _require_heads(manifest.tenant_schema_head, qualification, applied)
        return DefaultTenantExpandEvidence(
            manifest_digest=manifest.digest,
            implementation_identity_digest=(
                manifest.implementation_identity_digest
            ),
            migration_bundle_digest=manifest.migration_bundle_digest,
            schema_head=manifest.tenant_schema_head,
            migration_round_trip_digest=qualification.digest,
            metadata_model_match_digest=_metadata_digest(
                qualification,
                applied,
            ),
            database_identity_observation_digest=identity,
            tenant_dml_grants_digest=matrix.dml_grants_digest,
            platform_read_grants_digest=matrix.platform_read_grants_digest,
            cross_schema_negative_digest=matrix.cross_schema_negative_digest,
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultTenantDatabaseIdentityEstablisher:
    schema_generation: int
    service: object = field(
        default_factory=DefaultTenantInPlaceRegistrationService,
        repr=False,
    )

    def __post_init__(self) -> None:
        if (
            isinstance(self.schema_generation, bool)
            or not isinstance(self.schema_generation, int)
            or self.schema_generation < 1
            or not callable(
                getattr(self.service, "write_tenant_database_identity", None)
            )
        ):
            raise DefaultExpandEnforcementInputError()

    def __call__(
        self,
        connection: Connection,
        manifest: DefaultTenantMigrationManifest,
    ) -> bytes:
        if (
            not isinstance(connection, Connection)
            or connection.in_transaction()
            or not isinstance(manifest, DefaultTenantMigrationManifest)
        ):
            raise DefaultExpandEnforcementInputError()
        try:
            with Session(bind=connection, expire_on_commit=False) as session:
                with session.begin():
                    result = self.service.write_tenant_database_identity(
                        session,
                        manifest=manifest,
                        schema_generation=self.schema_generation,
                    )
        except Exception:
            raise DefaultExpandEnforcementInputError() from None
        if (
            result.manifest_digest != manifest.digest
            or result.tenant_uuid != manifest.tenant_uuid
            or result.database_uuid != manifest.database_uuid
            or result.schema_generation != self.schema_generation
        ):
            raise DefaultExpandEnforcementInputError()
        return hashlib.sha256(
            json.dumps(
                {
                    "database_uuid": str(result.database_uuid),
                    "identity_created_at": (
                        result.identity_created_at.isoformat()
                    ),
                    "manifest_digest": result.manifest_digest.hex(),
                    "schema_generation": result.schema_generation,
                    "tenant_uuid": str(result.tenant_uuid),
                    "version": 1,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).digest()


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultControlInstallationMarkerObserver:
    expected_installation_fingerprint: str = field(repr=False)

    def __post_init__(self) -> None:
        if not _fingerprint(self.expected_installation_fingerprint):
            raise DefaultExpandEnforcementInputError()

    def __call__(self, connection: Connection) -> bytes:
        if not isinstance(connection, Connection) or connection.in_transaction():
            raise DefaultExpandEnforcementInputError()
        try:
            rows = tuple(
                connection.execute(
                    sa.select(
                        Installation.id,
                        Installation.marker_fingerprint,
                        Installation.row_version,
                        Installation.created_at,
                    )
                    .where(Installation.retired_at.is_(None))
                    .order_by(Installation.created_at, Installation.id)
                    .limit(2)
                ).mappings()
            )
            if len(rows) != 1:
                raise DefaultExpandEnforcementInputError()
            row = rows[0]
            if (
                set(row)
                != {
                    "id",
                    "marker_fingerprint",
                    "row_version",
                    "created_at",
                }
                or str(UUID(row["id"])) != row["id"]
                or row["marker_fingerprint"]
                != self.expected_installation_fingerprint
                or isinstance(row["row_version"], bool)
                or not isinstance(row["row_version"], int)
                or row["row_version"] < 1
            ):
                raise DefaultExpandEnforcementInputError()
            created_at = _as_utc(row["created_at"])
        except DefaultExpandEnforcementInputError:
            raise
        except Exception:
            raise DefaultExpandEnforcementInputError() from None
        finally:
            connection.rollback()
        return hashlib.sha256(
            json.dumps(
                {
                    "created_at": created_at.isoformat(),
                    "installation_fingerprint": (
                        self.expected_installation_fingerprint
                    ),
                    "installation_uuid": row["id"],
                    "row_version": row["row_version"],
                    "version": 1,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).digest()


def _fingerprint(value: object) -> bool:
    return bool(
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise DefaultExpandEnforcementInputError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _manifest(invocation: DefaultMigrationStepInvocation):
    if (
        not isinstance(invocation, DefaultMigrationStepInvocation)
        or invocation.phase_invocation.plan.phase is not MigrationPhase.EXPAND
    ):
        raise DefaultExpandEnforcementInputError()
    return invocation.phase_invocation.manifest


def _observed_digest(observer: DigestObserver, connection: Connection) -> bytes:
    try:
        value = observer(connection)
    except Exception:
        raise DefaultExpandEnforcementInputError() from None
    if not isinstance(value, bytes) or len(value) != 32:
        raise DefaultExpandEnforcementInputError()
    return value


def _bound_digest(observer: BoundDigestObserver) -> bytes:
    try:
        value = observer()
    except Exception:
        raise DefaultExpandEnforcementInputError() from None
    if not isinstance(value, bytes) or len(value) != 32:
        raise DefaultExpandEnforcementInputError()
    return value


def _require_heads(expected: str, *receipts: object) -> None:
    if any(getattr(receipt, "schema_head", None) != expected for receipt in receipts):
        raise DefaultExpandEnforcementInputError()


def _metadata_digest(
    qualification: DefaultSchemaQualificationReceipt,
    applied: DefaultSchemaApplyReceipt,
) -> bytes:
    return hashlib.sha256(
        json.dumps(
            {
                "apply_receipt": applied.digest.hex(),
                "qualification_receipt": qualification.digest.hex(),
                "version": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).digest()


__all__ = [
    "DefaultExpandAlembicBinding",
    "DefaultControlInstallationMarkerObserver",
    "DefaultTenantDatabaseIdentityEstablisher",
    "QualifiedDefaultControlExpandVerifier",
    "QualifiedDefaultTenantExpandVerifier",
]
