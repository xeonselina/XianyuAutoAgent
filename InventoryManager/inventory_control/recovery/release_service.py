"""Tenant-scoped D58 recovery decisions in a caller-owned transaction.

The service persists only a completed decision.  Every fallible control-plane
check happens before the DML-route adapter is invoked, and no ORM object is
mutated until a release adapter returns a receipt proving that the exact
unpublished candidate was verified and published.  If the adapter raises or
returns an inconsistent receipt, the recovery hold remains the routing
authority and therefore continues to fail closed.

The adapter owns the provisioner/MySQL advisory-lock boundary.  In particular,
an adapter MUST keep the application route denied while it works, MUST leave a
failed candidate locked or revoked, and MUST make retries idempotent by the
request digest supplied in :class:`CandidateDmlRouteCommand`.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Callable, Protocol
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.database import read_database_utc_value
from inventory_control.evidence import canonical_json_sha256
from inventory_control.models.deletion import TenantDeletionRequest
from inventory_control.models.foundation import Tenant, TenantDatabase
from inventory_control.models.platform_identity import (
    PlatformAdmin,
    PlatformAdminSession,
)
from inventory_control.models.recovery import (
    DisasterRecoveryReleaseAction,
    DisasterRecoveryRun,
    TenantRecoveryHold,
)


RECOVERY_RELEASE_CANONICALIZATION_VERSION = 1

_OPENABLE_TENANT_STATUSES = frozenset({"active", "expired"})
_REVIEWABLE_HOLD_STATES = frozenset({"held", "reviewing", "kept_closed"})
_SAFE_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")
_SAFE_REFERENCE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/#-]{0,159}\Z")
_DML_USERNAME = re.compile(r"[A-Za-z0-9_$@.-]{1,128}\Z")


class RecoveryDecision(str, Enum):
    RELEASE = "release"
    KEEP_CLOSED = "keep_closed"


class RecoveryReleaseError(RuntimeError):
    """A stable, non-secret D58 rejection."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class RecoveryReleaseTransactionError(RecoveryReleaseError):
    pass


class RecoveryReleaseConflictError(RecoveryReleaseError):
    pass


class RecoveryReleaseGateError(RecoveryReleaseError):
    pass


class RecoveryReleaseAuthenticationError(RecoveryReleaseError):
    pass


class RecoveryReleaseAdapterError(RecoveryReleaseError):
    pass


@dataclass(frozen=True, slots=True)
class RecoveryReleaseRequest:
    recovery_run_uuid: str | UUID
    expected_recovery_run_row_version: int
    tenant_uuid: str | UUID
    hold_uuid: str | UUID
    decision: RecoveryDecision
    expected_hold_revision: int
    expected_tenant_row_version: int
    expected_access_version: int
    expected_dml_login_state_version: int
    expected_published_route_version: int
    candidate_generation: int | None
    platform_admin_uuid: str | UUID
    platform_session_uuid: str | UUID
    recent_mfa_method: str
    recent_mfa_at: datetime
    reason_code: str
    evidence_type: str
    evidence_reference: str | None
    idempotency_key: str


@dataclass(frozen=True, slots=True)
class CandidateDmlRouteCommand:
    recovery_run_uuid: str
    tenant_uuid: str
    hold_uuid: str
    database_uuid: str
    candidate_generation: int
    current_dml_username: str
    current_dml_credential_generation: int
    current_dml_root_key_version: int
    current_dml_derivation_version: int
    expected_dml_login_state_version: int
    expected_published_route_version: int
    idempotency_key: str
    request_digest: bytes


@dataclass(frozen=True, slots=True)
class DmlRoutePublication:
    recovery_run_uuid: str
    tenant_uuid: str
    hold_uuid: str
    database_uuid: str
    candidate_generation: int
    published_dml_username: str
    published_dml_credential_generation: int
    published_dml_root_key_version: int
    published_dml_derivation_version: int
    previous_dml_login_state_version: int
    published_dml_login_state_version: int
    previous_route_version: int
    published_route_version: int
    request_digest: bytes
    database_identity_verified: bool
    least_privilege_verified: bool
    cross_schema_denial_verified: bool
    other_generations_locked: bool
    candidate_published: bool


