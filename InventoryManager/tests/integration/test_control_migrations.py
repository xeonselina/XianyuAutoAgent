import logging
from pathlib import Path

import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext

from inventory_control import ControlBase
from tests.support.test_database import alembic_config_database_url


PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTROL_MIGRATIONS = PROJECT_ROOT / "control_migrations"


def _alembic_config(database_url: str) -> Config:
    config = Config(str(CONTROL_MIGRATIONS / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_MIGRATIONS))
    config.set_main_option(
        "sqlalchemy.url",
        alembic_config_database_url(database_url),
    )
    return config


def test_control_migration_upgrade_downgrade_upgrade(
    mysql_control_migration_url,
):
    host_logger = logging.getLogger("tests.control_migration_host_runtime")
    host_logger.disabled = False
    database_url = mysql_control_migration_url
    config = _alembic_config(database_url)
    expected_tables = {
        "alembic_version",
        "background_jobs",
        "backup_attempts",
        "backup_artifact_acknowledgements",
        "completed_backup_artifacts",
        "control_installations",
        "control_outbox_events",
        "database_identity_control_records",
        "disaster_recovery_release_actions",
        "disaster_recovery_runs",
        "plans",
        "redemption_code_batches",
        "redemption_codes",
        "redemption_code_replacements",
        "registration_integrity_incidents",
        "platform_admin_rate_limit_counters",
        "platform_admin_recovery_codes",
        "platform_admin_sessions",
        "platform_admin_setup_challenges",
            "platform_admin_totp_credentials",
            "platform_admins",
            "platform_audit_logs",
        "platform_alert_lifecycle_events",
        "platform_backup_leases",
        "platform_operational_signals",
        "platform_root_key_versions",
        "platform_schema_operation_leases",
        "provider_account_claim_events",
        "provider_account_claims",
        "sms_challenges",
        "sms_rate_limit_subjects",
        "subscription_events",
        "subscriptions",
        "tenant_databases",
        "tenant_fleet_migrations",
        "tenant_database_account_mutation_leases",
        "tenant_database_account_rotations",
        "tenant_deletion_actions",
        "tenant_deletion_effects",
        "tenant_deletion_evidence_receipts",
        "tenant_deletion_requests",
        "tenant_deletion_tombstones",
        "tenant_integration_secret_envelope_events",
        "tenant_integration_secret_revisions",
        "tenant_integrations",
        "tenant_invitations",
            "tenant_memberships",
            "tenant_auth_security_events",
        "tenant_provider_defaults",
        "tenant_provider_accounts",
        "tenant_provider_account_secret_revisions",
        "tenant_provider_account_secret_envelope_events",
        "tenant_registration_attempts",
        "tenant_registration_commits",
        "tenant_registration_provisioning_proofs",
            "tenant_recovery_holds",
            "tenant_sensitive_action_intent_challenges",
            "tenant_sensitive_action_intents",
            "tenant_suspension_actions",
        "tenant_suspensions",
        "tenant_quota_guards",
        "tenant_user_sessions",
        "tenants",
        "users",
    }

    command.upgrade(config, "head")
    assert host_logger.disabled is False
    engine = sa.create_engine(database_url)
    try:
        assert set(sa.inspect(engine).get_table_names()) == expected_tables
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            assert compare_metadata(context, ControlBase.metadata) == []
    finally:
        engine.dispose()

    command.downgrade(config, "base")
    engine = sa.create_engine(database_url)
    try:
        assert set(sa.inspect(engine).get_table_names()) <= {"alembic_version"}
    finally:
        engine.dispose()

    command.upgrade(config, "head")
    engine = sa.create_engine(database_url)
    try:
        assert set(sa.inspect(engine).get_table_names()) == expected_tables
    finally:
        engine.dispose()
