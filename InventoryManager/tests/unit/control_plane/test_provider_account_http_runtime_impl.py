from __future__ import annotations

import base64
import hashlib
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from flask import Flask
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import db
from app.models.warehouse import Warehouse
from app.routes.tenant_integration_api import bp as tenant_integration_api_bp
from app.services.tenant_business import TenantBusinessRequestScope
from app.services.tenant_integrations import (
    TENANT_PROVIDER_ACCOUNT_HTTP_RUNTIME_EXTENSION,
    SqlAlchemyTenantProviderAccountHttpRuntime,
)
from app.services.warehouse import WarehouseProviderBindingService
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
from inventory_control.domain import (
    EffectiveTenantGate,
    TenantGateDecision,
    TenantRole,
)
from inventory_control.identity import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
    SessionService,
)
from inventory_control.integrations import (
    ProviderValidationOutcome,
    SfAdminClaimProof,
    SfClaimOwner,
    TenantIntegrationService,
    TenantProviderAccountService,
)
from inventory_control.models import (
    ControlOutboxEvent,
    MemberSeatGuard,
    ProviderAccountClaim,
    ProviderAccountClaimEvent,
    SmsChallenge,
    TenantProviderAccount,
    TenantProviderAccountSecretRevision,
    TenantSensitiveActionIntent,
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


ROOT_KEY = RootKey(version=23, material=b"h" * 32)
WAREHOUSE_UUID = UUID("8b000000-0000-4000-8000-000000000001")


def _gate(_session, tenant, _now):
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
    def __init__(self):
        self.codes = []
        self.phones = []

    def send_verification(self, request):
        self.phones.append(request.canonical_phone_e164)
        self.codes.append(request.take_plaintext_code())
        return SmsDeliveryOutcome.SENT


class _TenantBusinessRuntime:
    def __init__(self, *, control_database, boundary, engine):
        self._control_database = control_database
        self._boundary = boundary
        self._engine = engine

    @contextmanager
    def tenant_session(
        self,
        *,
        flask_request,
        capability,
        additional_capabilities=(),
        request_id_prefix,
        after_authorize=None,
        passthrough_exceptions=(),
        allow_pending_warehouse_setup=False,
    ):
        del additional_capabilities, passthrough_exceptions
        del allow_pending_warehouse_setup
        with self._control_database.transaction() as control_session:
            now = read_database_utc_value(control_session)
            auth = self._boundary.authorize(
                control_session,
                flask_request,
                capability=capability,
                now=now,
            )
            if after_authorize is not None:
                after_authorize(auth)
        with Session(
            bind=self._engine,
            autoflush=False,
            expire_on_commit=False,
        ) as tenant_session:
            yield TenantBusinessRequestScope(
                auth_context=auth,
                request_id=f"{request_id_prefix}:test",
                database_now=now,
                tenant_session=tenant_session,
            )


def _harness(tmp_path, control):
    sessions = SessionService(gate_current_read=_gate)
    boundary = TenantHttpBoundary(sessions)
    provider = _SmsProvider()
    key_file = tmp_path / f"v{ROOT_KEY.version}"
    key_file.write_bytes(base64.b64encode(ROOT_KEY._material_bytes()) + b"\n")
    key_file.chmod(0o400)

    with control.transaction() as session:
        now = _utc(read_database_utc_value(session))
        tenant = Tenant(status="active", access_version=3)
        user = User(
            phone_e164="+8613800138023",
            phone_normalization_version=PHONE_NORMALIZATION_VERSION,
            phone_metadata_version=CN_MOBILE_METADATA_VERSION,
            phone_verified_at=now,
            status="active",
        )
        session.add_all((
            tenant,
            user,
            PlatformRootKeyVersion(
                version=ROOT_KEY.version,
                fingerprint_sha256=bytes.fromhex(ROOT_KEY.fingerprint_sha256),
                status="active",
                activated_at=now,
            ),
        ))
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
        user_id = user.id

    integration_id = str(uuid4())
    with control.transaction() as session:
        service = TenantIntegrationService(session)
        service.create_integration(
            integration_uuid=integration_id,
            tenant_uuid=tenant_id,
            provider="sf",
            name="main-sf",
        )
        pending = service.create_pending_revision(
            integration_uuid=integration_id,
            credentials={"partner_id": "partner", "checkword": "checkword"},
            root_key=ROOT_KEY,
            created_by_user_uuid=user_id,
            action_uuid=uuid4(),
            idempotency_key="http-test-sf-integration",
            expected_integration_row_version=1,
            expected_current_secret_revision_uuid=None,
        )
    attempt = uuid4()
    with control.transaction() as session:
        TenantIntegrationService(session).begin_provider_validation(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=attempt,
            expected_revision_row_version=1,
        )
    with control.transaction() as session:
        TenantIntegrationService(session).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=attempt,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=hashlib.sha256(b"valid").digest(),
            safe_code="VALID",
        )

    tenant_engine = control.engine
    with Session(tenant_engine) as tenant_session:
        with tenant_session.begin():
            warehouse = Warehouse(
                warehouse_uuid=str(WAREHOUSE_UUID),
                status="active",
                setup_state="pending",
                is_default=True,
                default_slot=1,
            )
            warehouse.mark_ready(
                name="Default",
                contact_name="Admin",
                contact_phone="13800138023",
                province="广东省",
                city="深圳市",
                district="南山区",
                address_detail="测试地址",
            )
            tenant_session.add(warehouse)

    tenant_business = _TenantBusinessRuntime(
        control_database=control,
        boundary=boundary,
        engine=tenant_engine,
    )
    runtime = SqlAlchemyTenantProviderAccountHttpRuntime(
        control_database=control,
        tenant_http_boundary=boundary,
        tenant_business_runtime=tenant_business,
        root_key_directory=tmp_path,
        sms_provider=provider,
        sms_policy=SmsPolicy(),
        trusted_source_resolver=lambda _request: TrustedSourceBucket.unknown(),
    )
    app = Flask(__name__)
    app.register_blueprint(tenant_integration_api_bp)
    app.extensions[TENANT_PROVIDER_ACCOUNT_HTTP_RUNTIME_EXTENSION] = runtime
    client = app.test_client()
    client.set_cookie(
        TENANT_SESSION_COOKIE_NAME,
        issued.session_token,
        secure=True,
    )
    headers = {TENANT_CSRF_HEADER_NAME: issued.csrf_token}
    return (
        app,
        client,
        headers,
        control,
        tenant_engine,
        provider,
        tenant_id,
        integration_id,
    )