class CandidateDmlRouteAdapter(Protocol):
    def verify_and_publish(
        self,
        command: CandidateDmlRouteCommand,
    ) -> DmlRoutePublication:
        ...


@dataclass(frozen=True, slots=True)
class RecoveryReleaseResult:
    action_uuid: str
    recovery_run_uuid: str
    tenant_uuid: str
    hold_uuid: str
    decision: RecoveryDecision
    safe_outcome_code: str
    request_digest: bytes
    expected_hold_revision: int
    resulting_hold_revision: int
    expected_tenant_row_version: int
    resulting_tenant_row_version: int
    expected_access_version: int
    resulting_access_version: int
    expected_dml_login_state_version: int
    resulting_dml_login_state_version: int
    expected_published_route_version: int
    resulting_published_route_version: int
    candidate_generation: int | None
    completed_at: datetime
    replayed: bool


@dataclass(frozen=True, slots=True)
class _NormalizedRequest:
    recovery_run_uuid: str
    expected_recovery_run_row_version: int
    tenant_uuid: str
    hold_uuid: str
    decision: RecoveryDecision
    expected_hold_revision: int
    expected_tenant_row_version: int
    expected_access_version: int
    expected_dml_login_state_version: int
    expected_published_route_version: int
    candidate_generation: int | None
    platform_admin_uuid: str
    platform_session_uuid: str
    recent_mfa_method: str
    recent_mfa_at: datetime
    reason_code: str
    evidence_type: str
    evidence_reference: str | None
    idempotency_key: str


DatabaseClock = Callable[[Session], datetime]


