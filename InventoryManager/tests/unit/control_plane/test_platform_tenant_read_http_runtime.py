from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
import sqlalchemy as sa
from flask import request

from app import create_app, db
from app.models.device import Device
from app.models.rental import Rental
from app.models.warehouse import Warehouse
from app.services.platform_tenant_read.http_runtime import (
    PlatformTenantReadQueryHttpInvalid,
    PlatformTenantReadResourceHttpUnavailable,
    PlatformTenantReadRuntimeUnavailable,
    PlatformTenantReadTargetHttpUnavailable,
    SqlAlchemyPlatformTenantReadHttpRuntime,
)
from inventory_control import ControlDatabase
from inventory_control.crypto import RootKey
from inventory_control.database import read_database_utc_value
from inventory_control.models import (
    ControlBase,
    PlatformAdmin,
    PlatformAdminSession,
    PlatformAdminTotpCredential,
    PlatformAuditLog,
    Tenant,
)
from inventory_control.platform_http import (
    PLATFORM_SESSION_COOKIE_NAME,
    PlatformAuthenticationRequired,
    PlatformHttpBoundary,
)
from inventory_control.platform_identity import (
    PlatformAdminSessionService,
    issue_platform_csrf_token,
    issue_platform_session_token,
)
from inventory_control.routing import (
    AccountKind,
    AccountLoginState,
    TenantDatabaseRouter,
    TenantRoute,
    TenantRouteStatus,
)
from tests.support.test_database import build_mysql_test_config


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


@pytest.fixture
def tenant_application(mysql_routed_database):
    del mysql_routed_database
    app = create_app(build_mysql_test_config())
    with app.app_context():
        try:
            yield app
        finally:
            db.session.remove()


def _platform_cookie_environment(bearer: str) -> dict[str, str]:
    return {
        "HTTP_COOKIE": f"{PLATFORM_SESSION_COOKIE_NAME}={bearer}",
    }


class _RouteRepository:
    def __init__(self, route: TenantRoute) -> None:
        self.route = route
        self.calls: list[tuple[UUID, int, AccountKind]] = []

    def get_current_ready_route(
        self,
        *,
        tenant_uuid,
        access_version,
        account_kind,
    ):
        self.calls.append((tenant_uuid, access_version, account_kind))
        return self.route


class _RootKeys:
    def get_root_key(self, *, version):
        return RootKey(version=version, material=bytes(range(32)))


class _EngineFactory:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.kinds: list[AccountKind] = []

    def create(self, *, route, identity, password):
        assert identity.account_kind is AccountKind.PLATFORM_READ
        assert isinstance(password, str) and password
        self.kinds.append(route.account_kind)
        return self.engine


class _IdentityVerifier:
    def verify(self, *, engine, expected):
        assert engine is not None
        assert expected.schema_generation == 1


def _seed_platform_session(control_database):
    with control_database.new_session() as session:
        database_now = read_database_utc_value(session)
    if database_now.tzinfo is None:
        database_now = database_now.replace(tzinfo=timezone.utc)
    now = database_now - timedelta(seconds=1)
    bearer = issue_platform_session_token()
    csrf = issue_platform_csrf_token()
    with control_database.transaction() as session:
        admin = PlatformAdmin(
            username_canonical="root.admin",
            status="active",
            password_hash_encoded="$test-v1$not-a-real-password-hash",
            password_hash_algorithm="test",
            password_hash_version=1,
            created_at=now,
            updated_at=now,
        )
        session.add(admin)
        session.flush()
        credential = PlatformAdminTotpCredential(
            platform_admin_id=admin.id,
            generation=admin.totp_generation,
            secret_revision=1,
            status="confirmed",
            seed_nonce=b"n" * 12,
            seed_ciphertext=b"c" * 32,
            root_key_version=1,
            crypto_version=1,
            aad_version=1,
            last_accepted_time_step=1,
            created_at=now,
            confirmed_at=now,
        )
        session.add(credential)
        session.flush()
        platform_session = PlatformAdminSession(
            platform_admin_id=admin.id,
            token_digest_sha256=bearer.digest_sha256,
            csrf_digest_sha256=csrf.digest_sha256,
            auth_version_at_issue=admin.auth_version,
            setup_version_at_issue=admin.setup_version,
            mfa_method="totp",
            mfa_verified_at=now,
            totp_credential_id=credential.id,
            totp_time_step=1,
            policy_version=1,
            csrf_generation=1,
            idle_timeout_seconds=1800,
            created_at=now,
            last_seen_at=now,
            idle_expires_at=now + timedelta(minutes=30),
            absolute_expires_at=now + timedelta(hours=8),
        )
        session.add(platform_session)
        session.flush()
        return bearer.plaintext, admin.id, platform_session.id