def test_admin_submits_write_only_sf_account_revision(
    tmp_path, mysql_routed_database
):
    (
        _app,
        client,
        headers,
        control,
        tenant_engine,
        provider,
        tenant_id,
        integration_id,
    ) = _harness(tmp_path, mysql_routed_database)
    account_id = str(uuid4())
    action_id = str(uuid4())
    body = {
        "action_id": action_id,
        "warehouse_id": str(WAREHOUSE_UUID),
        "provider_account_id": account_id,
        "integration_id": integration_id,
        "label": "Default warehouse",
        "account": "001234567890",
    }
    try:
        issued = client.post(
            "/api/integrations/sf/provider-accounts/bind-challenges",
            json=body,
            headers=headers,
        )
        assert issued.status_code == 202
        challenge_id = issued.get_json()["data"]["challenge_id"]
        assert provider.phones == ["+8613800138023"]

        confirmed = client.post(
            "/api/integrations/sf/provider-accounts/bind-confirm",
            json={
                **body,
                "challenge_id": challenge_id,
                "code": provider.codes[0],
            },
            headers=headers,
        )
        assert confirmed.status_code == 200
        result = confirmed.get_json()["data"]
        assert result["status"] == "pending_validation"
        assert result["target_binding_revision"] == 1
        assert "001234567890" not in confirmed.get_data(as_text=True)

        listed = client.get(
            "/api/integrations/sf/provider-accounts",
            headers=headers,
        )
        assert listed.status_code == 200
        listed_item = listed.get_json()["data"]["items"][0]
        assert listed_item == {
            "provider_account_id": account_id,
            "integration_id": integration_id,
            "connection_name": "main-sf",
            "label": "Default warehouse",
            "masked_hint": "****7890",
            "status": "pending",
            "verification_status": "not_attempted",
            "warehouse_id": str(WAREHOUSE_UUID),
            "binding_revision": 1,
            "last_verified_at": None,
            "row_version": 1,
        }
        assert "001234567890" not in listed.get_data(as_text=True)

        replay = client.post(
            "/api/integrations/sf/provider-accounts/bind-confirm",
            json={
                **body,
                "challenge_id": challenge_id,
                "code": provider.codes[0],
            },
            headers=headers,
        )
        assert replay.status_code == 200
        assert replay.get_json()["data"]["revision_id"] == result["revision_id"]
        assert replay.get_json()["data"]["idempotent"] is True

        with control.new_session() as session:
            account = session.get(TenantProviderAccount, account_id)
            revision = session.get(
                TenantProviderAccountSecretRevision,
                result["revision_id"],
            )
            claim = session.get(ProviderAccountClaim, revision.provider_account_claim_id)
            event = session.get(ControlOutboxEvent, result["validation_event_id"])
            assert account.tenant_id == tenant_id
            assert account.current_secret_revision_id is None
            assert revision.account_secret_ciphertext != b"001234567890"
            assert revision.target_binding_revision == 1
            assert claim.claim_status == "reserved"
            assert claim.current_warehouse_uuid == str(WAREHOUSE_UUID)
            assert event.payload == {
                "revision_uuid": revision.id,
                "revision_row_version": 1,
            }
            assert "001234567890" not in repr(event.payload)
    finally:
        control.dispose()
        tenant_engine.dispose()