class RecoveryReleaseService:
    """Persist one ``release`` or ``keep_closed`` decision without committing."""

    def __init__(
        self,
        *,
        dml_route_adapter: CandidateDmlRouteAdapter,
        recent_mfa_window: timedelta,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        publish = getattr(dml_route_adapter, "verify_and_publish", None)
        if not callable(publish):
            raise TypeError("dml_route_adapter must provide verify_and_publish")
        if not isinstance(
            recent_mfa_window, timedelta
        ) or recent_mfa_window <= timedelta(0):
            raise ValueError("recent_mfa_window must be positive")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._adapter = dml_route_adapter
        self._recent_mfa_window = recent_mfa_window
        self._database_clock = database_clock or _read_database_utc_now

    def decide(
        self,
        session: Session,
        request: RecoveryReleaseRequest,
    ) -> RecoveryReleaseResult:
        """Flush one decision and leave commit/rollback to the caller.

        The stable lock prefix is ``tenant -> current run -> exact hold ->
        active deletion -> exact route -> existing action -> platform admin ->
        platform session``.
        Successful replays return before current revisions or the now-revoked
        platform session are revalidated.
        """

        _require_clean_caller_transaction(session)
        normalized = _normalize_request(request)
        request_digest = _request_digest(normalized)

        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == normalized.tenant_uuid)
            .with_for_update()
        )
        if tenant is None:
            raise RecoveryReleaseGateError("RECOVERY_TENANT_UNAVAILABLE")

        run = session.scalar(
            sa.select(DisasterRecoveryRun)
            .where(DisasterRecoveryRun.current_run_marker == "current")
            .with_for_update()
        )
        if run is None or run.id != normalized.recovery_run_uuid:
            raise RecoveryReleaseGateError("RECOVERY_RUN_CHANGED")

        hold = session.scalar(
            sa.select(TenantRecoveryHold)
            .where(
                TenantRecoveryHold.id == normalized.hold_uuid,
                TenantRecoveryHold.recovery_run_id == run.id,
                TenantRecoveryHold.tenant_id == tenant.id,
            )
            .with_for_update()
        )
        if hold is None:
            raise RecoveryReleaseGateError("RECOVERY_HOLD_CHANGED")

        active_deletion = session.scalar(
            sa.select(TenantDeletionRequest)
            .where(
                TenantDeletionRequest.tenant_id == tenant.id,
                TenantDeletionRequest.active_tenant_id == tenant.id,
            )
            .with_for_update()
        )
        # A pending-review request can coexist briefly with an ``active``
        # tenant projection.  It must still win over the expanding D58 release
        # path.  ``keep_closed`` remains a monotonic deny decision and does not
        # publish or unlock a route.
        if (
            active_deletion is not None
            and normalized.decision is RecoveryDecision.RELEASE
        ):
            raise RecoveryReleaseGateError("RECOVERY_DELETION_IN_PROGRESS")

        route = session.scalar(
            sa.select(TenantDatabase)
            .where(
                TenantDatabase.tenant_id == tenant.id,
                TenantDatabase.database_uuid == hold.database_uuid,
            )
            .with_for_update()
        )
        if route is None:
            raise RecoveryReleaseGateError("RECOVERY_ROUTE_UNAVAILABLE")

        existing = session.scalar(
            sa.select(DisasterRecoveryReleaseAction)
            .where(
                DisasterRecoveryReleaseAction.recovery_run_id == run.id,
                DisasterRecoveryReleaseAction.tenant_id == tenant.id,
                DisasterRecoveryReleaseAction.platform_admin_id
                == normalized.platform_admin_uuid,
                DisasterRecoveryReleaseAction.idempotency_key
                == normalized.idempotency_key,
            )
            .with_for_update()
        )
        if existing is not None:
            return _replay(existing, normalized, request_digest)

        _require_current_revisions(
            run=run,
            hold=hold,
            tenant=tenant,
            route=route,
            request=normalized,
        )
        _require_current_dml_locked(hold=hold, route=route)
        database_now = _as_database_utc(self._database_clock(session))
        admin, platform_session = _lock_and_validate_platform_session(
            session,
            request=normalized,
            database_now=database_now,
            recent_mfa_window=self._recent_mfa_window,
        )

        publication: DmlRoutePublication | None = None
        if normalized.decision is RecoveryDecision.RELEASE:
            _require_releasable(
                tenant=tenant,
                hold=hold,
                route=route,
                candidate_generation=normalized.candidate_generation,
            )
            command = CandidateDmlRouteCommand(
                recovery_run_uuid=run.id,
                tenant_uuid=tenant.id,
                hold_uuid=hold.id,
                database_uuid=hold.database_uuid,
                candidate_generation=normalized.candidate_generation,
                current_dml_username=route.dml_username,
                current_dml_credential_generation=(route.dml_credential_generation),
                current_dml_root_key_version=route.dml_root_key_version,
                current_dml_derivation_version=route.dml_derivation_version,
                expected_dml_login_state_version=(
                    normalized.expected_dml_login_state_version
                ),
                expected_published_route_version=(
                    normalized.expected_published_route_version
                ),
                idempotency_key=normalized.idempotency_key,
                request_digest=request_digest,
            )
            try:
                publication = self._adapter.verify_and_publish(command)
            except Exception:
                raise RecoveryReleaseAdapterError(
                    "RECOVERY_DML_PUBLICATION_FAILED"
                ) from None
            _require_exact_publication(command, publication)

        action_uuid = str(uuid4())
        next_hold_revision = hold.hold_revision + 1
        next_tenant_row_version = tenant.row_version + 1
        next_access_version = tenant.access_version + 1
        safe_outcome_code = (
            "RECOVERY_TENANT_RELEASED"
            if normalized.decision is RecoveryDecision.RELEASE
            else "RECOVERY_TENANT_KEPT_CLOSED"
        )

        tenant.row_version = next_tenant_row_version
        tenant.access_version = next_access_version
        tenant.updated_at = database_now
        hold.state = (
            "released"
            if normalized.decision is RecoveryDecision.RELEASE
            else "kept_closed"
        )
        hold.hold_revision = next_hold_revision
        hold.row_version += 1
        hold.review_reason_code = normalized.reason_code
        hold.review_evidence_type = normalized.evidence_type
        hold.review_evidence_reference = normalized.evidence_reference
        hold.reviewed_by_platform_admin_id = admin.id
        hold.reviewed_by_platform_session_id = platform_session.id
        hold.reviewed_at = database_now
        hold.updated_at = database_now

        if publication is not None:
            hold.released_by_action_uuid = action_uuid
            hold.released_at = database_now
            hold.expected_dml_login_state_version = (
                publication.published_dml_login_state_version
            )
            hold.dml_convergence_status = "active"
            route.dml_username = publication.published_dml_username
            route.dml_credential_generation = (
                publication.published_dml_credential_generation
            )
            route.dml_root_key_version = publication.published_dml_root_key_version
            route.dml_derivation_version = publication.published_dml_derivation_version
            route.dml_desired_login_state = "active"
            route.dml_observed_login_state = "active"
            route.dml_login_state_version = (
                publication.published_dml_login_state_version
            )
            route.dml_desired_state_recovery_run_id = run.id
            route.route_version = publication.published_route_version
            route.row_version += 1
            route.updated_at = database_now

        action = DisasterRecoveryReleaseAction(
            id=action_uuid,
            recovery_run_id=run.id,
            hold_id=hold.id,
            tenant_id=tenant.id,
            decision=normalized.decision.value,
            expected_hold_revision=normalized.expected_hold_revision,
            expected_tenant_row_version=normalized.expected_tenant_row_version,
            expected_access_version=normalized.expected_access_version,
            expected_dml_login_state_version=(
                normalized.expected_dml_login_state_version
            ),
            expected_published_route_version=(
                normalized.expected_published_route_version
            ),
            candidate_generation=normalized.candidate_generation,
            platform_admin_id=admin.id,
            platform_session_id=platform_session.id,
            recent_mfa_method=normalized.recent_mfa_method,
            recent_mfa_at=normalized.recent_mfa_at,
            reason_code=normalized.reason_code,
            evidence_type=normalized.evidence_type,
            evidence_reference=normalized.evidence_reference,
            idempotency_key=normalized.idempotency_key,
            request_digest=request_digest,
            state="succeeded",
            safe_outcome_code=safe_outcome_code,
            row_version=1,
            requested_at=database_now,
            started_at=database_now,
            completed_at=database_now,
            created_at=database_now,
            updated_at=database_now,
        )
        session.add(action)

        # A D58 decision consumes the recovered platform session.  The same
        # request can still replay because idempotency is checked first.
        platform_session.revoked_at = database_now
        platform_session.revoked_reason_code = "recovery_decision_completed"
        platform_session.revoked_by_session_id = platform_session.id
        session.flush()
        return _result(action, replayed=False)


