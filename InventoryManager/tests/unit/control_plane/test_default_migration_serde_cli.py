from __future__ import annotations

import base64
import hashlib
import io
import json
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from inventory_control.default_migration import (
    HISTORICAL_BOUNDARY_COUNT_KEYS,
    DefaultHistoricalSnapshotBoundaryEvidence,
    DefaultSourceBaselineEvidence,
    DefaultSourceMigrationPreflightEvidence,
    DefaultTenantMigrationManifest,
    MigrationExecutionMode,
    MigrationJournal,
    MigrationPhase,
    MigrationPhaseExecutionResult,
    MigrationPhaseEvidence,
    HistoricalSnapshotDisposition,
    build_execution_plan,
    build_default_migration_bundle_evidence,
    journal_from_document,
    journal_to_document,
    manifest_from_document,
    manifest_to_document,
    migration_bundle_evidence_to_document,
    record_phase_completion,
    source_baseline_evidence_to_document,
    source_migration_preflight_to_document,
)
from inventory_control.default_migration.cli import main


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("ascii")).digest()


def _manifest() -> DefaultTenantMigrationManifest:
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="default-tenant-2026-08-22",
        tenant_uuid=UUID("00000000-0000-4000-8000-000000000201"),
        database_uuid=UUID("00000000-0000-4000-8000-000000000202"),
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID(
            "00000000-0000-4000-8000-000000000203"
        ),
        control_schema_head="202608220026",
        tenant_schema_head="20260823_shipping_contract",
        source_snapshot_digest=_digest("source"),
        implementation_identity_digest=_digest("implementation"),
        migration_bundle_digest=_digest("bundle"),
        display_name_input_commitment=_digest("keyed-display-name"),
        first_admin_phone_input_commitment=_digest("keyed-phone"),
    )


def _write_json(path, value):
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def _identity_template():
    document = manifest_to_document(_manifest())
    document.pop("display_name_input_commitment")
    document.pop("first_admin_phone_input_commitment")
    return document


def _source_baseline():
    return DefaultSourceBaselineEvidence(
        source_schema_name="inventory_management",
        baseline_migration_id="initial-baseline-v1",
        database_profile="mariadb-10.11",
        server_version="10.11.6-MariaDB-log",
        table_count=9,
        total_rows=6264,
        schema_inventory_digest=_digest("source-schema"),
        row_count_digest=_digest("source-rows"),
        source_snapshot_digest=_digest("observed-source"),
    )


def _source_baseline_identity_template():
    document = _identity_template()
    for key in (
        "source_snapshot_digest",
        "control_schema_head",
        "tenant_schema_head",
        "migration_bundle_digest",
    ):
        document.pop(key)
    return document


def _bundle_evidence():
    repository_root = Path(__file__).resolve().parents[3]
    return build_default_migration_bundle_evidence(repository_root)


def _source_preflight():
    source_baseline = _source_baseline()
    return DefaultSourceMigrationPreflightEvidence(
        source_baseline=source_baseline,
        historical_boundary=DefaultHistoricalSnapshotBoundaryEvidence(
            source_schema_name=source_baseline.source_schema_name,
            baseline_migration_id=source_baseline.baseline_migration_id,
            source_snapshot_digest=source_baseline.source_snapshot_digest,
            counts=tuple(
                (
                    key,
                    2 if key == "legacy_tracking_rows" else 0,
                )
                for key in HISTORICAL_BOUNDARY_COUNT_KEYS
            ),
            disposition=(
                HistoricalSnapshotDisposition.REQUIRES_APPROVED_NONEMPTY_ADAPTER
            ),
        ),
    )


def _write_root_key(path):
    path.write_bytes(base64.b64encode(bytes(range(32))) + b"\n")
    path.chmod(0o400)


def test_manifest_and_journal_documents_round_trip_exactly():
    manifest = _manifest()
    journal = MigrationJournal.for_manifest(manifest)
    plan = build_execution_plan(
        manifest,
        journal,
        mode=MigrationExecutionMode.APPLY,
    )
    journal = record_phase_completion(
        manifest,
        journal,
        plan=plan,
        input_state_digest=_digest("input"),
        result_state_digest=_digest("result"),
        completed_at=datetime(2026, 8, 22, tzinfo=timezone.utc),
        executor_reference="offline-test:expand",
    )

    restored_manifest = manifest_from_document(manifest_to_document(manifest))
    restored_journal = journal_from_document(journal_to_document(journal))

    assert restored_manifest == manifest
    assert restored_journal == journal


