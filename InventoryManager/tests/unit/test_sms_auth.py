import base64
import importlib
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest
from flask import Flask, g
from sqlalchemy import create_engine, func, select

from app import create_app
from app.control.models import (
    AuthSession,
    ControlBase,
    SmsLoginCode,
    Tenant,
    TenantMember,
)
from app.control.store import ControlStore
from app.crypto import SecretBox, hash_token
from config import ProductionConfig, TestingConfig


MASTER_BYTES = bytes(range(32))
MASTER_KEY = base64.b64encode(MASTER_BYTES).decode("ascii")


class MutableClock:
    def __init__(self, value):
        self.value = value

    def __call__(self):
        return self.value


@pytest.fixture
def auth_module():
    return importlib.import_module("app.auth")


@pytest.fixture
def auth_service(tmp_path, auth_module):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'auth.db'}"
    engine = create_engine(database_url)
    ControlBase.metadata.create_all(engine)
    store = ControlStore(database_url, SecretBox.from_base64(MASTER_KEY))
    clock = MutableClock(datetime(2026, 8, 24, 12, 0, 0))
    sender = auth_module.FakeSmsSender()

    with store.session() as session:
        tenant = Tenant(
            name="Unit Tenant",
            status="active",
            expires_at=clock() + timedelta(days=30),
            db_name="unit_tenant",
            db_username="unit_user",
            db_password_ciphertext="ciphertext",
            provisioning_status="active",
        )
        session.add(tenant)
        session.flush()
        member = TenantMember(
            tenant_id=tenant.id,
            phone="+8613800138000",
            role="admin",
            status="active",
        )
        session.add(member)
        session.flush()
        tenant_id = tenant.id
        member_id = member.id

    service = auth_module.AuthService(
        store=store,
        master_key=MASTER_BYTES,
        sender=sender,
        now=clock,
    )
    try:
        yield SimpleNamespace(
            module=auth_module,
            service=service,
            sender=sender,
            store=store,
            clock=clock,
            tenant_id=tenant_id,
            member_id=member_id,
        )
    finally:
        store.dispose()
        engine.dispose()


@pytest.mark.parametrize(
    "raw_phone",
    [
        "13800138000",
        "+8613800138000",
        "+86 138-0013-8000",
        "0086 138 0013 8000",
    ],
)
def test_normalize_mainland_phone_to_e164(auth_module, raw_phone):
    assert auth_module.normalize_china_phone(raw_phone) == "+8613800138000"


@pytest.mark.parametrize(
    "raw_phone",
    ["", "12800138000", "+85213800138000", "1380013800", None],
)
def test_phone_normalization_rejects_non_mainland_numbers(
    auth_module,
    raw_phone,
):
    with pytest.raises(ValueError, match="mainland China"):
        auth_module.normalize_china_phone(raw_phone)


def test_phone_normalization_rejects_non_ascii_digits(auth_module):
    with pytest.raises(ValueError, match="mainland China"):
        auth_module.normalize_china_phone("1380013800０")


def test_request_sends_six_digits_for_five_minutes_and_stores_only_digest(
    auth_service,
):
    auth_service.service.request_code("13800138000", "127.0.0.1")

    code = auth_service.sender.last_code
    assert len(code) == 6
    assert code.isdigit()
    assert auth_service.sender.last_phone == "+8613800138000"
    assert auth_service.sender.last_minutes == 5

    with auth_service.store.session() as session:
        row = session.scalars(select(SmsLoginCode)).one()
        assert row.code_digest != code
        assert code not in row.code_digest
        assert row.expires_at == auth_service.clock() + timedelta(minutes=5)
        assert row.send_succeeded is True


def test_failed_send_is_unusable_and_counts_for_rate_limit(auth_service):
    auth_service.sender.result = auth_service.module.SmsSendResult(
        ok=False,
        code="LimitExceeded",
    )

    auth_service.service.request_code("13800138000", "127.0.0.1")
    assert auth_service.service.verify_code(
        "13800138000",
        auth_service.sender.last_code,
    ) is None

    with pytest.raises(auth_service.module.SmsRateLimitExceeded):
        auth_service.service.request_code("13800138000", "127.0.0.1")


