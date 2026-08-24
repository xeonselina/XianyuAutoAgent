"""Caller-transactional persistence for the pure D26 deletion reducer.

The coordinator performs only control-database locking, state persistence, and
receipt bookkeeping.  It never drops a schema, changes a provider claim,
writes NAS storage, opens a tenant database, or commits/rolls back the caller's
transaction.  Fallible external work is represented by durable pending effect
facts; a trusted adapter records a bounded result before a later reducer
barrier may advance.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import asdict, dataclass, is_dataclass, replace
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Protocol
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.database import read_database_utc_value
from inventory_control.domain.tenant_gate import TenantStatus
from inventory_control.lifecycle.deletion import (
    CancellationEvidence,
    DeletionAction,
    DeletionActionKind,
    DeletionActionOutcome,
    DeletionClaimReleaseEvidence,
    DeletionEffectFact,
    DeletionEffectKind,
    DeletionExecutorFenceEvidence,
    DeletionIsolationEvidence,
    DeletionLockdownEvidence,
    DeletionRequest,
    DeletionRequestStatus,
    DeletionState,
    DeletionTombstone,
    DeletionTransition,
    DestructiveCleanupEvidence,
    OffsiteTombstoneAck,
)
from inventory_control.lifecycle.suspension import DmlLoginState, SuspensionPhase
from inventory_control.models.deletion import (
    TenantDeletionAction,
    TenantDeletionEffect,
    TenantDeletionEvidenceReceipt,
    TenantDeletionRequest,
    TenantDeletionTombstone,
)
from inventory_control.models.foundation import Tenant, TenantDatabase
from inventory_control.models.recovery import DisasterRecoveryRun, TenantRecoveryHold
from inventory_control.transactions import require_caller_transaction


_SAFE_TOKEN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/+-]{0,190}\Z", re.ASCII)
_SAFE_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}\Z", re.ASCII)
_MAX_LEASE_DURATION = timedelta(hours=1)


class DeletionPersistenceError(RuntimeError):
    """Stable, non-sensitive persistence rejection."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class DeletionPersistenceTransactionError(DeletionPersistenceError):
    pass


class DeletionPersistenceConflictError(DeletionPersistenceError):
    pass


class DeletionPersistenceAuthorityError(DeletionPersistenceError):
    pass


class DeletionPersistenceLeaseError(DeletionPersistenceError):
    pass


class DeletionPersistenceEvidenceError(DeletionPersistenceError):
    pass


class DeletionPersistenceProjectionError(DeletionPersistenceError):
    pass


@dataclass(frozen=True, slots=True)
class DeletionActionIdentity:
    """Immutable identity used to resolve action retries before reducing."""

    action_id: UUID
    kind: DeletionActionKind
    idempotency_key: str
    request_digest: bytes

    def __post_init__(self) -> None:
        _uuid(self.action_id, "DELETION_ACTION_ID_INVALID")
        if not isinstance(self.kind, DeletionActionKind):
            _raise(DeletionPersistenceConflictError, "DELETION_ACTION_KIND_INVALID")
        _token(self.idempotency_key, "DELETION_IDEMPOTENCY_KEY_INVALID", 191)
        _digest(self.request_digest, "DELETION_REQUEST_DIGEST_INVALID")


@dataclass(frozen=True, slots=True)
class DeletionExecutorLease:
    """Opaque lease identity; only its digest is ever persisted."""

    owner: str
    token_digest: bytes
    recovery_run_id: UUID
    execution_generation: int
    executor_fencing_token: int
    expires_at_utc: datetime

    def __post_init__(self) -> None:
        _token(self.owner, "DELETION_LEASE_OWNER_INVALID", 128)
        _digest(self.token_digest, "DELETION_LEASE_TOKEN_INVALID")
        _uuid(self.recovery_run_id, "DELETION_LEASE_RUN_INVALID")
        _positive(
            self.execution_generation,
            "DELETION_EXECUTION_GENERATION_INVALID",
        )
        _positive(
            self.executor_fencing_token,
            "DELETION_EXECUTOR_FENCING_TOKEN_INVALID",
        )
        object.__setattr__(
            self,
            "expires_at_utc",
            _aware_utc(self.expires_at_utc, "DELETION_LEASE_EXPIRY_INVALID"),
        )


@dataclass(frozen=True, slots=True)
class RecoveryDispositionVerification:
    """Current-run D58 anchors verified before tenant-owned rows disappear."""

    recovery_run_id: UUID
    recovery_hold_id: UUID
    recovery_hold_revision: int
    disposition_digest: bytes
    all_required_dispositions_complete: bool

    def __post_init__(self) -> None:
        _uuid(self.recovery_run_id, "DELETION_RECOVERY_RUN_INVALID")
        _uuid(self.recovery_hold_id, "DELETION_RECOVERY_HOLD_INVALID")
        _positive(
            self.recovery_hold_revision,
            "DELETION_RECOVERY_HOLD_REVISION_INVALID",
        )
        _digest(
            self.disposition_digest,
            "DELETION_RECOVERY_DISPOSITION_DIGEST_INVALID",
        )
        if not isinstance(self.all_required_dispositions_complete, bool):
            _raise(
                DeletionPersistenceEvidenceError,
                "DELETION_RECOVERY_DISPOSITION_STATE_INVALID",
            )


@dataclass(frozen=True, slots=True)
class DeletionEvidenceVerification:
    """Result of a trusted locking/current-read evidence verifier."""

    verifier_kind: str
    evidence_digest: bytes
    verified_at_utc: datetime
    verified: bool
    recovery_disposition: RecoveryDispositionVerification | None = None

    def __post_init__(self) -> None:
        if self.verifier_kind not in {
            "control_current_read",
            "nas_authenticated_ack",
            "provider_claim_current_read",
            "destructive_current_read",
        }:
            _raise(
                DeletionPersistenceEvidenceError,
                "DELETION_EVIDENCE_VERIFIER_INVALID",
            )
        _digest(self.evidence_digest, "DELETION_EVIDENCE_DIGEST_INVALID")
        object.__setattr__(
            self,
            "verified_at_utc",
            _aware_utc(
                self.verified_at_utc,
                "DELETION_EVIDENCE_TIME_INVALID",
            ),
        )
        if not isinstance(self.verified, bool):
            _raise(
                DeletionPersistenceEvidenceError,
                "DELETION_EVIDENCE_VERIFICATION_INVALID",
            )


class DeletionEvidenceCurrentRead(Protocol):
    """Verify evidence without performing the external action itself."""

    def __call__(
        self,
        session: Session,
        *,
        receipt_kind: str,
        evidence: object,
        evidence_digest: bytes,
        prior_state: DeletionState,
        transition: DeletionTransition,
        database_now_utc: datetime,
    ) -> DeletionEvidenceVerification:
        ...


@dataclass(frozen=True, slots=True)
class RouteProjectionVerification:
    """Proof returned by the separately owned expanding route coordinator."""

    tenant_id: UUID
    database_id: UUID
    published_dml_generation: int
    desired_dml_login_state: DmlLoginState
    route_row_version: int
    verified: bool


class ExpandingRouteProjectionWriter(Protocol):
    """Persist a pre-verified candidate publication in the caller transaction."""

    def __call__(
        self,
        session: Session,
        *,
        route: TenantDatabase,
        prior_state: DeletionState,
        transition: DeletionTransition,
    ) -> RouteProjectionVerification:
        ...


@dataclass(frozen=True, slots=True)
class PersistedDeletionEffect:
    """A reducer fact paired with the durable row UUID used for receipts."""

    effect_id: UUID
    fact: DeletionEffectFact
    state: str


@dataclass(frozen=True, slots=True)
class DeletionPersistenceResult:
    state: DeletionState
    effects: tuple[PersistedDeletionEffect, ...]
    replayed: bool
    tenant_row_version: int
    request_row_version: int | None


@dataclass(frozen=True, slots=True)
class DeletionLeaseResult:
    state: DeletionState
    lease: DeletionExecutorLease
    request_row_version: int
    replayed: bool
    takeover: bool
    effects: tuple[PersistedDeletionEffect, ...]


Reducer = Callable[[DeletionState], DeletionTransition]
DatabaseClock = Callable[[Session], datetime]


@dataclass(slots=True)
class _LockedAggregate:
    tenant: Tenant
    recovery_run: DisasterRecoveryRun
    recovery_hold: TenantRecoveryHold
    request_row: TenantDeletionRequest | None
    current_action_row: TenantDeletionAction | None
    tombstone_row: TenantDeletionTombstone | None
    route: TenantDatabase | None
    state: DeletionState


