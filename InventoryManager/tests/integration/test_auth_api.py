import base64
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Event, Lock

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.engine import make_url

from app import create_app, db
from app.control.models import (
    AuthSession,
    ControlBase,
    SmsLoginCode,
    Tenant,
    TenantMember,
)
from app.control.store import ControlStore
from app.crypto import SecretBox, hash_token
from config import TestingConfig


TEST_MASTER_KEY = base64.b64encode(bytes(range(32))).decode("ascii")
DATABASE_ENVIRONMENTS = {
    "TEST_CONTROL_DATABASE_URL": "control_saas_test",
    "TEST_TENANT_DATABASE_URL_A": "tenant_a_saas_test",
    "TEST_TENANT_DATABASE_URL_B": "tenant_b_saas_test",
}
GENERIC_SMS_RESPONSE = {
    "success": True,
    "message": "如果该手机号可登录，验证码将发送至手机",
}


class RecordingSmsSender:
    def __init__(self):
        self.last_code = None
        self.send_count = 0

    def send_code(self, _phone_e164, code, _minutes):
        self.last_code = code
        self.send_count += 1
        return type("SmsResult", (), {"ok": True, "code": "Ok"})()


@pytest.mark.parametrize(
    "path,body",
    [
        ("/auth/sms/request", {}),
        ("/auth/sms/request", []),
        ("/auth/sms/request", "phone"),
        ("/auth/sms/verify", []),
        ("/auth/sms/verify", "phone"),
    ],
)
def test_auth_sms_routes_validate_json_object_before_login(path, body):
    class RouteProbeConfig(TestingConfig):
        AUTH_BYPASS_FOR_TESTS = False
        SMS_SENDER = RecordingSmsSender()
        CORS_ORIGINS = []

    application = create_app(RouteProbeConfig)
    try:
        response = application.test_client().post(
            path,
            json=body,
        )
        assert response.status_code == 400
        assert response.get_json()["code"] == "INVALID_REQUEST"
    finally:
        finalizer = application.extensions["tenant_resource_finalizer"]
        if finalizer.alive:
            finalizer()


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


