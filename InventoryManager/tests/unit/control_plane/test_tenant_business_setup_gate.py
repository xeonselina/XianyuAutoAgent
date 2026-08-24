from __future__ import annotations

import pytest

from app import db
from app.models.warehouse import Warehouse
from app.services.tenant_business.http_runtime import (
    TenantSetupRequired,
    _require_ready_default_warehouse,
)


def test_normal_business_scope_rejects_pending_default(application):
    db.session.add(Warehouse.pending_default(contact_phone="13800138000"))
    db.session.commit()

    with pytest.raises(TenantSetupRequired) as rejected:
        _require_ready_default_warehouse(db.session())

    assert rejected.value.code == "tenant_setup_required"
    assert rejected.value.status_code == 409


def test_normal_business_scope_accepts_exactly_one_active_ready_default(
    application,
):
    warehouse = Warehouse.pending_default(contact_phone="13800138000")
    warehouse.mark_ready(
        name="默认仓库",
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="测试路 1 号",
    )
    db.session.add(warehouse)
    db.session.commit()

    _require_ready_default_warehouse(db.session())


def test_normal_business_scope_rejects_inactive_default(application):
    warehouse = Warehouse.pending_default(contact_phone="13800138000")
    warehouse.mark_ready(
        name="默认仓库",
        contact_name="负责人",
        contact_phone="13800138000",
        province="广东省",
        city="深圳市",
        district="南山区",
        address_detail="测试路 1 号",
    )
    warehouse.status = "inactive"
    db.session.add(warehouse)
    db.session.commit()

    with pytest.raises(TenantSetupRequired):
        _require_ready_default_warehouse(db.session())