def test_wrong_code_keeps_claim_account_revision_and_outbox_absent(
    tmp_path, mysql_routed_database
):
    (
        _app,
        client,
        headers,
        control,
        tenant_engine,
        provider,
        _tenant_id,
        integration_id,
    ) = _harness(tmp_path, mysql_routed_database)
    body = {
        "action_id": str(uuid4()),
        "warehouse_id": str(WAREHOUSE_UUID),
        "provider_account_id": str(uuid4()),
        "integration_id": integration_id,
        "label": "Default warehouse",
        "account": "009876543210",
    }
    try:
        issued = client.post(
            "/api/integrations/sf/provider-accounts/bind-challenges",
            json=body,
            headers=headers,
        )
        challenge_id = issued.get_json()["data"]["challenge_id"]
        wrong = "000000" if provider.codes[0] != "000000" else "111111"

        rejected = client.post(
            "/api/integrations/sf/provider-accounts/bind-confirm",
            json={**body, "challenge_id": challenge_id, "code": wrong},
            headers=headers,
        )

        assert rejected.status_code == 403
        assert rejected.get_json()["data"]["code"] == (
            "SF_ACCOUNT_VERIFICATION_REJECTED"
        )
        with control.new_session() as session:
            assert session.query(TenantProviderAccount).count() == 0
            assert session.query(TenantProviderAccountSecretRevision).count() == 0
            assert session.query(ProviderAccountClaim).count() == 0
            assert session.query(ControlOutboxEvent).count() == 0
    finally:
        control.dispose()
        tenant_engine.dispose()


