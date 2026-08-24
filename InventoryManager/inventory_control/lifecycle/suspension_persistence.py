"""Caller-owned SQLAlchemy coordination for the D52 suspension reducer.

The coordinator owns only short control-database transactions.  It persists
the reducer state, authorization provenance, immediate deny projections, and
durable outbox facts atomically.  It never connects to a tenant database,
claims a MySQL advisory lock, performs physical account changes, or publishes
a DML candidate.
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session

from inventory_control.domain.tenant_gate import TenantStatus
from inventory_control.models.deletion import TenantDeletionRequest
from inventory_control.models.foundation import Tenant, TenantDatabase
from inventory_control.models.identity import TenantMembership, TenantUserSession
from inventory_control.models.jobs import ControlOutboxEvent
from inventory_control.models.platform_identity import (
    PlatformAdmin,
    PlatformAdminSession,
)
from inventory_control.transactions import require_caller_transaction
from inventory_control.models.recovery import (
    DisasterRecoveryRun,
    TenantRecoveryHold,
)
from inventory_control.models.subscriptions import Subscription
from inventory_control.models.suspensions import (
    TenantSuspension,
    TenantSuspensionAction,
)
from inventory_control.jobs.outbox_service import (
    RESULT_DIGEST_VERSION,
    verify_persisted_safe_result_mac,
)

from .suspension import (
    DmlLoginState,
    FreezeBarrierEvidence,
    SuspensionAction,
    SuspensionActionDirection,
    SuspensionActionOutcome,
    SuspensionEffectFact,
    SuspensionEffectKind,
    SuspensionPhase,
    SuspensionState,
    SuspensionTransition,
    SuspensionTransitionError,
    complete_suspend as _reduce_complete_suspend,
    fail_current_barrier as _reduce_fail_current_barrier,
    request_resume as _reduce_request_resume,
    request_suspend as _reduce_request_suspend,
)


_SAFE_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_SAFE_CORRELATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#-]{0,159}\Z")
_OUTBOX_SOURCE_TYPE = "tenant_suspension_action"
_FREEZE_RESULT_SAFE_CODE = "SUSPENSION_EFFECT_COMPLETED"
_FREEZE_EFFECT_EVENT_TYPES = frozenset(
    {
        f"suspension.{kind.value}"
        for kind in (
            SuspensionEffectKind.REVOKE_ALL_SESSIONS,
            SuspensionEffectKind.DISPOSE_TENANT_ENGINES,
            SuspensionEffectKind.BLOCK_JOB_LEASES,
            SuspensionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
            SuspensionEffectKind.SET_DESIRED_DML_LOCKED,
            SuspensionEffectKind.LOCK_ALL_DML_IDENTITIES,
        )
    }
)


class SuspensionPersistenceError(RuntimeError):
    """Stable, non-sensitive persistence rejection."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class SuspensionPersistenceTransactionError(SuspensionPersistenceError):
    pass


class SuspensionPersistenceConflictError(SuspensionPersistenceError):
    pass


class SuspensionPersistenceGateError(SuspensionPersistenceError):
    pass


class SuspensionPersistenceAuthorityError(SuspensionPersistenceError):
    pass


class SuspensionPersistenceProofError(SuspensionPersistenceError):
    pass


class SuspensionPersistenceBoundaryError(SuspensionPersistenceError):
    """A safe boundary intentionally delegated to account mutation."""


@dataclass(frozen=True, slots=True)
class SuspensionPlatformActionRequest:
    tenant_uuid: str | UUID
    suspension_uuid: str | UUID
    action_uuid: str | UUID
    expected_recovery_run_uuid: str | UUID
    expected_hold_uuid: str | UUID
    expected_hold_revision: int
    expected_suspension_row_version: int
    expected_barrier_generation: int
    expected_tenant_row_version: int
    expected_access_version: int
    expected_route_row_version: int
    expected_login_state_version: int
    platform_admin_uuid: str | UUID
    platform_session_uuid: str | UUID
    recent_step_up_method: str
    recent_step_up_at: datetime
    reason_code: str
    safe_note: str | None
    safe_correlation: str | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class SuspensionBarrierCommand:
    tenant_uuid: str | UUID
    suspension_uuid: str | UUID
    action_uuid: str | UUID
    expected_recovery_run_uuid: str | UUID
    expected_hold_uuid: str | UUID
    expected_hold_revision: int
    expected_suspension_row_version: int
    expected_tenant_row_version: int
    expected_access_version: int
    expected_route_row_version: int
    expected_login_state_version: int


@dataclass(frozen=True, slots=True)
class SuspensionPersistenceResult:
    suspension_uuid: UUID
    action_uuid: UUID
    direction: SuspensionActionDirection
    phase: SuspensionPhase
    action_outcome: SuspensionActionOutcome
    barrier_generation: int
    tenant_status: TenantStatus
    tenant_row_version: int
    tenant_access_version: int
    suspension_row_version: int
    route_row_version: int
    login_state_version: int
    candidate_dml_generation: int | None
    effects: tuple[SuspensionEffectKind, ...]
    replayed: bool


@dataclass(frozen=True, slots=True)
class _NormalizedActionRequest:
    tenant_uuid: UUID
    suspension_uuid: UUID
    action_uuid: UUID
    expected_recovery_run_uuid: UUID
    expected_hold_uuid: UUID
    expected_hold_revision: int
    expected_suspension_row_version: int
    expected_barrier_generation: int
    expected_tenant_row_version: int
    expected_access_version: int
    expected_route_row_version: int
    expected_login_state_version: int
    platform_admin_uuid: UUID
    platform_session_uuid: UUID
    recent_step_up_method: str
    recent_step_up_at: datetime
    reason_code: str
    safe_note: str | None
    safe_correlation: str | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class _NormalizedBarrierCommand:
    tenant_uuid: UUID
    suspension_uuid: UUID
    action_uuid: UUID
    expected_recovery_run_uuid: UUID
    expected_hold_uuid: UUID
    expected_hold_revision: int
    expected_suspension_row_version: int
    expected_tenant_row_version: int
    expected_access_version: int
    expected_route_row_version: int
    expected_login_state_version: int


@dataclass(slots=True)
class _LockedContext:
    tenant: Tenant
    run: DisasterRecoveryRun
    hold: TenantRecoveryHold
    deletion: TenantDeletionRequest | None
    suspension: TenantSuspension | None
    action: TenantSuspensionAction | None
    subscription: Subscription
    route: TenantDatabase


DatabaseClock = Callable[[Session], datetime]


