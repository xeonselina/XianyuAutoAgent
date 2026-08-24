"""Opt-in synthetic utf8mb3 MariaDB 10.11 dump/restore into MySQL 8."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
import os
from pathlib import Path

import pytest
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

from tests.support.default_portability import (
    PORTABILITY_TABLES,
    require_empty_scoped_test_database,
    run_default_mariadb_mysql_portability,
)
from tests.support.test_database import assert_test_database_url


_SOURCE_ADMIN_URL = "TEST_PORTABILITY_SOURCE_ADMIN_DATABASE_URL"
_SOURCE_READ_URL = "TEST_PORTABILITY_SOURCE_READ_DATABASE_URL"
_TARGET_URL = "TEST_PORTABILITY_TARGET_DATABASE_URL"
_DOCKER_BINARY = "TEST_PORTABILITY_DOCKER_BINARY"
_SOURCE_DUMP_CONTAINER = "TEST_PORTABILITY_SOURCE_DUMP_CONTAINER"
_RESTORE_BINARY = "TEST_PORTABILITY_MYSQL_BINARY"
_ENABLED = (
    os.environ.get("RUN_REAL_MARIADB_MYSQL_PORTABILITY_TESTS", "").lower()
    == "true"
    and os.environ.get("ALLOW_REAL_TEST_DATABASE", "").lower() == "true"
    and all(
        os.environ.get(name)
        for name in (
            _SOURCE_ADMIN_URL,
            _SOURCE_READ_URL,
            _TARGET_URL,
            _DOCKER_BINARY,
            _SOURCE_DUMP_CONTAINER,
            _RESTORE_BINARY,
        )
    )
)
pytestmark = pytest.mark.skipif(
    not _ENABLED,
    reason="MariaDB/MySQL portability requires explicit disposable endpoints",
)


def _metadata() -> sa.MetaData:
    metadata = sa.MetaData()
    devices = sa.Table(
        "devices",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False),
        sa.Column("acquired_cost", sa.Numeric(10, 2), nullable=False),
        mysql_charset="utf8mb3",
        mysql_collate="utf8mb3_general_ci",
    )
    sa.Table(
        "rentals",
        metadata,
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "device_id",
            sa.Integer,
            sa.ForeignKey(devices.c.id, ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("destination", sa.String(100), nullable=False),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("ship_out_time", mysql.DATETIME(fsp=6), nullable=True),
        sa.Column("ship_in_time", mysql.DATETIME(fsp=6), nullable=True),
        sa.Index("ix_portability_rentals_device", "device_id"),
        mysql_charset="utf8mb3",
        mysql_collate="utf8mb3_general_ci",
    )
    sa.Table(
        "audit_logs",
        metadata,
        sa.Column("id", sa.BigInteger, primary_key=True, autoincrement=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("details", sa.Text, nullable=True),
        mysql_charset="utf8mb3",
        mysql_collate="utf8mb3_general_ci",
    )
    return metadata


def test_utf8mb3_dump_restore_and_utf8mb4_conversion():
    source_admin_url = assert_test_database_url(
        os.environ[_SOURCE_ADMIN_URL]
    ).render_as_string(hide_password=False)
    source_read_url = assert_test_database_url(
        os.environ[_SOURCE_READ_URL]
    ).render_as_string(hide_password=False)
    target_url = assert_test_database_url(
        os.environ[_TARGET_URL]
    ).render_as_string(hide_password=False)
    source_admin = sa.create_engine(source_admin_url, pool_pre_ping=True)
    source_read = sa.create_engine(source_read_url, pool_pre_ping=True)
    target = sa.create_engine(target_url, pool_pre_ping=True)
    metadata = _metadata()
    try:
        assert source_admin.url.host == source_read.url.host
        assert source_admin.url.port == source_read.url.port
        assert source_admin.url.username != source_read.url.username
        assert (source_admin.url.host, source_admin.url.port) != (
            target.url.host,
            target.url.port,
        )
        require_empty_scoped_test_database(source_admin)
        require_empty_scoped_test_database(target)
        metadata.create_all(source_admin)
        with source_admin.begin() as connection:
            connection.execute(
                metadata.tables["devices"].insert(),
                (
                    {
                        "name": "合成相机 A",
                        "active": True,
                        "acquired_cost": Decimal("1234.56"),
                    },
                    {
                        "name": "合成相机 B",
                        "active": False,
                        "acquired_cost": Decimal("78.90"),
                    },
                ),
            )
            connection.execute(
                metadata.tables["rentals"].insert(),
                {
                    "device_id": 1,
                    "destination": "广东省深圳市南山区",
                    "status": "not_shipped",
                    "ship_out_time": datetime(2026, 8, 23, 12, 0, 0, 123456),
                    "ship_in_time": None,
                },
            )
            connection.execute(
                metadata.tables["audit_logs"].insert(),
                {
                    "action": "synthetic_portability",
                    "details": "仅用于隔离迁移测试",
                },
            )

        observation = run_default_mariadb_mysql_portability(
            source_read_engine=source_read,
            target_write_engine=target,
            docker_binary=Path(os.environ[_DOCKER_BINARY]),
            source_dump_container=os.environ[_SOURCE_DUMP_CONTAINER],
            mysql_binary=Path(os.environ[_RESTORE_BINARY]),
        )

        assert observation.source_version.startswith("10.11.")
        assert observation.target_version.startswith("8.0.")
        assert observation.source_character_set == "utf8mb3"
        assert observation.source_collation == "utf8mb3_general_ci"
        assert observation.target_character_set == "utf8mb4"
        assert observation.target_collation == "utf8mb4_0900_ai_ci"
        assert observation.table_counts == (
            ("audit_logs", 1),
            ("devices", 2),
            ("rentals", 1),
        )
        assert observation.dump_size_bytes > 0
        with target.connect() as connection:
            assert connection.exec_driver_sql(
                "SELECT name FROM devices ORDER BY id"
            ).scalars().all() == ["合成相机 A", "合成相机 B"]
            assert connection.exec_driver_sql(
                "SELECT destination FROM rentals"
            ).scalar_one() == "广东省深圳市南山区"
            assert connection.exec_driver_sql(
                "SELECT acquired_cost FROM devices WHERE id = 1"
            ).scalar_one() == Decimal("1234.56")
    finally:
        try:
            metadata.drop_all(target)
        finally:
            metadata.drop_all(source_admin)
            source_admin.dispose()
            source_read.dispose()
            target.dispose()

    assert tuple(sorted(metadata.tables)) == PORTABILITY_TABLES
