"""Opt-in read-only source-baseline check on the isolated LAN test schema."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url

from app.services.migration.default_source_baseline import (
    SqlAlchemyDefaultSourceBaselineObserver,
)


SOURCE_URL_ENV = "DEFAULT_SOURCE_BASELINE_TEST_URL"


def test_real_test_schema_source_baseline_is_stable_and_read_only():
    raw_url = os.environ.get(SOURCE_URL_ENV)
    if not raw_url:
        pytest.skip(f"set {SOURCE_URL_ENV} for the opt-in read-only check")
    url = make_url(raw_url)
    if (
        url.get_backend_name() != "mysql"
        or url.database != "inventory_management_test"
    ):
        pytest.fail("source baseline test URL must select inventory_management_test")

    engine = create_engine(url, pool_pre_ping=True)
    observer = SqlAlchemyDefaultSourceBaselineObserver()
    try:
        observations = []
        for _ in range(2):
            with engine.connect() as connection:
                observations.append(
                    observer.observe_with_historical_boundary(
                        connection,
                        source_schema_name="inventory_management_test",
                        baseline_migration_id="pytest-source-baseline-v1",
                    )
                )
                assert connection.in_transaction() is False
        assert observations[0] == observations[1]
        source_baseline, historical_boundary = observations[0]
        assert source_baseline.table_count > 0
        assert source_baseline.total_rows >= 0
        historical_boundary.require_source_baseline(source_baseline)
    finally:
        engine.dispose()
