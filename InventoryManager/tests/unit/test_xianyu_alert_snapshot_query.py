from datetime import datetime, timedelta, timezone

import pytest


NOW = datetime(2026, 8, 23, 1, 0, tzinfo=timezone.utc)


@pytest.fixture
def app():
    from app import create_app

    return create_app("testing")


@pytest.fixture
def session(app):
    from app import db

    with app.app_context():
        db.create_all()
        value = db.session()
        yield value
        value.rollback()
        db.drop_all()


def test_snapshot_is_local_revisioned_and_stale_after_two_cycles(session):
    from app.models.xianyu_order_alert import (
        XianyuConnectionSyncState,
        XianyuOrderAlert,
        XianyuOrderSyncState,
    )
    from app.services.xianyu_sync import XianyuAlertSnapshotQueryService

    with session.begin():
        session.add_all(
            (
                XianyuOrderAlert(
                    order_no="LOCAL-ONLY",
                    state="pending",
                    pay_amount=6000,
                ),
                XianyuOrderSyncState(
                    id=1,
                    snapshot_revision=8,
                    sync_status="partial_failure",
                    last_success_at=(NOW - timedelta(seconds=361)).replace(
                        tzinfo=None
                    ),
                    last_error="部分闲鱼连接同步失败",
                ),
                XianyuConnectionSyncState(
                    integration_uuid=(
                        "71000000-0000-4000-8000-000000000001"
                    ),
                    secret_revision_uuid=(
                        "72000000-0000-4000-8000-000000000001"
                    ),
                    sync_status="failed",
                    safe_error_code="PROVIDER_UNAVAILABLE",
                ),
            )
        )

    snapshot = XianyuAlertSnapshotQueryService(session).get_snapshot(
        database_now=NOW
    )

    assert snapshot["count"] == 1
    assert snapshot["alerts"][0]["order_no"] == "LOCAL-ONLY"
    assert snapshot["snapshot_revision"] == 8
    assert snapshot["sync_status"] == "partial_failure"
    assert snapshot["stale"] is True
    assert snapshot["refreshing"] is False
    assert snapshot["connection_statuses"] == [
        {
            "integration_uuid": "71000000-0000-4000-8000-000000000001",
            "sync_status": "failed",
            "last_successful_sync_at": None,
            "safe_error_code": "PROVIDER_UNAVAILABLE",
            "retry_after_at": None,
        }
    ]
    session.rollback()


def test_snapshot_marks_current_durable_job_as_refreshing(session):
    from app.models.xianyu_order_alert import XianyuOrderSyncState
    from app.services.xianyu_sync import XianyuAlertSnapshotQueryService

    with session.begin():
        session.add(
            XianyuOrderSyncState(
                id=1,
                snapshot_revision=2,
                sync_status="syncing",
                current_job_uuid="73000000-0000-4000-8000-000000000001",
                last_success_at=NOW.replace(tzinfo=None),
            )
        )

    snapshot = XianyuAlertSnapshotQueryService(session).get_snapshot(
        database_now=NOW
    )

    assert snapshot["refreshing"] is True
    assert snapshot["stale"] is False
    assert XianyuAlertSnapshotQueryService(session).get_snapshot_revision() == 2
    session.rollback()


def test_ignore_is_caller_transactional_and_never_calls_provider(session):
    from app.models.xianyu_order_alert import XianyuOrderAlert
    from app.services.xianyu_sync import XianyuAlertSnapshotQueryService

    with session.begin():
        session.add(
            XianyuOrderAlert(
                order_no="IGNORE-LOCAL",
                state="pending",
                pay_amount=7000,
            )
        )
    with session.begin():
        XianyuAlertSnapshotQueryService(session).ignore(
            order_no="IGNORE-LOCAL",
            reason="非租赁商品",
            ignored_at=NOW,
        )

    alert = session.query(XianyuOrderAlert).one()
    assert alert.state == "ignored"
    assert alert.ignored_reason == "非租赁商品"
    session.rollback()
