from __future__ import annotations

from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

import pytest
import sqlalchemy as sa
from sqlalchemy import event

from app import create_app, db
from app.models.database_identity import TenantDatabaseIdentity
from app.models.device import Device
from app.models.warehouse import Warehouse
from app.services.migration.default_warehouse_backfill import (
    DefaultWarehouseBackfillInputError,
    DefaultWarehouseBackfillService,
    DefaultWarehouseBackfillTransactionError,
    DefaultWarehouseConflictError,
    DefaultWarehouseIdentityMismatchError,
    DefaultWarehouseProfile,
    derive_default_warehouse_uuid,
)


TENANT_UUID = uuid5(NAMESPACE_URL, "default-warehouse-backfill/tenant")
DATABASE_UUID = uuid5(NAMESPACE_URL, "default-warehouse-backfill/database")
SCHEMA_GENERATION = 8
BASELINE_ID = "initial-baseline-v1"


@pytest.fixture
def application():
    app = create_app("testing")
    with app.app_context():
        db.create_all()
        try:
            yield app
        finally:
            db.session.remove()
            db.drop_all()


def _seed_identity(
    *,
    tenant_uuid: UUID = TENANT_UUID,
    database_uuid: UUID = DATABASE_UUID,
    schema_generation: int = SCHEMA_GENERATION,
):
    db.session.add(
        TenantDatabaseIdentity(
            singleton_key=1,
            tenant_id=str(tenant_uuid),
            database_uuid=str(database_uuid),
            schema_generation=schema_generation,
        )
    )
    db.session.commit()


def _ready_profile() -> DefaultWarehouseProfile:
    return DefaultWarehouseProfile(
        name=" 默认仓库 ",
        contact_name=" 迁移联系人 ",
        contact_phone=" 13800138000 ",
        province=" 广东省 ",
        city=" 深圳市 ",
        district=" 南山区 ",
        address_detail=" 科技园测试地址 1 号 ",
    )


def _backfill(
    profile: DefaultWarehouseProfile,
    *,
    tenant_uuid: UUID = TENANT_UUID,
    database_uuid: UUID = DATABASE_UUID,
    schema_generation: int = SCHEMA_GENERATION,
    baseline_id: str = BASELINE_ID,
):
    session = db.session()
    with session.begin():
        return DefaultWarehouseBackfillService().backfill(
            session,
            tenant_uuid=tenant_uuid,
            database_uuid=database_uuid,
            expected_schema_generation=schema_generation,
            baseline_migration_id=baseline_id,
            profile=profile,
        )


def test_pending_backfill_creates_stable_default_and_assigns_only_null_devices(
    application,
):
    _seed_identity()
    unassigned = Device(name="待回填设备")
    other = Warehouse(
        warehouse_uuid=str(uuid4()),
        name="既有仓库",
        status="active",
        setup_state="ready",
        is_default=False,
        default_slot=None,
        contact_name="既有联系人",
        contact_phone="13900139000",
        province="广东省",
        city="深圳市",
        district="福田区",
        address_detail="既有地址",
    )
    already_assigned = Device(name="已归属设备", warehouse=other)
    db.session.add_all([unassigned, other, already_assigned])
    db.session.flush()
    unassigned_id = unassigned.id
    already_assigned_id = already_assigned.id
    other_id = other.id
    db.session.commit()

    result = _backfill(DefaultWarehouseProfile())

    expected_uuid = derive_default_warehouse_uuid(
        database_uuid=DATABASE_UUID,
        baseline_migration_id=BASELINE_ID,
    )
    assert result.warehouse_uuid == expected_uuid
    assert result.setup_state == "pending"
    assert result.warehouse_created is True
    assert result.assigned_device_ids == (unassigned_id,)
    assert result.preserved_assigned_device_count == 1
    assert result.idempotent_replay is False
    warehouse = db.session.get(Warehouse, result.warehouse_id)
    assert warehouse.warehouse_uuid == str(expected_uuid)
    assert warehouse.setup_state == "pending"
    assert warehouse.is_default is True
    assert warehouse.default_slot == 1
    for field_name in (
        "name",
        "contact_name",
        "contact_phone",
        "province",
        "city",
        "district",
        "address_detail",
    ):
        assert getattr(warehouse, field_name) is None
    assert db.session.get(Device, unassigned_id).warehouse_id == warehouse.id
    assert db.session.get(Device, already_assigned_id).warehouse_id == other_id


