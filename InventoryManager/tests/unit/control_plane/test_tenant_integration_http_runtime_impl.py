from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from flask import Flask

from app.routes.tenant_integration_api import bp as tenant_integration_api_bp
from app.services.tenant_integrations import (
    TENANT_INTEGRATION_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantIntegrationHttpRuntime,
)
from inventory_control import (
    ControlBase,
    ControlDatabase,
    PlatformRootKeyVersion,
    Tenant,
    TenantMembership,
    User,
)
from inventory_control.crypto import RootKey
from inventory_control.database import read_database_utc_value
from inventory_control.domain import EffectiveTenantGate, TenantGateDecision
from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
    SessionService,
)
from inventory_control.models import (
    ControlOutboxEvent,
    MemberSeatGuard,
    TenantIntegration,
    TenantIntegrationSecretRevision,
)
from inventory_control.sms import (
    SmsDeliveryOutcome,
    SmsPolicy,
    TrustedSourceBucket,
)
from inventory_control.tenant_http import (
    TENANT_CSRF_HEADER_NAME,
    TENANT_SESSION_COOKIE_NAME,
    TenantHttpBoundary,
)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _gate(_session, tenant, _now) -> TenantGateDecision:
    gate = (
        EffectiveTenantGate.ACTIVE
        if tenant.status == "active"
        else EffectiveTenantGate.EXPIRED
    )
    return TenantGateDecision(
        gate=gate,
        error_code=None if gate is EffectiveTenantGate.ACTIVE else gate.value,
    )


class _SmsProvider:
    def __init__(self) -> None:
        self.codes: list[str] = []
        self.phones: list[str] = []

    def send_verification(self, request):
        self.phones.append(request.canonical_phone_e164)
        self.codes.append(request.take_plaintext_code())
        return SmsDeliveryOutcome.SENT


def _harness(tmp_path, database):
    sessions = SessionService(gate_current_read=_gate)
    boundary = TenantHttpBoundary(sessions)
    provider = _SmsProvider()
    root_key = RootKey(version=17, material=b"i" * 32)
    key_file = tmp_path / "v17"
    key_file.write_bytes(
        base64.b64encode(root_key._material_bytes()) + b"\n"
    )
    key_file.chmod(0o400)

    with database.transaction() as session:
        now = _as_utc(read_database_utc_value(session))
        session.add(
            PlatformRootKeyVersion(
                version=root_key.version,
                fingerprint_sha256=bytes.fromhex(
                    root_key.fingerprint_sha256
                ),
                status="active",
                activated_at=now,
            )
        )
        tenant = Tenant(status="active", access_version=3)
        user = User(
            phone_e164="+8613800138001",
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=now,
            status="active",
        )
        session.add_all((tenant, user))
        session.flush()
        membership = TenantMembership(
            tenant_id=tenant.id,
            user_id=user.id,
            role_key="admin",
            status="active",
            source_type="registration",
        )
        session.add_all((membership, MemberSeatGuard(tenant_id=tenant.id)))
        session.flush()
        issued = sessions.issue(
            session,
            user_id=user.id,
            idle_timeout=timedelta(minutes=30),
            absolute_timeout=timedelta(hours=8),
            now=now,
        )
        tenant_id = tenant.id

    runtime = SqlAlchemyTenantIntegrationHttpRuntime(
        control_database=database,
        tenant_http_boundary=boundary,
        root_key_directory=tmp_path,
        sms_provider=provider,
        sms_policy=SmsPolicy(),
        trusted_source_resolver=lambda _request: TrustedSourceBucket.unknown(),
    )
    app = Flask(__name__)
    app.register_blueprint(tenant_integration_api_bp)
    app.extensions[TENANT_INTEGRATION_HTTP_RUNTIME_EXTENSION] = runtime
    client = app.test_client()
    client.set_cookie(
        TENANT_SESSION_COOKIE_NAME,
        issued.session_token,
        secure=True,
    )
    headers = {TENANT_CSRF_HEADER_NAME: issued.csrf_token}
    return app, client, headers, database, provider, tenant_id


