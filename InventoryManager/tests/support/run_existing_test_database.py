"""Run database-backed tests on the one approved existing test schema.

The launcher derives the test DSN in memory from ``.env`` and never prints it.
It deliberately replaces only the database component and enables the guards
that re-check the selected schema and current grants after connecting.
"""

from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values
from sqlalchemy.engine import make_url


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ISOLATED_DATABASE_TESTS = (
    "tests/integration/test_existing_test_database_migrations.py",
    "tests/unit/test_warehouse_service.py",
    "tests/unit/test_accessory_relay_chain_service.py",
    "tests/integration/test_accessory_mysql_contention.py",
    "tests/integration/test_warehouse_mysql_contention.py",
    "tests/integration/test_gantt_mysql_contention.py",
    "tests/unit/test_relay_case_transitions.py",
    "tests/unit/test_relay_case_service.py",
    "tests/unit/test_relay_case_tracking.py",
    "tests/integration/test_relay_case_api.py",
    "tests/integration/test_gantt_reorder_api.py",
    "tests/unit/test_sf_batch_shipping_http_runtime_impl.py",
    "tests/unit/control_plane/test_jobs.py",
    "tests/unit/control_plane/test_job_runtime.py",
    "tests/unit/control_plane/test_job_authority.py",
    "tests/unit/control_plane/test_job_scheduler.py",
    "tests/unit/control_plane/test_operational_signals.py",
    "tests/unit/control_plane/test_operational_freshness_evaluator.py",
    "tests/unit/control_plane/test_health_endpoints.py",
    "tests/unit/control_plane/test_queue_operational_signals.py",
    "tests/unit/control_plane/test_backup_operational_signals.py",
    "tests/unit/control_plane/test_tenant_sessions.py",
    "tests/unit/control_plane/test_membership_service.py",
    "tests/unit/control_plane/test_subscription_ledger_service.py",
    "tests/unit/control_plane/test_invitation_persistence.py",
    "tests/unit/control_plane/test_sms_challenges.py",
    "tests/unit/control_plane/test_tenant_login_service.py",
)

SHARED_DATABASE_TESTS = (
    "tests/unit/control_plane/test_account_mutation_persistence.py",
    "tests/unit/control_plane/test_backup_ack_persistence.py",
    "tests/unit/control_plane/test_backup_persistence.py",
    "tests/unit/control_plane/test_database.py",
    "tests/unit/control_plane/test_default_migration_collection.py",
    "tests/unit/control_plane/test_default_migration_grant_step.py",
    "tests/unit/control_plane/test_default_migration_policy_registry.py",
    "tests/unit/control_plane/test_default_tenant_in_place_registration.py",
    "tests/unit/control_plane/test_deletion_adapters.py",
    "tests/unit/control_plane/test_deletion_persistence.py",
    "tests/unit/control_plane/test_flask_integration.py",
    "tests/unit/control_plane/test_fleet_migration_persistence.py",
    "tests/unit/control_plane/test_gantt_http_runtime_impl.py",
    "tests/unit/control_plane/test_gantt_preview_authority_reader.py",
    "tests/unit/control_plane/test_inspection_http_runtime_impl.py",
    "tests/unit/control_plane/test_integration_metadata_backfill.py",
    "tests/unit/control_plane/test_inventory_control_cli.py",
    "tests/unit/control_plane/test_invitation_expiry_runtime.py",
    "tests/unit/control_plane/test_invitation_models.py",
    "tests/unit/control_plane/test_models.py",
    "tests/unit/control_plane/test_outbox_runtime.py",
    "tests/unit/control_plane/test_outbox_service.py",
    "tests/unit/control_plane/test_phone_change_service.py",
    "tests/unit/control_plane/test_platform_admin_cli.py",
    "tests/unit/control_plane/test_platform_http_boundary.py",
    "tests/unit/control_plane/test_platform_identity.py",
    "tests/unit/control_plane/test_platform_identity_http_runtime.py",
    "tests/unit/control_plane/test_platform_login_service.py",
    "tests/unit/control_plane/test_platform_subscription_adjustment_http_runtime.py",
    "tests/unit/control_plane/test_platform_tenant_read_http_runtime.py",
    "tests/unit/control_plane/test_provider_account_http_runtime_impl.py",
    "tests/unit/control_plane/test_provider_account_service.py",
    "tests/unit/control_plane/test_provider_account_validation_worker.py",
    "tests/unit/control_plane/test_recovery_authority.py",
    "tests/unit/control_plane/test_recovery_release_service.py",
    "tests/unit/control_plane/test_redemption_code_service.py",
    "tests/unit/control_plane/test_registration_models.py",
    "tests/unit/control_plane/test_registration_persistence.py",
    "tests/unit/control_plane/test_registration_publication_adapters.py",
    "tests/unit/control_plane/test_rental_http_runtime_impl.py",
    "tests/unit/control_plane/test_relay_http_runtime_impl.py",
    "tests/unit/control_plane/test_root_key_lifecycle.py",
    "tests/unit/control_plane/test_root_key_registry.py",
    "tests/unit/control_plane/test_schema_operation_lease_persistence.py",
    "tests/unit/control_plane/test_scoped_tenant_router.py",
    "tests/unit/control_plane/test_sensitive_action_service.py",
    "tests/unit/control_plane/test_sf_claim_persistence.py",
    "tests/unit/control_plane/test_sqlalchemy_route_repository.py",
    "tests/unit/control_plane/test_startup_authority.py",
    "tests/unit/control_plane/test_subscription_adjustment_service.py",
    "tests/unit/control_plane/test_subscription_models.py",
    "tests/unit/control_plane/test_subscription_projection_evaluator.py",
    "tests/unit/control_plane/test_subscription_projection_runtime.py",
    "tests/unit/control_plane/test_subscription_renewal_service.py",
    "tests/unit/control_plane/test_suspension_persistence.py",
    "tests/unit/control_plane/test_tenant_http_boundary.py",
    "tests/unit/control_plane/test_tenant_identity_http_runtime_impl.py",
    "tests/unit/control_plane/test_tenant_integration_http_runtime_impl.py",
    "tests/unit/control_plane/test_tenant_integration_service.py",
    "tests/unit/control_plane/test_tenant_integration_validation_worker.py",
    "tests/unit/control_plane/test_tenant_invitation_http_runtime.py",
    "tests/unit/control_plane/test_tenant_subscription_http_runtime.py",
    "tests/unit/control_plane/test_warehouse_http_runtime_impl.py",
    "tests/unit/control_plane/test_xianyu_job_scheduling.py",
    "tests/unit/control_plane/test_xianyu_sync_credentials.py",
    "tests/unit/tenancy/test_routed_transaction.py",
    "tests/unit/tenancy/test_sqlalchemy_identity.py",
    "tests/unit/test_default_application_enforce.py",
    "tests/unit/test_default_expand_qualification_verifier.py",
    "tests/unit/test_default_migration_phase_adapters.py",
    "tests/unit/test_relay_external_projection.py",
    "tests/unit/test_sf_waybill_worker.py",
    "tests/unit/test_xianyu_sync_http_runtime.py",
)