def _normalize_request(request: object) -> _NormalizedRequest:
    if not isinstance(request, RecoveryReleaseRequest):
        raise TypeError("request must be a RecoveryReleaseRequest")
    if not isinstance(request.decision, RecoveryDecision):
        raise ValueError("decision is invalid")
    candidate_generation = request.candidate_generation
    if request.decision is RecoveryDecision.RELEASE:
        candidate_generation = _positive_integer(
            candidate_generation,
            "candidate_generation",
        )
    elif candidate_generation is not None:
        raise ValueError("keep_closed must not include candidate_generation")
    return _NormalizedRequest(
        recovery_run_uuid=str(_uuid(request.recovery_run_uuid, "recovery_run_uuid")),
        expected_recovery_run_row_version=_positive_integer(
            request.expected_recovery_run_row_version,
            "expected_recovery_run_row_version",
        ),
        tenant_uuid=str(_uuid(request.tenant_uuid, "tenant_uuid")),
        hold_uuid=str(_uuid(request.hold_uuid, "hold_uuid")),
        decision=request.decision,
        expected_hold_revision=_positive_integer(
            request.expected_hold_revision,
            "expected_hold_revision",
        ),
        expected_tenant_row_version=_positive_integer(
            request.expected_tenant_row_version,
            "expected_tenant_row_version",
        ),
        expected_access_version=_positive_integer(
            request.expected_access_version,
            "expected_access_version",
        ),
        expected_dml_login_state_version=_positive_integer(
            request.expected_dml_login_state_version,
            "expected_dml_login_state_version",
        ),
        expected_published_route_version=_positive_integer(
            request.expected_published_route_version,
            "expected_published_route_version",
        ),
        candidate_generation=candidate_generation,
        platform_admin_uuid=str(
            _uuid(request.platform_admin_uuid, "platform_admin_uuid")
        ),
        platform_session_uuid=str(
            _uuid(request.platform_session_uuid, "platform_session_uuid")
        ),
        recent_mfa_method=_mfa_method(request.recent_mfa_method),
        recent_mfa_at=_as_input_utc(request.recent_mfa_at, "recent_mfa_at"),
        reason_code=_safe_code(request.reason_code, "reason_code"),
        evidence_type=_safe_code(request.evidence_type, "evidence_type", maximum=32),
        evidence_reference=_safe_reference(request.evidence_reference),
        idempotency_key=_bounded_required(
            request.idempotency_key,
            "idempotency_key",
            128,
        ),
    )


