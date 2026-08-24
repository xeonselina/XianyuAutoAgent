import os

import pytest
import sqlalchemy as sa


os.environ["TESTING"] = "true"
os.environ.pop("DATABASE_URL", None)
os.environ.pop("DATABASE_URL_HOST", None)
os.environ.pop("CONTROL_DATABASE_URL", None)


@pytest.fixture(scope="session")
def mysql_test_schema():
    """Own the one guarded MySQL schema and application for a serial run."""

    from app import create_app, db
    from inventory_control import ControlBase
    from tests.support.test_database import guarded_mysql_control_database
    from tests.support.test_database import build_mysql_test_config

    application = create_app(build_mysql_test_config())
    metadata = sa.MetaData()
    for table in ControlBase.metadata.sorted_tables:
        table.to_metadata(metadata)
    for table in db.metadata.sorted_tables:
        table.to_metadata(metadata)
    with guarded_mysql_control_database(
        metadata,
        engine_options={
            "pool_pre_ping": True,
            "pool_recycle": 300,
            "connect_args": {
                "connect_timeout": 5,
                "read_timeout": 120,
                "write_timeout": 120,
            },
        },
    ) as database:
        yield application, database, metadata
    with application.app_context():
        db.session.remove()
        db.engine.dispose()


@pytest.fixture(scope="session")
def mysql_control_database_schema(mysql_test_schema):
    """Expose the shared control database without creating another lifecycle."""

    _application, database, metadata = mysql_test_schema
    return database, metadata


@pytest.fixture
def app(mysql_test_schema):
    """Return the guarded MySQL application with an empty routed schema."""

    from app import db
    from tests.support.test_database import clear_guarded_mysql_test_rows

    application, database, metadata = mysql_test_schema
    clear_guarded_mysql_test_rows(database.engine, metadata)
    with application.app_context():
        yield application
        db.session.remove()


@pytest.fixture
def application(app):
    """Alias used by service-level tests."""

    return app


@pytest.fixture
def db_session(app):
    """Return the guarded application session owned by the test fixture."""

    from app import db

    return db.session


@pytest.fixture
def mysql_control_database(mysql_control_database_schema):
    """Return an empty control database on ``inventory_management_test``."""

    from inventory_control import ControlBase
    from tests.support.test_database import clear_guarded_mysql_test_rows

    database, _metadata = mysql_control_database_schema
    clear_guarded_mysql_test_rows(
        database.engine,
        ControlBase.metadata,
    )
    return database


@pytest.fixture
def mysql_routed_database(mysql_control_database_schema):
    """Return an empty combined control/tenant database."""

    from tests.support.test_database import clear_guarded_mysql_test_rows

    database, metadata = mysql_control_database_schema
    clear_guarded_mysql_test_rows(database.engine, metadata)
    return database


@pytest.fixture
def mysql_application_engine(mysql_control_database_schema):
    """Return the approved test engine with empty tenant-business tables."""

    from app import db
    from tests.support.test_database import clear_guarded_mysql_test_rows

    database, _metadata = mysql_control_database_schema
    clear_guarded_mysql_test_rows(database.engine, db.metadata)
    return database.engine


@pytest.fixture(scope="module")
def mysql_control_migration_schema_url():
    """Own one locked control migration schema for a serial test module."""

    from inventory_control import ControlBase
    from tests.support.test_database import guarded_mysql_migration_database

    if os.environ.get("RUN_REAL_MYSQL_MIGRATION_TESTS", "").lower() != "true":
        pytest.skip("existing test-database migration tests require opt-in")
    with guarded_mysql_migration_database(ControlBase.metadata) as url:
        yield url


@pytest.fixture
def mysql_control_migration_url(mysql_control_migration_schema_url):
    """Reset the locked control migration schema before one test case."""

    from inventory_control import ControlBase
    from tests.support.test_database import (
        reset_guarded_mysql_migration_database,
    )

    reset_guarded_mysql_migration_database(
        mysql_control_migration_schema_url,
        ControlBase.metadata,
    )
    return mysql_control_migration_schema_url


@pytest.fixture(scope="module")
def mysql_tenant_migration_schema_url():
    """Own one locked tenant migration schema for a serial test module."""

    from app import create_app, db
    from tests.support.test_database import guarded_mysql_migration_database

    if os.environ.get("RUN_REAL_MYSQL_MIGRATION_TESTS", "").lower() != "true":
        pytest.skip("existing test-database migration tests require opt-in")
    create_app("testing")
    with guarded_mysql_migration_database(db.metadata) as url:
        yield url


@pytest.fixture
def mysql_tenant_migration_url(mysql_tenant_migration_schema_url):
    """Reset the locked tenant migration schema before one test case."""

    from app import db
    from tests.support.test_database import (
        reset_guarded_mysql_migration_database,
    )

    reset_guarded_mysql_migration_database(
        mysql_tenant_migration_schema_url,
        db.metadata,
    )
    return mysql_tenant_migration_schema_url