@pytest.fixture
def auth_api_environment():
    auth_module = __import__("app.auth", fromlist=["FakeSmsSender"])
    urls = {
        name: _required_test_url(name)
        for name in DATABASE_ENVIRONMENTS
    }
    engines = {
        name: create_engine(url, pool_pre_ping=True)
        for name, url in urls.items()
    }
    schemas_verified_safe = False
    application = None
    try:
        for environment_name, engine in engines.items():
            with engine.connect() as connection:
                assert connection.exec_driver_sql(
                    "SELECT DATABASE()"
                ).scalar_one() == DATABASE_ENVIRONMENTS[environment_name]
                _assert_test_only_grants(connection)
        schemas_verified_safe = True
        for engine in engines.values():
            _reset_schema(engine)

        control_engine = engines["TEST_CONTROL_DATABASE_URL"]
        ControlBase.metadata.create_all(control_engine)
        tenant_a_url = urls["TEST_TENANT_DATABASE_URL_A"]
        box = SecretBox.from_base64(TEST_MASTER_KEY)

        from sqlalchemy.orm import Session

        with Session(control_engine) as session:
            tenant = Tenant(
                name="Auth API Tenant",
                status="active",
                expires_at=datetime.utcnow() + timedelta(days=30),
                db_name=tenant_a_url.database,
                db_username=tenant_a_url.username,
                db_password_ciphertext=box.encrypt(
                    tenant_a_url.password,
                    purpose="tenant-db-password",
                ),
                provisioning_status="active",
            )
            session.add(tenant)
            session.flush()
            members = {}
            for label, phone, role, status in (
                ("admin", "+8613800138000", "admin", "active"),
                ("operator", "+8613800138001", "operator", "active"),
                ("disabled", "+8613800138002", "operator", "disabled"),
            ):
                member = TenantMember(
                    tenant_id=tenant.id,
                    phone=phone,
                    role=role,
                    status=status,
                )
                session.add(member)
                session.flush()
                members[label] = member.id
            tenant_id = tenant.id
            session.commit()

        sender = auth_module.FakeSmsSender()

        class AuthApiConfig(TestingConfig):
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
            SMS_SENDER = sender
            DEV_SMS_CODE = "123456"
            API_KEY = "external-test-key"
            CORS_ORIGINS = ["https://inventory.example"]
            TRUSTED_PROXY_HOPS = 1

        application = create_app(AuthApiConfig)

        @application.get("/api/_auth-read")
        def auth_read_probe():
            return {"member_id": db.session.info.get("unused", 0)}

        @application.post("/api/_auth-write")
        def auth_write_probe():
            return {"written": True}

        @application.post("/api/_admin-only")
        @auth_module.require_role("admin")
        def admin_only_probe():
            return {"admin": True}

        yield {
            "app": application,
            "sender": sender,
            "tenant_id": tenant_id,
            "member_ids": members,
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
        for engine in engines.values():
            try:
                if schemas_verified_safe:
                    _reset_schema(engine)
            finally:
                engine.dispose()


def _login(environment, phone="13800138000"):
    client = environment["app"].test_client()
    request_response = client.post(
        "/auth/sms/request",
        json={"phone": phone},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    assert request_response.status_code == 200
    verify_response = client.post(
        "/auth/sms/verify",
        json={"phone": phone, "code": environment["sender"].last_code},
    )
    assert verify_response.status_code == 200
    return client, verify_response


def test_sms_request_is_generic_for_unknown_and_disabled_members(
    auth_api_environment,
):
    client = auth_api_environment["app"].test_client()

    registered = client.post(
        "/auth/sms/request",
        json={"phone": "13800138000"},
        environ_base={"REMOTE_ADDR": "127.0.0.1"},
    )
    unknown = client.post(
        "/auth/sms/request",
        json={"phone": "13900139000"},
        environ_base={"REMOTE_ADDR": "127.0.0.2"},
    )
    disabled = client.post(
        "/auth/sms/request",
        json={"phone": "13800138002"},
        environ_base={"REMOTE_ADDR": "127.0.0.3"},
    )

    assert registered.status_code == unknown.status_code
    assert unknown.status_code == disabled.status_code
    assert registered.get_json() == GENERIC_SMS_RESPONSE
    assert unknown.get_json() == GENERIC_SMS_RESPONSE
    assert disabled.get_json() == GENERIC_SMS_RESPONSE
    assert auth_api_environment["sender"].send_count == 1


def test_verify_sets_secure_session_shape_and_me_rotates_csrf_digest(
    auth_api_environment,
):
    client, verify_response = _login(auth_api_environment)
    verify_data = verify_response.get_json()["data"]
    first_csrf = verify_data["csrf_token"]
    cookie_header = verify_response.headers.getlist("Set-Cookie")[0]
    cookie = client.get_cookie("tenant_session")

    assert "HttpOnly" in cookie_header
    assert "SameSite=Lax" in cookie_header
    assert "Path=/" in cookie_header
    assert "Max-Age=604800" in cookie_header
    assert "Secure" not in cookie_header
    assert verify_data["member"]["role"] == "admin"
    assert verify_data["tenant"]["access_status"] == "active"

    store = auth_api_environment["app"].extensions["control_store"]
    with store.session() as session:
        stored = session.scalars(select(AuthSession)).one()
        assert stored.token_hash == hash_token(cookie.value)
        assert stored.token_hash != cookie.value
        assert stored.csrf_token_hash == hash_token(first_csrf)

    me_response = client.get("/auth/me")
    second_csrf = me_response.get_json()["data"]["csrf_token"]
    assert me_response.status_code == 200
    assert second_csrf != first_csrf
    with store.session() as session:
        stored = session.scalars(select(AuthSession)).one()
        assert stored.csrf_token_hash == hash_token(second_csrf)
        assert stored.csrf_token_hash != second_csrf


def test_logout_requires_csrf_and_revokes_server_session(
    auth_api_environment,
):
    client, verify_response = _login(auth_api_environment)
    csrf_token = verify_response.get_json()["data"]["csrf_token"]

    missing_csrf = client.post("/auth/logout")
    assert missing_csrf.status_code == 403
    assert missing_csrf.get_json()["code"] == "CSRF_INVALID"

    logged_out = client.post(
        "/auth/logout",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert logged_out.status_code == 200
    assert "Max-Age=0" in logged_out.headers.getlist("Set-Cookie")[0]
    assert client.get("/auth/me").status_code == 401

    store = auth_api_environment["app"].extensions["control_store"]
    with store.session() as session:
        assert session.scalars(select(AuthSession)).all() == []


def test_business_and_external_writes_require_csrf_and_keep_api_key_gate(
    auth_api_environment,
):
    client, verify_response = _login(auth_api_environment)
    csrf_token = verify_response.get_json()["data"]["csrf_token"]

    no_csrf = client.post("/api/_auth-write")
    assert no_csrf.status_code == 403
    assert no_csrf.get_json()["code"] == "CSRF_INVALID"
    assert client.post(
        "/api/_auth-write",
        headers={"X-CSRF-Token": csrf_token},
    ).get_json() == {"written": True}

    external_no_csrf = client.put(
        "/external-api/devices/1/status",
        headers={"X-API-Key": "external-test-key"},
    )
    assert external_no_csrf.status_code == 403
    assert external_no_csrf.get_json()["code"] == "CSRF_INVALID"

    external_no_api_key = client.put(
        "/external-api/devices/1/status",
        headers={"X-CSRF-Token": csrf_token},
    )
    assert external_no_api_key.status_code == 401
    external_dual_gate = client.put(
        "/external-api/devices/1/status",
        headers={
            "X-CSRF-Token": csrf_token,
            "X-API-Key": "external-test-key",
        },
    )
    assert external_dual_gate.status_code == 410


def test_fixed_roles_are_enforced_on_each_request(auth_api_environment):
    operator_client, operator_login = _login(
        auth_api_environment,
        phone="13800138001",
    )
    operator_csrf = operator_login.get_json()["data"]["csrf_token"]
    denied = operator_client.post(
        "/api/_admin-only",
        headers={"X-CSRF-Token": operator_csrf},
    )
    assert denied.status_code == 403
    assert denied.get_json()["code"] == "FORBIDDEN"

    admin_client, admin_login = _login(auth_api_environment)
    admin_csrf = admin_login.get_json()["data"]["csrf_token"]
    allowed = admin_client.post(
        "/api/_admin-only",
        headers={"X-CSRF-Token": admin_csrf},
    )
    assert allowed.status_code == 200
    assert allowed.get_json() == {"admin": True}


@pytest.mark.parametrize(
    "field,value,access_status,business_code",
    [
        ("status", "suspended", "suspended", "TENANT_SUSPENDED"),
        (
            "expires_at",
            datetime(2000, 1, 1),
            "expired",
            "TENANT_EXPIRED",
        ),
    ],
    ids=["suspended", "expired"],
)
def test_me_allows_restricted_tenant_but_business_request_reflects_state(
    auth_api_environment,
    field,
    value,
    access_status,
    business_code,
):
    client, _verify_response = _login(auth_api_environment)
    store = auth_api_environment["app"].extensions["control_store"]
    with store.session() as session:
        tenant = session.get(Tenant, auth_api_environment["tenant_id"])
        setattr(tenant, field, value)

    me_response = client.get("/auth/me")
    business_response = client.get("/api/_auth-read")

    assert me_response.status_code == 200
    assert me_response.get_json()["data"]["tenant"][
        "access_status"
    ] == access_status
    assert business_response.status_code == 403
    assert business_response.get_json()["code"] == business_code


@pytest.mark.parametrize("path", ["/auth/me", "/api/_auth-read"])
def test_disabling_member_immediately_revokes_current_session(
    auth_api_environment,
    path,
):
    client, _verify_response = _login(auth_api_environment)
    store = auth_api_environment["app"].extensions["control_store"]
    with store.session() as session:
        member = session.get(
            TenantMember,
            auth_api_environment["member_ids"]["admin"],
        )
        member.status = "disabled"

    response = client.get(path)

    assert response.status_code == 401
    assert response.get_json()["code"] == "AUTH_REQUIRED"
    with store.session() as session:
        assert session.scalars(select(AuthSession)).all() == []


def test_sms_routes_are_prelogin_csrf_exempt(auth_api_environment):
    client = auth_api_environment["app"].test_client()

    request_response = client.post(
        "/auth/sms/request",
        json={"phone": "13800138000"},
    )
    verify_response = client.post(
        "/auth/sms/verify",
        json={"phone": "13800138000", "code": "123456"},
    )

    assert request_response.status_code == 200
    assert verify_response.status_code == 200


def test_credentialless_cors_preflight_reaches_business_route(
    auth_api_environment,
):
    response = auth_api_environment["app"].test_client().options(
        "/api/_auth-write",
        headers={
            "Origin": "https://inventory.example",
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "X-CSRF-Token",
        },
    )

    assert response.status_code == 200
    assert response.headers["Access-Control-Allow-Origin"] == (
        "https://inventory.example"
    )
    assert "POST" in response.headers["Access-Control-Allow-Methods"]


def test_trusted_single_proxy_hop_supplies_sms_rate_limit_ip(
    auth_api_environment,
):
    client = auth_api_environment["app"].test_client()
    for phone, client_ip in (
        ("13900139000", "198.51.100.10"),
        ("13700137000", "198.51.100.11"),
    ):
        response = client.post(
            "/auth/sms/request",
            json={"phone": phone},
            headers={"X-Forwarded-For": client_ip},
            environ_base={"REMOTE_ADDR": "172.20.0.10"},
        )
        assert response.status_code == 200

    store = auth_api_environment["app"].extensions["control_store"]
    with store.session() as session:
        stored_ips = set(
            session.scalars(select(SmsLoginCode.requested_ip)).all()
        )
    assert stored_ips == {"198.51.100.10", "198.51.100.11"}


def test_concurrent_sms_requests_are_serialized_by_persisted_limits(
    auth_api_environment,
    monkeypatch,
):
    sender = auth_api_environment["sender"]
    original_send = sender.send_code
    entered_lock = Lock()
    second_sender_entered = Event()
    sender_entries = 0

    def synchronized_send(*args):
        nonlocal sender_entries
        with entered_lock:
            sender_entries += 1
            if sender_entries == 2:
                second_sender_entered.set()
        second_sender_entered.wait(timeout=0.5)
        return original_send(*args)

    monkeypatch.setattr(sender, "send_code", synchronized_send)

    def request_code(_index):
        with auth_api_environment["app"].test_client() as client:
            return client.post(
                "/auth/sms/request",
                json={"phone": "13800138000"},
                environ_base={"REMOTE_ADDR": "127.0.0.1"},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(request_code, range(2)))

    assert sorted(statuses) == [200, 429]
    assert sender.send_count == 1
    store = auth_api_environment["app"].extensions["control_store"]
    with store.session() as session:
        assert len(session.scalars(select(SmsLoginCode)).all()) == 1


def test_slow_sms_provider_does_not_starve_authenticated_requests(
    auth_api_environment,
    monkeypatch,
):
    app = auth_api_environment["app"]
    client, _login_response = _login(auth_api_environment)
    original_store = app.extensions["control_store"]
    constrained_store = ControlStore(
        app.config["CONTROL_DATABASE_URL"],
        original_store.secret_box,
        pool_size=1,
        max_overflow=0,
        pool_timeout=0.25,
    )
    app.extensions["control_store"] = constrained_store
    app.extensions["auth_service"].store = constrained_store

    sender_entered = Event()
    release_sender = Event()
    original_send = auth_api_environment["sender"].send_code

    def slow_send(*args):
        sender_entered.set()
        release_sender.wait(timeout=2)
        return original_send(*args)

    monkeypatch.setattr(
        auth_api_environment["sender"],
        "send_code",
        slow_send,
    )

    def request_code():
        with app.test_client() as request_client:
            return request_client.post(
                "/auth/sms/request",
                json={"phone": "13800138001"},
            )

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            slow_request = executor.submit(request_code)
            assert sender_entered.wait(timeout=1)
            me_request = executor.submit(client.get, "/auth/me")
            try:
                assert me_request.result(timeout=1).status_code == 200
            finally:
                release_sender.set()
            assert slow_request.result(timeout=1).status_code == 200
    finally:
        app.extensions["control_store"] = original_store
        app.extensions["auth_service"].store = original_store
        constrained_store.dispose()


def test_concurrent_correct_verification_consumes_code_once(
    auth_api_environment,
    monkeypatch,
):
    app = auth_api_environment["app"]
    request_response = app.test_client().post(
        "/auth/sms/request",
        json={"phone": "13800138000"},
    )
    assert request_response.status_code == 200

    auth_module = __import__("app.auth", fromlist=["create_auth_session"])
    original_create = auth_module.create_auth_session
    entered_lock = Lock()
    second_verifier_entered = Event()
    verifier_entries = 0

    def synchronized_create(*args, **kwargs):
        nonlocal verifier_entries
        with entered_lock:
            verifier_entries += 1
            if verifier_entries == 2:
                second_verifier_entered.set()
        second_verifier_entered.wait(timeout=0.5)
        return original_create(*args, **kwargs)

    monkeypatch.setattr(
        auth_module,
        "create_auth_session",
        synchronized_create,
    )

    def verify(_index):
        with app.test_client() as client:
            return client.post(
                "/auth/sms/verify",
                json={"phone": "13800138000", "code": "123456"},
            ).status_code

    with ThreadPoolExecutor(max_workers=2) as executor:
        statuses = list(executor.map(verify, range(2)))

    assert sorted(statuses) == [200, 401]
    store = app.extensions["control_store"]
    with store.session() as session:
        assert len(session.scalars(select(AuthSession)).all()) == 1


def test_concurrent_wrong_guesses_cannot_exceed_five_attempts(
    auth_api_environment,
    monkeypatch,
):
    app = auth_api_environment["app"]
    request_response = app.test_client().post(
        "/auth/sms/request",
        json={"phone": "13800138000"},
    )
    assert request_response.status_code == 200

    auth_module = __import__("app.auth", fromlist=["digest_sms_code"])
    original_digest = auth_module.digest_sms_code
    entered_lock = Lock()
    five_verifiers_entered = Event()
    verifier_entries = 0

    def synchronized_digest(*args, **kwargs):
        nonlocal verifier_entries
        with entered_lock:
            verifier_entries += 1
            if verifier_entries == 5:
                five_verifiers_entered.set()
        five_verifiers_entered.wait(timeout=0.5)
        return original_digest(*args, **kwargs)

    monkeypatch.setattr(auth_module, "digest_sms_code", synchronized_digest)

    def guess(_index):
        with app.test_client() as client:
            return client.post(
                "/auth/sms/verify",
                json={"phone": "13800138000", "code": "000000"},
            ).status_code

    with ThreadPoolExecutor(max_workers=6) as executor:
        statuses = list(executor.map(guess, range(6)))

    assert statuses == [401] * 6
    store = app.extensions["control_store"]
    with store.session() as session:
        code_row = session.scalars(select(SmsLoginCode)).one()
        assert code_row.attempt_count == 5
    correct_after_five = app.test_client().post(
        "/auth/sms/verify",
        json={"phone": "13800138000", "code": "123456"},
    )
    assert correct_after_five.status_code == 401