def test_complete_profile_creates_ready_default_and_exactly_replays(application):
    _seed_identity()
    db.session.add_all([Device(name="设备 B"), Device(name="设备 A")])
    db.session.commit()
    profile = _ready_profile()

    first = _backfill(profile)
    replay = _backfill(profile)

    assert first.setup_state == "ready"
    assert first.warehouse_created is True
    assert first.assigned_device_ids == tuple(sorted(first.assigned_device_ids))
    assert replay.warehouse_id == first.warehouse_id
    assert replay.warehouse_uuid == first.warehouse_uuid
    assert replay.warehouse_created is False
    assert replay.assigned_device_ids == ()
    assert replay.preserved_assigned_device_count == 2
    assert replay.idempotent_replay is True
    assert db.session.scalar(sa.select(sa.func.count()).select_from(Warehouse)) == 1
    warehouse = db.session.get(Warehouse, first.warehouse_id)
    assert warehouse.setup_state == "ready"
    assert warehouse.name == "默认仓库"
    assert warehouse.contact_name == "迁移联系人"
    assert warehouse.contact_phone == "13800138000"
    assert warehouse.province == "广东省"
    assert warehouse.city == "深圳市"
    assert warehouse.district == "南山区"
    assert warehouse.address_detail == "科技园测试地址 1 号"


def test_profile_is_all_missing_or_all_valid_and_repr_is_redacted():
    profile = _ready_profile()
    rendered = repr(profile)
    for sensitive in (
        "默认仓库",
        "迁移联系人",
        "13800138000",
        "广东省",
        "深圳市",
        "南山区",
        "科技园测试地址 1 号",
    ):
        assert sensitive not in rendered
    assert "<redacted>" in rendered

    with pytest.raises(DefaultWarehouseBackfillInputError) as caught:
        DefaultWarehouseProfile(
            name="敏感仓库名",
            contact_phone="13800138000",
        )
    assert "敏感仓库名" not in str(caught.value)
    assert "13800138000" not in repr(caught.value)

    with pytest.raises(DefaultWarehouseBackfillInputError):
        DefaultWarehouseProfile(
            name=" ",
            contact_name="联系人",
            contact_phone="13800138000",
            province="广东省",
            city="深圳市",
            district="南山区",
            address_detail="详细地址",
        )


@pytest.mark.parametrize(
    ("tenant_uuid", "database_uuid", "schema_generation"),
    (
        (uuid4(), DATABASE_UUID, SCHEMA_GENERATION),
        (TENANT_UUID, uuid4(), SCHEMA_GENERATION),
        (TENANT_UUID, DATABASE_UUID, SCHEMA_GENERATION + 1),
    ),
)
def test_identity_mismatch_fails_before_warehouse_write(
    application,
    tenant_uuid,
    database_uuid,
    schema_generation,
):
    _seed_identity()

    with pytest.raises(DefaultWarehouseIdentityMismatchError):
        _backfill(
            DefaultWarehouseProfile(),
            tenant_uuid=tenant_uuid,
            database_uuid=database_uuid,
            schema_generation=schema_generation,
        )

    assert db.session.scalar(sa.select(sa.func.count()).select_from(Warehouse)) == 0


def test_changed_profile_or_baseline_conflicts_without_rewriting_default(
    application,
):
    _seed_identity()
    pending = _backfill(DefaultWarehouseProfile())

    with pytest.raises(DefaultWarehouseConflictError):
        _backfill(_ready_profile())
    with pytest.raises(DefaultWarehouseConflictError):
        _backfill(DefaultWarehouseProfile(), baseline_id="initial-baseline-v2")

    warehouse = db.session.get(Warehouse, pending.warehouse_id)
    assert warehouse.setup_state == "pending"
    assert warehouse.warehouse_uuid == str(pending.warehouse_uuid)
    assert db.session.scalar(sa.select(sa.func.count()).select_from(Warehouse)) == 1


