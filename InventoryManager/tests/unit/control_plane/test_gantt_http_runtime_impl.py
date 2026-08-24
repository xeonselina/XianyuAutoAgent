from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import re
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app import create_app, db
from app.models.accessory_inventory import AccessoryType, RentalAccessoryRequest
from app.models.database_identity import TenantDatabaseIdentity
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.models.warehouse import Warehouse
from app.services.gantt.http_runtime import (
    GANTT_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyGanttSaasHttpRuntime,
)
from app.services.gantt.reorder_service import GanttReorderService
from app.services.rental.http_runtime import (
    RENTAL_SAAS_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyRentalSaasHttpRuntime,
)
from inventory_control import (
    ControlDatabase,
    Tenant,
    TenantMembership,
    User,
)
from inventory_control.crypto import RootKey
from inventory_control.domain import (
    EffectiveTenantGate,
    TenantGateDecision,
)
from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
    IssuedAuthSession,
    SessionService,
)
from inventory_control.proofs import (
    CurrentGanttPreviewAuthority,
    GanttPreviewAuthority,
    GanttPreviewProofAdapter,
)
from inventory_control.routing import (
    AccountKind,
    AccountLoginState,
    SqlAlchemyIdentityVerifier,
    TenantDatabaseRouter,
    TenantRoute,
    TenantRouteStatus,
)
from inventory_control.tenant_http import (
    TENANT_CSRF_HEADER_NAME,
    TENANT_SESSION_COOKIE_NAME,
    AuthContext,
    TenantHttpBoundary,
)
from tests.support.test_database import (
    build_mysql_test_config,
)


ROOT_KEY = RootKey(version=3, material=b"h" * 32)


def _active_gate(_session, _tenant, _now) -> TenantGateDecision:
    return TenantGateDecision(
        gate=EffectiveTenantGate.ACTIVE,
        error_code=None,
    )


class _RootKeys:
    def get_root_key(self, *, version: int) -> RootKey:
        if version != ROOT_KEY.version:
            raise LookupError
        return ROOT_KEY


class _EngineFactory:
    def __init__(self, engines: dict[UUID, Engine]) -> None:
        self.engines = engines

    def create(self, *, route, identity, password):
        assert identity == route.routing_identity()
        assert isinstance(password, str) and password
        return self.engines[route.tenant_uuid]


class _RequestRouteRepository:
    def __init__(self, owner: "_RouterFactory", session: Session) -> None:
        self.owner = owner
        self.session = session

    def get_current_ready_route(
        self,
        *,
        tenant_uuid: UUID,
        access_version: int,
        account_kind: AccountKind,
    ):
        self.owner.route_calls.append(
            (self.session, tenant_uuid, access_version, account_kind)
        )
        if not self.session.in_transaction():
            raise AssertionError("route lookup used a closed control transaction")
        if not self.owner.route_enabled:
            return None
        route = self.owner.routes.get(tenant_uuid)
        if (
            route is None
            or access_version != route.tenant_access_version
            or account_kind is not AccountKind.DML
        ):
            return None
        return route


class _RouterFactory:
    def __init__(
        self,
        *,
        routes: dict[UUID, TenantRoute],
        engines: dict[UUID, Engine],
    ) -> None:
        self.routes = routes
        self.engines = engines
        self.route_enabled = True
        self.sessions: list[Session] = []
        self.route_calls: list[tuple[Session, UUID, int, AccountKind]] = []

    @contextmanager
    def __call__(self, control_session: Session):
        assert control_session.in_transaction()
        self.sessions.append(control_session)
        yield TenantDatabaseRouter(
            repository=_RequestRouteRepository(self, control_session),
            root_key_provider=_RootKeys(),
            engine_factory=_EngineFactory(self.engines),
            identity_verifier=SqlAlchemyIdentityVerifier(),
            max_cache_entries=2,
        )


