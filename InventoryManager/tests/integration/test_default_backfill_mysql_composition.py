"""Complete default-backfill composition on the approved existing test DB."""

from __future__ import annotations

from tests.support.default_backfill import (
    run_complete_default_backfill_composition,
)


def test_complete_default_backfill_and_reconciliation_on_existing_test_db(
    mysql_routed_database,
):
    engine = mysql_routed_database.engine
    try:
        observation = run_complete_default_backfill_composition(
            engine=engine,
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
        with engine.begin() as connection:
            connection.exec_driver_sql("DROP TABLE IF EXISTS alembic_version")
