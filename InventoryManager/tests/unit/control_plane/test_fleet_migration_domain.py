from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.fleet_migrations import (
    FleetMigrationObservation,
    FleetMigrationState,
    FleetMigrationTarget,
    FleetRouteDisposition,
    FleetSchemaIdentity,
    SchemaCompatibilityWindow,
    begin_fleet_migration,
    evaluate_fleet_route,
    fail_fleet_migration,
    retry_fleet_migration,
    succeed_fleet_migration,
)
from inventory_control.fleet_migrations.domain import (
    FleetMigrationFenceConflict,
    FleetMigrationInvalid,
    FleetMigrationObservationRejected,
    FleetMigrationStateConflict,
)


NOW = datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc)
TENANT = UUID("11111111-1111-4111-8111-111111111111")
DATABASE = UUID("22222222-2222-4222-8222-222222222222")
MIGRATION = UUID("33333333-3333-4333-8333-333333333333")


def _identity(
    generation: int,
    *,
    revision: str | None = None,
    digest_byte: int | None = None,
    tenant: UUID = TENANT,
    database: UUID = DATABASE,
) -> FleetSchemaIdentity:
    selected = generation if digest_byte is None else digest_byte
    return FleetSchemaIdentity(
        tenant_uuid=tenant,
        database_uuid=database,
        schema_generation=generation,
        schema_revision=revision or f"rev_{generation}",
        schema_sha256=bytes([selected]) * 32,
    )


def _queued() -> FleetMigrationTarget:
    return FleetMigrationTarget.queued(
        migration_uuid=MIGRATION,
        source=_identity(8),
        target=_identity(9),
        database_now=NOW,
    )


def _observation(
    identity: FleetSchemaIdentity,
    *,
    at: datetime = NOW,
) -> FleetMigrationObservation:
    return FleetMigrationObservation(identity=identity, observed_at=at)


def _running() -> FleetMigrationTarget:
    return begin_fleet_migration(
        _queued(),
        expected_row_version=1,
        observation=_observation(_identity(8)),
        database_now=NOW,
    ).target


def test_compatibility_window_accepts_only_exact_current_and_previous() -> None:
    window = SchemaCompatibilityWindow(current=_identity(9), previous=_identity(8))

    assert window.evaluate(_identity(9)) is FleetRouteDisposition.ROUTABLE_CURRENT
    assert window.evaluate(_identity(8)) is FleetRouteDisposition.ROUTABLE_PREVIOUS
    assert window.evaluate(_identity(7)) is FleetRouteDisposition.HOLD_UNSUPPORTED_SCHEMA
    assert window.evaluate(None) is FleetRouteDisposition.HOLD_UNVERIFIED_SCHEMA


def test_same_generation_with_different_revision_or_digest_is_drift() -> None:
    window = SchemaCompatibilityWindow(current=_identity(9), previous=_identity(8))

    assert (
        window.evaluate(_identity(9, revision="unexpected"))
        is FleetRouteDisposition.HOLD_SCHEMA_DRIFT
    )
    assert (
        window.evaluate(_identity(8, digest_byte=42))
        is FleetRouteDisposition.HOLD_SCHEMA_DRIFT
    )


def test_cross_tenant_or_database_identity_is_held() -> None:
    window = SchemaCompatibilityWindow(current=_identity(9), previous=_identity(8))
    another_tenant = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
    another_database = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")

    assert (
        window.evaluate(_identity(9, tenant=another_tenant))
        is FleetRouteDisposition.HOLD_IDENTITY_MISMATCH
    )
    assert (
        window.evaluate(_identity(9, database=another_database))
        is FleetRouteDisposition.HOLD_IDENTITY_MISMATCH
    )


@pytest.mark.parametrize(
    "current,previous",
    [
        (_identity(9), _identity(9)),
        (_identity(8), _identity(9)),
        (_identity(9), _identity(7)),
        (
            _identity(9),
            _identity(
                8,
                database=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
            ),
        ),
    ],
)
def test_invalid_compatibility_windows_are_rejected(
    current: FleetSchemaIdentity,
    previous: FleetSchemaIdentity,
) -> None:
    with pytest.raises(FleetMigrationInvalid):
        SchemaCompatibilityWindow(current=current, previous=previous)