def test_existing_different_default_and_multiple_defaults_fail_closed(application):
    _seed_identity()
    db.session.add(
        Warehouse(
            warehouse_uuid=str(uuid4()),
            status="active",
            setup_state="pending",
            is_default=True,
            default_slot=1,
        )
    )
    db.session.commit()
    with pytest.raises(DefaultWarehouseConflictError):
        _backfill(DefaultWarehouseProfile())

    db.session.query(Warehouse).delete()
    db.session.commit()
    expected_uuid = derive_default_warehouse_uuid(
        database_uuid=DATABASE_UUID,
        baseline_migration_id=BASELINE_ID,
    )
    connection = db.session.connection()
    connection.exec_driver_sql("PRAGMA ignore_check_constraints = ON")
    now = datetime.utcnow()
    connection.execute(
        sa.insert(Warehouse.__table__),
        (
            {
                "warehouse_uuid": str(expected_uuid),
                "status": "active",
                "setup_state": "pending",
                "is_default": True,
                "default_slot": 1,
                "created_at": now,
                "updated_at": now,
            },
            {
                "warehouse_uuid": str(uuid4()),
                "status": "active",
                "setup_state": "pending",
                "is_default": True,
                "default_slot": None,
                "created_at": now,
                "updated_at": now,
            },
        ),
    )
    db.session.commit()
    db.session.execute(sa.text("PRAGMA ignore_check_constraints = OFF"))
    db.session.commit()

    with pytest.raises(DefaultWarehouseConflictError):
        _backfill(DefaultWarehouseProfile())


def test_lock_order_is_identity_then_warehouses_then_devices(application):
    _seed_identity()
    db.session.add(Device(name="锁序设备"))
    db.session.commit()
    sequence: list[str] = []

    def capture(_connection, _cursor, statement, _parameters, _context, _many):
        lowered = statement.lower()
        if not lowered.lstrip().startswith("select"):
            return
        if "database_identity" in lowered:
            sequence.append("identity")
        elif "warehouses" in lowered:
            sequence.append("warehouses")
        elif "devices" in lowered:
            sequence.append("devices")

    event.listen(db.engine, "before_cursor_execute", capture)
    try:
        _backfill(DefaultWarehouseProfile())
    finally:
        event.remove(db.engine, "before_cursor_execute", capture)

    assert sequence[:3] == ["identity", "warehouses", "devices"]


def test_service_requires_explicit_clean_transaction(application):
    _seed_identity()
    session = db.session()
    with pytest.raises(DefaultWarehouseBackfillTransactionError):
        DefaultWarehouseBackfillService().backfill(
            session,
            tenant_uuid=TENANT_UUID,
            database_uuid=DATABASE_UUID,
            expected_schema_generation=SCHEMA_GENERATION,
            baseline_migration_id=BASELINE_ID,
            profile=DefaultWarehouseProfile(),
        )

    with session.begin():
        session.add(Device(name="未提交设备"))
        with pytest.raises(DefaultWarehouseBackfillTransactionError):
            DefaultWarehouseBackfillService().backfill(
                session,
                tenant_uuid=TENANT_UUID,
                database_uuid=DATABASE_UUID,
                expected_schema_generation=SCHEMA_GENERATION,
                baseline_migration_id=BASELINE_ID,
                profile=DefaultWarehouseProfile(),
            )
        session.rollback()


def test_outer_rollback_removes_warehouse_and_device_assignments(application):
    class RollbackProbe(RuntimeError):
        pass

    _seed_identity()
    device = Device(name="回滚设备")
    db.session.add(device)
    db.session.commit()
    device_id = device.id
    db.session.remove()
    session = db.session()
    try:
        with pytest.raises(RollbackProbe):
            with session.begin():
                DefaultWarehouseBackfillService().backfill(
                    session,
                    tenant_uuid=TENANT_UUID,
                    database_uuid=DATABASE_UUID,
                    expected_schema_generation=SCHEMA_GENERATION,
                    baseline_migration_id=BASELINE_ID,
                    profile=DefaultWarehouseProfile(),
                )
                raise RollbackProbe()
    finally:
        db.session.remove()

    assert db.session.scalar(sa.select(sa.func.count()).select_from(Warehouse)) == 0
    assert db.session.get(Device, device_id).warehouse_id is None
