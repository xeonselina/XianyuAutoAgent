"""Manifest-bound machine evidence for the legacy double-count boundary.

Database row counts cannot prove that an old reader, writer, global provider
configuration, or child-rental quantity source is no longer authoritative.
This collector therefore consumes an independently produced negative-matrix
observation and exposes only the required zero anomaly count to the ordinary
default-tenant reconciliation runner.  It performs no discovery and accepts
no DSN, credential, provider adapter, or printer adapter.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .collection import MigrationReconciliationCollectionError
from .manifest import DefaultTenantMigrationManifest
from .reconciliation import (
    ReconciliationObservation,
    ReconciliationRequirement,
    ReconciliationScope,
    ReconciliationValueKind,
)


_EVIDENCE_VERSION = 1
_LEGACY_DOUBLE_COUNT_KEY = "legacy.double_count"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultLegacyAuthorityBoundaryEvidence:
    """Negative-matrix result bound to one immutable migration candidate."""

    manifest_digest: bytes
    source_snapshot_digest: bytes
    implementation_identity_digest: bytes
    migration_bundle_digest: bytes
    legacy_quantity_negative_digest: bytes
    legacy_child_rental_negative_digest: bytes
    legacy_global_provider_negative_digest: bytes
    legacy_shipment_writer_negative_digest: bytes
    legacy_quantity_authority_count: int = 0
    legacy_child_rental_authority_count: int = 0
    legacy_global_provider_authority_count: int = 0
    legacy_shipment_writer_authority_count: int = 0

    def __post_init__(self) -> None:
        digests = (
            self.manifest_digest,
            self.source_snapshot_digest,
            self.implementation_identity_digest,
            self.migration_bundle_digest,
            self.legacy_quantity_negative_digest,
            self.legacy_child_rental_negative_digest,
            self.legacy_global_provider_negative_digest,
            self.legacy_shipment_writer_negative_digest,
        )
        counts = (
            self.legacy_quantity_authority_count,
            self.legacy_child_rental_authority_count,
            self.legacy_global_provider_authority_count,
            self.legacy_shipment_writer_authority_count,
        )
        if any(
            not isinstance(value, bytes) or len(value) != 32
            for value in digests
        ) or any(
            isinstance(value, bool)
            or not isinstance(value, int)
            or value != 0
            for value in counts
        ):
            raise MigrationReconciliationCollectionError()

    def require_manifest(
        self,
        manifest: DefaultTenantMigrationManifest,
    ) -> None:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or self.manifest_digest != manifest.digest
            or self.source_snapshot_digest != manifest.source_snapshot_digest
            or self.implementation_identity_digest
            != manifest.implementation_identity_digest
            or self.migration_bundle_digest
            != manifest.migration_bundle_digest
        ):
            raise MigrationReconciliationCollectionError()

    @property
    def digest(self) -> bytes:
        payload = {
            "implementation_identity_digest": (
                self.implementation_identity_digest.hex()
            ),
            "legacy_child_rental_authority_count": (
                self.legacy_child_rental_authority_count
            ),
            "legacy_child_rental_negative_digest": (
                self.legacy_child_rental_negative_digest.hex()
            ),
            "legacy_global_provider_authority_count": (
                self.legacy_global_provider_authority_count
            ),
            "legacy_global_provider_negative_digest": (
                self.legacy_global_provider_negative_digest.hex()
            ),
            "legacy_quantity_authority_count": (
                self.legacy_quantity_authority_count
            ),
            "legacy_quantity_negative_digest": (
                self.legacy_quantity_negative_digest.hex()
            ),
            "legacy_shipment_writer_authority_count": (
                self.legacy_shipment_writer_authority_count
            ),
            "legacy_shipment_writer_negative_digest": (
                self.legacy_shipment_writer_negative_digest.hex()
            ),
            "manifest_digest": self.manifest_digest.hex(),
            "migration_bundle_digest": self.migration_bundle_digest.hex(),
            "source_snapshot_digest": self.source_snapshot_digest.hex(),
            "version": _EVIDENCE_VERSION,
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).digest()

    def __repr__(self) -> str:
        return (
            "DefaultLegacyAuthorityBoundaryEvidence("
            f"digest={self.digest.hex()!r}, remaining_authorities=0)"
        )


@dataclass(frozen=True, slots=True)
class DefaultLegacyDoubleCountCollector:
    """Adapt the bound negative matrix to one non-waivable zero count."""

    evidence: DefaultLegacyAuthorityBoundaryEvidence
    key: str = _LEGACY_DOUBLE_COUNT_KEY

    def __post_init__(self) -> None:
        if (
            not isinstance(
                self.evidence,
                DefaultLegacyAuthorityBoundaryEvidence,
            )
            or self.key != _LEGACY_DOUBLE_COUNT_KEY
        ):
            raise MigrationReconciliationCollectionError()

    def collect(
        self,
        *,
        manifest: DefaultTenantMigrationManifest,
        requirement: ReconciliationRequirement,
    ) -> ReconciliationObservation:
        if (
            not isinstance(requirement, ReconciliationRequirement)
            or requirement.key != self.key
            or requirement.scope is not ReconciliationScope.LEGACY_DOUBLE_COUNT
            or requirement.value_kind
            is not ReconciliationValueKind.NONNEGATIVE_INTEGER
            or requirement.expected != 0
            or requirement.tolerance != 0
            or requirement.disposition_allowed
        ):
            raise MigrationReconciliationCollectionError()
        self.evidence.require_manifest(manifest)
        return ReconciliationObservation(key=self.key, observed=0)


__all__ = [
    "DefaultLegacyAuthorityBoundaryEvidence",
    "DefaultLegacyDoubleCountCollector",
]