def test_begin_uses_exact_source_and_advances_attempt_and_fence() -> None:
    transition = begin_fleet_migration(
        _queued(),
        expected_row_version=1,
        observation=_observation(_identity(8)),
        database_now=NOW + timedelta(seconds=1),
    )

    assert transition.route_disposition is FleetRouteDisposition.ROUTABLE_PREVIOUS
    assert transition.target.state is FleetMigrationState.RUNNING
    assert transition.target.attempt_count == 1
    assert transition.target.operation_generation == 1
    assert transition.target.row_version == 2
    assert transition.target.started_at == NOW + timedelta(seconds=1)


def test_begin_finalizes_already_applied_target_without_second_ddl() -> None:
    transition = begin_fleet_migration(
        _queued(),
        expected_row_version=1,
        observation=_observation(_identity(9)),
        database_now=NOW,
    )

    assert transition.route_disposition is FleetRouteDisposition.ROUTABLE_CURRENT
    assert transition.target.state is FleetMigrationState.SUCCEEDED
    assert transition.target.attempt_count == 1
    assert transition.target.operation_generation == 1
    assert transition.target.started_at == NOW
    assert transition.target.completed_at == NOW


@pytest.mark.parametrize(
    "observed",
    [
        _identity(7),
        _identity(8, digest_byte=99),
        _identity(
            8,
            tenant=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        ),
    ],
)
def test_begin_rejects_unsupported_drifted_or_wrong_identity(
    observed: FleetSchemaIdentity,
) -> None:
    with pytest.raises(FleetMigrationObservationRejected):
        begin_fleet_migration(
            _queued(),
            expected_row_version=1,
            observation=_observation(observed),
            database_now=NOW,
        )


def test_success_requires_running_fence_and_exact_target() -> None:
    running = _running()
    completed = succeed_fleet_migration(
        running,
        expected_row_version=2,
        expected_operation_generation=1,
        observation=_observation(_identity(9), at=NOW + timedelta(seconds=1)),
        database_now=NOW + timedelta(seconds=1),
    )

    assert completed.target.state is FleetMigrationState.SUCCEEDED
    assert completed.target.row_version == 3
    assert completed.target.last_observed == _identity(9)
    assert completed.route_disposition is FleetRouteDisposition.ROUTABLE_CURRENT


@pytest.mark.parametrize(
    "row_version,generation",
    [(99, 1), (2, 99)],
)
def test_stale_success_fences_are_rejected(row_version: int, generation: int) -> None:
    with pytest.raises(FleetMigrationFenceConflict):
        succeed_fleet_migration(
            _running(),
            expected_row_version=row_version,
            expected_operation_generation=generation,
            observation=_observation(_identity(9)),
            database_now=NOW,
        )


def test_success_rejects_source_or_drifted_target_observation() -> None:
    for identity in (_identity(8), _identity(9, digest_byte=55)):
        with pytest.raises(FleetMigrationObservationRejected):
            succeed_fleet_migration(
                _running(),
                expected_row_version=2,
                expected_operation_generation=1,
                observation=_observation(identity),
                database_now=NOW,
            )


def test_failure_on_supported_source_is_local_and_retryable() -> None:
    failed = fail_fleet_migration(
        _running(),
        expected_row_version=2,
        expected_operation_generation=1,
        observation=_observation(_identity(8), at=NOW + timedelta(seconds=1)),
        safe_error_code="DDL_TIMEOUT",
        database_now=NOW + timedelta(seconds=1),
    )

    assert failed.target.state is FleetMigrationState.FAILED
    assert failed.target.safe_error_code == "DDL_TIMEOUT"
    assert failed.route_disposition is FleetRouteDisposition.ROUTABLE_PREVIOUS
    assert failed.route_disposition.routable

    retried = retry_fleet_migration(
        failed.target,
        expected_row_version=3,
        observation=_observation(_identity(8), at=NOW + timedelta(seconds=2)),
        database_now=NOW + timedelta(seconds=2),
    )
    assert retried.target.state is FleetMigrationState.RUNNING
    assert retried.target.attempt_count == 2
    assert retried.target.operation_generation == 2
    assert retried.target.row_version == 4


