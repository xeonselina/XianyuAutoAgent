"""MariaDB coverage for adopting the legacy database as one tenant."""

import json

import pytest
from sqlalchemy import create_engine, inspect, select, text

from app.control.models import Tenant, TenantMember
from app.models.warehouse import WarehouseKuaimaiConfig, WarehouseSFConfig
from app.models.xianyu_shop import XianyuShop
from app.services.settings_service import (
    KUAIMAI_SECRET_PURPOSE,
    SF_CHECKWORD_PURPOSE,
    SF_MONTHLY_CARD_PURPOSE,
    XIANYU_SECRET_PURPOSE,
)
from tests.integration.test_platform_provisioning import (
    _run_migration_revision,
    _tenant_engine,
    _tenant_snapshot,
    platform_environment,
)
from tests.integration.test_saas_lite_business_migrations import (
    _insert_legacy_rows,
)


BACKUP_HEAD = "20260807_damage_notes"
CURRENT_HEAD = "20260824_saas_lite_contract"
TARGET = "tenant_a_saas_test"
PHONE = "+8613800138000"
SECRET_VALUES = {
    "SF_PARTNER_ID": "sf-partner-private",
    "SF_CHECKWORD": "sf-checkword-private",
    "SF_MONTHLY_CARD": "sf-card-private",
    "SF_SENDER_NAME": "private-sender",
    "SF_SENDER_PHONE": "13900139000",
    "SF_SENDER_ADDRESS": "private-address",
    "SF_TEST_MODE": "true",
    "KUAIMAI_APP_ID": "kuaimai-app-private",
    "KUAIMAI_APP_SECRET": "kuaimai-secret-private",
    "KUAIMAI_PRINTER_SN": "printer-private",
    "XIANYU_APP_KEY": "xianyu-key-private",
    "XIANYU_APP_SECRET": "xianyu-secret-private",
}


@pytest.fixture
def legacy_environment(platform_environment):
    url = platform_environment["urls"]["TEST_TENANT_DATABASE_URL_A"]
    rendered = url.render_as_string(hide_password=False)
    _run_migration_revision(rendered, BACKUP_HEAD)
    engine = create_engine(url, pool_pre_ping=True)
    _insert_legacy_rows(engine)
    try:
        yield platform_environment, engine
    finally:
        engine.dispose()


def _invoke(environment, *extra):
    return environment["app"].test_cli_runner().invoke(args=[
        "migrate-default-tenant",
        "--name", "Legacy tenant",
        "--admin-phone", PHONE,
        "--expires-at", "2030-01-01T08:00:00+08:00",
        "--db-name", TARGET,
        "--province", "广东省",
        "--city", "深圳市",
        *extra,
    ])


def _control_rows(environment):
    store = environment["app"].extensions["control_store"]
    with store.session() as session:
        tenants = session.scalars(select(Tenant)).all()
        members = session.scalars(select(TenantMember)).all()
    return store, tenants, members


