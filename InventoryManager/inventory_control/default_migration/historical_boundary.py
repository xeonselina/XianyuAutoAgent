"""Redacted classification of legacy shipment and print history."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping

from .manifest import DefaultTenantMigrationManifest
from .source_baseline import (
    DefaultSourceBaselineError,
    DefaultSourceBaselineEvidence,
    source_baseline_evidence_from_document,
    source_baseline_evidence_to_document,
)


DEFAULT_HISTORICAL_BOUNDARY_FORMAT: Final = (
    "inventory-manager/default-historical-snapshot-boundary/v1"
)
DEFAULT_SOURCE_MIGRATION_PREFLIGHT_FORMAT: Final = (
    "inventory-manager/default-source-migration-preflight/v1"
)
HISTORICAL_BOUNDARY_COUNT_KEYS: Final = (
    "legacy_historical_rentals",
    "legacy_print_audits",
    "legacy_tracking_rows",
    "outbound_shipments",
    "provider_operation_attempts",
    "waybill_print_jobs",
)
_SCHEMA = re.compile(r"^[A-Za-z0-9_]{1,64}$", re.ASCII)
_BASELINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}$", re.ASCII)


class HistoricalSnapshotDisposition(str, Enum):
    EMPTY = "empty"
    REQUIRES_APPROVED_NONEMPTY_ADAPTER = (
        "requires_approved_nonempty_adapter"
    )


class DefaultHistoricalBoundaryError(RuntimeError):
    code = "DEFAULT_HISTORICAL_BOUNDARY_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class DefaultHistoricalBoundaryInputError(DefaultHistoricalBoundaryError):
    code = "DEFAULT_HISTORICAL_BOUNDARY_INPUT_INVALID"


class DefaultHistoricalBoundaryRejected(DefaultHistoricalBoundaryError):
    code = "DEFAULT_HISTORICAL_BOUNDARY_REJECTED"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultHistoricalSnapshotBoundaryEvidence:
    source_schema_name: str
    baseline_migration_id: str
    source_snapshot_digest: bytes
    counts: tuple[tuple[str, int], ...]
    disposition: HistoricalSnapshotDisposition
    format_version: str = DEFAULT_HISTORICAL_BOUNDARY_FORMAT

    def __post_init__(self) -> None:
        if not isinstance(self.counts, tuple):
            raise DefaultHistoricalBoundaryInputError()
        try:
            count_keys = tuple(key for key, _count in self.counts)
            counts_valid = all(
                isinstance(key, str)
                and not isinstance(count, bool)
                and isinstance(count, int)
                and count >= 0
                for key, count in self.counts
            )
        except (TypeError, ValueError):
            raise DefaultHistoricalBoundaryInputError() from None
        if (
            self.format_version != DEFAULT_HISTORICAL_BOUNDARY_FORMAT
            or not isinstance(self.source_schema_name, str)
            or _SCHEMA.fullmatch(self.source_schema_name) is None
            or not isinstance(self.baseline_migration_id, str)
            or _BASELINE.fullmatch(self.baseline_migration_id) is None
            or not isinstance(self.source_snapshot_digest, bytes)
            or len(self.source_snapshot_digest) != 32
            or count_keys != HISTORICAL_BOUNDARY_COUNT_KEYS
            or not counts_valid
            or not isinstance(self.disposition, HistoricalSnapshotDisposition)
        ):
            raise DefaultHistoricalBoundaryInputError()
        expected_disposition = (
            HistoricalSnapshotDisposition.EMPTY
            if all(count == 0 for _key, count in self.counts)
            else (
                HistoricalSnapshotDisposition.REQUIRES_APPROVED_NONEMPTY_ADAPTER
            )
        )
        if self.disposition is not expected_disposition:
            raise DefaultHistoricalBoundaryInputError()

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(
            json.dumps(
                {
                    "baseline_migration_id": self.baseline_migration_id,
                    "counts": list(self.counts),
                    "disposition": self.disposition.value,
                    "format_version": self.format_version,
                    "source_schema_name": self.source_schema_name,
                    "source_snapshot_digest": self.source_snapshot_digest.hex(),
                },
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
            ).encode("ascii")
        ).digest()

    def require_source_baseline(
        self,
        source_baseline: DefaultSourceBaselineEvidence,
    ) -> None:
        if (
            not isinstance(source_baseline, DefaultSourceBaselineEvidence)
            or source_baseline.source_schema_name != self.source_schema_name
            or source_baseline.baseline_migration_id
            != self.baseline_migration_id
            or source_baseline.source_snapshot_digest
            != self.source_snapshot_digest
        ):
            raise DefaultHistoricalBoundaryRejected()

    def require_manifest(
        self,
        manifest: DefaultTenantMigrationManifest,
    ) -> None:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or manifest.source_schema_name != self.source_schema_name
            or manifest.baseline_migration_id != self.baseline_migration_id
            or manifest.source_snapshot_digest != self.source_snapshot_digest
        ):
            raise DefaultHistoricalBoundaryRejected()

    def redacted_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "disposition": self.disposition.value,
                "evidence_digest": self.digest.hex(),
                "format_version": self.format_version,
                "nonzero_category_count": sum(
                    count != 0 for _key, count in self.counts
                ),
                "source_schema_name": self.source_schema_name,
            }
        )

    def __repr__(self) -> str:
        return (
            "DefaultHistoricalSnapshotBoundaryEvidence("
            f"digest={self.digest.hex()!r}, "
            f"disposition={self.disposition.value!r})"
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultSourceMigrationPreflightEvidence:
    source_baseline: DefaultSourceBaselineEvidence
    historical_boundary: DefaultHistoricalSnapshotBoundaryEvidence
    format_version: str = DEFAULT_SOURCE_MIGRATION_PREFLIGHT_FORMAT

    def __post_init__(self) -> None:
        if (
            self.format_version != DEFAULT_SOURCE_MIGRATION_PREFLIGHT_FORMAT
            or not isinstance(
                self.source_baseline,
                DefaultSourceBaselineEvidence,
            )
            or not isinstance(
                self.historical_boundary,
                DefaultHistoricalSnapshotBoundaryEvidence,
            )
        ):
            raise DefaultHistoricalBoundaryInputError()
        self.historical_boundary.require_source_baseline(self.source_baseline)

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(
            b"inventory-manager/default-source-migration-preflight/v1\x00"
            + self.source_baseline.digest
            + self.historical_boundary.digest
        ).digest()

    def require_manifest(
        self,
        manifest: DefaultTenantMigrationManifest,
    ) -> None:
        self.source_baseline.require_manifest(manifest)
        self.historical_boundary.require_manifest(manifest)

    def redacted_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "disposition": self.historical_boundary.disposition.value,
                "evidence_digest": self.digest.hex(),
                "source_schema_name": self.source_baseline.source_schema_name,
            }
        )

    def __repr__(self) -> str:
        return (
            "DefaultSourceMigrationPreflightEvidence("
            f"digest={self.digest.hex()!r}, "
            "details='<redacted>')"
        )


def historical_boundary_evidence_to_document(
    evidence: DefaultHistoricalSnapshotBoundaryEvidence,
) -> dict[str, object]:
    if not isinstance(evidence, DefaultHistoricalSnapshotBoundaryEvidence):
        raise DefaultHistoricalBoundaryInputError()
    return {
        "baseline_migration_id": evidence.baseline_migration_id,
        "counts": {key: count for key, count in evidence.counts},
        "disposition": evidence.disposition.value,
        "format_version": evidence.format_version,
        "source_schema_name": evidence.source_schema_name,
        "source_snapshot_digest": evidence.source_snapshot_digest.hex(),
    }


def historical_boundary_evidence_from_document(
    document: Mapping[str, object],
) -> DefaultHistoricalSnapshotBoundaryEvidence:
    expected_keys = {
        "baseline_migration_id",
        "counts",
        "disposition",
        "format_version",
        "source_schema_name",
        "source_snapshot_digest",
    }
    if not isinstance(document, Mapping) or set(document) != expected_keys:
        raise DefaultHistoricalBoundaryInputError()
    counts = document.get("counts")
    if not isinstance(counts, Mapping):
        raise DefaultHistoricalBoundaryInputError()
    try:
        count_keys = tuple(sorted(counts))
    except TypeError:
        raise DefaultHistoricalBoundaryInputError() from None
    if count_keys != HISTORICAL_BOUNDARY_COUNT_KEYS:
        raise DefaultHistoricalBoundaryInputError()
    try:
        digest_value = document["source_snapshot_digest"]
        if not isinstance(digest_value, str) or len(digest_value) != 64:
            raise DefaultHistoricalBoundaryInputError()
        source_snapshot_digest = bytes.fromhex(digest_value)
        return DefaultHistoricalSnapshotBoundaryEvidence(
            source_schema_name=document["source_schema_name"],
            baseline_migration_id=document["baseline_migration_id"],
            source_snapshot_digest=source_snapshot_digest,
            counts=tuple((key, counts[key]) for key in sorted(counts)),
            disposition=HistoricalSnapshotDisposition(
                document["disposition"]
            ),
            format_version=document["format_version"],
        )
    except DefaultHistoricalBoundaryError:
        raise
    except (KeyError, TypeError, ValueError):
        raise DefaultHistoricalBoundaryInputError() from None


def source_migration_preflight_to_document(
    evidence: DefaultSourceMigrationPreflightEvidence,
) -> dict[str, object]:
    if not isinstance(evidence, DefaultSourceMigrationPreflightEvidence):
        raise DefaultHistoricalBoundaryInputError()
    return {
        "format_version": evidence.format_version,
        "historical_boundary": historical_boundary_evidence_to_document(
            evidence.historical_boundary
        ),
        "source_baseline": source_baseline_evidence_to_document(
            evidence.source_baseline
        ),
    }


def source_migration_preflight_from_document(
    document: Mapping[str, object],
) -> DefaultSourceMigrationPreflightEvidence:
    if (
        not isinstance(document, Mapping)
        or set(document)
        != {"format_version", "historical_boundary", "source_baseline"}
        or document.get("format_version")
        != DEFAULT_SOURCE_MIGRATION_PREFLIGHT_FORMAT
    ):
        raise DefaultHistoricalBoundaryInputError()
    try:
        return DefaultSourceMigrationPreflightEvidence(
            format_version=document["format_version"],
            source_baseline=source_baseline_evidence_from_document(
                document["source_baseline"]
            ),
            historical_boundary=historical_boundary_evidence_from_document(
                document["historical_boundary"]
            ),
        )
    except (DefaultHistoricalBoundaryError, DefaultSourceBaselineError):
        raise
    except (KeyError, TypeError, ValueError):
        raise DefaultHistoricalBoundaryInputError() from None


__all__ = [
    "DEFAULT_HISTORICAL_BOUNDARY_FORMAT",
    "DEFAULT_SOURCE_MIGRATION_PREFLIGHT_FORMAT",
    "HISTORICAL_BOUNDARY_COUNT_KEYS",
    "DefaultHistoricalBoundaryError",
    "DefaultHistoricalBoundaryInputError",
    "DefaultHistoricalBoundaryRejected",
    "DefaultHistoricalSnapshotBoundaryEvidence",
    "DefaultSourceMigrationPreflightEvidence",
    "HistoricalSnapshotDisposition",
    "historical_boundary_evidence_from_document",
    "historical_boundary_evidence_to_document",
    "source_migration_preflight_from_document",
    "source_migration_preflight_to_document",
]
