"""Opt-in complete default-backfill composition on two disposable MySQL 8s."""

from __future__ import annotations

import os

import pytest
import sqlalchemy as sa

from app import db
from inventory_control import ControlBase
from tests.support.default_backfill import (
    run_complete_default_backfill_composition,
)
from tests.support.test_database import (
    assert_test_database_url,
    guarded_mysql_test_metadata,
)


_TENANT_URL = "TEST_DEFAULT_BACKFILL_TENANT_DATABASE_URL"
_CONTROL_URL = "TEST_DEFAULT_BACKFILL_CONTROL_DATABASE_URL"
_OBSERVER_URL = "TEST_DEFAULT_BACKFILL_OBSERVER_DATABASE_URL"
_REAL_MYSQL_ENABLED = (
    os.environ.get("RUN_REAL_MYSQL_BACKFILL_TESTS", "").lower() == "true"
    and os.environ.get("ALLOW_REAL_TEST_DATABASE", "").lower() == "true"
    and bool(os.environ.get(_TENANT_URL))
    and bool(os.environ.get(_CONTROL_URL))
    and bool(os.environ.get(_OBSERVER_URL))
)
pytestmark = pytest.mark.skipif(
    not _REAL_MYSQL_ENABLED,
    reason="complete backfill requires two explicit disposable MySQL URLs",
)


def test_complete_default_backfill_and_reconciliation_on_mysql8():
    tenant_url = assert_test_database_url(
        os.environ[_TENANT_URL]
    ).render_as_string(hide_password=False)
    control_url = assert_test_database_url(
        os.environ[_CONTROL_URL]
    ).render_as_string(hide_password=False)
    observer_url = assert_test_database_url(
        os.environ[_OBSERVER_URL]
    ).render_as_string(hide_password=False)
    tenant_engine = sa.create_engine(tenant_url, pool_pre_ping=True)
    control_engine = sa.create_engine(control_url, pool_pre_ping=True)
    observer_engine = sa.create_engine(observer_url, pool_pre_ping=True)
    try:
        with tenant_engine.connect() as tenant_connection:
            tenant_server = tenant_connection.exec_driver_sql(
                "SELECT @@server_uuid"
            ).scalar_one()
        with control_engine.connect() as control_connection:
            control_server = control_connection.exec_driver_sql(
                "SELECT @@server_uuid"
            ).scalar_one()
        with observer_engine.connect() as observer_connection:
            observer_server = observer_connection.exec_driver_sql(
                "SELECT @@server_uuid"
            ).scalar_one()
        assert tenant_server != control_server
        assert observer_server == tenant_server

        with guarded_mysql_test_metadata(tenant_engine, db.metadata):
            with guarded_mysql_test_metadata(
                control_engine,
                ControlBase.metadata,
            ):
                observation = run_complete_default_backfill_composition(
                    tenant_engine=tenant_engine,
                    control_engine=control_engine,
                    schema_observer_engine=observer_engine,
                )

        assert observation.result_digest == observation.replay_result_digest
        assert observation.device_rows == 2
        assert observation.device_warehouse_links == 2
        assert observation.default_warehouse_count == 1
        assert observation.logical_unit_count == 1
        assert observation.integration_count == 3
        assert observation.credential_revision_count == 0
        assert observation.rental_express_type_id == 2
        assert observation.schema_generation == 2
        assert len(observation.schema_digest) == 32
        assert observation.crash_resume_verified is True
    finally:
        tenant_engine.dispose()
        control_engine.dispose()
        observer_engine.dispose()
