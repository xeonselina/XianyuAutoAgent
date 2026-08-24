from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase, ControlDatabase, Installation
from inventory_control.models.recovery import DisasterRecoveryRun
from inventory_control.operations import HostRecoveryMarker, HostRecoveryMarkerMode
from inventory_control.recovery import (
    StartupAuthorityError,
    StartupAuthorityService,
    StartupAuthorityTransactionError,
)


NOW = datetime(2026, 8, 22, 8, 0, tzinfo=timezone.utc)
INSTALLATION = "1" * 64
DEPLOYMENT_MARKER = "2" * 64


@pytest.fixture
def database(mysql_control_database):
    return mysql_control_database


def _marker(
    mode=HostRecoveryMarkerMode.NORMAL,
    *,
    installation=INSTALLATION,
    marker=DEPLOYMENT_MARKER,
):
    return HostRecoveryMarker(
        mode=mode,
        installation_fingerprint=installation,
        marker_fingerprint=marker,
    )


def _run(
    *,
    kind="initial_baseline",
    status="completed",
    installation=INSTALLATION,
    marker=DEPLOYMENT_MARKER,
):
    return DisasterRecoveryRun(
        id="00000000-0000-4000-8000-000000000011",
        kind=kind,
        policy_version=1,
        status=status,
        expected_survivor_count=0,
        actual_survivor_count=0,
        host_installation_fingerprint=installation,
        deployment_marker_fingerprint=marker,
        row_version=3,
        started_at=NOW - timedelta(hours=1),
        reviewing_at=(
            NOW - timedelta(minutes=30)
            if status in {"reviewing", "completed"}
            else None
        ),
        completed_at=NOW if status == "completed" else None,
        created_at=NOW - timedelta(hours=1),
        updated_at=NOW,
    )


def _seed(database, *, run=None, installation=INSTALLATION):
    with database.transaction() as session:
        session.add(
            Installation(
                id="00000000-0000-4000-8000-000000000010",
                marker_fingerprint=installation,
                row_version=1,
                created_at=NOW - timedelta(days=1),
            )
        )
        if run is not False:
            session.add(run or _run())


def test_initial_baseline_authorizes_only_exact_normal_marker(database):
    _seed(database)
    with database.transaction() as session:
        result = StartupAuthorityService().verify(session, marker=_marker())
        assert result.installation_uuid == "00000000-0000-4000-8000-000000000010"
        assert result.recovery_run_uuid == "00000000-0000-4000-8000-000000000011"
        assert result.recovery_kind == "initial_baseline"
        assert result.recovery_row_version == 3
        assert result.marker_mode is HostRecoveryMarkerMode.NORMAL
        assert not session.new and not session.dirty and not session.deleted


def test_completed_host_restore_requires_host_restore_marker_mode(database):
    _seed(database, run=_run(kind="host_restore"))
    with database.transaction() as session:
        result = StartupAuthorityService().verify(
            session,
            marker=_marker(HostRecoveryMarkerMode.HOST_RESTORE),
        )
        assert result.recovery_kind == "host_restore"

    with database.transaction() as session:
        with pytest.raises(
            StartupAuthorityError,
            match="STARTUP_MARKER_MODE_MISMATCH",
        ):
            StartupAuthorityService().verify(session, marker=_marker())


@pytest.mark.parametrize(
    ("run", "marker", "code"),
    [
        (False, _marker(), "STARTUP_RECOVERY_RUN_INVALID"),
        (_run(status="reviewing"), _marker(), "STARTUP_RECOVERY_NOT_COMPLETED"),
        (
            _run(installation="3" * 64),
            _marker(),
            "STARTUP_RECOVERY_INSTALLATION_MISMATCH",
        ),
        (
            _run(marker="4" * 64),
            _marker(),
            "STARTUP_DEPLOYMENT_MARKER_MISMATCH",
        ),
        (
            _run(),
            _marker(installation="5" * 64),
            "STARTUP_INSTALLATION_MISMATCH",
        ),
    ],
)
def test_mismatch_or_incomplete_recovery_fails_closed(database, run, marker, code):
    _seed(database, run=run)
    with database.transaction() as session:
        with pytest.raises(StartupAuthorityError, match=code):
            StartupAuthorityService().verify(session, marker=marker)


def test_missing_or_duplicate_live_installation_fails_closed(database):
    with database.transaction() as session:
        session.add(_run())
    with database.transaction() as session:
        with pytest.raises(
            StartupAuthorityError,
            match="STARTUP_INSTALLATION_INVALID",
        ):
            StartupAuthorityService().verify(session, marker=_marker())

    with database.transaction() as session:
        session.add_all(
            [
                Installation(marker_fingerprint=INSTALLATION, created_at=NOW),
                Installation(marker_fingerprint="6" * 64, created_at=NOW),
            ]
        )
    with database.transaction() as session:
        with pytest.raises(
            StartupAuthorityError,
            match="STARTUP_INSTALLATION_INVALID",
        ):
            StartupAuthorityService().verify(session, marker=_marker())


def test_retired_installation_does_not_count_as_live(database):
    with database.transaction() as session:
        session.add_all(
            [
                Installation(
                    marker_fingerprint="7" * 64,
                    retired_at=NOW - timedelta(days=1),
                    created_at=NOW - timedelta(days=2),
                ),
                Installation(
                    id="00000000-0000-4000-8000-000000000010",
                    marker_fingerprint=INSTALLATION,
                    created_at=NOW - timedelta(days=1),
                ),
                _run(),
            ]
        )
    with database.transaction() as session:
        result = StartupAuthorityService().verify(session, marker=_marker())
        assert result.installation_uuid == "00000000-0000-4000-8000-000000000010"


def test_verify_requires_clean_explicit_transaction(database):
    with database.new_session() as session:
        with pytest.raises(
            StartupAuthorityTransactionError,
            match="STARTUP_EXPLICIT_TRANSACTION_REQUIRED",
        ):
            StartupAuthorityService().verify(session, marker=_marker())

    with database.new_session() as session:
        session.scalar(sa.select(sa.literal(1)))
        with pytest.raises(
            StartupAuthorityTransactionError,
            match="STARTUP_EXPLICIT_TRANSACTION_REQUIRED",
        ):
            StartupAuthorityService().verify(session, marker=_marker())

    with database.new_session() as session:
        transaction = session.begin()
        session.add(Installation(marker_fingerprint=INSTALLATION))
        with pytest.raises(
            StartupAuthorityTransactionError,
            match="STARTUP_CLEAN_TRANSACTION_REQUIRED",
        ):
            StartupAuthorityService().verify(session, marker=_marker())
        transaction.rollback()


def test_invalid_marker_object_is_a_fixed_startup_rejection(database):
    _seed(database)
    with database.transaction() as session:
        with pytest.raises(
            StartupAuthorityError,
            match="STARTUP_MARKER_UNAVAILABLE",
        ):
            StartupAuthorityService().verify(session, marker=None)
