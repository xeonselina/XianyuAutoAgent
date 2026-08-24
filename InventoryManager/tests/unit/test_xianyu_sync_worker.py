from datetime import datetime, timezone

import pytest

from app.services.xianyu_sync import (
    XianyuAlertFact,
    XianyuProviderSettings,
    XianyuProviderSyncResponse,
    XianyuSyncApplyResult,
    XianyuSyncJobHandler,
    XianyuSyncStart,
)
from inventory_control.integrations import (
    XianyuSyncCredentialError,
    XianyuSyncExecutionContext,
    XianyuSyncProviderRequest,
)
from inventory_control.jobs import (
    AuthorityVerdict,
    OutcomeDisposition,
    XIAN_YU_RESOURCE_KEY,
    XIAN_YU_SCHEDULED_JOB_TYPE,
    XianyuConnectionRevision,
    xianyu_connection_set_digest,
)
from inventory_control.models.jobs import BackgroundJob


NOW = datetime(2026, 8, 23, 0, 0, tzinfo=timezone.utc)
TENANT = "91000000-0000-4000-8000-000000000001"
JOB = "91000000-0000-4000-8000-000000000002"
CONNECTIONS = (
    XianyuConnectionRevision(
        integration_uuid="92000000-0000-4000-8000-000000000001",
        secret_revision_uuid="93000000-0000-4000-8000-000000000001",
        integration_row_version=4,
        revision_row_version=3,
    ),
    XianyuConnectionRevision(
        integration_uuid="92000000-0000-4000-8000-000000000002",
        secret_revision_uuid="93000000-0000-4000-8000-000000000002",
        integration_row_version=7,
        revision_row_version=5,
    ),
)
SETTINGS = XianyuProviderSettings(
    endpoint="https://open.goofish.pro",
    connect_timeout_seconds=3,
    read_timeout_seconds=15,
    rate_limit_retry_seconds=45,
    page_size=100,
    max_pages=20,
)


def _job(*, digest=None):
    return BackgroundJob(
        id=JOB,
        tenant_id=TENANT,
        tenant_access_version=9,
        job_type=XIAN_YU_SCHEDULED_JOB_TYPE,
        resource_key=XIAN_YU_RESOURCE_KEY,
        payload={
            "contract_version": 1,
            "bucket_started_at": "2026-08-23T00:00:00Z",
            "connection_set_digest": digest
            or xianyu_connection_set_digest(CONNECTIONS),
            "connections": [
                {
                    "integration_uuid": item.integration_uuid,
                    "secret_revision_uuid": item.secret_revision_uuid,
                    "integration_row_version": item.integration_row_version,
                    "revision_row_version": item.revision_row_version,
                }
                for item in CONNECTIONS
            ],
        },
        idempotency_key="xianyu:test",
        requested_by_type="scheduler",
        priority=10,
        status="leased",
        attempts=1,
        max_attempts=3,
        execution_generation=2,
        available_at=NOW,
        lease_owner="worker-1",
        lease_token="lease-1",
        lease_expires_at=NOW,
    )


class Store:
    def __init__(self, *, already_applied=False):
        self.already_applied = already_applied
        self.started = []
        self.applied = []

    def mark_started(self, *, prepared, attempted_at):
        self.started.append((prepared, attempted_at))
        return XianyuSyncStart(
            already_applied=self.already_applied,
            provider_cursors={
                CONNECTIONS[0].integration_uuid: "cursor-1",
                CONNECTIONS[1].integration_uuid: None,
            },
        )

    def apply_results(self, *, prepared, results, completed_at):
        self.applied.append((prepared, results, completed_at))
        return XianyuSyncApplyResult(
            snapshot_revision=12,
            sync_status="succeeded",
            applied=True,
        )


class Credentials:
    def __init__(self, unavailable=()):
        self.unavailable = frozenset(unavailable)
        self.calls = []

    def prepare(self, *, job, connection, provider_cursor):
        self.calls.append((job, connection, provider_cursor))
        if connection.integration_uuid in self.unavailable:
            raise XianyuSyncCredentialError()
        return XianyuSyncProviderRequest(
            context=XianyuSyncExecutionContext(
                tenant_uuid=job.tenant_uuid,
                integration_uuid=connection.integration_uuid,
                secret_revision_uuid=connection.secret_revision_uuid,
                integration_row_version=connection.integration_row_version,
                revision_row_version=connection.revision_row_version,
            ),
            provider_cursor=provider_cursor,
            credentials={"app_key": "app", "app_secret": "secret"},
        )


