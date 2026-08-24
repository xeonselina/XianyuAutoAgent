import base64
import os
from datetime import datetime, timedelta

import pytest
from flask import g
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import make_url

from app import create_app, db
from app.control.models import (
    AuthSession,
    ControlBase,
    Tenant,
    TenantMember,
)
from app.control.store import ControlStore
from app.crypto import SecretBox, hash_token
from config import TestingConfig


DATABASE_ENVIRONMENTS = {
    "TEST_CONTROL_DATABASE_URL": "control_saas_test",
    "TEST_TENANT_DATABASE_URL_A": "tenant_a_saas_test",
    "TEST_TENANT_DATABASE_URL_B": "tenant_b_saas_test",
}
TEST_MASTER_KEY = base64.b64encode(bytes(range(32))).decode("ascii")


def _required_test_url(environment_name):
    raw_url = os.environ.get(environment_name)
    if not raw_url:
        pytest.skip(f"{environment_name} is required for MariaDB test")

    parsed = make_url(raw_url)
    expected_database = DATABASE_ENVIRONMENTS[environment_name]
    if parsed.database != expected_database:
        raise RuntimeError(
            f"{environment_name} must target {expected_database}"
        )
    return parsed


def _reset_schema(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
        try:
            preparer = connection.dialect.identifier_preparer
            for table_name in inspect(connection).get_table_names():
                quoted_name = preparer.quote_identifier(table_name)
                connection.exec_driver_sql(f"DROP TABLE {quoted_name}")
        finally:
            connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")


def _assert_test_only_grants(connection):
    allowed_databases = set(DATABASE_ENVIRONMENTS.values())
    grants = connection.exec_driver_sql(
        "SHOW GRANTS FOR CURRENT_USER"
    ).scalars()

    for grant in grants:
        normalized = grant.replace("\\_", "_").replace("\\%", "%")
        if normalized.startswith("GRANT USAGE ON *.*"):
            continue
        if any(
            token in normalized
            for database in allowed_databases
            for token in (f"ON `{database}`.*", f"ON {database}.*")
        ):
            continue
        raise RuntimeError("test user has privileges outside named test DBs")


def _create_device_table(engine, device_name):
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE devices (
                id INTEGER NOT NULL PRIMARY KEY,
                name VARCHAR(100) NOT NULL,
                serial_number VARCHAR(100) NULL,
                model VARCHAR(50) NOT NULL,
                model_id INTEGER NULL,
                is_accessory BOOLEAN NOT NULL,
                lifecycle_status VARCHAR(32) NOT NULL,
                lifecycle_reason VARCHAR(255) NULL,
                lifecycle_date DATETIME NULL,
                created_at DATETIME NOT NULL,
                updated_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO devices (
                id, name, serial_number, model, is_accessory,
                lifecycle_status, created_at, updated_at
            ) VALUES (
                1, %s, %s, 'x200u', 0, 'active',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (device_name, f"serial-{device_name}"),
        )


@pytest.fixture(scope="module")
def tenant_databases():
    urls = {
        name: _required_test_url(name)
        for name in DATABASE_ENVIRONMENTS
    }
    tenant_a_url = urls["TEST_TENANT_DATABASE_URL_A"]
    tenant_b_url = urls["TEST_TENANT_DATABASE_URL_B"]
    if (
        tenant_a_url.host,
        tenant_a_url.port,
    ) != (
        tenant_b_url.host,
        tenant_b_url.port,
    ):
        raise RuntimeError("tenant test databases must share host and port")

    engines = {}
    schemas_verified_safe = False
    try:
        engines = {
            name: create_engine(url, pool_pre_ping=True)
            for name, url in urls.items()
        }
        for environment_name, engine in engines.items():
            with engine.connect() as connection:
                current_database = connection.exec_driver_sql(
                    "SELECT DATABASE()"
                ).scalar_one()
                assert current_database == DATABASE_ENVIRONMENTS[
                    environment_name
                ]
                _assert_test_only_grants(connection)
        schemas_verified_safe = True

        for engine in engines.values():
            _reset_schema(engine)

        control_engine = engines["TEST_CONTROL_DATABASE_URL"]
        ControlBase.metadata.create_all(control_engine)
        with control_engine.begin() as connection:
            # The isolated MariaDB fixture intentionally provides one user
            # restricted to all three named test schemas. Task 2 separately
            # verifies the production username uniqueness constraint; drop it
            # only in this disposable control schema so the real registry can
            # authenticate both tenant engines with that shared test user.
            connection.exec_driver_sql(
                "ALTER TABLE tenants "
                "DROP INDEX uq_tenants_db_username"
            )
        _create_device_table(
            engines["TEST_TENANT_DATABASE_URL_A"],
            "tenant-a-device",
        )
        _create_device_table(
            engines["TEST_TENANT_DATABASE_URL_B"],
            "tenant-b-device",
        )

        box = SecretBox.from_base64(TEST_MASTER_KEY)
        store = ControlStore(
            urls["TEST_CONTROL_DATABASE_URL"].render_as_string(
                hide_password=False
            ),
            box,
        )
        expires_at = datetime.utcnow() + timedelta(days=30)
        raw_tokens = {
            "a": "raw-tenant-a-session",
            "b": "raw-tenant-b-session",
        }

        with store.session() as session:
            tenants = {}
            members = {}
            for label, tenant_url in (
                ("a", tenant_a_url),
                ("b", tenant_b_url),
            ):
                tenant = Tenant(
                    name=f"Tenant {label.upper()}",
                    status="active",
                    expires_at=expires_at,
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
                member = TenantMember(
                    tenant_id=tenant.id,
                    phone=(
                        "+8613800138000"
                        if label == "a"
                        else "+8613800138001"
                    ),
                    role="admin",
                    status="active",
                )
                session.add(member)
                session.flush()
                session.add(
                    AuthSession(
                        kind="tenant",
                        subject_id=member.id,
                        tenant_id=tenant.id,
                        token_hash=hash_token(raw_tokens[label]),
                        csrf_token_hash=hash_token(f"csrf-{label}"),
                        expires_at=expires_at,
                    )
                )
                tenants[label] = tenant.id
                members[label] = member.id

        store.dispose()
        yield {
            "urls": urls,
            "tenant_ids": tenants,
            "member_ids": members,
            "raw_tokens": raw_tokens,
        }
    finally:
        for engine in engines.values():
            try:
                if schemas_verified_safe:
                    _reset_schema(engine)
            finally:
                engine.dispose()


@pytest.fixture
def tenant_app(tenant_databases):
    urls = tenant_databases["urls"]
    tenant_a_url = urls["TEST_TENANT_DATABASE_URL_A"]

    class TenantIsolationConfig(TestingConfig):
        AUTH_BYPASS_FOR_TESTS = False
        CONTROL_DATABASE_URL = urls[
            "TEST_CONTROL_DATABASE_URL"
        ].render_as_string(hide_password=False)
        SAAS_MASTER_KEY = TEST_MASTER_KEY
        SQLALCHEMY_DATABASE_URI = tenant_a_url.render_as_string(
            hide_password=False
        )
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
        TENANT_DB_HOST = tenant_a_url.host
        TENANT_DB_PORT = tenant_a_url.port
        TENANT_DB_POOL_SIZE = 2
        API_KEY = "external-test-key"

    application = create_app(TenantIsolationConfig)

    @application.get("/api/_tenant-context")
    def tenant_context_probe():
        return {
            "tenant_id": g.tenant.id,
            "member_id": g.member.id,
        }

    @application.get("/api/_tenant-error")
    def tenant_error_probe():
        db.session.execute(db.text("SELECT 1"))
        raise RuntimeError("request failed after opening tenant session")

    try:
        yield application
    finally:
        with application.app_context():
            db.session.remove()
            for engine in db.engines.values():
                engine.dispose()
        finalizer = application.extensions.get("tenant_resource_finalizer")
        if finalizer is not None and finalizer.alive:
            finalizer()


def _request_as(application, raw_token, path, **kwargs):
    with application.test_client() as client:
        client.set_cookie("tenant_session", raw_token)
        return client.get(path, **kwargs)


def test_same_primary_key_is_isolated(
    tenant_app,
    tenant_databases,
):
    raw_tokens = tenant_databases["raw_tokens"]

    a = _request_as(tenant_app, raw_tokens["a"], "/api/devices/1")
    b = _request_as(tenant_app, raw_tokens["b"], "/api/devices/1")

    assert a.get_json()["data"]["name"] == "tenant-a-device"
    assert b.get_json()["data"]["name"] == "tenant-b-device"

    from app.tenant_context import current_tenant_id

    assert current_tenant_id() is None


def test_business_route_requires_tenant_session(tenant_app):
    response = tenant_app.test_client().get("/api/devices/1")

    assert response.status_code == 401
    assert response.get_json()["code"] == "AUTH_REQUIRED"


def test_valid_session_sets_request_tenant_and_member(
    tenant_app,
    tenant_databases,
):
    response = _request_as(
        tenant_app,
        tenant_databases["raw_tokens"]["a"],
        "/api/_tenant-context",
    )

    assert response.get_json() == {
        "tenant_id": tenant_databases["tenant_ids"]["a"],
        "member_id": tenant_databases["member_ids"]["a"],
    }


@pytest.mark.parametrize(
    (
        "model",
        "object_key",
        "field",
        "value",
        "expected_status",
        "expected_code",
    ),
    [
        (
            Tenant,
            "tenant_ids",
            "status",
            "suspended",
            403,
            "TENANT_SUSPENDED",
        ),
        (
            Tenant,
            "tenant_ids",
            "expires_at",
            datetime(2000, 1, 1),
            403,
            "TENANT_EXPIRED",
        ),
        (
            Tenant,
            "tenant_ids",
            "provisioning_status",
            "failed",
            503,
            "PROVISIONING_FAILED",
        ),
        (
            TenantMember,
            "member_ids",
            "status",
            "disabled",
            401,
            "AUTH_REQUIRED",
        ),
    ],
    ids=["suspended", "expired", "provisioning-failed", "disabled-member"],
)
def test_invalid_tenant_access_state_is_rejected(
    tenant_app,
    tenant_databases,
    model,
    object_key,
    field,
    value,
    expected_status,
    expected_code,
):
    store = tenant_app.extensions["control_store"]
    object_id = tenant_databases[object_key]["a"]
    with store.session() as session:
        record = session.get(model, object_id)
        original = getattr(record, field)
        setattr(record, field, value)

    try:
        response = _request_as(
            tenant_app,
            tenant_databases["raw_tokens"]["a"],
            "/api/devices/1",
        )
    finally:
        with store.session() as session:
            setattr(session.get(model, object_id), field, original)
            if model is TenantMember and field == "status":
                raw_token = tenant_databases["raw_tokens"]["a"]
                existing_session = session.scalar(
                    select(AuthSession).where(
                        AuthSession.token_hash == hash_token(raw_token)
                    )
                )
                if existing_session is None:
                    session.add(
                        AuthSession(
                            kind="tenant",
                            subject_id=object_id,
                            tenant_id=tenant_databases["tenant_ids"]["a"],
                            token_hash=hash_token(raw_token),
                            csrf_token_hash=hash_token("csrf-a"),
                            expires_at=datetime.utcnow()
                            + timedelta(days=30),
                        )
                    )

    assert response.status_code == expected_status
    assert response.get_json()["code"] == expected_code


def test_external_api_keeps_public_exemptions_and_api_key_second_gate(
    tenant_app,
    tenant_databases,
):
    client = tenant_app.test_client()

    assert client.get("/external-api/health").status_code == 200
    assert client.get("/external-api/docs").status_code == 200

    no_session = client.get(
        "/external-api/inventory/available",
        headers={"X-API-Key": "external-test-key"},
    )
    assert no_session.status_code == 401
    assert no_session.get_json()["code"] == "AUTH_REQUIRED"

    missing_api_key = _request_as(
        tenant_app,
        tenant_databases["raw_tokens"]["a"],
        "/external-api/inventory/available",
    )
    assert missing_api_key.status_code == 401
    assert missing_api_key.get_json() == {
        "error": "无效的API密钥",
        "success": False,
    }

    tenant_a = _request_as(
        tenant_app,
        tenant_databases["raw_tokens"]["a"],
        "/external-api/devices",
        headers={"X-API-Key": "external-test-key"},
    )
    tenant_b = _request_as(
        tenant_app,
        tenant_databases["raw_tokens"]["b"],
        "/external-api/devices",
        headers={"X-API-Key": "external-test-key"},
    )
    assert tenant_a.get_json()["data"][0]["name"] == "tenant-a-device"
    assert tenant_b.get_json()["data"][0]["name"] == "tenant-b-device"


@pytest.mark.parametrize("path", ["/api", "/web", "/external-api"])
def test_business_path_roots_require_tenant_session(tenant_app, path):
    response = tenant_app.test_client().get(path)

    assert response.status_code == 401
    assert response.get_json()["code"] == "AUTH_REQUIRED"


def test_context_is_reset_when_tenant_route_raises(
    tenant_app,
    tenant_databases,
):
    with pytest.raises(
        RuntimeError,
        match="request failed after opening tenant session",
    ):
        _request_as(
            tenant_app,
            tenant_databases["raw_tokens"]["a"],
            "/api/_tenant-error",
        )

    from app.tenant_context import current_tenant_id

    assert current_tenant_id() is None


def test_business_session_is_removed_before_context_reset(
    tenant_app,
    tenant_databases,
    monkeypatch,
):
    from app.tenant_context import current_tenant_id

    observed_tenant_ids = []
    original_remove = db.session.remove

    def observe_remove():
        observed_tenant_ids.append(current_tenant_id())
        original_remove()

    monkeypatch.setattr(db.session, "remove", observe_remove)

    response = _request_as(
        tenant_app,
        tenant_databases["raw_tokens"]["a"],
        "/api/devices/1",
    )

    assert response.status_code == 200
    assert observed_tenant_ids[0] == tenant_databases["tenant_ids"]["a"]
