from datetime import datetime, timedelta, timezone

import pytest
import sqlalchemy as sa


JOB = "10000000-0000-4000-8000-000000000001"
SUCCESS_CONNECTION = "20000000-0000-4000-8000-000000000001"
SUCCESS_REVISION = "30000000-0000-4000-8000-000000000001"
FAILED_CONNECTION = "20000000-0000-4000-8000-000000000002"
FAILED_REVISION = "30000000-0000-4000-8000-000000000002"
NOW = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)


@pytest.fixture
def session(db_session):
    return db_session()


def _refs():
    from app.services.xianyu_sync import XianyuConnectionRef

    return (
        XianyuConnectionRef(SUCCESS_CONNECTION, SUCCESS_REVISION),
        XianyuConnectionRef(FAILED_CONNECTION, FAILED_REVISION),
    )


def test_multi_connection_result_is_independent_and_revision_is_aggregate(session):
    from app.models.xianyu_order_alert import (
        XianyuConnectionSyncState,
        XianyuOrderAlert,
        XianyuOrderSyncState,
    )
    from app.services.xianyu_sync import (
        XianyuAlertFact,
        XianyuConnectionSyncResult,
        XianyuSyncPersistenceService,
    )

    with session.begin():
        session.add(
            XianyuOrderAlert(
                integration_uuid=FAILED_CONNECTION,
                secret_revision_uuid=FAILED_REVISION,
                order_no="FAILED-CONNECTION-CACHED",
                state="pending",
                pay_amount=9000,
                first_detected_at=NOW.replace(tzinfo=None),
                last_seen_at=NOW.replace(tzinfo=None),
            )
        )
    with session.begin():
        started = XianyuSyncPersistenceService(session).mark_started(
            job_uuid=JOB,
            connections=_refs(),
            attempted_at=NOW,
        )
    assert started.snapshot_revision == 0
    assert started.sync_status == "syncing"

    with session.begin():
        applied = XianyuSyncPersistenceService(session).apply_results(
            job_uuid=JOB,
            completed_at=NOW + timedelta(seconds=3),
            results=(
                XianyuConnectionSyncResult(
                    integration_uuid=SUCCESS_CONNECTION,
                    secret_revision_uuid=SUCCESS_REVISION,
                    status="succeeded",
                    provider_cursor="cursor-next",
                    alerts=(
                        XianyuAlertFact(
                            order_no="NEW-SUCCESS",
                            pay_amount=8800,
                            receiver_mobile="13800138000",
                        ),
                    ),
                ),
                XianyuConnectionSyncResult(
                    integration_uuid=FAILED_CONNECTION,
                    secret_revision_uuid=FAILED_REVISION,
                    status="failed",
                    safe_error_code="PROVIDER_UNAVAILABLE",
                ),
            ),
        )

    assert applied.snapshot_revision == 1
    assert applied.sync_status == "partial_failure"
    aggregate = session.get(XianyuOrderSyncState, 1)
    states = {
        state.integration_uuid: state
        for state in session.scalars(
            sa.select(XianyuConnectionSyncState).order_by(
                XianyuConnectionSyncState.integration_uuid
            )
        )
    }
    alerts = {
        alert.order_no: alert for alert in session.scalars(sa.select(XianyuOrderAlert))
    }
    assert aggregate.current_job_uuid is None
    assert aggregate.last_applied_job_uuid == JOB
    assert states[SUCCESS_CONNECTION].sync_status == "succeeded"
    assert states[SUCCESS_CONNECTION].snapshot_revision == 1
    assert states[SUCCESS_CONNECTION].provider_cursor == "cursor-next"
    assert states[FAILED_CONNECTION].sync_status == "failed"
    assert states[FAILED_CONNECTION].snapshot_revision == 0
    assert states[FAILED_CONNECTION].safe_error_code == "PROVIDER_UNAVAILABLE"
    assert set(alerts) == {"NEW-SUCCESS", "FAILED-CONNECTION-CACHED"}
    assert alerts["FAILED-CONNECTION-CACHED"].integration_uuid == FAILED_CONNECTION
    session.rollback()


