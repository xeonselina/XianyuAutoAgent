from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from uuid import uuid4

import pytest
from flask import request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import create_app, db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.models.rental_relay_case import RentalRelayCase
from app.models.audit_log import AuditLog
from app.models.warehouse import Warehouse
from app.services.relay.http_runtime import (
    RELAY_SAAS_HTTP_RUNTIME_EXTENSION,
    RelayQueryInvalid,
    SqlAlchemyRelaySaasHttpRuntime,
)
from app.services.relay.mutation_service import RelayManualMutationInvalid
from app.services.tenant_business import TenantBusinessRequestScope
from inventory_control.domain import EffectiveTenantGate, TenantRole
from inventory_control.domain.rbac import Capability
from inventory_control.tenant_http import AuthContext


class _ExplicitTenantRuntime:
    def __init__(self, engine):
        self.engine = engine
        self.auth_context = AuthContext(
            session_id=str(uuid4()),
            user_id=str(uuid4()),
            membership_id=str(uuid4()),
            tenant_id=str(uuid4()),
            role=TenantRole.OPERATOR,
            user_auth_version=1,
            tenant_access_version=1,
            tenant_timezone="Asia/Shanghai",
            effective_gate=EffectiveTenantGate.ACTIVE,
        )
        self.calls: list[dict[str, object]] = []

    @contextmanager
    def tenant_session(
        self,
        *,
        flask_request,
        capability,
        additional_capabilities=(),
        request_id_prefix,
        after_authorize=None,
        passthrough_exceptions=(),
        allow_pending_warehouse_setup=False,
    ):
        self.calls.append({
            "capability": capability,
            "additional_capabilities": additional_capabilities,
            "request_id_prefix": request_id_prefix,
        })
        if after_authorize is not None:
            after_authorize(self.auth_context)
        with Session(
            self.engine,
            autoflush=False,
            expire_on_commit=False,
        ) as tenant_session:
            yield TenantBusinessRequestScope(
                auth_context=self.auth_context,
                request_id=f"{request_id_prefix}:{len(self.calls)}",
                database_now=datetime(
                    2026,
                    8,
                    22,
                    16,
                    30,
                    tzinfo=timezone.utc,
                ),
                tenant_session=tenant_session,
            )


def _ready_default() -> Warehouse:
    return Warehouse(
        name="默认仓",
        status="active",
        setup_state="ready",
        is_default=True,
        default_slot=1,
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="测试地址",
    )


def test_relay_reads_use_explicit_tenant_session_and_tenant_business_date(
    mysql_application_engine,
):
    app = create_app("testing")
    engine = mysql_application_engine
    scope = _ExplicitTenantRuntime(engine)
    try:
        with app.app_context():
            with Session(engine) as session:
                warehouse = _ready_default()
                model = DeviceModel(
                    name="x300u",
                    display_name="VIVO X300 Ultra",
                    is_active=True,
                    is_accessory=False,
                )
                device = Device(
                    name="租户主设备",
                    model="x300u",
                    device_model=model,
                    warehouse=warehouse,
                    lifecycle_status="active",
                )
                session.add_all((warehouse, model, device))
                session.flush()
                predecessor = Rental(
                    device=device,
                    start_date=date(2026, 8, 18),
                    end_date=date(2026, 8, 20),
                    planned_ship_out_date=date(2026, 8, 15),
                    planned_return_date=date(2026, 8, 23),
                    logistics_days=2,
                    ship_out_time=datetime(2026, 8, 17),
                    status="returned",
                    customer_name="前单客户",
                    customer_phone="13800138001",
                    destination="前单地址",
                )
                successor = Rental(
                    device=device,
                    start_date=date(2026, 8, 25),
                    end_date=date(2026, 8, 27),
                    planned_ship_out_date=date(2026, 8, 21),
                    planned_return_date=date(2026, 8, 31),
                    logistics_days=3,
                    ship_out_time=datetime(2026, 8, 21),
                    status="not_shipped",
                    customer_name="后单客户",
                    customer_phone="13800138002",
                    destination="后单地址",
                )
                session.add_all((predecessor, successor))
                session.commit()

        runtime = SqlAlchemyRelaySaasHttpRuntime(
            tenant_business_runtime=scope
        )
        with app.test_request_context(
            "/api/relay-cases?ship_date_from=2026-08-20&ship_date_to=2026-08-26"
        ):
            listed = runtime.list_cases(
                flask_request=request,
                query=request.args,
            )
        assert listed["total"] == 1
        assert listed["items"][0]["device"]["name"] == "租户主设备"
        assert listed["items"][0]["predecessor"]["customer_name"] == "前单客户"
        assert scope.calls[-1]["capability"] is Capability.RENTAL_READ
        assert scope.calls[-1]["additional_capabilities"] == (
            Capability.RELAY_WRITE,
            Capability.INVENTORY_READ,
            Capability.CUSTOMER_PII_READ,
        )

        with app.test_request_context("/api/relay-cases/manual-options"):
            manual = runtime.list_manual_options(flask_request=request)
        assert manual["total"] == 1
        assert manual["items"][0]["can_create"] is True
    finally:
        with app.app_context():
            db.session.remove()


