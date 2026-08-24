"""Opt-in MySQL 8 qualification for the default-tenant expand boundary."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import sqlalchemy as sa

from app import db
from inventory_control.default_migration import (
    DefaultMySqlTenantGrantMatrixVerifier,
    DefaultSchemaQualificationTarget,
    ExplicitConnectionAlembicQualificationRunner,
)
from tests.support.tenant_migration import (
    build_tenant_saas_segment_baseline,
)
from tests.support.test_database import (
    assert_test_database_url,
    guarded_mysql_test_metadata,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
TENANT_MIGRATIONS = PROJECT_ROOT / "migrations"
TENANT_BASELINE = "20260807_damage_notes"
TENANT_HEAD = "20260823_shipping_contract"
_REQUIRED_URLS = (
    "TEST_QUALIFICATION_DATABASE_URL",
    "TEST_APPLY_DATABASE_URL",
    "TEST_DML_DATABASE_URL",
    "TEST_PLATFORM_READ_DATABASE_URL",
)
_REAL_MYSQL_ENABLED = (
    os.environ.get("RUN_REAL_MYSQL_MIGRATION_TESTS", "").lower() == "true"
    and os.environ.get("ALLOW_REAL_TEST_DATABASE", "").lower() == "true"
    and all(os.environ.get(name) for name in _REQUIRED_URLS)
)
pytestmark = pytest.mark.skipif(
    not _REAL_MYSQL_ENABLED,
    reason=(
        "real MySQL migration qualification requires explicit opt-in and "
        "four isolated account URLs"
    ),
)


def test_tenant_round_trip_forward_apply_and_account_matrix_on_mysql8():
    urls = {
        name: assert_test_database_url(os.environ[name]).render_as_string(
            hide_password=False
        )
        for name in _REQUIRED_URLS
    }
    scratch = sa.create_engine(urls["TEST_QUALIFICATION_DATABASE_URL"])
    applied = sa.create_engine(urls["TEST_APPLY_DATABASE_URL"])
    dml = sa.create_engine(urls["TEST_DML_DATABASE_URL"])
    platform_read = sa.create_engine(urls["TEST_PLATFORM_READ_DATABASE_URL"])
    engines = (scratch, applied, dml, platform_read)
    target = DefaultSchemaQualificationTarget(
        mysql_database_name="inventory_management_test",
        real_test_database_authorized=True,
    )
    runner = ExplicitConnectionAlembicQualificationRunner(
        script_location=TENANT_MIGRATIONS,
        target_metadata=db.metadata,
        schema_head=TENANT_HEAD,
        baseline_revision=TENANT_BASELINE,
    )
    try:
        with guarded_mysql_test_metadata(scratch, db.metadata):
            build_tenant_saas_segment_baseline(
                scratch,
                script_location=TENANT_MIGRATIONS,
                target_metadata=db.metadata,
                schema_head=TENANT_HEAD,
                baseline_revision=TENANT_BASELINE,
            )
            with guarded_mysql_test_metadata(applied, db.metadata):
                build_tenant_saas_segment_baseline(
                    applied,
                    script_location=TENANT_MIGRATIONS,
                    target_metadata=db.metadata,
                    schema_head=TENANT_HEAD,
                    baseline_revision=TENANT_BASELINE,
                )
                with scratch.connect() as connection:
                    qualification = runner.qualify(connection, target=target)
                with applied.connect() as connection:
                    application = runner.apply(connection, target=target)

                assert qualification.dialect == application.dialect == "mysql"
                assert qualification.schema_head == application.schema_head == (
                    TENANT_HEAD
                )
                assert qualification.target_identity_digest != (
                    application.target_identity_digest
                )
                assert qualification.metadata_model_match_digest == (
                    application.metadata_model_match_digest
                )

                grants = DefaultMySqlTenantGrantMatrixVerifier(
                    dml_connection_factory=lambda: dml.connect(),
                    platform_read_connection_factory=(
                        lambda: platform_read.connect()
                    ),
                    dml_username="tenant_dml",
                    platform_read_username="platform_read",
                    database_name="inventory_management_test",
                    foreign_database_name="inventory_control_probe",
                ).verify()
                assert len(grants.dml_grants_digest) == 32
                assert len(grants.platform_read_grants_digest) == 32
                assert len(grants.cross_schema_negative_digest) == 32
    finally:
        for engine in engines:
            engine.dispose()