def test_create_manifest_reads_controlled_identity_files_without_echo(tmp_path):
    template_path = tmp_path / "template.json"
    display_name_path = tmp_path / "display-name.txt"
    phone_path = tmp_path / "admin-phone.txt"
    root_key_path = tmp_path / "root-key-v7.b64"
    _write_json(template_path, _identity_template())
    display_name_path.write_text("光影 租界\n", encoding="utf-8")
    phone_path.write_text("138-0013-8000\n", encoding="utf-8")
    _write_root_key(root_key_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "create-manifest",
            "--template",
            str(template_path),
            "--root-key-file",
            str(root_key_path),
            "--root-key-version",
            "7",
            "--display-name-file",
            str(display_name_path),
            "--first-admin-phone-file",
            str(phone_path),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    rendered = stdout.getvalue()
    assert "光影" not in rendered
    assert "13800138000" not in rendered
    result = json.loads(rendered)
    created = manifest_from_document(result["manifest"])
    assert created.tenant_uuid == _manifest().tenant_uuid
    assert created.display_name_input_commitment != b"\x00" * 32
    assert result["identity_inputs"] == {
        "commitment_root_key_version": 7,
        "display_name_bound": True,
        "first_admin_phone_bound": True,
        "input_version": 1,
    }


def test_create_manifest_binds_versioned_source_evidence_without_manual_digest(
    tmp_path,
    monkeypatch,
):
    template_path = tmp_path / "template.json"
    source_path = tmp_path / "source-baseline.json"
    display_name_path = tmp_path / "display-name.txt"
    phone_path = tmp_path / "admin-phone.txt"
    root_key_path = tmp_path / "root-key-v7.b64"
    bundle_path = tmp_path / "migration-bundle.json"
    _write_json(template_path, _source_baseline_identity_template())
    _write_json(
        source_path,
        source_baseline_evidence_to_document(_source_baseline()),
    )
    display_name_path.write_text("光影 租界\n", encoding="utf-8")
    phone_path.write_text("138-0013-8000\n", encoding="utf-8")
    _write_root_key(root_key_path)
    bundle = _bundle_evidence()
    _write_json(bundle_path, migration_bundle_evidence_to_document(bundle))
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql://implicit-secret:must-not-be-read@production/ignored",
    )

    rendered = []
    for _ in range(2):
        stdout = io.StringIO()
        stderr = io.StringIO()
        code = main(
            [
                "create-manifest-from-source-baseline",
                "--template",
                str(template_path),
                "--source-baseline",
                str(source_path),
                "--migration-bundle-evidence",
                str(bundle_path),
                "--root-key-file",
                str(root_key_path),
                "--root-key-version",
                "7",
                "--display-name-file",
                str(display_name_path),
                "--first-admin-phone-file",
                str(phone_path),
            ],
            stdout=stdout,
            stderr=stderr,
        )
        assert code == 0
        assert stderr.getvalue() == ""
        rendered.append(stdout.getvalue())

    assert rendered[0] == rendered[1]
    assert "implicit-secret" not in rendered[0]
    assert "光影" not in rendered[0]
    assert "13800138000" not in rendered[0]
    result = json.loads(rendered[0])
    manifest = manifest_from_document(result["manifest"])
    assert manifest.source_snapshot_digest == (
        _source_baseline().source_snapshot_digest
    )
    assert manifest.migration_bundle_digest == bundle.bundle_digest
    assert manifest.control_schema_head == bundle.control_schema_head
    assert manifest.tenant_schema_head == bundle.tenant_schema_head
    assert result["source_baseline"]["evidence_digest"] == (
        _source_baseline().digest.hex()
    )


