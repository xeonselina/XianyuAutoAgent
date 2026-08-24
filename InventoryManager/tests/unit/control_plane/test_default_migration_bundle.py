from __future__ import annotations

import io
import json
import shutil
from pathlib import Path
from uuid import UUID

import pytest

from inventory_control.default_migration import (
    DefaultTenantMigrationManifest,
    MigrationBundleContentError,
    MigrationBundleMismatchError,
    build_default_migration_bundle_evidence,
    migration_bundle_evidence_from_document,
    migration_bundle_evidence_to_document,
    manifest_to_document,
)
from inventory_control.default_migration.cli import main


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]


def _manifest(evidence):
    return DefaultTenantMigrationManifest(
        migration_idempotency_key="bundle-evidence-test",
        tenant_uuid=UUID("11111111-1111-4111-8111-111111111111"),
        database_uuid=UUID("22222222-2222-4222-8222-222222222222"),
        source_schema_name="inventory_management_test",
        baseline_migration_id="initial-baseline-v1",
        core_plan_revision_uuid=UUID(
            "33333333-3333-4333-8333-333333333333"
        ),
        control_schema_head=evidence.control_schema_head,
        tenant_schema_head=evidence.tenant_schema_head,
        source_snapshot_digest=b"s" * 32,
        implementation_identity_digest=b"i" * 32,
        migration_bundle_digest=evidence.bundle_digest,
        display_name_input_commitment=b"d" * 32,
        first_admin_phone_input_commitment=b"p" * 32,
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )


def test_bundle_is_canonical_round_trippable_and_manifest_bound():
    first = build_default_migration_bundle_evidence(REPOSITORY_ROOT)
    second = build_default_migration_bundle_evidence(REPOSITORY_ROOT)

    assert first == second
    assert first.control_schema_head == "202608230038"
    assert first.tenant_schema_head == "20260823_shipping_contract"
    assert len(first.files) >= 180
    assert tuple(item.relative_path for item in first.files) == tuple(
        sorted(item.relative_path for item in first.files)
    )
    assert any(
        "添加验货记录表和扩展租赁表" in item.relative_path
        for item in first.files
    )
    assert migration_bundle_evidence_from_document(
        migration_bundle_evidence_to_document(first)
    ) == first
    first.require_manifest(_manifest(first))

    mismatched = _manifest(first)
    object.__setattr__(mismatched, "migration_bundle_digest", b"x" * 32)
    with pytest.raises(MigrationBundleMismatchError):
        first.require_manifest(mismatched)


def test_bundle_digest_changes_when_one_fixed_file_changes(tmp_path: Path):
    original = build_default_migration_bundle_evidence(REPOSITORY_ROOT)
    copied_root = tmp_path / "repository"
    copied_root.mkdir()
    for item in original.files:
        source = REPOSITORY_ROOT / item.relative_path
        target = copied_root / item.relative_path
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)

    copied = build_default_migration_bundle_evidence(copied_root)
    assert copied == original

    requirements = copied_root / "requirements.txt"
    requirements.write_bytes(requirements.read_bytes() + b"\n# bundle drift\n")
    changed = build_default_migration_bundle_evidence(copied_root)

    assert changed.bundle_digest != original.bundle_digest
    assert changed.control_schema_head == original.control_schema_head
    assert changed.tenant_schema_head == original.tenant_schema_head
    assert len(changed.files) == len(original.files)


def test_bundle_document_rejects_unknown_or_tampered_fields():
    evidence = build_default_migration_bundle_evidence(REPOSITORY_ROOT)
    document = migration_bundle_evidence_to_document(evidence)
    document["unexpected"] = True
    with pytest.raises(MigrationBundleContentError):
        migration_bundle_evidence_from_document(document)

    document = migration_bundle_evidence_to_document(evidence)
    document["files"][0]["sha256_digest"] = "0" * 64
    with pytest.raises(MigrationBundleContentError):
        migration_bundle_evidence_from_document(document)


def test_cli_creates_and_validates_current_bundle_without_external_io(
    tmp_path: Path,
    monkeypatch,
):
    monkeypatch.setenv(
        "DATABASE_URL",
        "mysql://secret:must-not-be-read@production/ignored",
    )
    stdout = io.StringIO()
    stderr = io.StringIO()
    code = main(
        [
            "create-migration-bundle-evidence",
            "--repository-root",
            str(REPOSITORY_ROOT),
        ],
        stdout=stdout,
        stderr=stderr,
    )
    assert code == 0
    assert stderr.getvalue() == ""
    assert "must-not-be-read" not in stdout.getvalue()
    result = json.loads(stdout.getvalue())
    evidence = migration_bundle_evidence_from_document(
        result["migration_bundle"]
    )

    manifest_path = tmp_path / "manifest.json"
    evidence_path = tmp_path / "bundle.json"
    _write_json(manifest_path, manifest_to_document(_manifest(evidence)))
    _write_json(evidence_path, result["migration_bundle"])
    validated = io.StringIO()
    code = main(
        [
            "validate-migration-bundle",
            "--manifest",
            str(manifest_path),
            "--migration-bundle-evidence",
            str(evidence_path),
            "--repository-root",
            str(REPOSITORY_ROOT),
        ],
        stdout=validated,
        stderr=io.StringIO(),
    )
    assert code == 0
    assert json.loads(validated.getvalue())["migration_bundle"] == dict(
        evidence.safe_summary()
    )