def _require_current_revisions(
    *,
    run: DisasterRecoveryRun,
    hold: TenantRecoveryHold,
    tenant: Tenant,
    route: TenantDatabase,
    request: _NormalizedRequest,
) -> None:
    if run.status != "completed":
        raise RecoveryReleaseGateError("RECOVERY_RUN_NOT_COMPLETED")
    if run.row_version != request.expected_recovery_run_row_version:
        raise RecoveryReleaseConflictError("RECOVERY_RUN_REVISION_CHANGED")
    if hold.state not in _REVIEWABLE_HOLD_STATES:
        raise RecoveryReleaseGateError("RECOVERY_HOLD_NOT_REVIEWABLE")
    if hold.hold_revision != request.expected_hold_revision:
        raise RecoveryReleaseConflictError("RECOVERY_HOLD_REVISION_CHANGED")
    if tenant.row_version != request.expected_tenant_row_version:
        raise RecoveryReleaseConflictError("RECOVERY_TENANT_REVISION_CHANGED")
    if tenant.access_version != request.expected_access_version:
        raise RecoveryReleaseConflictError("RECOVERY_ACCESS_VERSION_CHANGED")
    if (
        hold.expected_dml_login_state_version
        != request.expected_dml_login_state_version
    ):
        raise RecoveryReleaseConflictError("RECOVERY_DML_VERSION_CHANGED")
    if route.route_version != request.expected_published_route_version:
        raise RecoveryReleaseConflictError("RECOVERY_ROUTE_VERSION_CHANGED")
    if route.dml_login_state_version != request.expected_dml_login_state_version:
        raise RecoveryReleaseConflictError("RECOVERY_DML_VERSION_CHANGED")


def _require_releasable(
    *,
    tenant: Tenant,
    hold: TenantRecoveryHold,
    route: TenantDatabase,
    candidate_generation: int,
) -> None:
    if tenant.status not in _OPENABLE_TENANT_STATUSES:
        raise RecoveryReleaseGateError("RECOVERY_UNDERLYING_GATE_CLOSED")
    if route.status != "ready":
        raise RecoveryReleaseGateError("RECOVERY_ROUTE_NOT_READY")
    if route.dml_credential_generation >= candidate_generation:
        raise RecoveryReleaseGateError("RECOVERY_DML_CANDIDATE_INVALID")


def _require_current_dml_locked(
    *,
    hold: TenantRecoveryHold,
    route: TenantDatabase,
) -> None:
    if (
        hold.dml_convergence_status != "locked"
        or route.dml_desired_login_state != "locked"
        or route.dml_observed_login_state != "locked"
        or route.dml_desired_state_recovery_run_id != hold.recovery_run_id
        or route.dml_username is None
        or route.dml_credential_generation is None
        or route.dml_root_key_version is None
        or route.dml_derivation_version is None
    ):
        raise RecoveryReleaseGateError("RECOVERY_DML_NOT_LOCKED")


def _lock_and_validate_platform_session(
    session: Session,
    *,
    request: _NormalizedRequest,
    database_now: datetime,
    recent_mfa_window: timedelta,
) -> tuple[PlatformAdmin, PlatformAdminSession]:
    admin = session.scalar(
        sa.select(PlatformAdmin)
        .where(PlatformAdmin.id == request.platform_admin_uuid)
        .with_for_update()
    )
    platform_session = session.scalar(
        sa.select(PlatformAdminSession)
        .where(PlatformAdminSession.id == request.platform_session_uuid)
        .with_for_update()
    )
    if (
        admin is None
        or platform_session is None
        or admin.status != "active"
        or admin.password_hash_encoded is None
        or admin.password_hash_algorithm is None
        or admin.password_hash_version is None
        or platform_session.platform_admin_id != admin.id
        or platform_session.auth_version_at_issue != admin.auth_version
        or platform_session.setup_version_at_issue != admin.setup_version
        or platform_session.revoked_at is not None
        or database_now >= _as_database_utc(platform_session.idle_expires_at)
        or database_now >= _as_database_utc(platform_session.absolute_expires_at)
    ):
        raise RecoveryReleaseAuthenticationError(
            "RECOVERY_PLATFORM_SESSION_UNAVAILABLE"
        )
    mfa_at = _as_database_utc(platform_session.mfa_verified_at)
    if (
        platform_session.mfa_method != request.recent_mfa_method
        or mfa_at != request.recent_mfa_at
        or mfa_at > database_now
        or database_now - mfa_at > recent_mfa_window
    ):
        raise RecoveryReleaseAuthenticationError("RECOVERY_RECENT_MFA_REQUIRED")
    return admin, platform_session


