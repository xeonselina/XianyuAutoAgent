from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

import pytest

from app import create_app, db
from app.models.warehouse import Warehouse, WarehouseProviderBinding
from app.services.warehouse import (
    WarehouseProviderBindingConflictError,
    WarehouseProviderBindingService,
    WarehouseProviderBindingTransactionError,
    WarehouseProviderBindingUnavailableError,
)
from app.services.tenant_integrations import (
    SfWarehouseBindingApplyRequest,
    SqlAlchemyTenantWarehouseBindingApplier,
)


WAREHOUSE_UUID = UUID("70000000-0000-4000-8000-000000000001")
ACCOUNT_A = UUID("70000000-0000-4000-8000-000000000002")
ACCOUNT_B = UUID("70000000-0000-4000-8000-000000000003")
ACTOR_UUID = UUID("70000000-0000-4000-8000-000000000004")
NOW = datetime(2026, 8, 23, 4, 0, tzinfo=timezone.utc)


@pytest.fixture
def application():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
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
            contact_phone="13800138000",
            province="广东省",
            city="深圳市",
            district="南山区",
            address_detail="测试地址",
        )
        db.session.add(warehouse)
        db.session.commit()
        try:
            yield app
        finally:
            db.session.remove()
            db.drop_all()


def _bind(*, account=ACCOUNT_A, revision=1, expected_account=None, expected=None):
    with db.session.begin():
        return WarehouseProviderBindingService(db.session).bind_sf_account(
            warehouse_uuid=WAREHOUSE_UUID,
            provider_account_uuid=account,
            binding_revision=revision,
            actor_user_uuid=ACTOR_UUID,
            verified_at=NOW,
            expected_provider_account_uuid=expected_account,
            expected_binding_revision=expected,
        )


def test_bind_replay_replace_and_unbind_are_monotonic(application):
    first = _bind()
    replay = _bind()
    with db.session.begin():
        resolved = WarehouseProviderBindingService(
            db.session
        ).resolve_active_sf_binding(warehouse_uuid=WAREHOUSE_UUID)
    replaced = _bind(
        account=ACCOUNT_B,
        revision=2,
        expected_account=ACCOUNT_A,
        expected=1,
    )
    with db.session.begin():
        inactive = WarehouseProviderBindingService(db.session).unbind_sf_account(
            warehouse_uuid=WAREHOUSE_UUID,
            provider_account_uuid=ACCOUNT_B,
            expected_binding_revision=2,
            actor_user_uuid=ACTOR_UUID,
            occurred_at=NOW,
        )
    with db.session.begin():
        unbind_replay = WarehouseProviderBindingService(
            db.session
        ).unbind_sf_account(
            warehouse_uuid=WAREHOUSE_UUID,
            provider_account_uuid=ACCOUNT_B,
            expected_binding_revision=2,
            actor_user_uuid=ACTOR_UUID,
            occurred_at=NOW,
        )

    assert first.binding_revision == 1
    assert replay.idempotent_replay is True
    assert resolved.provider_account_uuid == str(ACCOUNT_A)
    assert replaced.provider_account_uuid == str(ACCOUNT_B)
    assert replaced.binding_revision == 2
    assert inactive.status == "inactive"
    assert inactive.provider_account_uuid is None
    assert inactive.binding_revision == 3
    assert unbind_replay.idempotent_replay is True


def test_stale_replace_does_not_change_active_binding(application):
    _bind()

    with pytest.raises(WarehouseProviderBindingConflictError):
        _bind(
            account=ACCOUNT_B,
            revision=3,
            expected_account=ACCOUNT_A,
            expected=1,
        )

    row = db.session.get(
        WarehouseProviderBinding,
        {"warehouse_id": 1, "provider": "sf"},
    )
    assert row.provider_account_uuid == str(ACCOUNT_A)
    assert row.binding_revision == 1


def test_binding_plan_is_monotonic_and_reuses_current_revision(application):
    with db.session.begin():
        initial = WarehouseProviderBindingService(
            db.session
        ).plan_sf_account_binding(
            warehouse_uuid=WAREHOUSE_UUID,
            provider_account_uuid=ACCOUNT_A,
        )
    assert initial.expected_binding_revision is None
    assert initial.target_binding_revision == 1
    assert initial.binding_already_current is False

    _bind()
    with db.session.begin():
        same = WarehouseProviderBindingService(
            db.session
        ).plan_sf_account_binding(
            warehouse_uuid=WAREHOUSE_UUID,
            provider_account_uuid=ACCOUNT_A,
        )
    with db.session.begin():
        replacement = WarehouseProviderBindingService(
            db.session
        ).plan_sf_account_binding(
            warehouse_uuid=WAREHOUSE_UUID,
            provider_account_uuid=ACCOUNT_B,
        )
    assert same.expected_binding_revision == 1
    assert same.target_binding_revision == 1
    assert same.binding_already_current is True
    assert replacement.expected_provider_account_uuid == str(ACCOUNT_A)
    assert replacement.expected_binding_revision == 1
    assert replacement.target_binding_revision == 2


def test_sqlalchemy_worker_applier_uses_exact_local_cas(application):
    request = SfWarehouseBindingApplyRequest(
        tenant_id="70000000-0000-4000-8000-000000000010",
        tenant_access_version=1,
        warehouse_id=str(WAREHOUSE_UUID),
        provider_account_id=str(ACCOUNT_A),
        account_revision_id="70000000-0000-4000-8000-000000000011",
        account_revision_no=1,
        target_binding_revision=1,
        expected_provider_account_id=None,
        expected_binding_revision=None,
        actor_user_id=str(ACTOR_UUID),
        verified_at=NOW,
    )
    applier = SqlAlchemyTenantWarehouseBindingApplier(
        engine_resolver=lambda command: db.engine
    )

    first = applier.apply_binding(request)
    replay = applier.apply_binding(request)

    assert first.binding_revision == 1
    assert first.idempotent_replay is False
    assert replay.idempotent_replay is True
    row = db.session.get(
        WarehouseProviderBinding,
        {"warehouse_id": 1, "provider": "sf"},
    )
    assert row.provider_account_uuid == str(ACCOUNT_A)


def test_inactive_warehouse_and_implicit_transaction_are_rejected(application):
    warehouse = db.session.scalar(
        db.select(Warehouse).where(Warehouse.warehouse_uuid == str(WAREHOUSE_UUID))
    )
    warehouse.status = "inactive"
    db.session.commit()
    with pytest.raises(WarehouseProviderBindingUnavailableError):
        _bind()

    db.session.rollback()
    with pytest.raises(WarehouseProviderBindingTransactionError):
        WarehouseProviderBindingService(db.session).bind_sf_account(
            warehouse_uuid=WAREHOUSE_UUID,
            provider_account_uuid=ACCOUNT_A,
            binding_revision=1,
            actor_user_uuid=ACTOR_UUID,
            verified_at=NOW,
            expected_provider_account_uuid=None,
            expected_binding_revision=None,
        )