class _AuthorityReader:
    def __init__(self) -> None:
        self.fence_active = False
        self.fence_events: list[str] = []
        self.release_error = False

    @staticmethod
    def _current(auth_context: AuthContext) -> CurrentGanttPreviewAuthority:
        return CurrentGanttPreviewAuthority(
            authority=GanttPreviewAuthority(
                tenant_uuid=UUID(auth_context.tenant_id),
                actor_user_uuid=UUID(auth_context.user_id),
                actor_session_uuid=UUID(auth_context.session_id),
                user_auth_version=auth_context.user_auth_version,
                tenant_access_version=auth_context.tenant_access_version,
                tenant_timezone="UTC",
                recovery_run_uuid=UUID(
                    "90000000-0000-4000-8000-000000000001"
                ),
                recovery_hold_uuid=UUID(
                    "90000000-0000-4000-8000-000000000002"
                ),
                recovery_hold_revision=1,
            ),
            membership_uuid=UUID(auth_context.membership_id),
            role=auth_context.role,
            session_is_current=True,
            effective_gate=auth_context.effective_gate,
            active_root_key=ROOT_KEY,
            database_now=datetime.now(timezone.utc).replace(microsecond=0),
            tenant_timezone="UTC",
        )

    def read_current(self, *, auth_context: AuthContext):
        return self._current(auth_context)

    @contextmanager
    def lock_current(self, *, auth_context: AuthContext):
        self.fence_active = True
        self.fence_events.append("entered")
        try:
            yield self._current(auth_context)
        except BaseException:
            self.fence_events.append("rolled_back")
            raise
        else:
            self.fence_events.append("released")
            if self.release_error:
                raise RuntimeError("control fence release failed")
        finally:
            self.fence_active = False


@dataclass
class _Harness:
    app: object
    control_database: ControlDatabase
    credentials: dict[UUID, IssuedAuthSession]
    engines: dict[UUID, Engine]
    query_events: list[UUID]
    commit_fence_states: list[tuple[UUID, bool]]
    router_factory: _RouterFactory
    authority_reader: _AuthorityReader


def _seed_actor(
    control_database: ControlDatabase,
    session_service: SessionService,
    *,
    phone: str,
) -> tuple[UUID, IssuedAuthSession]:
    now = datetime.now(timezone.utc)
    with control_database.transaction() as session:
        tenant = Tenant(status="active", access_version=4, timezone="UTC")
        user = User(
            phone_e164=phone,
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=now,
            status="active",
        )
        session.add_all([tenant, user])
        session.flush()
        session.add(
            TenantMembership(
                tenant_id=tenant.id,
                user_id=user.id,
                role_key="admin",
                status="active",
                source_type="migration",
            )
        )
        session.flush()
        tenant_uuid = UUID(tenant.id)
        user_id = user.id
    with control_database.transaction() as session:
        issued = session_service.issue(
            session,
            user_id=user_id,
            idle_timeout=timedelta(minutes=30),
            absolute_timeout=timedelta(hours=8),
            now=now,
        )
    return tenant_uuid, issued


def _make_route(
    tenant_uuid: UUID,
    database_uuid: UUID,
    *,
    ordinal: int,
) -> TenantRoute:
    return TenantRoute(
        tenant_uuid=tenant_uuid,
        tenant_access_version=4,
        status=TenantRouteStatus.READY,
        account_kind=AccountKind.DML,
        database_uuid=database_uuid,
        database_instance_key="test-instance",
        database_name="inventory_management_test",
        username=f"tenant_runtime_user_{ordinal}",
        credential_generation=1,
        root_key_version=ROOT_KEY.version,
        derivation_version=1,
        route_version=1,
        desired_login_state=AccountLoginState.ACTIVE,
        expected_schema_generation=1,
    )


