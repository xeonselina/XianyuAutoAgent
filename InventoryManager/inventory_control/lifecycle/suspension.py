"""Pure, fail-closed tenant suspension and resume transitions.

The module deliberately does not perform persistence, routing, session, job,
provider, or MySQL operations.  It returns immutable state and effect facts
that a control-database transaction/outbox adapter must persist atomically.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import UUID

from inventory_control.domain.tenant_gate import TenantStatus


class SuspensionPhase(str, Enum):
    """Authoritative D52 suspension aggregate phases."""

    FREEZING = "freezing"
    ACTIVE = "active"
    RESOLVING = "resolving"
    RESOLVED = "resolved"
    FAILED = "failed"


class SuspensionActionDirection(str, Enum):
    FREEZE = "freeze"
    RESOLVE = "resolve"


class SuspensionActionOutcome(str, Enum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class DmlLoginState(str, Enum):
    ACTIVE = "active"
    LOCKED = "locked"


class SuspensionEffectKind(str, Enum):
    """Safe technical effects; none mutate subscription or redemption facts."""

    REVOKE_ALL_SESSIONS = "revoke_all_sessions"
    DISPOSE_TENANT_ENGINES = "dispose_tenant_engines"
    BLOCK_JOB_LEASES = "block_job_leases"
    BLOCK_PROVIDER_SUBMISSIONS = "block_provider_submissions"
    SET_DESIRED_DML_LOCKED = "set_desired_dml_locked"
    LOCK_ALL_DML_IDENTITIES = "lock_all_dml_identities"
    CREATE_LOCKED_UNPUBLISHED_DML_CANDIDATE = (
        "create_locked_unpublished_dml_candidate"
    )
    LOCK_UNPUBLISHED_DML_CANDIDATE = "lock_unpublished_dml_candidate"
    PUBLISH_VALIDATED_DML_CANDIDATE = "publish_validated_dml_candidate"


class SuspensionTransitionError(ValueError):
    """Stable deterministic rejection from the pure state machine."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


@dataclass(frozen=True, slots=True)
class SuspensionAction:
    action_id: UUID
    direction: SuspensionActionDirection
    generation: int
    idempotency_key: str
    request_digest: bytes
    outcome: SuspensionActionOutcome = SuspensionActionOutcome.RUNNING
    failure_code: Optional[str] = None

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, UUID):
            raise TypeError("action_id must be a UUID")
        if not isinstance(self.direction, SuspensionActionDirection):
            raise TypeError("direction must be a SuspensionActionDirection")
        _require_positive_integer("generation", self.generation)
        _require_idempotency_key(self.idempotency_key)
        _require_request_digest(self.request_digest)
        if not isinstance(self.outcome, SuspensionActionOutcome):
            raise TypeError("outcome must be a SuspensionActionOutcome")
        if self.outcome is SuspensionActionOutcome.FAILED:
            _require_failure_code(self.failure_code)
        elif self.failure_code is not None:
            raise ValueError("failure_code is only valid for a failed action")


@dataclass(frozen=True, slots=True)
class ResumeResolution:
    """Database-time facts used by the successful final resume CAS."""

    subscription_expires_at_utc: datetime
    database_now_utc: datetime
    resulting_tenant_status: TenantStatus
    published_dml_generation: int

    def __post_init__(self) -> None:
        _require_utc_datetime(
            "subscription_expires_at_utc", self.subscription_expires_at_utc
        )
        _require_utc_datetime("database_now_utc", self.database_now_utc)
        if self.resulting_tenant_status not in {
            TenantStatus.ACTIVE,
            TenantStatus.EXPIRED,
        }:
            raise ValueError("resume result must be active or expired")
        _require_positive_integer(
            "published_dml_generation", self.published_dml_generation
        )


