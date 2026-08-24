"""Crash-resumable orchestration for one default-tenant migration phase.

The runner is deliberately persistence- and executor-oriented instead of
database-aware.  Production and rehearsal composition must explicitly supply
an executor that owns the applicable database identities and schema-operation
fences.  A dry run never calls that executor.  An apply invocation binds the
executor to a stable per-manifest/per-phase key and only appends immutable
completion evidence after the executor reports a complete result.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping, Protocol

from .manifest import (
    DefaultTenantMigrationManifest,
    MigrationBoundaryError,
    MigrationEvidenceError,
    MigrationExecutionMode,
    MigrationExecutionPlan,
    MigrationJournal,
    MigrationManifestMismatchError,
    MigrationOrderError,
    MigrationPhase,
    MigrationPhaseEvidence,
    build_execution_plan,
    mark_tenant_aware_writes_authoritative,
    record_phase_completion,
)
from .persistence import (
    MigrationJournalFileStore,
    MigrationJournalPersistenceError,
)
from .reconciliation import (
    ReconciliationPolicy,
    ReconciliationReport,
    record_backfill_verification_completion,
)


_DIGEST_BYTES = 32


class MigrationPhaseRunOutcome(str, Enum):
    PLANNED = "planned"
    COMPLETED = "completed"
    REPLAYED = "replayed"


@dataclass(frozen=True, slots=True, kw_only=True)
class MigrationPhaseInvocation:
    """Identity-bound input handed to an explicitly composed phase executor."""

    manifest: DefaultTenantMigrationManifest
    plan: MigrationExecutionPlan
    phase_execution_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.manifest, DefaultTenantMigrationManifest):
            raise TypeError("manifest is invalid")
        if not isinstance(self.plan, MigrationExecutionPlan):
            raise TypeError("migration plan is invalid")
        if self.plan.manifest_digest != self.manifest.digest:
            raise MigrationManifestMismatchError(
                "migration invocation belongs to another manifest"
            )
        expected = _phase_execution_key(self.manifest, self.plan.phase)
        if self.phase_execution_key != expected:
            raise MigrationEvidenceError("phase execution key is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class MigrationPhaseExecutionResult:
    """Minimal, log-safe evidence returned after an executor finishes.

    Backfill/verify additionally carries the exact versioned policy and report.
    The runner checks that their identities equal the two public digests before
    allowing journal completion.
    """

    phase: MigrationPhase
    manifest_digest: bytes
    input_state_digest: bytes
    result_state_digest: bytes
    executor_reference: str
    reconciliation_policy: ReconciliationPolicy | None = None
    reconciliation_report: ReconciliationReport | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.phase, MigrationPhase):
            raise MigrationEvidenceError("execution result phase is invalid")
        for value in (
            self.manifest_digest,
            self.input_state_digest,
            self.result_state_digest,
        ):
            if not isinstance(value, bytes) or len(value) != _DIGEST_BYTES:
                raise MigrationEvidenceError("execution result digest is invalid")
        if not isinstance(self.executor_reference, str):
            raise MigrationEvidenceError("executor reference is invalid")
        has_policy = self.reconciliation_policy is not None
        has_report = self.reconciliation_report is not None
        if has_policy != has_report:
            raise MigrationEvidenceError(
                "backfill reconciliation policy and report must be paired"
            )
        if self.phase is MigrationPhase.BACKFILL_VERIFY:
            if not has_policy:
                raise MigrationEvidenceError(
                    "backfill execution requires reconciliation evidence"
                )
            assert self.reconciliation_policy is not None
            assert self.reconciliation_report is not None
            if self.input_state_digest != self.reconciliation_policy.digest:
                raise MigrationEvidenceError(
                    "backfill input digest does not match its policy"
                )
            if self.result_state_digest != self.reconciliation_report.report_digest:
                raise MigrationEvidenceError(
                    "backfill result digest does not match its report"
                )
        elif has_policy:
            raise MigrationEvidenceError(
                "reconciliation evidence is only valid for backfill/verify"
            )


class DefaultMigrationPhaseExecutor(Protocol):
    """Explicit adapter boundary for one idempotent phase execution."""

    def execute(
        self,
        invocation: MigrationPhaseInvocation,
    ) -> MigrationPhaseExecutionResult: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class MigrationPhaseRun:
    outcome: MigrationPhaseRunOutcome
    phase: MigrationPhase
    manifest_digest: bytes
    phase_execution_key: str
    plan: MigrationExecutionPlan | None
    evidence: MigrationPhaseEvidence | None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, MigrationPhaseRunOutcome):
            raise TypeError("migration run outcome is invalid")
        if not isinstance(self.phase, MigrationPhase):
            raise TypeError("migration run phase is invalid")
        if not isinstance(self.manifest_digest, bytes) or len(
            self.manifest_digest
        ) != _DIGEST_BYTES:
            raise TypeError("migration run manifest digest is invalid")
        if self.outcome is MigrationPhaseRunOutcome.PLANNED:
            if self.plan is None or self.evidence is not None:
                raise TypeError("planned run shape is invalid")
        elif self.evidence is None:
            raise TypeError("completed run evidence is missing")

    def redacted_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "outcome": self.outcome.value,
                "phase": self.phase.value,
                "manifest_digest": self.manifest_digest.hex(),
                "phase_execution_key": self.phase_execution_key,
                "mutations_allowed": bool(
                    self.plan is not None and self.plan.mutations_allowed
                ),
                "provider_or_print_side_effects_allowed": False,
                "executor_reference": (
                    None
                    if self.evidence is None
                    else self.evidence.executor_reference
                ),
            }
        )


class DefaultMigrationRunner:
    """Plan or execute exactly one ordered phase against a durable journal."""

    def __init__(
        self,
        journal_store: MigrationJournalFileStore,
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(journal_store, MigrationJournalFileStore):
            raise TypeError("journal store is invalid")
        self._store = journal_store
        self._clock = clock or (lambda: datetime.now(timezone.utc))

    def run_phase(
        self,
        manifest: DefaultTenantMigrationManifest,
        *,
        phase: MigrationPhase,
        mode: MigrationExecutionMode,
        executor: DefaultMigrationPhaseExecutor | None = None,
    ) -> MigrationPhaseRun:
        """Run or replay one explicit phase without skipping dependencies."""

        if not isinstance(manifest, DefaultTenantMigrationManifest):
            raise TypeError("manifest is invalid")
        if not isinstance(phase, MigrationPhase):
            raise TypeError("migration phase is invalid")
        if not isinstance(mode, MigrationExecutionMode):
            raise TypeError("execution mode is invalid")
        journal = self._store.load()
        _require_manifest(journal, manifest)
        key = _phase_execution_key(manifest, phase)
        existing = _evidence_for_phase(journal, phase)
        if existing is not None:
            return MigrationPhaseRun(
                outcome=MigrationPhaseRunOutcome.REPLAYED,
                phase=phase,
                manifest_digest=manifest.digest,
                phase_execution_key=key,
                plan=None,
                evidence=existing,
            )

        plan = build_execution_plan(
            manifest,
            journal,
            mode=mode,
            requested_phase=phase,
        )
        if mode is MigrationExecutionMode.DRY_RUN:
            return MigrationPhaseRun(
                outcome=MigrationPhaseRunOutcome.PLANNED,
                phase=phase,
                manifest_digest=manifest.digest,
                phase_execution_key=key,
                plan=plan,
                evidence=None,
            )
        if executor is None:
            raise MigrationEvidenceError("apply requires an explicit phase executor")

        result = executor.execute(
            MigrationPhaseInvocation(
                manifest=manifest,
                plan=plan,
                phase_execution_key=key,
            )
        )
        self._validate_result(manifest, phase, result)
        replacement = self._completed_journal(
            manifest,
            journal,
            plan=plan,
            result=result,
        )
        try:
            persisted = self._store.compare_and_swap(
                manifest,
                expected=journal,
                replacement=replacement,
            )
            outcome = MigrationPhaseRunOutcome.COMPLETED
        except MigrationJournalPersistenceError:
            persisted = self._store.load()
            _require_manifest(persisted, manifest)
            durable = _evidence_for_phase(persisted, phase)
            if durable is None or not _same_execution_result(durable, result):
                raise
            outcome = MigrationPhaseRunOutcome.REPLAYED
        evidence = _evidence_for_phase(persisted, phase)
        assert evidence is not None
        return MigrationPhaseRun(
            outcome=outcome,
            phase=phase,
            manifest_digest=manifest.digest,
            phase_execution_key=key,
            plan=plan,
            evidence=evidence,
        )

    def mark_tenant_aware_writes_authoritative(
        self,
        manifest: DefaultTenantMigrationManifest,
        *,
        enabled_at: datetime,
    ) -> MigrationJournal:
        """Persist the explicit, one-way writer-authority boundary."""

        journal = self._store.load()
        _require_manifest(journal, manifest)
        if journal.tenant_aware_writes_enabled_at is not None:
            replacement = mark_tenant_aware_writes_authoritative(
                manifest,
                journal,
                enabled_at=enabled_at,
            )
            return replacement
        if (
            not isinstance(enabled_at, datetime)
            or enabled_at.tzinfo is None
            or enabled_at.utcoffset() is None
        ):
            raise MigrationBoundaryError(
                "authoritative-write time must be timezone-aware"
            )
        now = self._clock()
        if (
            not isinstance(now, datetime)
            or now.tzinfo is None
            or now.utcoffset() is None
        ):
            raise MigrationBoundaryError("migration clock is invalid")
        if enabled_at.astimezone(timezone.utc) > now.astimezone(timezone.utc):
            raise MigrationBoundaryError(
                "authoritative-write marker cannot be in the future"
            )
        replacement = mark_tenant_aware_writes_authoritative(
            manifest,
            journal,
            enabled_at=enabled_at,
        )
        return self._store.compare_and_swap(
            manifest,
            expected=journal,
            replacement=replacement,
        )

    def _completed_journal(
        self,
        manifest: DefaultTenantMigrationManifest,
        journal: MigrationJournal,
        *,
        plan: MigrationExecutionPlan,
        result: MigrationPhaseExecutionResult,
    ) -> MigrationJournal:
        completed_at = self._clock()
        if result.phase is MigrationPhase.BACKFILL_VERIFY:
            assert result.reconciliation_policy is not None
            assert result.reconciliation_report is not None
            return record_backfill_verification_completion(
                manifest,
                journal,
                plan=plan,
                policy=result.reconciliation_policy,
                report=result.reconciliation_report,
                completed_at=completed_at,
                executor_reference=result.executor_reference,
            )
        return record_phase_completion(
            manifest,
            journal,
            plan=plan,
            input_state_digest=result.input_state_digest,
            result_state_digest=result.result_state_digest,
            completed_at=completed_at,
            executor_reference=result.executor_reference,
        )

    @staticmethod
    def _validate_result(
        manifest: DefaultTenantMigrationManifest,
        phase: MigrationPhase,
        result: MigrationPhaseExecutionResult,
    ) -> None:
        if not isinstance(result, MigrationPhaseExecutionResult):
            raise MigrationEvidenceError("phase executor returned invalid evidence")
        if result.manifest_digest != manifest.digest:
            raise MigrationManifestMismatchError(
                "phase result belongs to another manifest"
            )
        if result.phase is not phase:
            raise MigrationOrderError("phase executor returned another phase")


def _phase_execution_key(
    manifest: DefaultTenantMigrationManifest,
    phase: MigrationPhase,
) -> str:
    digest = hashlib.sha256(
        b"default-tenant-migration-phase-v1\x00"
        + manifest.digest
        + b"\x00"
        + phase.value.encode("ascii")
    ).hexdigest()
    return f"default-migration:{digest}"


def _require_manifest(
    journal: MigrationJournal,
    manifest: DefaultTenantMigrationManifest,
) -> None:
    if journal.manifest_digest != manifest.digest:
        raise MigrationManifestMismatchError(
            "journal belongs to another immutable manifest"
        )


def _evidence_for_phase(
    journal: MigrationJournal,
    phase: MigrationPhase,
) -> MigrationPhaseEvidence | None:
    return next((item for item in journal.completed if item.phase is phase), None)


def _same_execution_result(
    evidence: MigrationPhaseEvidence,
    result: MigrationPhaseExecutionResult,
) -> bool:
    return bool(
        evidence.phase is result.phase
        and evidence.manifest_digest == result.manifest_digest
        and evidence.input_state_digest == result.input_state_digest
        and evidence.result_state_digest == result.result_state_digest
        and evidence.executor_reference == result.executor_reference
    )


__all__ = [
    "DefaultMigrationPhaseExecutor",
    "DefaultMigrationRunner",
    "MigrationPhaseExecutionResult",
    "MigrationPhaseInvocation",
    "MigrationPhaseRun",
    "MigrationPhaseRunOutcome",
]