@pytest.fixture
def runtime_harness(mysql_routed_database) -> _Harness:
    app = create_app(build_mysql_test_config())
    control_database = mysql_routed_database
    engine = control_database.engine
    session_service = SessionService(gate_current_read=_active_gate)
    tenant_http_boundary = TenantHttpBoundary(session_service)
    tenant_uuid, issued = _seed_actor(
        control_database,
        session_service,
        phone="+8613800138099",
    )
    database_uuid = uuid4()
    with Session(engine) as session:
        session.add_all((
            TenantDatabaseIdentity(
                tenant_id=str(tenant_uuid),
                database_uuid=str(database_uuid),
                created_at=datetime.now(timezone.utc).replace(tzinfo=None),
                schema_generation=1,
            ),
            Warehouse(
                name="默认仓库",
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
            ),
        ))
        session.commit()

    credentials = {tenant_uuid: issued}
    engines = {tenant_uuid: engine}
    routes = {tenant_uuid: _make_route(tenant_uuid, database_uuid, ordinal=1)}
    router_factory = _RouterFactory(routes=routes, engines=engines)
    authority_reader = _AuthorityReader()
    runtime = SqlAlchemyGanttSaasHttpRuntime(
        control_database=control_database,
        tenant_http_boundary=tenant_http_boundary,
        proof_adapter=GanttPreviewProofAdapter(
            authority_reader=authority_reader
        ),
        tenant_router_factory=router_factory,
    )
    app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION] = runtime

    tenant_table_patterns = tuple(
        re.compile(
            rf"(?<![A-Za-z0-9_]){re.escape(name)}(?![A-Za-z0-9_])",
            re.IGNORECASE,
        )
        for name in db.metadata.tables
    )
    query_events: list[UUID] = []
    commit_fence_states: list[tuple[UUID, bool]] = []

    def capture_tenant_query(
        _connection,
        _cursor,
        statement,
        *_args,
        **_kwargs,
    ) -> None:
        if any(pattern.search(statement) for pattern in tenant_table_patterns):
            query_events.append(tenant_uuid)

    def capture_commit(_connection) -> None:
        commit_fence_states.append(
            (tenant_uuid, authority_reader.fence_active)
        )

    event.listen(engine, "before_cursor_execute", capture_tenant_query)
    event.listen(engine, "commit", capture_commit)

    harness = _Harness(
        app=app,
        control_database=control_database,
        credentials=credentials,
        engines=engines,
        query_events=query_events,
        commit_fence_states=commit_fence_states,
        router_factory=router_factory,
        authority_reader=authority_reader,
    )
    try:
        yield harness
    finally:
        event.remove(engine, "before_cursor_execute", capture_tenant_query)
        event.remove(engine, "commit", capture_commit)
        with app.app_context():
            db.session.remove()


def _authorize_client(client, issued: IssuedAuthSession) -> dict[str, str]:
    client.set_cookie(
        TENANT_SESSION_COOKIE_NAME,
        issued.session_token,
        secure=True,
    )
    return {TENANT_CSRF_HEADER_NAME: issued.csrf_token}


def test_runtime_rejects_missing_session_and_csrf_before_router_or_tenant_read(
    runtime_harness: _Harness,
) -> None:
    client = runtime_harness.app.test_client()

    unauthenticated = client.post("/api/gantt/reorder/analyze")
    tenant_uuid, issued = next(iter(runtime_harness.credentials.items()))
    _authorize_client(client, issued)
    csrf_missing = client.post("/api/gantt/reorder/analyze")

    assert unauthenticated.status_code == 401
    assert csrf_missing.status_code == 403
    assert runtime_harness.router_factory.sessions == []
    assert runtime_harness.query_events == []
    assert tenant_uuid not in runtime_harness.query_events


def test_execute_requires_token_only_after_auth_and_csrf_before_tenant_route(
    runtime_harness: _Harness,
) -> None:
    client = runtime_harness.app.test_client()

    unauthenticated = client.post(
        "/api/gantt/reorder/execute",
        json={},
    )
    _tenant_uuid, issued = next(iter(runtime_harness.credentials.items()))
    headers = _authorize_client(client, issued)
    csrf_missing = client.post(
        "/api/gantt/reorder/execute",
        json={},
    )
    authorized_missing_token = client.post(
        "/api/gantt/reorder/execute",
        json={},
        headers=headers,
    )

    assert unauthenticated.status_code == 401
    assert csrf_missing.status_code == 403
    assert authorized_missing_token.status_code == 400
    assert authorized_missing_token.get_json()["message"] == "缺少预览令牌"
    assert runtime_harness.router_factory.sessions == []
    assert runtime_harness.query_events == []