def _runtime(control_database, tenant_engine, tenant_id):
    route = TenantRoute(
        tenant_uuid=tenant_id,
        tenant_access_version=1,
        status=TenantRouteStatus.READY,
        account_kind=AccountKind.PLATFORM_READ,
        database_uuid=uuid4(),
        database_instance_key="test",
        database_name="tenant_test",
        username="tenant_platform_read",
        credential_generation=1,
        root_key_version=1,
        derivation_version=1,
        route_version=1,
        desired_login_state=AccountLoginState.ACTIVE,
        expected_schema_generation=1,
    )
    repository = _RouteRepository(route)
    engine_factory = _EngineFactory(tenant_engine)
    router = TenantDatabaseRouter(
        repository=repository,
        root_key_provider=_RootKeys(),
        engine_factory=engine_factory,
        identity_verifier=_IdentityVerifier(),
        max_cache_entries=2,
    )

    @contextmanager
    def router_factory(_control_session):
        yield router

    runtime = SqlAlchemyPlatformTenantReadHttpRuntime(
        control_database=control_database,
        platform_boundary=PlatformHttpBoundary(
            PlatformAdminSessionService()
        ),
        tenant_router_factory=router_factory,
        read_policy_version=1,
        maximum_execution_time_ms=1_000,
    )
    return runtime, repository, engine_factory


def _seed_target_and_rental(control_database, tenant_id) -> int:
    with control_database.transaction() as session:
        session.add(
            Tenant(
                id=str(tenant_id),
                name="被排障租户",
                slug="tenant-read-test",
                status="active",
                access_version=1,
            )
        )
    warehouse = Warehouse(
        name="只读仓库",
        status="active",
        setup_state="ready",
        is_default=True,
        default_slot=1,
        contact_name="秘密联系人",
        contact_phone="13900001111",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="秘密仓库地址",
    )
    device = Device(
        name="只读设备",
        model="x200u",
        serial_number="SERIAL-SECRET",
        lifecycle_reason="不可返回的设备备注",
        warehouse=warehouse,
    )
    rental = Rental(
        device=device,
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 2),
        customer_name="李雷",
        customer_phone="13800138000",
        customer_province="广东省",
        customer_city="深圳市",
        customer_district="南山区",
        customer_address_detail="科技园 1 号",
        status="not_shipped",
    )
    db.session.add(rental)
    db.session.commit()
    return rental.id


def test_runtime_uses_platform_read_route_and_commits_success_audit_first(
    tenant_application,
    control_database,
) -> None:
    tenant_id = uuid4()
    _seed_target_and_rental(control_database, tenant_id)
    bearer, admin_id, session_id = _seed_platform_session(control_database)
    runtime, repository, engine_factory = _runtime(
        control_database,
        db.engine,
        tenant_id,
    )

    with tenant_application.test_request_context(
        f"/platform/api/tenants/{tenant_id}/read/rentals?page_size=10",
        base_url="https://localhost",
        environ_overrides=_platform_cookie_environment(bearer),
    ):
        result = runtime.list_rentals(
            flask_request=request,
            tenant_id=str(tenant_id),
            query_arguments=request.args,
        )

    assert result["items"][0]["customer"] == {
        "name_masked": "李**",
        "phone_masked": "*******8000",
        "region_masked": "已设置",
    }
    assert repository.calls == [(tenant_id, 1, AccountKind.PLATFORM_READ)]
    assert engine_factory.kinds == [AccountKind.PLATFORM_READ]
    with control_database.new_session() as session:
        audit = session.scalar(
            sa.select(PlatformAuditLog).where(
                PlatformAuditLog.action == "platform.tenant_rentals.list"
            )
        )
        assert audit.outcome == "succeeded"
        assert audit.actor_platform_admin_id == admin_id
        assert audit.actor_platform_session_id == session_id
        assert audit.target_tenant_id == str(tenant_id)
        assert audit.access_mode == "tenant_read"
        assert audit.pii_revealed is False
        assert audit.result_count == 1