def test_failure_observing_completed_target_converges_to_success() -> None:
    result = fail_fleet_migration(
        _running(),
        expected_row_version=2,
        expected_operation_generation=1,
        observation=_observation(_identity(9), at=NOW + timedelta(seconds=1)),
        safe_error_code="WORKER_RESPONSE_LOST",
        database_now=NOW + timedelta(seconds=1),
    )

    assert result.target.state is FleetMigrationState.SUCCEEDED
    assert result.target.safe_error_code is None
    assert result.route_disposition is FleetRouteDisposition.ROUTABLE_CURRENT


def test_failure_with_drift_is_recorded_but_route_remains_held() -> None:
    result = fail_fleet_migration(
        _running(),
        expected_row_version=2,
        expected_operation_generation=1,
        observation=_observation(
            _identity(8, digest_byte=88),
            at=NOW + timedelta(seconds=1),
        ),
        safe_error_code="SCHEMA_DRIFT",
        database_now=NOW + timedelta(seconds=1),
    )

    assert result.target.state is FleetMigrationState.FAILED
    assert result.route_disposition is FleetRouteDisposition.HOLD_SCHEMA_DRIFT
    assert not result.route_disposition.routable
    assert (
        evaluate_fleet_route(
            result.target,
            _observation(_identity(8, digest_byte=88)),
        )
        is FleetRouteDisposition.HOLD_SCHEMA_DRIFT
    )


def test_failure_with_cross_database_observation_holds_only_this_target() -> None:
    other_database = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
    result = fail_fleet_migration(
        _running(),
        expected_row_version=2,
        expected_operation_generation=1,
        observation=_observation(
            _identity(8, database=other_database),
            at=NOW + timedelta(seconds=1),
        ),
        safe_error_code="IDENTITY_MISMATCH",
        database_now=NOW + timedelta(seconds=1),
    )

    assert result.target.state is FleetMigrationState.FAILED
    assert (
        result.route_disposition
        is FleetRouteDisposition.HOLD_IDENTITY_MISMATCH
    )
    assert result.target.last_observed.database_uuid == other_database


def test_missing_observation_fails_closed_without_changing_state() -> None:
    current = _queued()
    assert (
        evaluate_fleet_route(current, None)
        is FleetRouteDisposition.HOLD_UNVERIFIED_SCHEMA
    )
    assert current.state is FleetMigrationState.QUEUED


def test_future_observation_and_clock_regression_are_rejected() -> None:
    with pytest.raises(FleetMigrationObservationRejected):
        begin_fleet_migration(
            _queued(),
            expected_row_version=1,
            observation=_observation(
                _identity(8),
                at=NOW + timedelta(seconds=2),
            ),
            database_now=NOW + timedelta(seconds=1),
        )

    running = _running()
    with pytest.raises(FleetMigrationInvalid):
        fail_fleet_migration(
            running,
            expected_row_version=2,
            expected_operation_generation=1,
            observation=_observation(_identity(8), at=NOW - timedelta(seconds=1)),
            safe_error_code="DDL_FAILED",
            database_now=NOW - timedelta(seconds=1),
        )


def test_non_running_terminal_transitions_are_rejected() -> None:
    queued = _queued()
    with pytest.raises(FleetMigrationStateConflict):
        succeed_fleet_migration(
            queued,
            expected_row_version=1,
            expected_operation_generation=1,
            observation=_observation(_identity(9)),
            database_now=NOW,
        )
    with pytest.raises(FleetMigrationStateConflict):
        retry_fleet_migration(
            queued,
            expected_row_version=1,
            observation=_observation(_identity(8)),
            database_now=NOW,
        )


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: replace(value, row_version=0),
        lambda value: replace(value, source=_identity(9), target=_identity(8)),
        lambda value: replace(value, safe_error_code="contains secret text"),
    ],
)
def test_invalid_persisted_target_shapes_are_rejected(mutator) -> None:
    with pytest.raises(FleetMigrationInvalid):
        mutator(_queued())