def test_route_failure_performs_no_tenant_database_read(
    runtime_harness: _Harness,
) -> None:
    tenant_uuid, issued = next(iter(runtime_harness.credentials.items()))
    client = runtime_harness.app.test_client()
    headers = _authorize_client(client, issued)
    runtime_harness.router_factory.route_enabled = False

    response = client.post(
        "/api/gantt/reorder/analyze",
        headers=headers,
    )

    assert response.status_code == 503
    assert runtime_harness.query_events == []
    assert runtime_harness.router_factory.route_calls[0][1] == tenant_uuid


def test_each_request_uses_fresh_control_session_and_exact_tenant_route(
    runtime_harness: _Harness,
) -> None:
    client = runtime_harness.app.test_client()
    tenant_uuid, issued = next(iter(runtime_harness.credentials.items()))

    first_headers = _authorize_client(client, issued)
    first = client.post(
        "/api/gantt/reorder/analyze",
        headers=first_headers,
    )
    assert first.status_code == 200
    assert runtime_harness.query_events
    assert set(runtime_harness.query_events) == {tenant_uuid}

    runtime_harness.query_events.clear()
    second_headers = _authorize_client(client, issued)
    second = client.post(
        "/api/gantt/reorder/analyze",
        headers=second_headers,
    )

    assert second.status_code == 200
    assert runtime_harness.query_events
    assert set(runtime_harness.query_events) == {tenant_uuid}
    first_session, second_session = runtime_harness.router_factory.sessions
    assert first_session is not second_session
    assert not first_session.in_transaction()
    assert not second_session.in_transaction()


