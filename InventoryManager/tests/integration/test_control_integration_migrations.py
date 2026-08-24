from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from inventory_control.models import ControlBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_tenant_integration_migration_round_trip_matches_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)
    integration_tables = {
        "tenant_integrations",
        "tenant_integration_secret_revisions",
        "tenant_integration_secret_envelope_events",
        "tenant_provider_defaults",
    }

    command.upgrade(config, "202608220006")
    engine = sa.create_engine(database_url)
    try:
        assert integration_tables.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220007")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        assert integration_tables <= set(inspector.get_table_names())
        revision_columns = {
            column["name"]
            for column in inspector.get_columns(
                "tenant_integration_secret_revisions"
            )
        }
        assert {
            "crypto_context_uuid",
            "canonical_semantics_digest",
            "credentials_ciphertext",
            "credentials_nonce",
            "envelope_generation",
            "envelope_row_version",
            "current_integration_id",
            "verification_status",
            "verification_result_digest",
        } <= revision_columns
        with engine.connect() as connection:
            def include_integration_objects(
                object_, name, type_, reflected, compare_to
            ):
                if type_ == "table":
                    return name in integration_tables
                table = getattr(object_, "table", None)
                return table is None or table.name in integration_tables

            context = MigrationContext.configure(
                connection,
                opts={"include_object": include_integration_objects},
            )
            assert compare_metadata(context, ControlBase.metadata) == []
    finally:
        engine.dispose()

    command.downgrade(config, "202608220006")
    engine = sa.create_engine(database_url)
    try:
        assert integration_tables.isdisjoint(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()

    command.upgrade(config, "202608220007")
    engine = sa.create_engine(database_url)
    try:
        assert integration_tables <= set(sa.inspect(engine).get_table_names())
    finally:
        engine.dispose()
