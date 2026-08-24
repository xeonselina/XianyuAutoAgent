from io import StringIO
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.config import Config


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"


def config_for(database_url: str) -> Config:
    value = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    value.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    value.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    return value


def test_invitation_migration_roundtrip(mysql_control_migration_url):
    url = mysql_control_migration_url
    config = config_for(url)

    command.upgrade(config, "202608220007")
    engine = sa.create_engine(url)
    try:
        assert "tenant_invitations" not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "202608220008")
    engine = sa.create_engine(url)
    try:
        inspector = sa.inspect(engine)
        assert "tenant_invitations" in inspector.get_table_names()
        assert {index["name"] for index in inspector.get_indexes("tenant_invitations")} >= {
            "ix_tenant_invitations_user_status_expiry",
            "ix_tenant_invitations_tenant_status_expiry",
        }
    finally:
        engine.dispose()

    command.downgrade(config, "202608220007")
    engine = sa.create_engine(url)
    try:
        assert "tenant_invitations" not in sa.inspect(engine).get_table_names()
    finally:
        engine.dispose()

    command.upgrade(config, "202608220008")


def test_invitation_hash_length_fix_emits_mysql_varbinary():
    output = StringIO()
    config = config_for(
        "mysql+pymysql://unused:unused@localhost/control"
    )
    config.output_buffer = output

    command.upgrade(
        config,
        "202608230030:202608230031",
        sql=True,
    )
    ddl = output.getvalue().upper()

    assert "ALTER TABLE TENANT_INVITATIONS" in ddl
    assert "VARBINARY(32)" in ddl
