from __future__ import annotations

from io import StringIO
import logging
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from app import create_app
from config import TestingConfig


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TENANT_MIGRATIONS = PROJECT_ROOT / "migrations"
LEGACY_SAAS_BASE = "20260807_damage_notes"
TENANT_SAAS_HEAD = "20260823_shipping_contract"


def _config() -> Config:
    config = Config(str(TENANT_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(TENANT_MIGRATIONS))
    return config


def test_tenant_saas_migrations_have_one_ordered_head():
    script = ScriptDirectory.from_config(_config())

    assert script.get_heads() == [TENANT_SAAS_HEAD]
    revisions = {
        revision.revision: revision.down_revision
        for revision in script.walk_revisions(
            base=LEGACY_SAAS_BASE,
            head=TENANT_SAAS_HEAD,
        )
        if revision.revision != LEGACY_SAAS_BASE
    }
    assert revisions == {
        "20260822_db_identity": LEGACY_SAAS_BASE,
        "20260822_warehouses": "20260822_db_identity",
        "20260822_accessories": "20260822_warehouses",
        "20260822_rental_logistics": "20260822_accessories",
        "20260822_inspection_warehouse": "20260822_rental_logistics",
        "20260822_shipping_ledgers": "20260822_inspection_warehouse",
        "20260823_xianyu_sync_state": "20260822_shipping_ledgers",
        "20260823_shipping_intent": "20260823_xianyu_sync_state",
        TENANT_SAAS_HEAD: "20260823_shipping_intent",
    }


def test_tenant_saas_segment_emits_mysql8_offline_ddl(monkeypatch):
    """Compile every new tenant migration without opening a database socket."""

    host_logger = logging.getLogger("tests.migration_host_runtime")
    host_logger.disabled = False
    monkeypatch.setattr(
        TestingConfig,
        "SQLALCHEMY_DATABASE_URI",
        "mysql+pymysql://offline:offline@127.0.0.1/tenant_offline",
    )
    application = create_app("testing")
    output = StringIO()

    with application.app_context():
        assert application.extensions["migrate"].db.engine.dialect.name == "mysql"
        config = _config()
        config.output_buffer = output
        command.upgrade(
            config,
            f"{LEGACY_SAAS_BASE}:{TENANT_SAAS_HEAD}",
            sql=True,
        )

    # An in-process Alembic run must configure only its own loggers.  Disabling
    # host loggers contaminates every test or worker action executed afterward.
    assert host_logger.disabled is False

    ddl = output.getvalue()
    lower_ddl = ddl.lower()
    for required in (
        "CREATE TABLE database_identity",
        "CREATE TABLE warehouses",
        "CREATE TABLE accessory_types",
        "CREATE TABLE accessory_units",
        "CREATE TABLE rental_accessory_requests",
        "CREATE TABLE rental_accessory_unit_links",
        "CREATE TABLE accessory_unit_events",
        "CREATE TABLE outbound_shipments",
        "CREATE TABLE provider_operation_attempts",
        "CREATE TABLE waybill_print_jobs",
        "CREATE TABLE xianyu_connection_sync_states",
        "ALTER TABLE devices ADD COLUMN warehouse_id",
        "ALTER TABLE rentals ADD COLUMN logistics_days",
        "ALTER TABLE inspection_record ADD COLUMN warehouse_id",
        "ALTER TABLE xianyu_order_alerts ADD COLUMN integration_uuid",
        "ALTER TABLE xianyu_order_sync_state ADD COLUMN snapshot_revision",
        "ALTER TABLE provider_operation_attempts ADD COLUMN tenant_access_version",
        "ALTER TABLE provider_operation_attempts ADD COLUMN requested_by_user_uuid",
        "ALTER TABLE provider_operation_attempts ADD COLUMN job_enqueued_at",
        "ALTER TABLE outbound_shipments ADD COLUMN cargo_snapshot",
        "ALTER TABLE outbound_shipments ADD COLUMN scheduled_dispatch_at",
    ):
        assert required in ddl

    assert ddl.count("CREATE TABLE accessory_types") == 1
    assert f"version_num='{TENANT_SAAS_HEAD}'" in ddl
    assert "DROP TABLE" not in ddl
    assert "DROP COLUMN" not in ddl
    assert all(len(name) <= 64 for name in _constraint_names(ddl))
    for forbidden in (
        "secret_key",
        "api_key",
        "password",
        "plaintext",
        "database_url",
    ):
        assert forbidden not in lower_ddl


def _constraint_names(ddl: str) -> tuple[str, ...]:
    names: list[str] = []
    words = ddl.replace("\n", " ").replace("`", "").split()
    for index, word in enumerate(words[:-1]):
        if word.upper() == "CONSTRAINT":
            names.append(words[index + 1])
    return tuple(names)
