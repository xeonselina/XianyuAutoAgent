"""Real MariaDB coverage for tenant member and warehouse settings."""

import base64
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier, Event

import pytest
from alembic import command
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, delete, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.engine import Engine

from app import create_app
from app.auth import create_auth_session
from app.control.models import (
    AuthSession,
    ControlBase,
    PlatformAdmin,
    SmsLoginCode,
    Tenant,
    TenantMember,
)
from app.crypto import SecretBox
from config import TestingConfig


TEST_MASTER_KEY = base64.b64encode(bytes(range(32))).decode("ascii")
MIGRATIONS_DIRECTORY = str(
    Path(__file__).resolve().parents[2] / "migrations"
)
DATABASE_ENVIRONMENTS = {
    "TEST_CONTROL_DATABASE_URL": "control_saas_test",
    "TEST_TENANT_DATABASE_URL_A": "tenant_a_saas_test",
}


def _required_test_url(environment_name):
    raw_url = os.environ.get(environment_name)
    if not raw_url:
        pytest.skip(f"{environment_name} is required for MariaDB test")
    parsed = make_url(raw_url)
    if parsed.database != DATABASE_ENVIRONMENTS[environment_name]:
        raise RuntimeError(
            f"{environment_name} must target "
            f"{DATABASE_ENVIRONMENTS[environment_name]}"
        )
    return parsed


def _assert_test_only_grants(connection):
    allowed_databases = {
        "control_saas_test",
        "tenant_a_saas_test",
        "tenant_b_saas_test",
    }
    for grant in connection.exec_driver_sql(
        "SHOW GRANTS FOR CURRENT_USER"
    ).scalars():
        normalized = grant.replace("\\_", "_").replace("\\%", "%")
        if normalized.startswith("GRANT USAGE ON *.*"):
            continue
        if any(
            token in normalized
            for database in allowed_databases
            for token in (f"ON `{database}`.*", f"ON {database}.*")
        ):
            continue
        raise RuntimeError("test user has privileges outside fixed test DBs")