def _require_exact_publication(
    command: CandidateDmlRouteCommand,
    publication: object,
) -> None:
    if not isinstance(publication, DmlRoutePublication):
        raise RecoveryReleaseAdapterError("RECOVERY_DML_PUBLICATION_INVALID")
    digest = publication.request_digest
    exact = (
        publication.recovery_run_uuid == command.recovery_run_uuid
        and publication.tenant_uuid == command.tenant_uuid
        and publication.hold_uuid == command.hold_uuid
        and publication.database_uuid == command.database_uuid
        and type(publication.candidate_generation) is int
        and publication.candidate_generation == command.candidate_generation
        and type(publication.published_dml_credential_generation) is int
        and publication.published_dml_credential_generation
        == command.candidate_generation
        and isinstance(publication.published_dml_username, str)
        and _DML_USERNAME.fullmatch(publication.published_dml_username) is not None
        and publication.published_dml_username != command.current_dml_username
        and type(publication.published_dml_root_key_version) is int
        and publication.published_dml_root_key_version
        == command.current_dml_root_key_version
        and type(publication.published_dml_derivation_version) is int
        and publication.published_dml_derivation_version
        == command.current_dml_derivation_version
        and type(publication.previous_dml_login_state_version) is int
        and publication.previous_dml_login_state_version
        == command.expected_dml_login_state_version
        and type(publication.published_dml_login_state_version) is int
        and publication.published_dml_login_state_version
        == command.expected_dml_login_state_version + 1
        and type(publication.previous_route_version) is int
        and publication.previous_route_version
        == command.expected_published_route_version
        and type(publication.published_route_version) is int
        and publication.published_route_version
        == command.expected_published_route_version + 1
        and isinstance(digest, (bytes, bytearray, memoryview))
        and bytes(digest) == command.request_digest
        and publication.database_identity_verified is True
        and publication.least_privilege_verified is True
        and publication.cross_schema_denial_verified is True
        and publication.other_generations_locked is True
        and publication.candidate_published is True
    )
    if not exact:
        raise RecoveryReleaseAdapterError("RECOVERY_DML_PUBLICATION_INVALID")


def _replay(
    action: DisasterRecoveryReleaseAction,
    request: _NormalizedRequest,
    request_digest: bytes,
) -> RecoveryReleaseResult:
    expected = (
        action.hold_id == request.hold_uuid
        and action.platform_session_id == request.platform_session_uuid
        and action.decision == request.decision.value
        and action.expected_hold_revision == request.expected_hold_revision
        and action.expected_tenant_row_version == request.expected_tenant_row_version
        and action.expected_access_version == request.expected_access_version
        and action.expected_dml_login_state_version
        == request.expected_dml_login_state_version
        and action.expected_published_route_version
        == request.expected_published_route_version
        and action.candidate_generation == request.candidate_generation
        and action.recent_mfa_method == request.recent_mfa_method
        and _as_database_utc(action.recent_mfa_at) == request.recent_mfa_at
        and action.reason_code == request.reason_code
        and action.evidence_type == request.evidence_type
        and action.evidence_reference == request.evidence_reference
        and bytes(action.request_digest) == request_digest
    )
    if not expected:
        raise RecoveryReleaseConflictError("RECOVERY_IDEMPOTENCY_CONFLICT")
    if action.state != "succeeded" or action.completed_at is None:
        raise RecoveryReleaseConflictError("RECOVERY_ACTION_NOT_REPLAYABLE")
    return _result(action, replayed=True)