class TenantDeletionPersistenceCoordinator:
    """Apply one pure reducer transition and flush it without committing."""

    def __init__(
        self,
        *,
        evidence_current_read: DeletionEvidenceCurrentRead | None = None,
        expanding_route_writer: ExpandingRouteProjectionWriter | None = None,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if evidence_current_read is not None and not callable(evidence_current_read):
            raise TypeError("evidence_current_read must be callable")
        if expanding_route_writer is not None and not callable(expanding_route_writer):
            raise TypeError("expanding_route_writer must be callable")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._evidence_current_read = evidence_current_read
        self._expanding_route_writer = expanding_route_writer
        self._database_clock = database_clock or _read_database_utc_now

    def apply(
        self,
        session: Session,
        *,
        tenant_uuid: str | UUID,
        expected_tenant_row_version: int,
        reduce: Reducer,
        action_identity: DeletionActionIdentity | None = None,
        request_challenge_uuid: str | UUID | None = None,
        cancel_challenge_uuid: str | UUID | None = None,
        executor_lease: DeletionExecutorLease | None = None,
        evidence: object | None = None,
    ) -> DeletionPersistenceResult:
        """Lock, reduce, persist, and flush inside a clean caller transaction.

        This method never commits.  In particular, the two control-only facts
        emitted by ``complete_deletion`` must be applied and receipted by the
        caller in this same transaction before it removes the request/tenant
        rows and commits; the permanent tombstone deliberately survives both.
        """

        self._prepare(session)
        if not callable(reduce):
            raise TypeError("reduce must be callable")
        tenant_id = str(_uuid(tenant_uuid, "DELETION_TENANT_ID_INVALID"))
        expected_tenant_version = _positive(
            expected_tenant_row_version,
            "DELETION_TENANT_ROW_VERSION_INVALID",
        )
        locked = self._lock_aggregate(session, tenant_id)
        replay = self._historical_action_replay(
            session,
            locked=locked,
            identity=action_identity,
        )
        if replay:
            return self._result(locked, effects=(), replayed=True)
        if locked.tenant.row_version != expected_tenant_version:
            _raise(
                DeletionPersistenceConflictError,
                "STALE_DELETION_TENANT_ROW_VERSION",
            )

        transition = reduce(locked.state)
        self._validate_transition(locked.state, transition)
        if transition.idempotent_replay:
            if evidence is not None:
                _raise(
                    DeletionPersistenceEvidenceError,
                    "DELETION_REPLAY_EVIDENCE_UNEXPECTED",
                )
            return self._result(locked, effects=(), replayed=True)

        creates_request = bool(
            transition.state.request is not None
            and (
                locked.state.request is None
                or transition.state.request.request_id
                != locked.state.request.request_id
            )
        )
        if creates_request and (
            locked.recovery_run.status != "completed"
            or locked.recovery_hold.state != "released"
        ):
            _raise(
                DeletionPersistenceAuthorityError,
                "DELETION_RECOVERY_GATE_NOT_RELEASED",
            )

        self._validate_action_identity(
            prior_state=locked.state,
            transition=transition,
            identity=action_identity,
        )
        database_now = self._now(session)
        evidence_items = _transition_evidence_items(
            locked.state,
            transition,
            evidence,
        )
        if _transition_requires_lease(locked.state, transition, evidence_items):
            self._require_current_lease(
                locked,
                executor_lease,
                database_now=database_now,
            )

        verifications = self._verify_evidence(
            session,
            locked=locked,
            transition=transition,
            evidence_items=evidence_items,
            database_now=database_now,
        )
        self._persist_projection(session, locked=locked, transition=transition)
        request_row, action_row = self._persist_request_and_action(
            session,
            locked=locked,
            transition=transition,
            request_challenge_uuid=request_challenge_uuid,
            cancel_challenge_uuid=cancel_challenge_uuid,
            database_now=database_now,
        )
        tombstone_row = self._persist_tombstone(
            session,
            prior_state=locked.state,
            transition=transition,
            database_now=database_now,
        )
        self._persist_receipts(
            session,
            transition=transition,
            request_row=request_row,
            action_row=action_row,
            evidence_items=evidence_items,
            verifications=verifications,
        )
        effects = self._persist_effects(
            session,
            transition=transition,
            request_row=request_row,
            action_row=action_row,
            database_now=database_now,
        )
        self._mark_internal_effects(
            session,
            effects=effects,
            tombstone=tombstone_row,
            transition=transition,
            database_now=database_now,
        )
        session.flush()
        locked.request_row = request_row
        locked.current_action_row = action_row
        locked.tombstone_row = tombstone_row
        locked.state = transition.state
        return self._result(
            locked,
            effects=_persisted_effects(effects),
            replayed=False,
        )

    def acquire_executor_lease(
        self,
        session: Session,
        *,
        tenant_uuid: str | UUID,
        request_uuid: str | UUID,
        expected_request_revision: int,
        expected_execution_generation: int,
        expected_executor_fencing_token: int,
        lease_owner: str,
        lease_token_digest: bytes,
        lease_duration: timedelta,
    ) -> DeletionLeaseResult:
        """Acquire/renew a lease; a takeover fences and re-drives the stage."""

        self._prepare(session)
        tenant_id = str(_uuid(tenant_uuid, "DELETION_TENANT_ID_INVALID"))
        request_id = str(_uuid(request_uuid, "DELETION_REQUEST_ID_INVALID"))
        owner = _token(lease_owner, "DELETION_LEASE_OWNER_INVALID", 128)
        token_digest = _digest(
            lease_token_digest,
            "DELETION_LEASE_TOKEN_INVALID",
        )
        duration = _lease_duration(lease_duration)
        locked = self._lock_aggregate(session, tenant_id)
        row = locked.request_row
        action_row = locked.current_action_row
        if row is None or action_row is None or row.id != request_id:
            _raise(
                DeletionPersistenceLeaseError,
                "DELETION_LEASE_REQUEST_UNAVAILABLE",
            )
        if row.status not in {
            "cooling_off",
            "committing",
            "awaiting_offsite_ack",
            "releasing_claims",
            "dropping",
            "failed",
        }:
            _raise(
                DeletionPersistenceLeaseError,
                "DELETION_LEASE_STATE_INELIGIBLE",
            )
        if (
            row.request_revision != expected_request_revision
            or row.execution_generation != expected_execution_generation
            or row.executor_fencing_token != expected_executor_fencing_token
        ):
            _raise(
                DeletionPersistenceLeaseError,
                "STALE_DELETION_LEASE_FENCE",
            )
        now = self._now(session)
        expires_at = now + duration
        same_identity = bool(
            row.executor_lease_owner == owner
            and row.executor_lease_token_digest is not None
            and hmac.compare_digest(row.executor_lease_token_digest, token_digest)
            and row.executor_lease_recovery_run_id == locked.recovery_run.id
        )
        lease_is_current = bool(
            row.executor_lease_expires_at is not None
            and _database_utc(row.executor_lease_expires_at) > now
            and row.executor_lease_recovery_run_id == locked.recovery_run.id
        )
        if lease_is_current and not same_identity:
            _raise(
                DeletionPersistenceLeaseError,
                "DELETION_EXECUTOR_LEASE_HELD",
            )

        takeover = bool(
            row.executor_lease_owner is not None
            and (not same_identity or not lease_is_current)
        )
        replayed = same_identity and lease_is_current
        effect_facts: tuple[DeletionEffectFact, ...] = ()
        persisted_effects: tuple[PersistedDeletionEffect, ...] = ()
        if takeover:
            row.request_revision += 1
            row.execution_generation += 1
            row.executor_fencing_token += 1
            action_row.execution_generation = row.execution_generation
            action_row.executor_fencing_token = row.executor_fencing_token
            reset_cooling_lockdown = bool(
                row.status == "cooling_off"
                and action_row.kind == DeletionActionKind.REVIEW_APPROVE.value
                and action_row.outcome == DeletionActionOutcome.SUCCEEDED.value
            )
            if reset_cooling_lockdown:
                action_row.outcome = DeletionActionOutcome.RUNNING.value
            action_row.row_version += 1
            action_row.updated_at = now
            locked.state = _state_with_executor_takeover(
                locked.state,
                request_revision=row.request_revision,
                execution_generation=row.execution_generation,
                executor_fencing_token=row.executor_fencing_token,
                reset_cooling_lockdown=reset_cooling_lockdown,
            )
            effect_facts = _redrive_effects(locked.state)
            effect_rows = self._persist_effects(
                session,
                transition=DeletionTransition(
                    state=locked.state,
                    effects=effect_facts,
                ),
                request_row=row,
                action_row=action_row,
                database_now=now,
            )
            persisted_effects = _persisted_effects(effect_rows)

        row.executor_lease_owner = owner
        row.executor_lease_token_digest = token_digest
        row.executor_lease_expires_at = expires_at
        row.executor_lease_recovery_run_id = locked.recovery_run.id
        row.row_version += 1
        row.updated_at = now
        session.flush()
        lease = DeletionExecutorLease(
            owner=owner,
            token_digest=token_digest,
            recovery_run_id=UUID(locked.recovery_run.id),
            execution_generation=row.execution_generation,
            executor_fencing_token=row.executor_fencing_token,
            expires_at_utc=expires_at,
        )
        return DeletionLeaseResult(
            state=locked.state,
            lease=lease,
            request_row_version=row.row_version,
            replayed=replayed,
            takeover=takeover,
            effects=persisted_effects,
        )

    def complete_effect(
        self,
        session: Session,
        *,
        tenant_uuid: str | UUID,
        effect_uuid: str | UUID,
        executor_lease: DeletionExecutorLease,
        result_digest: bytes,
        safe_outcome_code: str,
        succeeded: bool,
    ) -> bool:
        """Persist a bounded effect receipt; return ``True`` on exact replay."""

        self._prepare(session)
        tenant_id = str(_uuid(tenant_uuid, "DELETION_TENANT_ID_INVALID"))
        effect_id = str(_uuid(effect_uuid, "DELETION_EFFECT_ID_INVALID"))
        digest = _digest(result_digest, "DELETION_EFFECT_RESULT_DIGEST_INVALID")
        outcome = _safe_code(safe_outcome_code)
        if not isinstance(succeeded, bool):
            raise TypeError("succeeded must be bool")
        locked = self._lock_aggregate(session, tenant_id)
        now = self._now(session)
        self._require_current_lease(locked, executor_lease, database_now=now)
        effect = session.scalar(
            sa.select(TenantDeletionEffect)
            .where(TenantDeletionEffect.id == effect_id)
            .with_for_update()
        )
        request = locked.request_row
        if effect is None or request is None:
            _raise(
                DeletionPersistenceEvidenceError,
                "DELETION_EFFECT_UNAVAILABLE",
            )
        if (
            effect.deletion_request_id != request.id
            or effect.action_id != request.current_action_id
            or effect.execution_generation != request.execution_generation
            or effect.executor_fencing_token != request.executor_fencing_token
            or effect.tenant_access_version != request.committed_tenant_access_version
        ):
            _raise(
                DeletionPersistenceEvidenceError,
                "STALE_DELETION_EFFECT_FENCE",
            )
        target_state = "succeeded" if succeeded else "failed"
        if effect.state != "pending":
            if (
                effect.state == target_state
                and effect.result_digest is not None
                and hmac.compare_digest(effect.result_digest, digest)
                and effect.safe_outcome_code == outcome
            ):
                return True
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_EFFECT_RESULT_CONFLICT",
            )
        effect.state = target_state
        effect.result_digest = digest
        effect.safe_outcome_code = outcome
        effect.completed_at = now
        effect.row_version += 1
        session.flush()
        return False

    def load_for_update(
        self,
        session: Session,
        *,
        tenant_uuid: str | UUID,
    ) -> DeletionState:
        """Return the authoritative reducer state inside a clean transaction."""

        self._prepare(session)
        tenant_id = str(_uuid(tenant_uuid, "DELETION_TENANT_ID_INVALID"))
        return self._lock_aggregate(session, tenant_id).state

    def _prepare(self, session: Session) -> None:
        require_caller_transaction(
            session,
            lambda: DeletionPersistenceTransactionError(
                "DELETION_CALLER_TRANSACTION_REQUIRED"
            ),
            invalid_session_error=lambda: DeletionPersistenceTransactionError(
                "DELETION_CALLER_TRANSACTION_REQUIRED"
            ),
            dirty_error=lambda: DeletionPersistenceTransactionError(
                "DELETION_CLEAN_CALLER_UNIT_OF_WORK_REQUIRED"
            ),
            clean=True,
        )

    def _now(self, session: Session) -> datetime:
        return _database_utc(self._database_clock(session))

    def _lock_aggregate(self, session: Session, tenant_id: str) -> _LockedAggregate:
        # Shared tenant-first lifecycle lock prefix.  Never lock a deletion row
        # and then wait backwards on tenant/recovery authority.
        tenant = session.scalar(
            sa.select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        if tenant is None:
            _raise(
                DeletionPersistenceAuthorityError,
                "DELETION_TENANT_UNAVAILABLE",
            )
        run = session.scalar(
            sa.select(DisasterRecoveryRun)
            .where(DisasterRecoveryRun.current_run_marker == "current")
            .with_for_update()
        )
        if run is None:
            _raise(
                DeletionPersistenceAuthorityError,
                "DELETION_CURRENT_RECOVERY_RUN_REQUIRED",
            )
        hold = session.scalar(
            sa.select(TenantRecoveryHold)
            .where(
                TenantRecoveryHold.recovery_run_id == run.id,
                TenantRecoveryHold.tenant_id == tenant.id,
            )
            .with_for_update()
        )
        if hold is None:
            _raise(
                DeletionPersistenceAuthorityError,
                "DELETION_CURRENT_RECOVERY_HOLD_REQUIRED",
            )
        request_row = session.scalar(
            sa.select(TenantDeletionRequest)
            .where(
                TenantDeletionRequest.tenant_id == tenant.id,
                TenantDeletionRequest.active_tenant_id == tenant.id,
            )
            .with_for_update()
        )
        if request_row is None:
            # Keep the latest terminal aggregate available for idempotency and
            # for the reducer's rejected/cancelled -> new request edge.
            request_row = session.scalar(
                sa.select(TenantDeletionRequest)
                .where(TenantDeletionRequest.tenant_id == tenant.id)
                .order_by(
                    TenantDeletionRequest.requested_at.desc(),
                    TenantDeletionRequest.id.desc(),
                )
                .limit(1)
                .with_for_update()
            )
        action_row = None
        tombstone_row = None
        if request_row is not None:
            action_row = session.scalar(
                sa.select(TenantDeletionAction)
                .where(TenantDeletionAction.id == request_row.current_action_id)
                .with_for_update()
            )
            if action_row is None or action_row.deletion_request_id != request_row.id:
                _raise(
                    DeletionPersistenceAuthorityError,
                    "DELETION_CURRENT_ACTION_MISSING",
                )
            tombstone_row = session.scalar(
                sa.select(TenantDeletionTombstone)
                .where(TenantDeletionTombstone.deletion_request_id == request_row.id)
                .with_for_update()
            )
        route = session.scalar(
            sa.select(TenantDatabase)
            .where(TenantDatabase.tenant_id == tenant.id)
            .with_for_update()
        )
        database_id = (
            request_row.database_uuid
            if request_row is not None
            else route.database_uuid
            if route is not None
            else None
        )
        if database_id is None or hold.database_uuid != database_id:
            _raise(
                DeletionPersistenceAuthorityError,
                "DELETION_RECOVERY_HOLD_SCOPE_MISMATCH",
            )
        state = _to_state(
            tenant=tenant,
            route=route,
            hold=hold,
            request_row=request_row,
            action_row=action_row,
            tombstone_row=tombstone_row,
        )
        return _LockedAggregate(
            tenant=tenant,
            recovery_run=run,
            recovery_hold=hold,
            request_row=request_row,
            current_action_row=action_row,
            tombstone_row=tombstone_row,
            route=route,
            state=state,
        )

    def _historical_action_replay(
        self,
        session: Session,
        *,
        locked: _LockedAggregate,
        identity: DeletionActionIdentity | None,
    ) -> bool:
        if identity is None or locked.request_row is None:
            return False
        existing = session.scalar(
            sa.select(TenantDeletionAction)
            .where(TenantDeletionAction.id == str(identity.action_id))
            .with_for_update()
        )
        if existing is None:
            existing = session.scalar(
                sa.select(TenantDeletionAction)
                .where(
                    TenantDeletionAction.deletion_request_id == locked.request_row.id,
                    TenantDeletionAction.idempotency_key == identity.idempotency_key,
                )
                .with_for_update()
            )
        if existing is None:
            return False
        if (
            existing.deletion_request_id != locked.request_row.id
            or existing.id != str(identity.action_id)
            or existing.kind != identity.kind.value
            or existing.idempotency_key != identity.idempotency_key
            or not hmac.compare_digest(existing.request_digest, identity.request_digest)
        ):
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_ACTION_IDEMPOTENCY_CONFLICT",
            )
        return True

    def _validate_action_identity(
        self,
        *,
        prior_state: DeletionState,
        transition: DeletionTransition,
        identity: DeletionActionIdentity | None,
    ) -> None:
        prior_action_id = (
            prior_state.request.current_action.action_id
            if prior_state.request is not None
            else None
        )
        request = transition.state.request
        if request is None:
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_TRANSITION_REQUEST_MISSING",
            )
        action_is_new = request.current_action.action_id != prior_action_id
        if action_is_new and identity is None:
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_ACTION_IDENTITY_REQUIRED",
            )
        if identity is None:
            return
        action = request.current_action
        if (
            action.action_id != identity.action_id
            or action.kind is not identity.kind
            or action.idempotency_key != identity.idempotency_key
            or not hmac.compare_digest(action.request_digest, identity.request_digest)
        ):
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_ACTION_IDENTITY_MISMATCH",
            )

    def _validate_transition(
        self,
        prior: DeletionState,
        transition: object,
    ) -> None:
        if not isinstance(transition, DeletionTransition):
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_REDUCER_RESULT_INVALID",
            )
        if transition.external_side_effect_performed:
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_REDUCER_EXTERNAL_EFFECT_FORBIDDEN",
            )
        if transition.state.tenant_id != prior.tenant_id:
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_TRANSITION_TENANT_MISMATCH",
            )
        if transition.state.database_id != prior.database_id:
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_TRANSITION_DATABASE_MISMATCH",
            )
        _validate_status_edge(prior.request, transition.state.request)
        if transition.idempotent_replay:
            if transition.state != prior or transition.effects:
                _raise(
                    DeletionPersistenceConflictError,
                    "DELETION_REPLAY_MUTATED_STATE",
                )
            return
        if transition.state.request is None:
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_TRANSITION_REQUEST_MISSING",
            )
        is_new_request = bool(
            prior.request is None
            or transition.state.request.request_id != prior.request.request_id
        )
        if is_new_request:
            if transition.state.request.revision != 1:
                _raise(
                    DeletionPersistenceConflictError,
                    "DELETION_INITIAL_REVISION_INVALID",
                )
        elif transition.state.request.revision != prior.request.revision + 1:
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_REQUEST_REVISION_NOT_MONOTONIC",
            )
        if transition.state.tenant_access_version not in {
            prior.tenant_access_version,
            prior.tenant_access_version + 1,
        }:
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_ACCESS_VERSION_NOT_MONOTONIC",
            )
        request = transition.state.request
        for effect in transition.effects:
            if (
                effect.request_id != request.request_id
                or effect.action_id != request.current_action.action_id
                or effect.execution_generation != request.execution_generation
                or effect.executor_fencing_token != request.executor_fencing_token
                or effect.tenant_access_version
                != transition.state.tenant_access_version
            ):
                _raise(
                    DeletionPersistenceConflictError,
                    "DELETION_EFFECT_FENCE_MISMATCH",
                )

    def _require_current_lease(
        self,
        locked: _LockedAggregate,
        lease: DeletionExecutorLease | None,
        *,
        database_now: datetime,
    ) -> None:
        row = locked.request_row
        if row is None or lease is None:
            _raise(
                DeletionPersistenceLeaseError,
                "DELETION_EXECUTOR_LEASE_REQUIRED",
            )
        if (
            row.executor_lease_owner is None
            or row.executor_lease_token_digest is None
            or row.executor_lease_expires_at is None
            or row.executor_lease_recovery_run_id is None
        ):
            _raise(
                DeletionPersistenceLeaseError,
                "DELETION_EXECUTOR_LEASE_REQUIRED",
            )
        if (
            lease.owner != row.executor_lease_owner
            or not hmac.compare_digest(
                lease.token_digest,
                row.executor_lease_token_digest,
            )
            or str(lease.recovery_run_id) != locked.recovery_run.id
            or row.executor_lease_recovery_run_id != locked.recovery_run.id
            or lease.execution_generation != row.execution_generation
            or lease.executor_fencing_token != row.executor_fencing_token
            or lease.expires_at_utc != _database_utc(row.executor_lease_expires_at)
            or lease.expires_at_utc <= database_now
        ):
            _raise(
                DeletionPersistenceLeaseError,
                "STALE_DELETION_EXECUTOR_LEASE",
            )

    def _verify_evidence(
        self,
        session: Session,
        *,
        locked: _LockedAggregate,
        transition: DeletionTransition,
        evidence_items: tuple[tuple[str, object], ...],
        database_now: datetime,
    ) -> tuple[DeletionEvidenceVerification, ...]:
        if not evidence_items:
            return ()
        if self._evidence_current_read is None:
            _raise(
                DeletionPersistenceEvidenceError,
                "DELETION_TRUSTED_EVIDENCE_READER_REQUIRED",
            )
        verifications: list[DeletionEvidenceVerification] = []
        for receipt_kind, evidence in evidence_items:
            self._require_effect_barrier(
                session,
                locked=locked,
                receipt_kind=receipt_kind,
            )
            evidence_digest = deletion_evidence_digest(evidence)
            verification = self._evidence_current_read(
                session,
                receipt_kind=receipt_kind,
                evidence=evidence,
                evidence_digest=evidence_digest,
                prior_state=locked.state,
                transition=transition,
                database_now_utc=database_now,
            )
            if not isinstance(verification, DeletionEvidenceVerification):
                _raise(
                    DeletionPersistenceEvidenceError,
                    "DELETION_EVIDENCE_VERIFICATION_INVALID",
                )
            expected_verifier = _EXPECTED_VERIFIER_KIND[receipt_kind]
            if (
                not verification.verified
                or verification.verifier_kind != expected_verifier
                or not hmac.compare_digest(
                    verification.evidence_digest,
                    evidence_digest,
                )
                or verification.verified_at_utc != database_now
            ):
                _raise(
                    DeletionPersistenceEvidenceError,
                    "DELETION_EVIDENCE_NOT_VERIFIED",
                )
            if receipt_kind == "offsite_ack":
                acknowledgment = evidence
                tombstone = transition.state.request.tombstone  # type: ignore[union-attr]
                if (
                    not isinstance(acknowledgment, OffsiteTombstoneAck)
                    or tombstone is None
                    or acknowledgment.acknowledged_at_utc < tombstone.recorded_at_utc
                    or acknowledgment.acknowledged_at_utc > database_now
                    or verification.verified_at_utc < acknowledgment.acknowledged_at_utc
                ):
                    _raise(
                        DeletionPersistenceEvidenceError,
                        "DELETION_OFFSITE_ACK_TIME_INVALID",
                    )
            if receipt_kind in {"claim_release", "destructive_cleanup"}:
                self._verify_recovery_disposition(
                    locked=locked,
                    transition=transition,
                    verification=verification,
                )
            verifications.append(verification)
        return tuple(verifications)

    def _require_effect_barrier(
        self,
        session: Session,
        *,
        locked: _LockedAggregate,
        receipt_kind: str,
    ) -> None:
        request = locked.request_row
        if request is None:
            _raise(
                DeletionPersistenceEvidenceError,
                "DELETION_EFFECT_BARRIER_MISSING",
            )
        required = _required_effect_kinds(
            receipt_kind,
            recovery_required=locked.state.recovery_dispositions_required,
        )
        if required is None:
            effects = tuple(
                session.scalars(
                    sa.select(TenantDeletionEffect)
                    .where(
                        TenantDeletionEffect.deletion_request_id == request.id,
                        TenantDeletionEffect.action_id == request.current_action_id,
                        TenantDeletionEffect.execution_generation
                        == request.execution_generation,
                    )
                    .with_for_update()
                )
            )
            required = frozenset(effect.effect_kind for effect in effects)
        if not required:
            return
        tombstone_sequence = (
            locked.state.request.tombstone.sequence
            if locked.state.request is not None
            and locked.state.request.tombstone is not None
            else None
        )
        persisted = tuple(
            session.scalars(
                sa.select(TenantDeletionEffect)
                .where(
                    TenantDeletionEffect.deletion_request_id == request.id,
                    TenantDeletionEffect.action_id == request.current_action_id,
                    TenantDeletionEffect.execution_generation
                    == request.execution_generation,
                    TenantDeletionEffect.effect_kind.in_(required),
                    TenantDeletionEffect.tombstone_sequence == tombstone_sequence,
                )
                .with_for_update()
            )
        )
        if {effect.effect_kind for effect in persisted} != set(required) or any(
            effect.state != "succeeded" for effect in persisted
        ):
            _raise(
                DeletionPersistenceEvidenceError,
                "DELETION_EFFECT_BARRIER_INCOMPLETE",
            )

    def _verify_recovery_disposition(
        self,
        *,
        locked: _LockedAggregate,
        transition: DeletionTransition,
        verification: DeletionEvidenceVerification,
    ) -> None:
        if not transition.state.recovery_dispositions_required:
            if verification.recovery_disposition is not None:
                _raise(
                    DeletionPersistenceEvidenceError,
                    "DELETION_RECOVERY_DISPOSITION_UNEXPECTED",
                )
            return
        disposition = verification.recovery_disposition
        request = transition.state.request
        tombstone = request.tombstone if request is not None else None
        hold = locked.recovery_hold
        if disposition is None or request is None or tombstone is None:
            _raise(
                DeletionPersistenceEvidenceError,
                "DELETION_RECOVERY_DISPOSITION_REQUIRED",
            )
        if (
            not disposition.all_required_dispositions_complete
            or str(disposition.recovery_run_id) != locked.recovery_run.id
            or str(disposition.recovery_hold_id) != hold.id
            or disposition.recovery_hold_revision != hold.hold_revision
            or hold.state != "tombstoned"
            or hold.terminal_reason_code != "superseded_by_deletion"
            or hold.deletion_request_uuid != str(request.request_id)
            or hold.tombstone_ledger_sequence != tombstone.sequence
            or hold.tombstone_record_hash != tombstone.record_hash
        ):
            _raise(
                DeletionPersistenceEvidenceError,
                "DELETION_RECOVERY_DISPOSITION_INCOMPLETE",
            )

    def _persist_projection(
        self,
        session: Session,
        *,
        locked: _LockedAggregate,
        transition: DeletionTransition,
    ) -> None:
        prior = locked.state
        target = transition.state
        tenant_changed = bool(
            locked.tenant.status != target.tenant_status.value
            or locked.tenant.access_version != target.tenant_access_version
        )
        if tenant_changed:
            locked.tenant.status = target.tenant_status.value
            locked.tenant.access_version = target.tenant_access_version
            locked.tenant.row_version += 1

        route_expands = bool(
            target.desired_dml_login_state is DmlLoginState.ACTIVE
            and (
                prior.desired_dml_login_state is DmlLoginState.LOCKED
                or target.published_dml_generation != prior.published_dml_generation
            )
        )
        if route_expands:
            if (
                locked.recovery_run.status != "completed"
                or locked.recovery_hold.state != "released"
            ):
                _raise(
                    DeletionPersistenceProjectionError,
                    "DELETION_RECOVERY_GATE_NOT_RELEASED",
                )
            if locked.route is None or self._expanding_route_writer is None:
                _raise(
                    DeletionPersistenceProjectionError,
                    "DELETION_EXPANDING_ROUTE_WRITER_REQUIRED",
                )
            proof = self._expanding_route_writer(
                session,
                route=locked.route,
                prior_state=prior,
                transition=transition,
            )
            if (
                not isinstance(proof, RouteProjectionVerification)
                or proof.verified is not True
                or proof.tenant_id != target.tenant_id
                or proof.database_id != target.database_id
                or proof.published_dml_generation != target.published_dml_generation
                or proof.desired_dml_login_state is not target.desired_dml_login_state
                or locked.route.row_version != proof.route_row_version
                or locked.route.dml_desired_login_state != "active"
            ):
                _raise(
                    DeletionPersistenceProjectionError,
                    "DELETION_EXPANDING_ROUTE_NOT_VERIFIED",
                )
            return
        if target.desired_dml_login_state is DmlLoginState.LOCKED:
            if locked.route is None:
                if target.request is None or target.request.status not in {
                    DeletionRequestStatus.DROPPING,
                    DeletionRequestStatus.COMPLETED,
                }:
                    _raise(
                        DeletionPersistenceProjectionError,
                        "DELETION_ROUTE_UNAVAILABLE",
                    )
                return
            if locked.route.dml_desired_login_state != "locked":
                locked.route.dml_desired_login_state = "locked"
                current_version = locked.route.dml_login_state_version
                if current_version is None:
                    _raise(
                        DeletionPersistenceProjectionError,
                        "DELETION_DML_LOGIN_STATE_VERSION_MISSING",
                    )
                locked.route.dml_login_state_version = current_version + 1
                locked.route.row_version += 1

    def _persist_request_and_action(
        self,
        session: Session,
        *,
        locked: _LockedAggregate,
        transition: DeletionTransition,
        request_challenge_uuid: str | UUID | None,
        cancel_challenge_uuid: str | UUID | None,
        database_now: datetime,
    ) -> tuple[TenantDeletionRequest, TenantDeletionAction]:
        target = transition.state.request
        if target is None:
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_TRANSITION_REQUEST_MISSING",
            )
        row = locked.request_row
        creates_new_request = bool(row is None or row.id != str(target.request_id))
        if creates_new_request:
            if row is not None and row.status not in {"rejected", "cancelled"}:
                _raise(
                    DeletionPersistenceConflictError,
                    "ACTIVE_DELETION_REQUEST_EXISTS",
                )
            challenge_id = str(
                _uuid(
                    request_challenge_uuid,
                    "DELETION_REQUEST_CHALLENGE_REQUIRED",
                )
            )
            row = TenantDeletionRequest(
                id=str(target.request_id),
                tenant_id=str(transition.state.tenant_id),
                database_uuid=str(transition.state.database_id),
                requested_by_user_id=str(target.requested_by_user_id),
                request_challenge_id=challenge_id,
                status=target.status.value,
                request_revision=target.revision,
                execution_generation=target.execution_generation,
                executor_fencing_token=target.executor_fencing_token,
                current_action_id=str(target.current_action.action_id),
                committed_tenant_access_version=(
                    transition.state.tenant_access_version
                ),
                desired_dml_login_state=(
                    transition.state.desired_dml_login_state.value
                ),
                published_dml_generation=(transition.state.published_dml_generation),
                latest_dml_generation=transition.state.latest_dml_generation,
                candidate_dml_generation=(transition.state.candidate_dml_generation),
                recovery_dispositions_required=(
                    transition.state.recovery_dispositions_required
                ),
                requested_at=target.requested_at_utc,
                row_version=1,
                created_at=database_now,
                updated_at=database_now,
            )
            session.add(row)
            session.flush()
        else:
            row.status = target.status.value
            row.request_revision = target.revision
            row.execution_generation = target.execution_generation
            row.executor_fencing_token = target.executor_fencing_token
            row.current_action_id = str(target.current_action.action_id)
            row.committed_tenant_access_version = transition.state.tenant_access_version
            row.desired_dml_login_state = transition.state.desired_dml_login_state.value
            row.published_dml_generation = transition.state.published_dml_generation
            row.latest_dml_generation = transition.state.latest_dml_generation
            row.candidate_dml_generation = transition.state.candidate_dml_generation
            row.recovery_dispositions_required = (
                transition.state.recovery_dispositions_required
            )
            row.reviewed_by_platform_admin_id = _uuid_text(
                target.reviewed_by_platform_admin_id
            )
            row.cancelled_by_user_id = _uuid_text(target.cancelled_by_user_id)
            row.pre_freeze_tenant_status = _enum_text(target.pre_freeze_tenant_status)
            row.pre_freeze_suspension_phase = _enum_text(
                target.pre_freeze_suspension_phase
            )
            row.failure_resume_status = _enum_text(target.failure_resume_status)
            row.failure_code = target.failure_code
            row.reviewed_at = target.reviewed_at_utc
            row.execute_not_before = target.execute_not_before_utc
            row.cancelled_at = target.cancelled_at_utc
            if (
                target.current_action.kind is DeletionActionKind.CANCEL
                and row.cancel_challenge_id is None
            ):
                row.cancel_challenge_id = str(
                    _uuid(
                        cancel_challenge_uuid,
                        "DELETION_CANCEL_CHALLENGE_REQUIRED",
                    )
                )
            row.row_version += 1
            row.updated_at = database_now

        action = target.current_action
        action_row = session.get(TenantDeletionAction, str(action.action_id))
        if action_row is None:
            action_row = TenantDeletionAction(
                id=str(action.action_id),
                deletion_request_id=row.id,
                kind=action.kind.value,
                execution_generation=action.execution_generation,
                executor_fencing_token=action.executor_fencing_token,
                idempotency_key=action.idempotency_key,
                request_digest=action.request_digest,
                outcome=action.outcome.value,
                failure_code=action.failure_code,
                row_version=1,
                created_at=database_now,
                updated_at=database_now,
            )
            session.add(action_row)
        else:
            if (
                action_row.deletion_request_id != row.id
                or action_row.kind != action.kind.value
                or action_row.idempotency_key != action.idempotency_key
                or not hmac.compare_digest(
                    action_row.request_digest,
                    action.request_digest,
                )
            ):
                _raise(
                    DeletionPersistenceConflictError,
                    "DELETION_ACTION_IDENTITY_CONFLICT",
                )
            action_row.execution_generation = action.execution_generation
            action_row.executor_fencing_token = action.executor_fencing_token
            action_row.outcome = action.outcome.value
            action_row.failure_code = action.failure_code
            action_row.row_version += 1
            action_row.updated_at = database_now
        return row, action_row

    def _persist_tombstone(
        self,
        session: Session,
        *,
        prior_state: DeletionState,
        transition: DeletionTransition,
        database_now: datetime,
    ) -> TenantDeletionTombstone | None:
        target_request = transition.state.request
        if target_request is None or target_request.tombstone is None:
            return None
        tombstone = target_request.tombstone
        if (
            tombstone.recorded_at_utc > database_now
            or tombstone.recorded_at_utc < target_request.requested_at_utc
            or (
                target_request.execute_not_before_utc is not None
                and tombstone.recorded_at_utc < target_request.execute_not_before_utc
            )
        ):
            _raise(
                DeletionPersistenceEvidenceError,
                "DELETION_TOMBSTONE_TIME_INVALID",
            )
        existing = session.scalar(
            sa.select(TenantDeletionTombstone)
            .where(
                TenantDeletionTombstone.deletion_request_id == str(tombstone.request_id)
            )
            .with_for_update()
        )
        if existing is None:
            newest = session.scalar(
                sa.select(TenantDeletionTombstone)
                .order_by(TenantDeletionTombstone.ledger_sequence.desc())
                .limit(1)
                .with_for_update()
            )
            expected_sequence = 1 if newest is None else newest.ledger_sequence + 1
            expected_previous = None if newest is None else newest.head_hash
            if (
                tombstone.sequence != expected_sequence
                or tombstone.previous_hash != expected_previous
            ):
                _raise(
                    DeletionPersistenceEvidenceError,
                    "DELETION_TOMBSTONE_CHAIN_NOT_CURRENT",
                )
            existing = TenantDeletionTombstone(
                deletion_request_id=str(tombstone.request_id),
                tenant_id=str(tombstone.tenant_id),
                database_uuid=str(tombstone.database_id),
                ledger_sequence=tombstone.sequence,
                previous_hash=tombstone.previous_hash,
                record_hash=tombstone.record_hash,
                head_hash=tombstone.head_hash,
                checkpoint_root_key_version=(tombstone.checkpoint_root_key_version),
                checkpoint_mac=tombstone.checkpoint_mac,
                recorded_at=tombstone.recorded_at_utc,
            )
            session.add(existing)
        else:
            _require_tombstone_match(existing, tombstone)

        prior_ack = (
            prior_state.request.offsite_ack if prior_state.request is not None else None
        )
        ack = target_request.offsite_ack
        if ack is not None and prior_ack is None:
            if (
                existing.offsite_acknowledged_at is not None
                or existing.offsite_artifact_checksum is not None
            ):
                _raise(
                    DeletionPersistenceConflictError,
                    "DELETION_OFFSITE_ACK_CONFLICT",
                )
            existing.offsite_artifact_checksum = ack.artifact_checksum
            existing.offsite_acknowledged_at = ack.acknowledged_at_utc
            existing.offsite_authenticated = ack.authenticated
            existing.offsite_durably_persisted = ack.durably_persisted
            existing.offsite_checksum_verified = ack.checksum_verified
            existing.offsite_chain_verified = ack.chain_verified
        elif ack is not None:
            _require_ack_match(existing, ack)
        return existing

    def _persist_receipts(
        self,
        session: Session,
        *,
        transition: DeletionTransition,
        request_row: TenantDeletionRequest,
        action_row: TenantDeletionAction,
        evidence_items: tuple[tuple[str, object], ...],
        verifications: tuple[DeletionEvidenceVerification, ...],
    ) -> None:
        request = transition.state.request
        assert request is not None
        tombstone = request.tombstone
        for (receipt_kind, _), verification in zip(
            evidence_items,
            verifications,
            strict=True,
        ):
            existing = session.scalar(
                sa.select(TenantDeletionEvidenceReceipt)
                .where(
                    TenantDeletionEvidenceReceipt.deletion_request_id == request_row.id,
                    TenantDeletionEvidenceReceipt.action_id == action_row.id,
                    TenantDeletionEvidenceReceipt.execution_generation
                    == request.execution_generation,
                    TenantDeletionEvidenceReceipt.receipt_kind == receipt_kind,
                )
                .with_for_update()
            )
            recovery = verification.recovery_disposition
            values = {
                "verifier_kind": verification.verifier_kind,
                "evidence_digest": verification.evidence_digest,
                "executor_fencing_token": request.executor_fencing_token,
                "tenant_access_version": transition.state.tenant_access_version,
                "tombstone_sequence": tombstone.sequence if tombstone else None,
                "tombstone_head_hash": tombstone.head_hash if tombstone else None,
                "recovery_run_id": (
                    str(recovery.recovery_run_id) if recovery else None
                ),
                "recovery_hold_id": (
                    str(recovery.recovery_hold_id) if recovery else None
                ),
                "recovery_hold_revision": (
                    recovery.recovery_hold_revision if recovery else None
                ),
                "recovery_disposition_digest": (
                    recovery.disposition_digest if recovery else None
                ),
                "verified_at": verification.verified_at_utc,
            }
            if existing is None:
                session.add(
                    TenantDeletionEvidenceReceipt(
                        id=str(uuid4()),
                        deletion_request_id=request_row.id,
                        action_id=action_row.id,
                        receipt_kind=receipt_kind,
                        evidence_schema_version=1,
                        execution_generation=request.execution_generation,
                        **values,
                    )
                )
                continue
            if any(getattr(existing, key) != value for key, value in values.items()):
                _raise(
                    DeletionPersistenceConflictError,
                    "DELETION_EVIDENCE_RECEIPT_CONFLICT",
                )

    def _persist_effects(
        self,
        session: Session,
        *,
        transition: DeletionTransition,
        request_row: TenantDeletionRequest,
        action_row: TenantDeletionAction,
        database_now: datetime,
    ) -> tuple[TenantDeletionEffect, ...]:
        rows: list[TenantDeletionEffect] = []
        for fact in transition.effects:
            existing = session.scalar(
                sa.select(TenantDeletionEffect)
                .where(
                    TenantDeletionEffect.deletion_request_id == request_row.id,
                    TenantDeletionEffect.action_id == action_row.id,
                    TenantDeletionEffect.execution_generation
                    == fact.execution_generation,
                    TenantDeletionEffect.effect_kind == fact.kind.value,
                    TenantDeletionEffect.tombstone_sequence == fact.tombstone_sequence,
                )
                .with_for_update()
            )
            if existing is None:
                existing = TenantDeletionEffect(
                    id=str(uuid4()),
                    deletion_request_id=request_row.id,
                    action_id=action_row.id,
                    effect_kind=fact.kind.value,
                    execution_generation=fact.execution_generation,
                    executor_fencing_token=fact.executor_fencing_token,
                    tenant_access_version=fact.tenant_access_version,
                    dml_generation=fact.dml_generation,
                    tombstone_sequence=fact.tombstone_sequence,
                    state="pending",
                    row_version=1,
                    created_at=database_now,
                )
                session.add(existing)
            elif (
                existing.executor_fencing_token != fact.executor_fencing_token
                or existing.tenant_access_version != fact.tenant_access_version
                or existing.dml_generation != fact.dml_generation
            ):
                _raise(
                    DeletionPersistenceConflictError,
                    "DELETION_EFFECT_IDENTITY_CONFLICT",
                )
            rows.append(existing)
        return tuple(rows)

    def _mark_internal_effects(
        self,
        session: Session,
        *,
        effects: tuple[TenantDeletionEffect, ...],
        tombstone: TenantDeletionTombstone | None,
        transition: DeletionTransition,
        database_now: datetime,
    ) -> None:
        request = transition.state.request
        ack = request.offsite_ack if request is not None else None
        for effect in effects:
            digest: bytes | None = None
            outcome: str | None = None
            if (
                effect.effect_kind
                == DeletionEffectKind.APPEND_PERMANENT_TOMBSTONE.value
                and tombstone is not None
            ):
                digest = tombstone.record_hash
                outcome = "TOMBSTONE_PERSISTED"
            elif (
                effect.effect_kind
                == DeletionEffectKind.RECORD_VERIFIED_OFFSITE_ACK.value
                and ack is not None
            ):
                digest = ack.artifact_checksum
                outcome = "OFFSITE_ACK_PERSISTED"
            if digest is None or effect.state != "pending":
                continue
            effect.state = "succeeded"
            effect.result_digest = digest
            effect.safe_outcome_code = outcome
            effect.completed_at = database_now
            effect.row_version += 1

    @staticmethod
    def _result(
        locked: _LockedAggregate,
        *,
        effects: tuple[PersistedDeletionEffect, ...],
        replayed: bool,
    ) -> DeletionPersistenceResult:
        return DeletionPersistenceResult(
            state=locked.state,
            effects=effects,
            replayed=replayed,
            tenant_row_version=locked.tenant.row_version,
            request_row_version=(
                locked.request_row.row_version
                if locked.request_row is not None
                else None
            ),
        )


