"""MariaDB coverage for the lightweight warehouse/shop schema migrations."""

import os
from datetime import datetime
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from flask import Flask
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError


MIGRATIONS_DIRECTORY = str(
    Path(__file__).resolve().parents[2] / "migrations"
)
CURRENT_PHASE_1_HEAD = "20260825_audit_schema"
EXPAND_REVISION = "20260824_saas_lite_expand"
CONTRACT_REVISION = "20260824_saas_lite_contract"
APPROVED_NEW_TABLES = {
    "warehouses",
    "warehouse_sf_configs",
    "warehouse_kuaimai_configs",
    "xianyu_shops",
}
DATABASE_ENVIRONMENTS = {
    "TEST_TENANT_DATABASE_URL_A": "tenant_a_saas_test",
    "TEST_TENANT_DATABASE_URL_B": "tenant_b_saas_test",
}


def _required_test_url(environment_name):
    raw_url = os.environ.get(environment_name)
    if not raw_url:
        pytest.skip(f"{environment_name} is required for MariaDB test")
    parsed = make_url(raw_url)
    expected_database = DATABASE_ENVIRONMENTS[environment_name]
    if parsed.database != expected_database:
        raise RuntimeError(
            f"{environment_name} must target {expected_database}"
        )
    return parsed.render_as_string(hide_password=False)


def _assert_test_only_grants(connection):
    allowed_databases = set(DATABASE_ENVIRONMENTS.values()) | {
        "control_saas_test"
    }
    for grant in connection.exec_driver_sql(
        "SHOW GRANTS FOR CURRENT_USER"
    ).scalars():
        normalized = grant.replace("\\_", "_").replace("\\%", "%")
        if normalized.startswith("GRANT USAGE ON *.*"):
            continue
        if any(
            token in normalized
            for database in allowed_databases
            for token in (f"ON `{database}`.*", f"ON {database}.*")
        ):
            continue
        raise RuntimeError("test user has privileges outside fixed test DBs")


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


def _upgrade(database_url, revision):
    application = Flask("saas_lite_business_migration_test")
    application.config.update(
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    )
    migration_db = SQLAlchemy()
    migration = Migrate()
    migration_db.init_app(application)
    migration.init_app(
        application,
        migration_db,
        directory=MIGRATIONS_DIRECTORY,
    )
    with application.app_context():
        try:
            config = migration.get_config(MIGRATIONS_DIRECTORY)
            config.attributes["programmatic_provisioning"] = True
            command.upgrade(config, revision)
        finally:
            migration_db.session.remove()
            migration_db.engine.dispose()


def _downgrade(database_url, revision):
    application = Flask("saas_lite_business_downgrade_test")
    application.config.update(
        SQLALCHEMY_DATABASE_URI=database_url,
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True},
    )
    migration_db = SQLAlchemy()
    migration = Migrate()
    migration_db.init_app(application)
    migration.init_app(
        application,
        migration_db,
        directory=MIGRATIONS_DIRECTORY,
    )
    with application.app_context():
        try:
            config = migration.get_config(MIGRATIONS_DIRECTORY)
            config.attributes["programmatic_provisioning"] = True
            command.downgrade(config, revision)
        finally:
            migration_db.session.remove()
            migration_db.engine.dispose()


def _business_api_app(database_url):
    from app import create_app
    from config import TestingConfig

    class BusinessApiConfig(TestingConfig):
        AUTH_BYPASS_FOR_TESTS = True
        SQLALCHEMY_DATABASE_URI = database_url
        SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
        CONTROL_DATABASE_URL = None
        PROVISIONER_DATABASE_URL = None

    return create_app(BusinessApiConfig)


def _dispose_business_api_app(application):
    from app import db

    with application.app_context():
        db.session.remove()
        for engine in db.engines.values():
            engine.dispose()
    finalizer = application.extensions.get("tenant_resource_finalizer")
    if finalizer is not None and finalizer.alive:
        finalizer()


@pytest.fixture(params=DATABASE_ENVIRONMENTS)
def empty_business_database(request):
    database_url = _required_test_url(request.param)
    engine = create_engine(database_url, pool_pre_ping=True)
    verified_safe = False
    try:
        with engine.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT DATABASE()"
            ).scalar_one() == DATABASE_ENVIRONMENTS[request.param]
            _assert_test_only_grants(connection)
        verified_safe = True
        _reset_schema(engine)
        yield database_url, engine
    finally:
        if verified_safe:
            _reset_schema(engine)
        engine.dispose()


