import base64
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select
from werkzeug.security import check_password_hash, generate_password_hash

from app.auth import create_auth_session
from app.control.models import AuthSession, ControlBase, Tenant, TenantMember
from app.control.store import ControlStore
from app.crypto import SecretBox
from app.services.settings_service import (
    SettingsNotFoundError,
    SettingsService,
    SettingsValidationError,
)


MASTER_KEY = base64.b64encode(bytes(range(32))).decode("ascii")


@pytest.fixture
def member_settings_environment(tmp_path):
    box = SecretBox.from_base64(MASTER_KEY)
    store = ControlStore(
        f"sqlite+pysqlite:///{tmp_path / 'control.db'}",
        secret_box=box,
    )
    ControlBase.metadata.create_all(store.engine)
    with store.session() as session:
        tenant = Tenant(
            name="成员密码租户",
            status="active",
            expires_at=datetime.utcnow() + timedelta(days=30),
            db_name="member_password_tenant",
            db_username="member_password_user",
            db_password_ciphertext=box.encrypt(
                "database-password", purpose="tenant-db-password"
            ),
            provisioning_status="active",
        )
        other_tenant = Tenant(
            name="其他租户",
            status="active",
            expires_at=datetime.utcnow() + timedelta(days=30),
            db_name="other_member_password_tenant",
            db_username="other_member_password_user",
            db_password_ciphertext=box.encrypt(
                "database-password", purpose="tenant-db-password"
            ),
            provisioning_status="active",
        )
        session.add_all((tenant, other_tenant))
        session.flush()
        managed_member = TenantMember(
            tenant_id=tenant.id,
            phone="+8613800138001",
            role="operator",
            status="active",
            password_hash=generate_password_hash("OldPass8"),
            failed_password_attempts=4,
            password_locked_until=datetime.utcnow() + timedelta(minutes=10),
        )
        outside_member = TenantMember(
            tenant_id=other_tenant.id,
            phone="+8613800138002",
            role="operator",
            status="active",
            password_hash=generate_password_hash("Outside8"),
        )
        session.add_all((managed_member, outside_member))
        session.flush()
        create_auth_session(
            session,
            kind="tenant",
            subject_id=managed_member.id,
            tenant_id=tenant.id,
        )
        ids = {
            "tenant": tenant.id,
            "managed": managed_member.id,
            "outside": outside_member.id,
        }

    try:
        yield store, SettingsService(None, store, ids["tenant"]), ids
    finally:
        store.dispose()


def test_create_member_accepts_eight_characters_and_stores_only_hash(
    member_settings_environment,
):
    store, service, _ids = member_settings_environment

    payload = service.create_member(
        "13900139000", "Passw0rd", role="operator"
    )

    assert payload == {
        "id": payload["id"],
        "phone": "+8613900139000",
        "role": "operator",
        "status": "active",
    }
    with store.session() as session:
        member = session.get(TenantMember, payload["id"])
        assert member.password_hash != "Passw0rd"
        assert check_password_hash(member.password_hash, "Passw0rd")
        assert member.password_changed_at is not None


def test_create_member_rejects_seven_characters_without_writing(
    member_settings_environment,
):
    store, service, _ids = member_settings_environment

    with pytest.raises(
        SettingsValidationError,
        match="初始密码必须为 8 至 128 个字符",
    ):
        service.create_member("13900139000", "short7!")

    with store.session() as session:
        assert session.scalar(
            select(TenantMember).where(
                TenantMember.phone == "+8613900139000"
            )
        ) is None


def test_reset_member_password_clears_lock_and_revokes_sessions(
    member_settings_environment,
):
    store, service, ids = member_settings_environment

    payload = service.reset_member_password(ids["managed"], "NewPass8")

    assert "password" not in payload
    with store.session() as session:
        member = session.get(TenantMember, ids["managed"])
        assert check_password_hash(member.password_hash, "NewPass8")
        assert member.failed_password_attempts == 0
        assert member.password_locked_until is None
        assert member.password_changed_at is not None
        assert session.scalars(select(AuthSession)).all() == []


def test_invalid_reset_password_preserves_credential_and_sessions(
    member_settings_environment,
):
    store, service, ids = member_settings_environment
    with store.session() as session:
        old_hash = session.get(
            TenantMember, ids["managed"]
        ).password_hash

    with pytest.raises(
        SettingsValidationError,
        match="新密码必须为 8 至 128 个字符",
    ):
        service.reset_member_password(ids["managed"], "short7!")

    with store.session() as session:
        assert session.get(
            TenantMember, ids["managed"]
        ).password_hash == old_hash
        assert len(session.scalars(select(AuthSession)).all()) == 1


def test_reset_member_password_cannot_cross_tenant_boundary(
    member_settings_environment,
):
    store, service, ids = member_settings_environment
    with store.session() as session:
        old_hash = session.get(
            TenantMember, ids["outside"]
        ).password_hash

    with pytest.raises(SettingsNotFoundError, match="成员不存在"):
        service.reset_member_password(ids["outside"], "NewPass8")

    with store.session() as session:
        assert session.get(
            TenantMember, ids["outside"]
        ).password_hash == old_hash