def test_runtime_reuses_one_select_only_boundary_for_devices_and_warehouses(
    tenant_application,
    control_database,
) -> None:
    tenant_id = uuid4()
    _seed_target_and_rental(control_database, tenant_id)
    bearer, _admin_id, _session_id = _seed_platform_session(control_database)
    runtime, repository, engine_factory = _runtime(
        control_database,
        db.engine,
        tenant_id,
    )
    environ_overrides = _platform_cookie_environment(bearer)
    with tenant_application.test_request_context(
        f"/platform/api/tenants/{tenant_id}/read/devices"
        "?lifecycle_status=active&page_size=10",
        base_url="https://localhost",
        environ_overrides=environ_overrides,
    ):
        devices = runtime.list_devices(
            flask_request=request,
            tenant_id=str(tenant_id),
            query_arguments=request.args,
        )
    with tenant_application.test_request_context(
        f"/platform/api/tenants/{tenant_id}/read/warehouses"
        "?status=active&setup_state=ready&page_size=10",
        base_url="https://localhost",
        environ_overrides=environ_overrides,
    ):
        warehouses = runtime.list_warehouses(
            flask_request=request,
            tenant_id=str(tenant_id),
            query_arguments=request.args,
        )

    assert devices["items"][0]["name"] == "只读设备"
    assert warehouses["items"][0]["name"] == "只读仓库"
    serialized = str({"devices": devices, "warehouses": warehouses})
    for forbidden in (
        "SERIAL-SECRET",
        "不可返回的设备备注",
        "秘密联系人",
        "13900001111",
        "秘密仓库地址",
    ):
        assert forbidden not in serialized
    assert repository.calls == [
        (tenant_id, 1, AccountKind.PLATFORM_READ),
        (tenant_id, 1, AccountKind.PLATFORM_READ),
    ]
    assert engine_factory.kinds == [AccountKind.PLATFORM_READ]
    with control_database.new_session() as session:
        audits = {
            row.action: row
            for row in session.scalars(
                sa.select(PlatformAuditLog).where(
                    PlatformAuditLog.action.in_(
                        {
                            "platform.tenant_devices.list",
                            "platform.tenant_warehouses.list",
                        }
                    )
                )
            )
        }
    assert set(audits) == {
        "platform.tenant_devices.list",
        "platform.tenant_warehouses.list",
    }
    assert audits["platform.tenant_devices.list"].target_resource_type == (
        "device"
    )
    assert audits[
        "platform.tenant_warehouses.list"
    ].target_resource_type == "warehouse"


def test_runtime_rejects_unauthenticated_read_before_tenant_routing(
    tenant_application,
    control_database,
) -> None:
    tenant_id = uuid4()
    _seed_target_and_rental(control_database, tenant_id)
    runtime, repository, engine_factory = _runtime(
        control_database,
        db.engine,
        tenant_id,
    )

    with tenant_application.test_request_context(
        f"/platform/api/tenants/{tenant_id}/read/rentals"
    ):
        with pytest.raises(PlatformAuthenticationRequired):
            runtime.list_rentals(
                flask_request=request,
                tenant_id=str(tenant_id),
                query_arguments=request.args,
            )

    assert repository.calls == []
    assert engine_factory.kinds == []
    with control_database.new_session() as session:
        audit = session.scalar(sa.select(PlatformAuditLog))
        assert audit.outcome == "rejected"
        assert audit.safe_reason_code == (
            "platform_tenant_read.auth_rejected"
        )
        assert audit.result_count is None


def test_runtime_never_returns_data_when_success_audit_cannot_commit(
    tenant_application,
    control_database,
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    _seed_target_and_rental(control_database, tenant_id)
    bearer, _admin_id, _session_id = _seed_platform_session(control_database)
    runtime, _repository, _engine_factory = _runtime(
        control_database,
        db.engine,
        tenant_id,
    )
    original_audit = runtime._audit

    def fail_success_audit(**values):
        if values["outcome"] == "succeeded":
            raise PlatformTenantReadRuntimeUnavailable()
        return original_audit(**values)

    monkeypatch.setattr(runtime, "_audit", fail_success_audit)
    with tenant_application.test_request_context(
        f"/platform/api/tenants/{tenant_id}/read/rentals",
        base_url="https://localhost",
        environ_overrides=_platform_cookie_environment(bearer),
    ):
        with pytest.raises(PlatformTenantReadRuntimeUnavailable):
            runtime.list_rentals(
                flask_request=request,
                tenant_id=str(tenant_id),
                query_arguments=request.args,
            )

    with control_database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count(PlatformAuditLog.id))
        ) == 0


