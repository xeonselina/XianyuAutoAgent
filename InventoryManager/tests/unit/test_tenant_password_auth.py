import base64
import importlib.util
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import create_engine, select
from werkzeug.security import check_password_hash, generate_password_hash

from app import create_app
from app.auth import create_auth_session
from app.crypto import hash_token
from app.control.models import (
    AuthSession,
    ControlBase,
    Tenant,
    TenantMember,
)
from app.crypto import SecretBox
from config import ProductionConfig, TestingConfig


MASTER_KEY = base64.b64encode(bytes(range(32))).decode("ascii")
INITIAL_PASSWORD = "Initial-pass-123"
NEW_PASSWORD = "Updated-pass-456"


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


@pytest.fixture
def password_environment(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'control.db'}"
    engine = create_engine(database_url)
    ControlBase.metadata.create_all(engine)
    box = SecretBox.from_base64(MASTER_KEY)
    now = datetime(2026, 8, 29, 12, 0, 0)

    from sqlalchemy.orm import Session

    with Session(engine) as session:
        tenant = Tenant(
            name="Password Tenant",
            status="active",
            expires_at=now + timedelta(days=30),
            db_name="password_tenant",
            db_username="password_user",
            db_password_ciphertext=box.encrypt(
                "database-password",
                purpose="tenant-db-password",
            ),
            provisioning_status="active",
        )
        session.add(tenant)
        session.flush()
        member = TenantMember(
            tenant_id=tenant.id,
            phone="+8613800138000",
            role="operator",
            status="active",
            password_hash=generate_password_hash(INITIAL_PASSWORD),
        )
        disabled = TenantMember(
            tenant_id=tenant.id,
            phone="+8613800138001",
            role="operator",
            status="disabled",
            password_hash=generate_password_hash(INITIAL_PASSWORD),
        )
        passwordless = TenantMember(
            tenant_id=tenant.id,
            phone="+8613800138002",
            role="operator",
            status="active",
        )
        session.add_all([member, disabled, passwordless])
        session.flush()
        ids = {
            "tenant": tenant.id,
            "member": member.id,
            "disabled": disabled.id,
            "passwordless": passwordless.id,
        }
        session.commit()

    class PasswordConfig(TestingConfig):
        AUTH_BYPASS_FOR_TESTS = False
        TENANT_AUTH_MODE = "password"
        CONTROL_DATABASE_URL = database_url
        SAAS_MASTER_KEY = MASTER_KEY
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        TENANT_DB_HOST = "127.0.0.1"
        CORS_ORIGINS = []

    application = create_app(PasswordConfig)
    clock = MutableClock(now)
    application.extensions["auth_service"].now = clock
    try:
        yield {
            "app": application,
            "clock": clock,
            "ids": ids,
            "store": application.extensions["control_store"],
        }
    finally:
        finalizer = application.extensions["tenant_resource_finalizer"]
        if finalizer.alive:
            finalizer()
        engine.dispose()


def _password_login(environment, password=INITIAL_PASSWORD, phone="13800138000"):
    client = environment["app"].test_client()
    response = client.post(
        "/auth/password/login",
        json={"phone": phone, "password": password},
    )
    return client, response


def test_auth_mode_defaults_to_sms_and_invalid_modes_fail_app_and_worker(tmp_path):
    assert TestingConfig.TENANT_AUTH_MODE == "sms"

    class InvalidAppConfig(TestingConfig):
        TENANT_AUTH_MODE = "both"

    with pytest.raises(RuntimeError, match="TENANT_AUTH_MODE"):
        create_app(InvalidAppConfig)

    class InvalidWorkerConfig(TestingConfig):
        TENANT_AUTH_MODE = "PASSWORD"
        SAAS_MASTER_KEY = MASTER_KEY
        CONTROL_DATABASE_URL = f"sqlite+pysqlite:///{tmp_path / 'worker.db'}"

    with pytest.raises(RuntimeError, match="TENANT_AUTH_MODE"):
        create_app(InvalidWorkerConfig, worker_mode=True)