class Adapter:
    def __init__(self):
        self.calls = []

    def fetch_alerts(self, *, request, settings):
        self.calls.append(
            (
                request.context.integration_uuid,
                request.provider_cursor,
                dict(request.take_credentials()),
                settings,
            )
        )
        return XianyuProviderSyncResponse(
            alerts=(
                XianyuAlertFact(
                    order_no=f"ORDER-{len(self.calls)}",
                    pay_amount=6000,
                ),
            ),
            next_cursor=f"cursor-next-{len(self.calls)}",
        )


class Authorizer:
    def __init__(self, verdicts=()):
        self.verdicts = list(verdicts)
        self.calls = []

    def authorize(self, job):
        self.calls.append(job.id)
        if self.verdicts:
            return self.verdicts.pop(0)
        return AuthorityVerdict(True)


def _handler(*, store=None, credentials=None, adapter=None, authorizer=None):
    return XianyuSyncJobHandler(
        tenant_store=store or Store(),
        credential_source=credentials or Credentials(),
        provider_adapter=adapter or Adapter(),
        provider_settings=SETTINGS,
        call_authorizer=authorizer or Authorizer(),
        clock=lambda: NOW,
    )


def test_handler_rechecks_and_dispatches_each_connection_independently():
    store = Store()
    credentials = Credentials()
    adapter = Adapter()
    authorizer = Authorizer()
    handler = _handler(
        store=store,
        credentials=credentials,
        adapter=adapter,
        authorizer=authorizer,
    )
    job = _job()

    outcome = handler.execute(job, handler.prepare(job))

    assert outcome.disposition is OutcomeDisposition.SUCCEEDED
    assert authorizer.calls == [JOB, JOB]
    assert [call[1] for call in credentials.calls] == list(CONNECTIONS)
    assert [call[2] for call in credentials.calls] == ["cursor-1", None]
    assert [call[0] for call in adapter.calls] == [
        connection.integration_uuid for connection in CONNECTIONS
    ]
    persisted = store.applied[0][1]
    assert [result.status for result in persisted] == ["succeeded", "succeeded"]
    assert outcome.safe_result == {
        "snapshot_revision": 12,
        "connection_count": 2,
        "succeeded_connections": 2,
        "failed_connections": 0,
    }


def test_authority_denial_stops_remaining_provider_calls_and_enters_review():
    store = Store()
    adapter = Adapter()
    authorizer = Authorizer(
        (AuthorityVerdict(True), AuthorityVerdict(False, "tenant_suspended"))
    )
    handler = _handler(store=store, adapter=adapter, authorizer=authorizer)
    job = _job()

    outcome = handler.execute(job, handler.prepare(job))

    assert outcome.disposition is OutcomeDisposition.REVIEW
    assert outcome.reason_code == "tenant_suspended"
    assert len(adapter.calls) == 1
    results = store.applied[0][1]
    assert [result.status for result in results] == ["succeeded", "failed"]
    assert results[1].safe_error_code == "TENANT_AUTHORITY_DENIED"


def test_stale_credential_fails_only_its_connection_without_provider_call():
    store = Store()
    credentials = Credentials(unavailable=(CONNECTIONS[0].integration_uuid,))
    adapter = Adapter()
    handler = _handler(store=store, credentials=credentials, adapter=adapter)
    job = _job()

    outcome = handler.execute(job, handler.prepare(job))

    assert outcome.disposition is OutcomeDisposition.SUCCEEDED
    assert len(adapter.calls) == 1
    results = store.applied[0][1]
    assert results[0].safe_error_code == "CREDENTIAL_UNAVAILABLE"
    assert results[1].status == "succeeded"


def test_idempotent_tenant_result_skips_all_provider_calls():
    store = Store(already_applied=True)
    adapter = Adapter()
    authorizer = Authorizer()
    handler = _handler(store=store, adapter=adapter, authorizer=authorizer)
    job = _job()

    outcome = handler.execute(job, handler.prepare(job))

    assert outcome.disposition is OutcomeDisposition.SUCCEEDED
    assert outcome.safe_result == {"idempotent_replay": True}
    assert authorizer.calls == []
    assert adapter.calls == []
    assert store.applied == []


def test_prepare_rejects_tampered_connection_digest():
    with pytest.raises(ValueError, match="digest"):
        _handler().prepare(_job(digest="0" * 32))