def test_relay_query_is_validated_only_after_authorization(
    mysql_application_engine,
):
    app = create_app("testing")
    engine = mysql_application_engine
    scope = _ExplicitTenantRuntime(engine)
    runtime = SqlAlchemyRelaySaasHttpRuntime(
        tenant_business_runtime=scope
    )
    with app.test_request_context("/api/relay-cases?per_page=101"):
        with pytest.raises(RelayQueryInvalid):
            runtime.list_cases(
                flask_request=request,
                query=request.args,
            )
    assert len(scope.calls) == 1


def test_manual_create_uses_caller_transaction_and_authenticated_actor(
    mysql_application_engine,
):
    app = create_app("testing")
    app.testing = False
    app.config["ENABLE_LEGACY_SINGLE_TENANT_RELAY_API"] = False
    engine = mysql_application_engine
    scope = _ExplicitTenantRuntime(engine)
    runtime = SqlAlchemyRelaySaasHttpRuntime(
        tenant_business_runtime=scope
    )
    try:
        with app.app_context():
            with Session(engine) as session:
                warehouse = _ready_default()
                model = DeviceModel(
                    name="manual-runtime",
                    display_name="人工接力设备",
                    is_active=True,
                    is_accessory=False,
                )
                device = Device(
                    name="人工接力主设备",
                    model="manual-runtime",
                    device_model=model,
                    warehouse=warehouse,
                    lifecycle_status="active",
                    is_accessory=False,
                )
                session.add_all((warehouse, model, device))
                session.flush()
                predecessor = Rental(
                    device=device,
                    start_date=date(2026, 8, 18),
                    end_date=date(2026, 8, 20),
                    planned_ship_out_date=date(2026, 8, 15),
                    planned_return_date=date(2026, 8, 23),
                    logistics_days=2,
                    ship_out_time=datetime(2026, 8, 17),
                    status="returned",
                    customer_name="前单客户",
                )
                successor = Rental(
                    device=device,
                    start_date=date(2026, 8, 25),
                    end_date=date(2026, 8, 27),
                    planned_ship_out_date=date(2026, 8, 21),
                    planned_return_date=date(2026, 8, 31),
                    logistics_days=3,
                    ship_out_time=datetime(2026, 8, 21),
                    status="not_shipped",
                    customer_name="后单客户",
                )
                session.add_all((predecessor, successor))
                session.commit()
                device_id = device.id

            app.extensions[RELAY_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
            response = app.test_client().post(
                "/api/relay-cases/manual",
                json={"device_id": device_id},
            )

            assert response.status_code == 200
            assert response.headers["Cache-Control"] == "private, no-store"
            payload = response.get_json()["data"]
            assert payload["status"] == "agreed"
            assert payload["accessory_chain"] == {
                "linked_count": 0,
                "shortage_count": 0,
                "shortage_type_codes": [],
                "unlinked_count": 0,
            }
            assert scope.calls[-1]["capability"] is Capability.RELAY_WRITE
            assert scope.calls[-1]["additional_capabilities"] == (
                Capability.RENTAL_WRITE,
                Capability.INVENTORY_WRITE,
            )

            with Session(engine) as session:
                relay_case = session.execute(
                    select(RentalRelayCase)
                ).scalar_one()
                binding = session.execute(
                    select(RentalRelayBinding)
                ).scalar_one()
                audit = session.execute(select(AuditLog)).scalar_one()
                assert binding.predecessor_rental_id == relay_case.predecessor_rental_id
                assert binding.successor_rental_id == relay_case.successor_rental_id
                assert audit.details["actor_id"] == scope.auth_context.user_id
                assert audit.details["operation_key"].startswith(
                    "relay-manual-create:"
                )

            downgraded = app.test_client().put(
                f"/api/relay-cases/{payload['predecessor_rental_id']}/"
                f"{payload['successor_rental_id']}",
                json={
                    "status": "notified",
                    "accessory_note": "  线下补寄手机支架  ",
                },
            )
            assert downgraded.status_code == 200
            downgraded_payload = downgraded.get_json()["data"]
            assert downgraded_payload["status"] == "notified"
            assert downgraded_payload["accessory_note"] == "线下补寄手机支架"

            restored = app.test_client().put(
                f"/api/relay-cases/{payload['predecessor_rental_id']}/"
                f"{payload['successor_rental_id']}",
                json={"status": "agreed"},
            )
            assert restored.status_code == 200
            assert restored.get_json()["data"]["status"] == "agreed"
            assert restored.get_json()["data"]["accessory_note"] == "线下补寄手机支架"

            external = app.test_client().put(
                f"/api/relay-cases/{payload['predecessor_rental_id']}/"
                f"{payload['successor_rental_id']}",
                json={"status": "shipped", "sf_tracking_number": "SF1"},
            )
            assert external.status_code == 503
            assert external.get_json()["data"]["code"] == (
                "RELAY_STATUS_EXTERNAL_MUTATION_UNAVAILABLE"
            )

            with Session(engine) as session:
                relay_case = session.execute(
                    select(RentalRelayCase)
                ).scalar_one()
                assert relay_case.status == "agreed"
                assert relay_case.accessory_note == "线下补寄手机支架"
                assert session.execute(
                    select(RentalRelayBinding)
                ).scalar_one().successor_rental_id == payload[
                    "successor_rental_id"
                ]
                note_audit = session.execute(
                    select(AuditLog).where(
                        AuditLog.action == "relay_accessory_note_updated"
                    )
                ).scalar_one()
                assert note_audit.details["note_present"] is True
    finally:
        with app.app_context():
            db.session.remove()


def test_manual_create_payload_is_validated_after_authorization(
    mysql_application_engine,
):
    app = create_app("testing")
    engine = mysql_application_engine
    scope = _ExplicitTenantRuntime(engine)
    runtime = SqlAlchemyRelaySaasHttpRuntime(
        tenant_business_runtime=scope
    )
    with app.test_request_context("/api/relay-cases/manual"):
        with pytest.raises(RelayManualMutationInvalid):
            runtime.create_manual_case(
                flask_request=request,
                payload={"device_id": True},
            )
    assert len(scope.calls) == 1


def test_automatic_agreement_rechecks_the_shared_schedule_policy(
    mysql_application_engine,
):
    app = create_app("testing")
    app.testing = False
    app.config["ENABLE_LEGACY_SINGLE_TENANT_RELAY_API"] = False
    engine = mysql_application_engine
    scope = _ExplicitTenantRuntime(engine)
    runtime = SqlAlchemyRelaySaasHttpRuntime(
        tenant_business_runtime=scope
    )
    try:
        with app.app_context():
            with Session(engine) as session:
                warehouse = _ready_default()
                model = DeviceModel(
                    name="automatic-runtime",
                    display_name="自动候选设备",
                    is_active=True,
                    is_accessory=False,
                )
                device = Device(
                    name="自动候选主设备",
                    model="automatic-runtime",
                    device_model=model,
                    warehouse=warehouse,
                    lifecycle_status="active",
                    is_accessory=False,
                )
                first = Rental(
                    device=device,
                    start_date=date(2026, 8, 2),
                    end_date=date(2026, 8, 8),
                    planned_ship_out_date=date(2026, 7, 29),
                    planned_return_date=date(2026, 8, 12),
                    logistics_days=3,
                    ship_out_time=datetime(2026, 7, 29),
                    status="not_shipped",
                    customer_name="自动前单",
                )
                second = Rental(
                    device=device,
                    start_date=date(2026, 8, 14),
                    end_date=date(2026, 8, 20),
                    planned_ship_out_date=date(2026, 8, 10),
                    planned_return_date=date(2026, 8, 24),
                    logistics_days=3,
                    ship_out_time=datetime(2026, 8, 10),
                    status="not_shipped",
                    customer_name="自动后单",
                )
                session.add_all((warehouse, model, device, first, second))
                session.commit()
                pair = first.id, second.id

            app.extensions[RELAY_SAAS_HTTP_RUNTIME_EXTENSION] = runtime
            client = app.test_client()
            agreed = client.put(
                f"/api/relay-cases/{pair[0]}/{pair[1]}",
                json={"status": "agreed"},
            )
            assert agreed.status_code == 200
            assert agreed.get_json()["data"]["status"] == "agreed"

            notified = client.put(
                f"/api/relay-cases/{pair[0]}/{pair[1]}",
                json={"status": "notified"},
            )
            assert notified.status_code == 200

            with Session(engine) as session:
                successor = session.get(Rental, pair[1])
                successor.start_date = date(2026, 8, 18)
                successor.end_date = date(2026, 8, 24)
                successor.planned_ship_out_date = date(2026, 8, 14)
                successor.planned_return_date = date(2026, 8, 28)
                session.commit()

            stale = client.put(
                f"/api/relay-cases/{pair[0]}/{pair[1]}",
                json={"status": "agreed"},
            )
            assert stale.status_code == 409
            assert stale.get_json()["data"]["code"] == (
                "RELAY_STATUS_MUTATION_CONFLICT"
            )
            with Session(engine) as session:
                assert session.execute(
                    select(RentalRelayCase)
                ).scalar_one().status == "notified"
                assert session.execute(
                    select(RentalRelayBinding)
                ).scalar_one_or_none() is None
    finally:
        with app.app_context():
            db.session.remove()


def test_non_test_relay_routes_fail_closed_without_runtime_or_write_adapter():
    app = create_app("testing")
    app.testing = False
    app.config["ENABLE_LEGACY_SINGLE_TENANT_RELAY_API"] = False
    client = app.test_client()

    listed = client.get("/api/relay-cases")
    updated = client.put(
        "/api/relay-cases/1/2",
        json={"status": "agreed"},
    )
    tracking = client.post("/api/relay-cases/1/tracking/refresh")
    manual = client.post(
        "/api/relay-cases/manual",
        json={"device_id": 1},
    )

    assert listed.status_code == 503
    assert updated.status_code == 503
    assert tracking.status_code == 503
    assert manual.status_code == 503
    assert listed.headers["Cache-Control"] == "private, no-store"
