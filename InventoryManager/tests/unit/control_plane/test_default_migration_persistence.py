from __future__ import annotations

import hashlib
import io
import json
import stat
from dataclasses import replace
from datetime import datetime, timezone
from uuid import UUID

import pytest

from inventory_control.default_migration import (
    DefaultTenantMigrationManifest,
    MigrationExecutionMode,
    MigrationJournal,
    MigrationJournalFileStore,
    MigrationJournalPersistenceError,
    build_execution_plan,
    manifest_to_document,
    record_phase_completion,
)
from inventory_control.default_migration.cli import main


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest(*, bundle: str = "bundle") -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-tenant-persistent-v1",
        tenant_uuid=UUID("00000000-0000-4000-8000-000000000401"),
        database_uuid=UUID("00000000-0000-4000-8000-000000000402"),
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID(
            "00000000-0000-4000-8000-000000000403"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest(bundle),
        display_name_input_commitment=_digest("keyed-name"),
        first_admin_phone_input_commitment=_digest("keyed-phone"),
    )


def _write_json(path, value) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _complete_expand(
    manifest: DefaultTenantMigrationManifest,
    journal: MigrationJournal,
    *,
    result: str = "expand-result",
) -> MigrationJournal:
    plan = build_execution_plan(
        manifest,
        journal,
        mode=MigrationExecutionMode.APPLY,
    )
    return record_phase_completion(
        manifest,
        journal,
        plan=plan,
        input_state_digest=_digest("expand-input"),
        result_state_digest=_digest(result),
        completed_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        executor_reference="offline-test:expand",
    )


def test_cli_initializes_private_journal_and_exact_replay_is_a_noop(tmp_path):
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    journal_path = tmp_path / "journal.json"
    _write_json(manifest_path, manifest_to_document(manifest))

    first_stdout = io.StringIO()
    assert main(
        [
            "initialize-journal",
            "--manifest",
            str(manifest_path),
            "--journal",
            str(journal_path),
        ],
        stdout=first_stdout,
        stderr=io.StringIO(),
    ) == 0
    first_bytes = journal_path.read_bytes()
    first_stat = journal_path.stat()

    second_stdout = io.StringIO()
    assert main(
        [
            "initialize-journal",
            "--manifest",
            str(manifest_path),
            "--journal",
            str(journal_path),
        ],
        stdout=second_stdout,
        stderr=io.StringIO(),
    ) == 0

    assert journal_path.read_bytes() == first_bytes
    assert stat.S_IMODE(first_stat.st_mode) == 0o600
    assert json.loads(first_stdout.getvalue()) == json.loads(
        second_stdout.getvalue()
    )
    assert json.loads(first_stdout.getvalue())["next_phase"] == "expand"


def test_cli_rejects_changed_manifest_without_overwriting_journal(tmp_path):
    original = _manifest()
    changed = _manifest(bundle="changed-bundle")
    manifest_path = tmp_path / "manifest.json"
    journal_path = tmp_path / "journal.json"
    _write_json(manifest_path, manifest_to_document(original))
    assert main(
        [
            "initialize-journal",
            "--manifest",
            str(manifest_path),
            "--journal",
            str(journal_path),
        ],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 0
    original_bytes = journal_path.read_bytes()
    _write_json(manifest_path, manifest_to_document(changed))
    stderr = io.StringIO()

    assert main(
        [
            "initialize-journal",
            "--manifest",
            str(manifest_path),
            "--journal",
            str(journal_path),
        ],
        stdout=io.StringIO(),
        stderr=stderr,
    ) == 2

    assert journal_path.read_bytes() == original_bytes
    assert json.loads(stderr.getvalue()) == {
        "error": "MIGRATION_DOCUMENT_REJECTED",
        "ok": False,
    }


def test_compare_and_swap_is_single_step_and_response_loss_idempotent(tmp_path):
    manifest = _manifest()
    store = MigrationJournalFileStore(tmp_path / "journal.json")
    empty = store.initialize(manifest)
    expanded = _complete_expand(manifest, empty)

    assert store.compare_and_swap(
        manifest,
        expected=empty,
        replacement=expanded,
    ) == expanded
    assert store.load() == expanded
    assert store.compare_and_swap(
        manifest,
        expected=empty,
        replacement=expanded,
    ) == expanded


def test_stale_or_history_rewriting_replacement_never_changes_file(tmp_path):
    manifest = _manifest()
    store = MigrationJournalFileStore(tmp_path / "journal.json")
    empty = store.initialize(manifest)
    expanded = _complete_expand(manifest, empty)
    store.compare_and_swap(manifest, expected=empty, replacement=expanded)
    persisted = store.path.read_bytes()

    divergent = _complete_expand(manifest, empty, result="different-result")
    with pytest.raises(MigrationJournalPersistenceError, match="stale"):
        store.compare_and_swap(
            manifest,
            expected=empty,
            replacement=divergent,
        )

    rewritten = replace(
        expanded,
        completed=(
            replace(
                expanded.completed[0],
                result_state_digest=_digest("rewritten-history"),
            ),
        ),
    )
    with pytest.raises(MigrationJournalPersistenceError, match="one immutable"):
        store.compare_and_swap(
            manifest,
            expected=expanded,
            replacement=rewritten,
        )
    assert store.path.read_bytes() == persisted


def test_strict_load_rejects_duplicate_fields_and_final_symlink(tmp_path):
    manifest = _manifest()
    path = tmp_path / "journal.json"
    store = MigrationJournalFileStore(path)
    store.initialize(manifest)
    path.write_text(
        '{"journal_version":1,"journal_version":1}',
        encoding="utf-8",
    )
    with pytest.raises(MigrationJournalPersistenceError, match="invalid"):
        store.load()

    target = tmp_path / "other.json"
    target.write_text("{}", encoding="utf-8")
    path.unlink()
    path.symlink_to(target)
    with pytest.raises(MigrationJournalPersistenceError, match="opened"):
        store.load()
