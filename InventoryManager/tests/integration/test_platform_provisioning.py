import base64
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from datetime import datetime, timedelta
from pathlib import Path
from threading import Barrier

import pyotp
import pytest
from alembic import command as alembic_command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session
from werkzeug.security import check_password_hash

from app import create_app, db
from app.auth import create_auth_session
from app.control.models import (
    AuthSession,
    ControlBase,
    PlatformAdmin,
    Tenant,
    TenantMember,
)
from app.models.audit_log import AuditLog
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from config import TestingConfig


TEST_MASTER_KEY = base64.b64encode(bytes(range(32))).decode("ascii")
TEST_PLATFORM_PASSWORD = "platform-admin-test-password"
TEST_TOTP_SECRET = "JBSWY3DPEHPK3PXP"
TEST_DATABASE_PREFIX = "inventory_test_tenant_"
TEST_USER_PREFIX = "im_test_t"
TEST_DATABASE_PATTERN = re.compile(r"^inventory_test_tenant_[0-9]{8}$")
TEST_USER_PATTERN = re.compile(r"^im_test_t[0-9]{8}$")
MIGRATIONS_DIRECTORY = str(
    Path(__file__).resolve().parents[2] / "migrations"
)
KNOWN_DATABASES = {
    "TEST_CONTROL_DATABASE_URL": "control_saas_test",
    "TEST_TENANT_DATABASE_URL_A": "tenant_a_saas_test",
    "TEST_TENANT_DATABASE_URL_B": "tenant_b_saas_test",
}


def _required_test_url(environment_name, expected_database):
    raw_url = os.environ.get(environment_name)
    if not raw_url:
        pytest.skip(f"{environment_name} is required for MariaDB test")
    parsed = make_url(raw_url)
    if (
        parsed.host != "127.0.0.1"
        or parsed.port != 33316
        or parsed.database != expected_database
    ):
        raise RuntimeError(
            f"{environment_name} must use localhost:33316/"
            f"{expected_database}"
        )
    return parsed


def _required_provisioner_url():
    parsed = _required_test_url(
        "TEST_PROVISIONER_DATABASE_URL",
        "mysql",
    )
    if parsed.username != "root":
        raise RuntimeError(
            "TEST_PROVISIONER_DATABASE_URL must use the isolated root user"
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


def _dynamic_resources(root_engine):
    with root_engine.connect() as connection:
        databases = [
            name
            for name in connection.execute(
                text(
                    "SELECT SCHEMA_NAME FROM information_schema.SCHEMATA "
                    "WHERE SCHEMA_NAME LIKE :prefix"
                ),
                {"prefix": f"{TEST_DATABASE_PREFIX}%"},
            ).scalars()
            if name.startswith(TEST_DATABASE_PREFIX)
        ]
        users = [
            name
            for name in connection.execute(
                text(
                    "SELECT User FROM mysql.user "
                    "WHERE Host = '%' AND User LIKE :prefix"
                ),
                {"prefix": f"{TEST_USER_PREFIX}%"},
            ).scalars()
            if name.startswith(TEST_USER_PREFIX)
        ]
    return databases, users


def _cleanup_dynamic_resources(root_engine):
    databases, users = _dynamic_resources(root_engine)
    if any(not TEST_DATABASE_PATTERN.fullmatch(name) for name in databases):
        raise RuntimeError("refusing to drop an unexpected test database")
    if any(not TEST_USER_PATTERN.fullmatch(name) for name in users):
        raise RuntimeError("refusing to drop an unexpected test user")

    with root_engine.begin() as connection:
        for username in users:
            connection.execute(
                text(f"DROP USER IF EXISTS `{username}`@'%'")
            )
        for database_name in databases:
            connection.exec_driver_sql(
                f"DROP DATABASE IF EXISTS `{database_name}`"
            )


def _assert_known_user_grants(connection):
    allowed_databases = set(KNOWN_DATABASES.values())
    grants = list(
        connection.exec_driver_sql(
            "SHOW GRANTS FOR CURRENT_USER"
        ).scalars()
    )
    for grant in grants:
        normalized = grant.replace("\\_", "_").replace("\\%", "%")
        if normalized.startswith("GRANT USAGE ON *.*"):
            continue
        if any(
            f"ON `{database}`.*" in normalized
            or f"ON {database}.*" in normalized
            for database in allowed_databases
        ):
            continue
        raise RuntimeError("known test user has an unexpected database grant")


@pytest.fixture
def platform_environment():
    urls = {
        name: _required_test_url(name, database)
        for name, database in KNOWN_DATABASES.items()
    }
    provisioner_url = _required_provisioner_url()
    root_engine = create_engine(provisioner_url, pool_pre_ping=True)
    known_engines = {
        name: create_engine(url, pool_pre_ping=True)
        for name, url in urls.items()
    }
    application = None
    schemas_verified_safe = False

    try:
        with root_engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT DATABASE()"
            ).scalar_one() == "mysql"
        for environment_name, engine in known_engines.items():
            with engine.connect() as connection:
                expected_database = KNOWN_DATABASES[environment_name]
                assert connection.exec_driver_sql(
                    "SELECT DATABASE()"
                ).scalar_one() == expected_database
                _assert_known_user_grants(connection)
        schemas_verified_safe = True

        _cleanup_dynamic_resources(root_engine)
        for engine in known_engines.values():
            _reset_schema(engine)
        ControlBase.metadata.create_all(
            known_engines["TEST_CONTROL_DATABASE_URL"]
        )

        control_url = urls[
            "TEST_CONTROL_DATABASE_URL"
        ].render_as_string(hide_password=False)
        tenant_url = urls[
            "TEST_TENANT_DATABASE_URL_A"
        ].render_as_string(hide_password=False)
        provisioner_database_url = provisioner_url.render_as_string(
            hide_password=False
        )

        class PlatformTestingConfig(TestingConfig):
            AUTH_BYPASS_FOR_TESTS = False
            CONTROL_DATABASE_URL = control_url
            SAAS_MASTER_KEY = TEST_MASTER_KEY
            SQLALCHEMY_DATABASE_URI = tenant_url
            SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
            TENANT_DB_HOST = "127.0.0.1"
            TENANT_DB_PORT = 33316
            PROVISIONER_DATABASE_URL = provisioner_database_url
            TENANT_DB_NAME_PREFIX = TEST_DATABASE_PREFIX
            TENANT_DB_USER_PREFIX = TEST_USER_PREFIX
            BUSINESS_MIGRATIONS_DIRECTORY = MIGRATIONS_DIRECTORY
            SESSION_COOKIE_SECURE = True
            CORS_ORIGINS = []

        application = create_app(PlatformTestingConfig)
        yield {
            "app": application,
            "root_engine": root_engine,
            "urls": urls,
        }
    finally:
        if application is not None:
            with application.app_context():
                db.session.remove()
                for engine in db.engines.values():
                    engine.dispose()
            finalizer = application.extensions.get(
                "tenant_resource_finalizer"
            )
            if finalizer is not None and finalizer.alive:
                finalizer()
            provisioner = application.extensions.get("tenant_provisioner")
            if provisioner is not None:
                provisioner.dispose()

        if schemas_verified_safe:
            _cleanup_dynamic_resources(root_engine)
            assert _dynamic_resources(root_engine) == ([], [])
            for engine in known_engines.values():
                _reset_schema(engine)
        for engine in known_engines.values():
            engine.dispose()
        root_engine.dispose()