def _assert_normalized_gantt_view_uses_one_tenant_snapshot_and_fixed_query_budget(
    runtime_harness: _Harness,
) -> None:
    tenant_uuid, issued = next(iter(runtime_harness.credentials.items()))
    engine = runtime_harness.engines[tenant_uuid]
    range_start = date(2026, 8, 22)
    range_end = range_start + timedelta(days=30)

    with Session(engine, expire_on_commit=False) as session:
        model = DeviceModel(
            name="range-model",
            display_name="范围型号",
            is_accessory=False,
            is_active=True,
        )
        session.add(model)
        session.flush()
        devices = [
            Device(
                name=f"range-device-{index:03d}",
                model="range-model",
                model_id=model.id,
                is_accessory=False,
                lifecycle_status="active",
            )
            for index in range(100)
        ]
        session.add_all(devices)
        session.flush()

        first_start = range_start
        first_end = range_start + timedelta(days=2)
        second_start = range_start + timedelta(days=4)
        second_end = range_start + timedelta(days=6)
        session.add_all([
            Rental(
                id=1,
                device_id=devices[0].id,
                start_date=first_start,
                end_date=first_end,
                customer_name="range-first",
                logistics_days=0,
                planned_ship_out_date=first_start - timedelta(days=1),
                planned_return_date=first_end + timedelta(days=1),
                status="not_shipped",
                includes_handle=True,
            ),
            Rental(
                id=2,
                device_id=devices[0].id,
                start_date=second_start,
                end_date=second_end,
                customer_name="range-second",
                logistics_days=2,
                planned_ship_out_date=second_start - timedelta(days=3),
                planned_return_date=second_end + timedelta(days=3),
                status="not_shipped",
            ),
        ])
        for offset in range(31):
            usage_date = range_start + timedelta(days=offset)
            session.add(
                Rental(
                    id=10 + offset,
                    device_id=devices[1 + offset].id,
                    start_date=usage_date,
                    end_date=usage_date,
                    customer_name=f"range-{offset:02d}",
                    logistics_days=0,
                    planned_ship_out_date=usage_date - timedelta(days=1),
                    planned_return_date=usage_date + timedelta(days=1),
                    status="not_shipped",
                )
            )
        session.flush()
        accessory_device = Device(
            name="手机支架-范围测试",
            serial_number="ACCESSORY-RANGE-001",
            model="phone-holder",
            is_accessory=True,
            lifecycle_status="active",
        )
        logical_type = AccessoryType(
            name="tripod",
            display_name="三脚架",
            tracking_mode="logical_unit",
            is_active=True,
        )
        session.add_all([accessory_device, logical_type])
        session.flush()
        session.add_all([
            Rental(
                id=1000,
                device_id=accessory_device.id,
                parent_rental_id=1,
                start_date=first_start,
                end_date=first_end,
                customer_name="range-first-accessory",
                planned_ship_out_date=range_start,
                planned_return_date=first_end + timedelta(days=1),
                status="not_shipped",
            ),
            RentalAccessoryRequest(
                rental_id=1,
                accessory_type_id=logical_type.id,
                name_snapshot="三脚架",
            ),
        ])
        session.commit()

    client = runtime_harness.app.test_client()
    headers = _authorize_client(client, issued)
    runtime_harness.query_events.clear()
    response = client.get(
        "/api/gantt/view",
        query_string={
            "start_date": range_start.isoformat(),
            "end_date": range_end.isoformat(),
            "device_model_id": str(model.id),
            "lifecycle_status": "active",
        },
        headers=headers,
    )

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "private, no-store"
    payload = response.get_json()["data"]
    assert payload["date_range"] == {
        "start": range_start.isoformat(),
        "end": range_end.isoformat(),
    }
    assert len(payload["devices"]) == 100
    assert len(payload["rentals"]) == 33
    assert len(payload["daily_stats_by_date"]) == 31
    first_rental = next(
        rental for rental in payload["rentals"] if rental["id"] == 1
    )
    assert [
        accessory["tracking_mode"]
        for accessory in first_rental["accessories"]
    ] == ["device_bound", "device_bound", "logical_unit"]
    logical_accessory = first_rental["accessories"][-1]
    assert logical_accessory == {
        "name": "三脚架",
        "type": "tripod",
        "tracking_mode": "logical_unit",
        "is_accessory": True,
        "is_bundled": False,
    }
    assert "id" not in logical_accessory
    assert (
        payload["daily_stats_by_date"][range_start.isoformat()][
            "accessory_ship_out_count"
        ]
        == 1
    )
    for stats in payload["daily_stats_by_date"].values():
        assert stats["ship_out_count"] == stats["planned_ship_out_count"]
    assert payload["model_facets"] == [{
        "model_id": model.id,
        "name": "range-model",
        "display_name": "范围型号",
        "device_count": 100,
    }]
    assert payload["schedule_warnings"] == [{
        "code": "LOGISTICS_OVERLAP_RELAY_WARNING",
        "blocking": False,
        "relay_candidate": True,
        "device_id": devices[0].id,
        "predecessor_rental_id": 1,
        "successor_rental_id": 2,
        "overlap_days": 2,
    }]
    assert len(payload["data_revision"]) == 64
    assert payload["request_id"].startswith("gantt-view:")
    assert set(runtime_harness.query_events) == {tenant_uuid}
    # One identity verification, one default-warehouse setup gate, and six
    # fixed projection reads. Device, facet, rental, accessory, request,
    # and summary counts do not scale with rows or displayed days.
    assert len(runtime_harness.query_events) == 8


def test_normalized_gantt_view_budget_on_inventory_management_test(
    runtime_harness: _Harness,
) -> None:
    _assert_normalized_gantt_view_uses_one_tenant_snapshot_and_fixed_query_budget(
        runtime_harness
    )


