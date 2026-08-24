from io import StringIO
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


def test_job_migration_round_trip_matches_control_metadata(
    mysql_control_migration_url,
):
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)

    command.upgrade(config, "202608220001")
    engine = sa.create_engine(database_url)
    try:
        foundation_tables = set(sa.inspect(engine).get_table_names())
        assert "background_jobs" not in foundation_tables
        assert "control_outbox_events" not in foundation_tables
    finally:
        engine.dispose()

    command.upgrade(config, "202608220002")
    engine = sa.create_engine(database_url)
    try:
        tables = set(sa.inspect(engine).get_table_names())
        assert {"background_jobs", "control_outbox_events"} <= tables
        inspector = sa.inspect(engine)
        assert {
            constraint["name"]
            for constraint in inspector.get_unique_constraints("background_jobs")
        } >= {"uq_background_jobs_effective_idempotency"}
        assert {
            index["name"] for index in inspector.get_indexes("background_jobs")
        } >= {"ix_background_jobs_claim", "ix_background_jobs_lease_expiry"}
        assert {
            constraint["name"]
            for constraint in inspector.get_unique_constraints(
                "control_outbox_events"
            )
        } >= {"uq_control_outbox_events_effective_idempotency"}
    finally:
        engine.dispose()

    command.downgrade(config, "202608220001")
    engine = sa.create_engine(database_url)
    try:
        downgraded_tables = set(sa.inspect(engine).get_table_names())
        assert "background_jobs" not in downgraded_tables
        assert "control_outbox_events" not in downgraded_tables
        assert "tenants" in downgraded_tables
    finally:
        engine.dispose()

    command.upgrade(config, "202608220002")
    engine = sa.create_engine(database_url)
    try:
        tables = set(sa.inspect(engine).get_table_names())
        assert {"background_jobs", "control_outbox_events"} <= tables
    finally:
        engine.dispose()


def test_job_migration_emits_mysql8_microsecond_protocol_timestamps():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/inventory_control"
    )
    config.output_buffer = output

    command.upgrade(config, "202608220001:202608220002", sql=True)
    ddl = output.getvalue()

    assert "CREATE TABLE background_jobs" in ddl
    assert "CREATE TABLE control_outbox_events" in ddl
    assert ddl.count("DATETIME(6)") == 17
    for column in (
        "available_at",
        "not_after",
        "lease_expires_at",
        "last_heartbeat_at",
        "created_at",
        "updated_at",
        "completed_at",
    ):
        assert f"{column} DATETIME(6)" in ddl
