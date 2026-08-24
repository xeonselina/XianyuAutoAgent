"""Real MariaDB coverage for tenant member and warehouse settings."""

import base64
import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, delete, inspect, text
from sqlalchemy.engine import make_url

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
