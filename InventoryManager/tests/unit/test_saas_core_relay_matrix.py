from __future__ import annotations

from types import SimpleNamespace

from tests.support import run_saas_core_relay_matrix as matrix


def test_matrix_is_version_locked_and_orders_real_database_last(monkeypatch):
    monkeypatch.setattr(
        matrix,
        "build_default_migration_bundle_evidence",
        lambda _root: SimpleNamespace(
            control_schema_head=matrix.EXPECTED_CONTROL_HEAD,
            tenant_schema_head=matrix.EXPECTED_TENANT_HEAD,
            bundle_digest=b"m" * 32,
        ),
    )
    calls = []

    def run(arguments, *, cwd, check):
        calls.append((arguments, cwd, check))
        return SimpleNamespace(returncode=0)

    assert matrix.run_matrix(include_real_database=True, runner=run) == 0
    assert calls[0][0][2] == "pytest"
    assert calls[1][0][1] == "run"
    assert calls[2][0][2] == "tests.support.run_existing_test_database"
    assert calls[-1][0][
        -len(matrix.REAL_DATABASE_SELECTORS):
    ] == matrix.REAL_DATABASE_SELECTORS
    assert all(check is False for _arguments, _cwd, check in calls)


def test_matrix_fails_fast_and_local_only_never_builds_database_command(
    monkeypatch,
):
    monkeypatch.setattr(
        matrix,
        "require_expected_migration_heads",
        lambda: "0" * 64,
    )
    calls = []

    def run(arguments, *, cwd, check):
        calls.append((arguments, cwd, check))
        return SimpleNamespace(returncode=7)

    assert matrix.run_matrix(include_real_database=False, runner=run) == 7
    assert len(calls) == 1
    assert "tests.support.run_existing_test_database" not in calls[0][0]