def test_production_password_mode_needs_no_tencent_sender(tmp_path):
    class PasswordProductionConfig(ProductionConfig):
        TESTING = True
        TENANT_AUTH_MODE = "password"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        TENANT_DB_HOST = "127.0.0.1"
        SECRET_KEY = "production-session-secret"
        SAAS_MASTER_KEY = MASTER_KEY
        DEV_SMS_CODE = None
        CONTROL_DATABASE_URL = f"sqlite+pysqlite:///{tmp_path / 'control.db'}"
        PROVISIONER_DATABASE_URL = f"sqlite+pysqlite:///{tmp_path / 'root.db'}"
        TENCENTCLOUD_SECRET_ID = None
        TENCENTCLOUD_SECRET_KEY = None
        TENCENT_SMS_SDK_APP_ID = None
        TENCENT_SMS_SIGN_NAME = None
        TENCENT_SMS_TEMPLATE_ID = None
        SMS_SENDER = object()

    application = create_app(PasswordProductionConfig)
    try:
        assert application.config["SESSION_COOKIE_SECURE"] is True
        assert application.extensions["sms_sender"] is None
        assert application.extensions["auth_service"].sender is None
    finally:
        application.extensions["tenant_resource_finalizer"]()


def test_production_sms_mode_still_requires_tencent_configuration(tmp_path):
    class SmsProductionConfig(ProductionConfig):
        TESTING = True
        TENANT_AUTH_MODE = "sms"
        SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
        SQLALCHEMY_ENGINE_OPTIONS = {}
        TENANT_DB_HOST = "127.0.0.1"
        SECRET_KEY = "production-session-secret"
        SAAS_MASTER_KEY = MASTER_KEY
        DEV_SMS_CODE = None
        CONTROL_DATABASE_URL = f"sqlite+pysqlite:///{tmp_path / 'control.db'}"
        PROVISIONER_DATABASE_URL = f"sqlite+pysqlite:///{tmp_path / 'root.db'}"
        TENCENTCLOUD_SECRET_ID = None
        TENCENTCLOUD_SECRET_KEY = None
        TENCENT_SMS_SDK_APP_ID = None
        TENCENT_SMS_SIGN_NAME = None
        TENCENT_SMS_TEMPLATE_ID = None

    with pytest.raises(RuntimeError, match="Tencent SMS"):
        create_app(SmsProductionConfig)


def test_public_config_and_disabled_methods_fail_closed(password_environment):
    app = password_environment["app"]
    client = app.test_client()

    config_response = client.get("/auth/config")
    request_response = client.post(
        "/auth/sms/request", json={"phone": "13800138000"}
    )
    verify_response = client.post(
        "/auth/sms/verify",
        json={"phone": "13800138000", "code": "123456"},
    )

    assert config_response.status_code == 200
    assert config_response.get_json() == {
        "success": True,
        "data": {"method": "password"},
    }
    assert request_response.status_code == verify_response.status_code == 409
    assert request_response.get_json()["code"] == "AUTH_METHOD_DISABLED"
    assert verify_response.get_json()["code"] == "AUTH_METHOD_DISABLED"
    assert app.extensions["sms_sender"] is None


def test_password_method_fails_closed_in_sms_mode():
    class SmsConfig(TestingConfig):
        AUTH_BYPASS_FOR_TESTS = False
        TENANT_AUTH_MODE = "sms"
        CORS_ORIGINS = []

    application = create_app(SmsConfig)
    try:
        response = application.test_client().post(
            "/auth/password/login",
            json={"phone": "13800138000", "password": INITIAL_PASSWORD},
        )
        change = application.test_client().post(
            "/auth/password/change",
            json={
                "current_password": INITIAL_PASSWORD,
                "new_password": NEW_PASSWORD,
            },
        )

        assert response.status_code == change.status_code == 409
        assert response.get_json()["code"] == "AUTH_METHOD_DISABLED"
        assert change.get_json()["code"] == "AUTH_METHOD_DISABLED"
    finally:
        application.extensions["tenant_resource_finalizer"]()