@dataclass(frozen=True, slots=True)
class SuspensionState:
    """Current authoritative inputs/outputs for the D52 state machine."""

    tenant_status: TenantStatus
    tenant_access_version: int
    barrier_generation: int
    phase: Optional[SuspensionPhase]
    current_action: Optional[SuspensionAction]
    desired_dml_login_state: DmlLoginState
    published_dml_generation: int
    latest_dml_generation: int
    candidate_dml_generation: Optional[int] = None
    last_resume_resolution: Optional[ResumeResolution] = None

    def __post_init__(self) -> None:
        if not isinstance(self.tenant_status, TenantStatus):
            raise TypeError("tenant_status must be a TenantStatus")
        _require_positive_integer(
            "tenant_access_version", self.tenant_access_version
        )
        _require_non_negative_integer(
            "barrier_generation", self.barrier_generation
        )
        if self.phase is not None and not isinstance(self.phase, SuspensionPhase):
            raise TypeError("phase must be a SuspensionPhase or None")
        if self.current_action is not None and not isinstance(
            self.current_action, SuspensionAction
        ):
            raise TypeError("current_action must be a SuspensionAction or None")
        if not isinstance(self.desired_dml_login_state, DmlLoginState):
            raise TypeError("desired_dml_login_state must be a DmlLoginState")
        _require_positive_integer(
            "published_dml_generation", self.published_dml_generation
        )
        _require_positive_integer(
            "latest_dml_generation", self.latest_dml_generation
        )
        if self.latest_dml_generation < self.published_dml_generation:
            raise ValueError("latest DML generation cannot precede published")
        if self.candidate_dml_generation is not None:
            _require_positive_integer(
                "candidate_dml_generation", self.candidate_dml_generation
            )
            if not (
                self.published_dml_generation < self.candidate_dml_generation
                <= self.latest_dml_generation
            ):
                raise ValueError("candidate DML generation must be unpublished")
        if self.last_resume_resolution is not None and not isinstance(
            self.last_resume_resolution, ResumeResolution
        ):
            raise TypeError(
                "last_resume_resolution must be a ResumeResolution or None"
            )
        self._validate_transition_shape()

    @classmethod
    def eligible(
        cls,
        *,
        tenant_status: TenantStatus,
        tenant_access_version: int,
        published_dml_generation: int = 1,
    ) -> SuspensionState:
        """Build an ordinary active/expired state with no open suspension."""

        if tenant_status not in {TenantStatus.ACTIVE, TenantStatus.EXPIRED}:
            raise SuspensionTransitionError("SUSPEND_STATE_INELIGIBLE")
        return cls(
            tenant_status=tenant_status,
            tenant_access_version=tenant_access_version,
            barrier_generation=0,
            phase=None,
            current_action=None,
            desired_dml_login_state=DmlLoginState.ACTIVE,
            published_dml_generation=published_dml_generation,
            latest_dml_generation=published_dml_generation,
        )

    def _validate_transition_shape(self) -> None:
        status = self.tenant_status
        action = self.current_action

        if status is TenantStatus.SUSPENDING:
            if self.phase not in {
                SuspensionPhase.FREEZING,
                SuspensionPhase.FAILED,
            }:
                raise ValueError("suspending tenant requires a freeze phase")
            _require_action_direction(action, SuspensionActionDirection.FREEZE)
            _require_locked_without_candidate(self)
        elif status is TenantStatus.SUSPENDED:
            if self.phase is not SuspensionPhase.ACTIVE:
                raise ValueError("suspended tenant requires an active barrier")
            _require_action_direction(action, SuspensionActionDirection.FREEZE)
            if action.outcome is not SuspensionActionOutcome.SUCCEEDED:
                raise ValueError("suspended tenant requires a succeeded freeze")
            _require_locked_without_candidate(self)
        elif status is TenantStatus.RESUMING:
            if self.phase is not SuspensionPhase.RESOLVING:
                raise ValueError("resuming tenant requires a resolving phase")
            _require_action_direction(action, SuspensionActionDirection.RESOLVE)
            if self.desired_dml_login_state is not DmlLoginState.LOCKED:
                raise ValueError("resuming tenant must keep desired DML locked")
            if self.candidate_dml_generation is None:
                raise ValueError("resuming tenant requires a fresh DML candidate")
        elif status in {TenantStatus.ACTIVE, TenantStatus.EXPIRED}:
            if self.phase is None:
                if action is not None or self.last_resume_resolution is not None:
                    raise ValueError("initial tenant cannot have suspension history")
            elif self.phase is SuspensionPhase.RESOLVED:
                _require_action_direction(
                    action, SuspensionActionDirection.RESOLVE
                )
                if action.outcome is not SuspensionActionOutcome.SUCCEEDED:
                    raise ValueError("resolved tenant requires a succeeded resume")
                if self.last_resume_resolution is None:
                    raise ValueError("resolved tenant requires DB-time facts")
            else:
                raise ValueError("active/expired tenant has invalid suspension phase")
            if self.desired_dml_login_state is not DmlLoginState.ACTIVE:
                raise ValueError("active/expired projection requires active DML")
            if self.candidate_dml_generation is not None:
                raise ValueError("active/expired tenant cannot retain a candidate")
        elif self.phase is not None or action is not None:
            raise ValueError("unrelated tenant state cannot own a D52 transition")

        if action is not None and action.generation != self.barrier_generation:
            raise ValueError("action and barrier generation must match")


