"""Validate the added migration on an isolated in-memory database."""

import importlib.util
from datetime import datetime
from pathlib import Path

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations


def test_rental_alert_migration_preserves_existing_data_and_has_shop_order_uniqueness():
    path = Path(__file__).resolve().parents[2] / "migrations/versions/20260907_add_xianyu_rental_alerts.py"
    spec = importlib.util.spec_from_file_location("rental_alert_migration", path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("PRAGMA foreign_keys=ON")
        connection.exec_driver_sql("CREATE TABLE xianyu_shops (id INTEGER PRIMARY KEY, name TEXT)")
        connection.exec_driver_sql("INSERT INTO xianyu_shops VALUES (1, 'first'), (2, 'second')")
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()
        table = sa.Table("xianyu_rental_alerts", sa.MetaData(), autoload_with=connection)
        row = dict(order_no="XY", kind="closed", status_text="交易关闭", order_status=24,
                   refund_status=0, first_detected_at=datetime.utcnow(), last_seen_at=datetime.utcnow())
        connection.execute(table.insert(), [{**row, "xianyu_shop_id": 1}, {**row, "xianyu_shop_id": 2}])
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(table.insert(), {**row, "xianyu_shop_id": 1})
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(table.insert(), {**row, "xianyu_shop_id": 99})
        with Operations.context(MigrationContext.configure(connection)):
            revision.downgrade()
        assert sa.inspect(connection).get_table_names() == ["xianyu_shops"]
        assert connection.exec_driver_sql("SELECT COUNT(*) FROM xianyu_shops").scalar_one() == 2
    engine.dispose()


def test_rental_alert_ignore_migration_adds_nullable_reason_columns():
    path = Path(__file__).resolve().parents[2] / "migrations/versions/20260908_add_xianyu_rental_alert_ignore.py"
    spec = importlib.util.spec_from_file_location("rental_alert_ignore_migration", path)
    revision = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(revision)
    engine = sa.create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE xianyu_rental_alerts ("
            "id INTEGER PRIMARY KEY, ignored_marker TEXT)"
        )
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()
        columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("xianyu_rental_alerts")
        }
        assert {"ignored_at", "ignored_reason"} <= columns
        with Operations.context(MigrationContext.configure(connection)):
            revision.downgrade()
        columns = {
            column["name"]
            for column in sa.inspect(connection).get_columns("xianyu_rental_alerts")
        }
        assert {"ignored_at", "ignored_reason"}.isdisjoint(columns)
    engine.dispose()