def test_ineligible_identities_run_dummy_password_verification(
    password_environment,
    monkeypatch,
):
    import app.auth as auth_module

    checked_hashes = []
    original_check = auth_module.check_password_hash

    def recording_check(password_hash, password):
        checked_hashes.append(password_hash)
        return original_check(password_hash, password)

    monkeypatch.setattr(auth_module, "check_password_hash", recording_check)

    for phone in (
        "13800138001",
        "13800138002",
        "13900139000",
        "not-a-phone",
    ):
        _, response = _password_login(password_environment, phone=phone)
        assert response.status_code == 401

    assert len(checked_hashes) == 4
    assert checked_hashes[1] == checked_hashes[2] == checked_hashes[3]


def test_normalized_password_candidates_use_hashed_advisory_lock(
    password_environment,
    monkeypatch,
):
    store = password_environment["store"]
    original_locked_session = store.locked_session
    lock_calls = []

    @contextmanager
    def recording_locked_session(names, timeout=0):
        lock_calls.append((tuple(names), timeout))
        with original_locked_session(names, timeout=timeout) as session:
            yield session

    monkeypatch.setattr(store, "locked_session", recording_locked_session)

    for phone in ("13800138000", "13900139000"):
        _, response = _password_login(
            password_environment,
            phone=phone,
            password="definitely-wrong",
        )
        assert response.status_code == 401

    assert lock_calls == [
        ((f"password-login-{hash_token('+8613800138000')[:48]}",), 5),
        ((f"password-login-{hash_token('+8613900139000')[:48]}",), 5),
    ]
    assert all("+86" not in names[0] for names, _timeout in lock_calls)


def test_password_advisory_lock_timeout_returns_generic_failure(
    password_environment,
    monkeypatch,
):
    _, ordinary_failure = _password_login(
        password_environment,
        phone="13900139000",
    )

    @contextmanager
    def timed_out_locked_session(_names, timeout=0):
        assert timeout == 5
        raise TimeoutError("test lock timeout")
        yield

    store = password_environment["store"]
    monkeypatch.setattr(store, "locked_session", timed_out_locked_session)

    _, response = _password_login(password_environment)

    assert response.status_code == 401
    assert response.get_json() == ordinary_failure.get_json()
    assert response.get_json()["code"] == "AUTH_INVALID"


def test_password_login_uses_existing_session_and_resets_failures(
    password_environment,
):
    store = password_environment["store"]
    member_id = password_environment["ids"]["member"]
    with store.session() as session:
        member = session.get(TenantMember, member_id)
        member.failed_password_attempts = 3
        member.password_locked_until = None

    client, response = _password_login(password_environment)

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["member"]["role"] == "operator"
    assert data["tenant"]["access_status"] == "active"
    assert data["csrf_token"]
    cookie_header = response.headers.getlist("Set-Cookie")[0]
    assert "tenant_session=" in cookie_header
    assert "HttpOnly" in cookie_header
    with store.session() as session:
        member = session.get(TenantMember, member_id)
        assert member.failed_password_attempts == 0
        assert member.password_locked_until is None
        assert len(session.scalars(select(AuthSession)).all()) == 1
    assert client.get("/auth/me").status_code == 200


def test_password_login_cookie_security_follows_request_scheme(
    password_environment,
):
    app = password_environment["app"]
    app.config["SESSION_COOKIE_SECURE"] = True
    payload = {
        "phone": "13800138000",
        "password": INITIAL_PASSWORD,
    }

    http_response = app.test_client().post(
        "/auth/password/login",
        json=payload,
        base_url="http://inventory.example",
    )
    https_response = app.test_client().post(
        "/auth/password/login",
        json=payload,
        base_url="https://inventory.example",
    )

    assert http_response.status_code == 200
    assert "Secure" not in http_response.headers["Set-Cookie"]
    assert https_response.status_code == 200
    assert "Secure" in https_response.headers["Set-Cookie"]