def test_unknown_and_disabled_members_are_persisted_but_never_sent(
    auth_service,
):
    auth_service.service.request_code("13900139000", "127.0.0.1")
    with auth_service.store.session() as session:
        member = session.get(TenantMember, auth_service.member_id)
        member.status = "disabled"

    auth_service.service.request_code("13800138000", "127.0.0.2")

    assert auth_service.sender.send_count == 0
    with auth_service.store.session() as session:
        rows = session.scalars(
            select(SmsLoginCode).order_by(SmsLoginCode.id)
        ).all()
        assert len(rows) == 2
        assert all(row.send_succeeded is False for row in rows)


def test_successful_verification_consumes_code_and_creates_hashed_session(
    auth_service,
):
    auth_service.service.request_code("13800138000", "127.0.0.1")
    code = auth_service.sender.last_code

    login = auth_service.service.verify_code("13800138000", code)

    assert login.member.id == auth_service.member_id
    assert login.tenant.id == auth_service.tenant_id
    assert login.credentials.raw_token
    assert login.credentials.csrf_token
    assert auth_service.service.verify_code("13800138000", code) is None

    with auth_service.store.session() as session:
        sms_row = session.scalars(select(SmsLoginCode)).one()
        auth_row = session.scalars(select(AuthSession)).one()
        assert sms_row.consumed_at == auth_service.clock()
        assert auth_row.token_hash == hash_token(
            login.credentials.raw_token
        )
        assert auth_row.csrf_token_hash == hash_token(
            login.credentials.csrf_token
        )
        assert auth_row.token_hash != login.credentials.raw_token
        assert auth_row.csrf_token_hash != login.credentials.csrf_token
        assert auth_row.expires_at == auth_service.clock() + timedelta(days=7)


def test_five_wrong_attempts_make_code_permanently_unusable(auth_service):
    auth_service.service.request_code("13800138000", "127.0.0.1")
    correct_code = auth_service.sender.last_code

    for _attempt in range(5):
        assert auth_service.service.verify_code(
            "13800138000",
            "000000" if correct_code != "000000" else "999999",
        ) is None

    assert auth_service.service.verify_code(
        "13800138000",
        correct_code,
    ) is None
    with auth_service.store.session() as session:
        row = session.scalars(select(SmsLoginCode)).one()
        assert row.attempt_count == 5


def test_non_ascii_verification_code_does_not_consume_an_attempt(
    auth_service,
):
    auth_service.service.request_code("13800138000", "127.0.0.1")

    assert auth_service.service.verify_code(
        "13800138000",
        "１２３４５６",
    ) is None
    with auth_service.store.session() as session:
        row = session.scalars(select(SmsLoginCode)).one()
        assert row.attempt_count == 0


def test_phone_cannot_request_twice_within_sixty_seconds(auth_service):
    auth_service.service.request_code("13800138000", "127.0.0.1")
    auth_service.clock.value += timedelta(seconds=59)

    with pytest.raises(auth_service.module.SmsRateLimitExceeded) as exc_info:
        auth_service.service.request_code("13800138000", "127.0.0.2")

    assert exc_info.value.scope == "phone_minute"


def test_phone_is_limited_to_five_requests_per_hour(auth_service):
    for _request in range(5):
        auth_service.service.request_code("13800138000", "127.0.0.1")
        auth_service.clock.value += timedelta(seconds=61)

    with pytest.raises(auth_service.module.SmsRateLimitExceeded) as exc_info:
        auth_service.service.request_code("13800138000", "127.0.0.2")

    assert exc_info.value.scope == "phone_hour"


def test_phone_is_limited_to_ten_requests_per_day(auth_service):
    for _request in range(10):
        auth_service.service.request_code("13800138000", "127.0.0.1")
        auth_service.clock.value += timedelta(minutes=16)

    with pytest.raises(auth_service.module.SmsRateLimitExceeded) as exc_info:
        auth_service.service.request_code("13800138000", "127.0.0.2")

    assert exc_info.value.scope == "phone_day"