@dataclass(frozen=True, slots=True)
class SuspensionEffectFact:
    """One immutable, non-secret technical effect bound to a transition."""

    kind: SuspensionEffectKind
    action_id: UUID
    barrier_generation: int
    tenant_access_version: int
    dml_generation: Optional[int] = None

    def __post_init__(self) -> None:
        if not isinstance(self.kind, SuspensionEffectKind):
            raise TypeError("kind must be a SuspensionEffectKind")
        if not isinstance(self.action_id, UUID):
            raise TypeError("action_id must be a UUID")
        _require_positive_integer("barrier_generation", self.barrier_generation)
        _require_positive_integer(
            "tenant_access_version", self.tenant_access_version
        )
        if self.dml_generation is not None:
            _require_positive_integer("dml_generation", self.dml_generation)


@dataclass(frozen=True, slots=True)
class FreezeBarrierEvidence:
    """Current-generation confirmations required before fully suspended."""

    action_id: UUID
    barrier_generation: int
    tenant_access_version: int
    sessions_revoked: bool
    engines_disposed: bool
    job_leases_blocked: bool
    provider_submissions_blocked: bool
    desired_dml_locked: bool
    all_dml_identities_locked: bool

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, UUID):
            raise TypeError("action_id must be a UUID")
        _require_positive_integer("barrier_generation", self.barrier_generation)
        _require_positive_integer(
            "tenant_access_version", self.tenant_access_version
        )
        for name in _FREEZE_EVIDENCE_FIELDS:
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")

    @property
    def is_complete(self) -> bool:
        return all(getattr(self, name) for name in _FREEZE_EVIDENCE_FIELDS)


@dataclass(frozen=True, slots=True)
class ResumeCandidateEvidence:
    """Proofs required before the final candidate-publish CAS."""

    action_id: UUID
    barrier_generation: int
    tenant_access_version: int
    candidate_dml_generation: int
    candidate_started_locked: bool
    candidate_unpublished: bool
    database_identity_verified: bool
    required_permissions_verified: bool
    cross_schema_access_denied: bool
    old_dml_generations_locked: bool

    def __post_init__(self) -> None:
        if not isinstance(self.action_id, UUID):
            raise TypeError("action_id must be a UUID")
        _require_positive_integer("barrier_generation", self.barrier_generation)
        _require_positive_integer(
            "tenant_access_version", self.tenant_access_version
        )
        _require_positive_integer(
            "candidate_dml_generation", self.candidate_dml_generation
        )
        for name in _RESUME_EVIDENCE_FIELDS:
            if not isinstance(getattr(self, name), bool):
                raise TypeError(f"{name} must be a boolean")

    @property
    def is_complete(self) -> bool:
        return all(getattr(self, name) for name in _RESUME_EVIDENCE_FIELDS)


@dataclass(frozen=True, slots=True)
class SuspensionTransition:
    state: SuspensionState
    effects: tuple[SuspensionEffectFact, ...] = ()
    idempotent: bool = False
    subscription_expiry_changed: bool = field(default=False, init=False)
    service_time_compensated: bool = field(default=False, init=False)
    redemption_code_consumed: bool = field(default=False, init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.state, SuspensionState):
            raise TypeError("state must be a SuspensionState")
        if not isinstance(self.effects, tuple) or not all(
            isinstance(effect, SuspensionEffectFact) for effect in self.effects
        ):
            raise TypeError("effects must be immutable SuspensionEffectFacts")
        if not isinstance(self.idempotent, bool):
            raise TypeError("idempotent must be a boolean")


