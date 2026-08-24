"""Bound evidence returned by explicit control/tenant expand verifiers."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from inventory_control.default_migration import DefaultTenantMigrationManifest


class DefaultExpandEnforcementError(RuntimeError):
    code = "DEFAULT_EXPAND_ENFORCEMENT_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class DefaultExpandEnforcementInputError(DefaultExpandEnforcementError):
    code = "DEFAULT_EXPAND_ENFORCEMENT_INPUT_INVALID"


def _base_valid(*values: object) -> bool:
    return all(isinstance(value, bytes) and len(value) == 32 for value in values)


def _side_effects_valid(
    production_write_identity_used: object,
    provider_side_effect_count: object,
    print_side_effect_count: object,
) -> bool:
    return bool(
        isinstance(production_write_identity_used, bool)
        and not production_write_identity_used
        and isinstance(provider_side_effect_count, int)
        and not isinstance(provider_side_effect_count, bool)
        and provider_side_effect_count == 0
        and isinstance(print_side_effect_count, int)
        and not isinstance(print_side_effect_count, bool)
        and print_side_effect_count == 0
    )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultControlExpandEvidence:
    manifest_digest: bytes
    implementation_identity_digest: bytes
    migration_bundle_digest: bytes
    schema_head: str
    migration_round_trip_digest: bytes
    metadata_model_match_digest: bytes
    control_account_grants_digest: bytes
    installation_marker_digest: bytes
    production_write_identity_used: bool = False
    provider_side_effect_count: int = 0
    print_side_effect_count: int = 0

    def __post_init__(self) -> None:
        if (
            not _base_valid(
                self.manifest_digest,
                self.implementation_identity_digest,
                self.migration_bundle_digest,
                self.migration_round_trip_digest,
                self.metadata_model_match_digest,
                self.control_account_grants_digest,
                self.installation_marker_digest,
            )
            or not isinstance(self.schema_head, str)
            or not self.schema_head
            or not _side_effects_valid(
                self.production_write_identity_used,
                self.provider_side_effect_count,
                self.print_side_effect_count,
            )
        ):
            raise DefaultExpandEnforcementInputError()

    def require_manifest(self, manifest: DefaultTenantMigrationManifest) -> None:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or self.manifest_digest != manifest.digest
            or self.implementation_identity_digest
            != manifest.implementation_identity_digest
            or self.migration_bundle_digest
            != manifest.migration_bundle_digest
            or self.schema_head != manifest.control_schema_head
        ):
            raise DefaultExpandEnforcementInputError()

    @property
    def digest(self) -> bytes:
        return _digest_document(
            {
                "control_account_grants_digest": (
                    self.control_account_grants_digest.hex()
                ),
                "implementation_identity_digest": (
                    self.implementation_identity_digest.hex()
                ),
                "installation_marker_digest": (
                    self.installation_marker_digest.hex()
                ),
                "manifest_digest": self.manifest_digest.hex(),
                "metadata_model_match_digest": (
                    self.metadata_model_match_digest.hex()
                ),
                "migration_bundle_digest": self.migration_bundle_digest.hex(),
                "migration_round_trip_digest": (
                    self.migration_round_trip_digest.hex()
                ),
                "schema_head": self.schema_head,
                "side_effects": 0,
                "version": 1,
            }
        )

    def __repr__(self) -> str:
        return f"DefaultControlExpandEvidence(digest={self.digest.hex()!r})"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultTenantExpandEvidence:
    manifest_digest: bytes
    implementation_identity_digest: bytes
    migration_bundle_digest: bytes
    schema_head: str
    migration_round_trip_digest: bytes
    metadata_model_match_digest: bytes
    database_identity_observation_digest: bytes
    tenant_dml_grants_digest: bytes
    platform_read_grants_digest: bytes
    cross_schema_negative_digest: bytes
    production_write_identity_used: bool = False
    provider_side_effect_count: int = 0
    print_side_effect_count: int = 0

    def __post_init__(self) -> None:
        if (
            not _base_valid(
                self.manifest_digest,
                self.implementation_identity_digest,
                self.migration_bundle_digest,
                self.migration_round_trip_digest,
                self.metadata_model_match_digest,
                self.database_identity_observation_digest,
                self.tenant_dml_grants_digest,
                self.platform_read_grants_digest,
                self.cross_schema_negative_digest,
            )
            or not isinstance(self.schema_head, str)
            or not self.schema_head
            or not _side_effects_valid(
                self.production_write_identity_used,
                self.provider_side_effect_count,
                self.print_side_effect_count,
            )
        ):
            raise DefaultExpandEnforcementInputError()

    def require_manifest(self, manifest: DefaultTenantMigrationManifest) -> None:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or self.manifest_digest != manifest.digest
            or self.implementation_identity_digest
            != manifest.implementation_identity_digest
            or self.migration_bundle_digest
            != manifest.migration_bundle_digest
            or self.schema_head != manifest.tenant_schema_head
        ):
            raise DefaultExpandEnforcementInputError()

    @property
    def digest(self) -> bytes:
        return _digest_document(
            {
                "cross_schema_negative_digest": (
                    self.cross_schema_negative_digest.hex()
                ),
                "database_identity_observation_digest": (
                    self.database_identity_observation_digest.hex()
                ),
                "implementation_identity_digest": (
                    self.implementation_identity_digest.hex()
                ),
                "manifest_digest": self.manifest_digest.hex(),
                "metadata_model_match_digest": (
                    self.metadata_model_match_digest.hex()
                ),
                "migration_bundle_digest": self.migration_bundle_digest.hex(),
                "migration_round_trip_digest": (
                    self.migration_round_trip_digest.hex()
                ),
                "platform_read_grants_digest": (
                    self.platform_read_grants_digest.hex()
                ),
                "schema_head": self.schema_head,
                "side_effects": 0,
                "tenant_dml_grants_digest": (
                    self.tenant_dml_grants_digest.hex()
                ),
                "version": 1,
            }
        )

    def __repr__(self) -> str:
        return f"DefaultTenantExpandEvidence(digest={self.digest.hex()!r})"


def _digest_document(value: dict[str, object]) -> bytes:
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).digest()


__all__ = [
    "DefaultControlExpandEvidence",
    "DefaultExpandEnforcementError",
    "DefaultExpandEnforcementInputError",
    "DefaultTenantExpandEvidence",
]