def test_password_failures_are_generic_and_fifth_attempt_locks_for_15_minutes(
    password_environment,
):
    store = password_environment["store"]
    member_id = password_environment["ids"]["member"]
    generic_bodies = []

    for _attempt in range(5):
        _, response = _password_login(
            password_environment,
            password="definitely-wrong",
        )
        assert response.status_code == 401
        generic_bodies.append(response.get_json())

    for phone in ("13800138001", "13800138002", "13900139000"):
        _, response = _password_login(password_environment, phone=phone)
        assert response.status_code == 401
        generic_bodies.append(response.get_json())

    assert all(body == generic_bodies[0] for body in generic_bodies)
    assert generic_bodies[0]["code"] == "AUTH_INVALID"
    with store.session() as session:
        member = session.get(TenantMember, member_id)
        assert member.failed_password_attempts == 5
        assert member.password_locked_until == (
            password_environment["clock"]() + timedelta(minutes=15)
        )

    _, locked_response = _password_login(password_environment)
    assert locked_response.status_code == 401
    assert locked_response.get_json() == generic_bodies[0]
    with store.session() as session:
        assert session.get(
            TenantMember, member_id
        ).failed_password_attempts == 5

    password_environment["clock"].value += timedelta(minutes=15, seconds=1)
    _, recovered = _password_login(password_environment)
    assert recovered.status_code == 200


def test_restricted_tenant_login_reports_status_but_business_gate_denies(
    password_environment,
):
    store = password_environment["store"]
    with store.session() as session:
        session.get(
            Tenant, password_environment["ids"]["tenant"]
        ).status = "suspended"

    client, response = _password_login(password_environment)

    assert response.status_code == 200
    assert response.get_json()["data"]["tenant"]["access_status"] == (
        "suspended"
    )
    blocked = client.get("/api/warehouses")
    assert blocked.status_code == 403
    assert blocked.get_json()["code"] == "TENANT_SUSPENDED"