def _result(
    action: DisasterRecoveryReleaseAction,
    *,
    replayed: bool,
) -> RecoveryReleaseResult:
    decision = RecoveryDecision(action.decision)
    released = decision is RecoveryDecision.RELEASE
    if action.completed_at is None or action.safe_outcome_code is None:
        raise RecoveryReleaseConflictError("RECOVERY_ACTION_RESULT_INVALID")
    return RecoveryReleaseResult(
        action_uuid=action.id,
        recovery_run_uuid=action.recovery_run_id,
        tenant_uuid=action.tenant_id,
        hold_uuid=action.hold_id,
        decision=decision,
        safe_outcome_code=action.safe_outcome_code,
        request_digest=bytes(action.request_digest),
        expected_hold_revision=action.expected_hold_revision,
        resulting_hold_revision=action.expected_hold_revision + 1,
        expected_tenant_row_version=action.expected_tenant_row_version,
        resulting_tenant_row_version=action.expected_tenant_row_version + 1,
        expected_access_version=action.expected_access_version,
        resulting_access_version=action.expected_access_version + 1,
        expected_dml_login_state_version=(action.expected_dml_login_state_version),
        resulting_dml_login_state_version=(
            action.expected_dml_login_state_version + (1 if released else 0)
        ),
        expected_published_route_version=action.expected_published_route_version,
        resulting_published_route_version=(
            action.expected_published_route_version + (1 if released else 0)
        ),
        candidate_generation=action.candidate_generation,
        completed_at=_as_database_utc(action.completed_at),
        replayed=replayed,
    )


def _request_digest(request: _NormalizedRequest) -> bytes:
    return canonical_json_sha256(
        {
            "candidate_generation": request.candidate_generation,
            "canonicalization_version": RECOVERY_RELEASE_CANONICALIZATION_VERSION,
            "decision": request.decision.value,
            "evidence_reference": request.evidence_reference,
            "evidence_type": request.evidence_type,
            "expected_access_version": request.expected_access_version,
            "expected_dml_login_state_version": (
                request.expected_dml_login_state_version
            ),
            "expected_hold_revision": request.expected_hold_revision,
            "expected_published_route_version": (
                request.expected_published_route_version
            ),
            "expected_recovery_run_row_version": (
                request.expected_recovery_run_row_version
            ),
            "expected_tenant_row_version": request.expected_tenant_row_version,
            "hold_uuid": request.hold_uuid,
            "idempotency_key": request.idempotency_key,
            "platform_admin_uuid": request.platform_admin_uuid,
            "platform_session_uuid": request.platform_session_uuid,
            "reason_code": request.reason_code,
            "recent_mfa_at": request.recent_mfa_at.isoformat(),
            "recent_mfa_method": request.recent_mfa_method,
            "recovery_run_uuid": request.recovery_run_uuid,
            "tenant_uuid": request.tenant_uuid,
        },
        ensure_ascii=False,
        allow_nan=True,
    )


def _require_clean_caller_transaction(session: object) -> None:
    if not isinstance(session, Session) or not session.in_transaction():
        raise RecoveryReleaseTransactionError("CALLER_TRANSACTION_REQUIRED")
    dirty = any(
        session.is_modified(instance, include_collections=True)
        for instance in session.dirty
    )
    if session.new or session.deleted or dirty:
        raise RecoveryReleaseTransactionError("CLEAN_CALLER_UNIT_OF_WORK_REQUIRED")


def _read_database_utc_now(session: Session) -> datetime:
    return _as_database_utc(read_database_utc_value(session))


def _as_database_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RecoveryReleaseTransactionError("DATABASE_CLOCK_INVALID")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_input_utc(value: object, field_name: str) -> datetime:
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


def _positive_integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
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


def _safe_code(value: object, field_name: str, maximum: int = 64) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or _SAFE_CODE.fullmatch(value) is None
    ):
        raise ValueError(f"{field_name} is invalid")
    return value


def _safe_reference(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or _SAFE_REFERENCE.fullmatch(value) is None:
        raise ValueError("evidence_reference is invalid")
    return value


def _mfa_method(value: object) -> str:
    if value not in {"totp", "recovery_code"}:
        raise ValueError("recent_mfa_method is invalid")
    return value