def _migration_head():
    alembic_config = AlembicConfig()
    alembic_config.set_main_option(
        "script_location",
        MIGRATIONS_DIRECTORY,
    )
    return ScriptDirectory.from_config(alembic_config).get_current_head()


def _run_migration_revision(database_url, revision):
    migration_app = Flask("task5_partial_migration")
    migration_app.config.update(
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    )
    migration_db = SQLAlchemy()
    migration = Migrate()
    migration_db.init_app(migration_app)
    migration.init_app(
        migration_app,
        migration_db,
        directory=MIGRATIONS_DIRECTORY,
    )
    with migration_app.app_context():
        try:
            config = migration.get_config(MIGRATIONS_DIRECTORY)
            config.attributes["programmatic_provisioning"] = True
            alembic_command.upgrade(config, revision)
        finally:
            migration_db.session.remove()
            migration_db.engine.dispose()


def _bootstrap_platform_admin(environment, username="platform-admin"):
    runner = environment["app"].test_cli_runner()
    result = runner.invoke(
        args=["bootstrap-platform-admin", "--username", username],
        input=(
            f"{TEST_PLATFORM_PASSWORD}\n"
            f"{TEST_PLATFORM_PASSWORD}\n"
            f"{TEST_TOTP_SECRET}\n"
        ),
    )
    assert result.exit_code == 0, result.output
    return result


def _platform_login(environment):
    client = environment["app"].test_client()
    response = client.post(
        "/platform/auth/login",
        json={
            "username": "platform-admin",
            "password": TEST_PLATFORM_PASSWORD,
            "totp": pyotp.TOTP(TEST_TOTP_SECRET).now(),
        },
    )
    assert response.status_code == 200
    return client, response.get_json()["data"]["csrf_token"], response


def _create_tenant(client, csrf_token, phone="13800138000", name="Acme"):
    return client.post(
        "/platform/api/tenants",
        json={
            "name": name,
            "admin_phone": phone,
            "expires_at": (
                datetime.utcnow() + timedelta(days=30)
            ).replace(microsecond=0).isoformat() + "Z",
        },
        headers={"X-CSRF-Token": csrf_token},
    )


def _tenant_snapshot(store, tenant_id):
    with store.session() as session:
        tenant = session.get(Tenant, tenant_id)
        member = session.scalar(
            select(TenantMember).where(
                TenantMember.tenant_id == tenant_id,
                TenantMember.role == "admin",
            )
        )
        return {
            "tenant_id": tenant.id,
            "db_name": tenant.db_name,
            "db_username": tenant.db_username,
            "db_password_ciphertext": tenant.db_password_ciphertext,
            "provisioning_status": tenant.provisioning_status,
            "provisioning_error": tenant.provisioning_error,
            "member_id": member.id,
            "member_phone": member.phone,
        }


def _assert_safe_tenant_payload(payload):
    forbidden_keys = {
        "db_username",
        "db_password",
        "db_password_ciphertext",
        "password",
        "password_hash",
        "totp_secret_ciphertext",
    }

    def visit(value):
        if isinstance(value, dict):
            assert forbidden_keys.isdisjoint(value)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, list):
            for nested in value:
                visit(nested)

    visit(payload)


def _tenant_engine(environment, snapshot):
    store = environment["app"].extensions["control_store"]
    password = store.secret_box.decrypt(
        snapshot["db_password_ciphertext"],
        purpose="tenant-db-password",
    )
    return create_engine(
        URL.create(
            "mysql+pymysql",
            username=snapshot["db_username"],
            password=password,
            host="127.0.0.1",
            port=33316,
            database=snapshot["db_name"],
        ),
        pool_pre_ping=True,
    )


def _root_tenant_engine(environment, database_name):
    if not TEST_DATABASE_PATTERN.fullmatch(database_name):
        raise RuntimeError("refusing unexpected root tenant database")
    return create_engine(
        environment["root_engine"].url.set(database=database_name),
        pool_pre_ping=True,
    )