_EXPECTED_VERIFIER_KIND = {
    "lockdown": "control_current_read",
    "cancellation": "control_current_read",
    "isolation": "control_current_read",
    "executor_fence": "control_current_read",
    "offsite_ack": "nas_authenticated_ack",
    "claim_release": "provider_claim_current_read",
    "destructive_cleanup": "destructive_current_read",
}


def deletion_evidence_digest(evidence: object) -> bytes:
    """Hash a bounded dataclass receipt using a stable typed encoding."""

    if not is_dataclass(evidence) or isinstance(evidence, type):
        _raise(
            DeletionPersistenceEvidenceError,
            "DELETION_EVIDENCE_TYPE_INVALID",
        )
    payload = {
        "type": f"{type(evidence).__module__}.{type(evidence).__qualname__}",
        "value": _canonical_value(asdict(evidence)),
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).digest()


def _canonical_value(value: object) -> object:
    if isinstance(value, dict):
        return {str(key): _canonical_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_value(item) for item in value]
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return _aware_utc(value, "DELETION_EVIDENCE_TIME_INVALID").isoformat()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, Enum):
        return value.value
    if value is None or isinstance(value, (str, int, bool)):
        return value
    _raise(
        DeletionPersistenceEvidenceError,
        "DELETION_EVIDENCE_VALUE_INVALID",
    )


