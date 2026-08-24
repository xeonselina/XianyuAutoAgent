from __future__ import annotations

from dataclasses import fields
from datetime import datetime, timezone
from typing import Mapping
from uuid import UUID, uuid4

import pytest

from inventory_control.fleet_migrations.domain import (
    FleetMigrationObservation,
    FleetSchemaIdentity,
)
from inventory_control.fleet_migrations.persistence import (
    FleetSchemaOperationFence,
)
from inventory_control.fleet_migrations.runner import (
    MAX_ADVISORY_LOCK_NAME_LENGTH,
    StaticTenantMigrationBundleRegistry,
    TenantMigrationBundleReference,
    TenantMigrationDdlError,
    TenantMigrationFenceError,
    TenantMigrationFencePhase,
    TenantMigrationIdentityMismatch,
    TenantMigrationLockUnavailable,
    TenantMigrationObservationPhase,
    TenantMigrationPlanError,
    TenantMigrationPostconditionError,
    TenantMigrationRunRequest,
    TenantMigrationRunner,
    VersionLockedTenantMigrationBundle,
    advisory_lock_name,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
TENANT_UUID = UUID("10000000-0000-4000-8000-000000000001")
DATABASE_UUID = UUID("20000000-0000-4000-8000-000000000002")
MIGRATION_UUID = UUID("30000000-0000-4000-8000-000000000003")
CLAIM_UUID = UUID("40000000-0000-4000-8000-000000000004")
SOURCE_DIGEST = bytes.fromhex("11" * 32)
TARGET_DIGEST = bytes.fromhex("22" * 32)
IMPLEMENTATION_DIGEST = bytes.fromhex("33" * 32)


def _identity(
    *,
    tenant_uuid: UUID = TENANT_UUID,
    database_uuid: UUID = DATABASE_UUID,
    generation: int = 8,
    revision: str = "tenant-schema-008",
    digest: bytes = SOURCE_DIGEST,
) -> FleetSchemaIdentity:
    return FleetSchemaIdentity(
        tenant_uuid=tenant_uuid,
        database_uuid=database_uuid,
        schema_generation=generation,
        schema_revision=revision,
        schema_sha256=digest,
    )


SOURCE = _identity()
TARGET = _identity(
    generation=9,
    revision="tenant-schema-009",
    digest=TARGET_DIGEST,
)


def _observation(identity: FleetSchemaIdentity) -> FleetMigrationObservation:
    return FleetMigrationObservation(identity=identity, observed_at=NOW)


class FakeTenantConnection:
    def __init__(
        self,
        events: list[object],
        *,
        get_lock_result: object = 1,
        release_lock_result: object = 1,
        get_lock_error: Exception | None = None,
        release_lock_error: Exception | None = None,
    ) -> None:
        self.events = events
        self.get_lock_result = get_lock_result
        self.release_lock_result = release_lock_result
        self.get_lock_error = get_lock_error
        self.release_lock_error = release_lock_error

    def scalar(
        self,
        statement: object,
        parameters: Mapping[str, object] | None = None,
    ) -> object:
        sql = str(statement)
        selected = dict(parameters or {})
        if sql == "SELECT GET_LOCK(:lock_name, :timeout_seconds)":
            self.events.append(("get_lock", selected))
            if self.get_lock_error is not None:
                raise self.get_lock_error
            return self.get_lock_result
        if sql == "SELECT RELEASE_LOCK(:lock_name)":
            self.events.append(("release_lock", selected))
            if self.release_lock_error is not None:
                raise self.release_lock_error
            return self.release_lock_result
        raise AssertionError("the runner sent unexpected SQL to the fake")


class RecordingObserver:
    def __init__(
        self,
        events: list[object],
        observations: list[object],
    ) -> None:
        self.events = events
        self.observations = list(observations)

    def observe(
        self,
        connection: FakeTenantConnection,
        *,
        phase: TenantMigrationObservationPhase,
        context: object,
    ) -> FleetMigrationObservation:
        assert isinstance(connection, FakeTenantConnection)
        self.events.append(("observe", phase))
        selected = self.observations.pop(0)
        if isinstance(selected, BaseException):
            raise selected
        return selected  # type: ignore[return-value]


class RecordingFenceValidator:
    def __init__(
        self,
        events: list[object],
        *,
        fail_phase: TenantMigrationFencePhase | None = None,
    ) -> None:
        self.events = events
        self.fail_phase = fail_phase

    def require_current(
        self,
        *,
        fence: FleetSchemaOperationFence,
        phase: TenantMigrationFencePhase,
        context: object,
    ) -> None:
        assert fence == FENCE
        self.events.append(("fence", phase))
        if phase is self.fail_phase:
            raise RuntimeError("UNTRUSTED_FENCE_DIAGNOSTIC")


FENCE = FleetSchemaOperationFence(
    claim_id=CLAIM_UUID,
    owner_id="fleet-worker-01",
    generation=7,
    fencing_token=11,
    row_version=13,
)


def _runner_parts(
    *,
    observations: list[object] | None = None,
    apply_error: Exception | None = None,
    fail_fence_phase: TenantMigrationFencePhase | None = None,
    lock_timeout_seconds: int = 5,
) -> tuple[
    TenantMigrationRunner,
    TenantMigrationRunRequest,
    list[object],
]:
    events: list[object] = []

    def apply(
        connection: FakeTenantConnection,
        context: object,
    ) -> None:
        assert isinstance(connection, FakeTenantConnection)
        events.append(("apply", context))
        if apply_error is not None:
            raise apply_error

    bundle = VersionLockedTenantMigrationBundle(
        bundle_id="tenant-schema-n8-to-n9",
        bundle_revision="build-20260822.1",
        implementation_sha256=IMPLEMENTATION_DIGEST,
        source=SOURCE,
        target=TARGET,
        apply=apply,
    )
    runner = TenantMigrationRunner(
        bundle_registry=StaticTenantMigrationBundleRegistry((bundle,)),
        observer=RecordingObserver(
            events,
            observations
            if observations is not None
            else [_observation(SOURCE), _observation(TARGET)],
        ),
        fence_validator=RecordingFenceValidator(
            events,
            fail_phase=fail_fence_phase,
        ),
        lock_timeout_seconds=lock_timeout_seconds,
    )
    request = TenantMigrationRunRequest(
        migration_uuid=MIGRATION_UUID,
        operation_generation=3,
        schema_operation_fence=FENCE,
        bundle=bundle.reference(),
    )
    return runner, request, events


def test_runner_acquires_lock_validates_fence_and_returns_target_observation() -> None:
    runner, request, events = _runner_parts()
    connection = FakeTenantConnection(events)

    result = runner.run(connection=connection, request=request)

    assert result.final_observation == _observation(TARGET)
    assert result.advisory_lock_release_confirmed is True
    assert result.connection_must_close is False
    assert result.ddl_is_transactional is False
    assert result.ddl_implicit_commit_possible is True
    assert result.context.ddl_is_transactional is False
    assert result.context.ddl_implicit_commit_possible is True
    assert [event[0] for event in events] == [
        "get_lock",
        "observe",
        "fence",
        "apply",
        "fence",
        "observe",
        "release_lock",
    ]
    assert events[1] == (
        "observe",
        TenantMigrationObservationPhase.BEFORE_DDL,
    )
    assert events[2] == ("fence", TenantMigrationFencePhase.BEFORE_DDL)
    assert events[4] == ("fence", TenantMigrationFencePhase.AFTER_DDL)
    assert events[5] == (
        "observe",
        TenantMigrationObservationPhase.AFTER_DDL,
    )
    get_lock_parameters = events[0][1]
    assert get_lock_parameters["timeout_seconds"] == 5
    assert get_lock_parameters["lock_name"] == events[-1][1]["lock_name"]


def test_runner_rejects_server_lock_denial_without_touching_tenant() -> None:
    runner, request, events = _runner_parts()
    connection = FakeTenantConnection(events, get_lock_result=0)

    with pytest.raises(TenantMigrationLockUnavailable) as raised:
        runner.run(connection=connection, request=request)

    assert raised.value.ddl_may_have_committed is False
    assert raised.value.lock_release_confirmed is None
    assert events == [
        (
            "get_lock",
            {
                "lock_name": advisory_lock_name(DATABASE_UUID),
                "timeout_seconds": 5,
            },
        )
    ]


@pytest.mark.parametrize("ambiguous_result", [None, False, 2])
def test_runner_best_effort_releases_ambiguous_get_lock_result(
    ambiguous_result: object,
) -> None:
    runner, request, events = _runner_parts()
    connection = FakeTenantConnection(
        events,
        get_lock_result=ambiguous_result,
    )

    with pytest.raises(TenantMigrationLockUnavailable) as raised:
        runner.run(connection=connection, request=request)

    assert raised.value.ddl_may_have_committed is False
    assert raised.value.lock_release_confirmed is True
    assert raised.value.connection_must_close is False
    assert [event[0] for event in events] == ["get_lock", "release_lock"]


def test_runner_sanitizes_get_lock_error_and_best_effort_releases() -> None:
    runner, request, events = _runner_parts()
    connection = FakeTenantConnection(
        events,
        get_lock_error=RuntimeError("UNTRUSTED_GET_LOCK_DIAGNOSTIC"),
    )

    with pytest.raises(TenantMigrationLockUnavailable) as raised:
        runner.run(connection=connection, request=request)

    assert "UNTRUSTED_GET_LOCK_DIAGNOSTIC" not in str(raised.value)
    assert "UNTRUSTED_GET_LOCK_DIAGNOSTIC" not in repr(raised.value)
    assert raised.value.lock_release_confirmed is True
    assert [event[0] for event in events] == ["get_lock", "release_lock"]


def test_ambiguous_get_lock_and_failed_release_requires_connection_close() -> None:
    runner, request, events = _runner_parts()
    connection = FakeTenantConnection(
        events,
        get_lock_error=RuntimeError("UNTRUSTED_GET_LOCK_DIAGNOSTIC"),
        release_lock_error=RuntimeError("UNTRUSTED_RELEASE_DIAGNOSTIC"),
    )

    with pytest.raises(TenantMigrationLockUnavailable) as raised:
        runner.run(connection=connection, request=request)

    assert raised.value.lock_release_confirmed is False
    assert raised.value.connection_must_close is True
    assert "UNTRUSTED_GET_LOCK_DIAGNOSTIC" not in str(raised.value)
    assert "UNTRUSTED_RELEASE_DIAGNOSTIC" not in repr(raised.value)
    assert [event[0] for event in events] == ["get_lock", "release_lock"]


@pytest.mark.parametrize(
    "unexpected_source",
    [
        _identity(database_uuid=uuid4()),
        _identity(digest=bytes.fromhex("44" * 32)),
        TARGET,
    ],
)
def test_runner_holds_identity_drift_before_ddl_and_releases_lock(
    unexpected_source: FleetSchemaIdentity,
) -> None:
    runner, request, events = _runner_parts(
        observations=[_observation(unexpected_source)]
    )
    connection = FakeTenantConnection(events)

    with pytest.raises(TenantMigrationIdentityMismatch) as raised:
        runner.run(connection=connection, request=request)

    assert raised.value.ddl_may_have_committed is False
    assert raised.value.post_observation == _observation(unexpected_source)
    assert raised.value.lock_release_confirmed is True
    assert [event[0] for event in events] == [
        "get_lock",
        "observe",
        "release_lock",
    ]


def test_runner_reports_ddl_failure_as_possibly_committed_and_sanitizes_error() -> None:
    runner, request, events = _runner_parts(
        observations=[_observation(SOURCE), _observation(SOURCE)],
        apply_error=RuntimeError("UNTRUSTED_DDL_DIAGNOSTIC"),
    )
    connection = FakeTenantConnection(events)

    with pytest.raises(TenantMigrationDdlError) as raised:
        runner.run(connection=connection, request=request)

    error = raised.value
    assert error.ddl_may_have_committed is True
    assert error.post_observation == _observation(SOURCE)
    assert error.lock_release_confirmed is True
    assert error.connection_must_close is False
    assert "UNTRUSTED_DDL_DIAGNOSTIC" not in str(error)
    assert "UNTRUSTED_DDL_DIAGNOSTIC" not in repr(error)
    assert error.__cause__ is None
    assert [event[0] for event in events] == [
        "get_lock",
        "observe",
        "fence",
        "apply",
        "observe",
        "release_lock",
    ]
    assert events[4] == (
        "observe",
        TenantMigrationObservationPhase.AFTER_FAILED_DDL,
    )


@pytest.mark.parametrize(
    "unexpected_target",
    [
        SOURCE,
        _identity(
            generation=9,
            revision="tenant-schema-009",
            digest=bytes.fromhex("55" * 32),
        ),
        _identity(
            generation=9,
            revision="tenant-schema-other",
            digest=TARGET_DIGEST,
        ),
        _identity(
            database_uuid=uuid4(),
            generation=9,
            revision="tenant-schema-009",
            digest=TARGET_DIGEST,
        ),
    ],
)
def test_runner_rejects_every_post_ddl_observation_other_than_exact_target(
    unexpected_target: FleetSchemaIdentity,
) -> None:
    runner, request, events = _runner_parts(
        observations=[_observation(SOURCE), _observation(unexpected_target)]
    )
    connection = FakeTenantConnection(events)

    with pytest.raises(TenantMigrationPostconditionError) as raised:
        runner.run(connection=connection, request=request)

    assert raised.value.ddl_may_have_committed is True
    assert raised.value.post_observation == _observation(unexpected_target)
    assert raised.value.lock_release_confirmed is True
    assert [event[0] for event in events][-1] == "release_lock"


@pytest.mark.parametrize("release_result", [0, None, False])
def test_success_survives_unconfirmed_release_and_requires_connection_close(
    release_result: object,
) -> None:
    runner, request, events = _runner_parts()
    connection = FakeTenantConnection(
        events,
        release_lock_result=release_result,
    )

    result = runner.run(connection=connection, request=request)

    assert result.final_observation == _observation(TARGET)
    assert result.advisory_lock_release_confirmed is False
    assert result.connection_must_close is True


def test_success_survives_sanitized_release_exception_and_requires_close() -> None:
    runner, request, events = _runner_parts()
    connection = FakeTenantConnection(
        events,
        release_lock_error=RuntimeError("UNTRUSTED_RELEASE_DIAGNOSTIC"),
    )

    result = runner.run(connection=connection, request=request)

    assert result.final_observation == _observation(TARGET)
    assert result.advisory_lock_release_confirmed is False
    assert result.connection_must_close is True


@pytest.mark.parametrize(
    ("phase", "expected_error", "partial", "expected_event_names"),
    [
        (
            TenantMigrationFencePhase.BEFORE_DDL,
            TenantMigrationFenceError,
            False,
            ["get_lock", "observe", "fence", "release_lock"],
        ),
        (
            TenantMigrationFencePhase.AFTER_DDL,
            TenantMigrationFenceError,
            True,
            [
                "get_lock",
                "observe",
                "fence",
                "apply",
                "fence",
                "observe",
                "release_lock",
            ],
        ),
    ],
)
def test_runner_holds_changed_shared_fence_before_or_after_ddl(
    phase: TenantMigrationFencePhase,
    expected_error: type[TenantMigrationFenceError],
    partial: bool,
    expected_event_names: list[str],
) -> None:
    observations = (
        [_observation(SOURCE), _observation(TARGET)]
        if partial
        else [_observation(SOURCE)]
    )
    runner, request, events = _runner_parts(
        observations=observations,
        fail_fence_phase=phase,
    )
    connection = FakeTenantConnection(events)

    with pytest.raises(expected_error) as raised:
        runner.run(connection=connection, request=request)

    assert raised.value.ddl_may_have_committed is partial
    assert raised.value.lock_release_confirmed is True
    assert "UNTRUSTED_FENCE_DIAGNOSTIC" not in str(raised.value)
    assert [event[0] for event in events] == expected_event_names
    if partial:
        assert raised.value.post_observation == _observation(TARGET)


def test_bundle_reference_digest_is_verified_before_get_lock() -> None:
    runner, request, events = _runner_parts()
    request = TenantMigrationRunRequest(
        migration_uuid=request.migration_uuid,
        operation_generation=request.operation_generation,
        schema_operation_fence=request.schema_operation_fence,
        bundle=TenantMigrationBundleReference(
            bundle_id=request.bundle.bundle_id,
            bundle_revision=request.bundle.bundle_revision,
            bundle_sha256=bytes.fromhex("99" * 32),
        ),
    )

    with pytest.raises(TenantMigrationPlanError):
        runner.run(connection=FakeTenantConnection(events), request=request)

    assert events == []


@pytest.mark.parametrize(
    "target",
    [
        _identity(
            generation=10,
            revision="tenant-schema-010",
            digest=TARGET_DIGEST,
        ),
        _identity(
            database_uuid=uuid4(),
            generation=9,
            revision="tenant-schema-009",
            digest=TARGET_DIGEST,
        ),
        _identity(
            generation=9,
            revision=SOURCE.schema_revision,
            digest=TARGET_DIGEST,
        ),
        _identity(
            generation=9,
            revision="tenant-schema-009",
            digest=SOURCE_DIGEST,
        ),
    ],
)
def test_bundle_must_be_exact_adjacent_version_locked_transition(
    target: FleetSchemaIdentity,
) -> None:
    with pytest.raises(TenantMigrationPlanError):
        VersionLockedTenantMigrationBundle(
            bundle_id="bad-bundle",
            bundle_revision="build-1",
            implementation_sha256=IMPLEMENTATION_DIGEST,
            source=SOURCE,
            target=target,
            apply=lambda connection, context: None,
        )


@pytest.mark.parametrize("timeout", [True, 0, -1, 31, 1.5, "5"])
def test_get_lock_timeout_is_bounded_integer(timeout: object) -> None:
    runner, _, events = _runner_parts()

    with pytest.raises(TenantMigrationPlanError):
        TenantMigrationRunner(
            bundle_registry=runner._bundle_registry,
            observer=runner._observer,
            fence_validator=runner._fence_validator,
            lock_timeout_seconds=timeout,  # type: ignore[arg-type]
        )

    assert events == []


def test_lock_name_is_bounded_opaque_and_stable_across_generations() -> None:
    selected = advisory_lock_name(DATABASE_UUID)
    same_database_next_generation = advisory_lock_name(TARGET.database_uuid)
    other_database = advisory_lock_name(uuid4())

    assert selected == same_database_next_generation
    assert selected != other_database
    assert selected.startswith("im:fm:")
    assert len(selected.encode("ascii")) <= MAX_ADVISORY_LOCK_NAME_LENGTH
    for forbidden in (
        str(TENANT_UUID),
        str(DATABASE_UUID),
        SOURCE.schema_revision,
        TARGET.schema_revision,
        "password",
        "schema",
    ):
        assert forbidden not in selected


def test_public_runner_request_has_no_sql_schema_dsn_or_secret_surface() -> None:
    request_fields = {selected.name for selected in fields(TenantMigrationRunRequest)}
    bundle_reference_fields = {
        selected.name for selected in fields(TenantMigrationBundleReference)
    }

    assert request_fields == {
        "migration_uuid",
        "operation_generation",
        "schema_operation_fence",
        "bundle",
    }
    assert bundle_reference_fields == {
        "bundle_id",
        "bundle_revision",
        "bundle_sha256",
    }
    assert not any(
        forbidden in field_name
        for field_name in request_fields | bundle_reference_fields
        for forbidden in ("sql", "schema_name", "dsn", "password", "secret")
    )
    with pytest.raises(TypeError):
        TenantMigrationRunRequest(  # type: ignore[call-arg]
            migration_uuid=MIGRATION_UUID,
            operation_generation=3,
            schema_operation_fence=FENCE,
            bundle=TenantMigrationBundleReference(
                bundle_id="bundle",
                bundle_revision="revision",
                bundle_sha256=bytes.fromhex("77" * 32),
            ),
            sql="ALTER TABLE customer_secret ...",
        )