@pytest.mark.parametrize(
    "target_status",
    ["provisioning", "deletion_committing", "deleted"],
)
def test_runtime_rejects_unreadable_tenant_states_before_routing(
    tenant_application,
    control_database,
    target_status,
) -> None:
    tenant_id = uuid4()
    _seed_target_and_rental(control_database, tenant_id)
    with control_database.transaction() as session:
        session.get(Tenant, str(tenant_id)).status = target_status
    bearer, _admin_id, _session_id = _seed_platform_session(control_database)
    runtime, repository, engine_factory = _runtime(
        control_database,
        db.engine,
        tenant_id,
    )

    with tenant_application.test_request_context(
        f"/platform/api/tenants/{tenant_id}/read/rentals",
        base_url="https://localhost",
        environ_overrides=_platform_cookie_environment(bearer),
    ):
        with pytest.raises(PlatformTenantReadTargetHttpUnavailable):
            runtime.list_rentals(
                flask_request=request,
                tenant_id=str(tenant_id),
                query_arguments=request.args,
            )

    assert repository.calls == []
    assert engine_factory.kinds == []
    with control_database.new_session() as session:
        audit = session.scalar(
            sa.select(PlatformAuditLog).where(
                PlatformAuditLog.action == "platform.tenant_rentals.list"
            )
        )
        assert audit.outcome == "rejected"
        assert audit.safe_reason_code == (
            "platform_tenant_read.target_rejected"
        )
        assert audit.target_tenant_id is None


@pytest.mark.parametrize(
    "query",
    [
        "?page=01",
        "?page_size=101",
        "?status=unknown",
        "?page=1&page=2",
        "?unexpected=value",
    ],
)
def test_runtime_rejects_invalid_query_before_routing_and_audits_target(
    tenant_application,
    control_database,
    query,
) -> None:
    tenant_id = uuid4()
    _seed_target_and_rental(control_database, tenant_id)
    bearer, _admin_id, _session_id = _seed_platform_session(control_database)
    runtime, repository, engine_factory = _runtime(
        control_database,
        db.engine,
        tenant_id,
    )

    with tenant_application.test_request_context(
        f"/platform/api/tenants/{tenant_id}/read/rentals{query}",
        base_url="https://localhost",
        environ_overrides=_platform_cookie_environment(bearer),
    ):
        with pytest.raises(PlatformTenantReadQueryHttpInvalid):
            runtime.list_rentals(
                flask_request=request,
                tenant_id=str(tenant_id),
                query_arguments=request.args,
            )

    assert repository.calls == []
    assert engine_factory.kinds == []
    with control_database.new_session() as session:
        audit = session.scalar(
            sa.select(PlatformAuditLog).where(
                PlatformAuditLog.action == "platform.tenant_rentals.list"
            )
        )
        assert audit.outcome == "rejected"
        assert audit.safe_reason_code == (
            "platform_tenant_read.query_rejected"
        )
        assert audit.target_tenant_id == str(tenant_id)


def test_runtime_returns_one_full_customer_projection_after_pii_audit(
    tenant_application,
    control_database,
) -> None:
    tenant_id = uuid4()
    rental_id = _seed_target_and_rental(control_database, tenant_id)
    bearer, admin_id, session_id = _seed_platform_session(control_database)
    runtime, repository, engine_factory = _runtime(
        control_database,
        db.engine,
        tenant_id,
    )

    with tenant_application.test_request_context(
        f"/platform/api/tenants/{tenant_id}/read/rentals/"
        f"{rental_id}/customer-pii?reason=support_case",
        base_url="https://localhost",
        environ_overrides=_platform_cookie_environment(bearer),
    ):
        result = runtime.get_rental_customer_pii(
            flask_request=request,
            tenant_id=str(tenant_id),
            rental_id=str(rental_id),
            query_arguments=request.args,
        )

    assert result == {
        "rental_id": rental_id,
        "customer": {
            "name": "李雷",
            "phone": "13800138000",
            "address": {
                "province": "广东省",
                "city": "深圳市",
                "district": "南山区",
                "detail": "科技园 1 号",
            },
        },
    }
    assert repository.calls == [(tenant_id, 1, AccountKind.PLATFORM_READ)]
    assert engine_factory.kinds == [AccountKind.PLATFORM_READ]
    with control_database.new_session() as session:
        audit = session.scalar(
            sa.select(PlatformAuditLog).where(
                PlatformAuditLog.action
                == "platform.tenant_rental_customer_pii.read"
            )
        )
        assert audit.outcome == "succeeded"
        assert audit.actor_platform_admin_id == admin_id
        assert audit.actor_platform_session_id == session_id
        assert audit.target_tenant_id == str(tenant_id)
        assert audit.target_resource_id == str(rental_id)
        assert audit.pii_revealed is True
        assert audit.safe_reason_code == "platform_pii.support_case"
        assert audit.result_count == 1


