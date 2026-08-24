from __future__ import annotations

from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from app import db
from tests.support.tenant_migration import (
    build_tenant_saas_segment_baseline,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TENANT_MIGRATIONS = PROJECT_ROOT / "migrations"
TENANT_BASELINE = "20260807_damage_notes"
TENANT_HEAD = "20260823_shipping_contract"


def test_tenant_saas_segment_forward_apply_on_single_test_database(
    mysql_tenant_migration_url,
):
    engine = sa.create_engine(mysql_tenant_migration_url)
    try:
        build_tenant_saas_segment_baseline(
            engine,
            script_location=TENANT_MIGRATIONS,
            target_metadata=db.metadata,
            schema_head=TENANT_HEAD,
            baseline_revision=TENANT_BASELINE,
        )
        with engine.connect() as connection:
            config = Config(str(TENANT_MIGRATIONS / "alembic.ini"))
            config.set_main_option("script_location", str(TENANT_MIGRATIONS))
            config.attributes["connection"] = connection
            config.attributes["target_metadata"] = db.metadata
            assert MigrationContext.configure(connection).get_current_revision() == (
                TENANT_BASELINE
            )
            command.upgrade(config, TENANT_HEAD)
            connection.commit()
            assert connection.execute(
                sa.text("SELECT version_num FROM alembic_version")
            ).scalar_one() == TENANT_HEAD
            assert compare_metadata(
                MigrationContext.configure(connection),
                db.metadata,
            ) == []
            inspector = sa.inspect(connection)
            assert _foreign_key_names(inspector, "devices") >= {
                "fk_devices_warehouse_id_warehouses"
            }
            assert _foreign_key_names(inspector, "inspection_record") >= {
                "fk_inspection_record_warehouse_id_warehouses"
            }
            assert _foreign_key_names(inspector, "rentals") >= {
                "fk_rentals_preferred_warehouse_id_warehouses",
                "fk_rentals_estimate_origin_warehouse_id_warehouses",
            }
    finally:
        engine.dispose()


def _foreign_key_names(inspector, table_name: str) -> set[str]:
    return {
        value["name"]
        for value in inspector.get_foreign_keys(table_name)
        if isinstance(value.get("name"), str)
    }