def test_cli_adopts_existing_database_preserves_rows_and_is_idempotent(
    legacy_environment, monkeypatch,
):
    environment, root_business_engine = legacy_environment
    for key, value in SECRET_VALUES.items():
        monkeypatch.setenv(key, value)

    with root_business_engine.connect() as connection:
        before = {
            name: connection.scalar(text(f"SELECT count(*) FROM `{name}`"))
            for name in inspect(connection).get_table_names()
            if name not in {"alembic_version", "xianyu_order_sync_state"}
        }
    first = _invoke(environment)
    assert first.exit_code == 0, first.output
    report = json.loads(first.output)
    serialized = first.output + repr(report)
    assert not any(
        value in serialized for key, value in SECRET_VALUES.items()
        if key != "SF_TEST_MODE"
    )
    assert report["target"] == TARGET
    assert report["head"] == CURRENT_HEAD
    assert set(report["before_counts"]) - set(report["after_counts"]) == {
        "xianyu_order_sync_state"
    }
    assert all(
        report["after_counts"][name] == count
        for name, count in report["before_counts"].items()
        if name != "xianyu_order_sync_state"
    )
    assert report["issue_counts"] == {
        "blank_alert_orders": 0,
        "duplicate_main_orders": 0,
        "null_alert_shops": 0,
        "null_device_warehouses": 0,
        "null_rental_warehouses": 0,
        "orphan_parent_rentals": 0,
        "orphan_rental_devices": 0,
        "parent_child_warehouse_mismatches": 0,
    }
    assert report["sf_config_complete"] is True
    assert report["kuaimai_config_complete"] is True
    assert report["xianyu_config_complete"] is True

    store, tenants, members = _control_rows(environment)
    assert len(tenants) == len(members) == 1
    tenant = tenants[0]
    assert tenant.provisioning_status == "active"
    assert tenant.db_name == TARGET
    assert members[0].phone == PHONE
    snapshot = _tenant_snapshot(store, tenant.id)
    tenant_engine = _tenant_engine(environment, snapshot)
    try:
        with tenant_engine.connect() as connection:
            assert connection.scalar(text("SELECT version_num FROM alembic_version")) == CURRENT_HEAD
            assert {
                name: connection.scalar(text(f"SELECT count(*) FROM `{name}`"))
                for name in before
            } == before
            warehouse = connection.execute(text(
                "SELECT id, province, city, name FROM warehouses"
            )).mappings().one()
            assert tuple(warehouse.values()) == (
                report["warehouse_id"], "广东省", "深圳市", "广东省深圳市仓库"
            )
            assert connection.scalar(text(
                "SELECT count(*) FROM devices WHERE warehouse_id != :id"
            ), {"id": warehouse["id"]}) == 0
            assert connection.scalar(text(
                "SELECT count(*) FROM rentals WHERE warehouse_id != :id"
            ), {"id": warehouse["id"]}) == 0
            shop = connection.execute(text(
                "SELECT id, is_active, last_success_at, last_error FROM xianyu_shops"
            )).mappings().one()
            assert shop["id"] == report["shop_id"]
            assert shop["is_active"] in (1, True)
            assert shop["last_success_at"] is not None
            assert shop["last_error"] == "legacy sync error"
            assert connection.scalar(text(
                "SELECT count(*) FROM xianyu_order_alerts WHERE xianyu_shop_id != :id"
            ), {"id": shop["id"]}) == 0
            grants = [value.replace("\\_", "_").replace("\\%", "%") for value in
                      connection.exec_driver_sql("SHOW GRANTS FOR CURRENT_USER").scalars()]
            assert len(grants) == 2
            assert sum(f"ON `{TARGET}`.*" in value for value in grants) == 1
            assert all("GRANT OPTION" not in value for value in grants)

        with environment["app"].app_context():
            from app.tenant_context import bind_tenant, reset_tenant
            from app import db

            token = bind_tenant(tenant.id, tenant_engine)
            try:
                sf = db.session.get(WarehouseSFConfig, report["warehouse_id"])
                kuaimai = db.session.get(WarehouseKuaimaiConfig, report["warehouse_id"])
                shop = db.session.get(XianyuShop, report["shop_id"])
                assert store.secret_box.decrypt(sf.checkword_ciphertext, purpose=SF_CHECKWORD_PURPOSE) == SECRET_VALUES["SF_CHECKWORD"]
                assert store.secret_box.decrypt(sf.monthly_card_ciphertext, purpose=SF_MONTHLY_CARD_PURPOSE) == SECRET_VALUES["SF_MONTHLY_CARD"]
                assert store.secret_box.decrypt(kuaimai.app_secret_ciphertext, purpose=KUAIMAI_SECRET_PURPOSE) == SECRET_VALUES["KUAIMAI_APP_SECRET"]
                assert store.secret_box.decrypt(shop.app_secret_ciphertext, purpose=XIANYU_SECRET_PURPOSE) == SECRET_VALUES["XIANYU_APP_SECRET"]
            finally:
                db.session.remove()
                reset_tenant(token)
    finally:
        tenant_engine.dispose()

    second = _invoke(environment, "--name", "Updated tenant")
    assert second.exit_code == 0, second.output
    second_report = json.loads(second.output)
    assert (second_report["tenant_id"], second_report["warehouse_id"], second_report["shop_id"]) == (
        report["tenant_id"], report["warehouse_id"], report["shop_id"]
    )
    _store, tenants, members = _control_rows(environment)
    assert len(tenants) == len(members) == 1


@pytest.mark.parametrize("mutation, issue", [
    ("UPDATE rentals SET device_id=999999 WHERE id=201", "orphan_rental_devices"),
    ("UPDATE rentals SET parent_rental_id=999999 WHERE id=202", "orphan_parent_rentals"),
    ("UPDATE xianyu_order_alerts SET order_no='' WHERE id=301", "blank_alert_orders"),
    ("UPDATE rentals SET xianyu_order_no='XY-BOUND' WHERE id=203", "duplicate_main_orders"),
])
def test_preflight_rejects_health_issues_before_control_mutation(
    legacy_environment, mutation, issue,
):
    environment, engine = legacy_environment
    with engine.begin() as connection:
        connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=0")
        connection.exec_driver_sql(mutation)
        connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS=1")

    result = _invoke(environment)
    assert result.exit_code != 0
    assert issue in result.output
    _store, tenants, members = _control_rows(environment)
    assert tenants == members == []


@pytest.mark.parametrize("extra", [
    ("--db-name", "unsafe"),
    ("--db-name", "bad-test;drop"),
    ("--db-name", "inventory_management"),
    ("--db-name", "inventory_management", "--confirm-maintenance", "maintenance-enabled"),
])
def test_cli_rejects_unsafe_or_unconfirmed_targets(platform_environment, extra):
    result = _invoke(platform_environment, *extra)
    assert result.exit_code != 0
    _store, tenants, members = _control_rows(platform_environment)
    assert tenants == members == []


def test_post_control_failure_is_redacted_failed_and_retryable(
    legacy_environment, monkeypatch,
):
    environment, _engine = legacy_environment
    provisioner = environment["app"].extensions["tenant_provisioner"]
    real_adopt = provisioner.adopt_existing

    def fail(_tenant):
        raise RuntimeError("private-dsn-and-phone-13800138000")

    monkeypatch.setattr(provisioner, "adopt_existing", fail)
    failed = _invoke(environment)
    assert failed.exit_code != 0
    assert "private-dsn" not in failed.output
    _store, tenants, members = _control_rows(environment)
    assert len(tenants) == len(members) == 1
    assert tenants[0].provisioning_status == "failed"
    assert tenants[0].provisioning_error == "Default tenant migration failed."
    tenant_id = tenants[0].id

    monkeypatch.setattr(provisioner, "adopt_existing", real_adopt)
    retry = _invoke(environment)
    assert retry.exit_code == 0, retry.output
    report = json.loads(retry.output)
    assert report["tenant_id"] == tenant_id
    assert report["sf_config_complete"] is False
    assert report["kuaimai_config_complete"] is False
    assert report["xianyu_config_complete"] is False
    _store, tenants, members = _control_rows(environment)
    assert len(tenants) == len(members) == 1
    assert tenants[0].provisioning_status == "active"