@pytest.mark.parametrize(
    ("rental_id", "query"),
    [
        ("01", "?reason=support_case"),
        ("1", ""),
        ("1", "?reason=UPPERCASE"),
        ("1", "?reason=support_case&reason=duplicate"),
        ("1", "?reason=support_case&unexpected=value"),
    ],
)
def test_runtime_rejects_invalid_pii_selector_before_tenant_routing(
    tenant_application,
    control_database,
    rental_id,
    query,
) -> None:
    tenant_id = uuid4()
    _seed_target_and_rental(control_database, tenant_id)
    bearer, _admin_id, _session_id = _seed_platform_session(control_database)
    runtime, repository, engine_factory = _runtime(
        control_database,
        db.engine,
        tenant_id,
    )

    with tenant_application.test_request_context(
        f"/platform/api/tenants/{tenant_id}/read/rentals/"
        f"{rental_id}/customer-pii{query}",
        base_url="https://localhost",
        environ_overrides=_platform_cookie_environment(bearer),
    ):
        with pytest.raises(PlatformTenantReadQueryHttpInvalid):
            runtime.get_rental_customer_pii(
                flask_request=request,
                tenant_id=str(tenant_id),
                rental_id=rental_id,
                query_arguments=request.args,
            )

    assert repository.calls == []
    assert engine_factory.kinds == []
    with control_database.new_session() as session:
        audit = session.scalar(
            sa.select(PlatformAuditLog).where(
                PlatformAuditLog.action
                == "platform.tenant_rental_customer_pii.read"
            )
        )
        assert audit.outcome == "rejected"
        assert audit.pii_revealed is False
        assert audit.safe_reason_code == "platform_tenant_pii.query_rejected"


def test_runtime_audits_unknown_pii_resource_without_revealing_data(
    tenant_application,
    control_database,
) -> None:
    tenant_id = uuid4()
    _seed_target_and_rental(control_database, tenant_id)
    bearer, _admin_id, _session_id = _seed_platform_session(control_database)
    runtime, _repository, _engine_factory = _runtime(
        control_database,
        db.engine,
        tenant_id,
    )

    with tenant_application.test_request_context(
        f"/platform/api/tenants/{tenant_id}/read/rentals/999999/"
        "customer-pii?reason=support_case",
        base_url="https://localhost",
        environ_overrides=_platform_cookie_environment(bearer),
    ):
        with pytest.raises(PlatformTenantReadResourceHttpUnavailable):
            runtime.get_rental_customer_pii(
                flask_request=request,
                tenant_id=str(tenant_id),
                rental_id="999999",
                query_arguments=request.args,
            )

    with control_database.new_session() as session:
        audit = session.scalar(
            sa.select(PlatformAuditLog).where(
                PlatformAuditLog.action
                == "platform.tenant_rental_customer_pii.read"
            )
        )
        assert audit.outcome == "rejected"
        assert audit.pii_revealed is False
        assert audit.target_resource_id == "999999"
        assert audit.result_count == 0


def test_runtime_never_returns_pii_when_success_audit_cannot_commit(
    tenant_application,
    control_database,
    monkeypatch,
) -> None:
    tenant_id = uuid4()
    rental_id = _seed_target_and_rental(control_database, tenant_id)
    bearer, _admin_id, _session_id = _seed_platform_session(control_database)
    runtime, _repository, _engine_factory = _runtime(
        control_database,
        db.engine,
        tenant_id,
    )
    original_audit = runtime._audit

    def fail_success_audit(**values):
        if values["outcome"] == "succeeded":
            raise PlatformTenantReadRuntimeUnavailable()
        return original_audit(**values)

    monkeypatch.setattr(runtime, "_audit", fail_success_audit)
    with tenant_application.test_request_context(
        f"/platform/api/tenants/{tenant_id}/read/rentals/"
        f"{rental_id}/customer-pii?reason=support_case",
        base_url="https://localhost",
        environ_overrides=_platform_cookie_environment(bearer),
    ):
        with pytest.raises(PlatformTenantReadRuntimeUnavailable):
            runtime.get_rental_customer_pii(
                flask_request=request,
                tenant_id=str(tenant_id),
                rental_id=str(rental_id),
                query_arguments=request.args,
            )