def _column_names(inspector, table_name):
    return {column["name"] for column in inspector.get_columns(table_name)}


def _unique_columns(inspector, table_name):
    return {
        tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints(table_name)
    }


def _foreign_keys(inspector, table_name):
    return {
        (
            tuple(constraint["constrained_columns"]),
            constraint["referred_table"],
            tuple(constraint["referred_columns"]),
            (constraint.get("options") or {}).get("ondelete"),
        )
        for constraint in inspector.get_foreign_keys(table_name)
    }


def _assert_restrictive_fk(inspector, table_name, column, referred_table):
    matches = {
        ondelete
        for columns, table, referred_columns, ondelete in _foreign_keys(
            inspector, table_name
        )
        if columns == (column,)
        and table == referred_table
        and referred_columns == ("id",)
    }
    assert matches
    assert matches <= {None, "RESTRICT"}


def _insert_legacy_rows(engine):
    with engine.begin() as connection:
        connection.execute(
            text(
                """
                INSERT INTO devices (
                    id, name, serial_number, model, is_accessory,
                    lifecycle_status, created_at, updated_at
                ) VALUES
                    (101, 'main-device', 'MAIN-101', 'x200u', 0,
                     'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    (102, 'tripod', 'TRIPOD-102', 'tripod', 1,
                     'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
                    (103, 'ordinary-device', 'ORDINARY-103', 'x200u', 0,
                     'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO rentals (
                    id, device_id, start_date, end_date, customer_name,
                    xianyu_order_no, status, parent_rental_id,
                    includes_handle, includes_lens_mount, photo_transfer,
                    lens_combo, created_at, updated_at
                ) VALUES
                    (201, 101, '2026-09-01', '2026-09-03', 'main',
                     'XY-BOUND', 'not_shipped', NULL,
                     0, 0, 0, 'lens_400mm', CURRENT_TIMESTAMP,
                     CURRENT_TIMESTAMP),
                    (202, 102, '2026-09-01', '2026-09-03', 'child',
                     'CHILD-MUST-STAY-UNBOUND', 'not_shipped', 201,
                     0, 0, 0, 'lens_400mm', CURRENT_TIMESTAMP,
                     CURRENT_TIMESTAMP),
                    (203, 103, '2026-10-01', '2026-10-03', 'ordinary',
                     NULL, 'not_shipped', NULL,
                     0, 0, 0, 'lens_400mm', CURRENT_TIMESTAMP,
                     CURRENT_TIMESTAMP)
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO xianyu_order_alerts (
                    id, order_no, state, pay_amount, first_detected_at,
                    last_seen_at, created_at, updated_at
                ) VALUES (
                    301, 'ALERT-SHARED-ORDER', 'pending', 12345,
                    '2026-08-24 08:00:00', '2026-08-24 08:01:00',
                    '2026-08-24 08:00:00', '2026-08-24 08:01:00'
                )
                """
            )
        )
        connection.execute(
            text(
                """
                INSERT INTO xianyu_order_sync_state (
                    id, last_attempt_at, last_success_at, last_error
                ) VALUES (
                    1, '2026-08-24 08:02:00',
                    '2026-08-24 08:01:30', 'legacy sync error'
                )
                """
            )
        )


def test_phase_2_uses_exactly_two_linear_revisions():
    config = AlembicConfig()
    config.set_main_option("script_location", MIGRATIONS_DIRECTORY)
    script = ScriptDirectory.from_config(config)
    revisions = {
        revision.revision: revision for revision in script.walk_revisions()
    }

    assert revisions[EXPAND_REVISION].down_revision == CURRENT_PHASE_1_HEAD
    assert revisions[CONTRACT_REVISION].down_revision == EXPAND_REVISION
    assert script.get_heads() == [CONTRACT_REVISION]
    phase_2_revisions = {
        revision.revision
        for revision in script.walk_revisions(
            CURRENT_PHASE_1_HEAD, CONTRACT_REVISION
        )
    } - {CURRENT_PHASE_1_HEAD}
    assert phase_2_revisions == {EXPAND_REVISION, CONTRACT_REVISION}