def _transition_evidence_items(
    prior: DeletionState,
    transition: DeletionTransition,
    supplied: object | None,
) -> tuple[tuple[str, object], ...]:
    before = prior.request
    after = transition.state.request
    if after is None:
        return ()
    expected_kind: str | None = None
    if before is not None:
        if (
            before.status is DeletionRequestStatus.COOLING_OFF
            and after.status is DeletionRequestStatus.COOLING_OFF
            and before.current_action.kind is DeletionActionKind.REVIEW_APPROVE
            and before.current_action.outcome is not DeletionActionOutcome.SUCCEEDED
            and after.current_action.outcome is DeletionActionOutcome.SUCCEEDED
        ):
            expected_kind = "lockdown"
        elif after.status is DeletionRequestStatus.CANCELLED:
            expected_kind = "cancellation"
        elif (
            before.status is DeletionRequestStatus.COMMITTING
            and after.status is DeletionRequestStatus.AWAITING_OFFSITE_ACK
        ):
            expected_kind = "isolation"
        elif (
            before.offsite_ack is None
            and after.offsite_ack is not None
            and after.status is DeletionRequestStatus.AWAITING_OFFSITE_ACK
        ):
            if not isinstance(supplied, DeletionExecutorFenceEvidence):
                _raise(
                    DeletionPersistenceEvidenceError,
                    "DELETION_EXECUTOR_FENCE_EVIDENCE_REQUIRED",
                )
            return (
                ("executor_fence", supplied),
                ("offsite_ack", after.offsite_ack),
            )
        elif after.status is DeletionRequestStatus.DROPPING:
            expected_kind = "claim_release"
        elif after.status is DeletionRequestStatus.COMPLETED:
            expected_kind = "destructive_cleanup"
    if expected_kind is None:
        if supplied is not None:
            _raise(
                DeletionPersistenceEvidenceError,
                "DELETION_EVIDENCE_UNEXPECTED",
            )
        return ()
    expected_type = {
        "lockdown": DeletionLockdownEvidence,
        "cancellation": CancellationEvidence,
        "isolation": DeletionIsolationEvidence,
        "claim_release": DeletionClaimReleaseEvidence,
        "destructive_cleanup": DestructiveCleanupEvidence,
    }[expected_kind]
    if not isinstance(supplied, expected_type):
        _raise(
            DeletionPersistenceEvidenceError,
            "DELETION_EVIDENCE_REQUIRED",
        )
    return ((expected_kind, supplied),)