def test_password_change_requires_csrf_and_keeps_only_current_session(
    password_environment,
):
    store = password_environment["store"]
    member_id = password_environment["ids"]["member"]
    tenant_id = password_environment["ids"]["tenant"]
    first_client, login_response = _password_login(password_environment)
    csrf_token = login_response.get_json()["data"]["csrf_token"]
    second_client, second_response = _password_login(password_environment)
    assert second_response.status_code == 200
    with store.session() as session:
        assert len(session.scalars(select(AuthSession)).all()) == 2

    missing_csrf = first_client.post(
        "/auth/password/change",
        json={
            "current_password": INITIAL_PASSWORD,
            "new_password": NEW_PASSWORD,
        },
    )
    assert missing_csrf.status_code == 403
    assert missing_csrf.get_json()["code"] == "CSRF_INVALID"

    wrong_current = first_client.post(
        "/auth/password/change",
        json={
            "current_password": "wrong-current-password",
            "new_password": NEW_PASSWORD,
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert wrong_current.status_code == 401
    assert wrong_current.get_json()["code"] == "AUTH_INVALID"

    changed = first_client.post(
        "/auth/password/change",
        json={
            "current_password": INITIAL_PASSWORD,
            "new_password": NEW_PASSWORD,
        },
        headers={"X-CSRF-Token": csrf_token},
    )
    assert changed.status_code == 200
    assert first_client.get("/auth/me").status_code == 200
    assert second_client.get("/auth/me").status_code == 401
    with store.session() as session:
        member = session.get(TenantMember, member_id)
        assert member.password_hash != NEW_PASSWORD
        assert check_password_hash(member.password_hash, NEW_PASSWORD)
        assert member.password_changed_at == password_environment["clock"]()
        assert member.failed_password_attempts == 0
        assert member.password_locked_until is None
        sessions = session.scalars(select(AuthSession)).all()
        assert len(sessions) == 1
        assert sessions[0].subject_id == member_id
        assert sessions[0].tenant_id == tenant_id

    _, old_login = _password_login(password_environment)
    _, new_login = _password_login(
        password_environment, password=NEW_PASSWORD
    )
    assert old_login.status_code == 401
    assert new_login.status_code == 200


@pytest.mark.parametrize("new_password", ["short", "x" * 129])
def test_password_change_returns_clear_policy_error_without_revoking_sessions(
    password_environment,
    new_password,
):
    store = password_environment["store"]
    client, login_response = _password_login(password_environment)
    csrf_token = login_response.get_json()["data"]["csrf_token"]

    response = client.post(
        "/auth/password/change",
        json={
            "current_password": INITIAL_PASSWORD,
            "new_password": new_password,
        },
        headers={"X-CSRF-Token": csrf_token},
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "PASSWORD_POLICY"
    with store.session() as session:
        assert len(session.scalars(select(AuthSession)).all()) == 1


def test_set_tenant_password_cli_reads_stdin_hides_secret_and_revokes_sessions(
    password_environment,
):
    app = password_environment["app"]
    store = password_environment["store"]
    member_id = password_environment["ids"]["member"]
    tenant_id = password_environment["ids"]["tenant"]
    with store.session() as session:
        create_auth_session(
            session,
            kind="tenant",
            subject_id=member_id,
            tenant_id=tenant_id,
        )

    runner = app.test_cli_runner()
    help_result = runner.invoke(args=["set-tenant-password", "--help"])
    result = runner.invoke(
        args=[
            "set-tenant-password",
            "--phone",
            "138 0013 8000",
            "--password-stdin",
        ],
        input=f"{NEW_PASSWORD}\n",
    )

    assert help_result.exit_code == 0
    assert "--password " not in help_result.output
    assert result.exit_code == 0, result.output
    assert NEW_PASSWORD not in result.output
    with store.session() as session:
        member = session.get(TenantMember, member_id)
        assert check_password_hash(member.password_hash, NEW_PASSWORD)
        assert member.password_changed_at is not None
        assert session.scalars(select(AuthSession)).all() == []


def test_set_tenant_password_cli_rejects_unknown_and_invalid_passwords(
    password_environment,
):
    runner = password_environment["app"].test_cli_runner()
    unknown = runner.invoke(
        args=[
            "set-tenant-password",
            "--phone",
            "13900139000",
            "--password-stdin",
        ],
        input=f"{NEW_PASSWORD}\n",
    )
    invalid = runner.invoke(
        args=[
            "set-tenant-password",
            "--phone",
            "13800138000",
            "--password-stdin",
        ],
        input="too-short\n",
    )

    assert unknown.exit_code != 0
    assert "not found" in unknown.output.lower()
    assert NEW_PASSWORD not in unknown.output
    assert invalid.exit_code != 0
    assert "12" in invalid.output and "128" in invalid.output
    assert "too-short" not in invalid.output


def test_set_tenant_password_cli_rejects_hidden_prompt_without_tty(
    password_environment,
):
    secret = "must-not-be-read-or-echoed"
    result = password_environment["app"].test_cli_runner().invoke(
        args=[
            "set-tenant-password",
            "--phone",
            "13800138000",
        ],
        input=f"{secret}\n",
    )

    assert result.exit_code != 0
    assert "--password-stdin" in result.output
    assert secret not in result.output
    assert "warning" not in result.output.lower()
    assert "getpass" not in result.output.lower()


def test_password_control_migration_is_forward_and_reversible(monkeypatch):
    migration_path = (
        Path(__file__).resolve().parents[2]
        / "control_migrations"
        / "versions"
        / "20260829_add_tenant_password_auth.py"
    )
    spec = importlib.util.spec_from_file_location(
        "tenant_password_migration", migration_path
    )
    migration = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(migration)

    added = []
    dropped = []
    monkeypatch.setattr(
        migration.op,
        "add_column",
        lambda table, column: added.append((table, column)),
    )
    monkeypatch.setattr(
        migration.op,
        "drop_column",
        lambda table, column: dropped.append((table, column)),
    )

    migration.upgrade()
    migration.downgrade()

    assert migration.down_revision == "20260824_control_baseline"
    assert [column.name for table, column in added if table == "tenant_members"] == [
        "password_hash",
        "failed_password_attempts",
        "password_locked_until",
        "password_changed_at",
    ]
    assert added[1][1].server_default is not None
    assert dropped == [
        ("tenant_members", "password_changed_at"),
        ("tenant_members", "password_locked_until"),
        ("tenant_members", "failed_password_attempts"),
        ("tenant_members", "password_hash"),
    ]
