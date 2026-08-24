"""Pure D11/D60/D64 default-tenant migration planning.

This module deliberately performs no SQL, filesystem, provider, or printing
operation.  It binds every migration run to immutable, non-secret inputs and
provides the ordered phase, resume, dry-run, and rollback boundary that an
eventual CLI/persistence adapter must enforce.

Display names and canonical Admin phone numbers are represented only by
caller-produced keyed input commitments.  They are never rendered by the
manifest, because an ordinary SHA-256 of a phone number would be enumerable.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from types import MappingProxyType
from typing import Final, Mapping
from uuid import UUID


MIGRATION_MANIFEST_VERSION: Final[int] = 1
_DIGEST_BYTES: Final[int] = 32
_SAFE_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}", re.ASCII)
_SCHEMA_NAME = re.compile(r"[A-Za-z0-9_]{1,64}", re.ASCII)
_SCHEMA_HEAD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", re.ASCII)


class MigrationManifestError(ValueError):
    """The immutable manifest is structurally invalid."""


class MigrationManifestMismatchError(MigrationManifestError):
    """A journal/evidence item belongs to another immutable manifest."""


class MigrationOrderError(MigrationManifestError):
    """A phase was attempted outside the fixed dependency order."""


class MigrationEvidenceError(MigrationManifestError):
    """Completion evidence is incomplete, conflicting, or dry-run only."""


class MigrationBoundaryError(MigrationManifestError):
    """A requested rollback or contract action crosses the safe boundary."""


class MigrationPhase(str, Enum):
    EXPAND = "expand"
    BACKFILL_VERIFY = "backfill_verify"
    APPLICATION_ENFORCE = "application_enforce"
    DATABASE_JOBS_ENFORCE = "database_jobs_enforce"
    CONTRACT = "contract"


MIGRATION_PHASE_ORDER: Final[tuple[MigrationPhase, ...]] = (
    MigrationPhase.EXPAND,
    MigrationPhase.BACKFILL_VERIFY,
    MigrationPhase.APPLICATION_ENFORCE,
    MigrationPhase.DATABASE_JOBS_ENFORCE,
    MigrationPhase.CONTRACT,
)


class MigrationExecutionMode(str, Enum):
    DRY_RUN = "dry_run"
    APPLY = "apply"


@dataclass(frozen=True, slots=True)
class _PhaseContract:
    prerequisites: tuple[str, ...]
    completion_conditions: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    rollback_action: str


_PHASE_CONTRACTS: Final[Mapping[MigrationPhase, _PhaseContract]] = (
    MappingProxyType(
        {
            MigrationPhase.EXPAND: _PhaseContract(
                prerequisites=(
                    "manifest inputs and bundle identities validate",
                    "source schema baseline is captured with read-only queries",
                    "D61 legacy credentials are excluded from Core revisions",
                ),
                completion_conditions=(
                    "control and tenant expand heads exactly match the manifest",
                    "database_identity and unpublished route bind the immutable UUIDs",
                    "rerun finds the same baseline, identity, and installation anchors",
                ),
                stop_conditions=(
                    "source schema identity or schema head differs from the manifest",
                    "an existing database_identity or route binds different UUIDs",
                    "a secret legacy provider value would be imported",
                ),
                rollback_action=(
                    "stop Core writers and retain expand metadata, database_identity, "
                    "and audit facts; do not delete them to simulate a clean rollback"
                ),
            ),
            MigrationPhase.BACKFILL_VERIFY: _PhaseContract(
                prerequisites=(
                    "expand completion evidence matches this manifest",
                    "source identity and schema generation remain unchanged",
                    "real provider, printing, and customer-data test side effects are disabled",
                ),
                completion_conditions=(
                    "warehouse/logistics/accessory/integration/shipment transforms reconcile",
                    "row counts, amounts, relationships, orphans, and schema digest reconcile",
                    "stable source identities make an identical rerun a no-op",
                ),
                stop_conditions=(
                    "any unknown schema drift or non-zero undispositioned difference exists",
                    "a transform would double-count legacy and Core facts",
                    "a provider revision depends on a D61 legacy credential",
                ),
                rollback_action=(
                    "disable Core readers/writers and preserve reversible expand/backfill "
                    "lineage for diagnosis; the old application remains authoritative"
                ),
            ),
            MigrationPhase.APPLICATION_ENFORCE: _PhaseContract(
                prerequisites=(
                    "backfill and reconciliation evidence is complete",
                    "tenant session, membership, gate, and trusted route checks pass",
                    "legacy and Core writers are not active concurrently",
                ),
                completion_conditions=(
                    "all supported application paths use trusted tenant routing",
                    "unrouted, cross-tenant, stale-session, and stale-gate requests fail closed",
                    "legacy provider and scheduler entry points remain isolated",
                ),
                stop_conditions=(
                    "a supported path still selects a database from untrusted input",
                    "a legacy global writer or provider fallback can execute",
                    "identity, RBAC, gate, or route negative tests differ",
                ),
                rollback_action=(
                    "before the authoritative-write marker, stop Core processes and restore "
                    "the tested old application without reversing expand/backfill records"
                ),
            ),
            MigrationPhase.DATABASE_JOBS_ENFORCE: _PhaseContract(
                prerequisites=(
                    "application enforcement evidence is complete",
                    "tenant DML, platform-read, control, and provisioner identities are distinct",
                    "durable worker/outbox/provider fencing tests pass",
                ),
                completion_conditions=(
                    "database grants and current schema generations match the manifest",
                    "Web scheduling is disabled and one durable worker owns scheduled work",
                    "cross-schema DML and stale lease/provider submissions are rejected",
                ),
                stop_conditions=(
                    "a broad legacy account is required by Core runtime",
                    "a tenant schema is drifted or outside the compatible version range",
                    "duplicate scheduler, job, outbox, or provider submission remains possible",
                ),
                rollback_action=(
                    "before the authoritative-write marker only, disable Core jobs/routes and "
                    "restore the tested old writer; afterward use tenant-aware rollback or forward-fix"
                ),
            ),
            MigrationPhase.CONTRACT: _PhaseContract(
                prerequisites=(
                    "tenant-aware writes are already the recorded authority",
                    "the required production observation and reconciliation are complete",
                    "no supported reader, writer, job, restore path, or rollback uses legacy surfaces",
                ),
                completion_conditions=(
                    "legacy fields, accounts, scheduler paths, fallbacks, and flags are unreachable",
                    "route/config/bundle/restore negative scans pass",
                    "historical audit, provider snapshots, and migration evidence remain preserved",
                ),
                stop_conditions=(
                    "any supported runtime or rollback still depends on a legacy surface",
                    "D61 legacy authority or a global writer remains usable",
                    "negative scans or recovery-path verification differ",
                ),
                rollback_action=(
                    "legacy-writer rollback is forbidden; deploy a compatible tenant-aware "
                    "version or forward-fix while preserving authoritative facts"
                ),
            ),
        }
    )
)


@dataclass(frozen=True, slots=True)
class DefaultTenantMigrationManifest:
    """Immutable, safely renderable identity for one migration bundle/run."""

    migration_idempotency_key: str
    tenant_uuid: UUID
    database_uuid: UUID
    source_schema_name: str
    baseline_migration_id: str
    core_plan_revision_uuid: UUID
    control_schema_head: str
    tenant_schema_head: str
    source_snapshot_digest: bytes
    implementation_identity_digest: bytes
    migration_bundle_digest: bytes
    display_name_input_commitment: bytes
    first_admin_phone_input_commitment: bytes
    manifest_version: int = MIGRATION_MANIFEST_VERSION

    def __post_init__(self) -> None:
        if self.manifest_version != MIGRATION_MANIFEST_VERSION:
            raise MigrationManifestError("unsupported migration manifest version")
        _safe_id(self.migration_idempotency_key, "migration_idempotency_key")
        _uuid(self.tenant_uuid, "tenant_uuid")
        _uuid(self.database_uuid, "database_uuid")
        if self.tenant_uuid == self.database_uuid:
            raise MigrationManifestError("tenant and database UUIDs must differ")
        if not isinstance(self.source_schema_name, str) or _SCHEMA_NAME.fullmatch(
            self.source_schema_name
        ) is None:
            raise MigrationManifestError("source_schema_name is invalid")
        _safe_id(self.baseline_migration_id, "baseline_migration_id")
        _uuid(self.core_plan_revision_uuid, "core_plan_revision_uuid")
        _schema_head(self.control_schema_head, "control_schema_head")
        _schema_head(self.tenant_schema_head, "tenant_schema_head")
        for value, name in (
            (self.source_snapshot_digest, "source_snapshot_digest"),
            (self.implementation_identity_digest, "implementation_identity_digest"),
            (self.migration_bundle_digest, "migration_bundle_digest"),
            (self.display_name_input_commitment, "display_name_input_commitment"),
            (
                self.first_admin_phone_input_commitment,
                "first_admin_phone_input_commitment",
            ),
        ):
            _digest(value, name)

    @property
    def digest(self) -> bytes:
        return hashlib.sha256(self.canonical_bytes()).digest()

    def canonical_bytes(self) -> bytes:
        payload = {
            "baseline_migration_id": self.baseline_migration_id,
            "control_schema_head": self.control_schema_head,
            "core_plan_revision_uuid": str(self.core_plan_revision_uuid),
            "database_uuid": str(self.database_uuid),
            "display_name_input_commitment": self.display_name_input_commitment.hex(),
            "first_admin_phone_input_commitment": (
                self.first_admin_phone_input_commitment.hex()
            ),
            "implementation_identity_digest": (
                self.implementation_identity_digest.hex()
            ),
            "manifest_version": self.manifest_version,
            "migration_bundle_digest": self.migration_bundle_digest.hex(),
            "migration_idempotency_key": self.migration_idempotency_key,
            "source_schema_name": self.source_schema_name,
            "source_snapshot_digest": self.source_snapshot_digest.hex(),
            "tenant_schema_head": self.tenant_schema_head,
            "tenant_uuid": str(self.tenant_uuid),
        }
        return json.dumps(
            payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")

    def redacted_summary(self) -> Mapping[str, object]:
        """Return a log-safe view without enumerable identity commitments."""

        return MappingProxyType(
            {
                "manifest_version": self.manifest_version,
                "manifest_digest": self.digest.hex(),
                "migration_idempotency_key": self.migration_idempotency_key,
                "tenant_uuid": str(self.tenant_uuid),
                "database_uuid": str(self.database_uuid),
                "source_schema_name": self.source_schema_name,
                "baseline_migration_id": self.baseline_migration_id,
                "core_plan_revision_uuid": str(self.core_plan_revision_uuid),
                "control_schema_head": self.control_schema_head,
                "tenant_schema_head": self.tenant_schema_head,
                "sensitive_inputs_bound": True,
            }
        )


@dataclass(frozen=True, slots=True)
class MigrationPhaseEvidence:
    phase: MigrationPhase
    manifest_digest: bytes
    input_state_digest: bytes
    result_state_digest: bytes
    completed_at: datetime
    executor_reference: str
    evidence_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.phase, MigrationPhase):
            raise MigrationEvidenceError("phase is invalid")
        for value, name in (
            (self.manifest_digest, "manifest_digest"),
            (self.input_state_digest, "input_state_digest"),
            (self.result_state_digest, "result_state_digest"),
        ):
            _digest(value, name)
        object.__setattr__(
            self,
            "completed_at",
            _utc(self.completed_at, "completed_at"),
        )
        _safe_id(self.executor_reference, "executor_reference")
        if self.evidence_version != 1:
            raise MigrationEvidenceError("unsupported evidence version")


@dataclass(frozen=True, slots=True)
class MigrationJournal:
    manifest_digest: bytes
    completed: tuple[MigrationPhaseEvidence, ...] = ()
    tenant_aware_writes_enabled_at: datetime | None = None

    def __post_init__(self) -> None:
        _digest(self.manifest_digest, "manifest_digest")
        if not isinstance(self.completed, tuple):
            raise MigrationEvidenceError("completed evidence must be a tuple")
        expected_prefix = MIGRATION_PHASE_ORDER[: len(self.completed)]
        actual = tuple(item.phase for item in self.completed)
        if actual != expected_prefix:
            raise MigrationOrderError("migration evidence is not a phase prefix")
        previous_at: datetime | None = None
        for item in self.completed:
            if not isinstance(item, MigrationPhaseEvidence):
                raise MigrationEvidenceError("completed evidence is invalid")
            if item.manifest_digest != self.manifest_digest:
                raise MigrationManifestMismatchError(
                    "phase evidence belongs to another manifest"
                )
            if previous_at is not None and item.completed_at < previous_at:
                raise MigrationEvidenceError("completion times are not monotonic")
            previous_at = item.completed_at
        if self.tenant_aware_writes_enabled_at is not None:
            marker = _utc(
                self.tenant_aware_writes_enabled_at,
                "tenant_aware_writes_enabled_at",
            )
            object.__setattr__(
                self,
                "tenant_aware_writes_enabled_at",
                marker,
            )
            if MigrationPhase.DATABASE_JOBS_ENFORCE not in actual:
                raise MigrationBoundaryError(
                    "authoritative writes require database/jobs enforcement"
                )
            database_jobs_evidence = self.completed[
                MIGRATION_PHASE_ORDER.index(MigrationPhase.DATABASE_JOBS_ENFORCE)
            ]
            if marker < database_jobs_evidence.completed_at:
                raise MigrationBoundaryError(
                    "authoritative-write marker precedes its prerequisites"
                )
        if (
            MigrationPhase.CONTRACT in actual
            and self.tenant_aware_writes_enabled_at is None
        ):
            raise MigrationBoundaryError(
                "contract cannot complete before authoritative writes"
            )

    @property
    def next_phase(self) -> MigrationPhase | None:
        if len(self.completed) == len(MIGRATION_PHASE_ORDER):
            return None
        return MIGRATION_PHASE_ORDER[len(self.completed)]

    @property
    def legacy_rollback_allowed(self) -> bool:
        return self.tenant_aware_writes_enabled_at is None

    @classmethod
    def for_manifest(
        cls, manifest: DefaultTenantMigrationManifest
    ) -> "MigrationJournal":
        if not isinstance(manifest, DefaultTenantMigrationManifest):
            raise TypeError("manifest is invalid")
        return cls(manifest_digest=manifest.digest)


@dataclass(frozen=True, slots=True)
class MigrationExecutionPlan:
    phase: MigrationPhase
    mode: MigrationExecutionMode
    manifest_digest: bytes
    prerequisites: tuple[str, ...]
    completion_conditions: tuple[str, ...]
    stop_conditions: tuple[str, ...]
    rollback_action: str
    mutations_allowed: bool
    provider_or_print_side_effects_allowed: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.phase, MigrationPhase):
            raise TypeError("phase is invalid")
        if not isinstance(self.mode, MigrationExecutionMode):
            raise TypeError("mode is invalid")
        _digest(self.manifest_digest, "manifest_digest")
        if self.mutations_allowed != (
            self.mode is MigrationExecutionMode.APPLY
        ):
            raise ValueError("mutation policy does not match execution mode")
        if self.provider_or_print_side_effects_allowed:
            raise ValueError(
                "default migration never authorizes provider or print side effects"
            )


@dataclass(frozen=True, slots=True)
class LegacyRollbackPlan:
    manifest_digest: bytes
    actions: tuple[str, ...]
    preserves_expand_and_audit_facts: bool
    reverses_business_data: bool

    def __post_init__(self) -> None:
        _digest(self.manifest_digest, "manifest_digest")
        if self.preserves_expand_and_audit_facts is not True:
            raise MigrationBoundaryError("rollback must preserve authoritative facts")
        if self.reverses_business_data is not False:
            raise MigrationBoundaryError("pre-boundary rollback does not reverse data")


def build_execution_plan(
    manifest: DefaultTenantMigrationManifest,
    journal: MigrationJournal,
    *,
    mode: MigrationExecutionMode,
    requested_phase: MigrationPhase | None = None,
) -> MigrationExecutionPlan:
    """Return only the next legal phase and its executable contract."""

    _matching_manifest(manifest, journal)
    if not isinstance(mode, MigrationExecutionMode):
        raise TypeError("mode must be a MigrationExecutionMode")
    phase = journal.next_phase
    if phase is None:
        raise MigrationOrderError("migration is already complete")
    if requested_phase is not None and requested_phase is not phase:
        raise MigrationOrderError("requested phase is not the next dependency")
    if phase is MigrationPhase.CONTRACT and not journal.tenant_aware_writes_enabled_at:
        raise MigrationBoundaryError(
            "contract requires the authoritative-write marker"
        )
    contract = _PHASE_CONTRACTS[phase]
    return MigrationExecutionPlan(
        phase=phase,
        mode=mode,
        manifest_digest=manifest.digest,
        prerequisites=contract.prerequisites,
        completion_conditions=contract.completion_conditions,
        stop_conditions=contract.stop_conditions,
        rollback_action=contract.rollback_action,
        mutations_allowed=mode is MigrationExecutionMode.APPLY,
    )


def record_phase_completion(
    manifest: DefaultTenantMigrationManifest,
    journal: MigrationJournal,
    *,
    plan: MigrationExecutionPlan,
    input_state_digest: bytes,
    result_state_digest: bytes,
    completed_at: datetime,
    executor_reference: str,
) -> MigrationJournal:
    """Append evidence only for a completed APPLY of the next phase.

    ``BACKFILL_VERIFY`` is deliberately excluded from this generic boundary.
    Its result digest is meaningful only after the versioned reconciliation
    policy and report have been checked together; callers must use
    ``record_backfill_verification_completion`` for that phase.
    """

    return _record_phase_completion(
        manifest,
        journal,
        plan=plan,
        input_state_digest=input_state_digest,
        result_state_digest=result_state_digest,
        completed_at=completed_at,
        executor_reference=executor_reference,
        reconciliation_validated=False,
    )


def _record_phase_completion(
    manifest: DefaultTenantMigrationManifest,
    journal: MigrationJournal,
    *,
    plan: MigrationExecutionPlan,
    input_state_digest: bytes,
    result_state_digest: bytes,
    completed_at: datetime,
    executor_reference: str,
    reconciliation_validated: bool,
) -> MigrationJournal:
    """Internal append boundary used by the reconciliation adapter."""

    _matching_manifest(manifest, journal)
    if plan.manifest_digest != manifest.digest:
        raise MigrationManifestMismatchError("plan belongs to another manifest")
    if plan.mode is not MigrationExecutionMode.APPLY:
        raise MigrationEvidenceError("dry-run output cannot complete a phase")
    if plan.phase is not journal.next_phase:
        raise MigrationOrderError("phase completion is stale or out of order")
    if (
        plan.phase is MigrationPhase.BACKFILL_VERIFY
        and not reconciliation_validated
    ):
        raise MigrationEvidenceError(
            "backfill/verify completion requires a passed reconciliation report"
        )
    if (
        plan.phase is MigrationPhase.CONTRACT
        and journal.tenant_aware_writes_enabled_at is None
    ):
        raise MigrationBoundaryError(
            "contract cannot complete before authoritative writes"
        )
    evidence = MigrationPhaseEvidence(
        phase=plan.phase,
        manifest_digest=manifest.digest,
        input_state_digest=input_state_digest,
        result_state_digest=result_state_digest,
        completed_at=completed_at,
        executor_reference=executor_reference,
    )
    return replace(journal, completed=journal.completed + (evidence,))


def mark_tenant_aware_writes_authoritative(
    manifest: DefaultTenantMigrationManifest,
    journal: MigrationJournal,
    *,
    enabled_at: datetime,
) -> MigrationJournal:
    """Cross the one-way old-writer rollback boundary exactly once."""

    _matching_manifest(manifest, journal)
    if journal.tenant_aware_writes_enabled_at is not None:
        if _utc(enabled_at, "enabled_at") == journal.tenant_aware_writes_enabled_at:
            return journal
        raise MigrationBoundaryError("authoritative-write marker is immutable")
    database_jobs = next(
        (
            item
            for item in journal.completed
            if item.phase is MigrationPhase.DATABASE_JOBS_ENFORCE
        ),
        None,
    )
    if database_jobs is None:
        raise MigrationBoundaryError(
            "database/jobs enforcement must complete before authoritative writes"
        )
    normalized = _utc(enabled_at, "enabled_at")
    if normalized < database_jobs.completed_at:
        raise MigrationBoundaryError(
            "authoritative-write marker predates database/jobs enforcement"
        )
    return replace(
        journal,
        tenant_aware_writes_enabled_at=normalized,
    )


def plan_legacy_rollback(
    manifest: DefaultTenantMigrationManifest,
    journal: MigrationJournal,
) -> LegacyRollbackPlan:
    """Describe the only safe rollback to the legacy writer."""

    _matching_manifest(manifest, journal)
    if not journal.legacy_rollback_allowed:
        raise MigrationBoundaryError(
            "legacy rollback is forbidden after tenant-aware writes"
        )
    return LegacyRollbackPlan(
        manifest_digest=manifest.digest,
        actions=(
            "stop Core Web writes, workers, schedulers, and provider submissions",
            "verify no tenant-aware business write crossed the authority boundary",
            "disable Core runtime routes without deleting database_identity or control facts",
            "restore the tested legacy application and its bounded rollback identity",
            "verify source reconciliation and external side-effect isolation",
        ),
        preserves_expand_and_audit_facts=True,
        reverses_business_data=False,
    )


def _matching_manifest(
    manifest: DefaultTenantMigrationManifest, journal: MigrationJournal
) -> None:
    if not isinstance(manifest, DefaultTenantMigrationManifest):
        raise TypeError("manifest is invalid")
    if not isinstance(journal, MigrationJournal):
        raise TypeError("journal is invalid")
    if journal.manifest_digest != manifest.digest:
        raise MigrationManifestMismatchError(
            "journal belongs to another immutable manifest"
        )


def _digest(value: object, field_name: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != _DIGEST_BYTES:
        raise MigrationManifestError(f"{field_name} must be a SHA-256 digest")
    return value


def _safe_id(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise MigrationManifestError(f"{field_name} is invalid")
    return value


def _schema_head(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SCHEMA_HEAD.fullmatch(value) is None:
        raise MigrationManifestError(f"{field_name} is invalid")
    return value


def _uuid(value: object, field_name: str) -> UUID:
    if not isinstance(value, UUID):
        raise MigrationManifestError(f"{field_name} must be a UUID")
    return value


def _utc(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise MigrationEvidenceError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)