def test_failed_result_preserves_last_successful_provider_cursor(session):
    from app.models.xianyu_order_alert import XianyuConnectionSyncState
    from app.services.xianyu_sync import (
        XianyuConnectionRef,
        XianyuConnectionSyncResult,
        XianyuSyncPersistenceService,
    )

    with session.begin():
        session.add(
            XianyuConnectionSyncState(
                integration_uuid=SUCCESS_CONNECTION,
                secret_revision_uuid=SUCCESS_REVISION,
                provider_cursor="cursor-stable",
                sync_status="succeeded",
                snapshot_revision=4,
                row_version=1,
                created_at=NOW.replace(tzinfo=None),
                updated_at=NOW.replace(tzinfo=None),
            )
        )
    with session.begin():
        XianyuSyncPersistenceService(session).mark_started(
            job_uuid=JOB,
            connections=(XianyuConnectionRef(SUCCESS_CONNECTION, SUCCESS_REVISION),),
            attempted_at=NOW,
        )
    with session.begin():
        XianyuSyncPersistenceService(session).apply_results(
            job_uuid=JOB,
            completed_at=NOW + timedelta(seconds=1),
            results=(
                XianyuConnectionSyncResult(
                    integration_uuid=SUCCESS_CONNECTION,
                    secret_revision_uuid=SUCCESS_REVISION,
                    status="failed",
                    safe_error_code="PROVIDER_UNAVAILABLE",
                ),
            ),
        )

    state = session.get(XianyuConnectionSyncState, SUCCESS_CONNECTION)
    assert state.provider_cursor == "cursor-stable"
    assert state.snapshot_revision == 4
    session.rollback()


def test_credential_revision_change_clears_old_provider_cursor(session):
    from app.models.xianyu_order_alert import XianyuConnectionSyncState
    from app.services.xianyu_sync import (
        XianyuConnectionRef,
        XianyuConnectionSyncResult,
        XianyuSyncPersistenceService,
    )

    rotated_revision = "30000000-0000-4000-8000-000000000099"
    with session.begin():
        session.add(
            XianyuConnectionSyncState(
                integration_uuid=SUCCESS_CONNECTION,
                secret_revision_uuid=SUCCESS_REVISION,
                provider_cursor="cursor-from-old-credential",
                sync_status="succeeded",
                snapshot_revision=2,
                row_version=1,
                created_at=NOW.replace(tzinfo=None),
                updated_at=NOW.replace(tzinfo=None),
            )
        )
    with session.begin():
        XianyuSyncPersistenceService(session).mark_started(
            job_uuid=JOB,
            connections=(XianyuConnectionRef(SUCCESS_CONNECTION, rotated_revision),),
            attempted_at=NOW,
        )
    with session.begin():
        XianyuSyncPersistenceService(session).apply_results(
            job_uuid=JOB,
            completed_at=NOW + timedelta(seconds=1),
            results=(
                XianyuConnectionSyncResult(
                    integration_uuid=SUCCESS_CONNECTION,
                    secret_revision_uuid=rotated_revision,
                    status="failed",
                    safe_error_code="PROVIDER_UNAVAILABLE",
                ),
            ),
        )

    state = session.get(XianyuConnectionSyncState, SUCCESS_CONNECTION)
    assert state.secret_revision_uuid == rotated_revision
    assert state.provider_cursor is None
    session.rollback()


def test_replaying_same_job_does_not_replace_alerts_or_increment_revision(session):
    from app.models.xianyu_order_alert import XianyuOrderAlert
    from app.services.xianyu_sync import (
        XianyuAlertFact,
        XianyuConnectionRef,
        XianyuConnectionSyncResult,
        XianyuSyncPersistenceService,
    )

    refs = (XianyuConnectionRef(SUCCESS_CONNECTION, SUCCESS_REVISION),)
    first_result = (
        XianyuConnectionSyncResult(
            integration_uuid=SUCCESS_CONNECTION,
            secret_revision_uuid=SUCCESS_REVISION,
            status="succeeded",
            alerts=(XianyuAlertFact(order_no="FIRST", pay_amount=7000),),
        ),
    )
    with session.begin():
        service = XianyuSyncPersistenceService(session)
        service.mark_started(job_uuid=JOB, connections=refs, attempted_at=NOW)
    with session.begin():
        first = XianyuSyncPersistenceService(session).apply_results(
            job_uuid=JOB,
            results=first_result,
            completed_at=NOW,
        )
    with session.begin():
        replay = XianyuSyncPersistenceService(session).apply_results(
            job_uuid=JOB,
            results=(
                XianyuConnectionSyncResult(
                    integration_uuid=SUCCESS_CONNECTION,
                    secret_revision_uuid=SUCCESS_REVISION,
                    status="succeeded",
                    alerts=(
                        XianyuAlertFact(order_no="SHOULD-NOT-APPLY", pay_amount=1),
                    ),
                ),
            ),
            completed_at=NOW + timedelta(minutes=1),
        )

    assert first.snapshot_revision == 1
    assert replay.snapshot_revision == 1
    assert replay.applied is False
    assert list(session.scalars(sa.select(XianyuOrderAlert.order_no))) == ["FIRST"]
    session.rollback()