def _transition_requires_lease(
    prior: DeletionState,
    transition: DeletionTransition,
    evidence_items: tuple[tuple[str, object], ...],
) -> bool:
    if evidence_items:
        return True
    before = prior.request.status if prior.request is not None else None
    after = (
        transition.state.request.status
        if transition.state.request is not None
        else None
    )
    irreversible = {
        DeletionRequestStatus.COMMITTING,
        DeletionRequestStatus.AWAITING_OFFSITE_ACK,
        DeletionRequestStatus.RELEASING_CLAIMS,
        DeletionRequestStatus.DROPPING,
        DeletionRequestStatus.FAILED,
        DeletionRequestStatus.COMPLETED,
    }
    return before in irreversible or after in irreversible


def _required_effect_kinds(
    receipt_kind: str,
    *,
    recovery_required: bool,
) -> frozenset[str] | None:
    if receipt_kind == "lockdown":
        return frozenset(
            {
                DeletionEffectKind.REVOKE_ALL_SESSIONS.value,
                DeletionEffectKind.DISPOSE_TENANT_ENGINES.value,
                DeletionEffectKind.BLOCK_JOB_LEASES.value,
                DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS.value,
                DeletionEffectKind.SET_DESIRED_DML_LOCKED.value,
                DeletionEffectKind.LOCK_ALL_DML_IDENTITIES.value,
                DeletionEffectKind.CREATE_DELETION_ENFORCE_LOCKED_ACTION.value,
                DeletionEffectKind.SUPERSEDE_LOWER_PRIORITY_LIFECYCLE_ACTIONS.value,
            }
        )
    if receipt_kind == "isolation":
        return frozenset(
            {
                DeletionEffectKind.REVOKE_ALL_SESSIONS.value,
                DeletionEffectKind.DISPOSE_TENANT_ENGINES.value,
                DeletionEffectKind.BLOCK_JOB_LEASES.value,
                DeletionEffectKind.RECLAIM_TENANT_JOB_LEASES.value,
                DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS.value,
                DeletionEffectKind.ISOLATE_PROVIDER_OPERATIONS.value,
                DeletionEffectKind.SET_DESIRED_DML_LOCKED.value,
                DeletionEffectKind.LOCK_ALL_DML_IDENTITIES.value,
                DeletionEffectKind.SUPERSEDE_LOWER_PRIORITY_LIFECYCLE_ACTIONS.value,
            }
        )
    if receipt_kind == "offsite_ack":
        return frozenset({DeletionEffectKind.REPLICATE_TOMBSTONE_OFFSITE.value})
    if receipt_kind == "claim_release":
        values = {
            DeletionEffectKind.RELEASE_TENANT_PROVIDER_CLAIMS.value,
            DeletionEffectKind.APPEND_PROVIDER_CLAIM_RELEASE_EVENTS.value,
            DeletionEffectKind.ISOLATE_PROVIDER_OPERATIONS.value,
        }
        if recovery_required:
            values.add(DeletionEffectKind.RECORD_RECOVERY_TOMBSTONED_DISPOSITIONS.value)
        return frozenset(values)
    if receipt_kind == "destructive_cleanup":
        return frozenset(
            {
                DeletionEffectKind.REVOKE_TENANT_DATABASE_IDENTITIES.value,
                DeletionEffectKind.REMOVE_TENANT_DATABASE_ROUTES.value,
                DeletionEffectKind.REMOVE_TENANT_PROVIDER_ACCOUNTS_AND_BINDINGS.value,
                DeletionEffectKind.DROP_TENANT_SCHEMA.value,
                DeletionEffectKind.MINIMIZE_TENANT_CONTROL_DATA.value,
            }
        )
    if receipt_kind == "cancellation":
        return None
    return frozenset()


