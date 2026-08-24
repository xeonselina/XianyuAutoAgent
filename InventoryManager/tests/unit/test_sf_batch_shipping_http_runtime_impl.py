from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
import os
from types import SimpleNamespace

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental
from app.models.shipping_execution import (
    OutboundShipment,
    ProviderOperationAttempt,
)
from app.models.warehouse import Warehouse, WarehouseProviderBinding
from app.services.shipping import batch_http_runtime as runtime_module
from app.services.shipping.batch_http_runtime import (
    SfBatchShippingRejected,
    SqlAlchemySfBatchShippingHttpRuntime,
)
from app.services.tenant_business.http_runtime import (
    TenantBusinessRequestScope,
)
from inventory_control import ControlDatabase
from inventory_control.domain import EffectiveTenantGate, TenantRole
from inventory_control.identity import SessionService
from inventory_control.integrations import SfProviderExecutionContext
from inventory_control.tenant_http import AuthContext, TenantHttpBoundary
from tests.support.test_database import (
    build_mysql_test_config,
    guarded_mysql_test_metadata,
)


NOW = datetime(2026, 8, 23, 9, tzinfo=timezone.utc)
TENANT_UUID = "11111111-1111-4111-8111-111111111111"
USER_UUID = "22222222-2222-4222-8222-222222222222"
REQUEST_UUID = "33333333-3333-4333-8333-333333333333"
ACCOUNT_UUID = "44444444-4444-4444-8444-444444444444"
INTEGRATION_UUID = "55555555-5555-4555-8555-555555555555"
INTEGRATION_REVISION_UUID = "66666666-6666-4666-8666-666666666666"
ACCOUNT_REVISION_UUID = "77777777-7777-4777-8777-777777777777"
CLAIM_UUID = "88888888-8888-4888-8888-888888888888"


class _TenantBusinessRuntime:
    def __init__(self, engine, auth):
        self.engine = engine
        self.auth = auth

    @contextmanager
    def tenant_session(self, *, after_authorize=None, **_kwargs):
        if after_authorize is not None:
            after_authorize(self.auth)
        with Session(
            self.engine,
            autoflush=False,
            expire_on_commit=False,
        ) as tenant_session:
            yield TenantBusinessRequestScope(
                auth_context=self.auth,
                request_id="sf-batch-schedule:test",
                database_now=NOW,
                tenant_session=tenant_session,
            )


class _Resolver:
    calls = []

    def __init__(self, _session):
        pass

    def resolve_current(self, **kwargs):
        self.calls.append(kwargs)
        return SfProviderExecutionContext(
            tenant_uuid=kwargs["tenant_uuid"],
            warehouse_uuid=kwargs["warehouse_uuid"],
            provider_account_uuid=kwargs["provider_account_uuid"],
            integration_uuid=INTEGRATION_UUID,
            integration_secret_revision_uuid=INTEGRATION_REVISION_UUID,
            provider_account_secret_revision_uuid=ACCOUNT_REVISION_UUID,
            global_claim_uuid=CLAIM_UUID,
            claim_generation=1,
            binding_revision=kwargs["binding_revision"],
            masked_account_hint="****1234",
        )


class _Enqueuer:
    calls = []

    def __init__(self, *, control_database):
        assert isinstance(control_database, ControlDatabase)

    def enqueue(self, *, signal, available_at):
        self.calls.append((signal, available_at))
        return SimpleNamespace(id=signal.job_uuid)