def test_ip_is_limited_to_thirty_requests_per_hour(auth_service):
    for index in range(30):
        auth_service.service.request_code(
            f"139{index:08d}",
            "127.0.0.1",
        )

    with pytest.raises(auth_service.module.SmsRateLimitExceeded) as exc_info:
        auth_service.service.request_code("13700000000", "127.0.0.1")

    assert exc_info.value.scope == "ip_hour"


def test_request_prunes_sms_rows_older_than_seven_days(auth_service):
    with auth_service.store.session() as session:
        session.add(
            SmsLoginCode(
                phone="+8613900139000",
                code_digest="0" * 64,
                requested_ip="127.0.0.2",
                send_succeeded=False,
                attempt_count=0,
                expires_at=auth_service.clock() - timedelta(days=8),
                created_at=auth_service.clock() - timedelta(days=8),
            )
        )

    auth_service.service.request_code("13800138000", "127.0.0.1")

    with auth_service.store.session() as session:
        assert session.scalar(select(func.count(SmsLoginCode.id))) == 1


def test_session_primitives_support_both_cookie_scopes(auth_service):
    with auth_service.store.session() as session:
        tenant_credentials = auth_service.module.create_auth_session(
            session,
            kind="tenant",
            subject_id=auth_service.member_id,
            tenant_id=auth_service.tenant_id,
            now=auth_service.clock(),
        )
        platform_credentials = auth_service.module.create_auth_session(
            session,
            kind="platform",
            subject_id=99,
            now=auth_service.clock(),
        )

    with auth_service.store.session() as session:
        rows = session.scalars(
            select(AuthSession).order_by(AuthSession.kind)
        ).all()
        by_kind = {row.kind: row for row in rows}
        assert by_kind["tenant"].expires_at == (
            auth_service.clock() + timedelta(days=7)
        )
        assert by_kind["platform"].expires_at == (
            auth_service.clock() + timedelta(hours=12)
        )
        assert by_kind["tenant"].token_hash == hash_token(
            tenant_credentials.raw_token
        )
        assert by_kind["platform"].token_hash == hash_token(
            platform_credentials.raw_token
        )

    assert auth_service.module.session_cookie_options(
        "tenant", secure=True
    ) == {
        "httponly": True,
        "samesite": "Lax",
        "secure": True,
        "path": "/",
        "max_age": 7 * 24 * 60 * 60,
    }
    assert auth_service.module.session_cookie_options(
        "platform", secure=False
    ) == {
        "httponly": True,
        "samesite": "Lax",
        "secure": False,
        "path": "/platform",
        "max_age": 12 * 60 * 60,
    }


def test_operator_is_rejected_by_admin_role_decorator(auth_module):
    application = Flask(__name__)

    @auth_module.require_role("admin")
    def admin_only():
        return "ok"

    with application.test_request_context("/api/admin"):
        g.member = SimpleNamespace(role="operator")
        response, status = admin_only()

    assert status == 403
    assert response["code"] == "FORBIDDEN"

    with application.test_request_context("/api/admin"):
        g.member = SimpleNamespace(role="admin")
        assert admin_only() == "ok"


def test_tencent_result_is_usable_only_for_exact_ok_code(auth_module):
    class Response:
        def __init__(self, code):
            self.SendStatusSet = [SimpleNamespace(Code=code)]

    class Client:
        def __init__(self, code):
            self.code = code

        def SendSms(self, _request):
            return Response(self.code)

    ok_sender = auth_module.TencentSmsSender(
        secret_id="id",
        secret_key="key",
        sdk_app_id="app",
        sign_name="sign",
        template_id="template",
        client=Client("Ok"),
    )
    failed_sender = auth_module.TencentSmsSender(
        secret_id="id",
        secret_key="key",
        sdk_app_id="app",
        sign_name="sign",
        template_id="template",
        client=Client("LimitExceeded"),
    )

    assert ok_sender.send_code("+8613800138000", "123456", 5) == (
        auth_module.SmsSendResult(ok=True, code="Ok")
    )
    assert failed_sender.send_code("+8613800138000", "123456", 5) == (
        auth_module.SmsSendResult(ok=False, code="LimitExceeded")
    )