def _validate_status_edge(
    before: DeletionRequest | None,
    after: DeletionRequest | None,
) -> None:
    if before is None:
        if after is None or after.status is not DeletionRequestStatus.PENDING_REVIEW:
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_STATUS_EDGE_INVALID",
            )
        return
    if after is None:
        _raise(
            DeletionPersistenceConflictError,
            "DELETION_STATUS_EDGE_INVALID",
        )
    allowed = {
        DeletionRequestStatus.PENDING_REVIEW: {
            DeletionRequestStatus.REJECTED,
            DeletionRequestStatus.COOLING_OFF,
        },
        DeletionRequestStatus.REJECTED: {DeletionRequestStatus.PENDING_REVIEW},
        DeletionRequestStatus.COOLING_OFF: {
            DeletionRequestStatus.COOLING_OFF,
            DeletionRequestStatus.CANCELLED,
            DeletionRequestStatus.COMMITTING,
        },
        DeletionRequestStatus.CANCELLED: {DeletionRequestStatus.PENDING_REVIEW},
        DeletionRequestStatus.COMMITTING: {
            DeletionRequestStatus.AWAITING_OFFSITE_ACK,
            DeletionRequestStatus.FAILED,
        },
        DeletionRequestStatus.AWAITING_OFFSITE_ACK: {
            DeletionRequestStatus.AWAITING_OFFSITE_ACK,
            DeletionRequestStatus.RELEASING_CLAIMS,
            DeletionRequestStatus.FAILED,
        },
        DeletionRequestStatus.RELEASING_CLAIMS: {
            DeletionRequestStatus.DROPPING,
            DeletionRequestStatus.FAILED,
        },
        DeletionRequestStatus.DROPPING: {
            DeletionRequestStatus.COMPLETED,
            DeletionRequestStatus.FAILED,
        },
        DeletionRequestStatus.FAILED: {
            DeletionRequestStatus.COMMITTING,
            DeletionRequestStatus.AWAITING_OFFSITE_ACK,
            DeletionRequestStatus.RELEASING_CLAIMS,
            DeletionRequestStatus.DROPPING,
        },
        DeletionRequestStatus.COMPLETED: set(),
    }
    if after.status is before.status:
        return
    if after.status not in allowed[before.status]:
        _raise(
            DeletionPersistenceConflictError,
            "DELETION_STATUS_EDGE_INVALID",
        )
    if before.status is DeletionRequestStatus.FAILED:
        if after.status is not before.failure_resume_status:
            _raise(
                DeletionPersistenceConflictError,
                "DELETION_RETRY_BOUNDARY_CHANGED",
            )