def _seed_legacy_init_schema(environment, snapshot):
    engine = _root_tenant_engine(environment, snapshot["db_name"])
    try:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                CREATE TABLE devices (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    name VARCHAR(100) NOT NULL,
                    serial_number VARCHAR(100) UNIQUE,
                    status ENUM(
                        'idle', 'pending_ship', 'renting',
                        'pending_return', 'returned', 'offline'
                    ) DEFAULT 'idle',
                    location VARCHAR(100),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE rentals (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    device_id INT NOT NULL,
                    start_date DATE NOT NULL,
                    end_date DATE NOT NULL,
                    ship_out_time DATETIME,
                    ship_in_time DATETIME,
                    customer_name VARCHAR(100) NOT NULL,
                    customer_phone VARCHAR(20),
                    destination TEXT,
                    ship_out_tracking_no VARCHAR(50),
                    ship_in_tracking_no VARCHAR(50),
                    status ENUM(
                        'pending', 'active', 'completed',
                        'cancelled', 'overdue'
                    ) DEFAULT 'pending',
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                        ON UPDATE CURRENT_TIMESTAMP,
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                        ON DELETE CASCADE
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            connection.exec_driver_sql(
                """
                CREATE TABLE audit_logs (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    device_id INT,
                    rental_id INT,
                    action VARCHAR(50) NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    user_id VARCHAR(100),
                    `timestamp` DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (device_id) REFERENCES devices(id)
                        ON DELETE SET NULL,
                    FOREIGN KEY (rental_id) REFERENCES rentals(id)
                        ON DELETE SET NULL
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            for statement in (
                "CREATE INDEX idx_devices_status ON devices(status)",
                "CREATE INDEX idx_rentals_device_id ON rentals(device_id)",
                "CREATE INDEX idx_rentals_dates ON rentals(start_date, end_date)",
                "CREATE INDEX idx_rentals_status ON rentals(status)",
                "CREATE INDEX idx_rentals_tracking ON rentals("
                "ship_out_tracking_no, ship_in_tracking_no)",
                "CREATE INDEX idx_audit_logs_device_id ON audit_logs(device_id)",
                "CREATE INDEX idx_audit_logs_rental_id ON audit_logs(rental_id)",
                "CREATE INDEX idx_audit_logs_timestamp ON audit_logs(`timestamp`)",
            ):
                connection.exec_driver_sql(statement)
            connection.exec_driver_sql(
                "INSERT INTO devices (name, serial_number) "
                "VALUES ('Legacy device', 'legacy-device')"
            )
            connection.exec_driver_sql(
                "INSERT INTO rentals ("
                "device_id, start_date, end_date, customer_name"
                ") VALUES (1, '2026-01-01', '2026-01-02', 'Legacy customer')"
            )
            connection.exec_driver_sql(
                "INSERT INTO audit_logs ("
                "device_id, rental_id, action, old_value, new_value, user_id"
                ") VALUES (1, 1, 'legacy_action', 'before', 'after', 'legacy')"
            )
    finally:
        engine.dispose()


def _smoke_current_business_models(environment, snapshot):
    engine = _tenant_engine(environment, snapshot)
    try:
        with Session(engine) as session:
            device_model = DeviceModel(
                name=f"task5-smoke-{snapshot['tenant_id']}",
                display_name="Task 5 smoke model",
                is_active=True,
                is_accessory=False,
            )
            session.add(device_model)
            session.flush()
            device = Device(
                name="Task 5 smoke device",
                serial_number=f"task5-smoke-{snapshot['tenant_id']}",
                model="task5-smoke",
                model_id=device_model.id,
                is_accessory=False,
                lifecycle_status="active",
            )
            session.add(device)
            session.flush()
            rental = Rental(
                device_id=device.id,
                start_date=datetime(2026, 1, 1).date(),
                end_date=datetime(2026, 1, 2).date(),
                customer_name="Task 5 smoke customer",
                status="not_shipped",
                lens_combo="bare",
            )
            session.add(rental)
            session.commit()
            device_id = device.id
            rental_id = rental.id

        with Session(engine) as session:
            session.add(
                AuditLog(
                    device_id=device_id,
                    rental_id=rental_id,
                    action="task5_smoke",
                    resource_type="rental",
                    resource_id=str(rental_id),
                    description="Current audit schema smoke",
                    details={"source": "task5"},
                    ip_address="127.0.0.1",
                    user_agent="task5-test",
                )
            )
            session.commit()
            audit = session.scalar(
                select(AuditLog).where(AuditLog.action == "task5_smoke")
            )
            assert audit.resource_type == "rental"
            assert audit.details == {"source": "task5"}
            assert session.get(Device, device_id).model == "task5-smoke"
            assert session.get(Rental, rental_id).damage_note is None
    finally:
        engine.dispose()


def test_default_identifier_formatter_is_exact_and_rejects_unsafe_prefixes():
    from app.provisioning import format_tenant_identifiers

    assert format_tenant_identifiers(42) == (
        "inventory_tenant_00000042",
        "im_t00000042",
    )
    with pytest.raises(ValueError, match="identifier"):
        format_tenant_identifiers(
            42,
            database_prefix="inventory_test_tenant_;drop_",
            user_prefix=TEST_USER_PREFIX,
        )


def test_bootstrap_is_interactive_secret_safe_and_first_admin_only(
    platform_environment,
):
    app = platform_environment["app"]
    runner = app.test_cli_runner()
    help_result = runner.invoke(
        args=["bootstrap-platform-admin", "--help"]
    )

    assert help_result.exit_code == 0
    assert "--password" not in help_result.output
    first = _bootstrap_platform_admin(platform_environment)
    assert TEST_PLATFORM_PASSWORD not in first.output
    assert TEST_TOTP_SECRET not in first.output

    store = app.extensions["control_store"]
    with store.session() as session:
        admins = session.scalars(select(PlatformAdmin)).all()
        assert len(admins) == 1
        assert admins[0].username == "platform-admin"
        assert admins[0].password_hash != TEST_PLATFORM_PASSWORD
        assert check_password_hash(
            admins[0].password_hash,
            TEST_PLATFORM_PASSWORD,
        )
        assert admins[0].totp_secret_ciphertext != TEST_TOTP_SECRET
        assert store.secret_box.decrypt(
            admins[0].totp_secret_ciphertext,
            purpose="platform-totp-secret",
        ) == TEST_TOTP_SECRET

    second = runner.invoke(
        args=["bootstrap-platform-admin", "--username", "second-admin"],
        input=(
            f"{TEST_PLATFORM_PASSWORD}\n"
            f"{TEST_PLATFORM_PASSWORD}\n"
            f"{TEST_TOTP_SECRET}\n"
        ),
    )
    assert second.exit_code != 0
    assert TEST_PLATFORM_PASSWORD not in second.output
    assert TEST_TOTP_SECRET not in second.output
    with store.session() as session:
        assert len(session.scalars(select(PlatformAdmin)).all()) == 1


def test_platform_auth_rotates_csrf_and_cannot_cross_session_boundaries(
    platform_environment,
):
    _bootstrap_platform_admin(platform_environment)
    app = platform_environment["app"]

    wrong_totp = app.test_client().post(
        "/platform/auth/login",
        json={
            "username": "platform-admin",
            "password": TEST_PLATFORM_PASSWORD,
            "totp": "000000",
        },
    )
    assert wrong_totp.status_code == 401
    assert wrong_totp.get_json()["code"] == "AUTH_INVALID"

    client, first_csrf, login_response = _platform_login(
        platform_environment
    )
    cookie = login_response.headers["Set-Cookie"]
    assert "platform_session=" in cookie
    assert "Path=/platform" in cookie
    assert "Max-Age=43200" in cookie
    assert "Secure" in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=Lax" in cookie

    me_response = client.get("/platform/auth/me")
    assert me_response.status_code == 200
    second_csrf = me_response.get_json()["data"]["csrf_token"]
    assert second_csrf != first_csrf

    stale_logout = client.post(
        "/platform/auth/logout",
        headers={"X-CSRF-Token": first_csrf},
    )
    assert stale_logout.status_code == 403
    assert stale_logout.get_json()["code"] == "CSRF_INVALID"

    business_response = client.get("/api/devices/1")
    assert business_response.status_code == 401
    assert business_response.get_json()["code"] == "AUTH_REQUIRED"

    tenant_client = app.test_client()
    store = app.extensions["control_store"]
    with store.session() as session:
        tenant = Tenant(
            name="Control-only tenant",
            status="active",
            expires_at=datetime.utcnow() + timedelta(days=30),
            db_name="inventory_test_tenant_99999999",
            db_username="im_test_t99999999",
            db_password_ciphertext=store.secret_box.encrypt(
                "test-only-password",
                purpose="tenant-db-password",
            ),
            provisioning_status="active",
        )
        session.add(tenant)
        session.flush()
        member = TenantMember(
            tenant_id=tenant.id,
            phone="+8613900139000",
            role="admin",
            status="active",
        )
        session.add(member)
        session.flush()
        credentials = create_auth_session(
            session,
            kind="tenant",
            subject_id=member.id,
            tenant_id=tenant.id,
        )

    tenant_client.set_cookie("tenant_session", credentials.raw_token)
    tenant_denied = tenant_client.get("/platform/api/tenants")
    assert tenant_denied.status_code == 401
    assert tenant_denied.get_json()["code"] == "AUTH_REQUIRED"
    tenant_client.set_cookie(
        "platform_session",
        credentials.raw_token,
        path="/platform",
    )
    copied_token_denied = tenant_client.get("/platform/api/tenants")
    assert copied_token_denied.status_code == 401
    assert copied_token_denied.get_json()["code"] == "AUTH_REQUIRED"

    logout_response = client.post(
        "/platform/auth/logout",
        headers={"X-CSRF-Token": second_csrf},
    )
    assert logout_response.status_code == 200
    assert "Path=/platform" in logout_response.headers["Set-Cookie"]
    with store.session() as session:
        platform_sessions = session.scalars(
            select(AuthSession).where(AuthSession.kind == "platform")
        ).all()
        assert platform_sessions == []


def test_platform_create_runs_real_migrations_with_minimal_grants_and_retries(
    platform_environment,
):
    _bootstrap_platform_admin(platform_environment)
    client, csrf_token, _response = _platform_login(platform_environment)

    missing_csrf = client.post(
        "/platform/api/tenants",
        json={
            "name": "No CSRF",
            "admin_phone": "13800138000",
            "expires_at": "2030-01-01T00:00:00Z",
        },
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.get_json()["code"] == "CSRF_INVALID"

    invalid_expiry = client.post(
        "/platform/api/tenants",
        json={
            "name": "Invalid expiry",
            "admin_phone": "13800138000",
            "expires_at": "0999-12-31T23:59:59Z",
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert invalid_expiry.status_code == 400
    assert invalid_expiry.get_json()["code"] == "INVALID_REQUEST"

    create_response = _create_tenant(client, csrf_token)
    assert create_response.status_code == 201, create_response.get_json()
    tenant_payload = create_response.get_json()["data"]
    _assert_safe_tenant_payload(tenant_payload)
    assert tenant_payload["provisioning_status"] == "active"
    assert tenant_payload["db_name"] == (
        f"{TEST_DATABASE_PREFIX}{tenant_payload['id']:08d}"
    )
    assert tenant_payload["admin_phone"] == "+8613800138000"

    store = platform_environment["app"].extensions["control_store"]
    first_snapshot = _tenant_snapshot(store, tenant_payload["id"])
    assert first_snapshot["db_username"] == (
        f"{TEST_USER_PREFIX}{tenant_payload['id']:08d}"
    )
    assert first_snapshot["provisioning_error"] is None
    _smoke_current_business_models(platform_environment, first_snapshot)

    tenant_engine = _tenant_engine(platform_environment, first_snapshot)
    try:
        with tenant_engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT DATABASE()"
            ).scalar_one() == first_snapshot["db_name"]
            assert connection.exec_driver_sql(
                "SELECT CURRENT_USER()"
            ).scalar_one() == f"{first_snapshot['db_username']}@%"
            tables = set(inspect(connection).get_table_names())
            assert {"alembic_version", "devices", "rentals"} <= tables
            assert connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one() == _migration_head()

            grants = list(
                connection.exec_driver_sql(
                    "SHOW GRANTS FOR CURRENT_USER"
                ).scalars()
            )
            assert len(grants) == 2
            assert any(
                grant.replace("\\_", "_").replace("\\%", "%").startswith(
                    "GRANT USAGE ON *.*"
                )
                for grant in grants
            )
            own_database_grants = [
                grant
                for grant in grants
                if f"ON `{first_snapshot['db_name']}`.*"
                in grant.replace("\\_", "_").replace("\\%", "%")
            ]
            assert len(own_database_grants) == 1
            assert "GRANT OPTION" not in own_database_grants[0]

        with pytest.raises(OperationalError):
            with tenant_engine.connect() as connection:
                connection.exec_driver_sql(
                    "SELECT COUNT(*) FROM "
                    "control_saas_test.platform_admins"
                ).scalar_one()
    finally:
        tenant_engine.dispose()

    with platform_environment["root_engine"].begin() as connection:
        connection.execute(
            text(
                "GRANT SELECT ON `tenant_a_saas_test`.* "
                f"TO `{first_snapshot['db_username']}`@'%'"
            )
        )

    retry_response = client.post(
        f"/platform/api/tenants/{tenant_payload['id']}/retry",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert retry_response.status_code == 200, retry_response.get_json()
    _assert_safe_tenant_payload(retry_response.get_json()["data"])
    second_snapshot = _tenant_snapshot(store, tenant_payload["id"])
    assert second_snapshot == first_snapshot

    tenant_engine = _tenant_engine(platform_environment, second_snapshot)
    try:
        with tenant_engine.connect() as connection:
            grants = [
                grant.replace("\\_", "_").replace("\\%", "%")
                for grant in connection.exec_driver_sql(
                    "SHOW GRANTS FOR CURRENT_USER"
                ).scalars()
            ]
            assert len(grants) == 2
            assert any(grant.startswith("GRANT USAGE ON *.*") for grant in grants)
            assert sum(
                f"ON `{second_snapshot['db_name']}`.*" in grant
                for grant in grants
            ) == 1
            assert all("tenant_a_saas_test" not in grant for grant in grants)
    finally:
        tenant_engine.dispose()

    conflict = _create_tenant(
        client,
        csrf_token,
        phone="+86 138-0013-8000",
        name="Phone conflict",
    )
    assert conflict.status_code == 409
    assert conflict.get_json()["code"] == "PHONE_CONFLICT"
    with store.session() as session:
        assert len(session.scalars(select(Tenant)).all()) == 1


def test_failed_migration_keeps_member_and_resources_then_retry_reuses_them(
    platform_environment,
    tmp_path,
):
    _bootstrap_platform_admin(platform_environment)
    client, csrf_token, _response = _platform_login(platform_environment)
    app = platform_environment["app"]
    provisioner = app.extensions["tenant_provisioner"]
    provisioner.migrations_directory = str(
        tmp_path / "missing-business-migrations"
    )

    failed_response = _create_tenant(client, csrf_token)
    assert failed_response.status_code == 503
    assert failed_response.get_json()["code"] == "PROVISIONING_FAILED"
    failed_payload = failed_response.get_json()["data"]
    _assert_safe_tenant_payload(failed_payload)
    assert failed_payload["provisioning_status"] == "failed"
    assert failed_payload["provisioning_error"] == (
        "Business database migration failed."
    )
    serialized_response = json.dumps(failed_response.get_json())
    assert "missing-business-migrations" not in serialized_response
    assert "CREATE DATABASE" not in serialized_response
    assert "mysql+pymysql" not in serialized_response

    store = app.extensions["control_store"]
    failed_snapshot = _tenant_snapshot(store, failed_payload["id"])
    assert failed_snapshot["provisioning_status"] == "failed"
    assert failed_snapshot["member_phone"] == "+8613800138000"

    databases, users = _dynamic_resources(
        platform_environment["root_engine"]
    )
    assert failed_snapshot["db_name"] in databases
    assert failed_snapshot["db_username"] in users

    _seed_legacy_init_schema(platform_environment, failed_snapshot)

    with store.session() as session:
        credentials = create_auth_session(
            session,
            kind="tenant",
            subject_id=failed_snapshot["member_id"],
            tenant_id=failed_snapshot["tenant_id"],
        )
    tenant_client = app.test_client()
    tenant_client.set_cookie("tenant_session", credentials.raw_token)
    failed_business_access = tenant_client.get("/api/devices/1")
    assert failed_business_access.status_code == 503
    assert failed_business_access.get_json()["code"] == (
        "PROVISIONING_FAILED"
    )

    provisioner.migrations_directory = MIGRATIONS_DIRECTORY
    retry_response = client.post(
        f"/platform/api/tenants/{failed_payload['id']}/retry",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert retry_response.status_code == 200, retry_response.get_json()
    assert retry_response.get_json()["data"]["provisioning_status"] == (
        "active"
    )
    active_snapshot = _tenant_snapshot(store, failed_payload["id"])
    for immutable_field in (
        "db_name",
        "db_username",
        "db_password_ciphertext",
        "member_id",
        "member_phone",
    ):
        assert active_snapshot[immutable_field] == failed_snapshot[
            immutable_field
        ]

    _smoke_current_business_models(platform_environment, active_snapshot)

    tenant_engine = _tenant_engine(platform_environment, active_snapshot)
    try:
        with Session(tenant_engine) as session:
            legacy_audit = session.scalar(
                select(AuditLog).where(AuditLog.action == "legacy_action")
            )
            assert legacy_audit.resource_type == "rental"
            assert legacy_audit.resource_id == "1"
            assert legacy_audit.details == {
                "old_value": "before",
                "new_value": "after",
                "legacy_user_id": "legacy",
            }
            assert legacy_audit.created_at is not None
        with tenant_engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one() == _migration_head()
    finally:
        tenant_engine.dispose()


def test_concurrent_different_tenant_creates_both_reach_head(
    platform_environment,
):
    _bootstrap_platform_admin(platform_environment)
    first_client, first_csrf, _response = _platform_login(
        platform_environment
    )
    second_client, second_csrf, _response = _platform_login(
        platform_environment
    )
    barrier = Barrier(2)

    def create_one(client, csrf_token, phone, name):
        barrier.wait(timeout=5)
        return _create_tenant(
            client,
            csrf_token,
            phone=phone,
            name=name,
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(
                create_one,
                first_client,
                first_csrf,
                "13800138000",
                "Concurrent tenant A",
            ),
            executor.submit(
                create_one,
                second_client,
                second_csrf,
                "13900139000",
                "Concurrent tenant B",
            ),
        )
        responses = [future.result(timeout=30) for future in futures]

    assert [response.status_code for response in responses] == [201, 201]
    assert all(
        response.get_json()["data"]["provisioning_status"] == "active"
        for response in responses
    )
    store = platform_environment["app"].extensions["control_store"]
    with store.session() as session:
        tenants = session.scalars(select(Tenant).order_by(Tenant.id)).all()
        assert len(tenants) == 2
        assert all(tenant.provisioning_status == "active" for tenant in tenants)


def test_concurrent_same_tenant_retries_both_succeed(
    platform_environment,
):
    _bootstrap_platform_admin(platform_environment)
    creator, creator_csrf, _response = _platform_login(platform_environment)
    created = _create_tenant(creator, creator_csrf)
    assert created.status_code == 201, created.get_json()
    tenant_id = created.get_json()["data"]["id"]
    first_client, first_csrf, _response = _platform_login(
        platform_environment
    )
    second_client, second_csrf, _response = _platform_login(
        platform_environment
    )
    barrier = Barrier(2)

    def retry_one(client, csrf_token):
        barrier.wait(timeout=5)
        return client.post(
            f"/platform/api/tenants/{tenant_id}/retry",
            headers={"X-CSRF-Token": csrf_token},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(retry_one, first_client, first_csrf),
            executor.submit(retry_one, second_client, second_csrf),
        )
        responses = [future.result(timeout=30) for future in futures]

    assert [response.status_code for response in responses] == [200, 200]
    assert all(
        response.get_json()["data"]["provisioning_status"] == "active"
        for response in responses
    )
    store = platform_environment["app"].extensions["control_store"]
    snapshot = _tenant_snapshot(store, tenant_id)
    engine = _tenant_engine(platform_environment, snapshot)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one() == _migration_head()
    finally:
        engine.dispose()


def test_retry_waits_for_cross_worker_tenant_lock(platform_environment):
    _bootstrap_platform_admin(platform_environment)
    creator, csrf_token, _response = _platform_login(platform_environment)
    created = _create_tenant(creator, csrf_token)
    assert created.status_code == 201, created.get_json()
    tenant_id = created.get_json()["data"]["id"]
    lock_name = f"tenant-provision-{tenant_id:08d}"

    lock_connection = platform_environment["root_engine"].connect()
    try:
        assert lock_connection.scalar(
            text("SELECT GET_LOCK(:name, 0)"),
            {"name": lock_name},
        ) == 1
        lock_connection.commit()
        with ThreadPoolExecutor(max_workers=1) as executor:
            retry_future = executor.submit(
                creator.post,
                f"/platform/api/tenants/{tenant_id}/retry",
                headers={"X-CSRF-Token": csrf_token},
            )
            with pytest.raises(FutureTimeout):
                retry_future.result(timeout=0.5)
            assert lock_connection.scalar(
                text("SELECT RELEASE_LOCK(:name)"),
                {"name": lock_name},
            ) == 1
            lock_connection.commit()
            response = retry_future.result(timeout=30)
        assert response.status_code == 200, response.get_json()
    finally:
        lock_connection.execute(
            text("SELECT RELEASE_LOCK(:name)"),
            {"name": lock_name},
        )
        lock_connection.commit()
        lock_connection.close()


def test_upgrade_all_waits_for_cross_worker_tenant_lock(platform_environment):
    _bootstrap_platform_admin(platform_environment)
    creator, csrf_token, _response = _platform_login(platform_environment)
    created = _create_tenant(creator, csrf_token)
    assert created.status_code == 201, created.get_json()
    tenant_id = created.get_json()["data"]["id"]
    lock_name = f"tenant-provision-{tenant_id:08d}"

    lock_connection = platform_environment["root_engine"].connect()
    try:
        assert lock_connection.scalar(
            text("SELECT GET_LOCK(:name, 0)"),
            {"name": lock_name},
        ) == 1
        lock_connection.commit()
        with ThreadPoolExecutor(max_workers=1) as executor:
            upgrade_future = executor.submit(
                platform_environment["app"].test_cli_runner().invoke,
                args=["upgrade-tenant-databases"],
            )
            with pytest.raises(FutureTimeout):
                upgrade_future.result(timeout=0.5)
            assert lock_connection.scalar(
                text("SELECT RELEASE_LOCK(:name)"),
                {"name": lock_name},
            ) == 1
            lock_connection.commit()
            result = upgrade_future.result(timeout=30)
        assert result.exit_code == 0, result.output
    finally:
        lock_connection.execute(
            text("SELECT RELEASE_LOCK(:name)"),
            {"name": lock_name},
        )
        lock_connection.commit()
        lock_connection.close()


def test_retry_repairs_partial_damage_note_revision(platform_environment):
    _bootstrap_platform_admin(platform_environment)
    client, csrf_token, _response = _platform_login(platform_environment)
    created = _create_tenant(client, csrf_token)
    assert created.status_code == 201, created.get_json()
    tenant_id = created.get_json()["data"]["id"]
    store = platform_environment["app"].extensions["control_store"]
    snapshot = _tenant_snapshot(store, tenant_id)
    engine = _tenant_engine(platform_environment, snapshot)
    try:
        with engine.begin() as connection:
            assert "damage_note" in {
                column["name"]
                for column in inspect(connection).get_columns("rentals")
            }
            connection.exec_driver_sql(
                "UPDATE alembic_version SET version_num = %s",
                ("20260805_relay_cases",),
            )
    finally:
        engine.dispose()

    retried = client.post(
        f"/platform/api/tenants/{tenant_id}/retry",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert retried.status_code == 200, retried.get_json()
    engine = _tenant_engine(platform_environment, snapshot)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one() == _migration_head()
    finally:
        engine.dispose()


def test_retry_repairs_unstamped_0670_revision(
    platform_environment,
    tmp_path,
):
    _bootstrap_platform_admin(platform_environment)
    client, csrf_token, _response = _platform_login(platform_environment)
    provisioner = platform_environment["app"].extensions[
        "tenant_provisioner"
    ]
    provisioner.migrations_directory = str(tmp_path / "missing-migrations")
    failed = _create_tenant(client, csrf_token)
    assert failed.status_code == 503
    tenant_id = failed.get_json()["data"]["id"]
    store = platform_environment["app"].extensions["control_store"]
    snapshot = _tenant_snapshot(store, tenant_id)
    engine = _tenant_engine(platform_environment, snapshot)
    database_url = engine.url.render_as_string(hide_password=False)
    engine.dispose()

    _run_migration_revision(database_url, "0670a790bdd7")
    engine = _tenant_engine(platform_environment, snapshot)
    try:
        with engine.begin() as connection:
            assert connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one() == "0670a790bdd7"
            connection.exec_driver_sql(
                "UPDATE alembic_version SET version_num = %s",
                ("501259f48019",),
            )
    finally:
        engine.dispose()

    provisioner.migrations_directory = MIGRATIONS_DIRECTORY
    retried = client.post(
        f"/platform/api/tenants/{tenant_id}/retry",
        headers={"X-CSRF-Token": csrf_token},
    )

    assert retried.status_code == 200, retried.get_json()
    engine = _tenant_engine(platform_environment, snapshot)
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one() == _migration_head()
    finally:
        engine.dispose()


def test_concurrent_expiry_extensions_accumulate(platform_environment):
    _bootstrap_platform_admin(platform_environment)
    first_client, first_csrf, _response = _platform_login(
        platform_environment
    )
    second_client, second_csrf, _response = _platform_login(
        platform_environment
    )
    store = platform_environment["app"].extensions["control_store"]
    initial_expiry = datetime(2030, 1, 1)
    with store.session() as session:
        tenant = Tenant(
            name="Concurrent extension tenant",
            status="active",
            expires_at=initial_expiry,
            db_name="inventory_test_tenant_99999997",
            db_username="im_test_t99999997",
            db_password_ciphertext=store.secret_box.encrypt(
                "test-only-extension-password",
                purpose="tenant-db-password",
            ),
            provisioning_status="active",
        )
        session.add(tenant)
        session.flush()
        session.add(
            TenantMember(
                tenant_id=tenant.id,
                phone="+8613800138000",
                role="admin",
                status="active",
            )
        )
        tenant_id = tenant.id
    with store.engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TRIGGER task5_delay_tenant_update "
            "BEFORE UPDATE ON tenants FOR EACH ROW "
            "SET @task5_delay = SLEEP(0.25)"
        )
    barrier = Barrier(2)

    def extend_one(client, csrf_token):
        barrier.wait(timeout=5)
        return client.patch(
            f"/platform/api/tenants/{tenant_id}",
            json={"extend_days": 1},
            headers={"X-CSRF-Token": csrf_token},
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = (
            executor.submit(extend_one, first_client, first_csrf),
            executor.submit(extend_one, second_client, second_csrf),
        )
        responses = [future.result(timeout=10) for future in futures]

    assert [response.status_code for response in responses] == [200, 200]
    with store.session() as session:
        assert session.get(Tenant, tenant_id).expires_at == (
            initial_expiry + timedelta(days=2)
        )


def test_platform_list_and_patch_manage_lifecycle_without_leaking_secrets(
    platform_environment,
):
    _bootstrap_platform_admin(platform_environment)
    client, csrf_token, _response = _platform_login(platform_environment)
    store = platform_environment["app"].extensions["control_store"]
    with store.session() as session:
        tenant = Tenant(
            name="Lifecycle tenant",
            status="active",
            expires_at=datetime(2020, 1, 1),
            db_name="inventory_test_tenant_99999998",
            db_username="im_test_t99999998",
            db_password_ciphertext=store.secret_box.encrypt(
                "test-only-lifecycle-password",
                purpose="tenant-db-password",
            ),
            provisioning_status="active",
        )
        session.add(tenant)
        session.flush()
        session.add(
            TenantMember(
                tenant_id=tenant.id,
                phone="+8613800138000",
                role="admin",
                status="active",
            )
        )
        tenant_id = tenant.id

    list_response = client.get("/platform/api/tenants")
    assert list_response.status_code == 200
    _assert_safe_tenant_payload(list_response.get_json()["data"])
    assert [row["id"] for row in list_response.get_json()["data"]] == [
        tenant_id
    ]

    invalid_name = client.patch(
        f"/platform/api/tenants/{tenant_id}",
        json={"name": "x" * 129},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert invalid_name.status_code == 400
    assert invalid_name.get_json()["code"] == "INVALID_REQUEST"

    with store.session() as session:
        conflicting_tenant = Tenant(
            name="Phone owner tenant",
            status="active",
            expires_at=datetime(2030, 1, 1),
            db_name="inventory_test_tenant_99999996",
            db_username="im_test_t99999996",
            db_password_ciphertext=store.secret_box.encrypt(
                "test-only-conflict-password",
                purpose="tenant-db-password",
            ),
            provisioning_status="active",
        )
        session.add(conflicting_tenant)
        session.flush()
        session.add(
            TenantMember(
                tenant_id=conflicting_tenant.id,
                phone="+8613700137000",
                role="admin",
                status="active",
            )
        )

    phone_conflict = client.patch(
        f"/platform/api/tenants/{tenant_id}",
        json={"admin_phone": "13700137000"},
        headers={"X-CSRF-Token": csrf_token},
    )
    assert phone_conflict.status_code == 409
    assert phone_conflict.get_json()["code"] == "PHONE_CONFLICT"

    for invalid_expiry in (
        {"expires_at": "0999-12-31T23:59:59Z"},
        {"extend_days": 10**100},
    ):
        invalid_response = client.patch(
            f"/platform/api/tenants/{tenant_id}",
            json=invalid_expiry,
            headers={"X-CSRF-Token": csrf_token},
        )
        assert invalid_response.status_code == 400
        assert invalid_response.get_json()["code"] == "INVALID_REQUEST"

    direct_expiry = "2031-02-03T04:05:06Z"
    direct_update = client.patch(
        f"/platform/api/tenants/{tenant_id}",
        json={
            "name": "Renamed tenant",
            "admin_phone": "13900139000",
            "expires_at": direct_expiry,
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert direct_update.status_code == 200
    assert direct_update.get_json()["data"]["name"] == "Renamed tenant"
    assert direct_update.get_json()["data"]["admin_phone"] == (
        "+8613900139000"
    )
    assert direct_update.get_json()["data"]["expires_at"] == direct_expiry

    with store.session() as session:
        session.get(Tenant, tenant_id).expires_at = datetime(2020, 1, 1)
    before_extension = datetime.utcnow()
    extension = client.patch(
        f"/platform/api/tenants/{tenant_id}",
        json={"extend_days": 5},
        headers={"X-CSRF-Token": csrf_token},
    )
    after_extension = datetime.utcnow()
    assert extension.status_code == 200
    extended_at = datetime.fromisoformat(
        extension.get_json()["data"]["expires_at"].removesuffix("Z")
    )
    assert (
        before_extension.replace(microsecond=0) + timedelta(days=5)
        <= extended_at
    )
    assert extended_at <= (
        after_extension.replace(microsecond=0) + timedelta(days=5)
    )

    for status in ("suspended", "active"):
        status_response = client.patch(
            f"/platform/api/tenants/{tenant_id}",
            json={"status": status},
            headers={"X-CSRF-Token": csrf_token},
        )
        assert status_response.status_code == 200
        assert status_response.get_json()["data"]["status"] == status
        _assert_safe_tenant_payload(status_response.get_json()["data"])


def test_upgrade_all_includes_suspended_and_expired_and_continues_failure(
    platform_environment,
):
    _bootstrap_platform_admin(platform_environment)
    client, csrf_token, _response = _platform_login(platform_environment)
    first_response = _create_tenant(
        client,
        csrf_token,
        phone="13800138000",
        name="Upgrade failure",
    )
    second_response = _create_tenant(
        client,
        csrf_token,
        phone="13900139000",
        name="Upgrade success",
    )
    assert first_response.status_code == 201, first_response.get_json()
    assert second_response.status_code == 201, second_response.get_json()

    first_id = first_response.get_json()["data"]["id"]
    second_id = second_response.get_json()["data"]["id"]
    store = platform_environment["app"].extensions["control_store"]
    with store.session() as session:
        first = session.get(Tenant, first_id)
        first.status = "suspended"
        first.expires_at = datetime(2020, 1, 1)
        first.db_password_ciphertext = store.secret_box.encrypt(
            "deliberately-wrong-test-password",
            purpose="tenant-db-password",
        )
    second_snapshot = _tenant_snapshot(store, second_id)
    second_engine = _tenant_engine(platform_environment, second_snapshot)
    try:
        with second_engine.begin() as connection:
            connection.exec_driver_sql(
                "ALTER TABLE rentals DROP COLUMN damage_note"
            )
            connection.exec_driver_sql(
                "UPDATE alembic_version SET version_num = %s",
                ("20260805_relay_cases",),
            )
    finally:
        second_engine.dispose()

    result = platform_environment["app"].test_cli_runner().invoke(
        args=["upgrade-tenant-databases"]
    )

    assert result.exit_code != 0
    rows = [json.loads(line) for line in result.output.splitlines()]
    assert [set(row) for row in rows] == [
        {"tenant_id", "db_name", "head", "success"},
        {"tenant_id", "db_name", "head", "success"},
    ]
    assert [row["tenant_id"] for row in rows] == [first_id, second_id]
    assert rows[0]["success"] is False
    assert rows[1]["success"] is True
    assert rows[0]["head"] == _migration_head()
    assert rows[1]["head"] == _migration_head()
    assert "password" not in result.output.lower()
    assert "mysql+pymysql" not in result.output
    assert "traceback" not in result.output.lower()

    second_engine = _tenant_engine(platform_environment, second_snapshot)
    try:
        with second_engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT version_num FROM alembic_version"
            ).scalar_one() == _migration_head()
            columns = {
                column["name"]
                for column in inspect(connection).get_columns(
                    "rentals"
                )
            }
            assert "damage_note" in columns
    finally:
        second_engine.dispose()
