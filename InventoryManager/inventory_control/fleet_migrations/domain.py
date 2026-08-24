"""Pure per-tenant fleet migration and schema compatibility rules.

The reducer deliberately performs no SQL, DDL, routing, or network work.  A
trusted adapter must obtain observations from ``database_identity`` and the
schema digest boundary while holding the shared schema-operation lease and a
per-database advisory lock.  These rules make one tenant failure local: an
exact supported N/N-1 schema can remain routable, while an unknown or drifted
schema is held instead of being bypassed with a generic database account.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from enum import Enum
from uuid import UUID


_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")
_ERROR_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,63}$")
_SHA256_BYTES = 32


class FleetMigrationState(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class FleetRouteDisposition(str, Enum):
    """Runtime result, not a D64 project approval or release gate."""

    ROUTABLE_CURRENT = "routable_current"
    ROUTABLE_PREVIOUS = "routable_previous"
    HOLD_IDENTITY_MISMATCH = "hold_identity_mismatch"
    HOLD_SCHEMA_DRIFT = "hold_schema_drift"
    HOLD_UNSUPPORTED_SCHEMA = "hold_unsupported_schema"
    HOLD_UNVERIFIED_SCHEMA = "hold_unverified_schema"

    @property
    def routable(self) -> bool:
        return self in {
            FleetRouteDisposition.ROUTABLE_CURRENT,
            FleetRouteDisposition.ROUTABLE_PREVIOUS,
        }


class FleetMigrationError(RuntimeError):
    code = "FLEET_MIGRATION_REJECTED"
    public_message = "the tenant schema migration request was rejected"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class FleetMigrationInvalid(FleetMigrationError):
    code = "FLEET_MIGRATION_INVALID"
    public_message = "the tenant schema migration request is invalid"


class FleetMigrationStateConflict(FleetMigrationError):
    code = "FLEET_MIGRATION_STATE_CONFLICT"
    public_message = "the tenant schema migration is out of order"


class FleetMigrationFenceConflict(FleetMigrationError):
    code = "FLEET_MIGRATION_FENCE_CONFLICT"
    public_message = "the tenant schema migration changed"


class FleetMigrationObservationRejected(FleetMigrationError):
    code = "FLEET_MIGRATION_OBSERVATION_REJECTED"
    public_message = "the tenant schema observation was rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class FleetSchemaIdentity:
    """Exact immutable database identity plus one schema revision digest."""

    tenant_uuid: UUID
    database_uuid: UUID
    schema_generation: int
    schema_revision: str
    schema_sha256: bytes

    def __post_init__(self) -> None:
        _uuid(self.tenant_uuid)
        _uuid(self.database_uuid)
        _positive(self.schema_generation)
        _revision(self.schema_revision)
        _digest(self.schema_sha256)

    def same_database(self, other: "FleetSchemaIdentity") -> bool:
        return bool(
            isinstance(other, FleetSchemaIdentity)
            and self.tenant_uuid == other.tenant_uuid
            and self.database_uuid == other.database_uuid
        )

    def same_schema(self, other: "FleetSchemaIdentity") -> bool:
        return bool(
            self.same_database(other)
            and self.schema_generation == other.schema_generation
            and self.schema_revision == other.schema_revision
            and hmac.compare_digest(self.schema_sha256, other.schema_sha256)
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class SchemaCompatibilityWindow:
    """The exact current schema and optional immediately previous schema."""

    current: FleetSchemaIdentity
    previous: FleetSchemaIdentity | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.current, FleetSchemaIdentity):
            raise FleetMigrationInvalid()
        if self.previous is None:
            return
        if not isinstance(self.previous, FleetSchemaIdentity):
            raise FleetMigrationInvalid()
        if not self.current.same_database(self.previous):
            raise FleetMigrationInvalid()
        if (
            self.previous.schema_generation
            != self.current.schema_generation - 1
        ):
            raise FleetMigrationInvalid()
        if self.previous.schema_revision == self.current.schema_revision:
            raise FleetMigrationInvalid()

    def evaluate(
        self,
        observed: FleetSchemaIdentity | None,
    ) -> FleetRouteDisposition:
        if observed is None:
            return FleetRouteDisposition.HOLD_UNVERIFIED_SCHEMA
        if not isinstance(observed, FleetSchemaIdentity):
            raise FleetMigrationInvalid()
        if not self.current.same_database(observed):
            return FleetRouteDisposition.HOLD_IDENTITY_MISMATCH
        if observed.schema_generation == self.current.schema_generation:
            if self.current.same_schema(observed):
                return FleetRouteDisposition.ROUTABLE_CURRENT
            return FleetRouteDisposition.HOLD_SCHEMA_DRIFT
        if (
            self.previous is not None
            and observed.schema_generation == self.previous.schema_generation
        ):
            if self.previous.same_schema(observed):
                return FleetRouteDisposition.ROUTABLE_PREVIOUS
            return FleetRouteDisposition.HOLD_SCHEMA_DRIFT
        return FleetRouteDisposition.HOLD_UNSUPPORTED_SCHEMA


@dataclass(frozen=True, slots=True, kw_only=True)
class FleetMigrationObservation:
    """Trusted post-lock observation from the target tenant database."""

    identity: FleetSchemaIdentity
    observed_at: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.identity, FleetSchemaIdentity):
            raise FleetMigrationInvalid()
        object.__setattr__(self, "observed_at", _utc(self.observed_at))


@dataclass(frozen=True, slots=True, kw_only=True)
class FleetMigrationTarget:
    """Persistable per-database migration state.

    ``operation_generation`` is advanced for every new running attempt and is
    carried with the global schema-operation fencing token to external DDL.
    Row version protects caller-owned control-database CAS updates.
    """

    migration_uuid: UUID
    source: FleetSchemaIdentity
    target: FleetSchemaIdentity
    state: FleetMigrationState
    attempt_count: int
    operation_generation: int
    row_version: int
    queued_at: datetime
    started_at: datetime | None = None
    completed_at: datetime | None = None
    last_observed: FleetSchemaIdentity | None = None
    safe_error_code: str | None = None

    def __post_init__(self) -> None:
        _uuid(self.migration_uuid)
        if not isinstance(self.source, FleetSchemaIdentity):
            raise FleetMigrationInvalid()
        if not isinstance(self.target, FleetSchemaIdentity):
            raise FleetMigrationInvalid()
        if not self.source.same_database(self.target):
            raise FleetMigrationInvalid()
        if self.target.schema_generation != self.source.schema_generation + 1:
            raise FleetMigrationInvalid()
        try:
            state = FleetMigrationState(self.state)
        except (TypeError, ValueError):
            raise FleetMigrationInvalid() from None
        object.__setattr__(self, "state", state)
        _nonnegative(self.attempt_count)
        _nonnegative(self.operation_generation)
        _positive(self.row_version)
        queued = _utc(self.queued_at)
        object.__setattr__(self, "queued_at", queued)
        started = None if self.started_at is None else _utc(self.started_at)
        completed = None if self.completed_at is None else _utc(self.completed_at)
        if started is not None and started < queued:
            raise FleetMigrationInvalid()
        if completed is not None and (started is None or completed < started):
            raise FleetMigrationInvalid()
        object.__setattr__(self, "started_at", started)
        object.__setattr__(self, "completed_at", completed)
        if self.last_observed is not None:
            if not isinstance(self.last_observed, FleetSchemaIdentity):
                raise FleetMigrationInvalid()
            if (
                state is not FleetMigrationState.FAILED
                and not self.source.same_database(self.last_observed)
            ):
                raise FleetMigrationInvalid()
        if self.safe_error_code is not None:
            _error_code(self.safe_error_code)

        if state is FleetMigrationState.QUEUED:
            if any(
                value is not None
                for value in (started, completed, self.last_observed, self.safe_error_code)
            ) or self.attempt_count != 0 or self.operation_generation != 0:
                raise FleetMigrationInvalid()
        elif state is FleetMigrationState.RUNNING:
            if (
                started is None
                or completed is not None
                or self.last_observed is None
                or self.safe_error_code is not None
                or self.attempt_count < 1
                or self.operation_generation < 1
            ):
                raise FleetMigrationInvalid()
        elif state is FleetMigrationState.SUCCEEDED:
            if (
                completed is None
                or self.last_observed is None
                or not self.target.same_schema(self.last_observed)
                or self.safe_error_code is not None
                or self.attempt_count < 1
                or self.operation_generation < 1
            ):
                raise FleetMigrationInvalid()
        elif state is FleetMigrationState.FAILED:
            if (
                completed is None
                or self.last_observed is None
                or self.safe_error_code is None
                or self.attempt_count < 1
                or self.operation_generation < 1
            ):
                raise FleetMigrationInvalid()

    @classmethod
    def queued(
        cls,
        *,
        migration_uuid: UUID,
        source: FleetSchemaIdentity,
        target: FleetSchemaIdentity,
        database_now: datetime,
    ) -> "FleetMigrationTarget":
        return cls(
            migration_uuid=migration_uuid,
            source=source,
            target=target,
            state=FleetMigrationState.QUEUED,
            attempt_count=0,
            operation_generation=0,
            row_version=1,
            queued_at=database_now,
        )


@dataclass(frozen=True, slots=True)
class FleetMigrationTransition:
    target: FleetMigrationTarget
    route_disposition: FleetRouteDisposition


def begin_fleet_migration(
    current: FleetMigrationTarget,
    *,
    expected_row_version: int,
    observation: FleetMigrationObservation,
    database_now: datetime,
) -> FleetMigrationTransition:
    """Start a first attempt from source or retry from a failed observation."""

    _target(current)
    _expected_version(current, expected_row_version)
    now = _transition_time(current, database_now)
    if current.state not in {FleetMigrationState.QUEUED, FleetMigrationState.FAILED}:
        raise FleetMigrationStateConflict()
    observed = _observation_for(current, observation, now)
    compatibility = _window(current).evaluate(observed.identity)
    if compatibility is not FleetRouteDisposition.ROUTABLE_PREVIOUS:
        # A retry after an idempotently completed DDL may already observe the
        # target; finalize that fact instead of executing DDL a second time.
        if compatibility is FleetRouteDisposition.ROUTABLE_CURRENT:
            selected = replace(
                current,
                state=FleetMigrationState.SUCCEEDED,
                attempt_count=current.attempt_count + 1,
                operation_generation=current.operation_generation + 1,
                row_version=current.row_version + 1,
                started_at=now,
                completed_at=now,
                last_observed=observed.identity,
                safe_error_code=None,
            )
            return FleetMigrationTransition(selected, compatibility)
        raise FleetMigrationObservationRejected()
    selected = replace(
        current,
        state=FleetMigrationState.RUNNING,
        attempt_count=current.attempt_count + 1,
        operation_generation=current.operation_generation + 1,
        row_version=current.row_version + 1,
        started_at=now,
        completed_at=None,
        last_observed=observed.identity,
        safe_error_code=None,
    )
    return FleetMigrationTransition(selected, compatibility)


def succeed_fleet_migration(
    current: FleetMigrationTarget,
    *,
    expected_row_version: int,
    expected_operation_generation: int,
    observation: FleetMigrationObservation,
    database_now: datetime,
) -> FleetMigrationTransition:
    """Accept success only from an exact target identity and digest."""

    _running(current, expected_row_version, expected_operation_generation)
    now = _transition_time(current, database_now)
    observed = _observation_for(current, observation, now)
    disposition = _window(current).evaluate(observed.identity)
    if disposition is not FleetRouteDisposition.ROUTABLE_CURRENT:
        raise FleetMigrationObservationRejected()
    selected = replace(
        current,
        state=FleetMigrationState.SUCCEEDED,
        row_version=current.row_version + 1,
        completed_at=now,
        last_observed=observed.identity,
    )
    return FleetMigrationTransition(selected, disposition)


def fail_fleet_migration(
    current: FleetMigrationTarget,
    *,
    expected_row_version: int,
    expected_operation_generation: int,
    observation: FleetMigrationObservation,
    safe_error_code: str,
    database_now: datetime,
) -> FleetMigrationTransition:
    """Record a bounded technical failure without storing exception text."""

    _running(current, expected_row_version, expected_operation_generation)
    _error_code(safe_error_code)
    now = _transition_time(current, database_now)
    observed = _observation_for(
        current,
        observation,
        now,
        require_database_identity=False,
    )
    disposition = _window(current).evaluate(observed.identity)
    selected = replace(
        current,
        state=(
            FleetMigrationState.SUCCEEDED
            if disposition is FleetRouteDisposition.ROUTABLE_CURRENT
            else FleetMigrationState.FAILED
        ),
        row_version=current.row_version + 1,
        completed_at=now,
        last_observed=observed.identity,
        safe_error_code=(
            None
            if disposition is FleetRouteDisposition.ROUTABLE_CURRENT
            else safe_error_code
        ),
    )
    return FleetMigrationTransition(selected, disposition)


def retry_fleet_migration(
    current: FleetMigrationTarget,
    *,
    expected_row_version: int,
    observation: FleetMigrationObservation,
    database_now: datetime,
) -> FleetMigrationTransition:
    if current.state is not FleetMigrationState.FAILED:
        raise FleetMigrationStateConflict()
    return begin_fleet_migration(
        current,
        expected_row_version=expected_row_version,
        observation=observation,
        database_now=database_now,
    )


def evaluate_fleet_route(
    current: FleetMigrationTarget,
    observation: FleetMigrationObservation | None,
) -> FleetRouteDisposition:
    """Fail closed on absent, stale, cross-database, or drifted observations."""

    _target(current)
    if observation is None:
        return FleetRouteDisposition.HOLD_UNVERIFIED_SCHEMA
    if not isinstance(observation, FleetMigrationObservation):
        raise FleetMigrationInvalid()
    return _window(current).evaluate(observation.identity)


def _window(current: FleetMigrationTarget) -> SchemaCompatibilityWindow:
    return SchemaCompatibilityWindow(current=current.target, previous=current.source)


def _target(value: FleetMigrationTarget) -> None:
    if not isinstance(value, FleetMigrationTarget):
        raise FleetMigrationInvalid()


def _running(
    current: FleetMigrationTarget,
    expected_row_version: int,
    expected_operation_generation: int,
) -> None:
    _target(current)
    _expected_version(current, expected_row_version)
    _positive(expected_operation_generation)
    if current.state is not FleetMigrationState.RUNNING:
        raise FleetMigrationStateConflict()
    if current.operation_generation != expected_operation_generation:
        raise FleetMigrationFenceConflict()


def _expected_version(current: FleetMigrationTarget, expected: int) -> None:
    _positive(expected)
    if current.row_version != expected:
        raise FleetMigrationFenceConflict()


def _observation_for(
    current: FleetMigrationTarget,
    observation: FleetMigrationObservation,
    database_now: datetime,
    *,
    require_database_identity: bool = True,
) -> FleetMigrationObservation:
    if not isinstance(observation, FleetMigrationObservation):
        raise FleetMigrationInvalid()
    if observation.observed_at > database_now:
        raise FleetMigrationObservationRejected()
    if (
        require_database_identity
        and not current.source.same_database(observation.identity)
    ):
        raise FleetMigrationObservationRejected()
    return observation


def _transition_time(current: FleetMigrationTarget, value: datetime) -> datetime:
    selected = _utc(value)
    floor = current.completed_at or current.started_at or current.queued_at
    if selected < floor:
        raise FleetMigrationInvalid()
    return selected


def _uuid(value: UUID) -> None:
    if not isinstance(value, UUID):
        raise FleetMigrationInvalid()


def _positive(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise FleetMigrationInvalid()


def _nonnegative(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise FleetMigrationInvalid()


def _revision(value: str) -> None:
    if not isinstance(value, str) or _REVISION.fullmatch(value) is None:
        raise FleetMigrationInvalid()


def _error_code(value: str) -> None:
    if not isinstance(value, str) or _ERROR_CODE.fullmatch(value) is None:
        raise FleetMigrationInvalid()


def _digest(value: bytes) -> None:
    if not isinstance(value, bytes) or len(value) != _SHA256_BYTES:
        raise FleetMigrationInvalid()


def _utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise FleetMigrationInvalid()
    try:
        selected = value.astimezone(timezone.utc)
    except (OverflowError, ValueError):
        raise FleetMigrationInvalid() from None
    return selected


__all__ = [
    "FleetMigrationError",
    "FleetMigrationFenceConflict",
    "FleetMigrationInvalid",
    "FleetMigrationObservation",
    "FleetMigrationObservationRejected",
    "FleetMigrationState",
    "FleetMigrationStateConflict",
    "FleetMigrationTarget",
    "FleetMigrationTransition",
    "FleetRouteDisposition",
    "FleetSchemaIdentity",
    "SchemaCompatibilityWindow",
    "begin_fleet_migration",
    "evaluate_fleet_route",
    "fail_fleet_migration",
    "retry_fleet_migration",
    "succeed_fleet_migration",
]