def _to_state(
    *,
    tenant: Tenant,
    route: TenantDatabase | None,
    hold: TenantRecoveryHold,
    request_row: TenantDeletionRequest | None,
    action_row: TenantDeletionAction | None,
    tombstone_row: TenantDeletionTombstone | None,
) -> DeletionState:
    try:
        tenant_status = TenantStatus(tenant.status)
    except ValueError:
        _raise(
            DeletionPersistenceAuthorityError,
            "DELETION_TENANT_STATUS_INVALID",
        )
    if request_row is None:
        if route is None or route.dml_credential_generation is None:
            _raise(
                DeletionPersistenceAuthorityError,
                "DELETION_ROUTE_UNAVAILABLE",
            )
        try:
            desired = DmlLoginState(route.dml_desired_login_state)
        except (TypeError, ValueError):
            _raise(
                DeletionPersistenceAuthorityError,
                "DELETION_ROUTE_DML_STATE_INVALID",
            )
        return DeletionState(
            tenant_id=UUID(tenant.id),
            database_id=UUID(route.database_uuid),
            tenant_status=tenant_status,
            tenant_access_version=tenant.access_version,
            desired_dml_login_state=desired,
            published_dml_generation=route.dml_credential_generation,
            latest_dml_generation=route.dml_credential_generation,
            candidate_dml_generation=None,
            recovery_dispositions_required=True,
        )
    if action_row is None:
        _raise(
            DeletionPersistenceAuthorityError,
            "DELETION_CURRENT_ACTION_MISSING",
        )
    action = DeletionAction(
        action_id=UUID(action_row.id),
        kind=DeletionActionKind(action_row.kind),
        execution_generation=action_row.execution_generation,
        executor_fencing_token=action_row.executor_fencing_token,
        idempotency_key=action_row.idempotency_key,
        request_digest=action_row.request_digest,
        outcome=DeletionActionOutcome(action_row.outcome),
        failure_code=action_row.failure_code,
    )
    tombstone = _domain_tombstone(tombstone_row)
    ack = _domain_ack(tombstone_row)
    request = DeletionRequest(
        request_id=UUID(request_row.id),
        requested_by_user_id=UUID(request_row.requested_by_user_id),
        status=DeletionRequestStatus(request_row.status),
        revision=request_row.request_revision,
        execution_generation=request_row.execution_generation,
        executor_fencing_token=request_row.executor_fencing_token,
        current_action=action,
        requested_at_utc=_database_utc(request_row.requested_at),
        reviewed_by_platform_admin_id=_optional_uuid(
            request_row.reviewed_by_platform_admin_id
        ),
        cancelled_by_user_id=_optional_uuid(request_row.cancelled_by_user_id),
        reviewed_at_utc=_optional_database_utc(request_row.reviewed_at),
        execute_not_before_utc=_optional_database_utc(request_row.execute_not_before),
        cancelled_at_utc=_optional_database_utc(request_row.cancelled_at),
        pre_freeze_tenant_status=(
            TenantStatus(request_row.pre_freeze_tenant_status)
            if request_row.pre_freeze_tenant_status
            else None
        ),
        pre_freeze_suspension_phase=(
            SuspensionPhase(request_row.pre_freeze_suspension_phase)
            if request_row.pre_freeze_suspension_phase
            else None
        ),
        tombstone=tombstone,
        offsite_ack=ack,
        failure_resume_status=(
            DeletionRequestStatus(request_row.failure_resume_status)
            if request_row.failure_resume_status
            else None
        ),
        failure_code=request_row.failure_code,
    )
    published = request_row.published_dml_generation
    latest = request_row.latest_dml_generation
    if route is not None and route.dml_credential_generation is not None:
        published = route.dml_credential_generation
        latest = max(latest, published)
    desired = DmlLoginState(request_row.desired_dml_login_state)
    if (
        request.status
        in {
            DeletionRequestStatus.COOLING_OFF,
            DeletionRequestStatus.COMMITTING,
            DeletionRequestStatus.AWAITING_OFFSITE_ACK,
            DeletionRequestStatus.RELEASING_CLAIMS,
            DeletionRequestStatus.DROPPING,
            DeletionRequestStatus.FAILED,
            DeletionRequestStatus.COMPLETED,
        }
        and route is not None
        and route.dml_desired_login_state != "locked"
    ):
        _raise(
            DeletionPersistenceAuthorityError,
            "DELETION_ROUTE_NOT_LOCKED",
        )
    return DeletionState(
        tenant_id=UUID(request_row.tenant_id),
        database_id=UUID(request_row.database_uuid),
        tenant_status=tenant_status,
        tenant_access_version=tenant.access_version,
        desired_dml_login_state=desired,
        published_dml_generation=published,
        latest_dml_generation=latest,
        candidate_dml_generation=request_row.candidate_dml_generation,
        request=request,
        recovery_dispositions_required=True,
    )


def _domain_tombstone(
    row: TenantDeletionTombstone | None,
) -> DeletionTombstone | None:
    if row is None:
        return None
    return DeletionTombstone(
        request_id=UUID(row.deletion_request_id),
        tenant_id=UUID(row.tenant_id),
        database_id=UUID(row.database_uuid),
        sequence=row.ledger_sequence,
        previous_hash=row.previous_hash,
        record_hash=row.record_hash,
        head_hash=row.head_hash,
        checkpoint_root_key_version=row.checkpoint_root_key_version,
        checkpoint_mac=row.checkpoint_mac,
        recorded_at_utc=_database_utc(row.recorded_at),
    )


def _domain_ack(
    row: TenantDeletionTombstone | None,
) -> OffsiteTombstoneAck | None:
    if row is None or row.offsite_acknowledged_at is None:
        return None
    if row.offsite_artifact_checksum is None:
        _raise(
            DeletionPersistenceAuthorityError,
            "DELETION_OFFSITE_ACK_CORRUPT",
        )
    return OffsiteTombstoneAck(
        sequence=row.ledger_sequence,
        head_hash=row.head_hash,
        artifact_checksum=row.offsite_artifact_checksum,
        acknowledged_at_utc=_database_utc(row.offsite_acknowledged_at),
        authenticated=row.offsite_authenticated,
        durably_persisted=row.offsite_durably_persisted,
        checksum_verified=row.offsite_checksum_verified,
        chain_verified=row.offsite_chain_verified,
    )


