"""Caller-owned operational signal evaluation and alert lifecycle state."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from types import MappingProxyType
from typing import Iterable, Mapping
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inventory_control.models.operations import (
    PlatformAlertLifecycleEvent,
    PlatformOperationalSignal,
)
from inventory_control.transactions import require_caller_transaction


ALERT_FINGERPRINT_VERSION = 1
_MAX_POLICY_SECONDS = 2_147_483_647


class OperationalStateError(RuntimeError):
    code = "OPERATIONAL_STATE_ERROR"
    public_message = "operational state operation failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class OperationalInputError(OperationalStateError):
    code = "OPERATIONAL_INPUT_INVALID"
    public_message = "operational state input is invalid"


class OperationalTransactionRequiredError(OperationalStateError):
    code = "OPERATIONAL_TRANSACTION_REQUIRED"
    public_message = "an explicit caller-owned transaction is required"


class OperationalPolicyError(OperationalStateError):
    code = "OPERATIONAL_POLICY_INVALID"
    public_message = "operational signal policy is invalid"


class OperationalPolicyConflictError(OperationalStateError):
    code = "OPERATIONAL_POLICY_CONFLICT"
    public_message = "operational signal policy conflicts with persisted state"


class OperationalSignalNotFoundError(OperationalStateError):
    code = "OPERATIONAL_SIGNAL_NOT_FOUND"
    public_message = "operational signal has not been initialized"


class OperationalObservationConflictError(OperationalStateError):
    code = "OPERATIONAL_OBSERVATION_CONFLICT"
    public_message = "operational signal observation conflicts with current state"


class OperationalStateIntegrityError(OperationalStateError):
    code = "OPERATIONAL_STATE_INTEGRITY"
    public_message = "operational signal state failed integrity validation"


class OperationalEnvironment(str, Enum):
    DEVELOPMENT = "development"
    PRODUCTION = "production"
    STAGING = "staging"
    TEST = "test"


class OperationalSignalKey(str, Enum):
    BACKUP_DUMP_DURATION = "backup.dump_duration"
    BACKUP_VERIFIED_FRESHNESS = "backup.verified_freshness"
    CLOUD_SYNC_FRESHNESS = "cloud_sync.freshness"
    CONTROL_DB_CONNECTION_CAPACITY = "control_db.connection_capacity"
    CONTROL_DB_CONNECTIVITY = "control_db.connectivity"
    EVALUATOR_HEARTBEAT = "evaluator.heartbeat"
    KUAIMAI_AGGREGATE = "kuaimai.aggregate"
    NOTIFICATION_DELIVERY = "notification.delivery"
    QUEUE_CONSECUTIVE_FAILURES = "queue.consecutive_failures"
    QUEUE_OLDEST_WAIT = "queue.oldest_wait"
    SF_AGGREGATE = "sf.aggregate"
    SMS_AGGREGATE = "sms.aggregate"
    WEB_HEARTBEAT = "web.heartbeat"
    WORKER_HEARTBEAT = "worker.heartbeat"
    XIANYU_AGGREGATE = "xianyu.aggregate"


class OperationalObservationStatus(str, Enum):
    FAILURE = "failure"
    OK = "ok"


class OperationalResultClass(str, Enum):
    AUTHENTICATION_FAILURE = "authentication_failure"
    CAPACITY_HIGH = "capacity_high"
    DELIVERY_FAILURE = "delivery_failure"
    HEARTBEAT = "heartbeat"
    OK = "ok"
    PERSISTENT_FAILURE = "persistent_failure"
    PROVIDER_ERROR = "provider_error"
    RATE_LIMITED = "rate_limited"
    STALE = "stale"
    THRESHOLD_EXCEEDED = "threshold_exceeded"
    UNAVAILABLE = "unavailable"
    UNKNOWN = "unknown"
    VERIFIED = "verified"


class OperationalEffectiveStatus(str, Enum):
    DEGRADED = "degraded"
    HEALTHY = "healthy"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


class AlertLifecycleKind(str, Enum):
    RECOVERY = "recovery"
    REPEAT = "repeat"
    SUPPRESSED = "suppressed"
    TRIGGER = "trigger"


@dataclass(frozen=True, slots=True)
class _SignalDefinition:
    source: str
    component: str
    severity: str


_SIGNAL_DEFINITIONS: Mapping[
    OperationalSignalKey, _SignalDefinition
] = MappingProxyType(
    {
        OperationalSignalKey.BACKUP_DUMP_DURATION: _SignalDefinition(
            "nas", "backup", "p2"
        ),
        OperationalSignalKey.BACKUP_VERIFIED_FRESHNESS: _SignalDefinition(
            "nas", "backup", "p1"
        ),
        OperationalSignalKey.CLOUD_SYNC_FRESHNESS: _SignalDefinition(
            "nas", "cloud_sync", "p2"
        ),
        OperationalSignalKey.CONTROL_DB_CONNECTION_CAPACITY: (
            _SignalDefinition("control_db", "mysql", "p2")
        ),
        OperationalSignalKey.CONTROL_DB_CONNECTIVITY: _SignalDefinition(
            "control_db", "mysql", "p1"
        ),
        OperationalSignalKey.EVALUATOR_HEARTBEAT: _SignalDefinition(
            "evaluator", "evaluator", "p2"
        ),
        OperationalSignalKey.KUAIMAI_AGGREGATE: _SignalDefinition(
            "provider_aggregate", "kuaimai", "p2"
        ),
        OperationalSignalKey.NOTIFICATION_DELIVERY: _SignalDefinition(
            "notification_adapter", "notification", "p2"
        ),
        OperationalSignalKey.QUEUE_CONSECUTIVE_FAILURES: _SignalDefinition(
            "worker", "queue", "p2"
        ),
        OperationalSignalKey.QUEUE_OLDEST_WAIT: _SignalDefinition(
            "worker", "queue", "p2"
        ),
        OperationalSignalKey.SF_AGGREGATE: _SignalDefinition(
            "provider_aggregate", "sf", "p2"
        ),
        OperationalSignalKey.SMS_AGGREGATE: _SignalDefinition(
            "provider_aggregate", "sms", "p1"
        ),
        OperationalSignalKey.WEB_HEARTBEAT: _SignalDefinition("web", "web", "p2"),
        OperationalSignalKey.WORKER_HEARTBEAT: _SignalDefinition(
            "worker", "worker", "p2"
        ),
        OperationalSignalKey.XIANYU_AGGREGATE: _SignalDefinition(
            "provider_aggregate", "xianyu", "p2"
        ),
    }
)

_OK_RESULT_CLASSES = frozenset(
    {
        OperationalResultClass.HEARTBEAT,
        OperationalResultClass.OK,
        OperationalResultClass.VERIFIED,
    }
)
_FAILURE_RESULT_CLASSES = frozenset(OperationalResultClass) - (
    _OK_RESULT_CLASSES | {OperationalResultClass.STALE}
)


@dataclass(frozen=True, slots=True)
class OperationalSignalPolicy:
    signal_key: OperationalSignalKey
    version: int
    failure_threshold: int
    recovery_threshold: int
    freshness_window: timedelta
    repeat_interval: timedelta

    def __post_init__(self) -> None:
        if not isinstance(self.signal_key, OperationalSignalKey):
            raise OperationalPolicyError()
        _positive_int(self.version, policy=True)
        _positive_int(self.failure_threshold, policy=True)
        _positive_int(self.recovery_threshold, policy=True)
        _duration_seconds(self.freshness_window, policy=True)
        _duration_seconds(self.repeat_interval, policy=True)


class OperationalPolicyRegistry:
    """Complete immutable policy set for every supported signal key."""

    __slots__ = ("_policies",)

    def __init__(self, policies: Iterable[OperationalSignalPolicy]) -> None:
        try:
            supplied = tuple(policies)
        except TypeError:
            raise OperationalPolicyError() from None
        by_key: dict[OperationalSignalKey, OperationalSignalPolicy] = {}
        for policy in supplied:
            if not isinstance(policy, OperationalSignalPolicy):
                raise OperationalPolicyError()
            if policy.signal_key in by_key:
                raise OperationalPolicyError()
            by_key[policy.signal_key] = policy
        if set(by_key) != set(OperationalSignalKey):
            raise OperationalPolicyError()
        self._policies = MappingProxyType(by_key)

    def get(self, signal_key: OperationalSignalKey) -> OperationalSignalPolicy:
        try:
            return self._policies[signal_key]
        except (KeyError, TypeError):
            raise OperationalPolicyError() from None


@dataclass(frozen=True, slots=True)
class OperationalSignalSnapshot:
    signal_key: OperationalSignalKey
    environment: OperationalEnvironment
    source: str
    component: str
    severity: str
    observed_status: OperationalObservationStatus
    observed_result_class: OperationalResultClass
    effective_status: OperationalEffectiveStatus
    result_class: OperationalResultClass
    policy_version: int
    consecutive_failures: int
    consecutive_recoveries: int
    state_generation: int
    alert_generation: int
    active_alert_fingerprint: str | None
    observed_at: datetime
    freshness_deadline_at: datetime
    evaluated_at: datetime
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class AlertLifecycleEventRef:
    event_id: str
    signal_key: OperationalSignalKey
    event_type: AlertLifecycleKind
    effective_status: OperationalEffectiveStatus
    result_class: OperationalResultClass
    severity: str
    alert_fingerprint: str
    alert_generation: int
    lifecycle_sequence: int
    occurred_at: datetime
    suppressed_until: datetime | None


@dataclass(frozen=True, slots=True)
class OperationalSignalUpdate:
    signal: OperationalSignalSnapshot
    lifecycle_event: AlertLifecycleEventRef | None


class OperationalSignalService:
    """Persist current signal state without becoming a metrics time series."""

    def __init__(
        self,
        *,
        environment: OperationalEnvironment,
        policies: OperationalPolicyRegistry,
    ) -> None:
        if not isinstance(environment, OperationalEnvironment):
            raise OperationalInputError()
        if not isinstance(policies, OperationalPolicyRegistry):
            raise OperationalPolicyError()
        self._environment = environment
        self._policies = policies

    def record_worker_heartbeat(
        self,
        session: Session,
        *,
        observed_at: datetime,
    ) -> OperationalSignalUpdate:
        return self.record_observation(
            session,
            signal_key=OperationalSignalKey.WORKER_HEARTBEAT,
            observed_status=OperationalObservationStatus.OK,
            result_class=OperationalResultClass.HEARTBEAT,
            observed_at=observed_at,
        )

    def record_evaluator_heartbeat(
        self,
        session: Session,
        *,
        observed_at: datetime,
    ) -> OperationalSignalUpdate:
        return self.record_observation(
            session,
            signal_key=OperationalSignalKey.EVALUATOR_HEARTBEAT,
            observed_status=OperationalObservationStatus.OK,
            result_class=OperationalResultClass.HEARTBEAT,
            observed_at=observed_at,
        )

    def record_observation(
        self,
        session: Session,
        *,
        signal_key: OperationalSignalKey,
        observed_status: OperationalObservationStatus,
        result_class: OperationalResultClass,
        observed_at: datetime,
        notifications_suppressed_until: datetime | None = None,
    ) -> OperationalSignalUpdate:
        self._require_transaction(session)
        key = _signal_key(signal_key)
        status = _observation_status(observed_status)
        result = _result_class(result_class)
        _validate_observation_result(status, result)
        current_time = _time(observed_at)
        suppression = _active_suppression(
            notifications_suppressed_until, now=current_time
        )
        policy = self._policies.get(key)
        definition = _SIGNAL_DEFINITIONS[key]
        signal = self._load_signal_for_update(session, key)

        if signal is None:
            signal = self._new_signal(
                key=key,
                definition=definition,
                policy=policy,
                status=status,
                result=result,
                observed_at=current_time,
            )
            try:
                with session.begin_nested():
                    session.add(signal)
                    session.flush()
            except IntegrityError:
                signal = self._load_signal_for_update(session, key)
                if signal is None:
                    raise OperationalStateIntegrityError() from None
            else:
                event = self._emit_due_lifecycle(
                    session,
                    signal=signal,
                    now=current_time,
                    suppression=suppression,
                )
                signal.updated_at = current_time
                session.flush()
                return OperationalSignalUpdate(
                    signal=_snapshot(signal),
                    lifecycle_event=_event_ref(event),
                )

        self._verify_signal_identity(signal, key=key, definition=definition)
        previous_observed_at = _as_utc(signal.observed_at)
        previous_evaluated_at = _as_utc(signal.evaluated_at)
        if current_time < previous_observed_at:
            raise OperationalObservationConflictError()
        if current_time == previous_observed_at:
            if (
                signal.observed_status == status.value
                and signal.observed_result_class == result.value
            ):
                policy_changed = self._apply_policy(
                    signal, policy=policy, now=current_time
                )
                if policy_changed:
                    signal.state_generation += 1
                    signal.row_version += 1
                    session.flush()
                return OperationalSignalUpdate(
                    signal=_snapshot(signal, replay=True),
                    lifecycle_event=None,
                )
            raise OperationalObservationConflictError()
        if current_time <= previous_evaluated_at:
            raise OperationalObservationConflictError()
        self._apply_policy(signal, policy=policy, now=current_time)

        signal.observed_status = status.value
        signal.observed_result_class = result.value
        signal.observed_at = current_time
        signal.freshness_deadline_at = current_time + policy.freshness_window
        signal.evaluated_at = current_time
        signal.state_generation += 1
        signal.row_version += 1
        event: PlatformAlertLifecycleEvent | None = None

        if status is OperationalObservationStatus.FAILURE:
            signal.consecutive_failures += 1
            signal.consecutive_recoveries = 0
            signal.result_class = result.value
            if signal.active_alert_fingerprint is not None:
                if (
                    signal.effective_status == OperationalEffectiveStatus.UNKNOWN.value
                    and signal.consecutive_failures >= policy.failure_threshold
                ):
                    signal.effective_status = OperationalEffectiveStatus.UNHEALTHY.value
            elif signal.consecutive_failures >= policy.failure_threshold:
                signal.effective_status = OperationalEffectiveStatus.UNHEALTHY.value
                self._open_alert(signal, key=key, now=current_time)
            else:
                signal.effective_status = OperationalEffectiveStatus.DEGRADED.value
        else:
            signal.consecutive_failures = 0
            signal.consecutive_recoveries += 1
            if signal.active_alert_fingerprint is None:
                signal.effective_status = OperationalEffectiveStatus.HEALTHY.value
                signal.result_class = result.value
            elif signal.consecutive_recoveries >= policy.recovery_threshold:
                signal.effective_status = OperationalEffectiveStatus.HEALTHY.value
                signal.result_class = result.value
                event = self._append_lifecycle_event(
                    session,
                    signal=signal,
                    event_type=AlertLifecycleKind.RECOVERY,
                    occurred_at=current_time,
                )
                self._close_alert(signal)

        if event is None:
            event = self._emit_due_lifecycle(
                session,
                signal=signal,
                now=current_time,
                suppression=suppression,
            )
        signal.updated_at = current_time
        session.flush()
        return OperationalSignalUpdate(
            signal=_snapshot(signal),
            lifecycle_event=_event_ref(event),
        )

    def evaluate_freshness(
        self,
        session: Session,
        *,
        signal_key: OperationalSignalKey,
        evaluated_at: datetime,
        notifications_suppressed_until: datetime | None = None,
    ) -> OperationalSignalUpdate:
        self._require_transaction(session)
        key = _signal_key(signal_key)
        current_time = _time(evaluated_at)
        suppression = _active_suppression(
            notifications_suppressed_until, now=current_time
        )
        policy = self._policies.get(key)
        definition = _SIGNAL_DEFINITIONS[key]
        signal = self._load_signal_for_update(session, key)
        if signal is None:
            raise OperationalSignalNotFoundError()
        self._verify_signal_identity(signal, key=key, definition=definition)
        previous_evaluated_at = _as_utc(signal.evaluated_at)
        if (
            current_time < _as_utc(signal.observed_at)
            or current_time < previous_evaluated_at
        ):
            raise OperationalInputError()
        policy_changed = self._apply_policy(signal, policy=policy, now=current_time)

        changed = False
        if current_time >= _as_utc(signal.freshness_deadline_at):
            if signal.effective_status != OperationalEffectiveStatus.UNKNOWN.value:
                signal.effective_status = OperationalEffectiveStatus.UNKNOWN.value
                signal.result_class = OperationalResultClass.STALE.value
                signal.consecutive_failures = 0
                signal.consecutive_recoveries = 0
                signal.state_generation += 1
                changed = True
                if signal.active_alert_fingerprint is None:
                    self._open_alert(signal, key=key, now=current_time)

        if policy_changed and not changed:
            signal.state_generation += 1

        event = self._emit_due_lifecycle(
            session,
            signal=signal,
            now=current_time,
            suppression=suppression,
        )
        signal.evaluated_at = current_time
        signal.updated_at = current_time
        if (
            policy_changed
            or changed
            or event is not None
            or current_time > previous_evaluated_at
        ):
            signal.row_version += 1
        session.flush()
        return OperationalSignalUpdate(
            signal=_snapshot(signal),
            lifecycle_event=_event_ref(event),
        )

    def _new_signal(
        self,
        *,
        key: OperationalSignalKey,
        definition: _SignalDefinition,
        policy: OperationalSignalPolicy,
        status: OperationalObservationStatus,
        result: OperationalResultClass,
        observed_at: datetime,
    ) -> PlatformOperationalSignal:
        failure_count = 1 if status is OperationalObservationStatus.FAILURE else 0
        recovery_count = 1 if status is OperationalObservationStatus.OK else 0
        effective = (
            OperationalEffectiveStatus.UNHEALTHY
            if failure_count >= policy.failure_threshold
            else (
                OperationalEffectiveStatus.DEGRADED
                if failure_count
                else OperationalEffectiveStatus.HEALTHY
            )
        )
        signal = PlatformOperationalSignal(
            signal_key=key.value,
            environment=self._environment.value,
            source=definition.source,
            component=definition.component,
            severity=definition.severity,
            policy_version=policy.version,
            failure_threshold=policy.failure_threshold,
            recovery_threshold=policy.recovery_threshold,
            freshness_window_seconds=_duration_seconds(
                policy.freshness_window, policy=True
            ),
            repeat_interval_seconds=_duration_seconds(
                policy.repeat_interval, policy=True
            ),
            observed_status=status.value,
            observed_result_class=result.value,
            effective_status=effective.value,
            result_class=result.value,
            consecutive_failures=failure_count,
            consecutive_recoveries=recovery_count,
            state_generation=1,
            alert_generation=0,
            lifecycle_sequence=0,
            observed_at=observed_at,
            freshness_deadline_at=observed_at + policy.freshness_window,
            evaluated_at=observed_at,
            row_version=1,
            created_at=observed_at,
            updated_at=observed_at,
        )
        if effective is OperationalEffectiveStatus.UNHEALTHY:
            self._open_alert(signal, key=key, now=observed_at)
        return signal

    def _apply_policy(
        self,
        signal: PlatformOperationalSignal,
        *,
        policy: OperationalSignalPolicy,
        now: datetime,
    ) -> bool:
        current_values = (
            signal.failure_threshold,
            signal.recovery_threshold,
            signal.freshness_window_seconds,
            signal.repeat_interval_seconds,
        )
        configured_values = (
            policy.failure_threshold,
            policy.recovery_threshold,
            _duration_seconds(policy.freshness_window, policy=True),
            _duration_seconds(policy.repeat_interval, policy=True),
        )
        if signal.policy_version > policy.version:
            raise OperationalPolicyConflictError()
        if signal.policy_version == policy.version:
            if current_values != configured_values:
                raise OperationalPolicyConflictError()
            return False
        signal.policy_version = policy.version
        (
            signal.failure_threshold,
            signal.recovery_threshold,
            signal.freshness_window_seconds,
            signal.repeat_interval_seconds,
        ) = configured_values
        signal.freshness_deadline_at = _as_utc(signal.observed_at) + (
            policy.freshness_window
        )
        if signal.next_repeat_at is not None:
            signal.next_repeat_at = min(
                _as_utc(signal.next_repeat_at),
                now + policy.repeat_interval,
            )
        signal.updated_at = now
        return True

    def _open_alert(
        self,
        signal: PlatformOperationalSignal,
        *,
        key: OperationalSignalKey,
        now: datetime,
    ) -> None:
        if signal.active_alert_fingerprint is not None:
            raise OperationalStateIntegrityError()
        signal.alert_generation += 1
        signal.lifecycle_sequence = 0
        signal.active_alert_fingerprint = _alert_fingerprint(
            environment=self._environment,
            signal_key=key,
            definition=_SIGNAL_DEFINITIONS[key],
        )
        signal.alert_triggered_at = None
        signal.next_repeat_at = now

    @staticmethod
    def _close_alert(signal: PlatformOperationalSignal) -> None:
        signal.active_alert_fingerprint = None
        signal.alert_triggered_at = None
        signal.next_repeat_at = None

    def _emit_due_lifecycle(
        self,
        session: Session,
        *,
        signal: PlatformOperationalSignal,
        now: datetime,
        suppression: datetime | None,
    ) -> PlatformAlertLifecycleEvent | None:
        if (
            signal.active_alert_fingerprint is None
            or signal.next_repeat_at is None
            or _as_utc(signal.next_repeat_at) > now
        ):
            return None
        if suppression is not None:
            event_type = AlertLifecycleKind.SUPPRESSED
            suppressed_until = suppression
            signal.next_repeat_at = max(
                suppression,
                now + timedelta(seconds=signal.repeat_interval_seconds),
            )
        elif signal.alert_triggered_at is None:
            event_type = AlertLifecycleKind.TRIGGER
            suppressed_until = None
            signal.alert_triggered_at = now
            signal.next_repeat_at = now + timedelta(
                seconds=signal.repeat_interval_seconds
            )
        else:
            event_type = AlertLifecycleKind.REPEAT
            suppressed_until = None
            signal.next_repeat_at = now + timedelta(
                seconds=signal.repeat_interval_seconds
            )
        return self._append_lifecycle_event(
            session,
            signal=signal,
            event_type=event_type,
            occurred_at=now,
            suppressed_until=suppressed_until,
        )

    @staticmethod
    def _append_lifecycle_event(
        session: Session,
        *,
        signal: PlatformOperationalSignal,
        event_type: AlertLifecycleKind,
        occurred_at: datetime,
        suppressed_until: datetime | None = None,
    ) -> PlatformAlertLifecycleEvent:
        fingerprint = signal.active_alert_fingerprint
        if fingerprint is None or signal.alert_generation < 1:
            raise OperationalStateIntegrityError()
        signal.lifecycle_sequence += 1
        event = PlatformAlertLifecycleEvent(
            id=str(uuid4()),
            signal_key=signal.signal_key,
            environment=signal.environment,
            source=signal.source,
            component=signal.component,
            severity=signal.severity,
            event_type=event_type.value,
            effective_status=signal.effective_status,
            result_class=signal.result_class,
            policy_version=signal.policy_version,
            signal_state_generation=signal.state_generation,
            alert_generation=signal.alert_generation,
            lifecycle_sequence=signal.lifecycle_sequence,
            fingerprint_version=ALERT_FINGERPRINT_VERSION,
            alert_fingerprint=fingerprint,
            suppressed_until=suppressed_until,
            occurred_at=occurred_at,
        )
        session.add(event)
        return event

    @staticmethod
    def _load_signal_for_update(
        session: Session,
        key: OperationalSignalKey,
    ) -> PlatformOperationalSignal | None:
        return session.scalar(
            sa.select(PlatformOperationalSignal)
            .where(PlatformOperationalSignal.signal_key == key.value)
            .with_for_update()
        )

    def _verify_signal_identity(
        self,
        signal: PlatformOperationalSignal,
        *,
        key: OperationalSignalKey,
        definition: _SignalDefinition,
    ) -> None:
        if (
            signal.signal_key != key.value
            or signal.environment != self._environment.value
            or signal.source != definition.source
            or signal.component != definition.component
            or signal.severity != definition.severity
        ):
            raise OperationalStateIntegrityError()

    @staticmethod
    def _require_transaction(session: Session) -> None:
        require_caller_transaction(
            session,
            OperationalTransactionRequiredError,
            invalid_session_error=OperationalInputError,
        )


def _alert_fingerprint(
    *,
    environment: OperationalEnvironment,
    signal_key: OperationalSignalKey,
    definition: _SignalDefinition,
) -> str:
    parts = (
        "inventory-manager/platform-alert-fingerprint/v1",
        environment.value,
        signal_key.value,
        definition.source,
        definition.component,
        definition.severity,
    )
    encoded = b"".join(
        len(part.encode("ascii")).to_bytes(2, "big") + part.encode("ascii")
        for part in parts
    )
    return hashlib.sha256(encoded).hexdigest()


def _snapshot(
    signal: PlatformOperationalSignal,
    *,
    replay: bool = False,
) -> OperationalSignalSnapshot:
    try:
        return OperationalSignalSnapshot(
            signal_key=OperationalSignalKey(signal.signal_key),
            environment=OperationalEnvironment(signal.environment),
            source=signal.source,
            component=signal.component,
            severity=signal.severity,
            observed_status=OperationalObservationStatus(signal.observed_status),
            observed_result_class=OperationalResultClass(signal.observed_result_class),
            effective_status=OperationalEffectiveStatus(signal.effective_status),
            result_class=OperationalResultClass(signal.result_class),
            policy_version=signal.policy_version,
            consecutive_failures=signal.consecutive_failures,
            consecutive_recoveries=signal.consecutive_recoveries,
            state_generation=signal.state_generation,
            alert_generation=signal.alert_generation,
            active_alert_fingerprint=signal.active_alert_fingerprint,
            observed_at=_as_utc(signal.observed_at),
            freshness_deadline_at=_as_utc(signal.freshness_deadline_at),
            evaluated_at=_as_utc(signal.evaluated_at),
            idempotent_replay=replay,
        )
    except (TypeError, ValueError):
        raise OperationalStateIntegrityError() from None


def _event_ref(
    event: PlatformAlertLifecycleEvent | None,
) -> AlertLifecycleEventRef | None:
    if event is None:
        return None
    try:
        return AlertLifecycleEventRef(
            event_id=event.id,
            signal_key=OperationalSignalKey(event.signal_key),
            event_type=AlertLifecycleKind(event.event_type),
            effective_status=OperationalEffectiveStatus(event.effective_status),
            result_class=OperationalResultClass(event.result_class),
            severity=event.severity,
            alert_fingerprint=event.alert_fingerprint,
            alert_generation=event.alert_generation,
            lifecycle_sequence=event.lifecycle_sequence,
            occurred_at=_as_utc(event.occurred_at),
            suppressed_until=(
                None
                if event.suppressed_until is None
                else _as_utc(event.suppressed_until)
            ),
        )
    except (TypeError, ValueError):
        raise OperationalStateIntegrityError() from None


def _signal_key(value: OperationalSignalKey) -> OperationalSignalKey:
    if not isinstance(value, OperationalSignalKey):
        raise OperationalInputError()
    return value


def _observation_status(
    value: OperationalObservationStatus,
) -> OperationalObservationStatus:
    if not isinstance(value, OperationalObservationStatus):
        raise OperationalInputError()
    return value


def _result_class(value: OperationalResultClass) -> OperationalResultClass:
    if not isinstance(value, OperationalResultClass):
        raise OperationalInputError()
    return value


def _validate_observation_result(
    status: OperationalObservationStatus,
    result: OperationalResultClass,
) -> None:
    if (
        status is OperationalObservationStatus.OK and result not in _OK_RESULT_CLASSES
    ) or (
        status is OperationalObservationStatus.FAILURE
        and result not in _FAILURE_RESULT_CLASSES
    ):
        raise OperationalInputError()


def _positive_int(value: int, *, policy: bool = False) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > _MAX_POLICY_SECONDS
    ):
        if policy:
            raise OperationalPolicyError()
        raise OperationalInputError()
    return value


def _duration_seconds(value: timedelta, *, policy: bool = False) -> int:
    if not isinstance(value, timedelta):
        if policy:
            raise OperationalPolicyError()
        raise OperationalInputError()
    seconds = value.total_seconds()
    if seconds < 1 or seconds > _MAX_POLICY_SECONDS or not float(seconds).is_integer():
        if policy:
            raise OperationalPolicyError()
        raise OperationalInputError()
    return int(seconds)


def _time(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise OperationalInputError()
    return value.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise OperationalStateIntegrityError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _active_suppression(
    value: datetime | None,
    *,
    now: datetime,
) -> datetime | None:
    if value is None:
        return None
    suppression = _time(value)
    return suppression if suppression > now else None