def test_create_manifest_rejects_source_template_mismatch_before_output(
    tmp_path,
):
    template = _source_baseline_identity_template()
    template["source_schema_name"] = "another_schema"
    template_path = tmp_path / "template.json"
    source_path = tmp_path / "source-baseline.json"
    display_name_path = tmp_path / "display-name.txt"
    phone_path = tmp_path / "admin-phone.txt"
    root_key_path = tmp_path / "root-key-v7.b64"
    bundle_path = tmp_path / "migration-bundle.json"
    _write_json(template_path, template)
    _write_json(
        source_path,
        source_baseline_evidence_to_document(_source_baseline()),
    )
    display_name_path.write_text("光影 租界\n", encoding="utf-8")
    phone_path.write_text("138-0013-8000\n", encoding="utf-8")
    _write_root_key(root_key_path)
    _write_json(
        bundle_path,
        migration_bundle_evidence_to_document(_bundle_evidence()),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "create-manifest-from-source-baseline",
            "--template",
            str(template_path),
            "--source-baseline",
            str(source_path),
            "--migration-bundle-evidence",
            str(bundle_path),
            "--root-key-file",
            str(root_key_path),
            "--root-key-version",
            "7",
            "--display-name-file",
            str(display_name_path),
            "--first-admin-phone-file",
            str(phone_path),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "error": "MIGRATION_DOCUMENT_REJECTED",
        "ok": False,
    }


def test_create_manifest_from_preflight_preserves_nonempty_disposition(
    tmp_path,
):
    template_path = tmp_path / "template.json"
    preflight_path = tmp_path / "source-preflight.json"
    display_name_path = tmp_path / "display-name.txt"
    phone_path = tmp_path / "admin-phone.txt"
    root_key_path = tmp_path / "root-key-v7.b64"
    bundle_path = tmp_path / "migration-bundle.json"
    _write_json(template_path, _source_baseline_identity_template())
    _write_json(
        preflight_path,
        source_migration_preflight_to_document(_source_preflight()),
    )
    display_name_path.write_text("光影 租界\n", encoding="utf-8")
    phone_path.write_text("138-0013-8000\n", encoding="utf-8")
    _write_root_key(root_key_path)
    _write_json(
        bundle_path,
        migration_bundle_evidence_to_document(_bundle_evidence()),
    )
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "create-manifest-from-source-preflight",
            "--template",
            str(template_path),
            "--source-preflight",
            str(preflight_path),
            "--migration-bundle-evidence",
            str(bundle_path),
            "--root-key-file",
            str(root_key_path),
            "--root-key-version",
            "7",
            "--display-name-file",
            str(display_name_path),
            "--first-admin-phone-file",
            str(phone_path),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    result = json.loads(stdout.getvalue())
    assert result["source_preflight"]["disposition"] == (
        "requires_approved_nonempty_adapter"
    )
    manifest = manifest_from_document(result["manifest"])
    assert manifest.source_snapshot_digest == (
        _source_preflight().source_baseline.source_snapshot_digest
    )


def test_create_manifest_rejects_bad_identity_without_echo(tmp_path):
    template_path = tmp_path / "template.json"
    display_name_path = tmp_path / "display-name.txt"
    phone_path = tmp_path / "admin-phone.txt"
    root_key_path = tmp_path / "root-key-v7.b64"
    _write_json(template_path, _identity_template())
    display_name_path.write_text("默认租户\n", encoding="utf-8")
    phone_path.write_text("+852-secret-phone\n", encoding="utf-8")
    _write_root_key(root_key_path)
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        [
            "create-manifest",
            "--template",
            str(template_path),
            "--root-key-file",
            str(root_key_path),
            "--root-key-version",
            "7",
            "--display-name-file",
            str(display_name_path),
            "--first-admin-phone-file",
            str(phone_path),
        ],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 2
    assert stdout.getvalue() == ""
    assert "默认租户" not in stderr.getvalue()
    assert "+852-secret-phone" not in stderr.getvalue()
    assert json.loads(stderr.getvalue()) == {
        "error": "MIGRATION_DOCUMENT_REJECTED",
        "ok": False,
    }


def test_validate_cli_emits_only_redacted_manifest(tmp_path):
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    _write_json(manifest_path, manifest_to_document(manifest))
    stdout = io.StringIO()
    stderr = io.StringIO()

    code = main(
        ["validate-manifest", "--manifest", str(manifest_path)],
        stdout=stdout,
        stderr=stderr,
    )

    assert code == 0
    assert stderr.getvalue() == ""
    rendered = stdout.getvalue()
    assert manifest.display_name_input_commitment.hex() not in rendered
    assert manifest.first_admin_phone_input_commitment.hex() not in rendered
    assert json.loads(rendered)["manifest"]["sensitive_inputs_bound"] is True


