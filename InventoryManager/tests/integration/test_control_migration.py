import os

import pytest
from alembic import command
from alembic.config import Config as AlembicConfig
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DatabaseError, IntegrityError


DOMAIN_TABLES = {
    "platform_admins",
    "tenants",
    "tenant_members",
    "auth_sessions",
    "sms_login_codes",
}


def _control_database_url():
    raw_url = os.environ.get("TEST_CONTROL_DATABASE_URL")
    if not raw_url:
        pytest.skip("TEST_CONTROL_DATABASE_URL is required for MariaDB test")
    parsed = make_url(raw_url)
    if parsed.database != "control_saas_test":
        raise RuntimeError(
            "control migration tests may only reset control_saas_test"
        )
    return parsed.render_as_string(hide_password=False)


def _reset_control_schema(engine):
    with engine.begin() as connection:
        connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 0")
        try:
            preparer = connection.dialect.identifier_preparer
            for table_name in inspect(connection).get_table_names():
                quoted_name = preparer.quote_identifier(table_name)
                connection.exec_driver_sql(f"DROP TABLE {quoted_name}")
        finally:
            connection.exec_driver_sql("SET FOREIGN_KEY_CHECKS = 1")


@pytest.fixture
def migrated_control_database(monkeypatch):
    url = _control_database_url()
    engine = create_engine(url, pool_pre_ping=True)
    _reset_control_schema(engine)
    monkeypatch.setenv("CONTROL_DATABASE_URL", url)
    alembic_config = AlembicConfig("control_alembic.ini")

    try:
        command.upgrade(alembic_config, "head")
        yield engine, alembic_config
    finally:
        try:
            command.downgrade(alembic_config, "base")
        finally:
            _reset_control_schema(engine)
            engine.dispose()


def test_control_baseline_has_exact_domain_tables(migrated_control_database):
    engine, _ = migrated_control_database

    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())

    assert tables - {"alembic_version"} == DOMAIN_TABLES
    assert tables <= DOMAIN_TABLES | {"alembic_version"}


def test_control_baseline_has_exact_domain_columns(migrated_control_database):
    engine, _ = migrated_control_database
    expected_columns = {
        "platform_admins": {
            "id", "username", "password_hash", "totp_secret_ciphertext",
            "created_at", "updated_at",
        },
        "tenants": {
            "id", "name", "status", "expires_at", "db_name",
            "db_username", "db_password_ciphertext",
            "provisioning_status", "provisioning_error", "created_at",
            "updated_at",
        },
        "tenant_members": {
            "id", "tenant_id", "phone", "role", "status", "created_at",
            "updated_at",
        },
        "auth_sessions": {
            "id", "kind", "subject_id", "tenant_id", "token_hash",
            "csrf_token_hash", "expires_at", "created_at", "last_seen_at",
        },
        "sms_login_codes": {
            "id", "phone", "code_digest", "requested_ip",
            "send_succeeded", "attempt_count", "expires_at", "consumed_at",
            "created_at",
        },
    }

    with engine.connect() as connection:
        inspector = inspect(connection)
        actual_columns = {
            table_name: {
                column["name"]
                for column in inspector.get_columns(table_name)
            }
            for table_name in DOMAIN_TABLES
        }

    assert actual_columns == expected_columns


def test_control_models_match_migrated_baseline(migrated_control_database):
    _, alembic_config = migrated_control_database

    command.check(alembic_config)


def test_control_baseline_enforces_uniques_and_checks(
    migrated_control_database,
):
    engine, _ = migrated_control_database

    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            INSERT INTO tenants (
                name, status, expires_at, db_name, db_username,
                db_password_ciphertext, provisioning_status,
                created_at, updated_at
            ) VALUES (
                'Tenant A', 'active', '2027-08-24 00:00:00',
                'tenant_a', 'tenant_a_user', 'ciphertext', 'active',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """
        )
        tenant_id = connection.exec_driver_sql(
            "SELECT id FROM tenants WHERE db_name = 'tenant_a'"
        ).scalar_one()
        connection.exec_driver_sql(
            """
            INSERT INTO tenant_members (
                tenant_id, phone, role, status, created_at, updated_at
            ) VALUES (
                %s, '+8613800138000', 'admin', 'active',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (tenant_id,),
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                INSERT INTO tenant_members (
                    tenant_id, phone, role, status, created_at, updated_at
                ) VALUES (
                    %s, '+8613800138000', 'operator', 'active',
                    CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """,
                (tenant_id,),
            )

    with pytest.raises(DatabaseError):
        with engine.begin() as connection:
            connection.exec_driver_sql(
                """
                INSERT INTO tenants (
                    name, status, expires_at, db_name, db_username,
                    db_password_ciphertext, provisioning_status,
                    created_at, updated_at
                ) VALUES (
                    'Invalid Tenant', 'deleted', '2027-08-24 00:00:00',
                    'tenant_invalid', 'tenant_invalid_user', 'ciphertext',
                    'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
                )
                """
            )

    expected_checks = {
        "tenants": {
            "ck_tenants_status",
            "ck_tenants_provisioning_status",
        },
        "tenant_members": {
            "ck_tenant_members_role",
            "ck_tenant_members_status",
        },
        "auth_sessions": {"ck_auth_sessions_kind"},
    }
    expected_uniques = {
        "platform_admins": {"uq_platform_admins_username"},
        "tenants": {"uq_tenants_db_name", "uq_tenants_db_username"},
        "tenant_members": {"uq_tenant_members_phone"},
        "auth_sessions": {"uq_auth_sessions_token_hash"},
        "sms_login_codes": set(),
    }
    expected_foreign_keys = {
        "platform_admins": set(),
        "tenants": set(),
        "tenant_members": {
            (("tenant_id",), "tenants", ("id",)),
        },
        "auth_sessions": {
            (("tenant_id",), "tenants", ("id",)),
        },
        "sms_login_codes": set(),
    }
    with engine.connect() as connection:
        inspector = inspect(connection)
        actual_checks = {
            table_name: {
                constraint["name"]
                for constraint in inspector.get_check_constraints(table_name)
            }
            for table_name in expected_checks
        }
        actual_uniques = {
            table_name: {
                constraint["name"]
                for constraint in inspector.get_unique_constraints(
                    table_name
                )
            }
            for table_name in expected_uniques
        }
        actual_foreign_keys = {
            table_name: {
                (
                    tuple(constraint["constrained_columns"]),
                    constraint["referred_table"],
                    tuple(constraint["referred_columns"]),
                )
                for constraint in inspector.get_foreign_keys(table_name)
            }
            for table_name in expected_foreign_keys
        }

    assert actual_checks == expected_checks
    assert actual_uniques == expected_uniques
    assert actual_foreign_keys == expected_foreign_keys


def test_control_baseline_downgrades_all_domain_tables(
    migrated_control_database,
):
    engine, alembic_config = migrated_control_database

    command.downgrade(alembic_config, "base")

    with engine.connect() as connection:
        tables = set(inspect(connection).get_table_names())
    assert not tables & DOMAIN_TABLES
