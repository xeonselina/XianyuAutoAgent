"""Ordered, idempotency-bound composition for default-migration phase steps."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from typing import Protocol

from .collection import DefaultMigrationReconciliationRunner
from .manifest import (
    MigrationEvidenceError,
    MigrationManifestMismatchError,
    MigrationOrderError,
    MigrationPhase,
)
from .reconciliation import ReconciliationPolicy
from .runner import (
    MigrationPhaseExecutionResult,
    MigrationPhaseInvocation,
)


_SAFE_STEP = re.compile(r"[a-z][a-z0-9_.:-]{0,63}")


@dataclass(frozen=True, slots=True, kw_only=True)
class DefaultMigrationStepInvocation:
    phase_invocation: MigrationPhaseInvocation
    step_name: str
    step_execution_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.phase_invocation, MigrationPhaseInvocation):
            raise TypeError("phase invocation is invalid")
        if (
            not isinstance(self.step_name, str)
            or _SAFE_STEP.fullmatch(self.step_name) is None
            or self.step_execution_key
            != _step_execution_key(
                self.phase_invocation.phase_execution_key,
                self.step_name,
            )
        ):
            raise MigrationEvidenceError("migration step invocation is invalid")


@dataclass(frozen=True, slots=True, kw_only=True)
class DefaultMigrationStepResult:
    step_name: str
    manifest_digest: bytes
    result_digest: bytes
    executor_reference: str

    def __post_init__(self) -> None:
        if (
            not isinstance(self.step_name, str)
            or _SAFE_STEP.fullmatch(self.step_name) is None
            or not isinstance(self.manifest_digest, bytes)
            or len(self.manifest_digest) != 32
            or not isinstance(self.result_digest, bytes)
            or len(self.result_digest) != 32
            or not isinstance(self.executor_reference, str)
            or _SAFE_STEP.fullmatch(self.executor_reference) is None
        ):
            raise MigrationEvidenceError("migration step result is invalid")


class DefaultMigrationPhaseStep(Protocol):
    @property
    def name(self) -> str: ...

    def execute(
        self,
        invocation: DefaultMigrationStepInvocation,
    ) -> DefaultMigrationStepResult: ...


@dataclass(frozen=True, slots=True)
class OrderedDefaultMigrationPhaseExecutor:
    """Execute every required non-backfill step in declared dependency order."""

    phase: MigrationPhase
    steps: tuple[DefaultMigrationPhaseStep, ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.phase, MigrationPhase)
            or self.phase is MigrationPhase.BACKFILL_VERIFY
        ):
            raise MigrationEvidenceError("ordered executor phase is invalid")
        _validate_steps(self.steps)

    def execute(
        self,
        invocation: MigrationPhaseInvocation,
    ) -> MigrationPhaseExecutionResult:
        _require_phase(invocation, self.phase)
        results = _execute_steps(invocation, self.steps)
        input_digest = _step_plan_digest(invocation, self.steps)
        result_digest = _step_results_digest(results)
        return MigrationPhaseExecutionResult(
            phase=self.phase,
            manifest_digest=invocation.manifest.digest,
            input_state_digest=input_digest,
            result_state_digest=result_digest,
            executor_reference=f"ordered-phase:{self.phase.value}",
        )


@dataclass(frozen=True, slots=True)
class ReconciledDefaultMigrationBackfillExecutor:
    """Run every backfill step, then collect and require passed reconciliation."""

    steps: tuple[DefaultMigrationPhaseStep, ...]
    policy: ReconciliationPolicy
    reconciliation_runner: DefaultMigrationReconciliationRunner

    def __post_init__(self) -> None:
        _validate_steps(self.steps)
        if not isinstance(self.policy, ReconciliationPolicy) or not isinstance(
            self.reconciliation_runner,
            DefaultMigrationReconciliationRunner,
        ):
            raise MigrationEvidenceError("backfill executor is invalid")

    def execute(
        self,
        invocation: MigrationPhaseInvocation,
    ) -> MigrationPhaseExecutionResult:
        _require_phase(invocation, MigrationPhase.BACKFILL_VERIFY)
        results = _execute_steps(invocation, self.steps)
        report = self.reconciliation_runner.collect_and_evaluate(
            manifest=invocation.manifest,
            policy=self.policy,
        )
        result_identity = hashlib.sha256(
            _step_results_digest(results) + report.report_digest
        ).hexdigest()[:32]
        return MigrationPhaseExecutionResult(
            phase=MigrationPhase.BACKFILL_VERIFY,
            manifest_digest=invocation.manifest.digest,
            input_state_digest=self.policy.digest,
            result_state_digest=report.report_digest,
            executor_reference=f"reconciled-backfill:{result_identity}",
            reconciliation_policy=self.policy,
            reconciliation_report=report,
        )


def _validate_steps(steps: object) -> None:
    if not isinstance(steps, tuple) or not steps:
        raise MigrationEvidenceError("migration steps are missing")
    try:
        names = tuple(item.name for item in steps)
    except Exception:
        raise MigrationEvidenceError("migration step is invalid") from None
    if (
        any(
            not isinstance(name, str) or _SAFE_STEP.fullmatch(name) is None
            for name in names
        )
        or len(names) != len(set(names))
    ):
        raise MigrationEvidenceError("migration step identity is invalid")


def _execute_steps(
    invocation: MigrationPhaseInvocation,
    steps: tuple[DefaultMigrationPhaseStep, ...],
) -> tuple[DefaultMigrationStepResult, ...]:
    results: list[DefaultMigrationStepResult] = []
    for step in steps:
        step_invocation = DefaultMigrationStepInvocation(
            phase_invocation=invocation,
            step_name=step.name,
            step_execution_key=_step_execution_key(
                invocation.phase_execution_key,
                step.name,
            ),
        )
        result = step.execute(step_invocation)
        if not isinstance(result, DefaultMigrationStepResult):
            raise MigrationEvidenceError("migration step returned invalid evidence")
        if result.step_name != step.name:
            raise MigrationOrderError("migration step returned another identity")
        if result.manifest_digest != invocation.manifest.digest:
            raise MigrationManifestMismatchError(
                "migration step result belongs to another manifest"
            )
        results.append(result)
    return tuple(results)


def _require_phase(
    invocation: MigrationPhaseInvocation,
    expected: MigrationPhase,
) -> None:
    if not isinstance(invocation, MigrationPhaseInvocation):
        raise MigrationEvidenceError("phase invocation is invalid")
    if invocation.plan.phase is not expected:
        raise MigrationOrderError("executor is composed for another phase")


def _step_execution_key(phase_execution_key: str, step_name: str) -> str:
    digest = hashlib.sha256(
        b"default-migration-step-v1\x00"
        + phase_execution_key.encode("ascii")
        + b"\x00"
        + step_name.encode("ascii")
    ).hexdigest()
    return f"default-step:{digest}"


def _step_plan_digest(
    invocation: MigrationPhaseInvocation,
    steps: tuple[DefaultMigrationPhaseStep, ...],
) -> bytes:
    return hashlib.sha256(
        json.dumps(
            {
                "manifest_digest": invocation.manifest.digest.hex(),
                "phase": invocation.plan.phase.value,
                "phase_execution_key": invocation.phase_execution_key,
                "steps": [item.name for item in steps],
                "version": 1,
            },
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).digest()


def _step_results_digest(
    results: tuple[DefaultMigrationStepResult, ...],
) -> bytes:
    return hashlib.sha256(
        json.dumps(
            [
                {
                    "executor_reference": item.executor_reference,
                    "result_digest": item.result_digest.hex(),
                    "step_name": item.step_name,
                }
                for item in results
            ],
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
    ).digest()


__all__ = [
    "DefaultMigrationPhaseStep",
    "DefaultMigrationStepInvocation",
    "DefaultMigrationStepResult",
    "OrderedDefaultMigrationPhaseExecutor",
    "ReconciledDefaultMigrationBackfillExecutor",
]