def test_admin_unbind_releases_claim_then_removes_local_binding(
    tmp_path, mysql_routed_database
):
    harness = _harness(tmp_path, mysql_routed_database)
    (
        _app,
        client,
        headers,
        control,
        tenant_engine,
        provider,
        tenant_id,
        integration_id,
    ) = harness
    account_id = str(uuid4())
    try:
        _activate_bound_account(
            client=client,
            headers=headers,
            control=control,
            tenant_engine=tenant_engine,
            provider=provider,
            tenant_id=tenant_id,
            integration_id=integration_id,
            account_id=account_id,
        )
        active_list = client.get(
            "/api/integrations/sf/provider-accounts",
            headers=headers,
        ).get_json()["data"]["items"]
        assert active_list[0]["status"] == "active"
        assert active_list[0]["verification_status"] == "succeeded"
        body = {
            "action_id": str(uuid4()),
            "warehouse_id": str(WAREHOUSE_UUID),
            "provider_account_id": account_id,
        }
        issued = client.post(
            "/api/integrations/sf/provider-accounts/unbind-challenges",
            json=body,
            headers=headers,
        )
        assert issued.status_code == 202
        challenge_id = issued.get_json()["data"]["challenge_id"]

        confirmed = client.post(
            "/api/integrations/sf/provider-accounts/unbind-confirm",
            json={
                **body,
                "challenge_id": challenge_id,
                "code": provider.codes[-1],
            },
            headers=headers,
        )
        assert confirmed.status_code == 200
        result = confirmed.get_json()["data"]
        assert result["provider_account_id"] == account_id
        assert result["status"] == "inactive"
        inactive_list = client.get(
            "/api/integrations/sf/provider-accounts",
            headers=headers,
        ).get_json()["data"]["items"]
        assert inactive_list[0]["status"] == "inactive"
        assert inactive_list[0]["warehouse_id"] == str(WAREHOUSE_UUID)

        replay_before_local_cleanup = client.post(
            "/api/integrations/sf/provider-accounts/unbind-confirm",
            json={
                **body,
                "challenge_id": challenge_id,
                "code": provider.codes[-1],
            },
            headers=headers,
        )
        assert replay_before_local_cleanup.status_code == 200
        assert replay_before_local_cleanup.get_json()["data"]["idempotent"] is True

        with control.new_session() as session:
            account = session.get(TenantProviderAccount, account_id)
            claim_event = session.scalar(
                sa.select(ProviderAccountClaimEvent).where(
                    ProviderAccountClaimEvent.source_action_uuid
                    == body["action_id"]
                )
            )
            outbox = session.get(ControlOutboxEvent, result["unbinding_event_id"])
            assert account.status == "inactive"
            assert account.current_global_claim_id is None
            assert claim_event.to_status == "released"
            assert claim_event.previous_tenant_id == tenant_id
            assert outbox.source_uuid == claim_event.provider_account_claim_id
            assert outbox.source_generation == claim_event.claim_generation
            assert outbox.payload["expected_binding_revision"] == 1

        with Session(tenant_engine) as session:
            with session.begin():
                removed = WarehouseProviderBindingService(
                    session
                ).unbind_sf_account(
                    warehouse_uuid=WAREHOUSE_UUID,
                    provider_account_uuid=account_id,
                    expected_binding_revision=1,
                    actor_user_uuid=claim_event.actor_user_uuid,
                    occurred_at=_utc(claim_event.created_at),
                )
            assert removed.status == "inactive"
            assert removed.binding_revision == 2

        replay_after_local_cleanup = client.post(
            "/api/integrations/sf/provider-accounts/unbind-confirm",
            json={
                **body,
                "challenge_id": challenge_id,
                "code": provider.codes[-1],
            },
            headers=headers,
        )
        assert replay_after_local_cleanup.status_code == 200
        assert replay_after_local_cleanup.get_json()["data"]["idempotent"] is True
    finally:
        control.dispose()
        tenant_engine.dispose()


def test_wrong_unbind_code_preserves_claim_account_binding_and_outbox(
    tmp_path, mysql_routed_database
):
    (
        _app,
        client,
        headers,
        control,
        tenant_engine,
        provider,
        tenant_id,
        integration_id,
    ) = _harness(tmp_path, mysql_routed_database)
    account_id = str(uuid4())
    try:
        _activate_bound_account(
            client=client,
            headers=headers,
            control=control,
            tenant_engine=tenant_engine,
            provider=provider,
            tenant_id=tenant_id,
            integration_id=integration_id,
            account_id=account_id,
        )
        with control.new_session() as session:
            outbox_count = session.query(ControlOutboxEvent).count()
        body = {
            "action_id": str(uuid4()),
            "warehouse_id": str(WAREHOUSE_UUID),
            "provider_account_id": account_id,
        }
        issued = client.post(
            "/api/integrations/sf/provider-accounts/unbind-challenges",
            json=body,
            headers=headers,
        )
        challenge_id = issued.get_json()["data"]["challenge_id"]
        wrong = "000000" if provider.codes[-1] != "000000" else "111111"

        rejected = client.post(
            "/api/integrations/sf/provider-accounts/unbind-confirm",
            json={**body, "challenge_id": challenge_id, "code": wrong},
            headers=headers,
        )

        assert rejected.status_code == 403
        with control.new_session() as session:
            account = session.get(TenantProviderAccount, account_id)
            claim = session.get(ProviderAccountClaim, account.current_global_claim_id)
            assert account.status == "active"
            assert claim.claim_status == "active"
            assert session.query(ControlOutboxEvent).count() == outbox_count
            assert session.query(ProviderAccountClaimEvent).filter_by(
                source_action_uuid=body["action_id"]
            ).count() == 0
        with Session(tenant_engine) as session:
            with session.begin():
                binding = WarehouseProviderBindingService(
                    session
                ).resolve_active_sf_binding(warehouse_uuid=WAREHOUSE_UUID)
            assert binding.provider_account_uuid == account_id
    finally:
        control.dispose()
        tenant_engine.dispose()


