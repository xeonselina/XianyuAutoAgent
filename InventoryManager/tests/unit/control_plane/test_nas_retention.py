from __future__ import annotations

import hashlib
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from inventory_control.backups import (
    NasRetentionError,
    apply_nas_retention_plan,
    encode_manifest_json,
)
from inventory_control.backups.domain import (
    BackupManifest,
    DatabaseKind,
    DatabaseSnapshot,
    RecoveryMarkerSnapshot,
    RetentionPlan,
)


UTC = timezone.utc
BASE = datetime(2026, 8, 22, 8, 0, tzinfo=UTC)


def _id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"inventory-manager-nas-retention/{label}")


def _digest(value: bytes | str) -> bytes:
    if isinstance(value, str):
        value = value.encode("ascii")
    return hashlib.sha256(value).digest()


def _manifest(label: str, *, content: bytes, offset: int) -> BackupManifest:
    artifact_id = _id(f"artifact/{label}")
    return BackupManifest(
        artifact_id=artifact_id,
        attempt_id=_id(f"attempt/{label}"),
        published_name=f"backup-{artifact_id}.sql.gz",
        snapshot_at_utc=BASE + timedelta(hours=offset),
        completed_at_utc=BASE + timedelta(hours=offset, minutes=1),
        artifact_sha256=_digest(content),
        size_bytes=len(content),
        databases=(
            DatabaseSnapshot(
                database_id=_id("control"),
                kind=DatabaseKind.CONTROL,
                schema_generation=26,
                schema_sha256=_digest("control-schema"),
                required_root_key_versions=(1,),
            ),
            DatabaseSnapshot(
                database_id=_id("tenant"),
                kind=DatabaseKind.TENANT,
                schema_generation=12,
                schema_sha256=_digest("tenant-schema"),
                required_root_key_versions=(1,),
            ),
        ),
        root_key_versions=(1,),
        recovery_marker=RecoveryMarkerSnapshot(
            installation_id=_id("installation"),
            recovery_run_id=_id("recovery-run"),
            marker_generation=3,
            marker_sha256=_digest("marker"),
        ),
    )


def _write_pair(root: Path, manifest: BackupManifest, content: bytes) -> None:
    (root / manifest.published_name).write_bytes(content)
    (root / f"{manifest.published_name}.manifest.json").write_bytes(
        encode_manifest_json(manifest)
    )


def _plan(
    *,
    trigger: UUID,
    retained: tuple[UUID, ...] | None = None,
    cleanup: tuple[UUID, ...] = (),
) -> RetentionPlan:
    retained = retained or (trigger,)
    return RetentionPlan(
        hourly_artifact_ids=retained,
        daily_artifact_ids=(),
        monthly_artifact_ids=(),
        retained_artifact_ids=retained,
        cleanup_candidate_ids=cleanup,
        triggered_by_artifact_id=trigger,
    )


@pytest.fixture
def root(tmp_path: Path) -> Path:
    tmp_path.chmod(0o700)
    return tmp_path


def _assert_code(code: str, call) -> None:
    with pytest.raises(NasRetentionError) as exc_info:
        call()
    assert exc_info.value.code == code
    assert str(exc_info.value) == code


def test_verified_trigger_allows_exact_candidate_pair_cleanup(root: Path):
    old_content = b"verified old backup"
    new_content = b"verified new backup"
    old = _manifest("old", content=old_content, offset=0)
    new = _manifest("new", content=new_content, offset=1)
    _write_pair(root, old, old_content)
    _write_pair(root, new, new_content)

    result = apply_nas_retention_plan(
        root=root,
        plan=_plan(trigger=new.artifact_id, cleanup=(old.artifact_id,)),
    )

    assert result.triggered_by_artifact_id == new.artifact_id
    assert result.deleted_artifact_ids == (old.artifact_id,)
    assert result.already_absent_artifact_ids == ()
    assert not (root / old.published_name).exists()
    assert not (root / f"{old.published_name}.manifest.json").exists()
    assert (root / new.published_name).read_bytes() == new_content
    assert (root / f"{new.published_name}.manifest.json").exists()
    assert not (root / ".nas-pull.lock").exists()


def test_cleanup_replay_is_idempotent_and_removes_valid_manifest_orphan(root: Path):
    old_content = b"old"
    new_content = b"new"
    old = _manifest("orphan-old", content=old_content, offset=0)
    new = _manifest("orphan-new", content=new_content, offset=1)
    _write_pair(root, old, old_content)
    _write_pair(root, new, new_content)
    (root / old.published_name).unlink()
    plan = _plan(trigger=new.artifact_id, cleanup=(old.artifact_id,))

    first = apply_nas_retention_plan(root=root, plan=plan)
    replay = apply_nas_retention_plan(root=root, plan=plan)

    assert first.deleted_artifact_ids == (old.artifact_id,)
    assert replay.deleted_artifact_ids == ()
    assert replay.already_absent_artifact_ids == (old.artifact_id,)


