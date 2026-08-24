from __future__ import annotations

import hashlib
from uuid import UUID

import pytest

from inventory_control import ControlBase, ControlDatabase
from inventory_control.crypto import RootKey, RootKeyLifecycle, RootKeyRing
from inventory_control.integrations import (
    ProviderValidationOutcome,
    TenantIntegrationService,
    XianyuSyncCredentialError,
    XianyuSyncCredentialFactory,
    XianyuSyncCredentialInputError,
)
from inventory_control.models import Tenant, TenantIntegration


TENANT = UUID("71000000-0000-4000-8000-000000000001")
USER = UUID("71000000-0000-4000-8000-000000000002")
INTEGRATION = UUID("71000000-0000-4000-8000-000000000003")
ACTION = UUID("71000000-0000-4000-8000-000000000004")
ATTEMPT = UUID("71000000-0000-4000-8000-000000000005")
LEGACY_KEY = RootKey(version=1, material=b"x" * 32)
ACTIVE_KEY = RootKey(version=2, material=b"y" * 32)
KEY_RING = RootKeyRing(
    active_version=2,
    keys={1: LEGACY_KEY, 2: ACTIVE_KEY},
    statuses={1: RootKeyLifecycle.LEGACY, 2: RootKeyLifecycle.ACTIVE},
)


@pytest.fixture
def configured(mysql_control_database):
    database = mysql_control_database
    with database.transaction() as session:
        session.add(Tenant(id=str(TENANT), status="active"))
    with database.transaction() as session:
        TenantIntegrationService(session).create_integration(
            integration_uuid=INTEGRATION,
            tenant_uuid=TENANT,
            provider="xianyu",
            name="main-xianyu",
        )
    with database.transaction() as session:
        pending = TenantIntegrationService(session).create_pending_revision(
            integration_uuid=INTEGRATION,
            credentials={"app_key": "xianyu-app", "app_secret": "secret-value"},
            root_key=LEGACY_KEY,
            created_by_user_uuid=USER,
            action_uuid=ACTION,
            idempotency_key="xianyu-revision-1",
            expected_integration_row_version=1,
            expected_current_secret_revision_uuid=None,
        )
    with database.transaction() as session:
        TenantIntegrationService(session).begin_provider_validation(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT,
            expected_revision_row_version=1,
        )
    with database.transaction() as session:
        TenantIntegrationService(session).record_provider_validation_result(
            revision_uuid=pending.revision_uuid,
            attempt_uuid=ATTEMPT,
            outcome=ProviderValidationOutcome.SUCCESS,
            provider_result_digest=hashlib.sha256(b"valid").digest(),
            safe_code="VALID",
        )
    with database.new_session() as session:
        integration = session.get(TenantIntegration, str(INTEGRATION))
        facts = (
            integration.current_secret_revision_id,
            integration.row_version,
        )
    return database, facts


def _prepare(configured, **overrides):
    database, (revision_uuid, integration_version) = configured
    values = {
        "tenant_uuid": TENANT,
        "integration_uuid": INTEGRATION,
        "secret_revision_uuid": revision_uuid,
        "integration_row_version": integration_version,
        "revision_row_version": 3,
        "provider_cursor": "cursor-previous",
        "root_key_ring": KEY_RING,
    }
    values.update(overrides)
    with database.transaction() as session:
        return XianyuSyncCredentialFactory(session).prepare(**values)


def test_factory_uses_named_legacy_key_and_consumes_credentials_once(configured):
    request = _prepare(configured)

    assert request.context.tenant_uuid == str(TENANT)
    assert request.context.integration_uuid == str(INTEGRATION)
    assert request.provider_cursor == "cursor-previous"
    assert "xianyu-app" not in repr(request)
    assert "secret-value" not in repr(request)
    assert "cursor-previous" not in repr(request)
    assert dict(request.take_credentials()) == {
        "app_key": "xianyu-app",
        "app_secret": "secret-value",
    }
    with pytest.raises(XianyuSyncCredentialError):
        request.take_credentials()


@pytest.mark.parametrize(
    "override",
    (
        {"integration_row_version": 999},
        {"revision_row_version": 999},
        {"tenant_uuid": UUID("71000000-0000-4000-8000-000000000099")},
    ),
)
def test_factory_rejects_stale_or_cross_tenant_job_facts(configured, override):
    with pytest.raises(XianyuSyncCredentialError):
        _prepare(configured, **override)


def test_factory_never_falls_back_to_active_root_key(configured):
    active_only = RootKeyRing(
        active_version=2,
        keys={2: ACTIVE_KEY},
        statuses={2: RootKeyLifecycle.ACTIVE},
    )

    with pytest.raises(XianyuSyncCredentialError):
        _prepare(configured, root_key_ring=active_only)


def test_factory_requires_explicit_caller_transaction(configured):
    database, (revision_uuid, integration_version) = configured
    with database.new_session() as session:
        with pytest.raises(XianyuSyncCredentialInputError):
            XianyuSyncCredentialFactory(session).prepare(
                tenant_uuid=TENANT,
                integration_uuid=INTEGRATION,
                secret_revision_uuid=revision_uuid,
                integration_row_version=integration_version,
                revision_row_version=3,
                provider_cursor=None,
                root_key_ring=KEY_RING,
            )