def _reset_schema(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
        try:
            preparer = connection.dialect.identifier_preparer
            for table_name in inspect(connection).get_table_names():
                quoted = preparer.quote_identifier(table_name)
                connection.exec_driver_sql(f"DROP TABLE {quoted}")
        finally:
            connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")


def _upgrade(database_url):
    application = Flask("settings_api_migration_test")
    application.config.update(
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    )
    migration_db = SQLAlchemy()
    migration = Migrate()
    migration_db.init_app(application)
    migration.init_app(
        application,
        migration_db,
        directory=MIGRATIONS_DIRECTORY,
    )
    with application.app_context():
        try:
            config = migration.get_config(MIGRATIONS_DIRECTORY)
            config.attributes["programmatic_provisioning"] = True
            command.upgrade(config, "head")
        finally:
            migration_db.session.remove()
            migration_db.engine.dispose()


@pytest.fixture(scope="module")
def settings_api_application():
    urls = {
        name: _required_test_url(name)
        for name in DATABASE_ENVIRONMENTS
    }
    engines = {
        name: create_engine(url, pool_pre_ping=True)
        for name, url in urls.items()
    }
    application = None
    verified_safe = False
    try:
        for environment_name, engine in engines.items():
            with engine.connect() as connection:
                assert connection.exec_driver_sql(
                    "SELECT DATABASE()"
                ).scalar_one() == DATABASE_ENVIRONMENTS[environment_name]
                _assert_test_only_grants(connection)
        verified_safe = True
        for engine in engines.values():
            _reset_schema(engine)
        ControlBase.metadata.create_all(
            engines["TEST_CONTROL_DATABASE_URL"]
        )
        tenant_url = urls["TEST_TENANT_DATABASE_URL_A"]
        tenant_url_string = tenant_url.render_as_string(
            hide_password=False
        )
        _upgrade(tenant_url_string)

        class SettingsApiConfig(TestingConfig):
            AUTH_BYPASS_FOR_TESTS = False
            CONTROL_DATABASE_URL = urls[
                "TEST_CONTROL_DATABASE_URL"
            ].render_as_string(hide_password=False)
            SAAS_MASTER_KEY = TEST_MASTER_KEY
            SQLALCHEMY_DATABASE_URI = tenant_url_string
            SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
            TENANT_DB_HOST = tenant_url.host
            TENANT_DB_PORT = tenant_url.port
            TENANT_DB_POOL_SIZE = 3
            PROVISIONER_DATABASE_URL = None
            CORS_ORIGINS = []

        application = create_app(SettingsApiConfig)
        yield {
            "app": application,
            "control_engine": engines["TEST_CONTROL_DATABASE_URL"],
            "tenant_engine": engines["TEST_TENANT_DATABASE_URL_A"],
            "tenant_url": tenant_url,
        }
    finally:
        if application is not None:
            finalizer = application.extensions.get(
                "tenant_resource_finalizer"
            )
            if finalizer is not None and finalizer.alive:
                finalizer()
        for engine in engines.values():
            try:
                if verified_safe:
                    _reset_schema(engine)
            finally:
                engine.dispose()


def _clear_rows(environment):
    with environment["tenant_engine"].begin() as connection:
        connection.exec_driver_sql("DELETE FROM xianyu_order_alerts")
        connection.exec_driver_sql("DELETE FROM xianyu_shops")
        connection.exec_driver_sql(
            "DELETE FROM warehouse_sf_configs"
        )
        connection.exec_driver_sql(
            "DELETE FROM warehouse_kuaimai_configs"
        )
        connection.exec_driver_sql("DELETE FROM warehouses")
    store = environment["app"].extensions["control_store"]
    with store.session() as session:
        session.execute(delete(AuthSession))
        session.execute(delete(SmsLoginCode))
        session.execute(delete(TenantMember))
        session.execute(delete(Tenant))
        session.execute(delete(PlatformAdmin))


def _new_client(application, credentials):
    client = application.test_client()
    client.set_cookie("tenant_session", credentials.raw_token)
    return client


@pytest.fixture
def settings_api_environment(settings_api_application):
    environment = settings_api_application
    _clear_rows(environment)
    store = environment["app"].extensions["control_store"]
    tenant_url = environment["tenant_url"]
    box = SecretBox.from_base64(TEST_MASTER_KEY)
    with store.session() as session:
        tenant = Tenant(
            name="设置测试租户",
            status="active",
            expires_at=datetime.utcnow() + timedelta(days=30),
            db_name=tenant_url.database,
            db_username=tenant_url.username,
            db_password_ciphertext=box.encrypt(
                tenant_url.password,
                purpose="tenant-db-password",
            ),
            provisioning_status="active",
        )
        session.add(tenant)
        session.flush()
        admin = TenantMember(
            tenant_id=tenant.id,
            phone="+8613800138000",
            role="admin",
            status="active",
        )
        operator = TenantMember(
            tenant_id=tenant.id,
            phone="+8613800138001",
            role="operator",
            status="active",
        )
        session.add_all((admin, operator))
        session.flush()
        admin_credentials = create_auth_session(
            session,
            kind="tenant",
            subject_id=admin.id,
            tenant_id=tenant.id,
        )
        operator_credentials = create_auth_session(
            session,
            kind="tenant",
            subject_id=operator.id,
            tenant_id=tenant.id,
        )
        result = {
            **environment,
            "tenant_id": tenant.id,
            "admin_id": admin.id,
            "operator_id": operator.id,
            "admin_credentials": admin_credentials,
            "operator_credentials": operator_credentials,
        }
    result["admin_client"] = _new_client(
        environment["app"], admin_credentials
    )
    result["operator_client"] = _new_client(
        environment["app"], operator_credentials
    )
    yield result
    _clear_rows(environment)


def _csrf(environment, role="admin"):
    return {
        "X-CSRF-Token": environment[
            f"{role}_credentials"
        ].csrf_token
    }


def _create_warehouse(environment, province="广东省", city="深圳市"):
    response = environment["admin_client"].post(
        "/api/settings/warehouses",
        json={"province": province, "city": city},
        headers=_csrf(environment),
    )
    assert response.status_code == 201
    return response.get_json()["data"]


def test_active_admin_and_operator_can_list_public_warehouses(
    settings_api_environment,
):
    warehouse = _create_warehouse(settings_api_environment)
    configured = settings_api_environment["admin_client"].put(
        f"/api/settings/warehouses/{warehouse['id']}/sf",
        json={
            "partner_id": "public-state-only",
            "checkword": "must-not-leak",
            "monthly_card": "must-not-leak-either",
        },
        headers=_csrf(settings_api_environment),
    )
    assert configured.status_code == 200

    for role in ("admin", "operator"):
        response = settings_api_environment[f"{role}_client"].get(
            "/api/warehouses"
        )

        assert response.status_code == 200
        assert response.get_json()["data"] == [{
            "id": warehouse["id"],
            "province": "广东省",
            "city": "深圳市",
            "name": "广东省深圳市仓库",
            "sf_configured": True,
            "kuaimai_configured": False,
            "created_at": response.get_json()["data"][0]["created_at"],
            "updated_at": response.get_json()["data"][0]["updated_at"],
        }]
        serialized = json.dumps(response.get_json(), ensure_ascii=False)
        assert "sf_config" not in response.get_json()["data"][0]
        assert "kuaimai_config" not in response.get_json()["data"][0]
        assert "ciphertext" not in serialized
        assert "must-not-leak" not in serialized


def test_public_warehouse_list_still_requires_a_tenant_session(
    settings_api_environment,
):
    response = settings_api_environment["app"].test_client().get(
        "/api/warehouses"
    )

    assert response.status_code == 401
    assert response.get_json()["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize(
    "method,path,body",
    [
        ("get", "/api/settings/members", None),
        ("post", "/api/settings/members", {"phone": "13800138009"}),
        ("patch", "/api/settings/members/1", {"status": "disabled"}),
        ("get", "/api/settings/warehouses", None),
        (
            "post",
            "/api/settings/warehouses",
            {"province": "广东省", "city": "深圳市"},
        ),
        ("patch", "/api/settings/warehouses/1", {"city": "广州市"}),
        ("put", "/api/settings/warehouses/1/sf", {}),
        ("put", "/api/settings/warehouses/1/kuaimai", {}),
        ("get", "/api/settings/xianyu-shops", None),
        ("post", "/api/settings/xianyu-shops", {"name": "店", "app_key": "key"}),
        ("patch", "/api/settings/xianyu-shops/1", {"name": "店"}),
        ("post", "/api/settings/xianyu-shops/1/sync", None),
    ],
)
def test_operator_cannot_access_any_settings_endpoint(
    settings_api_environment,
    method,
    path,
    body,
):
    response = getattr(settings_api_environment["operator_client"], method)(
        path,
        json=body,
        headers=_csrf(settings_api_environment, "operator"),
    )

    assert response.status_code == 403
    assert response.get_json()["code"] == "FORBIDDEN"


def test_admin_lists_creates_and_updates_normalized_members(
    settings_api_environment,
):
    client = settings_api_environment["admin_client"]
    created = client.post(
        "/api/settings/members",
        json={"phone": "(+86) 139-0013-9000", "role": "operator"},
        headers=_csrf(settings_api_environment),
    )
    assert created.status_code == 201
    member = created.get_json()["data"]
    assert member == {
        "id": member["id"],
        "phone": "+8613900139000",
        "role": "operator",
        "status": "active",
    }

    updated = client.patch(
        f"/api/settings/members/{member['id']}",
        json={"role": "admin", "status": "disabled"},
        headers=_csrf(settings_api_environment),
    )
    assert updated.status_code == 200
    assert updated.get_json()["data"]["role"] == "admin"
    assert updated.get_json()["data"]["status"] == "disabled"

    listed = client.get("/api/settings/members")
    assert listed.status_code == 200
    assert [row["phone"] for row in listed.get_json()["data"]] == [
        "+8613800138000",
        "+8613800138001",
        "+8613900139000",
    ]


def test_member_phone_is_globally_unique_across_tenants(
    settings_api_environment,
):
    store = settings_api_environment["app"].extensions["control_store"]
    box = store.secret_box
    with store.session() as session:
        other_tenant = Tenant(
            name="另一个租户",
            status="active",
            expires_at=datetime.utcnow() + timedelta(days=30),
            db_name="unused_settings_other",
            db_username="unused_settings_other",
            db_password_ciphertext=box.encrypt(
                "unused",
                purpose="tenant-db-password",
            ),
            provisioning_status="active",
        )
        session.add(other_tenant)
        session.flush()
        session.add(
            TenantMember(
                tenant_id=other_tenant.id,
                phone="+8613900139001",
                role="admin",
                status="active",
            )
        )

    response = settings_api_environment["admin_client"].post(
        "/api/settings/members",
        json={"phone": "13900139001", "role": "operator"},
        headers=_csrf(settings_api_environment),
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "PHONE_CONFLICT"


@pytest.mark.parametrize(
    "method,path,payload",
    [
        (
            "post",
            "/api/settings/members",
            {"phone": "13900139003", "role": []},
        ),
        ("patch", "/api/settings/members/{admin_id}", {"role": []}),
    ],
)
def test_member_role_rejects_non_string_json_values(
    settings_api_environment,
    method,
    path,
    payload,
):
    path = path.format(admin_id=settings_api_environment["admin_id"])
    response = getattr(settings_api_environment["admin_client"], method)(
        path,
        json=payload,
        headers=_csrf(settings_api_environment),
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize("payload", [{"role": None}, {"status": None}])
def test_member_patch_rejects_explicit_null_role_or_status(
    settings_api_environment,
    payload,
):
    response = settings_api_environment["admin_client"].patch(
        f"/api/settings/members/{settings_api_environment['operator_id']}",
        json=payload,
        headers=_csrf(settings_api_environment),
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "INVALID_REQUEST"


@pytest.mark.parametrize(
    "payload", [{"status": "disabled"}, {"role": "operator"}]
)
def test_last_active_admin_cannot_be_disabled_or_demoted(
    settings_api_environment,
    payload,
):
    response = settings_api_environment["admin_client"].patch(
        f"/api/settings/members/{settings_api_environment['admin_id']}",
        json=payload,
        headers=_csrf(settings_api_environment),
    )

    assert response.status_code == 409
    assert response.get_json()["code"] == "INVALID_REQUEST"


def test_concurrent_admin_demotions_preserve_one_active_admin(
    settings_api_environment,
):
    store = settings_api_environment["app"].extensions["control_store"]
    with store.session() as session:
        second_admin = TenantMember(
            tenant_id=settings_api_environment["tenant_id"],
            phone="+8613900139002",
            role="admin",
            status="active",
        )
        session.add(second_admin)
        session.flush()
        second_credentials = create_auth_session(
            session,
            kind="tenant",
            subject_id=second_admin.id,
            tenant_id=settings_api_environment["tenant_id"],
        )
        second_admin_id = second_admin.id

    barrier = Barrier(2)

    def demote(member_id, credentials):
        client = _new_client(settings_api_environment["app"], credentials)
        barrier.wait(timeout=5)
        return client.patch(
            f"/api/settings/members/{member_id}",
            json={"role": "operator"},
            headers={"X-CSRF-Token": credentials.csrf_token},
        ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(
                demote,
                settings_api_environment["admin_id"],
                settings_api_environment["admin_credentials"],
            ),
            executor.submit(
                demote,
                second_admin_id,
                second_credentials,
            ),
        )
        statuses = sorted(future.result(timeout=15) for future in futures)

    assert statuses == [200, 409]
    with store.session() as session:
        active_admins = session.query(TenantMember).filter_by(
            tenant_id=settings_api_environment["tenant_id"],
            role="admin",
            status="active",
        ).count()
    assert active_admins == 1


@pytest.mark.parametrize(
    "payload",
    [
        {"province": "", "city": "深圳市"},
        {"province": "广东省", "city": ""},
        {"city": "深圳市"},
        {"province": "广东省"},
    ],
)
def test_warehouse_requires_nonempty_province_and_city(
    settings_api_environment,
    payload,
):
    response = settings_api_environment["admin_client"].post(
        "/api/settings/warehouses",
        json=payload,
        headers=_csrf(settings_api_environment),
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "INVALID_REQUEST"


def test_warehouse_default_name_tracks_location_until_customized(
    settings_api_environment,
):
    warehouse = _create_warehouse(settings_api_environment)
    assert warehouse["name"] == "广东省深圳市仓库"

    tracked = settings_api_environment["admin_client"].patch(
        f"/api/settings/warehouses/{warehouse['id']}",
        json={"city": "广州市"},
        headers=_csrf(settings_api_environment),
    )
    assert tracked.status_code == 200
    assert tracked.get_json()["data"]["name"] == "广东省广州市仓库"

    custom = settings_api_environment["admin_client"].patch(
        f"/api/settings/warehouses/{warehouse['id']}",
        json={"name": "华南维修仓"},
        headers=_csrf(settings_api_environment),
    )
    assert custom.status_code == 200

    preserved = settings_api_environment["admin_client"].patch(
        f"/api/settings/warehouses/{warehouse['id']}",
        json={"province": "福建省", "city": "厦门市"},
        headers=_csrf(settings_api_environment),
    )
    assert preserved.status_code == 200
    assert preserved.get_json()["data"]["name"] == "华南维修仓"


def test_create_rejects_overlong_generated_name_without_writing(
    settings_api_environment,
):
    response = settings_api_environment["admin_client"].post(
        "/api/settings/warehouses",
        json={"province": "省" * 50, "city": "市" * 50},
        headers=_csrf(settings_api_environment),
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "INVALID_REQUEST"
    with settings_api_environment["tenant_engine"].connect() as connection:
        assert connection.execute(
            text("SELECT COUNT(*) FROM warehouses")
        ).scalar_one() == 0


def test_update_rejects_overlong_automatic_name_but_preserves_custom_name(
    settings_api_environment,
):
    automatic = _create_warehouse(settings_api_environment)
    custom_response = settings_api_environment["admin_client"].post(
        "/api/settings/warehouses",
        json={
            "province": "广东省",
            "city": "深圳市",
            "name": "华南自定义仓",
        },
        headers=_csrf(settings_api_environment),
    )
    assert custom_response.status_code == 201
    custom = custom_response.get_json()["data"]
    oversized_location = {"province": "省" * 50, "city": "市" * 50}

    rejected = settings_api_environment["admin_client"].patch(
        f"/api/settings/warehouses/{automatic['id']}",
        json=oversized_location,
        headers=_csrf(settings_api_environment),
    )
    preserved = settings_api_environment["admin_client"].patch(
        f"/api/settings/warehouses/{custom['id']}",
        json=oversized_location,
        headers=_csrf(settings_api_environment),
    )

    assert rejected.status_code == 400
    assert rejected.get_json()["code"] == "INVALID_REQUEST"
    assert preserved.status_code == 200
    assert preserved.get_json()["data"]["name"] == "华南自定义仓"
    listed = settings_api_environment["admin_client"].get(
        "/api/settings/warehouses"
    ).get_json()["data"]
    stored_automatic = next(
        row for row in listed if row["id"] == automatic["id"]
    )
    assert stored_automatic["province"] == "广东省"
    assert stored_automatic["city"] == "深圳市"
    assert stored_automatic["name"] == "广东省深圳市仓库"


def test_warehouse_delete_is_not_supported(settings_api_environment):
    warehouse = _create_warehouse(settings_api_environment)
    response = settings_api_environment["admin_client"].delete(
        f"/api/settings/warehouses/{warehouse['id']}",
        headers=_csrf(settings_api_environment),
    )
    assert response.status_code == 405


def test_sf_config_upserts_per_warehouse_and_partner_can_repeat(
    settings_api_environment,
):
    first = _create_warehouse(settings_api_environment)
    second = _create_warehouse(
        settings_api_environment, province="浙江省", city="杭州市"
    )
    payload = {
        "partner_id": "shared-partner",
        "checkword": "first-checkword",
        "monthly_card": "first-monthly-card",
        "test_mode": True,
        "sender_name": "测试寄件人",
        "sender_phone": "13800138000",
        "sender_address": "科技园一号",
    }
    first_response = settings_api_environment["admin_client"].put(
        f"/api/settings/warehouses/{first['id']}/sf",
        json=payload,
        headers=_csrf(settings_api_environment),
    )
    second_response = settings_api_environment["admin_client"].put(
        f"/api/settings/warehouses/{second['id']}/sf",
        json={**payload, "checkword": "second-checkword"},
        headers=_csrf(settings_api_environment),
    )
    assert first_response.status_code == second_response.status_code == 200
    assert first_response.get_json()["data"]["partner_id"] == "shared-partner"
    assert second_response.get_json()["data"]["partner_id"] == "shared-partner"
    with settings_api_environment["tenant_engine"].connect() as connection:
        before = connection.execute(
            text(
                "SELECT checkword_ciphertext, monthly_card_ciphertext "
                "FROM warehouse_sf_configs WHERE warehouse_id = :id"
            ),
            {"id": first["id"]},
        ).one()
    box = SecretBox.from_base64(TEST_MASTER_KEY)
    assert box.decrypt(
        before.checkword_ciphertext,
        purpose="warehouse-sf-checkword",
    ) == "first-checkword"
    assert box.decrypt(
        before.monthly_card_ciphertext,
        purpose="warehouse-sf-monthly-card",
    ) == "first-monthly-card"

    unchanged = settings_api_environment["admin_client"].put(
        f"/api/settings/warehouses/{first['id']}/sf",
        json={"partner_id": "updated", "checkword": "", "monthly_card": ""},
        headers=_csrf(settings_api_environment),
    )
    assert unchanged.status_code == 200
    assert unchanged.get_json()["data"]["checkword_configured"] is True
    assert unchanged.get_json()["data"]["monthly_card_configured"] is True
    with settings_api_environment["tenant_engine"].connect() as connection:
        after = connection.execute(
            text(
                "SELECT checkword_ciphertext, monthly_card_ciphertext "
                "FROM warehouse_sf_configs WHERE warehouse_id = :id"
            ),
            {"id": first["id"]},
        ).one()
    assert after == before

    first_empty = settings_api_environment["admin_client"].put(
        f"/api/settings/warehouses/{second['id']}/sf",
        json={"checkword": "", "monthly_card": ""},
        headers=_csrf(settings_api_environment),
    )
    assert first_empty.status_code == 200
    assert first_empty.get_json()["data"]["monthly_card_configured"] is True


def test_first_empty_secrets_remain_unconfigured_and_kuaimai_keeps_secret(
    settings_api_environment,
):
    warehouse = _create_warehouse(settings_api_environment)
    empty_sf = settings_api_environment["admin_client"].put(
        f"/api/settings/warehouses/{warehouse['id']}/sf",
        json={"checkword": "", "monthly_card": ""},
        headers=_csrf(settings_api_environment),
    )
    empty_kuaimai = settings_api_environment["admin_client"].put(
        f"/api/settings/warehouses/{warehouse['id']}/kuaimai",
        json={"app_secret": ""},
        headers=_csrf(settings_api_environment),
    )
    assert empty_sf.get_json()["data"]["checkword_configured"] is False
    assert empty_sf.get_json()["data"]["monthly_card_configured"] is False
    assert empty_kuaimai.get_json()["data"]["app_secret_configured"] is False

    configured = settings_api_environment["admin_client"].put(
        f"/api/settings/warehouses/{warehouse['id']}/kuaimai",
        json={
            "app_id": "kuaimai-app",
            "app_secret": "kuaimai-secret-value",
            "printer_sn": "PRINTER-001",
        },
        headers=_csrf(settings_api_environment),
    )
    assert configured.status_code == 200
    with settings_api_environment["tenant_engine"].connect() as connection:
        secret_before = connection.execute(
            text(
                "SELECT app_secret_ciphertext "
                "FROM warehouse_kuaimai_configs WHERE warehouse_id = :id"
            ),
            {"id": warehouse["id"]},
        ).scalar_one()
    assert SecretBox.from_base64(TEST_MASTER_KEY).decrypt(
        secret_before,
        purpose="warehouse-kuaimai-app-secret",
    ) == "kuaimai-secret-value"
    retained = settings_api_environment["admin_client"].put(
        f"/api/settings/warehouses/{warehouse['id']}/kuaimai",
        json={"app_id": "kuaimai-app-2", "app_secret": ""},
        headers=_csrf(settings_api_environment),
    )
    assert retained.get_json()["data"]["app_secret_configured"] is True
    assert retained.get_json()["data"]["printer_sn"] == "PRINTER-001"
    with settings_api_environment["tenant_engine"].connect() as connection:
        secret_after = connection.execute(
            text(
                "SELECT app_secret_ciphertext "
                "FROM warehouse_kuaimai_configs WHERE warehouse_id = :id"
            ),
            {"id": warehouse["id"]},
        ).scalar_one()
    assert secret_after == secret_before


def _run_concurrent_config_puts(
    environment,
    endpoint,
    config_table,
    payloads,
):
    barrier = Barrier(2)
    locking_query_seen = Event()

    def synchronize_config_race(
        _connection,
        _cursor,
        statement,
        _parameters,
        _context,
        _executemany,
    ):
        normalized = " ".join(statement.lower().split())
        if "from warehouses" in normalized and "for update" in normalized:
            locking_query_seen.set()
            barrier.wait(timeout=10)
        elif (
            not locking_query_seen.is_set()
            and f"from {config_table}" in normalized
        ):
            barrier.wait(timeout=10)

    def put_config(payload):
        client = _new_client(
            environment["app"], environment["admin_credentials"]
        )
        return client.put(
            endpoint,
            json=payload,
            headers=_csrf(environment),
        )

    event.listen(Engine, "before_cursor_execute", synchronize_config_race)
    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(put_config, body) for body in payloads]
            return [future.result(timeout=20) for future in futures]
    finally:
        event.remove(
            Engine, "before_cursor_execute", synchronize_config_race
        )


def test_concurrent_sf_upserts_are_serialized_and_redacted(
    settings_api_environment,
    caplog,
):
    warehouse = _create_warehouse(settings_api_environment)
    payloads = (
        {
            "partner_id": "partner-a",
            "checkword": "sf-checkword-sensitive-A9x2",
            "monthly_card": "sf-monthly-sensitive-A7q4",
            "sender_name": "寄件人A",
        },
        {
            "partner_id": "partner-b",
            "checkword": "sf-checkword-sensitive-B8m3",
            "monthly_card": "sf-monthly-sensitive-B6p5",
            "sender_name": "寄件人B",
        },
    )
    endpoint = f"/api/settings/warehouses/{warehouse['id']}/sf"

    with caplog.at_level(logging.DEBUG):
        responses = _run_concurrent_config_puts(
            settings_api_environment,
            endpoint,
            "warehouse_sf_configs",
            payloads,
        )

    assert [response.status_code for response in responses] == [200, 200]
    with settings_api_environment["tenant_engine"].connect() as connection:
        rows = connection.execute(
            text(
                "SELECT partner_id, checkword_ciphertext, "
                "monthly_card_ciphertext, sender_name "
                "FROM warehouse_sf_configs WHERE warehouse_id = :id"
            ),
            {"id": warehouse["id"]},
        ).all()
    assert len(rows) == 1
    row = rows[0]
    box = SecretBox.from_base64(TEST_MASTER_KEY)
    final_values = (
        row.partner_id,
        box.decrypt(
            row.checkword_ciphertext, purpose="warehouse-sf-checkword"
        ),
        box.decrypt(
            row.monthly_card_ciphertext,
            purpose="warehouse-sf-monthly-card",
        ),
        row.sender_name,
    )
    assert final_values in {
        (
            payload["partner_id"],
            payload["checkword"],
            payload["monthly_card"],
            payload["sender_name"],
        )
        for payload in payloads
    }
    serialized = json.dumps(
        [response.get_json() for response in responses], ensure_ascii=False
    )
    for payload in payloads:
        for field in ("checkword", "monthly_card"):
            assert payload[field] not in serialized
            assert payload[field] not in caplog.text
    assert "ciphertext" not in serialized


def test_concurrent_kuaimai_upserts_are_serialized_and_redacted(
    settings_api_environment,
    caplog,
):
    warehouse = _create_warehouse(settings_api_environment)
    payloads = (
        {
            "app_id": "kuaimai-a",
            "app_secret": "kuaimai-sensitive-A2v7",
            "printer_sn": "PRINTER-A",
        },
        {
            "app_id": "kuaimai-b",
            "app_secret": "kuaimai-sensitive-B3n8",
            "printer_sn": "PRINTER-B",
        },
    )
    endpoint = f"/api/settings/warehouses/{warehouse['id']}/kuaimai"

    with caplog.at_level(logging.DEBUG):
        responses = _run_concurrent_config_puts(
            settings_api_environment,
            endpoint,
            "warehouse_kuaimai_configs",
            payloads,
        )

    assert [response.status_code for response in responses] == [200, 200]
    with settings_api_environment["tenant_engine"].connect() as connection:
        rows = connection.execute(
            text(
                "SELECT app_id, app_secret_ciphertext, printer_sn "
                "FROM warehouse_kuaimai_configs WHERE warehouse_id = :id"
            ),
            {"id": warehouse["id"]},
        ).all()
    assert len(rows) == 1
    row = rows[0]
    final_values = (
        row.app_id,
        SecretBox.from_base64(TEST_MASTER_KEY).decrypt(
            row.app_secret_ciphertext,
            purpose="warehouse-kuaimai-app-secret",
        ),
        row.printer_sn,
    )
    assert final_values in {
        (payload["app_id"], payload["app_secret"], payload["printer_sn"])
        for payload in payloads
    }
    serialized = json.dumps(
        [response.get_json() for response in responses], ensure_ascii=False
    )
    for payload in payloads:
        assert payload["app_secret"] not in serialized
        assert payload["app_secret"] not in caplog.text
    assert "ciphertext" not in serialized


def test_config_database_errors_are_rolled_back_and_redacted(
    settings_api_environment,
    caplog,
):
    first = _create_warehouse(settings_api_environment)
    second = _create_warehouse(
        settings_api_environment, province="浙江省", city="杭州市"
    )
    client = settings_api_environment["admin_client"]
    headers = _csrf(settings_api_environment)
    seeded = client.put(
        f"/api/settings/warehouses/{first['id']}/sf",
        json={"partner_id": "duplicate-for-error-test"},
        headers=headers,
    )
    assert seeded.status_code == 200

    with settings_api_environment["tenant_engine"].begin() as connection:
        connection.exec_driver_sql(
            "CREATE UNIQUE INDEX uq_test_sf_partner "
            "ON warehouse_sf_configs (partner_id)"
        )
        connection.exec_driver_sql(
            "ALTER TABLE warehouse_kuaimai_configs "
            "MODIFY app_id VARCHAR(3) NULL"
        )
    sf_secret = "integrity-sensitive-sf-Z8k1"
    kuaimai_secret = "data-error-sensitive-kuaimai-Y7j2"
    try:
        with caplog.at_level(logging.DEBUG):
            integrity_response = client.put(
                f"/api/settings/warehouses/{second['id']}/sf",
                json={
                    "partner_id": "duplicate-for-error-test",
                    "checkword": sf_secret,
                },
                headers=headers,
            )
            data_response = client.put(
                f"/api/settings/warehouses/{second['id']}/kuaimai",
                json={"app_id": "too-long", "app_secret": kuaimai_secret},
                headers=headers,
            )
    finally:
        with settings_api_environment["tenant_engine"].begin() as connection:
            connection.exec_driver_sql(
                "DROP INDEX uq_test_sf_partner ON warehouse_sf_configs"
            )
            connection.exec_driver_sql(
                "ALTER TABLE warehouse_kuaimai_configs "
                "MODIFY app_id VARCHAR(100) NULL"
            )

    assert integrity_response.status_code == 409
    assert data_response.status_code == 400
    for response in (integrity_response, data_response):
        serialized = json.dumps(response.get_json(), ensure_ascii=False)
        assert response.get_json()["code"] == "INVALID_REQUEST"
        assert "sql" not in serialized.lower()
        assert "ciphertext" not in serialized.lower()
        assert "secret" not in serialized.lower()
    assert sf_secret not in caplog.text
    assert kuaimai_secret not in caplog.text
    with settings_api_environment["tenant_engine"].connect() as connection:
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM warehouse_sf_configs "
                "WHERE warehouse_id = :id"
            ),
            {"id": second["id"]},
        ).scalar_one() == 0
        assert connection.execute(
            text(
                "SELECT COUNT(*) FROM warehouse_kuaimai_configs "
                "WHERE warehouse_id = :id"
            ),
            {"id": second["id"]},
        ).scalar_one() == 0


def test_settings_responses_never_expose_secret_values_or_ciphertexts(
    settings_api_environment,
):
    warehouse = _create_warehouse(settings_api_environment)
    secret_values = (
        "do-not-return-checkword-x9K2",
        "do-not-return-monthly-card-q7V4",
        "do-not-return-app-secret-m3P8",
    )
    sf = settings_api_environment["admin_client"].put(
        f"/api/settings/warehouses/{warehouse['id']}/sf",
        json={
            "checkword": secret_values[0],
            "monthly_card": secret_values[1],
            "partner_id": "partner-public",
        },
        headers=_csrf(settings_api_environment),
    )
    kuaimai = settings_api_environment["admin_client"].put(
        f"/api/settings/warehouses/{warehouse['id']}/kuaimai",
        json={"app_secret": secret_values[2], "app_id": "app-public"},
        headers=_csrf(settings_api_environment),
    )
    listed = settings_api_environment["admin_client"].get(
        "/api/settings/warehouses"
    )

    serialized = json.dumps(
        [sf.get_json(), kuaimai.get_json(), listed.get_json()],
        ensure_ascii=False,
    )
    for value in secret_values:
        assert value not in serialized
        assert value[-4:] not in serialized
    assert "ciphertext" not in serialized
    for response in (sf, kuaimai, listed):
        assert response.status_code == 200


def test_admin_manages_xianyu_shop_without_exposing_or_clearing_secret(
    settings_api_environment,
):
    client = settings_api_environment["admin_client"]
    headers = _csrf(settings_api_environment)
    secret = "xianyu-secret-never-return"
    created_response = client.post("/api/settings/xianyu-shops", json={
        "name": "深圳店", "app_key": "app-key",
        "app_secret": secret, "is_active": True,
    }, headers=headers)
    assert created_response.status_code == 201
    shop = created_response.get_json()["data"]
    assert shop["app_secret_configured"] is True
    assert secret not in json.dumps(shop)
    assert "ciphertext" not in json.dumps(shop)

    path = f"/api/settings/xianyu-shops/{shop['id']}"
    updated = client.patch(path, json={"name": "深圳主店", "app_secret": ""}, headers=headers)
    assert updated.status_code == 200
    with settings_api_environment["tenant_engine"].connect() as connection:
        ciphertext = connection.execute(
            text("SELECT app_secret_ciphertext FROM xianyu_shops WHERE id=:id"),
            {"id": shop["id"]},
        ).scalar_one()
    assert SecretBox.from_base64(TEST_MASTER_KEY).decrypt(
        ciphertext, purpose="xianyu-shop-app-secret"
    ) == secret

    forbidden = client.patch(path, json={"seller_id": "forbidden"}, headers=headers)
    assert forbidden.status_code == 400