def _activate_bound_account(
    *,
    client,
    headers,
    control,
    tenant_engine,
    provider,
    tenant_id,
    integration_id,
    account_id,
):
    action_id = str(uuid4())
    body = {
        "action_id": action_id,
        "warehouse_id": str(WAREHOUSE_UUID),
        "provider_account_id": account_id,
        "integration_id": integration_id,
        "label": "Default warehouse",
        "account": "001234567890",
    }
    issued = client.post(
        "/api/integrations/sf/provider-accounts/bind-challenges",
        json=body,
        headers=headers,
    )
    assert issued.status_code == 202
    challenge_id = issued.get_json()["data"]["challenge_id"]
    confirmed = client.post(
        "/api/integrations/sf/provider-accounts/bind-confirm",
        json={
            **body,
            "challenge_id": challenge_id,
            "code": provider.codes[-1],
        },
        headers=headers,
    )
    assert confirmed.status_code == 200
    revision_id = confirmed.get_json()["data"]["revision_id"]
    attempt_id = uuid4()
    with control.transaction() as session:
        revision = session.get(TenantProviderAccountSecretRevision, revision_id)
        intent = session.get(TenantSensitiveActionIntent, action_id)
        TenantProviderAccountService(session).begin_provider_validation(
            revision_uuid=revision.id,
            attempt_uuid=attempt_id,
            expected_revision_row_version=revision.row_version,
        )
        proof = SfAdminClaimProof(
            tenant_uuid=UUID(tenant_id),
            actor_user_uuid=UUID(intent.actor_user_id),
            actor_session_uuid=UUID(intent.actor_session_id),
            role=TenantRole.ADMIN,
            effective_gate=EffectiveTenantGate.ACTIVE,
            tenant_access_version=3,
            otp_challenge_uuid=UUID(challenge_id),
            otp_purpose="sf_account_bind",
            otp_action_uuid=UUID(action_id),
            otp_request_digest=bytes(revision.request_digest),
            otp_consumed=True,
        )
    with control.transaction() as session:
        activated = TenantProviderAccountService(
            session
        ).record_provider_validation_result(
            revision_uuid=revision_id,
            attempt_uuid=attempt_id,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=hashlib.sha256(b"valid-account").digest(),
            safe_code="VALID",
            proof=proof,
            owner=SfClaimOwner(
                tenant_uuid=UUID(tenant_id),
                provider_account_uuid=UUID(account_id),
                warehouse_uuid=WAREHOUSE_UUID,
            ),
            binding_revision=1,
        )
        challenge = session.get(SmsChallenge, challenge_id)
        challenge.created_at = challenge.created_at - timedelta(minutes=2)
        if challenge.delivery_recorded_at is not None:
            challenge.delivery_recorded_at = (
                challenge.delivery_recorded_at - timedelta(minutes=2)
            )
    with Session(tenant_engine) as session:
        with session.begin():
            WarehouseProviderBindingService(session).bind_sf_account(
                warehouse_uuid=WAREHOUSE_UUID,
                provider_account_uuid=account_id,
                binding_revision=1,
                actor_user_uuid=proof.actor_user_uuid,
                verified_at=datetime.now(timezone.utc),
                expected_provider_account_uuid=None,
                expected_binding_revision=None,
            )
    return activated


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
