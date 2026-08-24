"""Complete, boundary-aware orchestration for the default migration bundle."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Callable, Mapping

from .manifest import (
    DefaultTenantMigrationManifest,
    MigrationBoundaryError,
    MigrationEvidenceError,
    MigrationExecutionMode,
    MigrationJournal,
    MigrationOrderError,
    MigrationPhase,
)
from .persistence import MigrationJournalFileStore
from .runner import (
    DefaultMigrationPhaseExecutor,
    DefaultMigrationRunner,
    MigrationPhaseRun,
)


_PRE_AUTHORITY_PHASES = (
    MigrationPhase.EXPAND,
    MigrationPhase.BACKFILL_VERIFY,
    MigrationPhase.APPLICATION_ENFORCE,
    MigrationPhase.DATABASE_JOBS_ENFORCE,
)


@dataclass(frozen=True, slots=True)
class DefaultMigrationCommandRun:
    runs: tuple[MigrationPhaseRun, ...]
    journal: MigrationJournal

    def redacted_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "executed": [dict(item.redacted_summary()) for item in self.runs],
                "next_phase": (
                    None
                    if self.journal.next_phase is None
                    else self.journal.next_phase.value
                ),
                "tenant_aware_writes_authoritative": (
                    self.journal.tenant_aware_writes_enabled_at is not None
                ),
                "legacy_rollback_allowed": self.journal.legacy_rollback_allowed,
            }
        )


class DefaultMigrationCommand:
    """Drive a complete registry but never cross authority implicitly."""

    def __init__(
        self,
        journal_store: MigrationJournalFileStore,
        *,
        executors: Mapping[MigrationPhase, DefaultMigrationPhaseExecutor],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        if not isinstance(journal_store, MigrationJournalFileStore):
            raise TypeError("journal store is invalid")
        if not isinstance(executors, Mapping):
            raise MigrationEvidenceError("complete executor registry is required")
        try:
            frozen = {phase: executors[phase] for phase in MigrationPhase}
        except (KeyError, TypeError):
            raise MigrationEvidenceError(
                "complete executor registry is required"
            ) from None
        if len(executors) != len(MigrationPhase) or any(
            not callable(getattr(executor, "execute", None))
            for executor in frozen.values()
        ):
            raise MigrationEvidenceError(
                "complete executor registry is required"
            )
        self._store = journal_store
        self._executors = MappingProxyType(frozen)
        self._runner = DefaultMigrationRunner(journal_store, clock=clock)

    def run_to_authoritative_boundary(
        self,
        manifest: DefaultTenantMigrationManifest,
    ) -> DefaultMigrationCommandRun:
        """Apply every remaining pre-authority phase, then always stop."""

        if not isinstance(manifest, DefaultTenantMigrationManifest):
            raise TypeError("manifest is invalid")
        runs: list[MigrationPhaseRun] = []
        while True:
            journal = self._store.load()
            phase = journal.next_phase
            if phase not in _PRE_AUTHORITY_PHASES:
                return DefaultMigrationCommandRun(
                    runs=tuple(runs),
                    journal=journal,
                )
            runs.append(
                self._runner.run_phase(
                    manifest,
                    phase=phase,
                    mode=MigrationExecutionMode.APPLY,
                    executor=self._executors[phase],
                )
            )

    def mark_tenant_aware_writes_authoritative(
        self,
        manifest: DefaultTenantMigrationManifest,
        *,
        enabled_at: datetime,
    ) -> MigrationJournal:
        """Expose the existing explicit one-way CAS without an implicit time."""

        journal = self._store.load()
        if journal.next_phase is not MigrationPhase.CONTRACT:
            raise MigrationOrderError(
                "authority marker requires all pre-authority phases"
            )
        return self._runner.mark_tenant_aware_writes_authoritative(
            manifest,
            enabled_at=enabled_at,
        )

    def run_contract(
        self,
        manifest: DefaultTenantMigrationManifest,
    ) -> DefaultMigrationCommandRun:
        """Run contract only after a separately durable authority marker."""

        journal = self._store.load()
        if journal.next_phase is None:
            return DefaultMigrationCommandRun(runs=(), journal=journal)
        if journal.next_phase is not MigrationPhase.CONTRACT:
            raise MigrationOrderError(
                "contract requires all pre-authority phases"
            )
        if journal.tenant_aware_writes_enabled_at is None:
            raise MigrationBoundaryError(
                "contract requires the authoritative-write marker"
            )
        run = self._runner.run_phase(
            manifest,
            phase=MigrationPhase.CONTRACT,
            mode=MigrationExecutionMode.APPLY,
            executor=self._executors[MigrationPhase.CONTRACT],
        )
        return DefaultMigrationCommandRun(
            runs=(run,),
            journal=self._store.load(),
        )


__all__ = ["DefaultMigrationCommand", "DefaultMigrationCommandRun"]