_FREEZE_EVIDENCE_FIELDS = (
    "sessions_revoked",
    "engines_disposed",
    "job_leases_blocked",
    "provider_submissions_blocked",
    "desired_dml_locked",
    "all_dml_identities_locked",
)

_RESUME_EVIDENCE_FIELDS = (
    "candidate_started_locked",
    "candidate_unpublished",
    "database_identity_verified",
    "required_permissions_verified",
    "cross_schema_access_denied",
    "old_dml_generations_locked",
)


def request_suspend(
    state: SuspensionState,
    *,
    action_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
    expected_access_version: int,
    expected_barrier_generation: int,
) -> SuspensionTransition:
    """Commit the first freeze boundary and emit all required effect facts."""

    _require_state(state)
    retry = _same_action_retry(
        state,
        direction=SuspensionActionDirection.FREEZE,
        action_id=action_id,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    if retry is not None:
        return retry
    _require_expected_versions(
        state,
        expected_access_version=expected_access_version,
        expected_barrier_generation=expected_barrier_generation,
    )
    if state.tenant_status not in {TenantStatus.ACTIVE, TenantStatus.EXPIRED}:
        if state.tenant_status in {
            TenantStatus.SUSPENDING,
            TenantStatus.SUSPENDED,
            TenantStatus.RESUMING,
        }:
            raise SuspensionTransitionError("SUSPENSION_ACTION_CONFLICT")
        raise SuspensionTransitionError("SUSPEND_STATE_INELIGIBLE")
    if state.phase not in {None, SuspensionPhase.RESOLVED}:
        raise SuspensionTransitionError("SUSPENSION_STATE_INVALID")

    generation = state.barrier_generation + 1
    access_version = state.tenant_access_version + 1
    action = SuspensionAction(
        action_id=action_id,
        direction=SuspensionActionDirection.FREEZE,
        generation=generation,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    new_state = replace(
        state,
        tenant_status=TenantStatus.SUSPENDING,
        tenant_access_version=access_version,
        barrier_generation=generation,
        phase=SuspensionPhase.FREEZING,
        current_action=action,
        desired_dml_login_state=DmlLoginState.LOCKED,
        candidate_dml_generation=None,
        last_resume_resolution=None,
    )
    effects = _effect_facts(
        new_state,
        (
            SuspensionEffectKind.REVOKE_ALL_SESSIONS,
            SuspensionEffectKind.DISPOSE_TENANT_ENGINES,
            SuspensionEffectKind.BLOCK_JOB_LEASES,
            SuspensionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
            SuspensionEffectKind.SET_DESIRED_DML_LOCKED,
            SuspensionEffectKind.LOCK_ALL_DML_IDENTITIES,
        ),
    )
    return SuspensionTransition(new_state, effects)


def complete_suspend(
    state: SuspensionState,
    *,
    evidence: FreezeBarrierEvidence,
) -> SuspensionTransition:
    """Enter fully suspended only after every current barrier is confirmed."""

    _require_state(state)
    if not isinstance(evidence, FreezeBarrierEvidence):
        raise TypeError("evidence must be FreezeBarrierEvidence")
    action = _require_current_action(
        state,
        action_id=evidence.action_id,
        direction=SuspensionActionDirection.FREEZE,
    )
    if (
        state.tenant_status is TenantStatus.SUSPENDED
        and state.phase is SuspensionPhase.ACTIVE
        and action.outcome is SuspensionActionOutcome.SUCCEEDED
    ):
        return SuspensionTransition(state, idempotent=True)
    _require_evidence_versions(
        state,
        barrier_generation=evidence.barrier_generation,
        tenant_access_version=evidence.tenant_access_version,
    )
    if state.tenant_status is not TenantStatus.SUSPENDING or state.phase not in {
        SuspensionPhase.FREEZING,
        SuspensionPhase.FAILED,
    }:
        raise SuspensionTransitionError("SUSPENSION_STATE_INVALID")
    if not evidence.is_complete:
        raise SuspensionTransitionError("SUSPENSION_BARRIER_INCOMPLETE")

    new_state = replace(
        state,
        tenant_status=TenantStatus.SUSPENDED,
        phase=SuspensionPhase.ACTIVE,
        current_action=replace(
            action,
            outcome=SuspensionActionOutcome.SUCCEEDED,
            failure_code=None,
        ),
    )
    return SuspensionTransition(new_state)


def request_resume(
    state: SuspensionState,
    *,
    action_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
    expected_access_version: int,
    expected_barrier_generation: int,
) -> SuspensionTransition:
    """Start resume while retaining deny and creating a fresh DML candidate."""

    _require_state(state)
    retry = _same_action_retry(
        state,
        direction=SuspensionActionDirection.RESOLVE,
        action_id=action_id,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    if retry is not None:
        return retry
    _require_expected_versions(
        state,
        expected_access_version=expected_access_version,
        expected_barrier_generation=expected_barrier_generation,
    )
    if not (
        state.tenant_status is TenantStatus.SUSPENDED
        and state.phase is SuspensionPhase.ACTIVE
        and state.current_action is not None
        and state.current_action.outcome is SuspensionActionOutcome.SUCCEEDED
    ):
        if state.tenant_status in {
            TenantStatus.SUSPENDING,
            TenantStatus.RESUMING,
        }:
            raise SuspensionTransitionError("SUSPENSION_ACTION_CONFLICT")
        raise SuspensionTransitionError("RESUME_REQUIRES_FULLY_SUSPENDED")

    generation = state.barrier_generation + 1
    access_version = state.tenant_access_version + 1
    candidate_generation = state.latest_dml_generation + 1
    action = SuspensionAction(
        action_id=action_id,
        direction=SuspensionActionDirection.RESOLVE,
        generation=generation,
        idempotency_key=idempotency_key,
        request_digest=request_digest,
    )
    new_state = replace(
        state,
        tenant_status=TenantStatus.RESUMING,
        tenant_access_version=access_version,
        barrier_generation=generation,
        phase=SuspensionPhase.RESOLVING,
        current_action=action,
        desired_dml_login_state=DmlLoginState.LOCKED,
        latest_dml_generation=candidate_generation,
        candidate_dml_generation=candidate_generation,
        last_resume_resolution=None,
    )
    effects = _effect_facts(
        new_state,
        (
            SuspensionEffectKind.REVOKE_ALL_SESSIONS,
            SuspensionEffectKind.BLOCK_JOB_LEASES,
            SuspensionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
            SuspensionEffectKind.SET_DESIRED_DML_LOCKED,
            SuspensionEffectKind.CREATE_LOCKED_UNPUBLISHED_DML_CANDIDATE,
        ),
        candidate_dml_generation=candidate_generation,
    )
    return SuspensionTransition(new_state, effects)


def complete_resume(
    state: SuspensionState,
    *,
    evidence: ResumeCandidateEvidence,
    subscription_expires_at: datetime,
    database_now: datetime,
) -> SuspensionTransition:
    """Publish only the verified candidate and reduce from current DB time."""

    _require_state(state)
    if not isinstance(evidence, ResumeCandidateEvidence):
        raise TypeError("evidence must be ResumeCandidateEvidence")
    action = _require_current_action(
        state,
        action_id=evidence.action_id,
        direction=SuspensionActionDirection.RESOLVE,
    )
    if (
        state.phase is SuspensionPhase.RESOLVED
        and state.tenant_status in {TenantStatus.ACTIVE, TenantStatus.EXPIRED}
        and action.outcome is SuspensionActionOutcome.SUCCEEDED
    ):
        return SuspensionTransition(state, idempotent=True)
    _require_evidence_versions(
        state,
        barrier_generation=evidence.barrier_generation,
        tenant_access_version=evidence.tenant_access_version,
    )
    if (
        state.tenant_status is not TenantStatus.RESUMING
        or state.phase is not SuspensionPhase.RESOLVING
        or state.candidate_dml_generation is None
    ):
        raise SuspensionTransitionError("SUSPENSION_STATE_INVALID")
    if evidence.candidate_dml_generation != state.candidate_dml_generation:
        raise SuspensionTransitionError("STALE_DML_CANDIDATE_GENERATION")
    if not evidence.is_complete:
        raise SuspensionTransitionError(
            "RESUME_CANDIDATE_VERIFICATION_INCOMPLETE"
        )

    expires_at_utc = _normalize_aware_datetime(
        "subscription_expires_at", subscription_expires_at
    )
    database_now_utc = _normalize_aware_datetime("database_now", database_now)
    resulting_status = (
        TenantStatus.ACTIVE
        if expires_at_utc > database_now_utc
        else TenantStatus.EXPIRED
    )
    candidate_generation = state.candidate_dml_generation
    resolution = ResumeResolution(
        subscription_expires_at_utc=expires_at_utc,
        database_now_utc=database_now_utc,
        resulting_tenant_status=resulting_status,
        published_dml_generation=candidate_generation,
    )
    new_state = replace(
        state,
        tenant_status=resulting_status,
        phase=SuspensionPhase.RESOLVED,
        current_action=replace(
            action,
            outcome=SuspensionActionOutcome.SUCCEEDED,
            failure_code=None,
        ),
        desired_dml_login_state=DmlLoginState.ACTIVE,
        published_dml_generation=candidate_generation,
        candidate_dml_generation=None,
        last_resume_resolution=resolution,
    )
    effects = _effect_facts(
        new_state,
        (
            SuspensionEffectKind.REVOKE_ALL_SESSIONS,
            SuspensionEffectKind.PUBLISH_VALIDATED_DML_CANDIDATE,
        ),
        candidate_dml_generation=candidate_generation,
    )
    return SuspensionTransition(new_state, effects)


def fail_current_barrier(
    state: SuspensionState,
    *,
    action_id: UUID,
    barrier_generation: int,
    tenant_access_version: int,
    failure_code: str,
) -> SuspensionTransition:
    """Record a safe failure while preserving the current deny boundary."""

    _require_state(state)
    _require_failure_code(failure_code)
    action = _require_current_action(state, action_id=action_id)
    if action.outcome in {
        SuspensionActionOutcome.FAILED,
        SuspensionActionOutcome.SUCCEEDED,
    }:
        return SuspensionTransition(state, idempotent=True)
    _require_evidence_versions(
        state,
        barrier_generation=barrier_generation,
        tenant_access_version=tenant_access_version,
    )
    failed_action = replace(
        action,
        outcome=SuspensionActionOutcome.FAILED,
        failure_code=failure_code,
    )
    if (
        action.direction is SuspensionActionDirection.FREEZE
        and state.tenant_status is TenantStatus.SUSPENDING
        and state.phase is SuspensionPhase.FREEZING
    ):
        new_state = replace(
            state,
            phase=SuspensionPhase.FAILED,
            current_action=failed_action,
        )
    elif (
        action.direction is SuspensionActionDirection.RESOLVE
        and state.tenant_status is TenantStatus.RESUMING
        and state.phase is SuspensionPhase.RESOLVING
    ):
        new_state = replace(state, current_action=failed_action)
    else:
        raise SuspensionTransitionError("SUSPENSION_STATE_INVALID")

    kinds = [
        SuspensionEffectKind.BLOCK_JOB_LEASES,
        SuspensionEffectKind.BLOCK_PROVIDER_SUBMISSIONS,
        SuspensionEffectKind.SET_DESIRED_DML_LOCKED,
        SuspensionEffectKind.LOCK_ALL_DML_IDENTITIES,
    ]
    if new_state.candidate_dml_generation is not None:
        kinds.append(SuspensionEffectKind.LOCK_UNPUBLISHED_DML_CANDIDATE)
    effects = _effect_facts(
        new_state,
        tuple(kinds),
        candidate_dml_generation=new_state.candidate_dml_generation,
    )
    return SuspensionTransition(new_state, effects)


def _same_action_retry(
    state: SuspensionState,
    *,
    direction: SuspensionActionDirection,
    action_id: UUID,
    idempotency_key: str,
    request_digest: bytes,
) -> Optional[SuspensionTransition]:
    if not isinstance(action_id, UUID):
        raise TypeError("action_id must be a UUID")
    _require_idempotency_key(idempotency_key)
    _require_request_digest(request_digest)
    action = state.current_action
    if action is None or action.action_id != action_id:
        return None
    if (
        action.direction is not direction
        or action.idempotency_key != idempotency_key
        or action.request_digest != request_digest
    ):
        raise SuspensionTransitionError("SUSPENSION_ACTION_REPLAY_MISMATCH")
    return SuspensionTransition(state, idempotent=True)


def _require_current_action(
    state: SuspensionState,
    *,
    action_id: UUID,
    direction: Optional[SuspensionActionDirection] = None,
) -> SuspensionAction:
    if not isinstance(action_id, UUID):
        raise TypeError("action_id must be a UUID")
    action = state.current_action
    if action is None or action.action_id != action_id:
        raise SuspensionTransitionError("STALE_SUSPENSION_ACTION")
    if direction is not None and action.direction is not direction:
        raise SuspensionTransitionError("SUSPENSION_ACTION_REPLAY_MISMATCH")
    return action


def _require_expected_versions(
    state: SuspensionState,
    *,
    expected_access_version: int,
    expected_barrier_generation: int,
) -> None:
    _require_positive_integer("expected_access_version", expected_access_version)
    _require_non_negative_integer(
        "expected_barrier_generation", expected_barrier_generation
    )
    if expected_access_version != state.tenant_access_version:
        raise SuspensionTransitionError("STALE_TENANT_ACCESS_VERSION")
    if expected_barrier_generation != state.barrier_generation:
        raise SuspensionTransitionError("STALE_SUSPENSION_GENERATION")


def _require_evidence_versions(
    state: SuspensionState,
    *,
    barrier_generation: int,
    tenant_access_version: int,
) -> None:
    _require_positive_integer("barrier_generation", barrier_generation)
    _require_positive_integer("tenant_access_version", tenant_access_version)
    if barrier_generation != state.barrier_generation:
        raise SuspensionTransitionError("STALE_SUSPENSION_GENERATION")
    if tenant_access_version != state.tenant_access_version:
        raise SuspensionTransitionError("STALE_TENANT_ACCESS_VERSION")


def _effect_facts(
    state: SuspensionState,
    kinds: tuple[SuspensionEffectKind, ...],
    *,
    candidate_dml_generation: Optional[int] = None,
) -> tuple[SuspensionEffectFact, ...]:
    action = state.current_action
    if action is None:
        raise SuspensionTransitionError("SUSPENSION_STATE_INVALID")
    candidate_kinds = {
        SuspensionEffectKind.CREATE_LOCKED_UNPUBLISHED_DML_CANDIDATE,
        SuspensionEffectKind.LOCK_UNPUBLISHED_DML_CANDIDATE,
        SuspensionEffectKind.PUBLISH_VALIDATED_DML_CANDIDATE,
    }
    return tuple(
        SuspensionEffectFact(
            kind=kind,
            action_id=action.action_id,
            barrier_generation=state.barrier_generation,
            tenant_access_version=state.tenant_access_version,
            dml_generation=(
                candidate_dml_generation if kind in candidate_kinds else None
            ),
        )
        for kind in kinds
    )


def _require_state(state: SuspensionState) -> None:
    if not isinstance(state, SuspensionState):
        raise TypeError("state must be a SuspensionState")


def _require_action_direction(
    action: Optional[SuspensionAction],
    direction: SuspensionActionDirection,
) -> None:
    if action is None or action.direction is not direction:
        raise ValueError(f"state requires a {direction.value} action")


def _require_locked_without_candidate(state: SuspensionState) -> None:
    if state.desired_dml_login_state is not DmlLoginState.LOCKED:
        raise ValueError("suspension barrier must keep desired DML locked")
    if state.candidate_dml_generation is not None:
        raise ValueError("freeze barrier cannot publish or retain a DML candidate")


def _require_positive_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")


def _require_non_negative_integer(name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{name} must be a non-negative integer")


def _require_idempotency_key(value: object) -> None:
    if (
        not isinstance(value, str)
        or not value.strip()
        or len(value) > 128
    ):
        raise ValueError("idempotency_key must be non-empty and bounded")


def _require_request_digest(value: object) -> None:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError("request_digest must be a 32-byte digest")


def _require_failure_code(value: object) -> None:
    if not isinstance(value, str) or not value.strip() or len(value) > 64:
        raise ValueError("failure_code must be non-empty and bounded")


def _normalize_aware_datetime(name: str, value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise SuspensionTransitionError("SUSPENSION_TIME_MUST_BE_TIMEZONE_AWARE")
    return value.astimezone(timezone.utc)


def _require_utc_datetime(name: str, value: object) -> None:
    normalized = _normalize_aware_datetime(name, value)
    if normalized != value or value.tzinfo is not timezone.utc:
        raise ValueError(f"{name} must be normalized UTC")
