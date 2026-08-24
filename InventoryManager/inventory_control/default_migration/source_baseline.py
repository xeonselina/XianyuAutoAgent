"""Portable, redacted evidence for one immutable migration source snapshot."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Mapping

from .manifest import DefaultTenantMigrationManifest


DEFAULT_SOURCE_BASELINE_FORMAT: Final = (
    "inventory-manager/default-source-baseline/v1"
)
_SCHEMA = re.compile(r"^[A-Za-z0-9_]{1,64}$", re.ASCII)
_BASELINE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}$", re.ASCII)
_MAX_TABLES: Final = 512
_DOCUMENT_KEYS: Final = frozenset(
    {
        "baseline_migration_id",
        "database_profile",
        "format_version",
        "row_count_digest",
        "schema_inventory_digest",
        "server_version",
        "source_schema_name",
        "source_snapshot_digest",
        "table_count",
        "total_rows",
    }
)


class DefaultSourceBaselineError(RuntimeError):
    code = "DEFAULT_SOURCE_BASELINE_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class DefaultSourceBaselineInputError(DefaultSourceBaselineError):
    code = "DEFAULT_SOURCE_BASELINE_INPUT_INVALID"


class DefaultSourceBaselineRejected(DefaultSourceBaselineError):
    code = "DEFAULT_SOURCE_BASELINE_REJECTED"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DefaultSourceBaselineEvidence:
    source_schema_name: str
    baseline_migration_id: str
    database_profile: str
    server_version: str
    table_count: int
    total_rows: int
    schema_inventory_digest: bytes
    row_count_digest: bytes
    source_snapshot_digest: bytes
    format_version: str = DEFAULT_SOURCE_BASELINE_FORMAT

    def __post_init__(self) -> None:
        if (
            self.format_version != DEFAULT_SOURCE_BASELINE_FORMAT
            or not isinstance(self.source_schema_name, str)
            or _SCHEMA.fullmatch(self.source_schema_name) is None
            or not isinstance(self.baseline_migration_id, str)
            or _BASELINE.fullmatch(self.baseline_migration_id) is None
            or self.database_profile not in {
                "mariadb-10.11",
                "mysql-8.0.30+",
            }
            or not isinstance(self.server_version, str)
            or not self.server_version
            or isinstance(self.table_count, bool)
            or not isinstance(self.table_count, int)
            or not 0 <= self.table_count <= _MAX_TABLES
            or isinstance(self.total_rows, bool)
            or not isinstance(self.total_rows, int)
            or self.total_rows < 0
            or any(
                not isinstance(value, bytes) or len(value) != 32
                for value in (
                    self.schema_inventory_digest,
                    self.row_count_digest,
                    self.source_snapshot_digest,
                )
            )
        ):
            raise DefaultSourceBaselineInputError()

    @property
    def digest(self) -> bytes:
        return source_baseline_payload_digest(
            source_baseline_evidence_to_document(self)
        )

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
            raise DefaultSourceBaselineRejected()

    def redacted_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "database_profile": self.database_profile,
                "evidence_digest": self.digest.hex(),
                "format_version": self.format_version,
                "source_schema_name": self.source_schema_name,
                "table_count": self.table_count,
                "total_rows": self.total_rows,
            }
        )

    def __repr__(self) -> str:
        return f"DefaultSourceBaselineEvidence(digest={self.digest.hex()!r})"


def source_baseline_evidence_to_document(
    evidence: DefaultSourceBaselineEvidence,
) -> dict[str, object]:
    if not isinstance(evidence, DefaultSourceBaselineEvidence):
        raise DefaultSourceBaselineInputError()
    return {
        "baseline_migration_id": evidence.baseline_migration_id,
        "database_profile": evidence.database_profile,
        "format_version": evidence.format_version,
        "row_count_digest": evidence.row_count_digest.hex(),
        "schema_inventory_digest": evidence.schema_inventory_digest.hex(),
        "server_version": evidence.server_version,
        "source_schema_name": evidence.source_schema_name,
        "source_snapshot_digest": evidence.source_snapshot_digest.hex(),
        "table_count": evidence.table_count,
        "total_rows": evidence.total_rows,
    }


def source_baseline_evidence_from_document(
    document: Mapping[str, object],
) -> DefaultSourceBaselineEvidence:
    if (
        not isinstance(document, Mapping)
        or set(document) != _DOCUMENT_KEYS
        or not all(isinstance(key, str) for key in document)
    ):
        raise DefaultSourceBaselineInputError()
    try:
        return DefaultSourceBaselineEvidence(
            format_version=_text(document["format_version"]),
            source_schema_name=_text(document["source_schema_name"]),
            baseline_migration_id=_text(document["baseline_migration_id"]),
            database_profile=_text(document["database_profile"]),
            server_version=_text(document["server_version"]),
            table_count=_integer(document["table_count"]),
            total_rows=_integer(document["total_rows"]),
            schema_inventory_digest=_hex_digest(
                document["schema_inventory_digest"]
            ),
            row_count_digest=_hex_digest(document["row_count_digest"]),
            source_snapshot_digest=_hex_digest(
                document["source_snapshot_digest"]
            ),
        )
    except DefaultSourceBaselineError:
        raise
    except (KeyError, TypeError, ValueError):
        raise DefaultSourceBaselineInputError() from None


def source_baseline_payload_digest(value: object) -> bytes:
    try:
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeEncodeError):
        raise DefaultSourceBaselineRejected() from None
    return hashlib.sha256(encoded).digest()


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise DefaultSourceBaselineInputError()
    return value


def _integer(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DefaultSourceBaselineInputError()
    return value


def _hex_digest(value: object) -> bytes:
    if not isinstance(value, str) or len(value) != 64:
        raise DefaultSourceBaselineInputError()
    try:
        decoded = bytes.fromhex(value)
    except ValueError:
        raise DefaultSourceBaselineInputError() from None
    if len(decoded) != 32:
        raise DefaultSourceBaselineInputError()
    return decoded


__all__ = [
    "DEFAULT_SOURCE_BASELINE_FORMAT",
    "DefaultSourceBaselineError",
    "DefaultSourceBaselineEvidence",
    "DefaultSourceBaselineInputError",
    "DefaultSourceBaselineRejected",
    "source_baseline_evidence_from_document",
    "source_baseline_evidence_to_document",
    "source_baseline_payload_digest",
]