def test_gantt_view_validates_bounds_after_auth_before_tenant_route(
    runtime_harness: _Harness,
) -> None:
    client = runtime_harness.app.test_client()
    invalid_query = {
        "start_date": "2026-01-01",
        "end_date": "2026-04-01",
    }

    unauthenticated = client.get(
        "/api/gantt/view",
        query_string=invalid_query,
    )
    _tenant_uuid, issued = next(iter(runtime_harness.credentials.items()))
    _authorize_client(client, issued)
    authorized = client.get(
        "/api/gantt/view",
        query_string=invalid_query,
    )

    assert unauthenticated.status_code == 401
    assert authorized.status_code == 400
    assert authorized.get_json()["message"] == "甘特范围不能超过62天"
    assert runtime_harness.router_factory.sessions == []
    assert runtime_harness.query_events == []


def test_rental_reads_use_the_authenticated_single_test_database_route(
    runtime_harness: _Harness,
) -> None:
    app = runtime_harness.app
    gantt_runtime = app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION]
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = (
        SqlAlchemyRentalSaasHttpRuntime(
            tenant_business_runtime=gantt_runtime.tenant_business_runtime
        )
    )
    app.config["ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API"] = False

    tenant_uuid, issued = next(iter(runtime_harness.credentials.items()))
    tenant_business_date = datetime.now(timezone.utc).date()
    with Session(runtime_harness.engines[tenant_uuid]) as session:
        device = Device(
            name="tenant-device",
            is_accessory=False,
        )
        session.add(device)
        session.flush()
        session.add_all((
            Rental(
                id=1,
                device_id=device.id,
                start_date=date.today(),
                end_date=date.today(),
                customer_name="tenant-routed",
            ),
            Rental(
                id=2,
                device_id=device.id,
                start_date=tenant_business_date - timedelta(days=4),
                end_date=tenant_business_date - timedelta(days=1),
                customer_name="pending-row",
                customer_phone="13800138000",
                destination="上海市测试路 1 号",
                status="shipped",
            ),
        ))
        session.commit()

    client = app.test_client()
    runtime_harness.query_events.clear()
    headers = _authorize_client(client, issued)
    first = client.get("/api/rentals/1", headers=headers)
    assert first.status_code == 200
    assert first.get_json()["data"]["customer_name"] == "tenant-routed"
    assert set(runtime_harness.query_events) == {tenant_uuid}

    runtime_harness.query_events.clear()
    second = client.get("/web/rentals/1", headers=headers)
    assert second.status_code == 200
    assert second.get_json()["data"]["customer_name"] == "tenant-routed"
    assert set(runtime_harness.query_events) == {tenant_uuid}

    runtime_harness.query_events.clear()
    pending = client.get("/api/rentals/pending-returns")
    assert pending.status_code == 200
    assert pending.get_json()["data"]["total"] == 1
    assert pending.get_json()["data"]["rentals"][0]["id"] == 2
    assert set(runtime_harness.query_events) == {tenant_uuid}

    runtime_harness.query_events.clear()
    missing_csrf = client.post(
        "/api/rentals/search",
        json={"q": "tenant-routed"},
    )
    assert missing_csrf.status_code == 403
    assert runtime_harness.query_events == []

    searched = client.post(
        "/api/rentals/search",
        json={"q": "tenant-routed", "page": 1, "per_page": 20},
        headers=headers,
    )
    assert searched.status_code == 200
    assert searched.get_json()["data"]["total"] == 1
    assert (
        searched.get_json()["data"]["rentals"][0]["customer_name"]
        == "tenant-routed"
    )
    assert set(runtime_harness.query_events) == {tenant_uuid}


def test_invalid_control_tenant_timezone_fails_before_tenant_route(
    runtime_harness: _Harness,
) -> None:
    app = runtime_harness.app
    gantt_runtime = app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION]
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = (
        SqlAlchemyRentalSaasHttpRuntime(
            tenant_business_runtime=gantt_runtime.tenant_business_runtime
        )
    )
    app.config["ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API"] = False
    tenant_uuid, issued = next(iter(runtime_harness.credentials.items()))
    with runtime_harness.control_database.transaction() as session:
        tenant = session.get(Tenant, str(tenant_uuid))
        assert tenant is not None
        tenant.timezone = "Invalid/Timezone"

    client = app.test_client()
    _authorize_client(client, issued)
    response = client.get("/api/rentals/1")

    assert response.status_code == 503
    assert runtime_harness.router_factory.sessions == []
    assert runtime_harness.query_events == []


