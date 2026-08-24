"""Negative-scan evidence contract for the default migration contract phase."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from inventory_control.default_migration import DefaultTenantMigrationManifest


class DefaultContractEnforcementError(RuntimeError):
    code = "DEFAULT_CONTRACT_ENFORCEMENT_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class DefaultContractEnforcementInputError(DefaultContractEnforcementError):
    code = "DEFAULT_CONTRACT_ENFORCEMENT_INPUT_INVALID"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultContractEnforcementEvidence:
    manifest_digest: bytes
    implementation_identity_digest: bytes
    migration_bundle_digest: bytes
    observation_window_digest: bytes
    legacy_schema_surface_negative_digest: bytes
    route_config_bundle_negative_digest: bytes
    recovery_path_negative_digest: bytes
    provider_snapshot_preservation_digest: bytes
    d61_legacy_authority_count: int = 0
    legacy_writer_authority_count: int = 0
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
                    self.observation_window_digest,
                    self.legacy_schema_surface_negative_digest,
                    self.route_config_bundle_negative_digest,
                    self.recovery_path_negative_digest,
                    self.provider_snapshot_preservation_digest,
                )
            )
            or any(
                isinstance(value, bool)
                or not isinstance(value, int)
                or value != 0
                for value in (
                    self.d61_legacy_authority_count,
                    self.legacy_writer_authority_count,
                    self.provider_side_effect_count,
                    self.print_side_effect_count,
                )
            )
            or not isinstance(self.production_write_identity_used, bool)
            or self.production_write_identity_used
        ):
            raise DefaultContractEnforcementInputError()

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
            raise DefaultContractEnforcementInputError()

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(
            json.dumps(
                {
                    "d61_legacy_authority_count": (
                        self.d61_legacy_authority_count
                    ),
                    "implementation_identity_digest": (
                        self.implementation_identity_digest.hex()
                    ),
                    "legacy_schema_surface_negative_digest": (
                        self.legacy_schema_surface_negative_digest.hex()
                    ),
                    "legacy_writer_authority_count": (
                        self.legacy_writer_authority_count
                    ),
                    "manifest_digest": self.manifest_digest.hex(),
                    "migration_bundle_digest": (
                        self.migration_bundle_digest.hex()
                    ),
                    "observation_window_digest": (
                        self.observation_window_digest.hex()
                    ),
                    "print_side_effect_count": self.print_side_effect_count,
                    "production_write_identity_used": (
                        self.production_write_identity_used
                    ),
                    "provider_side_effect_count": (
                        self.provider_side_effect_count
                    ),
                    "provider_snapshot_preservation_digest": (
                        self.provider_snapshot_preservation_digest.hex()
                    ),
                    "recovery_path_negative_digest": (
                        self.recovery_path_negative_digest.hex()
                    ),
                    "route_config_bundle_negative_digest": (
                        self.route_config_bundle_negative_digest.hex()
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
            "DefaultContractEnforcementEvidence("
            f"digest={self.digest.hex()!r}, legacy_authorities=0)"
        )


__all__ = [
    "DefaultContractEnforcementError",
    "DefaultContractEnforcementEvidence",
    "DefaultContractEnforcementInputError",
]
