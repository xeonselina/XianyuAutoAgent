import pytest
from sqlalchemy import inspect

from app import create_app, db as tenant_db
from config import TestingConfig
from inventory_control import ControlBase, get_control_database


def test_control_database_is_disabled_by_default_in_tests():
    app = create_app("testing")

    assert "inventory_control" not in app.extensions


def test_explicit_control_database_is_independent_and_does_not_create_schema(
    mysql_control_database,
):
    database_url = mysql_control_database.engine.url.render_as_string(
        hide_password=False
    )
    table_names_before = set(
        inspect(mysql_control_database.engine).get_table_names()
    )

    class ControlTestingConfig(TestingConfig):
        CONTROL_DATABASE_URL = database_url
        CONTROL_DATABASE_ENGINE_OPTIONS = {"pool_pre_ping": True}

    app = create_app(ControlTestingConfig)
    control_database = app.extensions["inventory_control"]
    try:
        with app.app_context():
            assert get_control_database() is control_database
            assert control_database.engine is not tenant_db.engine
            assert set(inspect(control_database.engine).get_table_names()) == (
                table_names_before
            )
        assert "devices" not in ControlBase.metadata.tables
        assert "tenants" in ControlBase.metadata.tables
    finally:
        control_database.dispose()


def test_get_control_database_requires_configuration():
    app = create_app("testing")

    with app.app_context(), pytest.raises(RuntimeError, match="not configured"):
        get_control_database()