def test_production_rejects_fake_sms_sender(auth_module):
    class UnsafeSmsConfig(ProductionConfig):
        TESTING = True
        SAAS_MASTER_KEY = MASTER_KEY
        DEV_SMS_CODE = None
        SMS_SENDER = auth_module.FakeSmsSender()

    with pytest.raises(RuntimeError, match="FakeSmsSender"):
        create_app(UnsafeSmsConfig)


def test_cors_defaults_to_same_origin_and_explicit_origins_use_credentials(
    auth_module,
):
    class SameOriginConfig(TestingConfig):
        AUTH_BYPASS_FOR_TESTS = False
        SMS_SENDER = auth_module.FakeSmsSender()
        CORS_ORIGINS = []

    class ExplicitOriginConfig(SameOriginConfig):
        CORS_ORIGINS = ["https://inventory.example"]

    same_origin_app = create_app(SameOriginConfig)
    explicit_app = create_app(ExplicitOriginConfig)
    try:
        same_origin_response = same_origin_app.test_client().get(
            "/health",
            headers={"Origin": "https://evil.example"},
        )
        explicit_response = explicit_app.test_client().get(
            "/health",
            headers={"Origin": "https://inventory.example"},
        )

        assert (
            "Access-Control-Allow-Origin"
            not in same_origin_response.headers
        )
        assert explicit_response.headers["Access-Control-Allow-Origin"] == (
            "https://inventory.example"
        )
        assert explicit_response.headers[
            "Access-Control-Allow-Credentials"
        ] == "true"
    finally:
        for application in (same_origin_app, explicit_app):
            finalizer = application.extensions["tenant_resource_finalizer"]
            if finalizer.alive:
                finalizer()


@pytest.mark.parametrize(
    "origin",
    [
        "*",
        ".*",
        "https://.*",
        "https://inventory.example/path",
        "https://user@inventory.example",
        "file://inventory.example",
    ],
)
def test_non_exact_cors_origins_are_rejected(auth_module, origin):
    class WildcardConfig(TestingConfig):
        SMS_SENDER = auth_module.FakeSmsSender()
        CORS_ORIGINS = [origin]

    with pytest.raises(RuntimeError, match="exact HTTP origins"):
        create_app(WildcardConfig)


def test_gunicorn_entrypoint_selects_production_security_profile():
    environment = os.environ.copy()
    environment.update(
        {
            "FLASK_ENV": "production",
            "DATABASE_URL_HOST": (
                "mysql+pymysql://entrypoint@127.0.0.1:9/entrypoint_test"
            ),
            "SAAS_MASTER_KEY": MASTER_KEY,
            "CORS_ORIGINS": "https://inventory.example",
            "TENCENTCLOUD_SECRET_ID": "test-secret-id",
            "TENCENTCLOUD_SECRET_KEY": "test-secret-key",
            "TENCENT_SMS_SDK_APP_ID": "test-sdk-app-id",
            "TENCENT_SMS_SIGN_NAME": "test-sign",
            "TENCENT_SMS_TEMPLATE_ID": "test-template",
        }
    )
    environment.pop("DEV_SMS_CODE", None)
    project_root = Path(__file__).resolve().parents[2]
    script = """
import json
import os
import run
print('ENTRYPOINT_CONFIG=' + json.dumps({
    'is_production': run.app.config['IS_PRODUCTION'],
    'secure_cookie': run.app.config['SESSION_COOKIE_SECURE'],
    'sender': type(run.app.extensions['sms_sender']).__name__,
}), flush=True)
os._exit(0)
"""

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project_root,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=True,
    )
    marker = next(
        line
        for line in result.stdout.splitlines()
        if line.startswith("ENTRYPOINT_CONFIG=")
    )

    assert json.loads(marker.removeprefix("ENTRYPOINT_CONFIG=")) == {
        "is_production": True,
        "secure_cookie": True,
        "sender": "TencentSmsSender",
    }