def test_fresh_chain_has_only_the_approved_tables_and_columns(
    empty_business_database,
):
    database_url, engine = empty_business_database
    _upgrade(database_url, "head")

    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        assert APPROVED_NEW_TABLES <= tables
        assert _column_names(inspector, "warehouses") == {
            "id", "province", "city", "name", "created_at", "updated_at",
        }
        assert _column_names(inspector, "warehouse_sf_configs") == {
            "warehouse_id", "partner_id", "checkword_ciphertext",
            "monthly_card_ciphertext", "test_mode", "sender_name",
            "sender_phone", "sender_address", "created_at", "updated_at",
        }
        assert _column_names(inspector, "warehouse_kuaimai_configs") == {
            "warehouse_id", "app_id", "app_secret_ciphertext", "printer_sn",
            "created_at", "updated_at",
        }
        assert _column_names(inspector, "xianyu_shops") == {
            "id", "name", "app_key", "app_secret_ciphertext", "is_active",
            "last_success_at", "last_error", "created_at", "updated_at",
        }
        assert connection.execute(
            text("SELECT version_num FROM alembic_version")
        ).scalar_one() == CONTRACT_REVISION


def test_contract_backfills_old_business_rows_and_removes_sync_state(
    empty_business_database,
):
    database_url, engine = empty_business_database
    _upgrade(database_url, CURRENT_PHASE_1_HEAD)
    with engine.connect() as connection:
        old_tables = set(inspect(connection).get_table_names())
    _insert_legacy_rows(engine)

    _upgrade(database_url, "head")

    with engine.connect() as connection:
        inspector = inspect(connection)
        new_tables = set(inspector.get_table_names())
        assert new_tables - old_tables == APPROVED_NEW_TABLES
        assert old_tables - new_tables == {"xianyu_order_sync_state"}
        default_warehouse = connection.execute(
            text("SELECT id, province, city, name FROM warehouses")
        ).mappings().one()
        assert dict(default_warehouse) == {
            "id": default_warehouse["id"],
            "province": "待配置",
            "city": "待配置",
            "name": "默认仓库",
        }
        default_shop = connection.execute(
            text(
                "SELECT id, name, app_key, is_active, last_success_at, "
                "last_error FROM xianyu_shops"
            )
        ).mappings().one()
        assert default_shop["name"] == "默认闲鱼店铺"
        assert default_shop["app_key"] == ""
        assert default_shop["is_active"] in (False, 0)
        assert default_shop["last_success_at"] == datetime(
            2026, 8, 24, 8, 1, 30
        )
        assert default_shop["last_error"] == "legacy sync error"

        assert connection.scalar(
            text("SELECT count(*) FROM devices WHERE warehouse_id IS NULL")
        ) == 0
        assert connection.scalar(
            text("SELECT count(*) FROM rentals WHERE warehouse_id IS NULL")
        ) == 0
        assert connection.scalar(
            text(
                "SELECT count(*) FROM rentals WHERE warehouse_id != :id"
            ),
            {"id": default_warehouse["id"]},
        ) == 0
        assert connection.scalar(
            text(
                "SELECT count(*) FROM xianyu_order_alerts "
                "WHERE xianyu_shop_id != :id OR xianyu_shop_id IS NULL"
            ),
            {"id": default_shop["id"]},
        ) == 0
        rental_shops = dict(
            connection.execute(
                text("SELECT id, xianyu_shop_id FROM rentals ORDER BY id")
            ).all()
        )
        assert rental_shops == {
            201: default_shop["id"],
            202: None,
            203: None,
        }


