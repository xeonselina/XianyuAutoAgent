"""Opt-in real-MySQL expand composition across four physical targets."""

from __future__ import annotations

from contextlib import ExitStack
import os

import pytest
import sqlalchemy as sa

from app import db
from inventory_control import ControlBase
from inventory_control.default_migration import (
    DefaultMySqlTenantGrantMatrixVerifier,
    DefaultSchemaQualificationTarget,
)
from tests.support.default_expand import run_complete_expand_composition
from tests.support.test_database import (
    assert_test_database_url,
    guarded_mysql_test_metadata,
)


_MIGRATION_URLS = (
    "TEST_CONTROL_QUALIFICATION_DATABASE_URL",
    "TEST_CONTROL_APPLY_DATABASE_URL",
    "TEST_TENANT_QUALIFICATION_DATABASE_URL",
    "TEST_TENANT_APPLY_DATABASE_URL",
)
_ACCOUNT_URLS = (
    "TEST_DML_DATABASE_URL",
    "TEST_PLATFORM_READ_DATABASE_URL",
)
_REQUIRED_URLS = (*_MIGRATION_URLS, *_ACCOUNT_URLS)
_ENABLED = (
    os.environ.get("RUN_REAL_MYSQL_EXPAND_TESTS", "").lower() == "true"
    and os.environ.get("ALLOW_REAL_TEST_DATABASE", "").lower() == "true"
    and all(os.environ.get(name) for name in _REQUIRED_URLS)
)
pytestmark = pytest.mark.skipif(
    not _ENABLED,
    reason=(
        "real MySQL expand composition requires explicit opt-in, four "
        "physical migration targets and two tenant account URLs"
    ),
)


def test_complete_expand_composition_on_mysql8(tmp_path):
    parsed = {
        name: assert_test_database_url(os.environ[name])
        for name in _REQUIRED_URLS
    }
    engines = {
        name: sa.create_engine(
            parsed[name].render_as_string(hide_password=False)
        )
        for name in _MIGRATION_URLS
    }
    dml = sa.create_engine(
        parsed["TEST_DML_DATABASE_URL"].render_as_string(
            hide_password=False
        )
    )
    platform_read = sa.create_engine(
        parsed["TEST_PLATFORM_READ_DATABASE_URL"].render_as_string(
            hide_password=False
        )
    )
    all_engines = (*engines.values(), dml, platform_read)
    target = DefaultSchemaQualificationTarget(
        mysql_database_name="inventory_management_test",
        real_test_database_authorized=True,
    )
    grant_matrix = DefaultMySqlTenantGrantMatrixVerifier(
        dml_connection_factory=lambda: dml.connect(),
        platform_read_connection_factory=lambda: platform_read.connect(),
        dml_username=parsed["TEST_DML_DATABASE_URL"].username,
        platform_read_username=(
            parsed["TEST_PLATFORM_READ_DATABASE_URL"].username
        ),
        database_name="inventory_management_test",
        foreign_database_name="inventory_control_probe",
    )
    try:
        with ExitStack() as stack:
            stack.enter_context(
                guarded_mysql_test_metadata(
                    engines["TEST_CONTROL_QUALIFICATION_DATABASE_URL"],
                    ControlBase.metadata,
                )
            )
            stack.enter_context(
                guarded_mysql_test_metadata(
                    engines["TEST_CONTROL_APPLY_DATABASE_URL"],
                    ControlBase.metadata,
                )
            )
            stack.enter_context(
                guarded_mysql_test_metadata(
                    engines["TEST_TENANT_QUALIFICATION_DATABASE_URL"],
                    db.metadata,
                )
            )
            stack.enter_context(
                guarded_mysql_test_metadata(
                    engines["TEST_TENANT_APPLY_DATABASE_URL"],
                    db.metadata,
                )
            )
            observation = run_complete_expand_composition(
                control_qualification_engine=(
                    engines["TEST_CONTROL_QUALIFICATION_DATABASE_URL"]
                ),
                control_apply_engine=(
                    engines["TEST_CONTROL_APPLY_DATABASE_URL"]
                ),
                tenant_qualification_engine=(
                    engines["TEST_TENANT_QUALIFICATION_DATABASE_URL"]
                ),
                tenant_apply_engine=(
                    engines["TEST_TENANT_APPLY_DATABASE_URL"]
                ),
                qualification_target=target,
                grant_matrix_verifier=grant_matrix,
                journal_path=(tmp_path / "mysql-expand-journal.json").resolve(),
                database_instance_key="isolated-mysql8",
            )
            assert len(observation.phase_result_digest) == 32
    finally:
        for engine in all_engines:
            engine.dispose()
