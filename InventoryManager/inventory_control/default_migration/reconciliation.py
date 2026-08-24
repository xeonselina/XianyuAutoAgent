"""Pure, versioned reconciliation for the default-tenant migration.

Collectors may read a source snapshot, control database, and isolated target
schema, but this module performs no SQL.  It rejects missing coverage and
unknown values, treats schema identity drift as non-waivable, and permits a
bounded disposition only when the versioned policy explicitly allows it.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from types import MappingProxyType
from typing import Mapping

from .manifest import (
    DefaultTenantMigrationManifest,
    MigrationEvidenceError,
    MigrationExecutionPlan,
    MigrationJournal,
    MigrationManifestMismatchError,
    MigrationOrderError,
    MigrationPhase,
    _record_phase_completion,
)


_SAFE_KEY = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")
_SAFE_CODE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_DIGEST_BYTES = 32


class MigrationReconciliationError(ValueError):
    """A reconciliation document or policy is invalid."""


class ReconciliationScope(str, Enum):
    TABLE_ROW_COUNT = "table_row_count"
    MONETARY_AMOUNT = "monetary_amount"
    DEVICE_ASSOCIATION = "device_association"
    RENTAL_ASSOCIATION = "rental_association"
    ACCESSORY_ASSOCIATION = "accessory_association"
    ORPHAN_COUNT = "orphan_count"
    HISTORICAL_WAYBILL = "historical_waybill"
    CREDENTIAL_REVISION = "credential_revision"
    DEFAULT_WAREHOUSE = "default_warehouse"
    LEGACY_DOUBLE_COUNT = "legacy_double_count"
    SCHEMA_GENERATION = "schema_generation"
    SCHEMA_DIGEST = "schema_digest"


REQUIRED_RECONCILIATION_SCOPES = frozenset(ReconciliationScope)
_ZERO_TOLERANCE_SCOPES = frozenset(
    {
        ReconciliationScope.ORPHAN_COUNT,
        ReconciliationScope.LEGACY_DOUBLE_COUNT,
        ReconciliationScope.SCHEMA_GENERATION,
        ReconciliationScope.SCHEMA_DIGEST,
    }
)


class ReconciliationValueKind(str, Enum):
    NONNEGATIVE_INTEGER = "nonnegative_integer"
    POSITIVE_INTEGER = "positive_integer"
    SHA256_DIGEST = "sha256_digest"


class ReconciliationFindingStatus(str, Enum):
    MATCHED = "matched"
    DISPOSITIONED = "dispositioned"
    UNKNOWN = "unknown"
    MISMATCH = "mismatch"


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationRequirement:
    key: str
    scope: ReconciliationScope
    value_kind: ReconciliationValueKind
    expected: int | bytes
    tolerance: int
    disposition_allowed: bool

    def __post_init__(self) -> None:
        _safe_key(self.key)
        try:
            scope = ReconciliationScope(self.scope)
            kind = ReconciliationValueKind(self.value_kind)
        except (TypeError, ValueError):
            raise MigrationReconciliationError("requirement enum is invalid") from None
        object.__setattr__(self, "scope", scope)
        object.__setattr__(self, "value_kind", kind)
        _value(self.expected, kind, allow_unknown=False)
        if (
            isinstance(self.tolerance, bool)
            or not isinstance(self.tolerance, int)
            or self.tolerance < 0
        ):
            raise MigrationReconciliationError("requirement tolerance is invalid")
        if not isinstance(self.disposition_allowed, bool):
            raise MigrationReconciliationError("disposition policy is invalid")
        if kind is ReconciliationValueKind.SHA256_DIGEST and self.tolerance != 0:
            raise MigrationReconciliationError("digest tolerance must be zero")
        if self.scope in _ZERO_TOLERANCE_SCOPES and self.tolerance != 0:
            raise MigrationReconciliationError(
                "schema identity and anomaly tolerance must be zero"
            )
        if scope in {
            ReconciliationScope.SCHEMA_GENERATION,
            ReconciliationScope.SCHEMA_DIGEST,
            ReconciliationScope.LEGACY_DOUBLE_COUNT,
        } and self.disposition_allowed:
            raise MigrationReconciliationError(
                "schema and legacy authority checks are non-waivable"
            )
        if (
            scope is ReconciliationScope.SCHEMA_DIGEST
            and kind is not ReconciliationValueKind.SHA256_DIGEST
        ):
            raise MigrationReconciliationError("schema digest kind is invalid")
        if (
            scope is ReconciliationScope.SCHEMA_GENERATION
            and kind is not ReconciliationValueKind.POSITIVE_INTEGER
        ):
            raise MigrationReconciliationError("schema generation kind is invalid")
        if (
            scope in {
                ReconciliationScope.ORPHAN_COUNT,
                ReconciliationScope.LEGACY_DOUBLE_COUNT,
            }
            and self.expected != 0
        ):
            raise MigrationReconciliationError("anomaly count must expect zero")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationPolicy:
    policy_version: int
    requirements: tuple[ReconciliationRequirement, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.policy_version, bool)
            or not isinstance(self.policy_version, int)
            or self.policy_version < 1
        ):
            raise MigrationReconciliationError("policy version is invalid")
        if not isinstance(self.requirements, tuple) or not self.requirements:
            raise MigrationReconciliationError("policy requirements are missing")
        if not all(
            isinstance(item, ReconciliationRequirement)
            for item in self.requirements
        ):
            raise MigrationReconciliationError("policy requirement is invalid")
        keys = tuple(item.key for item in self.requirements)
        if len(keys) != len(set(keys)) or keys != tuple(sorted(keys)):
            raise MigrationReconciliationError(
                "policy requirement keys must be unique and sorted"
            )
        scopes = frozenset(item.scope for item in self.requirements)
        if scopes != REQUIRED_RECONCILIATION_SCOPES:
            raise MigrationReconciliationError(
                "policy does not cover every required reconciliation scope"
            )

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(self.canonical_bytes()).digest()

    def canonical_bytes(self) -> bytes:
        payload = {
            "policy_version": self.policy_version,
            "requirements": [
                {
                    "disposition_allowed": item.disposition_allowed,
                    "expected": _encoded_value(item.expected),
                    "key": item.key,
                    "scope": item.scope.value,
                    "tolerance": item.tolerance,
                    "value_kind": item.value_kind.value,
                }
                for item in self.requirements
            ],
        }
        return _canonical_json(payload)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationDisposition:
    reason_code: str
    evidence_digest: bytes

    def __post_init__(self) -> None:
        if not isinstance(self.reason_code, str) or _SAFE_CODE.fullmatch(
            self.reason_code
        ) is None:
            raise MigrationReconciliationError("disposition reason is invalid")
        _digest(self.evidence_digest)


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationObservation:
    key: str
    observed: int | bytes | None
    disposition: ReconciliationDisposition | None = None

    def __post_init__(self) -> None:
        _safe_key(self.key)
        if self.observed is not None and not isinstance(self.observed, (int, bytes)):
            raise MigrationReconciliationError("observed value is invalid")
        if isinstance(self.observed, bool):
            raise MigrationReconciliationError("observed value is invalid")
        if self.disposition is not None and not isinstance(
            self.disposition, ReconciliationDisposition
        ):
            raise MigrationReconciliationError("disposition is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationFinding:
    key: str
    scope: ReconciliationScope
    status: ReconciliationFindingStatus
    blocking: bool
    safe_reason_code: str

    def __post_init__(self) -> None:
        _safe_key(self.key)
        try:
            object.__setattr__(self, "scope", ReconciliationScope(self.scope))
            object.__setattr__(
                self,
                "status",
                ReconciliationFindingStatus(self.status),
            )
        except (TypeError, ValueError):
            raise MigrationReconciliationError("finding is invalid") from None
        if not isinstance(self.blocking, bool):
            raise MigrationReconciliationError("finding blocking flag is invalid")
        if not isinstance(self.safe_reason_code, str) or _SAFE_CODE.fullmatch(
            self.safe_reason_code
        ) is None:
            raise MigrationReconciliationError("finding reason is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class ReconciliationReport:
    manifest_digest: bytes
    source_snapshot_digest: bytes
    policy_digest: bytes
    findings: tuple[ReconciliationFinding, ...]
    report_digest: bytes

    def __post_init__(self) -> None:
        for digest in (
            self.manifest_digest,
            self.source_snapshot_digest,
            self.policy_digest,
            self.report_digest,
        ):
            _digest(digest)
        if not isinstance(self.findings, tuple) or not self.findings:
            raise MigrationReconciliationError("report findings are missing")
        if not all(isinstance(item, ReconciliationFinding) for item in self.findings):
            raise MigrationReconciliationError("report finding is invalid")
        keys = tuple(item.key for item in self.findings)
        if keys != tuple(sorted(keys)) or len(keys) != len(set(keys)):
            raise MigrationReconciliationError("report findings are not canonical")

    @property
    def passed(self) -> bool:
        return not any(item.blocking for item in self.findings)

    def redacted_summary(self) -> Mapping[str, object]:
        counts = {
            status.value: sum(item.status is status for item in self.findings)
            for status in ReconciliationFindingStatus
        }
        return MappingProxyType(
            {
                "manifest_digest": self.manifest_digest.hex(),
                "policy_digest": self.policy_digest.hex(),
                "report_digest": self.report_digest.hex(),
                "passed": self.passed,
                "finding_counts": MappingProxyType(counts),
            }
        )


def evaluate_reconciliation(
    manifest: DefaultTenantMigrationManifest,
    policy: ReconciliationPolicy,
    observations: tuple[ReconciliationObservation, ...],
) -> ReconciliationReport:
    if not isinstance(manifest, DefaultTenantMigrationManifest):
        raise MigrationReconciliationError("manifest is invalid")
    if not isinstance(policy, ReconciliationPolicy):
        raise MigrationReconciliationError("policy is invalid")
    if not isinstance(observations, tuple) or not all(
        isinstance(item, ReconciliationObservation) for item in observations
    ):
        raise MigrationReconciliationError("observations are invalid")
    by_key: dict[str, ReconciliationObservation] = {}
    for item in observations:
        if item.key in by_key:
            raise MigrationReconciliationError("observation key is duplicated")
        by_key[item.key] = item
    required_keys = {item.key for item in policy.requirements}
    if set(by_key) != required_keys:
        raise MigrationReconciliationError(
            "observations must exactly cover the versioned policy"
        )

    findings: list[ReconciliationFinding] = []
    report_items: list[dict[str, object]] = []
    for requirement in policy.requirements:
        observation = by_key[requirement.key]
        status, blocking, reason = _evaluate(requirement, observation)
        findings.append(
            ReconciliationFinding(
                key=requirement.key,
                scope=requirement.scope,
                status=status,
                blocking=blocking,
                safe_reason_code=reason,
            )
        )
        report_items.append(
            {
                "disposition": (
                    None
                    if observation.disposition is None
                    else {
                        "evidence_digest": observation.disposition.evidence_digest.hex(),
                        "reason_code": observation.disposition.reason_code,
                    }
                ),
                "expected": _encoded_value(requirement.expected),
                "key": requirement.key,
                "observed": _encoded_value(observation.observed),
                "safe_reason_code": reason,
                "scope": requirement.scope.value,
                "status": status.value,
            }
        )
    report_digest = hashlib.sha256(
        _canonical_json(
            {
                "findings": report_items,
                "manifest_digest": manifest.digest.hex(),
                "policy_digest": policy.digest.hex(),
                "source_snapshot_digest": manifest.source_snapshot_digest.hex(),
            }
        )
    ).digest()
    return ReconciliationReport(
        manifest_digest=manifest.digest,
        source_snapshot_digest=manifest.source_snapshot_digest,
        policy_digest=policy.digest,
        findings=tuple(findings),
        report_digest=report_digest,
    )


def record_backfill_verification_completion(
    manifest: DefaultTenantMigrationManifest,
    journal: MigrationJournal,
    *,
    plan: MigrationExecutionPlan,
    policy: ReconciliationPolicy,
    report: ReconciliationReport,
    completed_at: datetime,
    executor_reference: str,
) -> MigrationJournal:
    """Record a passed, identity-bound reconciliation as backfill evidence.

    The journal evidence stores only the manifest, policy, and report digests;
    observations, expected values, disposition material, and customer data do
    not cross this boundary.
    """

    if not isinstance(policy, ReconciliationPolicy):
        raise MigrationReconciliationError(
            "reconciliation policy identity is missing or invalid"
        )
    if not isinstance(report, ReconciliationReport):
        raise MigrationReconciliationError(
            "reconciliation report identity is missing or invalid"
        )
    if not isinstance(plan, MigrationExecutionPlan):
        raise MigrationReconciliationError("migration plan is invalid")
    if plan.phase is not MigrationPhase.BACKFILL_VERIFY:
        raise MigrationOrderError(
            "reconciliation evidence can only complete backfill/verify"
        )
    if report.manifest_digest != manifest.digest:
        raise MigrationManifestMismatchError(
            "reconciliation report belongs to another immutable manifest"
        )
    if report.source_snapshot_digest != manifest.source_snapshot_digest:
        raise MigrationManifestMismatchError(
            "reconciliation report belongs to another source snapshot"
        )
    if report.policy_digest != policy.digest:
        raise MigrationReconciliationError(
            "reconciliation report belongs to another policy"
        )

    expected_identity = tuple(
        (requirement.key, requirement.scope)
        for requirement in policy.requirements
    )
    report_identity = tuple(
        (finding.key, finding.scope) for finding in report.findings
    )
    if report_identity != expected_identity:
        raise MigrationReconciliationError(
            "reconciliation report does not cover its policy identity"
        )
    if any(
        finding.status is ReconciliationFindingStatus.DISPOSITIONED
        and not requirement.disposition_allowed
        for requirement, finding in zip(
            policy.requirements,
            report.findings,
            strict=True,
        )
    ):
        raise MigrationEvidenceError(
            "non-waivable reconciliation findings cannot complete backfill/verify"
        )
    if any(
        finding.status is ReconciliationFindingStatus.UNKNOWN
        for finding in report.findings
    ):
        raise MigrationEvidenceError(
            "unknown reconciliation findings cannot complete backfill/verify"
        )
    if not report.passed or any(
        finding.status
        not in {
            ReconciliationFindingStatus.MATCHED,
            ReconciliationFindingStatus.DISPOSITIONED,
        }
        for finding in report.findings
    ):
        raise MigrationEvidenceError(
            "failed reconciliation cannot complete backfill/verify"
        )

    return _record_phase_completion(
        manifest,
        journal,
        plan=plan,
        input_state_digest=policy.digest,
        result_state_digest=report.report_digest,
        completed_at=completed_at,
        executor_reference=executor_reference,
        reconciliation_validated=True,
    )


def _evaluate(
    requirement: ReconciliationRequirement,
    observation: ReconciliationObservation,
) -> tuple[ReconciliationFindingStatus, bool, str]:
    if observation.observed is None:
        return ReconciliationFindingStatus.UNKNOWN, True, "observation_unknown"
    try:
        _value(observation.observed, requirement.value_kind, allow_unknown=False)
    except MigrationReconciliationError:
        return ReconciliationFindingStatus.MISMATCH, True, "observation_type_mismatch"
    matched = _matches(requirement, observation.observed)
    if matched:
        if observation.disposition is not None:
            return ReconciliationFindingStatus.MISMATCH, True, "unexpected_disposition"
        return ReconciliationFindingStatus.MATCHED, False, "matched"
    disposition = observation.disposition
    if disposition is not None and requirement.disposition_allowed:
        return (
            ReconciliationFindingStatus.DISPOSITIONED,
            False,
            disposition.reason_code,
        )
    if disposition is not None:
        return ReconciliationFindingStatus.MISMATCH, True, "disposition_not_allowed"
    return ReconciliationFindingStatus.MISMATCH, True, "undispositioned_difference"


def _matches(requirement: ReconciliationRequirement, observed: int | bytes) -> bool:
    if requirement.value_kind is ReconciliationValueKind.SHA256_DIGEST:
        return bool(observed == requirement.expected)
    assert isinstance(observed, int) and isinstance(requirement.expected, int)
    return abs(observed - requirement.expected) <= requirement.tolerance


def _value(
    value: int | bytes | None,
    kind: ReconciliationValueKind,
    *,
    allow_unknown: bool,
) -> None:
    if value is None:
        if allow_unknown:
            return
        raise MigrationReconciliationError("value is unknown")
    if kind is ReconciliationValueKind.SHA256_DIGEST:
        _digest(value)
        return
    minimum = 1 if kind is ReconciliationValueKind.POSITIVE_INTEGER else 0
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise MigrationReconciliationError("integer value is invalid")


def _safe_key(value: str) -> None:
    if not isinstance(value, str) or _SAFE_KEY.fullmatch(value) is None:
        raise MigrationReconciliationError("reconciliation key is invalid")


def _digest(value: object) -> None:
    if not isinstance(value, bytes) or len(value) != _DIGEST_BYTES:
        raise MigrationReconciliationError("digest is invalid")


def _encoded_value(value: int | bytes | None) -> int | str | None:
    return value.hex() if isinstance(value, bytes) else value


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


__all__ = [
    "MigrationReconciliationError",
    "REQUIRED_RECONCILIATION_SCOPES",
    "ReconciliationDisposition",
    "ReconciliationFinding",
    "ReconciliationFindingStatus",
    "ReconciliationObservation",
    "ReconciliationPolicy",
    "ReconciliationReport",
    "ReconciliationRequirement",
    "ReconciliationScope",
    "ReconciliationValueKind",
    "evaluate_reconciliation",
    "record_backfill_verification_completion",
]
