"""Durable control-outbox leasing with explicit authority and side-effect fences.

The service owns no transaction and performs no external I/O.  Every method
requires a caller-owned control-database transaction.  A worker must commit an
``authorize_side_effect`` transition before invoking an external adapter.
Expired or uncertain leases are quarantined and are never reclaimed.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from secrets import token_urlsafe
from typing import Any, Callable, Collection, Mapping, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.crypto import CryptoCodecV1
from inventory_control.database import read_database_utc_datetime
from inventory_control.evidence import require_sha256_digest
from inventory_control.models.jobs import ControlOutboxEvent
from inventory_control.transactions import require_caller_transaction


RESULT_DIGEST_VERSION = 1
DEFAULT_SYSTEM_CLEANUP_EVENT_TYPES = frozenset(
    {
        "provisional_cleanup",
        "registration_cleanup",
        "replacement_residual_cleanup",
        "recovery_cleanup",
        "tenant_deletion_cleanup",
    }
)

_SAFE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,63}$")
_REASON_CODE = re.compile(r"^[a-z0-9][a-z0-9_.:-]{0,63}$")
_TECHNICAL_TEXT = re.compile(r"^[\x21-\x7e]+$")
_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class OutboxError(RuntimeError):
    code = "OUTBOX_ERROR"
    public_message = "control outbox operation failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class OutboxTransactionRequiredError(OutboxError):
    code = "OUTBOX_TRANSACTION_REQUIRED"
    public_message = "an explicit caller-owned transaction is required"


class OutboxInputError(OutboxError):
    code = "OUTBOX_INPUT_INVALID"
    public_message = "control outbox input is invalid"


class OutboxLeaseFenceError(OutboxError):
    code = "OUTBOX_LEASE_STALE"
    public_message = "control outbox lease is stale"


class OutboxTransitionError(OutboxError):
    code = "OUTBOX_TRANSITION_INVALID"
    public_message = "control outbox transition is invalid"


class OutboxAuthorityRejectedError(OutboxError):
    code = "OUTBOX_AUTHORITY_REJECTED"
    public_message = "control outbox authority could not be verified"


class OutboxSystemCleanupPolicyError(OutboxError):
    code = "OUTBOX_SYSTEM_CLEANUP_POLICY"
    public_message = "system cleanup cannot use an ordinary outbox operation"


class OutboxLane(str, Enum):
    ORDINARY = "ordinary"
    SYSTEM_CLEANUP = "system_cleanup"


class OutboxAuthorityPhase(str, Enum):
    CLAIM = "claim"
    SIDE_EFFECT = "side_effect"
    HEARTBEAT = "heartbeat"
    RESULT = "result"
    SAFE_RETRY = "safe_retry"
    CANCEL = "cancel"
    RECOVERY_QUARANTINE = "recovery_quarantine"


class OutboxFailureCertainty(str, Enum):
    BEFORE_SIDE_EFFECT = "before_side_effect"
    PROVIDER_CONFIRMED_NO_EFFECT = "provider_confirmed_no_effect"


@dataclass(frozen=True, slots=True)
class OutboxAuthorityFacts:
    event_id: str
    lane: OutboxLane
    tenant_id: str | None
    tenant_access_version: int | None
    source_type: str
    source_uuid: str
    source_generation: int
    event_type: str
    execution_generation: int


@dataclass(frozen=True, slots=True)
class OutboxAuthorityVerdict:
    """Attestation returned after current authoritative rows were read.

    ``current_recovery_run_verified`` means the verifier checked the current
    deployment/recovery marker and any required tenant hold for this lane.
    The two current versions must be copied from authority, not from facts.
    """

    allowed: bool
    current_recovery_run_verified: bool
    current_source_generation: int
    current_tenant_access_version: int | None
    reason_code: str


class OutboxAuthorityVerifier(Protocol):
    def lock_current_outbox_authority(
        self,
        session: Session,
        *,
        facts: OutboxAuthorityFacts,
        phase: OutboxAuthorityPhase,
    ) -> Any:
        """Lock the current authority prefix in its canonical order."""

    def evaluate_locked_outbox_authority(
        self,
        session: Session,
        *,
        locked_authority: Any,
        facts: OutboxAuthorityFacts,
        phase: OutboxAuthorityPhase,
        now: datetime,
    ) -> OutboxAuthorityVerdict:
        """Evaluate only the authority rows locked by the first method."""


@dataclass(frozen=True, slots=True)
class OutboxLease:
    event_id: str
    lane: OutboxLane
    tenant_id: str | None
    tenant_access_version: int | None
    source_type: str
    source_uuid: str
    source_generation: int
    event_type: str
    idempotency_key: str
    attempts: int
    max_attempts: int
    execution_generation: int
    lease_expires_at: datetime
    lease_token: str = field(repr=False)
    payload: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class OutboxDispatchPermit:
    event_id: str
    lane: OutboxLane
    source_type: str
    source_uuid: str
    source_generation: int
    event_type: str
    idempotency_key: str
    execution_generation: int
    payload: Mapping[str, Any] = field(repr=False)


@dataclass(frozen=True, slots=True)
class SafeOutboxResultEvidence:
    safe_code: str
    digest_version: int
    digest_hex: str
    mac_hex: str


def verify_persisted_safe_result_mac(
    event_id: str | UUID,
    execution_generation: int,
    safe_code: str,
    digest_version: int,
    digest_hex: str,
    mac_hex: str,
    result_mac_key: bytes,
) -> bool:
    """Verify current-read safe-result fields without exposing parse errors."""

    try:
        if (
            isinstance(digest_version, bool)
            or not isinstance(digest_version, int)
            or digest_version != RESULT_DIGEST_VERSION
            or not isinstance(digest_hex, str)
            or _HEX_64.fullmatch(digest_hex) is None
            or not isinstance(mac_hex, str)
            or _HEX_64.fullmatch(mac_hex) is None
        ):
            return False
        expected = _result_mac(
            event_id=_uuid(event_id),
            execution_generation=_positive_int(execution_generation),
            safe_code=_safe_code(safe_code),
            digest=bytes.fromhex(digest_hex),
            mac_key=_mac_key(result_mac_key),
        )
        presented = bytes.fromhex(mac_hex)
    except Exception:
        return False
    return hmac.compare_digest(expected, presented)


@dataclass(frozen=True, slots=True)
class OutboxEventRef:
    event_id: str
    state: str
    attempts: int
    max_attempts: int
    execution_generation: int
    available_at: datetime
    completed_at: datetime | None
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class _OutboxEventSnapshot:
    """Non-locking projection used before the authority lock prefix."""

    facts: OutboxAuthorityFacts
    lane: OutboxLane
    state: str


@dataclass(frozen=True, slots=True)
class _LockedOutboxAuthority:
    """Authority-first event lock plus its final database timestamp."""

    event: ControlOutboxEvent
    locked_authority: Any
    authority_lock_failed: bool
    now: datetime


class ControlOutboxService:
    """Lease and finish outbox events without touching a provider."""

    def __init__(
        self,
        *,
        system_cleanup_event_types: Collection[str] = (
            DEFAULT_SYSTEM_CLEANUP_EVENT_TYPES
        ),
        database_clock: Callable[[Session], datetime] | None = None,
    ) -> None:
        normalized = frozenset(
            _technical_text(value, maximum=96) for value in system_cleanup_event_types
        )
        if not normalized:
            raise OutboxInputError()
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._system_cleanup_event_types = normalized
        self._database_clock = database_clock or read_database_utc_datetime

    def claim_ordinary_mysql_skip_locked(
        self,
        session: Session,
        *,
        worker_id: str,
        lease_duration: timedelta,
        authority: OutboxAuthorityVerifier,
        now: datetime | None = None,
    ) -> OutboxLease | None:
        return self._claim(
            session,
            lane=OutboxLane.ORDINARY,
            worker_id=worker_id,
            lease_duration=lease_duration,
            authority=authority,
            now=now,
        )

    def claim_system_cleanup_mysql_skip_locked(
        self,
        session: Session,
        *,
        worker_id: str,
        lease_duration: timedelta,
        authority: OutboxAuthorityVerifier,
        now: datetime | None = None,
    ) -> OutboxLease | None:
        return self._claim(
            session,
            lane=OutboxLane.SYSTEM_CLEANUP,
            worker_id=worker_id,
            lease_duration=lease_duration,
            authority=authority,
            now=now,
        )

    def heartbeat(
        self,
        session: Session,
        *,
        event_id: str | UUID,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        lease_duration: timedelta,
        authority: OutboxAuthorityVerifier,
        now: datetime | None = None,
    ) -> OutboxEventRef:
        self._require_transaction(session)
        duration = _duration(lease_duration)
        locked = self._lock_authority_then_event(
            session,
            event_id=_uuid(event_id),
            authority=authority,
            phase=OutboxAuthorityPhase.HEARTBEAT,
            test_now=now,
        )
        event = locked.event
        current_time = locked.now
        self._validate_fence(
            event,
            worker_id=_worker(worker_id),
            lease_token=_lease_token(lease_token),
            execution_generation=_positive_int(execution_generation),
            now=current_time,
        )
        allowed, reason = self._authority_allows(
            session,
            event,
            authority=authority,
            locked=locked,
            phase=OutboxAuthorityPhase.HEARTBEAT,
            now=current_time,
        )
        if not allowed:
            return self._quarantine_fenced(
                session, event=event, reason_code=reason, now=current_time
            )
        updated = self._fenced_finish(
            session,
            event=event,
            now=current_time,
            values={
                "lease_expires_at": current_time + duration,
                "last_heartbeat_at": current_time,
                "updated_at": current_time,
            },
        )
        return _event_ref(updated)

    def authorize_side_effect(
        self,
        session: Session,
        *,
        event_id: str | UUID,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        authority: OutboxAuthorityVerifier,
        now: datetime | None = None,
    ) -> OutboxDispatchPermit | None:
        """Persist the last authority check before an external side effect.

        The caller must commit this transaction before using the returned
        permit.  A second authorization for the same execution quarantines the
        event because the first external result may be unknown.
        """

        self._require_transaction(session)
        locked = self._lock_authority_then_event(
            session,
            event_id=_uuid(event_id),
            authority=authority,
            phase=OutboxAuthorityPhase.SIDE_EFFECT,
            test_now=now,
        )
        event = locked.event
        current_time = locked.now
        self._validate_fence(
            event,
            worker_id=_worker(worker_id),
            lease_token=_lease_token(lease_token),
            execution_generation=_positive_int(execution_generation),
            now=current_time,
        )
        if event.last_attempt_at is not None:
            self._quarantine_fenced(
                session,
                event=event,
                reason_code="duplicate_dispatch_boundary",
                now=current_time,
            )
            return None
        allowed, reason = self._authority_allows(
            session,
            event,
            authority=authority,
            locked=locked,
            phase=OutboxAuthorityPhase.SIDE_EFFECT,
            now=current_time,
        )
        if not allowed:
            self._quarantine_fenced(
                session, event=event, reason_code=reason, now=current_time
            )
            return None
        updated = self._fenced_finish(
            session,
            event=event,
            now=current_time,
            extra_predicates=(ControlOutboxEvent.last_attempt_at.is_(None),),
            values={
                "last_attempt_at": current_time,
                "last_heartbeat_at": current_time,
                "updated_at": current_time,
            },
        )
        return _permit(updated, lane=self._lane(updated))

    def complete_success(
        self,
        session: Session,
        *,
        event_id: str | UUID,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        evidence: SafeOutboxResultEvidence,
        result_mac_key: bytes,
        authority: OutboxAuthorityVerifier,
        now: datetime | None = None,
    ) -> OutboxEventRef:
        """Persist only authenticated, versioned safe result evidence."""

        self._require_transaction(session)
        event_identity = _uuid(event_id)
        generation = _positive_int(execution_generation)
        event = session.scalar(
            sa.select(ControlOutboxEvent)
            .where(ControlOutboxEvent.id == event_identity)
            .execution_options(populate_existing=True)
        )
        if event is None:
            raise OutboxLeaseFenceError()
        self._verify_result_evidence(
            event,
            evidence=evidence,
            result_mac_key=result_mac_key,
            execution_generation=generation,
        )
        if event.state == "succeeded":
            if (
                event.execution_generation == generation
                and event.result_digest_version == evidence.digest_version
                and event.result_digest == evidence.digest_hex
                and event.result_mac == evidence.mac_hex
            ):
                return _event_ref(event, replay=True)
            raise OutboxTransitionError()
        locked = self._lock_authority_then_event(
            session,
            event_id=event_identity,
            authority=authority,
            phase=OutboxAuthorityPhase.RESULT,
            test_now=now,
        )
        event = locked.event
        current_time = locked.now
        self._validate_fence(
            event,
            worker_id=_worker(worker_id),
            lease_token=_lease_token(lease_token),
            execution_generation=generation,
            now=current_time,
        )
        if event.last_attempt_at is None:
            raise OutboxTransitionError()
        allowed, reason = self._authority_allows(
            session,
            event,
            authority=authority,
            locked=locked,
            phase=OutboxAuthorityPhase.RESULT,
            now=current_time,
        )
        values: dict[str, Any] = {
            "result_digest_version": evidence.digest_version,
            "result_digest": evidence.digest_hex,
            "result_mac": evidence.mac_hex,
            "lease_owner": None,
            "lease_token": None,
            "lease_expires_at": None,
            "completed_at": current_time,
            "updated_at": current_time,
        }
        if allowed:
            values.update(state="succeeded", last_error_code=None)
        else:
            values.update(state="recovery_quarantined", last_error_code=reason)
        updated = self._fenced_finish(
            session, event=event, now=current_time, values=values
        )
        return _event_ref(updated)

    def record_safe_failure(
        self,
        session: Session,
        *,
        event_id: str | UUID,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        certainty: OutboxFailureCertainty,
        error_code: str,
        authority: OutboxAuthorityVerifier,
        retry_at: datetime | None = None,
        now: datetime | None = None,
    ) -> OutboxEventRef:
        """Retry only when absence of an external effect is proven."""

        self._require_transaction(session)
        try:
            selected_certainty = OutboxFailureCertainty(certainty)
        except (TypeError, ValueError):
            raise OutboxInputError() from None
        locked = self._lock_authority_then_event(
            session,
            event_id=_uuid(event_id),
            authority=authority,
            phase=OutboxAuthorityPhase.SAFE_RETRY,
            test_now=now,
        )
        event = locked.event
        current_time = locked.now
        retry_time = _time(retry_at) if retry_at is not None else current_time
        self._validate_fence(
            event,
            worker_id=_worker(worker_id),
            lease_token=_lease_token(lease_token),
            execution_generation=_positive_int(execution_generation),
            now=current_time,
        )
        if (
            selected_certainty is OutboxFailureCertainty.BEFORE_SIDE_EFFECT
            and event.last_attempt_at is not None
        ) or (
            selected_certainty is OutboxFailureCertainty.PROVIDER_CONFIRMED_NO_EFFECT
            and event.last_attempt_at is None
        ):
            raise OutboxTransitionError()
        allowed, reason = self._authority_allows(
            session,
            event,
            authority=authority,
            locked=locked,
            phase=OutboxAuthorityPhase.SAFE_RETRY,
            now=current_time,
        )
        if not allowed:
            return self._quarantine_fenced(
                session, event=event, reason_code=reason, now=current_time
            )
        lane = self._lane(event)
        can_retry = (
            event.attempts < event.max_attempts
            and retry_time >= current_time
            and (event.not_after is None or _as_utc(event.not_after) >= retry_time)
        )
        state = (
            "pending"
            if can_retry
            else (
                "recovery_quarantined"
                if lane is OutboxLane.SYSTEM_CLEANUP
                else "cancelled"
            )
        )
        updated = self._fenced_finish(
            session,
            event=event,
            now=current_time,
            values={
                "state": state,
                "available_at": retry_time if can_retry else event.available_at,
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "last_error_code": _reason(error_code),
                "result_digest_version": None,
                "result_digest": None,
                "result_mac": None,
                "completed_at": None if can_retry else current_time,
                "updated_at": current_time,
            },
        )
        return _event_ref(updated)

    def record_unknown_outcome(
        self,
        session: Session,
        *,
        event_id: str | UUID,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        reason_code: str = "external_outcome_unknown",
        now: datetime | None = None,
    ) -> OutboxEventRef:
        """Quarantine an uncertain side effect; it is never made pending."""

        self._require_transaction(session)
        event, current_time = self._lock_fenced_event(
            session,
            event_id=_uuid(event_id),
            worker_id=_worker(worker_id),
            lease_token=_lease_token(lease_token),
            execution_generation=_positive_int(execution_generation),
            test_now=now,
        )
        return self._quarantine_fenced(
            session,
            event=event,
            reason_code=_reason(reason_code),
            now=current_time,
        )

    def cancel_pending_ordinary(
        self,
        session: Session,
        *,
        event_id: str | UUID,
        expected_source_generation: int,
        expected_execution_generation: int,
        authority: OutboxAuthorityVerifier,
        reason_code: str,
        now: datetime | None = None,
    ) -> OutboxEventRef:
        """Cancel ordinary work only before it receives a lease."""

        self._require_transaction(session)
        locked = self._lock_authority_then_event(
            session,
            event_id=_uuid(event_id),
            authority=authority,
            phase=OutboxAuthorityPhase.CANCEL,
            test_now=now,
        )
        event = locked.event
        current_time = locked.now
        if self._lane(event) is OutboxLane.SYSTEM_CLEANUP:
            raise OutboxSystemCleanupPolicyError()
        if (
            event.state != "pending"
            or event.source_generation != _positive_int(expected_source_generation)
            or event.execution_generation
            != _nonnegative_int(expected_execution_generation)
        ):
            raise OutboxTransitionError()
        allowed, authority_reason = self._authority_allows(
            session,
            event,
            authority=authority,
            locked=locked,
            phase=OutboxAuthorityPhase.CANCEL,
            now=current_time,
        )
        if not allowed:
            return self._quarantine_unfenced(
                session,
                event=event,
                reason_code=authority_reason,
                now=current_time,
            )
        event.state = "cancelled"
        event.last_error_code = _reason(reason_code)
        event.completed_at = current_time
        event.updated_at = current_time
        session.flush()
        return _event_ref(event)

    def cancel_leased_ordinary_before_side_effect(
        self,
        session: Session,
        *,
        event_id: str | UUID,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        authority: OutboxAuthorityVerifier,
        reason_code: str,
        now: datetime | None = None,
    ) -> OutboxEventRef:
        self._require_transaction(session)
        locked = self._lock_authority_then_event(
            session,
            event_id=_uuid(event_id),
            authority=authority,
            phase=OutboxAuthorityPhase.CANCEL,
            test_now=now,
        )
        event = locked.event
        current_time = locked.now
        self._validate_fence(
            event,
            worker_id=_worker(worker_id),
            lease_token=_lease_token(lease_token),
            execution_generation=_positive_int(execution_generation),
            now=current_time,
        )
        if self._lane(event) is OutboxLane.SYSTEM_CLEANUP:
            raise OutboxSystemCleanupPolicyError()
        if event.last_attempt_at is not None:
            return self._quarantine_fenced(
                session,
                event=event,
                reason_code="cancel_after_dispatch_unknown",
                now=current_time,
            )
        allowed, authority_reason = self._authority_allows(
            session,
            event,
            authority=authority,
            locked=locked,
            phase=OutboxAuthorityPhase.CANCEL,
            now=current_time,
        )
        if not allowed:
            return self._quarantine_fenced(
                session,
                event=event,
                reason_code=authority_reason,
                now=current_time,
            )
        updated = self._fenced_finish(
            session,
            event=event,
            now=current_time,
            values={
                "state": "cancelled",
                "last_error_code": _reason(reason_code),
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "completed_at": current_time,
                "updated_at": current_time,
            },
        )
        return _event_ref(updated)

    def quarantine_for_recovery(
        self,
        session: Session,
        *,
        event_id: str | UUID,
        expected_source_generation: int,
        expected_execution_generation: int,
        authority: OutboxAuthorityVerifier,
        reason_code: str,
        now: datetime | None = None,
    ) -> OutboxEventRef:
        """Invalidate an old pending/leased generation during recovery."""

        self._require_transaction(session)
        event_identity = _uuid(event_id)
        snapshot_event = session.scalar(
            sa.select(ControlOutboxEvent)
            .where(ControlOutboxEvent.id == event_identity)
            .execution_options(populate_existing=True)
        )
        if snapshot_event is None:
            raise OutboxTransitionError()
        if snapshot_event.state == "recovery_quarantined":
            return _event_ref(snapshot_event, replay=True)
        locked = self._lock_authority_then_event(
            session,
            event_id=event_identity,
            authority=authority,
            phase=OutboxAuthorityPhase.RECOVERY_QUARANTINE,
            test_now=now,
        )
        event = locked.event
        current_time = locked.now
        if (
            event.state not in ("pending", "leased")
            or event.source_generation != _positive_int(expected_source_generation)
            or event.execution_generation
            != _nonnegative_int(expected_execution_generation)
        ):
            raise OutboxTransitionError()
        allowed, _ = self._authority_allows(
            session,
            event,
            authority=authority,
            locked=locked,
            phase=OutboxAuthorityPhase.RECOVERY_QUARANTINE,
            now=current_time,
            allow_superseded_versions=True,
        )
        if not allowed:
            raise OutboxAuthorityRejectedError()
        event.state = "recovery_quarantined"
        event.execution_generation += 1
        event.lease_owner = None
        event.lease_token = None
        event.lease_expires_at = None
        event.last_error_code = _reason(reason_code)
        event.completed_at = current_time
        event.updated_at = current_time
        session.flush()
        return _event_ref(event)

    def make_safe_result_evidence(
        self,
        permit: OutboxDispatchPermit,
        *,
        safe_code: str,
        safe_facts_digest: bytes,
        result_mac_key: bytes,
    ) -> SafeOutboxResultEvidence:
        """Bind a pre-hashed allowlisted result; raw results are not accepted."""

        if not isinstance(permit, OutboxDispatchPermit):
            raise OutboxInputError()
        result_code = _safe_code(safe_code)
        facts_digest = require_sha256_digest(safe_facts_digest, OutboxInputError)
        mac_key = _mac_key(result_mac_key)
        digest = hashlib.sha256(
            CryptoCodecV1.encode_parts(
                CryptoCodecV1.domain("inventory-manager/control-outbox-safe-result/v1"),
                CryptoCodecV1.uuid_bytes(permit.event_id),
                CryptoCodecV1.ascii_text(permit.source_type),
                CryptoCodecV1.uuid_bytes(permit.source_uuid),
                CryptoCodecV1.uint64(permit.source_generation),
                CryptoCodecV1.ascii_text(permit.event_type),
                CryptoCodecV1.uint64(permit.execution_generation),
                CryptoCodecV1.ascii_text(result_code),
                facts_digest,
            )
        ).digest()
        mac = _result_mac(
            event_id=permit.event_id,
            execution_generation=permit.execution_generation,
            safe_code=result_code,
            digest=digest,
            mac_key=mac_key,
        )
        return SafeOutboxResultEvidence(
            safe_code=result_code,
            digest_version=RESULT_DIGEST_VERSION,
            digest_hex=digest.hex(),
            mac_hex=mac.hex(),
        )

    def _claim(
        self,
        session: Session,
        *,
        lane: OutboxLane,
        worker_id: str,
        lease_duration: timedelta,
        authority: OutboxAuthorityVerifier,
        now: datetime | None,
    ) -> OutboxLease | None:
        self._require_transaction(session)
        if session.bind is None or session.bind.dialect.name not in {
            "mysql",
            "mariadb",
        }:
            raise OutboxInputError()
        self._require_authority(authority)
        duration = _duration(lease_duration)
        worker = _worker(worker_id)
        discovery_time = self._database_now(session, test_now=now)
        statement = self._claim_candidate_statement(
            lane=lane,
            now=discovery_time,
        )
        projected = session.scalar(statement)
        if projected is None:
            return None
        snapshot = self._snapshot(projected)
        locked = self._lock_projected_event(
            session,
            snapshot=snapshot,
            authority=authority,
            phase=OutboxAuthorityPhase.CLAIM,
            test_now=now,
            skip_locked=True,
        )
        if locked is None:
            return None
        event = locked.event
        current_time = locked.now
        action = self._claim_action(event, now=current_time)
        if action is None:
            return None
        if action != "claim":
            self._terminalize_locked_candidate(
                event,
                lane=lane,
                action=action,
                now=current_time,
            )
            session.flush()
            return None
        allowed, reason = self._authority_allows(
            session,
            event,
            authority=authority,
            locked=locked,
            phase=OutboxAuthorityPhase.CLAIM,
            now=current_time,
        )
        if not allowed:
            self._quarantine_unfenced(
                session, event=event, reason_code=reason, now=current_time
            )
            return None
        event.state = "leased"
        event.attempts += 1
        event.execution_generation += 1
        event.lease_owner = worker
        event.lease_token = token_urlsafe(32)
        event.lease_expires_at = current_time + duration
        event.last_heartbeat_at = current_time
        event.last_attempt_at = None
        event.completed_at = None
        event.updated_at = current_time
        session.flush()
        return _lease(event, lane=lane)

    def _claim_candidate_statement(
        self,
        *,
        lane: OutboxLane,
        now: datetime,
        skip_locked: bool | None = None,
    ) -> Any:
        """Project one candidate identity without taking an event-row lock."""

        # Kept as a compatibility keyword for dialect-level callers.  The
        # candidate projection must remain non-locking regardless of dialect.
        del skip_locked
        lane_predicate = self._lane_predicate(lane)
        return (
            sa.select(ControlOutboxEvent)
            .where(
                sa.or_(
                    sa.and_(
                        ControlOutboxEvent.state == "pending",
                        sa.or_(
                            ControlOutboxEvent.available_at <= now,
                            ControlOutboxEvent.not_after < now,
                            ControlOutboxEvent.attempts
                            >= ControlOutboxEvent.max_attempts,
                        ),
                    ),
                    sa.and_(
                        ControlOutboxEvent.state == "leased",
                        ControlOutboxEvent.lease_expires_at <= now,
                    ),
                ),
                lane_predicate,
            )
            .order_by(
                ControlOutboxEvent.available_at.asc(),
                ControlOutboxEvent.created_at.asc(),
                ControlOutboxEvent.id.asc(),
            )
            .limit(1)
            .execution_options(populate_existing=True)
        )

    @staticmethod
    def _event_lock_statement(*, event_id: str, skip_locked: bool) -> Any:
        return (
            sa.select(ControlOutboxEvent)
            .where(ControlOutboxEvent.id == event_id)
            .with_for_update(skip_locked=skip_locked)
            .execution_options(populate_existing=True)
        )

    @staticmethod
    def _claim_action(event: ControlOutboxEvent, *, now: datetime) -> str | None:
        current_time = _as_utc(now)
        if (
            event.state == "leased"
            and event.lease_expires_at is not None
            and _as_utc(event.lease_expires_at) <= current_time
        ):
            return "lease_expired"
        if event.state != "pending":
            return None
        if event.not_after is not None and _as_utc(event.not_after) < current_time:
            return "deadline_expired"
        if event.attempts >= event.max_attempts:
            return "attempts_exhausted"
        if _as_utc(event.available_at) <= current_time:
            return "claim"
        return None

    @staticmethod
    def _terminalize_locked_candidate(
        event: ControlOutboxEvent,
        *,
        lane: OutboxLane,
        action: str,
        now: datetime,
    ) -> None:
        if action == "lease_expired":
            event.state = "recovery_quarantined"
            event.last_error_code = "lease_expired_outcome_unknown"
        elif action == "deadline_expired":
            event.state = (
                "recovery_quarantined"
                if lane is OutboxLane.SYSTEM_CLEANUP
                else "cancelled"
            )
            event.last_error_code = (
                "system_cleanup_deadline_expired"
                if lane is OutboxLane.SYSTEM_CLEANUP
                else "deadline_expired"
            )
        elif action == "attempts_exhausted":
            event.state = (
                "recovery_quarantined"
                if lane is OutboxLane.SYSTEM_CLEANUP
                else "cancelled"
            )
            event.last_error_code = (
                "system_cleanup_attempts_exhausted"
                if lane is OutboxLane.SYSTEM_CLEANUP
                else "attempts_exhausted"
            )
        else:
            raise OutboxTransitionError()
        event.lease_owner = None
        event.lease_token = None
        event.lease_expires_at = None
        event.completed_at = now
        event.updated_at = now

    def _authority_allows(
        self,
        session: Session,
        event: ControlOutboxEvent,
        *,
        authority: OutboxAuthorityVerifier,
        locked: _LockedOutboxAuthority,
        phase: OutboxAuthorityPhase,
        now: datetime,
        allow_superseded_versions: bool = False,
    ) -> tuple[bool, str]:
        if locked.authority_lock_failed:
            return False, "authority_verification_failed"
        facts = _authority_facts(event, lane=self._lane(event))
        try:
            verdict = authority.evaluate_locked_outbox_authority(
                session,
                locked_authority=locked.locked_authority,
                facts=facts,
                phase=phase,
                now=now,
            )
        except Exception:
            return False, "authority_verification_failed"
        if not isinstance(verdict, OutboxAuthorityVerdict):
            return False, "authority_verification_failed"
        try:
            reason = _reason(verdict.reason_code)
        except OutboxInputError:
            return False, "authority_verification_failed"
        if (
            not verdict.allowed
            or not verdict.current_recovery_run_verified
            or isinstance(verdict.current_source_generation, bool)
            or not isinstance(verdict.current_source_generation, int)
            or verdict.current_source_generation < 1
        ):
            return False, reason
        if allow_superseded_versions:
            source_matches = (
                verdict.current_source_generation >= event.source_generation
            )
        else:
            source_matches = (
                verdict.current_source_generation == event.source_generation
            )
        if event.tenant_id is None:
            tenant_matches = verdict.current_tenant_access_version is None
        elif (
            isinstance(verdict.current_tenant_access_version, bool)
            or not isinstance(verdict.current_tenant_access_version, int)
            or event.tenant_access_version is None
        ):
            tenant_matches = False
        elif allow_superseded_versions:
            tenant_matches = (
                verdict.current_tenant_access_version >= event.tenant_access_version
            )
        else:
            tenant_matches = (
                verdict.current_tenant_access_version == event.tenant_access_version
            )
        if not source_matches or not tenant_matches:
            return False, "authority_version_mismatch"
        return True, reason

    def _verify_result_evidence(
        self,
        event: ControlOutboxEvent,
        *,
        evidence: SafeOutboxResultEvidence,
        result_mac_key: bytes,
        execution_generation: int,
    ) -> None:
        if (
            not isinstance(evidence, SafeOutboxResultEvidence)
            or evidence.digest_version != RESULT_DIGEST_VERSION
            or _HEX_64.fullmatch(evidence.digest_hex) is None
            or _HEX_64.fullmatch(evidence.mac_hex) is None
        ):
            raise OutboxInputError()
        safe_code = _safe_code(evidence.safe_code)
        key = _mac_key(result_mac_key)
        digest = bytes.fromhex(evidence.digest_hex)
        expected = _result_mac(
            event_id=event.id,
            execution_generation=execution_generation,
            safe_code=safe_code,
            digest=digest,
            mac_key=key,
        )
        if not hmac.compare_digest(expected.hex(), evidence.mac_hex):
            raise OutboxInputError()

    def _lane_predicate(self, lane: OutboxLane) -> Any:
        system = ControlOutboxEvent.event_type.in_(
            tuple(sorted(self._system_cleanup_event_types))
        )
        return system if lane is OutboxLane.SYSTEM_CLEANUP else sa.not_(system)

    def _lane(self, event: ControlOutboxEvent) -> OutboxLane:
        return (
            OutboxLane.SYSTEM_CLEANUP
            if event.event_type in self._system_cleanup_event_types
            else OutboxLane.ORDINARY
        )

    def _snapshot(self, event: ControlOutboxEvent) -> _OutboxEventSnapshot:
        lane = self._lane(event)
        return _OutboxEventSnapshot(
            facts=_authority_facts(event, lane=lane),
            lane=lane,
            state=event.state,
        )

    def _lock_authority_then_event(
        self,
        session: Session,
        *,
        event_id: str,
        authority: OutboxAuthorityVerifier,
        phase: OutboxAuthorityPhase,
        test_now: datetime | None,
    ) -> _LockedOutboxAuthority:
        self._require_authority(authority)
        projected = session.scalar(
            sa.select(ControlOutboxEvent)
            .where(ControlOutboxEvent.id == event_id)
            .execution_options(populate_existing=True)
        )
        if projected is None:
            raise OutboxLeaseFenceError()
        locked = self._lock_projected_event(
            session,
            snapshot=self._snapshot(projected),
            authority=authority,
            phase=phase,
            test_now=test_now,
            skip_locked=False,
        )
        if locked is None:  # pragma: no cover - non-SKIP-LOCKED invariant
            raise OutboxLeaseFenceError()
        return locked

    def _lock_projected_event(
        self,
        session: Session,
        *,
        snapshot: _OutboxEventSnapshot,
        authority: OutboxAuthorityVerifier,
        phase: OutboxAuthorityPhase,
        test_now: datetime | None,
        skip_locked: bool,
    ) -> _LockedOutboxAuthority | None:
        """Lock authority first, then the unchanged event, then read DB time."""

        self._require_authority(authority)
        try:
            locked_authority = authority.lock_current_outbox_authority(
                session,
                facts=snapshot.facts,
                phase=phase,
            )
            authority_lock_failed = False
        except Exception:
            # No further authority method is called after a failed lock.  The
            # exact event can still be quarantined without creating an
            # event-to-authority lock edge.
            locked_authority = None
            authority_lock_failed = True

        event = session.scalar(
            self._event_lock_statement(
                event_id=snapshot.facts.event_id,
                skip_locked=skip_locked,
            )
        )
        if event is None:
            return None
        current_time = self._database_now(session, test_now=test_now)
        if self._snapshot(event) != snapshot:
            # Authority was locked for the projected identity.  Never acquire
            # a different authority prefix while holding this event row.
            raise OutboxLeaseFenceError()
        return _LockedOutboxAuthority(
            event=event,
            locked_authority=locked_authority,
            authority_lock_failed=authority_lock_failed,
            now=current_time,
        )

    def _lock_fenced_event(
        self,
        session: Session,
        *,
        event_id: str,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        test_now: datetime | None,
    ) -> tuple[ControlOutboxEvent, datetime]:
        event = session.scalar(
            sa.select(ControlOutboxEvent)
            .where(ControlOutboxEvent.id == event_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if event is None:
            raise OutboxLeaseFenceError()
        current_time = self._database_now(session, test_now=test_now)
        self._validate_fence(
            event,
            worker_id=worker_id,
            lease_token=lease_token,
            execution_generation=execution_generation,
            now=current_time,
        )
        return event, current_time

    @staticmethod
    def _validate_fence(
        event: ControlOutboxEvent,
        *,
        worker_id: str,
        lease_token: str,
        execution_generation: int,
        now: datetime,
    ) -> None:
        if event.state != "leased":
            raise OutboxTransitionError()
        if (
            event.lease_owner != worker_id
            or event.lease_token != lease_token
            or event.execution_generation != execution_generation
            or event.lease_expires_at is None
            or _as_utc(event.lease_expires_at) <= now
        ):
            raise OutboxLeaseFenceError()

    @staticmethod
    def _require_authority(authority: OutboxAuthorityVerifier) -> None:
        if not callable(getattr(authority, "lock_current_outbox_authority", None)):
            raise TypeError("authority must lock current outbox authority")
        if not callable(getattr(authority, "evaluate_locked_outbox_authority", None)):
            raise TypeError("authority must evaluate locked outbox authority")

    def _database_now(
        self,
        session: Session,
        *,
        test_now: datetime | None,
    ) -> datetime:
        # Caller-provided time is never authoritative for SQL-backed work.
        return _as_utc(self._database_clock(session))

    def _fenced_finish(
        self,
        session: Session,
        *,
        event: ControlOutboxEvent,
        now: datetime,
        values: Mapping[str, Any],
        extra_predicates: tuple[Any, ...] = (),
    ) -> ControlOutboxEvent:
        changed = session.execute(
            sa.update(ControlOutboxEvent)
            .where(
                ControlOutboxEvent.id == event.id,
                ControlOutboxEvent.state == "leased",
                ControlOutboxEvent.lease_owner == event.lease_owner,
                ControlOutboxEvent.lease_token == event.lease_token,
                ControlOutboxEvent.execution_generation == event.execution_generation,
                ControlOutboxEvent.lease_expires_at > now,
                *extra_predicates,
            )
            .values(**dict(values))
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise OutboxLeaseFenceError()
        refreshed = session.execute(
            sa.select(ControlOutboxEvent)
            .where(ControlOutboxEvent.id == event.id)
            .execution_options(populate_existing=True)
        ).scalar_one()
        return refreshed

    def _quarantine_fenced(
        self,
        session: Session,
        *,
        event: ControlOutboxEvent,
        reason_code: str,
        now: datetime,
    ) -> OutboxEventRef:
        result = self._fenced_finish(
            session,
            event=event,
            now=now,
            values={
                "state": "recovery_quarantined",
                "lease_owner": None,
                "lease_token": None,
                "lease_expires_at": None,
                "last_error_code": _reason(reason_code),
                "completed_at": now,
                "updated_at": now,
            },
        )
        return _event_ref(result)

    def _quarantine_unfenced(
        self,
        session: Session,
        *,
        event: ControlOutboxEvent,
        reason_code: str,
        now: datetime,
    ) -> OutboxEventRef:
        event.state = "recovery_quarantined"
        event.lease_owner = None
        event.lease_token = None
        event.lease_expires_at = None
        event.last_error_code = _reason(reason_code)
        event.completed_at = now
        event.updated_at = now
        session.flush()
        return _event_ref(event)

    @staticmethod
    def _require_transaction(session: Session) -> None:
        require_caller_transaction(
            session,
            OutboxTransactionRequiredError,
            invalid_session_error=OutboxInputError,
        )


def _authority_facts(
    event: ControlOutboxEvent,
    *,
    lane: OutboxLane,
) -> OutboxAuthorityFacts:
    return OutboxAuthorityFacts(
        event_id=event.id,
        lane=lane,
        tenant_id=event.tenant_id,
        tenant_access_version=event.tenant_access_version,
        source_type=event.source_type,
        source_uuid=event.source_uuid,
        source_generation=event.source_generation,
        event_type=event.event_type,
        execution_generation=event.execution_generation,
    )


def _lease(event: ControlOutboxEvent, *, lane: OutboxLane) -> OutboxLease:
    if event.lease_token is None or event.lease_expires_at is None:
        raise OutboxTransitionError()
    return OutboxLease(
        event_id=event.id,
        lane=lane,
        tenant_id=event.tenant_id,
        tenant_access_version=event.tenant_access_version,
        source_type=event.source_type,
        source_uuid=event.source_uuid,
        source_generation=event.source_generation,
        event_type=event.event_type,
        idempotency_key=event.idempotency_key,
        attempts=event.attempts,
        max_attempts=event.max_attempts,
        execution_generation=event.execution_generation,
        lease_expires_at=event.lease_expires_at,
        lease_token=event.lease_token,
        payload=dict(event.payload),
    )


def _permit(
    event: ControlOutboxEvent,
    *,
    lane: OutboxLane,
) -> OutboxDispatchPermit:
    return OutboxDispatchPermit(
        event_id=event.id,
        lane=lane,
        source_type=event.source_type,
        source_uuid=event.source_uuid,
        source_generation=event.source_generation,
        event_type=event.event_type,
        idempotency_key=event.idempotency_key,
        execution_generation=event.execution_generation,
        payload=dict(event.payload),
    )


def _event_ref(
    event: ControlOutboxEvent,
    *,
    replay: bool = False,
) -> OutboxEventRef:
    return OutboxEventRef(
        event_id=event.id,
        state=event.state,
        attempts=event.attempts,
        max_attempts=event.max_attempts,
        execution_generation=event.execution_generation,
        available_at=event.available_at,
        completed_at=event.completed_at,
        idempotent_replay=replay,
    )


def _result_mac(
    *,
    event_id: str,
    execution_generation: int,
    safe_code: str,
    digest: bytes,
    mac_key: bytes,
) -> bytes:
    message = CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain("inventory-manager/control-outbox-result-mac/v1"),
        CryptoCodecV1.uuid_bytes(event_id),
        CryptoCodecV1.uint64(execution_generation),
        CryptoCodecV1.ascii_text(safe_code),
        digest,
    )
    return hmac.new(mac_key, message, hashlib.sha256).digest()


def _uuid(value: str | UUID) -> str:
    try:
        parsed = value if isinstance(value, UUID) else UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise OutboxInputError() from None
    return str(parsed)


def _technical_text(value: str, *, maximum: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > maximum
        or _TECHNICAL_TEXT.fullmatch(value) is None
    ):
        raise OutboxInputError()
    return value


def _worker(value: str) -> str:
    return _technical_text(value, maximum=128)


def _lease_token(value: str) -> str:
    return _technical_text(value, maximum=128)


def _safe_code(value: str) -> str:
    if not isinstance(value, str) or _SAFE_CODE.fullmatch(value) is None:
        raise OutboxInputError()
    return value


def _reason(value: str) -> str:
    if not isinstance(value, str) or _REASON_CODE.fullmatch(value) is None:
        raise OutboxInputError()
    return value


def _positive_int(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise OutboxInputError()
    return value


def _nonnegative_int(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise OutboxInputError()
    return value


def _duration(value: timedelta) -> timedelta:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise OutboxInputError()
    return value


def _time(value: datetime | None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if not isinstance(current, datetime):
        raise OutboxInputError()
    return _as_utc(current)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _mac_key(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) < 32:
        raise OutboxInputError()
    return bytes(value)
