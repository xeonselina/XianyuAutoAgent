"""Machine evidence contract for database/jobs migration enforcement.

The evidence is produced by an explicitly injected isolated-environment
verifier.  This module cannot discover a DSN, mutate grants, start a worker,
or contact providers; it only makes a phase completion cryptographically bind
to the immutable migration and all required positive/negative test matrices.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from inventory_control.default_migration import DefaultTenantMigrationManifest


class DefaultDatabaseJobsEnforcementError(RuntimeError):
    code = "DEFAULT_DATABASE_JOBS_ENFORCEMENT_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class DefaultDatabaseJobsEnforcementInputError(
    DefaultDatabaseJobsEnforcementError
):
    code = "DEFAULT_DATABASE_JOBS_ENFORCEMENT_INPUT_INVALID"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultDatabaseJobsEnforcementEvidence:
    manifest_digest: bytes
    implementation_identity_digest: bytes
    migration_bundle_digest: bytes
    database_grants_matrix_digest: bytes
    schema_fleet_matrix_digest: bytes
    scheduler_negative_matrix_digest: bytes
    durable_worker_matrix_digest: bytes
    outbox_provider_fence_matrix_digest: bytes
    cross_schema_negative_matrix_digest: bytes
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
                    self.database_grants_matrix_digest,
                    self.schema_fleet_matrix_digest,
                    self.scheduler_negative_matrix_digest,
                    self.durable_worker_matrix_digest,
                    self.outbox_provider_fence_matrix_digest,
                    self.cross_schema_negative_matrix_digest,
                )
            )
            or not isinstance(self.production_write_identity_used, bool)
            or self.production_write_identity_used
            or isinstance(self.provider_side_effect_count, bool)
            or self.provider_side_effect_count != 0
            or isinstance(self.print_side_effect_count, bool)
            or self.print_side_effect_count != 0
        ):
            raise DefaultDatabaseJobsEnforcementInputError()

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
            raise DefaultDatabaseJobsEnforcementInputError()

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(
            json.dumps(
                {
                    "cross_schema_negative_matrix_digest": (
                        self.cross_schema_negative_matrix_digest.hex()
                    ),
                    "database_grants_matrix_digest": (
                        self.database_grants_matrix_digest.hex()
                    ),
                    "durable_worker_matrix_digest": (
                        self.durable_worker_matrix_digest.hex()
                    ),
                    "implementation_identity_digest": (
                        self.implementation_identity_digest.hex()
                    ),
                    "manifest_digest": self.manifest_digest.hex(),
                    "migration_bundle_digest": (
                        self.migration_bundle_digest.hex()
                    ),
                    "outbox_provider_fence_matrix_digest": (
                        self.outbox_provider_fence_matrix_digest.hex()
                    ),
                    "print_side_effect_count": self.print_side_effect_count,
                    "production_write_identity_used": (
                        self.production_write_identity_used
                    ),
                    "provider_side_effect_count": (
                        self.provider_side_effect_count
                    ),
                    "scheduler_negative_matrix_digest": (
                        self.scheduler_negative_matrix_digest.hex()
                    ),
                    "schema_fleet_matrix_digest": (
                        self.schema_fleet_matrix_digest.hex()
                    ),
                    "version": 1,
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).digest()

    def __repr__(self) -> str:
        return (
            "DefaultDatabaseJobsEnforcementEvidence("
            f"digest={self.digest.hex()!r}, side_effects=0)"
        )


__all__ = [
    "DefaultDatabaseJobsEnforcementError",
    "DefaultDatabaseJobsEnforcementEvidence",
    "DefaultDatabaseJobsEnforcementInputError",
]