class TenantSuspensionPersistenceCoordinator:
    """Persist reducer-backed suspension boundaries without committing."""

    def __init__(
        self,
        session: Session,
        *,
        recent_step_up_window: timedelta,
        outbox_result_mac_key: bytes,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not isinstance(session, Session):
            raise SuspensionPersistenceTransactionError(
                "SUSPENSION_CALLER_TRANSACTION_REQUIRED"
            )
        if not isinstance(
            recent_step_up_window, timedelta
        ) or recent_step_up_window <= timedelta(0):
            raise ValueError("recent_step_up_window must be positive")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        if (
            not isinstance(outbox_result_mac_key, bytes)
            or len(outbox_result_mac_key) < 32
        ):
            raise ValueError("outbox_result_mac_key must contain at least 32 bytes")
        self._session = session
        self._recent_step_up_window = recent_step_up_window
        self._outbox_result_mac_key = outbox_result_mac_key
        self._database_clock = database_clock or _read_database_utc_now

    def request_freeze(
        self,
        request: SuspensionPlatformActionRequest,
    ) -> SuspensionPersistenceResult:
        """Atomically establish deny, desired-lock, action, and outbox facts."""

        self._prepare()
        normalized = _normalize_action_request(request)
        digest = suspension_action_digest(
            normalized,
            SuspensionActionDirection.FREEZE,
        )
        context = self._lock_context(normalized)
        state = self._domain_state(context)
        transition = self._reduce(
            lambda: _reduce_request_suspend(
                state,
                action_id=normalized.action_uuid,
                idempotency_key=normalized.idempotency_key,
                request_digest=digest,
                expected_access_version=normalized.expected_access_version,
                expected_barrier_generation=(normalized.expected_barrier_generation),
            )
        )
        if transition.idempotent:
            return self._replay(context, normalized, digest, transition)

        self._require_new_freeze_fences(context, normalized)
        admin, platform_session = self._lock_platform_authority(normalized)
        now = self._now()
        self._validate_platform_authority(
            admin,
            platform_session,
            normalized,
            now,
        )
        after = transition.state
        if context.suspension is not None:
            raise SuspensionPersistenceConflictError("SUSPENSION_ACTION_CONFLICT")
        if after.current_action is None:
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_REDUCER_RESULT_INVALID"
            )

        suspension = TenantSuspension(
            id=str(normalized.suspension_uuid),
            tenant_id=context.tenant.id,
            state=after.phase.value,
            initial_reason_code=normalized.reason_code,
            initial_safe_note=normalized.safe_note,
            barrier_generation=after.barrier_generation,
            committed_tenant_row_version=(context.tenant.row_version + 1),
            committed_access_version=after.tenant_access_version,
            requested_at=now,
            frozen_at=None,
            resolving_at=None,
            resolved_at=None,
            safe_failure_code=None,
            row_version=1,
            created_at=now,
            updated_at=now,
        )
        action = self._new_action(
            suspension=suspension,
            action=after.current_action,
            request=normalized,
            request_digest=digest,
            now=now,
        )
        next_route_row_version = context.route.row_version + 1
        next_login_version = context.route.dml_login_state_version + 1

        try:
            with self._session.no_autoflush:
                self._cas_tenant(
                    context.tenant,
                    expected_row_version=normalized.expected_tenant_row_version,
                    expected_access_version=normalized.expected_access_version,
                    values={
                        "status": after.tenant_status.value,
                        "access_version": after.tenant_access_version,
                        "row_version": context.tenant.row_version + 1,
                        "updated_at": now,
                    },
                )
                self._cas_route(
                    context.route,
                    expected_row_version=normalized.expected_route_row_version,
                    expected_login_state_version=(
                        normalized.expected_login_state_version
                    ),
                    values={
                        "dml_desired_login_state": "locked",
                        "dml_login_state_version": next_login_version,
                        "dml_desired_state_recovery_run_id": context.run.id,
                        "row_version": next_route_row_version,
                        "updated_at": now,
                    },
                )
                self._session.add_all((suspension, action))
                self._revoke_tenant_sessions(context.tenant.id, now)
                self._append_effects(
                    suspension=suspension,
                    action=action,
                    effects=transition.effects,
                    run=context.run,
                    hold=context.hold,
                    suspension_row_version=1,
                    route_row_version=next_route_row_version,
                    login_state_version=next_login_version,
                    now=now,
                )
                self._session.flush()
        except (IntegrityError, OperationalError):
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_CONCURRENT_WRITE"
            ) from None

        return _result(
            transition,
            suspension_uuid=normalized.suspension_uuid,
            tenant_row_version=context.tenant.row_version + 1,
            suspension_row_version=1,
            route_row_version=next_route_row_version,
            login_state_version=next_login_version,
            replayed=False,
        )

    def request_resolve(
        self,
        request: SuspensionPlatformActionRequest,
    ) -> SuspensionPersistenceResult:
        """Persist a resolve intent while keeping the application route denied.

        Candidate creation and all subsequent account work remain an outbox
        effect for the account-mutation three-stage protocol.
        """

        self._prepare()
        normalized = _normalize_action_request(request)
        digest = suspension_action_digest(
            normalized,
            SuspensionActionDirection.RESOLVE,
        )
        context = self._lock_context(normalized)
        state = self._domain_state(context)
        transition = self._reduce(
            lambda: _reduce_request_resume(
                state,
                action_id=normalized.action_uuid,
                idempotency_key=normalized.idempotency_key,
                request_digest=digest,
                expected_access_version=normalized.expected_access_version,
                expected_barrier_generation=(normalized.expected_barrier_generation),
            )
        )
        if transition.idempotent:
            return self._replay(context, normalized, digest, transition)

        self._require_resolve_fences(context, normalized)
        admin, platform_session = self._lock_platform_authority(normalized)
        now = self._now()
        self._validate_platform_authority(
            admin,
            platform_session,
            normalized,
            now,
        )
        suspension = context.suspension
        if suspension is None or transition.state.current_action is None:
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_REDUCER_RESULT_INVALID"
            )
        action = self._new_action(
            suspension=suspension,
            action=transition.state.current_action,
            request=normalized,
            request_digest=digest,
            now=now,
        )
        next_tenant_row_version = context.tenant.row_version + 1
        next_suspension_row_version = suspension.row_version + 1

        try:
            with self._session.no_autoflush:
                self._cas_tenant(
                    context.tenant,
                    expected_row_version=normalized.expected_tenant_row_version,
                    expected_access_version=normalized.expected_access_version,
                    values={
                        "status": transition.state.tenant_status.value,
                        "access_version": transition.state.tenant_access_version,
                        "row_version": next_tenant_row_version,
                        "updated_at": now,
                    },
                )
                self._cas_suspension(
                    suspension,
                    expected_row_version=(normalized.expected_suspension_row_version),
                    values={
                        "state": transition.state.phase.value,
                        "barrier_generation": (transition.state.barrier_generation),
                        "committed_tenant_row_version": (next_tenant_row_version),
                        "committed_access_version": (
                            transition.state.tenant_access_version
                        ),
                        "resolving_at": now,
                        "safe_failure_code": None,
                        "row_version": next_suspension_row_version,
                        "updated_at": now,
                    },
                )
                self._session.add(action)
                self._revoke_tenant_sessions(context.tenant.id, now)
                self._append_effects(
                    suspension=suspension,
                    action=action,
                    effects=transition.effects,
                    run=context.run,
                    hold=context.hold,
                    suspension_row_version=next_suspension_row_version,
                    route_row_version=context.route.row_version,
                    login_state_version=context.route.dml_login_state_version,
                    now=now,
                )
                self._session.flush()
        except (IntegrityError, OperationalError):
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_CONCURRENT_WRITE"
            ) from None

        return _result(
            transition,
            suspension_uuid=normalized.suspension_uuid,
            tenant_row_version=next_tenant_row_version,
            suspension_row_version=next_suspension_row_version,
            route_row_version=context.route.row_version,
            login_state_version=context.route.dml_login_state_version,
            replayed=False,
        )

    def complete_freeze(
        self,
        command: SuspensionBarrierCommand,
    ) -> SuspensionPersistenceResult:
        """Close a freeze from authenticated persisted effect receipts only."""

        self._prepare()
        normalized = _normalize_barrier_command(command)
        context = self._lock_context(normalized)
        if context.deletion is not None:
            raise SuspensionPersistenceBoundaryError(
                "SUSPENSION_HIGHER_PRIORITY_COMPENSATION_REQUIRED"
            )
        self._require_barrier_identity(context, normalized)
        evidence = self._lock_verified_freeze_receipts(context, normalized)
        state = self._domain_state(context)
        transition = self._reduce(
            lambda: _reduce_complete_suspend(state, evidence=evidence)
        )
        if transition.idempotent:
            return self._barrier_replay(
                context,
                normalized,
                transition,
                tenant_row_advanced=True,
                route_row_advanced=True,
                require_observed_locked=True,
            )
        self._require_barrier_fences(context, normalized)
        suspension = context.suspension
        action = context.action
        if suspension is None or action is None:
            raise SuspensionPersistenceConflictError("SUSPENSION_ACTION_UNAVAILABLE")
        now = self._now()
        next_tenant_row_version = context.tenant.row_version + 1
        next_suspension_row_version = suspension.row_version + 1
        next_route_row_version = context.route.row_version + 1

        try:
            with self._session.no_autoflush:
                self._cas_tenant(
                    context.tenant,
                    expected_row_version=normalized.expected_tenant_row_version,
                    expected_access_version=normalized.expected_access_version,
                    values={
                        "status": transition.state.tenant_status.value,
                        "row_version": next_tenant_row_version,
                        "updated_at": now,
                    },
                )
                self._cas_suspension(
                    suspension,
                    expected_row_version=(normalized.expected_suspension_row_version),
                    values={
                        "state": transition.state.phase.value,
                        "committed_tenant_row_version": next_tenant_row_version,
                        "frozen_at": now,
                        "safe_failure_code": None,
                        "row_version": next_suspension_row_version,
                        "updated_at": now,
                    },
                )
                self._cas_route(
                    context.route,
                    expected_row_version=normalized.expected_route_row_version,
                    expected_login_state_version=(
                        normalized.expected_login_state_version
                    ),
                    values={
                        "dml_observed_login_state": "locked",
                        "row_version": next_route_row_version,
                        "updated_at": now,
                    },
                )
                self._cas_action(
                    action,
                    values={
                        "state": "succeeded",
                        "safe_outcome_code": "suspension_freeze_completed",
                        "safe_failure_code": None,
                        "completed_at": now,
                        "row_version": action.row_version + 1,
                        "updated_at": now,
                    },
                )
                self._session.flush()
        except (IntegrityError, OperationalError):
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_CONCURRENT_WRITE"
            ) from None

        return _result(
            transition,
            suspension_uuid=normalized.suspension_uuid,
            tenant_row_version=next_tenant_row_version,
            suspension_row_version=next_suspension_row_version,
            route_row_version=next_route_row_version,
            login_state_version=context.route.dml_login_state_version,
            replayed=False,
        )

    def fail_barrier(
        self,
        command: SuspensionBarrierCommand,
        *,
        failure_code: str,
    ) -> SuspensionPersistenceResult:
        """Record a safe current-generation failure and retain deny/locked."""

        self._prepare()
        normalized = _normalize_barrier_command(command)
        safe_failure = _safe_code_value(failure_code, "failure_code")
        context = self._lock_context(normalized)
        self._require_barrier_identity(context, normalized)
        state = self._domain_state(context)
        if (
            context.action is not None
            and context.action.state == "failed"
            and context.action.safe_failure_code != safe_failure
        ):
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_FAILURE_REPLAY_MISMATCH"
            )
        transition = self._reduce(
            lambda: _reduce_fail_current_barrier(
                state,
                action_id=normalized.action_uuid,
                barrier_generation=state.barrier_generation,
                tenant_access_version=normalized.expected_access_version,
                failure_code=safe_failure,
            )
        )
        if transition.idempotent:
            return self._barrier_replay(
                context,
                normalized,
                transition,
                tenant_row_advanced=False,
                route_row_advanced=False,
                require_observed_locked=False,
            )
        self._require_barrier_fences(context, normalized)
        suspension = context.suspension
        action = context.action
        if suspension is None or action is None:
            raise SuspensionPersistenceConflictError("SUSPENSION_ACTION_UNAVAILABLE")
        now = self._now()
        next_suspension_row_version = suspension.row_version + 1
        aggregate_failure = (
            safe_failure if transition.state.phase is SuspensionPhase.FAILED else None
        )

        try:
            with self._session.no_autoflush:
                self._cas_suspension(
                    suspension,
                    expected_row_version=(normalized.expected_suspension_row_version),
                    values={
                        "state": transition.state.phase.value,
                        "safe_failure_code": aggregate_failure,
                        "row_version": next_suspension_row_version,
                        "updated_at": now,
                    },
                )
                self._cas_action(
                    action,
                    values={
                        "state": "failed",
                        "safe_outcome_code": "suspension_barrier_failed",
                        "safe_failure_code": safe_failure,
                        "completed_at": now,
                        "row_version": action.row_version + 1,
                        "updated_at": now,
                    },
                )
                self._append_effects(
                    suspension=suspension,
                    action=action,
                    effects=transition.effects,
                    run=context.run,
                    hold=context.hold,
                    suspension_row_version=next_suspension_row_version,
                    route_row_version=context.route.row_version,
                    login_state_version=context.route.dml_login_state_version,
                    now=now,
                    stage="failure",
                )
                self._session.flush()
        except (IntegrityError, OperationalError):
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_CONCURRENT_WRITE"
            ) from None

        return _result(
            transition,
            suspension_uuid=normalized.suspension_uuid,
            tenant_row_version=context.tenant.row_version,
            suspension_row_version=next_suspension_row_version,
            route_row_version=context.route.row_version,
            login_state_version=context.route.dml_login_state_version,
            replayed=False,
        )

    def complete_resume(self, *_args: object, **_kwargs: object) -> None:
        """Fail closed until account-mutation publication proof is integrated."""

        self._prepare()
        raise SuspensionPersistenceBoundaryError(
            "SUSPENSION_ACCOUNT_MUTATION_PROOF_REQUIRED"
        )

    def request_enforce_locked(self, *_args: object, **_kwargs: object) -> None:
        """Fail closed because the selected pure reducer has no such action."""

        self._prepare()
        raise SuspensionPersistenceBoundaryError(
            "SUSPENSION_ENFORCE_LOCKED_REDUCER_REQUIRED"
        )

    freeze = request_freeze
    resolve = request_resolve

    def _prepare(self) -> None:
        require_caller_transaction(
            self._session,
            lambda: SuspensionPersistenceTransactionError(
                "SUSPENSION_CALLER_TRANSACTION_REQUIRED"
            ),
            dirty_error=lambda: SuspensionPersistenceTransactionError(
                "SUSPENSION_CLEAN_CALLER_UNIT_OF_WORK_REQUIRED"
            ),
            clean=True,
        )

    def _lock_context(
        self,
        request: _NormalizedActionRequest | _NormalizedBarrierCommand,
    ) -> _LockedContext:
        # Global order: tenant -> current run -> current hold -> deletion ->
        # suspension/action -> subscription -> route.  Platform authority, if
        # needed, is locked only after this prefix.
        tenant = self._session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == str(request.tenant_uuid))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if tenant is None:
            raise SuspensionPersistenceGateError("SUSPENSION_TENANT_UNAVAILABLE")
        run = self._session.scalar(
            sa.select(DisasterRecoveryRun)
            .where(DisasterRecoveryRun.current_run_marker == "current")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is None:
            raise SuspensionPersistenceGateError("SUSPENSION_RECOVERY_RUN_UNAVAILABLE")
        hold = self._session.scalar(
            sa.select(TenantRecoveryHold)
            .where(
                TenantRecoveryHold.recovery_run_id == run.id,
                TenantRecoveryHold.tenant_id == tenant.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if hold is None:
            raise SuspensionPersistenceGateError("SUSPENSION_RECOVERY_HOLD_UNAVAILABLE")
        deletion = self._session.scalar(
            sa.select(TenantDeletionRequest)
            .where(
                TenantDeletionRequest.tenant_id == tenant.id,
                TenantDeletionRequest.active_tenant_id == tenant.id,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        suspension = self._session.scalar(
            sa.select(TenantSuspension)
            .where(TenantSuspension.active_tenant_id == tenant.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        action = None
        if suspension is not None:
            action = self._session.scalar(
                sa.select(TenantSuspensionAction)
                .where(
                    TenantSuspensionAction.suspension_id == suspension.id,
                    TenantSuspensionAction.generation == suspension.barrier_generation,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            if action is None:
                raise SuspensionPersistenceConflictError(
                    "SUSPENSION_STORED_STATE_INVALID"
                )
        subscription = self._session.scalar(
            sa.select(Subscription)
            .where(Subscription.tenant_id == tenant.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if subscription is None:
            raise SuspensionPersistenceGateError("SUSPENSION_SUBSCRIPTION_UNAVAILABLE")
        route = self._session.scalar(
            sa.select(TenantDatabase)
            .where(TenantDatabase.tenant_id == tenant.id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            route is None
            or route.status != "ready"
            or route.dml_credential_generation is None
            or route.dml_desired_login_state is None
            or route.dml_login_state_version is None
        ):
            raise SuspensionPersistenceGateError("SUSPENSION_ROUTE_UNAVAILABLE")
        return _LockedContext(
            tenant=tenant,
            run=run,
            hold=hold,
            deletion=deletion,
            suspension=suspension,
            action=action,
            subscription=subscription,
            route=route,
        )

    def _domain_state(self, context: _LockedContext) -> SuspensionState:
        try:
            tenant_status = TenantStatus(context.tenant.status)
            desired = DmlLoginState(context.route.dml_desired_login_state)
            published = context.route.dml_credential_generation
            if context.suspension is None:
                return SuspensionState.eligible(
                    tenant_status=tenant_status,
                    tenant_access_version=context.tenant.access_version,
                    published_dml_generation=published,
                )
            if context.action is None:
                raise ValueError("missing action")
            outcome = {
                "requested": SuspensionActionOutcome.RUNNING,
                "running": SuspensionActionOutcome.RUNNING,
                "succeeded": SuspensionActionOutcome.SUCCEEDED,
                "failed": SuspensionActionOutcome.FAILED,
            }.get(context.action.state)
            if outcome is None:
                raise ValueError("unsupported action state")
            action = SuspensionAction(
                action_id=UUID(context.action.id),
                direction=SuspensionActionDirection(context.action.direction),
                generation=context.action.generation,
                idempotency_key=context.action.idempotency_key,
                request_digest=bytes(context.action.request_digest),
                outcome=outcome,
                failure_code=context.action.safe_failure_code,
            )
            phase = SuspensionPhase(context.suspension.state)
            candidate = None
            latest = published
            if phase is SuspensionPhase.RESOLVING:
                candidate = self._candidate_generation(context.action)
                latest = candidate
            return SuspensionState(
                tenant_status=tenant_status,
                tenant_access_version=context.tenant.access_version,
                barrier_generation=context.suspension.barrier_generation,
                phase=phase,
                current_action=action,
                desired_dml_login_state=desired,
                published_dml_generation=published,
                latest_dml_generation=latest,
                candidate_dml_generation=candidate,
            )
        except (TypeError, ValueError):
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_STORED_STATE_INVALID"
            ) from None

    def _candidate_generation(self, action: TenantSuspensionAction) -> int:
        event = self._session.scalar(
            sa.select(ControlOutboxEvent).where(
                ControlOutboxEvent.source_type == _OUTBOX_SOURCE_TYPE,
                ControlOutboxEvent.source_uuid == action.id,
                ControlOutboxEvent.source_generation == action.generation,
                ControlOutboxEvent.event_type
                == "suspension.create_locked_unpublished_dml_candidate",
            )
        )
        value = None if event is None else event.payload.get("dml_generation")
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_CANDIDATE_FACT_UNAVAILABLE"
            )
        return value

    def _require_new_freeze_fences(
        self,
        context: _LockedContext,
        request: _NormalizedActionRequest,
    ) -> None:
        self._require_gate_fences(context, request)
        if context.deletion is not None:
            raise SuspensionPersistenceGateError("SUSPENSION_DELETION_IN_PROGRESS")
        if context.suspension is not None:
            raise SuspensionPersistenceConflictError("SUSPENSION_ACTION_CONFLICT")
        if (
            request.expected_suspension_row_version != 0
            or request.expected_barrier_generation != 0
            or context.tenant.row_version != request.expected_tenant_row_version
            or context.tenant.access_version != request.expected_access_version
            or context.route.row_version != request.expected_route_row_version
            or context.route.dml_login_state_version
            != request.expected_login_state_version
        ):
            raise SuspensionPersistenceConflictError("SUSPENSION_VERSION_CONFLICT")
        if (
            context.tenant.status not in {"active", "expired"}
            or context.subscription.status != context.tenant.status
        ):
            raise SuspensionPersistenceGateError("SUSPENSION_FREEZE_STATE_INELIGIBLE")

    def _require_resolve_fences(
        self,
        context: _LockedContext,
        request: _NormalizedActionRequest,
    ) -> None:
        self._require_gate_fences(context, request)
        if context.deletion is not None:
            raise SuspensionPersistenceGateError("SUSPENSION_DELETION_IN_PROGRESS")
        if context.hold.state != "released":
            raise SuspensionPersistenceGateError(
                "SUSPENSION_RECOVERY_HOLD_NOT_RELEASED"
            )
        if context.run.status != "completed":
            raise SuspensionPersistenceGateError(
                "SUSPENSION_RECOVERY_RUN_NOT_COMPLETED"
            )
        suspension = context.suspension
        if (
            suspension is None
            or suspension.id != str(request.suspension_uuid)
            or suspension.state != "active"
            or suspension.row_version != request.expected_suspension_row_version
            or suspension.barrier_generation != request.expected_barrier_generation
            or context.tenant.status != "suspended"
            or context.tenant.row_version != request.expected_tenant_row_version
            or context.tenant.access_version != request.expected_access_version
            or context.route.row_version != request.expected_route_row_version
            or context.route.dml_login_state_version
            != request.expected_login_state_version
            or context.route.dml_desired_login_state != "locked"
        ):
            raise SuspensionPersistenceConflictError("SUSPENSION_VERSION_CONFLICT")

    def _require_barrier_fences(
        self,
        context: _LockedContext,
        command: _NormalizedBarrierCommand,
    ) -> None:
        suspension = context.suspension
        action = context.action
        if (
            suspension is None
            or action is None
            or suspension.id != str(command.suspension_uuid)
            or action.id != str(command.action_uuid)
            or suspension.row_version != command.expected_suspension_row_version
            or context.tenant.row_version != command.expected_tenant_row_version
            or context.tenant.access_version != command.expected_access_version
            or context.route.row_version != command.expected_route_row_version
            or context.route.dml_login_state_version
            != command.expected_login_state_version
            or context.route.dml_desired_login_state != "locked"
        ):
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_BARRIER_FENCE_CONFLICT"
            )

    def _require_barrier_identity(
        self,
        context: _LockedContext,
        command: _NormalizedBarrierCommand,
    ) -> None:
        self._require_gate_fences(context, command)
        if (
            context.suspension is None
            or context.action is None
            or context.suspension.id != str(command.suspension_uuid)
            or context.action.id != str(command.action_uuid)
            or context.tenant.id != str(command.tenant_uuid)
        ):
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_BARRIER_FENCE_CONFLICT"
            )

    def _lock_verified_freeze_receipts(
        self,
        context: _LockedContext,
        command: _NormalizedBarrierCommand,
    ) -> FreezeBarrierEvidence:
        """Authenticate the exact persisted results for one freeze generation.

        A caller-provided collection of booleans is deliberately insufficient.
        Each required effect must have reached the outbox's authenticated
        succeeded state, remain bound to the current action/access/route
        fences, and carry a valid result MAC under the process-held key.
        """

        suspension = context.suspension
        action = context.action
        if suspension is None or action is None or action.direction != "freeze":
            raise SuspensionPersistenceProofError(
                "SUSPENSION_BARRIER_RECEIPT_UNAVAILABLE"
            )
        events = self._session.scalars(
            sa.select(ControlOutboxEvent)
            .where(
                ControlOutboxEvent.source_type == _OUTBOX_SOURCE_TYPE,
                ControlOutboxEvent.source_uuid == action.id,
                ControlOutboxEvent.source_generation == action.generation,
                ControlOutboxEvent.event_type.in_(
                    tuple(sorted(_FREEZE_EFFECT_EVENT_TYPES))
                ),
            )
            .order_by(ControlOutboxEvent.event_type.asc())
            .with_for_update()
            .execution_options(autoflush=False, populate_existing=True)
        ).all()
        if (
            len(events) != len(_FREEZE_EFFECT_EVENT_TYPES)
            or {event.event_type for event in events} != _FREEZE_EFFECT_EVENT_TYPES
        ):
            raise SuspensionPersistenceProofError(
                "SUSPENSION_BARRIER_RECEIPT_INCOMPLETE"
            )

        for event in events:
            payload = event.payload
            if (
                event.tenant_id != context.tenant.id
                or event.tenant_access_version != command.expected_access_version
                or event.state != "succeeded"
                or event.execution_generation < 1
                or event.lease_owner is not None
                or event.lease_token is not None
                or event.lease_expires_at is not None
                or event.completed_at is None
                or event.last_error_code is not None
                or event.result_digest_version != RESULT_DIGEST_VERSION
                or not isinstance(event.result_digest, str)
                or not isinstance(event.result_mac, str)
                or not isinstance(payload, dict)
                or payload.get("action_uuid") != action.id
                or payload.get("suspension_uuid") != suspension.id
                or payload.get("recovery_run_uuid") != context.run.id
                or payload.get("hold_uuid") != context.hold.id
                or payload.get("expected_access_version")
                != command.expected_access_version
                or payload.get("expected_route_row_version")
                != command.expected_route_row_version
                or payload.get("expected_login_state_version")
                != command.expected_login_state_version
                or payload.get("expected_suspension_row_version")
                != action.expected_suspension_row_version + 1
                or f"suspension.{payload.get('effect')}" != event.event_type
                or not verify_persisted_safe_result_mac(
                    event_id=event.id,
                    execution_generation=event.execution_generation,
                    safe_code=_FREEZE_RESULT_SAFE_CODE,
                    digest_version=event.result_digest_version,
                    digest_hex=event.result_digest,
                    mac_hex=event.result_mac,
                    result_mac_key=self._outbox_result_mac_key,
                )
            ):
                raise SuspensionPersistenceProofError(
                    "SUSPENSION_BARRIER_RECEIPT_INVALID"
                )

        return FreezeBarrierEvidence(
            action_id=command.action_uuid,
            barrier_generation=suspension.barrier_generation,
            tenant_access_version=command.expected_access_version,
            sessions_revoked=True,
            engines_disposed=True,
            job_leases_blocked=True,
            provider_submissions_blocked=True,
            desired_dml_locked=True,
            all_dml_identities_locked=True,
        )

    def _require_gate_fences(
        self,
        context: _LockedContext,
        request: _NormalizedActionRequest | _NormalizedBarrierCommand,
    ) -> None:
        if context.run.id != str(request.expected_recovery_run_uuid):
            raise SuspensionPersistenceGateError("SUSPENSION_RECOVERY_RUN_CHANGED")
        if (
            context.hold.id != str(request.expected_hold_uuid)
            or context.hold.hold_revision != request.expected_hold_revision
        ):
            raise SuspensionPersistenceGateError("SUSPENSION_RECOVERY_HOLD_CHANGED")

    def _lock_platform_authority(
        self,
        request: _NormalizedActionRequest,
    ) -> tuple[PlatformAdmin, PlatformAdminSession]:
        admin = self._session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == str(request.platform_admin_uuid))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        platform_session = self._session.scalar(
            sa.select(PlatformAdminSession)
            .where(PlatformAdminSession.id == str(request.platform_session_uuid))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if admin is None or platform_session is None:
            raise SuspensionPersistenceAuthorityError(
                "SUSPENSION_PLATFORM_SESSION_UNAVAILABLE"
            )
        return admin, platform_session

    def _validate_platform_authority(
        self,
        admin: PlatformAdmin,
        platform_session: PlatformAdminSession,
        request: _NormalizedActionRequest,
        database_now: datetime,
    ) -> None:
        if (
            admin.status != "active"
            or admin.password_hash_encoded is None
            or admin.password_hash_algorithm is None
            or admin.password_hash_version is None
            or platform_session.platform_admin_id != admin.id
            or platform_session.auth_version_at_issue != admin.auth_version
            or platform_session.setup_version_at_issue != admin.setup_version
            or platform_session.revoked_at is not None
            or database_now >= _as_utc(platform_session.idle_expires_at)
            or database_now >= _as_utc(platform_session.absolute_expires_at)
        ):
            raise SuspensionPersistenceAuthorityError(
                "SUSPENSION_PLATFORM_SESSION_UNAVAILABLE"
            )
        mfa_at = _as_utc(platform_session.mfa_verified_at)
        if (
            platform_session.mfa_method != request.recent_step_up_method
            or mfa_at != request.recent_step_up_at
            or mfa_at > database_now
            or database_now - mfa_at > self._recent_step_up_window
        ):
            raise SuspensionPersistenceAuthorityError(
                "SUSPENSION_RECENT_STEP_UP_REQUIRED"
            )

    def _new_action(
        self,
        *,
        suspension: TenantSuspension,
        action: SuspensionAction,
        request: _NormalizedActionRequest,
        request_digest: bytes,
        now: datetime,
    ) -> TenantSuspensionAction:
        return TenantSuspensionAction(
            id=str(action.action_id),
            suspension_id=suspension.id,
            direction=action.direction.value,
            generation=action.generation,
            actor_type="platform_admin",
            platform_admin_id=str(request.platform_admin_uuid),
            platform_session_id=str(request.platform_session_uuid),
            recent_step_up_method=request.recent_step_up_method,
            recent_step_up_at=request.recent_step_up_at,
            authorization_source="user_step_up",
            authorization_source_uuid=None,
            safe_correlation=request.safe_correlation,
            reason_code=request.reason_code,
            safe_note=request.safe_note,
            idempotency_key=request.idempotency_key,
            request_digest=request_digest,
            expected_suspension_row_version=(request.expected_suspension_row_version),
            expected_tenant_row_version=request.expected_tenant_row_version,
            expected_access_version=request.expected_access_version,
            state="running",
            safe_outcome_code=None,
            safe_failure_code=None,
            requested_at=now,
            started_at=now,
            completed_at=None,
            row_version=1,
            created_at=now,
            updated_at=now,
        )

    def _append_effects(
        self,
        *,
        suspension: TenantSuspension,
        action: TenantSuspensionAction,
        effects: tuple[SuspensionEffectFact, ...],
        run: DisasterRecoveryRun,
        hold: TenantRecoveryHold,
        suspension_row_version: int,
        route_row_version: int,
        login_state_version: int,
        now: datetime,
        stage: str = "request",
    ) -> None:
        for effect in effects:
            event_type = f"suspension.{effect.kind.value}"
            if stage != "request":
                event_type = f"suspension.{stage}.{effect.kind.value}"
            self._session.add(
                ControlOutboxEvent(
                    id=str(uuid4()),
                    tenant_id=suspension.tenant_id,
                    tenant_access_version=effect.tenant_access_version,
                    source_type=_OUTBOX_SOURCE_TYPE,
                    source_uuid=action.id,
                    source_generation=effect.barrier_generation,
                    event_type=event_type,
                    payload={
                        "action_uuid": action.id,
                        "dml_generation": effect.dml_generation,
                        "effect": effect.kind.value,
                        "expected_access_version": (effect.tenant_access_version),
                        "expected_login_state_version": login_state_version,
                        "expected_route_row_version": route_row_version,
                        "expected_suspension_row_version": (suspension_row_version),
                        "hold_uuid": hold.id,
                        "recovery_run_uuid": run.id,
                        "suspension_uuid": suspension.id,
                    },
                    idempotency_key=(
                        f"{action.idempotency_key}:{stage}:{effect.kind.value}"
                    ),
                    state="pending",
                    attempts=0,
                    max_attempts=10,
                    execution_generation=0,
                    available_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )

    def _revoke_tenant_sessions(self, tenant_id: str, now: datetime) -> None:
        member_user_ids = sa.select(TenantMembership.user_id).where(
            TenantMembership.tenant_id == tenant_id,
            TenantMembership.status != "released",
        )
        self._session.execute(
            sa.update(TenantUserSession)
            .where(
                TenantUserSession.user_id.in_(member_user_ids),
                TenantUserSession.revoked_at.is_(None),
            )
            .values(
                revoked_at=now,
                revoked_reason_code="tenant_suspension_barrier",
                revoked_by_session_id=None,
            )
            .execution_options(synchronize_session=False)
        )

    def _cas_tenant(
        self,
        tenant: Tenant,
        *,
        expected_row_version: int,
        expected_access_version: int,
        values: dict[str, object],
    ) -> None:
        changed = self._session.execute(
            sa.update(Tenant)
            .where(
                Tenant.id == tenant.id,
                Tenant.row_version == expected_row_version,
                Tenant.access_version == expected_access_version,
                Tenant.status == tenant.status,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise SuspensionPersistenceConflictError("SUSPENSION_TENANT_FENCE_CONFLICT")

    def _cas_route(
        self,
        route: TenantDatabase,
        *,
        expected_row_version: int,
        expected_login_state_version: int,
        values: dict[str, object],
    ) -> None:
        changed = self._session.execute(
            sa.update(TenantDatabase)
            .where(
                TenantDatabase.tenant_id == route.tenant_id,
                TenantDatabase.database_uuid == route.database_uuid,
                TenantDatabase.row_version == expected_row_version,
                TenantDatabase.dml_login_state_version == expected_login_state_version,
                TenantDatabase.dml_desired_login_state == route.dml_desired_login_state,
                TenantDatabase.dml_observed_login_state
                == route.dml_observed_login_state,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise SuspensionPersistenceConflictError("SUSPENSION_ROUTE_FENCE_CONFLICT")

    def _cas_suspension(
        self,
        suspension: TenantSuspension,
        *,
        expected_row_version: int,
        values: dict[str, object],
    ) -> None:
        changed = self._session.execute(
            sa.update(TenantSuspension)
            .where(
                TenantSuspension.id == suspension.id,
                TenantSuspension.row_version == expected_row_version,
                TenantSuspension.state == suspension.state,
                TenantSuspension.barrier_generation == suspension.barrier_generation,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_AGGREGATE_FENCE_CONFLICT"
            )

    def _cas_action(
        self,
        action: TenantSuspensionAction,
        *,
        values: dict[str, object],
    ) -> None:
        changed = self._session.execute(
            sa.update(TenantSuspensionAction)
            .where(
                TenantSuspensionAction.id == action.id,
                TenantSuspensionAction.row_version == action.row_version,
                TenantSuspensionAction.state == action.state,
                TenantSuspensionAction.generation == action.generation,
                TenantSuspensionAction.request_digest == action.request_digest,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise SuspensionPersistenceConflictError("SUSPENSION_ACTION_FENCE_CONFLICT")

    def _replay(
        self,
        context: _LockedContext,
        request: _NormalizedActionRequest,
        request_digest: bytes,
        transition: SuspensionTransition,
    ) -> SuspensionPersistenceResult:
        suspension = context.suspension
        action = context.action
        if (
            suspension is None
            or action is None
            or suspension.id != str(request.suspension_uuid)
            or action.id != str(request.action_uuid)
            or action.platform_admin_id != str(request.platform_admin_uuid)
            or action.platform_session_id != str(request.platform_session_uuid)
            or action.recent_step_up_method != request.recent_step_up_method
            or _as_utc(action.recent_step_up_at) != request.recent_step_up_at
            or action.reason_code != request.reason_code
            or action.safe_note != request.safe_note
            or action.safe_correlation != request.safe_correlation
            or action.expected_suspension_row_version
            != request.expected_suspension_row_version
            or action.expected_tenant_row_version != request.expected_tenant_row_version
            or action.expected_access_version != request.expected_access_version
            or bytes(action.request_digest) != request_digest
        ):
            raise SuspensionPersistenceConflictError("SUSPENSION_IDEMPOTENCY_CONFLICT")
        return _result(
            transition,
            suspension_uuid=request.suspension_uuid,
            tenant_row_version=context.tenant.row_version,
            suspension_row_version=suspension.row_version,
            route_row_version=context.route.row_version,
            login_state_version=context.route.dml_login_state_version,
            replayed=True,
        )

    def _barrier_replay(
        self,
        context: _LockedContext,
        command: _NormalizedBarrierCommand,
        transition: SuspensionTransition,
        tenant_row_advanced: bool,
        route_row_advanced: bool,
        require_observed_locked: bool,
    ) -> SuspensionPersistenceResult:
        if context.suspension is None or context.action is None:
            raise SuspensionPersistenceConflictError("SUSPENSION_ACTION_UNAVAILABLE")
        expected_tenant_row_version = command.expected_tenant_row_version + (
            1 if tenant_row_advanced else 0
        )
        expected_route_row_version = command.expected_route_row_version + (
            1 if route_row_advanced else 0
        )
        if (
            context.suspension.row_version
            != command.expected_suspension_row_version + 1
            or context.tenant.row_version != expected_tenant_row_version
            or context.tenant.access_version != command.expected_access_version
            or context.route.row_version != expected_route_row_version
            or context.route.dml_login_state_version
            != command.expected_login_state_version
            or context.route.dml_desired_login_state != "locked"
            or (
                require_observed_locked
                and context.route.dml_observed_login_state != "locked"
            )
        ):
            raise SuspensionPersistenceConflictError(
                "SUSPENSION_BARRIER_REPLAY_MISMATCH"
            )
        return _result(
            transition,
            suspension_uuid=command.suspension_uuid,
            tenant_row_version=context.tenant.row_version,
            suspension_row_version=context.suspension.row_version,
            route_row_version=context.route.row_version,
            login_state_version=context.route.dml_login_state_version,
            replayed=True,
        )

    def _reduce(
        self,
        reducer: Callable[[], SuspensionTransition],
    ) -> SuspensionTransition:
        try:
            return reducer()
        except SuspensionTransitionError as error:
            raise SuspensionPersistenceConflictError(error.code) from None

    def _now(self) -> datetime:
        return _as_utc(self._database_clock(self._session))


def suspension_action_digest(
    request: SuspensionPlatformActionRequest | _NormalizedActionRequest,
    direction: SuspensionActionDirection,
) -> bytes:
    """Return the versioned digest used by exact replay and outbox identity."""

    normalized = (
        request
        if isinstance(request, _NormalizedActionRequest)
        else _normalize_action_request(request)
    )
    canonical = json.dumps(
        {
            "action_uuid": str(normalized.action_uuid),
            "canonicalization_version": 1,
            "direction": direction.value,
            "expected_access_version": normalized.expected_access_version,
            "expected_barrier_generation": (normalized.expected_barrier_generation),
            "expected_hold_revision": normalized.expected_hold_revision,
            "expected_hold_uuid": str(normalized.expected_hold_uuid),
            "expected_login_state_version": (normalized.expected_login_state_version),
            "expected_recovery_run_uuid": str(normalized.expected_recovery_run_uuid),
            "expected_route_row_version": normalized.expected_route_row_version,
            "expected_suspension_row_version": (
                normalized.expected_suspension_row_version
            ),
            "expected_tenant_row_version": (normalized.expected_tenant_row_version),
            "idempotency_key": normalized.idempotency_key,
            "platform_admin_uuid": str(normalized.platform_admin_uuid),
            "platform_session_uuid": str(normalized.platform_session_uuid),
            "reason_code": normalized.reason_code,
            "recent_step_up_at": normalized.recent_step_up_at.isoformat(),
            "recent_step_up_method": normalized.recent_step_up_method,
            "safe_correlation": normalized.safe_correlation,
            "safe_note": normalized.safe_note,
            "suspension_uuid": str(normalized.suspension_uuid),
            "tenant_uuid": str(normalized.tenant_uuid),
        },
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(canonical).digest()


def _normalize_action_request(
    request: SuspensionPlatformActionRequest,
) -> _NormalizedActionRequest:
    if not isinstance(request, SuspensionPlatformActionRequest):
        raise TypeError("request must be SuspensionPlatformActionRequest")
    return _NormalizedActionRequest(
        tenant_uuid=_uuid(request.tenant_uuid, "tenant_uuid"),
        suspension_uuid=_uuid(request.suspension_uuid, "suspension_uuid"),
        action_uuid=_uuid(request.action_uuid, "action_uuid"),
        expected_recovery_run_uuid=_uuid(
            request.expected_recovery_run_uuid,
            "expected_recovery_run_uuid",
        ),
        expected_hold_uuid=_uuid(request.expected_hold_uuid, "expected_hold_uuid"),
        expected_hold_revision=_positive(
            request.expected_hold_revision,
            "expected_hold_revision",
        ),
        expected_suspension_row_version=_non_negative(
            request.expected_suspension_row_version,
            "expected_suspension_row_version",
        ),
        expected_barrier_generation=_non_negative(
            request.expected_barrier_generation,
            "expected_barrier_generation",
        ),
        expected_tenant_row_version=_positive(
            request.expected_tenant_row_version,
            "expected_tenant_row_version",
        ),
        expected_access_version=_positive(
            request.expected_access_version,
            "expected_access_version",
        ),
        expected_route_row_version=_positive(
            request.expected_route_row_version,
            "expected_route_row_version",
        ),
        expected_login_state_version=_positive(
            request.expected_login_state_version,
            "expected_login_state_version",
        ),
        platform_admin_uuid=_uuid(
            request.platform_admin_uuid,
            "platform_admin_uuid",
        ),
        platform_session_uuid=_uuid(
            request.platform_session_uuid,
            "platform_session_uuid",
        ),
        recent_step_up_method=_step_up_method(request.recent_step_up_method),
        recent_step_up_at=_input_utc(
            request.recent_step_up_at,
            "recent_step_up_at",
        ),
        reason_code=_safe_code_value(request.reason_code, "reason_code"),
        safe_note=_safe_note(request.safe_note),
        safe_correlation=_safe_correlation(request.safe_correlation),
        idempotency_key=_bounded_required(
            request.idempotency_key,
            "idempotency_key",
            160,
        ),
    )


def _normalize_barrier_command(
    command: SuspensionBarrierCommand,
) -> _NormalizedBarrierCommand:
    if not isinstance(command, SuspensionBarrierCommand):
        raise TypeError("command must be SuspensionBarrierCommand")
    return _NormalizedBarrierCommand(
        tenant_uuid=_uuid(command.tenant_uuid, "tenant_uuid"),
        suspension_uuid=_uuid(command.suspension_uuid, "suspension_uuid"),
        action_uuid=_uuid(command.action_uuid, "action_uuid"),
        expected_recovery_run_uuid=_uuid(
            command.expected_recovery_run_uuid,
            "expected_recovery_run_uuid",
        ),
        expected_hold_uuid=_uuid(command.expected_hold_uuid, "expected_hold_uuid"),
        expected_hold_revision=_positive(
            command.expected_hold_revision,
            "expected_hold_revision",
        ),
        expected_suspension_row_version=_positive(
            command.expected_suspension_row_version,
            "expected_suspension_row_version",
        ),
        expected_tenant_row_version=_positive(
            command.expected_tenant_row_version,
            "expected_tenant_row_version",
        ),
        expected_access_version=_positive(
            command.expected_access_version,
            "expected_access_version",
        ),
        expected_route_row_version=_positive(
            command.expected_route_row_version,
            "expected_route_row_version",
        ),
        expected_login_state_version=_positive(
            command.expected_login_state_version,
            "expected_login_state_version",
        ),
    )


def _result(
    transition: SuspensionTransition,
    *,
    suspension_uuid: UUID,
    tenant_row_version: int,
    suspension_row_version: int,
    route_row_version: int,
    login_state_version: int,
    replayed: bool,
) -> SuspensionPersistenceResult:
    action = transition.state.current_action
    phase = transition.state.phase
    if action is None or phase is None:
        raise SuspensionPersistenceConflictError("SUSPENSION_REDUCER_RESULT_INVALID")
    return SuspensionPersistenceResult(
        suspension_uuid=suspension_uuid,
        action_uuid=action.action_id,
        direction=action.direction,
        phase=phase,
        action_outcome=action.outcome,
        barrier_generation=transition.state.barrier_generation,
        tenant_status=transition.state.tenant_status,
        tenant_row_version=tenant_row_version,
        tenant_access_version=transition.state.tenant_access_version,
        suspension_row_version=suspension_row_version,
        route_row_version=route_row_version,
        login_state_version=login_state_version,
        candidate_dml_generation=(transition.state.candidate_dml_generation),
        effects=tuple(effect.kind for effect in transition.effects),
        replayed=replayed,
    )


def _read_database_utc_now(session: Session) -> datetime:
    if session.get_bind().dialect.name not in {"mysql", "mariadb"}:
        raise SuspensionPersistenceTransactionError(
            "SUSPENSION_DATABASE_DIALECT_UNSUPPORTED"
        )
    return _as_utc(session.scalar(sa.text("SELECT UTC_TIMESTAMP(6)")))


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise SuspensionPersistenceTransactionError("SUSPENSION_DATABASE_CLOCK_INVALID")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _input_utc(value: object, field_name: str) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            return UUID(value)
        except ValueError:
            pass
    raise ValueError(f"{field_name} must be a UUID")


def _positive(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _non_negative(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _bounded_required(value: object, field_name: str, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > maximum
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise ValueError(f"{field_name} is invalid")
    return value


def _safe_code_value(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_CODE.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


def _safe_note(value: object) -> str | None:
    if value is None:
        return None
    if (
        not isinstance(value, str)
        or len(value) > 500
        or any(unicodedata.category(character) == "Cc" for character in value)
    ):
        raise ValueError("safe_note is invalid")
    return value


def _safe_correlation(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SAFE_CORRELATION.fullmatch(value) is None:
        raise ValueError("safe_correlation is invalid")
    return value


def _step_up_method(value: object) -> str:
    if value not in {"totp", "recovery_code"}:
        raise ValueError("recent_step_up_method is invalid")
    return value


__all__ = [
    "SuspensionBarrierCommand",
    "SuspensionPersistenceAuthorityError",
    "SuspensionPersistenceBoundaryError",
    "SuspensionPersistenceConflictError",
    "SuspensionPersistenceError",
    "SuspensionPersistenceGateError",
    "SuspensionPersistenceProofError",
    "SuspensionPersistenceResult",
    "SuspensionPersistenceTransactionError",
    "SuspensionPlatformActionRequest",
    "TenantSuspensionPersistenceCoordinator",
    "suspension_action_digest",
]