def test_invalid_or_unverified_trigger_never_cleans_candidates(root: Path):
    old_content = b"old"
    new_content = b"new"
    old = _manifest("trigger-old", content=old_content, offset=0)
    new = _manifest("trigger-new", content=new_content, offset=1)
    _write_pair(root, old, old_content)
    _write_pair(root, new, new_content)
    (root / new.published_name).write_bytes(b"tampered")

    _assert_code(
        "NAS_RETENTION_ARTIFACT_INVALID",
        lambda: apply_nas_retention_plan(
            root=root,
            plan=_plan(trigger=new.artifact_id, cleanup=(old.artifact_id,)),
        ),
    )
    assert (root / old.published_name).exists()
    assert (root / f"{old.published_name}.manifest.json").exists()


def test_all_candidates_are_preflighted_before_first_unlink(root: Path):
    first_content = b"first"
    broken_content = b"broken"
    new_content = b"new"
    first = _manifest("preflight-first", content=first_content, offset=0)
    broken = _manifest("preflight-broken", content=broken_content, offset=1)
    new = _manifest("preflight-new", content=new_content, offset=2)
    _write_pair(root, first, first_content)
    _write_pair(root, broken, broken_content)
    _write_pair(root, new, new_content)
    (root / f"{broken.published_name}.manifest.json").unlink()

    _assert_code(
        "NAS_RETENTION_MANIFEST_MISSING",
        lambda: apply_nas_retention_plan(
            root=root,
            plan=_plan(
                trigger=new.artifact_id,
                cleanup=(first.artifact_id, broken.artifact_id),
            ),
        ),
    )
    assert (root / first.published_name).exists()
    assert (root / f"{first.published_name}.manifest.json").exists()


def test_candidate_identity_corruption_and_symlink_are_fail_closed(root: Path):
    old_content = b"old"
    new_content = b"new"
    old = _manifest("identity-old", content=old_content, offset=0)
    new = _manifest("identity-new", content=new_content, offset=1)
    _write_pair(root, old, old_content)
    _write_pair(root, new, new_content)
    (root / f"{old.published_name}.manifest.json").write_bytes(
        encode_manifest_json(new)
    )

    _assert_code(
        "NAS_RETENTION_MANIFEST_IDENTITY_MISMATCH",
        lambda: apply_nas_retention_plan(
            root=root,
            plan=_plan(trigger=new.artifact_id, cleanup=(old.artifact_id,)),
        ),
    )

    (root / f"{old.published_name}.manifest.json").unlink()
    os.symlink(
        root / f"{new.published_name}.manifest.json",
        root / f"{old.published_name}.manifest.json",
    )
    _assert_code(
        "NAS_RETENTION_NONREGULAR_REJECTED",
        lambda: apply_nas_retention_plan(
            root=root,
            plan=_plan(trigger=new.artifact_id, cleanup=(old.artifact_id,)),
        ),
    )
    assert (root / old.published_name).exists()


def test_plan_must_retain_trigger_and_keep_cleanup_disjoint(root: Path):
    content = b"new"
    trigger = _manifest("bad-plan", content=content, offset=0)
    _write_pair(root, trigger, content)
    invalid = RetentionPlan(
        hourly_artifact_ids=(),
        daily_artifact_ids=(),
        monthly_artifact_ids=(),
        retained_artifact_ids=(),
        cleanup_candidate_ids=(trigger.artifact_id,),
        triggered_by_artifact_id=trigger.artifact_id,
    )

    _assert_code(
        "NAS_RETENTION_PLAN_INVALID",
        lambda: apply_nas_retention_plan(root=root, plan=invalid),
    )
    assert (root / trigger.published_name).exists()


def test_shared_pull_lock_rejects_retention_without_touching_files(root: Path):
    content = b"new"
    trigger = _manifest("locked", content=content, offset=0)
    _write_pair(root, trigger, content)
    lock = root / ".nas-pull.lock"
    lock.write_text("pulling\n", encoding="ascii")

    _assert_code(
        "NAS_RETENTION_OVERLAP",
        lambda: apply_nas_retention_plan(
            root=root,
            plan=_plan(trigger=trigger.artifact_id),
        ),
    )
    assert lock.read_text(encoding="ascii") == "pulling\n"
    assert (root / trigger.published_name).exists()
