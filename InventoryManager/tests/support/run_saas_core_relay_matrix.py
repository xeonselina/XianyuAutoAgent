"""Run the version-locked SaaS Core rental/relay acceptance matrix.

The matrix reuses focused tests that already own their domain fixtures.  Its
default mode runs local backend and frontend checks first, then delegates the
database contention slice to the single approved ``inventory_management_test``
launcher.  It never embeds a DSN and never calls a provider or printer.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import subprocess
import sys
from typing import Sequence

from inventory_control.default_migration import (
    build_default_migration_bundle_evidence,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
MATRIX_REVISION = "saas-core-relay-matrix.v1"
EXPECTED_CONTROL_HEAD = "202608230038"
EXPECTED_TENANT_HEAD = "20260824_legacy_history"

LOCAL_BACKEND_SELECTORS = (
    "tests/unit/scheduling/test_overlap_policy.py::"
    "test_zero_day_logistics_preserves_one_day_operational_buffers",
    "tests/unit/test_shipping_batch_http_runtime.py",
    "tests/unit/test_security_fail_closed.py::"
    "test_provider_test_routes_are_never_registered",
)

FRONTEND_SELECTORS = (
    "tests/unit/components/BookingDialogDeviceModel.spec.ts",
    "tests/unit/composables/useRentalBooking.spec.ts",
    "tests/unit/components/RentalSaveSuccessEvents.spec.ts",
    "tests/unit/composables/usePendingReturns.spec.ts",
    "tests/unit/stores/gantt.spec.ts",
)

REAL_DATABASE_SELECTORS = (
    "tests/unit/control_plane/test_rental_http_runtime_impl.py::"
    "test_booking_availability_stays_at_five_sql_for_100_devices_and_31_days",
    "tests/unit/control_plane/test_gantt_http_runtime_impl.py::"
    "test_normalized_gantt_view_budget_on_inventory_management_test",
    "tests/unit/test_warehouse_service.py",
    "tests/unit/test_accessory_relay_chain_service.py",
    "tests/unit/test_relay_external_projection.py::"
    "test_fake_sf_worker_success_reaches_direct_relay_handoff",
    "tests/integration/test_warehouse_mysql_contention.py",
    "tests/integration/test_accessory_mysql_contention.py",
    "tests/integration/test_gantt_mysql_contention.py",
    "tests/unit/test_sf_batch_shipping_http_runtime_impl.py",
)


@dataclass(frozen=True, slots=True)
class MatrixCommand:
    name: str
    working_directory: Path
    arguments: tuple[str, ...]


def build_matrix_commands(
    *,
    include_real_database: bool,
) -> tuple[MatrixCommand, ...]:
    commands = [
        MatrixCommand(
            name="local-backend",
            working_directory=PROJECT_ROOT,
            arguments=(
                sys.executable,
                "-m",
                "pytest",
                "-q",
                *LOCAL_BACKEND_SELECTORS,
            ),
        ),
        MatrixCommand(
            name="frontend-http-fanout",
            working_directory=PROJECT_ROOT / "frontend",
            arguments=(
                str(PROJECT_ROOT / "frontend/node_modules/.bin/vitest"),
                "run",
                *FRONTEND_SELECTORS,
            ),
        ),
    ]
    if include_real_database:
        commands.append(
            MatrixCommand(
                name="inventory-management-test-contention",
                working_directory=PROJECT_ROOT,
                arguments=(
                    sys.executable,
                    "-m",
                    "tests.support.run_existing_test_database",
                    *REAL_DATABASE_SELECTORS,
                ),
            )
        )
    return tuple(commands)


def require_expected_migration_heads() -> str:
    evidence = build_default_migration_bundle_evidence(PROJECT_ROOT)
    if (
        evidence.control_schema_head != EXPECTED_CONTROL_HEAD
        or evidence.tenant_schema_head != EXPECTED_TENANT_HEAD
    ):
        raise RuntimeError(
            "relay matrix migration heads are stale: "
            f"expected {EXPECTED_CONTROL_HEAD}/{EXPECTED_TENANT_HEAD}, "
            f"observed {evidence.control_schema_head}/"
            f"{evidence.tenant_schema_head}"
        )
    return evidence.bundle_digest.hex()


def run_matrix(
    *,
    include_real_database: bool,
    runner=subprocess.run,
) -> int:
    bundle_digest = require_expected_migration_heads()
    print(
        f"[{MATRIX_REVISION}] bundle={bundle_digest} "
        f"real_database={str(include_real_database).lower()}",
        flush=True,
    )
    for command in build_matrix_commands(
        include_real_database=include_real_database
    ):
        print(f"[{MATRIX_REVISION}] running {command.name}", flush=True)
        completed = runner(
            command.arguments,
            cwd=command.working_directory,
            check=False,
        )
        if completed.returncode != 0:
            print(
                f"[{MATRIX_REVISION}] failed {command.name} "
                f"exit={completed.returncode}",
                flush=True,
            )
            return completed.returncode
    print(f"[{MATRIX_REVISION}] passed", flush=True)
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the version-locked SaaS Core relay matrix."
    )
    parser.add_argument(
        "--local-only",
        action="store_true",
        help="Run backend/frontend checks without the real database slice.",
    )
    return parser


def main(arguments: Sequence[str] | None = None) -> int:
    options = _parser().parse_args(arguments)
    return run_matrix(include_real_database=not options.local_only)


if __name__ == "__main__":
    raise SystemExit(main())