def _require_tombstone_match(
    row: TenantDeletionTombstone,
    tombstone: DeletionTombstone,
) -> None:
    if (
        row.tenant_id != str(tombstone.tenant_id)
        or row.database_uuid != str(tombstone.database_id)
        or row.ledger_sequence != tombstone.sequence
        or row.previous_hash != tombstone.previous_hash
        or row.record_hash != tombstone.record_hash
        or row.head_hash != tombstone.head_hash
        or row.checkpoint_root_key_version != tombstone.checkpoint_root_key_version
        or row.checkpoint_mac != tombstone.checkpoint_mac
        or _database_utc(row.recorded_at) != tombstone.recorded_at_utc
    ):
        _raise(
            DeletionPersistenceConflictError,
            "DELETION_TOMBSTONE_CONFLICT",
        )


def _require_ack_match(
    row: TenantDeletionTombstone,
    ack: OffsiteTombstoneAck,
) -> None:
    if (
        row.ledger_sequence != ack.sequence
        or row.head_hash != ack.head_hash
        or row.offsite_artifact_checksum != ack.artifact_checksum
        or row.offsite_acknowledged_at is None
        or _database_utc(row.offsite_acknowledged_at) != ack.acknowledged_at_utc
        or row.offsite_authenticated != ack.authenticated
        or row.offsite_durably_persisted != ack.durably_persisted
        or row.offsite_checksum_verified != ack.checksum_verified
        or row.offsite_chain_verified != ack.chain_verified
    ):
        _raise(
            DeletionPersistenceConflictError,
            "DELETION_OFFSITE_ACK_CONFLICT",
        )


def _state_with_executor_takeover(
    state: DeletionState,
    *,
    request_revision: int,
    execution_generation: int,
    executor_fencing_token: int,
    reset_cooling_lockdown: bool,
) -> DeletionState:
    request = state.request
    if request is None:
        _raise(
            DeletionPersistenceLeaseError,
            "DELETION_LEASE_REQUEST_UNAVAILABLE",
        )
    action = replace(
        request.current_action,
        execution_generation=execution_generation,
        executor_fencing_token=executor_fencing_token,
        outcome=(
            DeletionActionOutcome.RUNNING
            if reset_cooling_lockdown
            else request.current_action.outcome
        ),
        failure_code=(
            None if reset_cooling_lockdown else request.current_action.failure_code
        ),
    )
    return replace(
        state,
        request=replace(
            request,
            revision=request_revision,
            execution_generation=execution_generation,
            executor_fencing_token=executor_fencing_token,
            current_action=action,
        ),
    )


def _redrive_effects(state: DeletionState) -> tuple[DeletionEffectFact, ...]:
    request = state.request
    if request is None:
        return ()
    if request.status is DeletionRequestStatus.COOLING_OFF:
        kinds = (
            DeletionEffectKind.REVOKE_ALL_SESSIONS,
            DeletionEffectKind.DISPOSE_TENANT_ENGINES,
            DeletionEffectKind.BLOCK_JOB_LEASES,
            DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
            DeletionEffectKind.SET_DESIRED_DML_LOCKED,
            DeletionEffectKind.LOCK_ALL_DML_IDENTITIES,
            DeletionEffectKind.CREATE_DELETION_ENFORCE_LOCKED_ACTION,
            DeletionEffectKind.SUPERSEDE_LOWER_PRIORITY_LIFECYCLE_ACTIONS,
        )
    elif request.status is DeletionRequestStatus.COMMITTING:
        kinds = (
            DeletionEffectKind.REVOKE_ALL_SESSIONS,
            DeletionEffectKind.DISPOSE_TENANT_ENGINES,
            DeletionEffectKind.BLOCK_JOB_LEASES,
            DeletionEffectKind.RECLAIM_TENANT_JOB_LEASES,
            DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
            DeletionEffectKind.ISOLATE_PROVIDER_OPERATIONS,
            DeletionEffectKind.SET_DESIRED_DML_LOCKED,
            DeletionEffectKind.LOCK_ALL_DML_IDENTITIES,
            DeletionEffectKind.SUPERSEDE_LOWER_PRIORITY_LIFECYCLE_ACTIONS,
        )
    elif request.status is DeletionRequestStatus.AWAITING_OFFSITE_ACK:
        kinds = (DeletionEffectKind.REPLICATE_TOMBSTONE_OFFSITE,)
    elif request.status is DeletionRequestStatus.RELEASING_CLAIMS:
        values = [
            DeletionEffectKind.RELEASE_TENANT_PROVIDER_CLAIMS,
            DeletionEffectKind.APPEND_PROVIDER_CLAIM_RELEASE_EVENTS,
            DeletionEffectKind.ISOLATE_PROVIDER_OPERATIONS,
        ]
        if state.recovery_dispositions_required:
            values.append(DeletionEffectKind.RECORD_RECOVERY_TOMBSTONED_DISPOSITIONS)
        kinds = tuple(values)
    elif request.status is DeletionRequestStatus.DROPPING:
        kinds = (
            DeletionEffectKind.REVOKE_TENANT_DATABASE_IDENTITIES,
            DeletionEffectKind.REMOVE_TENANT_DATABASE_ROUTES,
            DeletionEffectKind.REMOVE_TENANT_PROVIDER_ACCOUNTS_AND_BINDINGS,
            DeletionEffectKind.DROP_TENANT_SCHEMA,
            DeletionEffectKind.MINIMIZE_TENANT_CONTROL_DATA,
        )
    else:
        kinds = (
            DeletionEffectKind.BLOCK_JOB_LEASES,
            DeletionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
            DeletionEffectKind.SET_DESIRED_DML_LOCKED,
            DeletionEffectKind.LOCK_ALL_DML_IDENTITIES,
        )
    sequence = request.tombstone.sequence if request.tombstone else None
    return tuple(
        DeletionEffectFact(
            kind=kind,
            request_id=request.request_id,
            action_id=request.current_action.action_id,
            execution_generation=request.execution_generation,
            executor_fencing_token=request.executor_fencing_token,
            tenant_access_version=state.tenant_access_version,
            tombstone_sequence=sequence,
        )
        for kind in kinds
    )


def _persisted_effects(
    rows: tuple[TenantDeletionEffect, ...],
) -> tuple[PersistedDeletionEffect, ...]:
    return tuple(
        PersistedDeletionEffect(
            effect_id=UUID(row.id),
            fact=DeletionEffectFact(
                kind=DeletionEffectKind(row.effect_kind),
                request_id=UUID(row.deletion_request_id),
                action_id=UUID(row.action_id),
                execution_generation=row.execution_generation,
                executor_fencing_token=row.executor_fencing_token,
                tenant_access_version=row.tenant_access_version,
                dml_generation=row.dml_generation,
                tombstone_sequence=row.tombstone_sequence,
            ),
            state=row.state,
        )
        for row in rows
    )


def _read_database_utc_now(session: Session) -> datetime:
    return _database_utc(read_database_utc_value(session))


def _database_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        _raise(
            DeletionPersistenceTransactionError,
            "DELETION_DATABASE_CLOCK_INVALID",
        )
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _optional_database_utc(value: object) -> datetime | None:
    return None if value is None else _database_utc(value)


def _aware_utc(value: object, code: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        _raise(DeletionPersistenceConflictError, code)
    return value.astimezone(timezone.utc)


def _uuid(value: object, code: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    _raise(DeletionPersistenceConflictError, code)


def _optional_uuid(value: object) -> UUID | None:
    return None if value is None else _uuid(value, "DELETION_UUID_INVALID")


def _uuid_text(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _enum_text(value: Enum | None) -> str | None:
    return value.value if value is not None else None


def _positive(value: object, code: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        _raise(DeletionPersistenceConflictError, code)
    return value


def _digest(value: object, code: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        _raise(DeletionPersistenceConflictError, code)
    return value


def _token(value: object, code: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or _SAFE_TOKEN.fullmatch(value) is None
    ):
        _raise(DeletionPersistenceConflictError, code)
    return value


def _safe_code(value: object) -> str:
    if not isinstance(value, str) or _SAFE_CODE.fullmatch(value) is None:
        _raise(
            DeletionPersistenceEvidenceError,
            "DELETION_SAFE_OUTCOME_CODE_INVALID",
        )
    return value


def _lease_duration(value: object) -> timedelta:
    if (
        not isinstance(value, timedelta)
        or value <= timedelta(0)
        or value > _MAX_LEASE_DURATION
    ):
        _raise(
            DeletionPersistenceLeaseError,
            "DELETION_LEASE_DURATION_INVALID",
        )
    return value


def _raise(error_type: type[DeletionPersistenceError], code: str) -> None:
    raise error_type(code)


__all__ = [
    "DeletionActionIdentity",
    "DeletionEvidenceCurrentRead",
    "DeletionEvidenceVerification",
    "DeletionExecutorLease",
    "DeletionLeaseResult",
    "DeletionPersistenceAuthorityError",
    "DeletionPersistenceConflictError",
    "DeletionPersistenceError",
    "DeletionPersistenceEvidenceError",
    "DeletionPersistenceLeaseError",
    "DeletionPersistenceProjectionError",
    "DeletionPersistenceResult",
    "DeletionPersistenceTransactionError",
    "ExpandingRouteProjectionWriter",
    "PersistedDeletionEffect",
    "RecoveryDispositionVerification",
    "RouteProjectionVerification",
    "TenantDeletionPersistenceCoordinator",
    "deletion_evidence_digest",
]