def test_admin_creates_lists_and_submits_write_only_revision(
    tmp_path, mysql_control_database
):
    app, client, headers, database, provider, tenant_id = _harness(
        tmp_path, mysql_control_database
    )
    integration_id = str(uuid4())
    action_id = str(uuid4())
    credentials = {
        "app_key": "xianyu-app-key",
        "app_secret": "xianyu-secret-must-not-echo",
    }
    try:
        created = client.post(
            "/api/integrations",
            json={
                "integration_id": integration_id,
                "provider": "xianyu",
                "name": "闲鱼主连接",
                "config": {"sync_mode": "poll"},
            },
            headers=headers,
        )
        assert created.status_code == 201
        assert created.get_json()["data"]["configured"] is False

        listed = client.get("/api/integrations", headers=headers)
        assert listed.status_code == 200
        assert listed.get_json()["data"]["items"] == [{
            "integration_id": integration_id,
            "provider": "xianyu",
            "name": "闲鱼主连接",
            "status": "unconfigured",
            "configured": False,
            "last_verified_at": None,
            "row_version": 1,
        }]

        issued = client.post(
            f"/api/integrations/{integration_id}/credential-challenges",
            json={
                "action_id": action_id,
                "expected_row_version": 1,
                "credentials": credentials,
            },
            headers=headers,
        )
        assert issued.status_code == 202
        challenge_id = issued.get_json()["data"]["challenge_id"]
        assert provider.phones == ["+8613800138001"]
        assert len(provider.codes) == 1

        issue_replay = client.post(
            f"/api/integrations/{integration_id}/credential-challenges",
            json={
                "action_id": action_id,
                "expected_row_version": 1,
                "credentials": credentials,
            },
            headers=headers,
        )
        assert issue_replay.status_code == 202
        assert issue_replay.get_json()["data"]["replayed"] is True
        assert issue_replay.get_json()["data"]["challenge_id"] == challenge_id
        assert len(provider.codes) == 1

        confirmed = client.post(
            f"/api/integrations/{integration_id}/credential-confirm",
            json={
                "action_id": action_id,
                "challenge_id": challenge_id,
                "code": provider.codes[0],
                "expected_row_version": 1,
                "credentials": credentials,
            },
            headers=headers,
        )
        assert confirmed.status_code == 200
        result = confirmed.get_json()["data"]
        assert result["status"] == "pending_validation"
        assert result["verification_status"] == "not_attempted"
        assert result["revision_no"] == 1
        assert credentials["app_secret"] not in confirmed.get_data(as_text=True)

        replayed = client.post(
            f"/api/integrations/{integration_id}/credential-confirm",
            json={
                "action_id": action_id,
                "challenge_id": challenge_id,
                "code": provider.codes[0],
                "expected_row_version": 1,
                "credentials": credentials,
            },
            headers=headers,
        )
        assert replayed.status_code == 200
        replay_result = replayed.get_json()["data"]
        assert replay_result["revision_id"] == result["revision_id"]
        assert replay_result["validation_event_id"] == (
            result["validation_event_id"]
        )
        assert replay_result["idempotent"] is True
        assert len(provider.codes) == 1

        with database.transaction() as session:
            integration = session.get(TenantIntegration, integration_id)
            revision = session.get(
                TenantIntegrationSecretRevision,
                result["revision_id"],
            )
            outbox = session.get(
                ControlOutboxEvent,
                result["validation_event_id"],
            )
            assert integration is not None
            assert integration.tenant_id == tenant_id
            assert integration.status == "pending"
            assert integration.current_secret_revision_id is None
            assert revision is not None
            assert revision.status == "pending_validation"
            assert revision.credentials_ciphertext
            assert outbox is not None
            assert outbox.max_attempts == 1
            assert outbox.payload == {
                "integration_uuid": integration_id,
                "revision_uuid": revision.id,
                "revision_row_version": 1,
                "provider": "xianyu",
            }
            assert credentials["app_secret"] not in repr(outbox.payload)
    finally:
        database.dispose()


def test_wrong_code_commits_attempt_but_no_revision_or_outbox(
    tmp_path, mysql_control_database
):
    _app, client, headers, database, provider, _tenant_id = _harness(
        tmp_path, mysql_control_database
    )
    integration_id = str(uuid4())
    action_id = str(uuid4())
    credentials = {"app_id": "kuaimai-id", "app_secret": "kuaimai-secret"}
    try:
        assert client.post(
            "/api/integrations",
            json={
                "integration_id": integration_id,
                "provider": "kuaimai",
                "name": "快麦",
            },
            headers=headers,
        ).status_code == 201
        issued = client.post(
            f"/api/integrations/{integration_id}/credential-challenges",
            json={
                "action_id": action_id,
                "expected_row_version": 1,
                "credentials": credentials,
            },
            headers=headers,
        )
        challenge_id = issued.get_json()["data"]["challenge_id"]

        wrong_code = "000000" if provider.codes[0] != "000000" else "111111"
        rejected = client.post(
            f"/api/integrations/{integration_id}/credential-confirm",
            json={
                "action_id": action_id,
                "challenge_id": challenge_id,
                "code": wrong_code,
                "expected_row_version": 1,
                "credentials": credentials,
            },
            headers=headers,
        )

        assert rejected.status_code == 403
        assert rejected.get_json()["data"]["code"] == (
            "TENANT_INTEGRATION_VERIFICATION_REJECTED"
        )
        with database.transaction() as session:
            integration = session.get(TenantIntegration, integration_id)
            assert integration is not None
            assert integration.status == "unconfigured"
            assert integration.row_version == 1
            assert session.query(TenantIntegrationSecretRevision).count() == 0
            assert session.query(ControlOutboxEvent).count() == 0
    finally:
        database.dispose()


def test_expired_gate_rejects_before_credentials_or_sms_are_touched(
    tmp_path, mysql_control_database
):
    _app, client, headers, database, provider, tenant_id = _harness(
        tmp_path, mysql_control_database
    )
    integration_id = str(uuid4())
    marker = "expired-secret-must-not-be-processed"
    try:
        assert client.post(
            "/api/integrations",
            json={
                "integration_id": integration_id,
                "provider": "sf",
                "name": "顺丰",
            },
            headers=headers,
        ).status_code == 201
        with database.transaction() as session:
            tenant = session.get(Tenant, tenant_id)
            assert tenant is not None
            tenant.status = "expired"

        listed = client.get("/api/integrations", headers=headers)
        challenged = client.post(
            f"/api/integrations/{integration_id}/credential-challenges",
            json={
                "action_id": str(uuid4()),
                "expected_row_version": 1,
                "credentials": {
                    "partner_id": "monthly-account",
                    "checkword": marker,
                },
            },
            headers=headers,
        )

        assert listed.status_code == 403
        assert challenged.status_code == 403
        assert marker not in challenged.get_data(as_text=True)
        assert provider.codes == []
        with database.transaction() as session:
            assert session.query(TenantIntegrationSecretRevision).count() == 0
            assert session.query(ControlOutboxEvent).count() == 0
    finally:
        database.dispose()
