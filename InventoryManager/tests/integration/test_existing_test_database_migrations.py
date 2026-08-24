"""Tenant migration round trip on the approved existing test database."""

from __future__ import annotations

from contextlib import contextmanager
import os
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
import pytest
import sqlalchemy as sa

from app import create_app, db
from inventory_control import ControlBase
from tests.support.tenant_migration import build_tenant_saas_segment_baseline
from tests.support.test_database import (
    build_mysql_test_config,
    guarded_mysql_test_metadata,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TENANT_MIGRATIONS = PROJECT_ROOT / "migrations"
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
TENANT_BASELINE = "20260807_damage_notes"
TENANT_HEAD = "20260823_shipping_contract"
CONTROL_HEAD = "202608230038"
pytestmark = pytest.mark.skipif(
    os.environ.get("RUN_REAL_MYSQL_MIGRATION_TESTS", "").lower() != "true",
    reason="existing test-database migration round trip requires opt-in",
)


def test_tenant_saas_segment_round_trip_on_existing_test_database():
    application = create_app(build_mysql_test_config())
    with application.app_context():
        engine = db.engine
        with guarded_mysql_test_metadata(
            engine,
            db.metadata,
        ), _drop_alembic_version_after(engine):
            build_tenant_saas_segment_baseline(
                engine,
                script_location=TENANT_MIGRATIONS,
                target_metadata=db.metadata,
                schema_head=TENANT_HEAD,
                baseline_revision=TENANT_BASELINE,
            )
            with engine.connect() as connection:
                config = Config(str(TENANT_MIGRATIONS / "alembic.ini"))
                config.set_main_option(
                    "script_location",
                    str(TENANT_MIGRATIONS),
                )
                config.attributes["connection"] = connection
                config.attributes["target_metadata"] = db.metadata
                assert _current_revision(connection) == TENANT_BASELINE
                command.upgrade(config, TENANT_HEAD)
                connection.commit()
                assert _current_revision(connection) == TENANT_HEAD
                assert compare_metadata(
                    MigrationContext.configure(connection),
                    db.metadata,
                ) == []
                connection.commit()
                command.downgrade(config, TENANT_BASELINE)
                connection.commit()
                assert _current_revision(connection) == TENANT_BASELINE
                command.upgrade(config, TENANT_HEAD)
                connection.commit()
                assert _current_revision(connection) == TENANT_HEAD
                assert compare_metadata(
                    MigrationContext.configure(connection),
                    db.metadata,
                ) == []
        db.session.remove()


def test_control_schema_round_trip_on_existing_test_database():
    application = create_app(build_mysql_test_config())
    with application.app_context():
        engine = db.engine
        with guarded_mysql_test_metadata(
            engine,
            ControlBase.metadata,
        ), _drop_alembic_version_after(engine):
            # The metadata guard establishes a known, locked schema before the
            # test.  Remove that synthetic head so Alembic itself must build
            # the complete control chain from base on the same approved test
            # database.
            ControlBase.metadata.drop_all(bind=engine)
            with engine.connect() as connection:
                config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
                config.set_main_option(
                    "script_location",
                    str(CONTROL_MIGRATIONS),
                )
                config.attributes["connection"] = connection

                command.upgrade(config, CONTROL_HEAD)
                connection.commit()
                assert _current_revision(connection) == CONTROL_HEAD
                assert compare_metadata(
                    MigrationContext.configure(connection),
                    ControlBase.metadata,
                ) == []

                command.downgrade(config, "base")
                connection.commit()
                assert _current_revision(connection) is None
                assert set(sa.inspect(connection).get_table_names()) <= {
                    "alembic_version"
                }

                command.upgrade(config, CONTROL_HEAD)
                connection.commit()
                assert _current_revision(connection) == CONTROL_HEAD
                assert compare_metadata(
                    MigrationContext.configure(connection),
                    ControlBase.metadata,
                ) == []
        db.session.remove()


def _current_revision(connection) -> str | None:
    heads = tuple(MigrationContext.configure(connection).get_current_heads())
    assert len(heads) <= 1
    return heads[0] if heads else None


@contextmanager
def _drop_alembic_version_after(engine):
    try:
        yield
    finally:
        with engine.begin() as connection:
            connection.exec_driver_sql(
                "DROP TABLE IF EXISTS alembic_version"
            )