def test_incomplete_connection_result_set_fails_closed(session):
    from app.models.xianyu_order_alert import XianyuOrderSyncState
    from app.services.xianyu_sync import (
        XianyuConnectionSyncResult,
        XianyuSyncConflict,
        XianyuSyncPersistenceService,
    )

    with session.begin():
        XianyuSyncPersistenceService(session).mark_started(
            job_uuid=JOB,
            connections=_refs(),
            attempted_at=NOW,
        )
    with pytest.raises(XianyuSyncConflict, match="incomplete"):
        with session.begin():
            XianyuSyncPersistenceService(session).apply_results(
                job_uuid=JOB,
                results=(
                    XianyuConnectionSyncResult(
                        integration_uuid=SUCCESS_CONNECTION,
                        secret_revision_uuid=SUCCESS_REVISION,
                        status="succeeded",
                    ),
                ),
                completed_at=NOW,
            )

    aggregate = session.get(XianyuOrderSyncState, 1)
    assert aggregate.snapshot_revision == 0
    assert aggregate.current_job_uuid == JOB
    session.rollback()


def test_started_revision_cannot_change_when_result_is_applied(session):
    from app.services.xianyu_sync import (
        XianyuConnectionRef,
        XianyuConnectionSyncResult,
        XianyuSyncConflict,
        XianyuSyncPersistenceService,
    )

    with session.begin():
        XianyuSyncPersistenceService(session).mark_started(
            job_uuid=JOB,
            connections=(XianyuConnectionRef(SUCCESS_CONNECTION, SUCCESS_REVISION),),
            attempted_at=NOW,
        )
    with pytest.raises(XianyuSyncConflict, match="revision"):
        with session.begin():
            XianyuSyncPersistenceService(session).apply_results(
                job_uuid=JOB,
                results=(
                    XianyuConnectionSyncResult(
                        integration_uuid=SUCCESS_CONNECTION,
                        secret_revision_uuid=("30000000-0000-4000-8000-000000000099"),
                        status="succeeded",
                    ),
                ),
                completed_at=NOW,
            )


def test_service_requires_caller_owned_transaction(session):
    from app.services.xianyu_sync import (
        XianyuConnectionRef,
        XianyuSyncPersistenceService,
    )

    assert session.in_transaction() is False
    with pytest.raises(RuntimeError, match="explicit tenant transaction"):
        XianyuSyncPersistenceService(session).mark_started(
            job_uuid=JOB,
            connections=(XianyuConnectionRef(SUCCESS_CONNECTION, SUCCESS_REVISION),),
            attempted_at=NOW,
        )


def test_result_without_matching_started_job_is_rejected(session):
    from app.services.xianyu_sync import (
        XianyuConnectionSyncResult,
        XianyuSyncConflict,
        XianyuSyncPersistenceService,
    )

    with pytest.raises(XianyuSyncConflict, match="active Xianyu job"):
        with session.begin():
            XianyuSyncPersistenceService(session).apply_results(
                job_uuid=JOB,
                results=(
                    XianyuConnectionSyncResult(
                        integration_uuid=SUCCESS_CONNECTION,
                        secret_revision_uuid=SUCCESS_REVISION,
                        status="succeeded",
                    ),
                ),
                completed_at=NOW,
            )


def test_sensitive_alert_repr_is_redacted():
    from app.services.xianyu_sync import XianyuAlertFact

    fact = XianyuAlertFact(
        order_no="SECRET-ORDER-NO",
        pay_amount=8888,
        receiver_mobile="13800138000",
        address="不应出现在日志里的地址",
    )

    assert repr(fact) == "XianyuAlertFact(<redacted>)"


def test_sync_result_repr_redacts_provider_cursor():
    from app.services.xianyu_sync import XianyuConnectionSyncResult

    result = XianyuConnectionSyncResult(
        integration_uuid=SUCCESS_CONNECTION,
        secret_revision_uuid=SUCCESS_REVISION,
        status="succeeded",
        provider_cursor="sensitive-cursor",
    )

    assert "sensitive-cursor" not in repr(result)
