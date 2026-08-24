from contextlib import contextmanager
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session


NOW = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)
JOB = "a1000000-0000-4000-8000-000000000001"
TENANT = "a1000000-0000-4000-8000-000000000002"
INTEGRATION = "a1000000-0000-4000-8000-000000000003"
REVISION = "a1000000-0000-4000-8000-000000000004"
ROTATED_REVISION = "a1000000-0000-4000-8000-000000000005"


def test_sqlalchemy_store_carries_same_revision_cursor_and_applies_result(app):
    from app import db
    from app.models.xianyu_order_alert import XianyuConnectionSyncState
    from app.services.xianyu_sync import (
        PreparedXianyuSyncJob,
        SqlAlchemyXianyuTenantSyncStore,
        XianyuAlertFact,
        XianyuConnectionSyncResult,
    )
    from inventory_control.jobs import XianyuConnectionRevision

    with app.app_context():

        @contextmanager
        def transaction(_prepared):
            with Session(db.engine) as session:
                with session.begin():
                    yield session

        prepared = PreparedXianyuSyncJob(
            job_uuid=JOB,
            tenant_uuid=TENANT,
            tenant_access_version=1,
            connections=(
                XianyuConnectionRevision(
                    integration_uuid=INTEGRATION,
                    secret_revision_uuid=REVISION,
                    integration_row_version=1,
                    revision_row_version=1,
                ),
            ),
            request_id="request-1",
        )
        with Session(db.engine) as session:
            with session.begin():
                session.add(
                    XianyuConnectionSyncState(
                        integration_uuid=INTEGRATION,
                        secret_revision_uuid=REVISION,
                        provider_cursor="cursor-before",
                        sync_status="succeeded",
                        snapshot_revision=2,
                        row_version=1,
                        created_at=NOW.replace(tzinfo=None),
                        updated_at=NOW.replace(tzinfo=None),
                    )
                )

        store = SqlAlchemyXianyuTenantSyncStore(transaction)
        started = store.mark_started(prepared=prepared, attempted_at=NOW)
        assert started.provider_cursors[INTEGRATION] == "cursor-before"
        applied = store.apply_results(
            prepared=prepared,
            completed_at=NOW + timedelta(seconds=1),
            results=(
                XianyuConnectionSyncResult(
                    integration_uuid=INTEGRATION,
                    secret_revision_uuid=REVISION,
                    status="succeeded",
                    alerts=(XianyuAlertFact(order_no="ORDER-1", pay_amount=6000),),
                    provider_cursor="cursor-after",
                ),
            ),
        )

        assert applied.snapshot_revision == 1
        with Session(db.engine) as session:
            state = session.get(XianyuConnectionSyncState, INTEGRATION)
            assert state.provider_cursor == "cursor-after"
            assert state.snapshot_revision == 3


def test_sqlalchemy_store_does_not_return_cursor_across_revision_rotation(app):
    from app import db
    from app.models.xianyu_order_alert import XianyuConnectionSyncState
    from app.services.xianyu_sync import (
        PreparedXianyuSyncJob,
        SqlAlchemyXianyuTenantSyncStore,
    )
    from inventory_control.jobs import XianyuConnectionRevision

    with app.app_context():

        @contextmanager
        def transaction(_prepared):
            with Session(db.engine) as session:
                with session.begin():
                    yield session

        with Session(db.engine) as session:
            with session.begin():
                session.add(
                    XianyuConnectionSyncState(
                        integration_uuid=INTEGRATION,
                        secret_revision_uuid=REVISION,
                        provider_cursor="cursor-from-old-revision",
                        sync_status="succeeded",
                        snapshot_revision=2,
                        row_version=1,
                        created_at=NOW.replace(tzinfo=None),
                        updated_at=NOW.replace(tzinfo=None),
                    )
                )
        prepared = PreparedXianyuSyncJob(
            job_uuid=JOB,
            tenant_uuid=TENANT,
            tenant_access_version=1,
            connections=(
                XianyuConnectionRevision(
                    integration_uuid=INTEGRATION,
                    secret_revision_uuid=ROTATED_REVISION,
                    integration_row_version=2,
                    revision_row_version=1,
                ),
            ),
            request_id="request-2",
        )

        started = SqlAlchemyXianyuTenantSyncStore(transaction).mark_started(
            prepared=prepared,
            attempted_at=NOW,
        )

        assert started.provider_cursors[INTEGRATION] is None
        with Session(db.engine) as session:
            state = session.get(XianyuConnectionSyncState, INTEGRATION)
            assert state.secret_revision_uuid == ROTATED_REVISION
            assert state.provider_cursor is None
