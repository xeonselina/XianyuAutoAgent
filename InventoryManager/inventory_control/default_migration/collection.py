"""Deterministic orchestration for default-migration reconciliation collectors.

Concrete collectors are composed with read-only source/control/tenant handles
outside this module.  The runner requires exact versioned-policy coverage,
collects in canonical key order, converts adapter failures to a stable safe
error, and never returns a successful report when any value is unknown or any
difference remains blocking.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping, Protocol

from .manifest import DefaultTenantMigrationManifest
from .reconciliation import (
    MigrationReconciliationError,
    ReconciliationObservation,
    ReconciliationPolicy,
    ReconciliationReport,
    ReconciliationRequirement,
    evaluate_reconciliation,
)


class MigrationReconciliationCollectionError(MigrationReconciliationError):
    """Collector coverage or execution failed without exposing observed data."""

    code = "MIGRATION_RECONCILIATION_COLLECTION_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class MigrationReconciliationBlockedError(MigrationReconciliationError):
    """A complete report contains at least one blocking finding."""

    code = "MIGRATION_RECONCILIATION_BLOCKED"

    def __init__(self, report: ReconciliationReport) -> None:
        if not isinstance(report, ReconciliationReport) or report.passed:
            raise TypeError("blocked reconciliation report is invalid")
        self.report = report
        super().__init__(self.code)

    def redacted_summary(self) -> Mapping[str, object]:
        return MappingProxyType(dict(self.report.redacted_summary()))


class DefaultMigrationReconciliationCollector(Protocol):
    """One explicitly composed read-only collector for one policy key."""

    @property
    def key(self) -> str: ...

    def collect(
        self,
        *,
        manifest: DefaultTenantMigrationManifest,
        requirement: ReconciliationRequirement,
    ) -> ReconciliationObservation: ...


@dataclass(frozen=True, slots=True)
class DefaultMigrationReconciliationRunner:
    collectors: tuple[DefaultMigrationReconciliationCollector, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.collectors, tuple) or not self.collectors:
            raise MigrationReconciliationCollectionError()
        try:
            keys = tuple(item.key for item in self.collectors)
        except Exception:
            raise MigrationReconciliationCollectionError() from None
        if (
            any(not isinstance(key, str) for key in keys)
            or len(keys) != len(set(keys))
            or keys != tuple(sorted(keys))
        ):
            raise MigrationReconciliationCollectionError()

    def collect_and_evaluate(
        self,
        *,
        manifest: DefaultTenantMigrationManifest,
        policy: ReconciliationPolicy,
    ) -> ReconciliationReport:
        if not isinstance(manifest, DefaultTenantMigrationManifest) or not isinstance(
            policy, ReconciliationPolicy
        ):
            raise MigrationReconciliationCollectionError()
        requirements = policy.requirements
        required_keys = tuple(item.key for item in requirements)
        collector_keys = tuple(item.key for item in self.collectors)
        if collector_keys != required_keys:
            raise MigrationReconciliationCollectionError()

        observations: list[ReconciliationObservation] = []
        for requirement, collector in zip(
            requirements,
            self.collectors,
            strict=True,
        ):
            try:
                observation = collector.collect(
                    manifest=manifest,
                    requirement=requirement,
                )
            except Exception:
                raise MigrationReconciliationCollectionError() from None
            if (
                not isinstance(observation, ReconciliationObservation)
                or observation.key != requirement.key
            ):
                raise MigrationReconciliationCollectionError()
            observations.append(observation)

        report = evaluate_reconciliation(
            manifest,
            policy,
            tuple(observations),
        )
        if not report.passed:
            raise MigrationReconciliationBlockedError(report)
        return report


__all__ = [
    "DefaultMigrationReconciliationCollector",
    "DefaultMigrationReconciliationRunner",
    "MigrationReconciliationBlockedError",
    "MigrationReconciliationCollectionError",
]