def test_plan_cli_is_read_only_in_dry_run_and_lists_stop_conditions(tmp_path):
    manifest = _manifest()
    journal = MigrationJournal.for_manifest(manifest)
    manifest_path = tmp_path / "manifest.json"
    journal_path = tmp_path / "journal.json"
    _write_json(manifest_path, manifest_to_document(manifest))
    _write_json(journal_path, journal_to_document(journal))
    stdout = io.StringIO()

    code = main(
        [
            "plan",
            "--manifest",
            str(manifest_path),
            "--journal",
            str(journal_path),
            "--mode",
            "dry_run",
        ],
        stdout=stdout,
        stderr=io.StringIO(),
    )

    output = json.loads(stdout.getvalue())
    assert code == 0
    assert output["phase"] == "expand"
    assert output["mutations_allowed"] is False
    assert output["provider_or_print_side_effects_allowed"] is False
    assert any("schema" in item for item in output["stop_conditions"])


def test_cli_rejects_unknown_fields_and_duplicate_json_keys_without_echo(tmp_path):
    manifest = _manifest()
    document = manifest_to_document(manifest)
    document["plaintext_phone"] = "+8613800000000"
    unknown_path = tmp_path / "unknown.json"
    _write_json(unknown_path, document)
    stderr = io.StringIO()

    assert main(
        ["validate-manifest", "--manifest", str(unknown_path)],
        stdout=io.StringIO(),
        stderr=stderr,
    ) == 2
    assert "+8613800000000" not in stderr.getvalue()
    assert json.loads(stderr.getvalue()) == {
        "error": "MIGRATION_DOCUMENT_REJECTED",
        "ok": False,
    }

    duplicate_path = tmp_path / "duplicate.json"
    duplicate_path.write_text(
        '{"manifest_version":1,"manifest_version":1}',
        encoding="utf-8",
    )
    assert main(
        ["validate-manifest", "--manifest", str(duplicate_path)],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 2


class _ExpandExecutor:
    def __init__(self):
        self.invocations = []

    def execute(self, invocation):
        self.invocations.append(invocation)
        return MigrationPhaseExecutionResult(
            phase=MigrationPhase.EXPAND,
            manifest_digest=invocation.manifest.digest,
            input_state_digest=_digest("expand-input"),
            result_state_digest=_digest("expand-result"),
            executor_reference="isolated-cli-test:expand",
        )


class _LeakyFailingExpandExecutor:
    def execute(self, invocation):
        raise RuntimeError(
            "mysql+pymysql://migration:secret@production/inventory_management"
        )


def test_run_phase_cli_dry_run_is_read_only_and_apply_requires_composition(
    tmp_path,
):
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    journal_path = tmp_path / "journal.json"
    _write_json(manifest_path, manifest_to_document(manifest))
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
    before = journal_path.read_bytes()
    stdout = io.StringIO()

    assert main(
        [
            "run-phase",
            "--manifest",
            str(manifest_path),
            "--journal",
            str(journal_path),
            "--phase",
            "expand",
            "--mode",
            "dry_run",
        ],
        stdout=stdout,
        stderr=io.StringIO(),
    ) == 0
    output = json.loads(stdout.getvalue())
    assert output["outcome"] == "planned"
    assert output["mutations_allowed"] is False
    assert output["provider_or_print_side_effects_allowed"] is False
    assert output["prerequisites"]
    assert output["completion_conditions"]
    assert output["stop_conditions"]
    assert journal_path.read_bytes() == before

    stderr = io.StringIO()
    assert main(
        [
            "run-phase",
            "--manifest",
            str(manifest_path),
            "--journal",
            str(journal_path),
            "--phase",
            "expand",
            "--mode",
            "apply",
        ],
        stdout=io.StringIO(),
        stderr=stderr,
    ) == 2
    assert json.loads(stderr.getvalue()) == {
        "error": "MIGRATION_EXECUTION_REJECTED",
        "ok": False,
    }
    assert journal_path.read_bytes() == before


def test_run_phase_cli_redacts_unexpected_executor_failure(tmp_path):
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    journal_path = tmp_path / "journal.json"
    _write_json(manifest_path, manifest_to_document(manifest))
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
    before = journal_path.read_bytes()
    stdout = io.StringIO()
    stderr = io.StringIO()

    assert main(
        [
            "run-phase",
            "--manifest",
            str(manifest_path),
            "--journal",
            str(journal_path),
            "--phase",
            "expand",
            "--mode",
            "apply",
        ],
        stdout=stdout,
        stderr=stderr,
        phase_executors={
            MigrationPhase.EXPAND: _LeakyFailingExpandExecutor()
        },
    ) == 2
    assert stdout.getvalue() == ""
    assert json.loads(stderr.getvalue()) == {
        "error": "MIGRATION_EXECUTION_REJECTED",
        "ok": False,
    }
    assert "secret" not in stderr.getvalue()
    assert "production" not in stderr.getvalue()
    assert journal_path.read_bytes() == before


def test_run_phase_cli_uses_explicit_executor_and_replays_durable_evidence(
    tmp_path,
):
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    journal_path = tmp_path / "journal.json"
    _write_json(manifest_path, manifest_to_document(manifest))
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
    executor = _ExpandExecutor()
    args = [
        "run-phase",
        "--manifest",
        str(manifest_path),
        "--journal",
        str(journal_path),
        "--phase",
        "expand",
        "--mode",
        "apply",
    ]
    stdout = io.StringIO()

    assert main(
        args,
        stdout=stdout,
        stderr=io.StringIO(),
        phase_executors={MigrationPhase.EXPAND: executor},
        clock=lambda: datetime(2026, 8, 22, tzinfo=timezone.utc),
    ) == 0
    completed = json.loads(stdout.getvalue())
    replay_stdout = io.StringIO()
    assert main(
        args,
        stdout=replay_stdout,
        stderr=io.StringIO(),
    ) == 0
    replayed = json.loads(replay_stdout.getvalue())

    assert completed["outcome"] == "completed"
    assert completed["completion_evidence"]["executor_reference"] == (
        "isolated-cli-test:expand"
    )
    assert replayed["outcome"] == "replayed"
    assert replayed["completion_evidence"] == completed["completion_evidence"]
    assert len(executor.invocations) == 1


def test_authoritative_write_marker_is_explicit_idempotent_and_blocks_rollback(
    tmp_path,
):
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    journal_path = tmp_path / "journal.json"
    completed_at = datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc)
    journal = MigrationJournal(
        manifest_digest=manifest.digest,
        completed=tuple(
            MigrationPhaseEvidence(
                phase=phase,
                manifest_digest=manifest.digest,
                input_state_digest=_digest(f"{phase.value}:input"),
                result_state_digest=_digest(f"{phase.value}:result"),
                completed_at=completed_at,
                executor_reference=f"isolated-cli-test:{phase.value}",
            )
            for phase in (
                MigrationPhase.EXPAND,
                MigrationPhase.BACKFILL_VERIFY,
                MigrationPhase.APPLICATION_ENFORCE,
                MigrationPhase.DATABASE_JOBS_ENFORCE,
            )
        ),
    )
    _write_json(manifest_path, manifest_to_document(manifest))
    _write_json(journal_path, journal_to_document(journal))
    args = [
        "mark-tenant-aware-writes-authoritative",
        "--manifest",
        str(manifest_path),
        "--journal",
        str(journal_path),
        "--enabled-at",
        "2026-08-22T01:00:01+00:00",
    ]
    first_stdout = io.StringIO()

    assert main(args, stdout=first_stdout, stderr=io.StringIO()) == 0
    first_bytes = journal_path.read_bytes()
    replay_stdout = io.StringIO()
    assert main(args, stdout=replay_stdout, stderr=io.StringIO()) == 0

    first = json.loads(first_stdout.getvalue())
    assert first["tenant_aware_writes_authoritative"] is True
    assert first["legacy_rollback_allowed"] is False
    assert journal_path.read_bytes() == first_bytes
    assert json.loads(replay_stdout.getvalue()) == first
    assert main(
        [
            "rollback-before-authoritative-write",
            "--manifest",
            str(manifest_path),
            "--journal",
            str(journal_path),
        ],
        stdout=io.StringIO(),
        stderr=io.StringIO(),
    ) == 2


def test_authoritative_write_marker_rejects_naive_or_non_utc_time(tmp_path):
    manifest = _manifest()
    manifest_path = tmp_path / "manifest.json"
    journal_path = tmp_path / "journal.json"
    _write_json(manifest_path, manifest_to_document(manifest))
    _write_json(
        journal_path,
        journal_to_document(MigrationJournal.for_manifest(manifest)),
    )

    for invalid in ("2026-08-22T01:00:01", "2026-08-22T09:00:01+08:00"):
        assert main(
            [
                "mark-tenant-aware-writes-authoritative",
                "--manifest",
                str(manifest_path),
                "--journal",
                str(journal_path),
                "--enabled-at",
                invalid,
            ],
            stdout=io.StringIO(),
            stderr=io.StringIO(),
        ) == 2
