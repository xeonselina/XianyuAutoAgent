import base64
from datetime import datetime

import pytest
from sqlalchemy import select
from werkzeug.security import check_password_hash

from app.auth import PasswordPolicyError
from app.control.models import ControlBase, Tenant, TenantMember
from app.control.store import ControlStore
from app.crypto import SecretBox
from app.provisioning import TenantProvisioner


MASTER_KEY = base64.b64encode(bytes(range(32))).decode("ascii")
INITIAL_PASSWORD = "tenant-initial-password-123"


@pytest.fixture
def provisioner(tmp_path, monkeypatch):
    control_url = f"sqlite+pysqlite:///{tmp_path / 'control.db'}"
    provisioner_url = f"sqlite+pysqlite:///{tmp_path / 'provisioner.db'}"
    store = ControlStore(
        control_url,
        SecretBox.from_base64(MASTER_KEY),
    )
    ControlBase.metadata.create_all(store.engine)
    service = TenantProvisioner(
        store=store,
        provisioner_database_url=provisioner_url,
        migrations_directory=str(tmp_path),
        tenant_db_host="127.0.0.1",
        tenant_db_port=3306,
        database_prefix="inventory_unit_tenant_",
        user_prefix="iu_t",
    )
    monkeypatch.setattr(service, "_provision", service._get_tenant)
    try:
        yield service, store
    finally:
        service.dispose()
        store.dispose()


def test_super_admin_creation_sets_a_hashed_initial_admin_password(provisioner):
    service, store = provisioner

    tenant = service.create(
        "客户店铺甲",
        "13800138000",
        datetime(2026, 9, 28, 12, 0, 0),
        INITIAL_PASSWORD,
    )

    with store.session() as session:
        member = session.scalar(
            select(TenantMember).where(TenantMember.tenant_id == tenant.id)
        )
        assert member.phone == "+8613800138000"
        assert member.role == "admin"
        assert member.status == "active"
        assert member.password_hash != INITIAL_PASSWORD
        assert check_password_hash(member.password_hash, INITIAL_PASSWORD)
        assert member.password_changed_at is not None


@pytest.mark.parametrize("initial_password", [None, "short7!", "x" * 129])
def test_invalid_initial_password_creates_no_tenant(provisioner, initial_password):
    service, store = provisioner

    with pytest.raises(PasswordPolicyError):
        service.create(
            "客户店铺甲",
            "13800138000",
            datetime(2026, 9, 28, 12, 0, 0),
            initial_password,
        )

    with store.session() as session:
        assert session.scalars(select(Tenant)).all() == []
        assert session.scalars(select(TenantMember)).all() == []