MIGRATION_DATABASE_TESTS = (
    "tests/integration/test_control_migrations.py",
    "tests/integration/test_control_account_mutation_migrations.py",
    "tests/integration/test_control_backup_ack_migrations.py",
    "tests/integration/test_control_backup_migrations.py",
    "tests/integration/test_control_deletion_migrations.py",
    "tests/integration/test_control_fleet_migration_migrations.py",
    "tests/integration/test_control_identity_migrations.py",
    "tests/integration/test_control_integration_migrations.py",
    "tests/integration/test_control_invitation_migrations.py",
    "tests/integration/test_control_job_migrations.py",
    "tests/integration/test_control_platform_identity_migrations.py",
    "tests/integration/test_control_provider_account_migrations.py",
    "tests/integration/test_control_provider_claim_migrations.py",
    "tests/integration/test_control_recovery_migrations.py",
    "tests/integration/test_control_redemption_migrations.py",
    "tests/integration/test_control_registration_migrations.py",
    "tests/integration/test_control_root_key_migrations.py",
    "tests/integration/test_control_schema_operation_migrations.py",
    "tests/integration/test_control_sensitive_action_migrations.py",
    "tests/integration/test_control_sensitive_security_event_migration.py",
    "tests/integration/test_control_session_login_anchor_migration.py",
    "tests/integration/test_control_sms_migrations.py",
    "tests/integration/test_control_subscription_migrations.py",
    "tests/integration/test_control_suspension_migrations.py",
    "tests/integration/test_control_tenant_route_migrations.py",
    "tests/integration/test_default_tenant_schema_qualification.py",
)

DEFAULT_DATABASE_TEST_GROUPS = (
    ISOLATED_DATABASE_TESTS,
    MIGRATION_DATABASE_TESTS,
    SHARED_DATABASE_TESTS,
)


def main(arguments: list[str] | None = None) -> None:
    selected = tuple(arguments if arguments is not None else sys.argv[1:])
    raw_url = dotenv_values(PROJECT_ROOT / ".env").get("DATABASE_URL")
    if not raw_url:
        raise SystemExit("DATABASE_URL is missing from .env")
    test_url = make_url(raw_url).set(database="inventory_management_test")
    environment = os.environ.copy()
    environment.update(
        {
            "TESTING": "true",
            "ALLOW_REAL_TEST_DATABASE": "true",
            "ALLOW_GLOBAL_DBA_TEST_ACCOUNT": "true",
            "RUN_REAL_MYSQL_CONTENTION_TESTS": "true",
            "RUN_REAL_MYSQL_MIGRATION_TESTS": "true",
            "TEST_DATABASE_URL": test_url.render_as_string(
                hide_password=False
            ),
        }
    )
    os.chdir(PROJECT_ROOT)
    if selected:
        os.execvpe(
            sys.executable,
            _pytest_command(selected),
            environment,
        )

    for test_group in DEFAULT_DATABASE_TEST_GROUPS:
        completed = subprocess.run(
            _pytest_command(test_group),
            env=environment,
            check=False,
        )
        if completed.returncode != 0:
            raise SystemExit(completed.returncode)


def _pytest_command(test_paths: tuple[str, ...]) -> list[str]:
    return [
        sys.executable,
        "-m",
        "pytest",
        "-p",
        "no:xdist",
        "-q",
        *test_paths,
    ]


if __name__ == "__main__":
    main()