def test_contract_enforces_foreign_keys_not_null_and_shop_uniqueness(
    empty_business_database,
):
    database_url, engine = empty_business_database
    _upgrade(database_url, CURRENT_PHASE_1_HEAD)
    _insert_legacy_rows(engine)
    _upgrade(database_url, "head")

    with engine.connect() as connection:
        inspector = inspect(connection)
        nullable_columns = {
            table_name: {
                column["name"]: column["nullable"]
                for column in inspector.get_columns(table_name)
            }
            for table_name in (
                "devices", "rentals", "xianyu_order_alerts"
            )
        }
        assert nullable_columns["devices"]["warehouse_id"] is False
        assert nullable_columns["rentals"]["warehouse_id"] is False
        assert nullable_columns["rentals"]["xianyu_shop_id"] is True
        assert nullable_columns["xianyu_order_alerts"][
            "xianyu_shop_id"
        ] is False
        _assert_restrictive_fk(
            inspector, "devices", "warehouse_id", "warehouses"
        )
        _assert_restrictive_fk(
            inspector, "rentals", "warehouse_id", "warehouses"
        )
        _assert_restrictive_fk(
            inspector, "rentals", "xianyu_shop_id", "xianyu_shops"
        )
        _assert_restrictive_fk(
            inspector,
            "xianyu_order_alerts",
            "xianyu_shop_id",
            "xianyu_shops",
        )
        assert ("xianyu_shop_id", "order_no") in _unique_columns(
            inspector, "xianyu_order_alerts"
        )
        assert ("xianyu_shop_id", "xianyu_order_no") in _unique_columns(
            inspector, "rentals"
        )
        assert ("order_no",) not in _unique_columns(
            inspector, "xianyu_order_alerts"
        )
        assert any(
            index["column_names"] == ["order_no"] and not index["unique"]
            for index in inspector.get_indexes("xianyu_order_alerts")
        )

        warehouse_id = connection.scalar(text("SELECT id FROM warehouses"))
        default_shop_id = connection.scalar(
            text("SELECT id FROM xianyu_shops")
        )

    with engine.begin() as connection:
        second_shop_id = connection.execute(
            text(
                """
                INSERT INTO xianyu_shops (
                    name, app_key, is_active, created_at, updated_at
                ) VALUES (
                    'second shop', 'second-app', 1,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                ) RETURNING id
                """
            )
        ).scalar_one()
        connection.execute(
            text(
                """
                INSERT INTO xianyu_order_alerts (
                    order_no, xianyu_shop_id, state, pay_amount,
                    first_detected_at, last_seen_at, created_at, updated_at
                ) VALUES (
                    'ALERT-SHARED-ORDER', :shop_id, 'pending', 54321,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {"shop_id": second_shop_id},
        )
        connection.execute(
            text(
                """
                INSERT INTO rentals (
                    device_id, warehouse_id, xianyu_shop_id,
                    xianyu_order_no, start_date, end_date, customer_name,
                    status, includes_handle, includes_lens_mount,
                    photo_transfer, lens_combo, created_at, updated_at
                ) VALUES (
                    103, :warehouse_id, :shop_id, 'XY-BOUND',
                    '2026-11-01', '2026-11-03', 'second-shop-order',
                    'not_shipped', 0, 0, 0, 'lens_400mm',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            ),
            {"warehouse_id": warehouse_id, "shop_id": second_shop_id},
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO xianyu_order_alerts (
                        order_no, xianyu_shop_id, state, pay_amount,
                        first_detected_at, last_seen_at,
                        created_at, updated_at
                    ) VALUES (
                        'ALERT-SHARED-ORDER', :shop_id, 'pending', 1,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP,
                        CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                    )
                    """
                ),
                {"shop_id": default_shop_id},
            )


def test_downgrade_preserves_the_documented_expand_contract_boundary(
    empty_business_database,
):
    database_url, engine = empty_business_database
    _upgrade(database_url, CURRENT_PHASE_1_HEAD)
    _insert_legacy_rows(engine)
    _upgrade(database_url, "head")

    _downgrade(database_url, EXPAND_REVISION)

    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        assert APPROVED_NEW_TABLES <= tables
        assert "xianyu_order_sync_state" in tables
        assert _column_names(inspector, "devices") >= {"warehouse_id"}
        assert _column_names(inspector, "rentals") >= {
            "warehouse_id", "xianyu_shop_id",
        }
        assert _column_names(inspector, "xianyu_order_alerts") >= {
            "xianyu_shop_id",
        }
        assert ("xianyu_shop_id", "order_no") not in _unique_columns(
            inspector, "xianyu_order_alerts"
        )
        assert ("xianyu_shop_id", "xianyu_order_no") not in (
            _unique_columns(inspector, "rentals")
        )
        assert connection.execute(
            text("SELECT last_success_at, last_error "
                 "FROM xianyu_order_sync_state WHERE id = 1")
        ).one() == (
            datetime(2026, 8, 24, 8, 1, 30),
            "legacy sync error",
        )

    _downgrade(database_url, CURRENT_PHASE_1_HEAD)

    with engine.connect() as connection:
        inspector = inspect(connection)
        tables = set(inspector.get_table_names())
        assert not tables & APPROVED_NEW_TABLES
        assert "xianyu_order_sync_state" in tables
        assert "warehouse_id" not in _column_names(inspector, "devices")
        assert not {
            "warehouse_id", "xianyu_shop_id",
        } & _column_names(inspector, "rentals")
        assert "xianyu_shop_id" not in _column_names(
            inspector, "xianyu_order_alerts"
        )
        assert ("order_no",) in _unique_columns(
            inspector, "xianyu_order_alerts"
        ) or any(
            index["column_names"] == ["order_no"] and index["unique"]
            for index in inspector.get_indexes("xianyu_order_alerts")
        )
        assert connection.scalar(
            text("SELECT version_num FROM alembic_version")
        ) == CURRENT_PHASE_1_HEAD


def test_model_serializers_never_expose_secret_material():
    from app.models.warehouse import (
        Warehouse,
        WarehouseKuaimaiConfig,
        WarehouseSFConfig,
    )
    from app.models.xianyu_shop import XianyuShop

    warehouse = Warehouse(
        id=1,
        province="广东省",
        city="深圳市",
        name="深圳仓库",
        created_at=datetime(2026, 8, 25, 1, 0, 0),
        updated_at=datetime(2026, 8, 25, 1, 0, 0),
    )
    warehouse.sf_config = WarehouseSFConfig(
        partner_id="partner",
        checkword_ciphertext="CHECKWORD-CIPHERTEXT",
        monthly_card_ciphertext="MONTHLY-CARD-CIPHERTEXT",
        test_mode=True,
        sender_name="寄件人",
        sender_phone="13800138000",
        sender_address="详细地址",
    )
    warehouse.kuaimai_config = WarehouseKuaimaiConfig(
        app_id="app-id",
        app_secret_ciphertext="KUAI-MAI-CIPHERTEXT",
        printer_sn="printer-sn",
    )
    shop = XianyuShop(
        id=2,
        name="店铺",
        app_key="public-app-key",
        app_secret_ciphertext="XIANYU-CIPHERTEXT",
        is_active=True,
    )

    payloads = [
        warehouse.to_dict(),
        warehouse.sf_config.to_dict(),
        warehouse.kuaimai_config.to_dict(),
        shop.to_dict(),
    ]
    serialized = repr(payloads)
    assert "CHECKWORD-CIPHERTEXT" not in serialized
    assert "MONTHLY-CARD-CIPHERTEXT" not in serialized
    assert "KUAI-MAI-CIPHERTEXT" not in serialized
    assert "XIANYU-CIPHERTEXT" not in serialized
    assert not any(
        "ciphertext" in key
        or key in {"app_secret", "checkword", "monthly_card"}
        for payload in payloads
        for key in payload
    )
    assert warehouse.to_dict()["sf_configured"] is True
    assert warehouse.to_dict()["kuaimai_configured"] is True
    assert warehouse.sf_config.to_dict()["checkword_configured"] is True
    assert warehouse.sf_config.to_dict()["monthly_card_configured"] is True
    assert warehouse.kuaimai_config.to_dict()["app_secret_configured"] is True
    assert shop.to_dict()["app_secret_configured"] is True


def test_head_public_create_apis_resolve_and_persist_warehouses(
    empty_business_database,
):
    database_url, engine = empty_business_database
    _upgrade(database_url, "head")
    application = _business_api_app(database_url)
    client = application.test_client()
    try:
        with engine.begin() as connection:
            connection.execute(text("DELETE FROM warehouses"))

        no_warehouse = client.post(
            "/api/devices",
            json={"name": "无仓设备", "serial_number": "NO-WAREHOUSE"},
        )
        assert no_warehouse.status_code == 400
        assert no_warehouse.get_json() == {
            "success": False,
            "message": "请指定仓库",
        }

        with engine.begin() as connection:
            default_warehouse_id = connection.execute(
                text(
                    "INSERT INTO warehouses "
                    "(province, city, name, created_at, updated_at) VALUES "
                    "('待配置', '待配置', '默认仓库', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id"
                )
            ).scalar_one()

        main_response = client.post(
            "/api/devices",
            json={"name": "主设备", "serial_number": "MAIN-PUBLIC"},
        )
        accessory_response = client.post(
            "/api/devices",
            json={
                "name": "三脚架",
                "serial_number": "TRIPOD-PUBLIC",
                "is_accessory": True,
            },
        )
        assert main_response.status_code == 201
        assert accessory_response.status_code == 201
        assert main_response.get_json()["data"]["warehouse_id"] == (
            default_warehouse_id
        )
        assert accessory_response.get_json()["data"]["warehouse_id"] == (
            default_warehouse_id
        )

        rental_response = client.post(
            "/api/rentals",
            json={
                "device_id": main_response.get_json()["data"]["id"],
                "accessories": [
                    accessory_response.get_json()["data"]["id"]
                ],
                "customer_name": "测试客户",
                "start_date": "2026-09-01",
                "end_date": "2026-09-03",
            },
        )
        assert rental_response.status_code == 201
        created = rental_response.get_json()["data"]
        assert created["main_rental"]["warehouse_id"] == (
            default_warehouse_id
        )
        assert {
            row["warehouse_id"] for row in created["accessory_rentals"]
        } == {default_warehouse_id}

        with engine.begin() as connection:
            second_warehouse_id = connection.execute(
                text(
                    "INSERT INTO warehouses "
                    "(province, city, name, created_at, updated_at) VALUES "
                    "('广东省', '广州市', '广州仓库', "
                    "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP) RETURNING id"
                )
            ).scalar_one()
            rental_count = connection.scalar(
                text("SELECT count(*) FROM rentals")
            )

        missing_warehouse = client.post(
            "/api/devices",
            json={"name": "多仓设备", "serial_number": "MULTI-MISSING"},
        )
        invalid_warehouse = client.post(
            "/api/devices",
            json={
                "name": "无效仓设备",
                "serial_number": "INVALID-WAREHOUSE",
                "warehouse_id": 999999,
            },
        )
        assert missing_warehouse.status_code == 400
        assert missing_warehouse.get_json()["message"] == "请指定仓库"
        assert invalid_warehouse.status_code == 400
        assert invalid_warehouse.get_json()["message"] == "仓库不存在"

        second_device = client.post(
            "/api/devices",
            json={
                "name": "广州设备",
                "serial_number": "GUANGZHOU-DEVICE",
                "warehouse_id": second_warehouse_id,
            },
        )
        assert second_device.status_code == 201

        missing_rental_warehouse = client.post(
            "/api/rentals",
            json={
                "device_id": second_device.get_json()["data"]["id"],
                "customer_name": "多仓缺失",
                "start_date": "2026-10-01",
                "end_date": "2026-10-03",
            },
        )
        mismatched_rental_warehouse = client.post(
            "/api/rentals",
            json={
                "device_id": second_device.get_json()["data"]["id"],
                "warehouse_id": default_warehouse_id,
                "customer_name": "仓库不匹配",
                "start_date": "2026-10-01",
                "end_date": "2026-10-03",
            },
        )
        assert missing_rental_warehouse.status_code == 400
        assert missing_rental_warehouse.get_json()["message"] == "请指定仓库"
        assert mismatched_rental_warehouse.status_code == 400
        assert mismatched_rental_warehouse.get_json()["message"] == (
            "主设备不属于所选仓库"
        )
        with engine.connect() as connection:
            assert connection.scalar(
                text("SELECT count(*) FROM rentals")
            ) == rental_count
    finally:
        _dispose_business_api_app(application)


def test_head_xianyu_alert_endpoint_reads_shop_sync_state(
    empty_business_database,
):
    database_url, _engine = empty_business_database
    _upgrade(database_url, "head")
    application = _business_api_app(database_url)
    try:
        response = application.test_client().get("/api/xianyu-order-alerts")

        assert response.status_code == 200
        assert response.get_json()["data"]["sync"] == {
            "last_attempt_at": None,
            "last_success_at": None,
            "last_error": None,
        }
    finally:
        _dispose_business_api_app(application)