@pytest.fixture
def runtime_harness(monkeypatch):
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.fail("TEST_DATABASE_URL is required for database tests")
    app = create_app(build_mysql_test_config())
    with app.app_context():
        engine = db.engine
        with guarded_mysql_test_metadata(engine, db.metadata):
            with Session(engine) as session, session.begin():
                warehouse = Warehouse(
                    name="测试仓",
                    status="active",
                    setup_state="ready",
                    is_default=True,
                    default_slot=1,
                    contact_name="仓库联系人",
                    contact_phone="13800138000",
                    province="仓库省",
                    city="仓库市",
                    district="仓库区",
                    address_detail="仓库路 1 号",
                )
                device = Device(
                    name="主设备",
                    model="x300u",
                    is_accessory=False,
                    warehouse=warehouse,
                )
                rental = Rental(
                    device=device,
                    start_date=date(2026, 9, 1),
                    end_date=date(2026, 9, 3),
                    customer_name="客户",
                    customer_phone="13900139000",
                    customer_province="客户省",
                    customer_city="客户市",
                    customer_district="客户区",
                    customer_address_detail="客户路 2 号",
                    express_type_id=2,
                    status="not_shipped",
                )
                session.add_all((warehouse, device, rental))
                session.flush()
                session.add(WarehouseProviderBinding(
                    warehouse_id=warehouse.id,
                    provider="sf",
                    provider_account_uuid=ACCOUNT_UUID,
                    binding_revision=1,
                    status="active",
                    verified_at=NOW.replace(tzinfo=None),
                    bound_by=USER_UUID,
                ))
                rental_id = rental.id

            auth = AuthContext(
                session_id="99999999-9999-4999-8999-999999999999",
                user_id=USER_UUID,
                membership_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
                tenant_id=TENANT_UUID,
                role=TenantRole.OPERATOR,
                user_auth_version=1,
                tenant_access_version=3,
                tenant_timezone="Asia/Shanghai",
                effective_gate=EffectiveTenantGate.ACTIVE,
            )
            tenant_runtime = _TenantBusinessRuntime(engine, auth)
            control_database = ControlDatabase.from_url(
                os.environ["TEST_DATABASE_URL"]
            )
            boundary = TenantHttpBoundary(
                SessionService(gate_current_read=lambda *_args, **_kwargs: None)
            )
            _Resolver.calls = []
            _Enqueuer.calls = []
            monkeypatch.setattr(
                runtime_module,
                "SfProviderContextResolver",
                _Resolver,
            )
            monkeypatch.setattr(
                runtime_module,
                "SqlAlchemySfWaybillIntentEnqueuer",
                _Enqueuer,
            )
            runtime = SqlAlchemySfBatchShippingHttpRuntime(
                control_database=control_database,
                tenant_http_boundary=boundary,
                tenant_business_runtime=tenant_runtime,
            )
            try:
                yield runtime, engine, rental_id
            finally:
                control_database.dispose()
                db.session.remove()


def _payload(rental_id, *, scheduled_time="2026-08-24T09:00:00+08:00"):
    return {
        "request_uuid": REQUEST_UUID,
        "rental_ids": [rental_id, rental_id],
        "scheduled_time": scheduled_time,
    }


def test_runtime_persists_exact_intent_enqueues_and_replays_response_loss(
    runtime_harness,
):
    runtime, engine, rental_id = runtime_harness

    first = runtime.schedule_shipments(
        flask_request=object(),
        payload=_payload(rental_id),
    )
    replay = runtime.schedule_shipments(
        flask_request=object(),
        payload=_payload(rental_id),
    )

    assert first["accepted_count"] == replay["accepted_count"] == 1
    assert first["items"] == replay["items"]
    assert first["items"][0]["job_enqueued"] is True
    assert len(_Resolver.calls) == 1
    assert len(_Enqueuer.calls) == 2
    assert _Enqueuer.calls[0][0].job_uuid == _Enqueuer.calls[1][0].job_uuid

    with Session(engine) as session:
        shipment = session.scalar(sa.select(OutboundShipment))
        attempt = session.scalar(sa.select(ProviderOperationAttempt))
        assert shipment.scheduled_dispatch_at == datetime(2026, 8, 24, 1)
        assert shipment.cargo_snapshot == {
            "items": [{"name": "x300u", "count": 1}]
        }
        assert shipment.receiver_snapshot["contact_name"] == "客户"
        assert attempt.background_job_uuid == first["items"][0]["job_uuid"]
        assert attempt.tenant_access_version == 3
        assert attempt.requested_by_user_uuid == USER_UUID
        assert attempt.job_enqueued_at == NOW.replace(tzinfo=None)


def test_same_request_uuid_rejects_changed_scheduled_snapshot(runtime_harness):
    runtime, engine, rental_id = runtime_harness
    runtime.schedule_shipments(
        flask_request=object(),
        payload=_payload(rental_id),
    )

    with pytest.raises(SfBatchShippingRejected):
        runtime.schedule_shipments(
            flask_request=object(),
            payload=_payload(
                rental_id,
                scheduled_time="2026-08-24T10:00:00+08:00",
            ),
        )

    with Session(engine) as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(OutboundShipment)
        ) == 1
        assert session.scalar(
            sa.select(sa.func.count()).select_from(ProviderOperationAttempt)
        ) == 1