def test_booking_availability_authenticates_and_checks_csrf_before_shape_or_route(
    runtime_harness: _Harness,
) -> None:
    app = runtime_harness.app
    gantt_runtime = app.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION]
    app.extensions[RENTAL_SAAS_HTTP_RUNTIME_EXTENSION] = (
        SqlAlchemyRentalSaasHttpRuntime(
            tenant_business_runtime=gantt_runtime.tenant_business_runtime
        )
    )
    app.config["ENABLE_LEGACY_SINGLE_TENANT_RENTAL_API"] = False
    client = app.test_client()

    unauthenticated = client.post(
        "/api/rental-booking/availability",
        json={},
    )
    _tenant_uuid, issued = next(iter(runtime_harness.credentials.items()))
    headers = _authorize_client(client, issued)
    csrf_missing = client.post(
        "/api/rental-booking/availability",
        json={},
    )
    authorized_invalid = client.post(
        "/api/rental-booking/availability",
        json={},
        headers=headers,
    )

    assert unauthenticated.status_code == 401
    assert csrf_missing.status_code == 403
    assert authorized_invalid.status_code == 400
    assert authorized_invalid.get_json()["message"] == "start_date 格式错误"
    assert runtime_harness.router_factory.sessions == []
    assert runtime_harness.query_events == []


def test_http_execute_holds_authority_fence_across_tenant_commit_and_rejects_legacy(
    runtime_harness: _Harness,
    monkeypatch,
) -> None:
    tenant_uuid, issued = next(iter(runtime_harness.credentials.items()))
    client = runtime_harness.app.test_client()
    headers = _authorize_client(client, issued)
    preview = client.post(
        "/api/gantt/reorder/preview",
        json={"decisions": []},
        headers=headers,
    )
    assert preview.status_code == 200

    runtime_harness.commit_fence_states.clear()
    execute = client.post(
        "/api/gantt/reorder/execute",
        json={"token": preview.get_json()["data"]["token"]},
        headers=headers,
    )

    assert execute.status_code == 200
    assert (tenant_uuid, True) in runtime_harness.commit_fence_states
    assert runtime_harness.authority_reader.fence_events[-2:] == [
        "entered",
        "released",
    ]

    with runtime_harness.app.app_context():
        legacy_token = GanttReorderService._sign_preview(
            "ab" * 32,
            [],
            {},
            date.today(),
        )
    monkeypatch.setattr(
        GanttReorderService,
        "_load_preview",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("legacy preview decoder must be unreachable")
        ),
    )
    runtime_harness.commit_fence_states.clear()

    rejected = client.post(
        "/api/gantt/reorder/execute",
        json={"token": legacy_token},
        headers=headers,
    )

    assert rejected.status_code == 409
    assert (tenant_uuid, True) not in runtime_harness.commit_fence_states


def test_http_execute_returns_committed_result_when_fence_release_is_uncertain(
    runtime_harness: _Harness,
) -> None:
    tenant_uuid, issued = next(iter(runtime_harness.credentials.items()))
    client = runtime_harness.app.test_client()
    headers = _authorize_client(client, issued)
    preview = client.post(
        "/api/gantt/reorder/preview",
        json={"decisions": []},
        headers=headers,
    )
    assert preview.status_code == 200

    runtime_harness.commit_fence_states.clear()
    runtime_harness.authority_reader.release_error = True
    execute = client.post(
        "/api/gantt/reorder/execute",
        json={"token": preview.get_json()["data"]["token"]},
        headers=headers,
    )

    assert execute.status_code == 200
    assert execute.get_json()["data"]["authority_fence_outcome"] == (
        "release_unknown_after_tenant_commit"
    )
    assert (tenant_uuid, True) in runtime_harness.commit_fence_states
