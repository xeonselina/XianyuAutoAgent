from __future__ import annotations

from io import StringIO
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

from inventory_control.models import ControlBase


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"
OPERATIONS_TABLES = {
    "platform_alert_lifecycle_events",
    "platform_operational_signals",
}


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


def test_operations_migration_contract_is_present_in_current_control_head():
    config = _alembic_config("mysql+pymysql://unused:unused@localhost/control")
    script = ScriptDirectory.from_config(config)
    ancestry = {
        revision.revision
        for revision in script.walk_revisions(base="base", head="heads")
    }

    assert "202608220011" in ancestry
    assert "202608230030" in ancestry
    assert OPERATIONS_TABLES <= set(ControlBase.metadata.tables)
    signal_columns = set(
        ControlBase.metadata.tables["platform_operational_signals"].columns.keys()
    )
    assert {
        "signal_key",
        "observed_result_class",
        "freshness_deadline_at",
        "consecutive_failures",
        "consecutive_recoveries",
        "active_alert_fingerprint",
    } <= signal_columns


def test_operations_migration_emits_mysql_8_compatible_offline_ddl():
    output = StringIO()
    config = _alembic_config("mysql+pymysql://unused:unused@localhost/control")
    config.output_buffer = output

    command.upgrade(
        config,
        "202608220010:202608220011",
        sql=True,
    )
    ddl = output.getvalue()

    assert "CREATE TABLE platform_operational_signals" in ddl
    assert "CREATE TABLE platform_alert_lifecycle_events" in ddl
    assert "VARCHAR(64)" in ddl
    assert "CHECK (signal_key IN" in ddl
    assert "FOREIGN KEY(signal_key)" in ddl
    assert "tenant_id" not in ddl
    assert " JSON" not in ddl.upper()


def test_operational_timestamp_precision_forward_fix_emits_mysql_datetime_6():
    output = StringIO()
    config = _alembic_config("mysql+pymysql://unused:unused@localhost/control")
    config.output_buffer = output

    command.upgrade(
        config,
        "202608220029:202608230030",
        sql=True,
    )
    ddl = output.getvalue().upper()

    assert ddl.count("DATETIME(6)") == 9
    assert "ALTER TABLE PLATFORM_OPERATIONAL_SIGNALS" in ddl
    assert "ALTER TABLE PLATFORM_ALERT_LIFECYCLE_EVENTS" in ddl


def test_recovery_factor_precision_fix_emits_mysql_datetime_6():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/control"
    )
    config.output_buffer = output

    command.upgrade(
        config,
        "202608230031:202608230032",
        sql=True,
    )
    ddl = output.getvalue().upper()

    assert "ALTER TABLE PLATFORM_ADMIN_RECOVERY_CODES" in ddl
    assert "CONSUMED_AT DATETIME(6)" in ddl


def test_sms_protocol_precision_fix_emits_six_mysql_datetime_6_columns():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/control"
    )
    config.output_buffer = output

    command.upgrade(
        config,
        "202608230032:202608230033",
        sql=True,
    )
    ddl = output.getvalue().upper()

    assert ddl.count("ALTER TABLE SMS_CHALLENGES") == 6
    assert ddl.count("DATETIME(6)") == 6


def test_sensitive_action_precision_fix_emits_six_mysql_datetime_6_columns():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/control"
    )
    config.output_buffer = output

    command.upgrade(
        config,
        "202608230033:202608230034",
        sql=True,
    )
    ddl = output.getvalue().upper()

    assert ddl.count("ALTER TABLE TENANT_SENSITIVE_ACTION_INTENTS") == 6
    assert ddl.count("DATETIME(6)") == 6


def test_invitation_precision_fix_emits_five_mysql_datetime_6_columns():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/control"
    )
    config.output_buffer = output

    command.upgrade(
        config,
        "202608230034:202608230035",
        sql=True,
    )
    ddl = output.getvalue().upper()

    assert ddl.count("ALTER TABLE TENANT_INVITATIONS") == 5
    assert ddl.count("DATETIME(6)") == 5


def test_platform_session_precision_fix_emits_six_mysql_datetime_6_columns():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/control"
    )
    config.output_buffer = output

    command.upgrade(
        config,
        "202608230035:202608230036",
        sql=True,
    )
    ddl = output.getvalue().upper()

    assert ddl.count("ALTER TABLE PLATFORM_ADMIN_SESSIONS") == 6
    assert ddl.count("DATETIME(6)") == 6


def test_subscription_protocol_precision_fix_emits_six_mysql_datetime_6_columns():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/control"
    )
    config.output_buffer = output

    command.upgrade(
        config,
        "202608230036:202608230037",
        sql=True,
    )
    ddl = output.getvalue().upper()

    assert ddl.count("ALTER TABLE SUBSCRIPTIONS") == 1
    assert ddl.count("ALTER TABLE SUBSCRIPTION_EVENTS") == 5
    assert ddl.count("DATETIME(6)") == 6


def test_schema_operation_digest_fix_emits_mysql_varbinary_32():
    output = StringIO()
    config = _alembic_config(
        "mysql+pymysql://unused:unused@localhost/control"
    )
    config.output_buffer = output

    command.upgrade(
        config,
        "202608230037:202608230038",
        sql=True,
    )
    ddl = output.getvalue().upper()

    assert "ALTER TABLE PLATFORM_SCHEMA_OPERATION_LEASES" in ddl
    assert "LAST_REQUEST_DIGEST VARBINARY(32)" in ddl
