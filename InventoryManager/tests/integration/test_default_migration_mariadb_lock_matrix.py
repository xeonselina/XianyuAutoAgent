"""Real MariaDB connector and lock semantics on the approved test schema."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import sqlalchemy as sa

from inventory_control import BackgroundJob, Tenant
from inventory_control.jobs import ControlJobService


NOW = datetime(2026, 8, 24, 0, 0, tzinfo=timezone.utc)
_LOCK_NAME = "im:default-migration:mariadb-lock-matrix:v1"


def test_mariadb_connector_skip_locked_and_advisory_lock_matrix(
    mysql_routed_database,
):
    """Prove the production connector primitives on inventory_management_test."""

    database = mysql_routed_database
    engine = database.engine
    assert engine.dialect.name == "mysql"
    assert engine.dialect.driver == "pymysql"

    service = ControlJobService()
    with database.transaction() as session:
        tenant = Tenant()
        session.add(tenant)
        session.flush()
        high = service.enqueue_job(
            session,
            tenant_id=tenant.id,
            tenant_access_version=1,
            job_type="migration_lock_probe",
            resource_key="migration-lock:high",
            payload={"probe": "high"},
            idempotency_key="migration-lock:high",
            requested_by_type="system",
            priority=100,
            available_at=NOW,
        )
        low = service.enqueue_job(
            session,
            tenant_id=tenant.id,
            tenant_access_version=1,
            job_type="migration_lock_probe",
            resource_key="migration-lock:low",
            payload={"probe": "low"},
            idempotency_key="migration-lock:low",
            requested_by_type="system",
            priority=10,
            available_at=NOW,
        )
        high_id = high.id
        low_id = low.id

    with engine.connect() as first, engine.connect() as second:
        first_profile = first.exec_driver_sql(
            "SELECT VERSION(), @@version_comment, CONNECTION_ID(), "
            "@@character_set_connection, @@SESSION.sql_mode"
        ).one()
        second_connection_id = second.exec_driver_sql(
            "SELECT CONNECTION_ID()"
        ).scalar_one()
        version, comment, first_connection_id, charset, sql_mode = first_profile
        assert str(version).startswith("10.11.")
        assert "mariadb" in f"{version} {comment}".lower()
        assert first_connection_id != second_connection_id
        assert str(charset).lower() == "utf8mb4"
        assert "STRICT_TRANS_TABLES" in str(sql_mode).upper().split(",")

        first.exec_driver_sql("SET SESSION time_zone = '+00:00'")
        first_now, first_utc_now, microsecond_value = first.exec_driver_sql(
            "SELECT NOW(6), UTC_TIMESTAMP(6), "
            "CAST('2026-08-24 12:34:56.123456' AS DATETIME(6))"
        ).one()
        assert abs(first_now - first_utc_now) <= timedelta(seconds=1)
        assert microsecond_value == datetime(2026, 8, 24, 12, 34, 56, 123456)
        first.commit()
        second.commit()

        first_transaction = first.begin()
        second_transaction = second.begin()
        try:
            locked = first.execute(
                sa.select(BackgroundJob.id)
                .where(BackgroundJob.id == high_id)
                .with_for_update()
            ).scalar_one()
            assert locked == high_id

            skipped = second.exec_driver_sql(
                "SELECT id FROM background_jobs "
                "WHERE status = 'pending' "
                "ORDER BY priority DESC, available_at ASC, "
                "created_at ASC, id ASC "
                "LIMIT 1 FOR UPDATE SKIP LOCKED"
            ).scalar_one()
            assert skipped == low_id
        finally:
            second_transaction.rollback()
            first_transaction.rollback()

        try:
            assert first.exec_driver_sql(
                "SELECT GET_LOCK(%s, 0)", (_LOCK_NAME,)
            ).scalar_one() == 1
            assert first.exec_driver_sql(
                "SELECT IS_USED_LOCK(%s)", (_LOCK_NAME,)
            ).scalar_one() == first_connection_id
            assert second.exec_driver_sql(
                "SELECT GET_LOCK(%s, 0)", (_LOCK_NAME,)
            ).scalar_one() == 0
            assert second.exec_driver_sql(
                "SELECT RELEASE_LOCK(%s)", (_LOCK_NAME,)
            ).scalar_one() == 0
            assert first.exec_driver_sql(
                "SELECT RELEASE_LOCK(%s)", (_LOCK_NAME,)
            ).scalar_one() == 1
            assert second.exec_driver_sql(
                "SELECT GET_LOCK(%s, 0)", (_LOCK_NAME,)
            ).scalar_one() == 1
            assert second.exec_driver_sql(
                "SELECT IS_USED_LOCK(%s)", (_LOCK_NAME,)
            ).scalar_one() == second_connection_id
        finally:
            first.exec_driver_sql("SELECT RELEASE_LOCK(%s)", (_LOCK_NAME,))
            second.exec_driver_sql("SELECT RELEASE_LOCK(%s)", (_LOCK_NAME,))
            first.rollback()
            second.rollback()
