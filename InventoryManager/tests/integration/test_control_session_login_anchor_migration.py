from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return config


def test_session_login_anchor_upgrade_and_downgrade(
    mysql_control_migration_url,
) -> None:
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)
    command.upgrade(config, "202608220023")

    command.upgrade(config, "202608220024")
    engine = sa.create_engine(database_url)
    try:
        inspector = sa.inspect(engine)
        columns = {
            column["name"]
            for column in inspector.get_columns("tenant_user_sessions")
        }
        unique_sets = {
            tuple(item["column_names"])
            for item in inspector.get_unique_constraints(
                "tenant_user_sessions"
            )
        }
        foreign_sets = {
            tuple(item["constrained_columns"])
            for item in inspector.get_foreign_keys("tenant_user_sessions")
        }
        expected = {
            "created_from_challenge_id",
            "rotated_from_session_id",
            "replaced_by_session_id",
        }
        assert expected <= columns
        assert {(name,) for name in expected} <= unique_sets
        assert {(name,) for name in expected} <= foreign_sets
    finally:
        engine.dispose()

    command.downgrade(config, "202608220023")
    engine = sa.create_engine(database_url)
    try:
        columns = {
            column["name"]
            for column in sa.inspect(engine).get_columns(
                "tenant_user_sessions"
            )
        }
        assert "created_from_challenge_id" not in columns
        assert "rotated_from_session_id" not in columns
        assert "replaced_by_session_id" not in columns
    finally:
        engine.dispose()
