from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

import inventory_control.backups.filesystem as backup_filesystem
from inventory_control.backups.domain import (
    BackupLease,
    BackupManifest,
    BackupStage,
    DatabaseKind,
    DatabaseSnapshot,
    RecoveryMarkerSnapshot,
    acquire_backup_lease,
    begin_backup_attempt,
    complete_backup,
)
from inventory_control.backups.filesystem import (
    BackupFilesystemError,
    decode_manifest_json,
    encode_manifest_json,
    publish_verified_artifact,
    stream_sha256_and_size,
)


UTC = timezone.utc
BASE = datetime(2026, 2, 1, 0, 0, tzinfo=UTC)
UPSTREAM_STAGES = frozenset(
    {BackupStage.DUMP, BackupStage.COMPRESSION, BackupStage.TRANSFER}
)


def _id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"inventory-manager-backup-filesystem/{label}")


def _digest(value: bytes | str) -> bytes:
    if isinstance(value, str):
        value = value.encode("ascii")
    return hashlib.sha256(value).digest()


def _manifest(label: str, content: bytes) -> BackupManifest:
    artifact_id = _id(f"artifact/{label}")
    databases = (
        DatabaseSnapshot(
            database_id=_id("control"),
            kind=DatabaseKind.CONTROL,
            schema_generation=15,
            schema_sha256=_digest("control-schema"),
            required_root_key_versions=(2, 4),
        ),
        DatabaseSnapshot(
            database_id=_id("tenant"),
            kind=DatabaseKind.TENANT,
            schema_generation=8,
            schema_sha256=_digest("tenant-schema"),
            required_root_key_versions=(4,),
        ),
    )
    return BackupManifest(
        artifact_id=artifact_id,
        attempt_id=_id(f"attempt/{label}"),
        published_name=f"backup-{artifact_id}.sql.gz",
        snapshot_at_utc=BASE + timedelta(minutes=1),
        completed_at_utc=BASE + timedelta(minutes=2),
        artifact_sha256=_digest(content),
        size_bytes=len(content),
        databases=databases,
        root_key_versions=(4, 2),
        recovery_marker=RecoveryMarkerSnapshot(
            installation_id=_id("installation"),
            recovery_run_id=_id("recovery-run"),
            marker_generation=6,
            marker_sha256=_digest("marker"),
        ),
    )


def _stage_partial(root: Path, label: str, content: bytes | None = None):
    content = content or ((f"compressed-full-dump/{label}/" * 200).encode("ascii"))
    manifest = _manifest(label, content)
    partial = root / f"{manifest.published_name}.partial"
    partial.write_bytes(content)
    return manifest, partial, content


def _assert_code(code: str, call) -> BackupFilesystemError:
    with pytest.raises(BackupFilesystemError) as exc_info:
        call()
    assert exc_info.value.code == code
    assert str(exc_info.value) == code
    return exc_info.value


def _canonical(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def test_manifest_json_is_canonical_complete_and_digest_verified():
    manifest = _manifest("roundtrip", b"roundtrip-content")

    encoded = encode_manifest_json(manifest)
    decoded = decode_manifest_json(
        encoded,
        expected_manifest_sha256=manifest.manifest_sha256,
    )

    assert decoded == manifest
    assert encode_manifest_json(decoded) == encoded
    envelope = json.loads(encoded)
    assert envelope["format_version"] == "inventory-manager-backup-manifest/v1"
    assert envelope["manifest_sha256"] == manifest.manifest_sha256.hex()
    assert envelope["manifest"]["databases"][0]["schema_sha256"]
    assert envelope["manifest"]["recovery_marker"]["marker_sha256"]


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda value: value.update({"unexpected": True}),
            "UNKNOWN_MANIFEST_ENVELOPE_FIELD",
        ),
        (
            lambda value: value.pop("format_version"),
            "MISSING_MANIFEST_ENVELOPE_FIELD",
        ),
        (
            lambda value: value["manifest"].update({"unexpected": True}),
            "UNKNOWN_MANIFEST_FIELD",
        ),
        (
            lambda value: value["manifest"].pop("size_bytes"),
            "MISSING_MANIFEST_FIELD",
        ),
        (
            lambda value: value["manifest"]["databases"][0].update(
                {"unexpected": True}
            ),
            "UNKNOWN_DATABASE_FIELD",
        ),
        (
            lambda value: value["manifest"]["recovery_marker"].pop(
                "marker_generation"
            ),
            "MISSING_RECOVERY_MARKER_FIELD",
        ),
    ],
)
def test_manifest_rejects_unknown_and_missing_fields(mutation, code):
    manifest = _manifest("schema", b"schema-content")
    value = json.loads(encode_manifest_json(manifest))
    mutation(value)
    _assert_code(code, lambda: decode_manifest_json(_canonical(value)))


@pytest.mark.parametrize(
    "sensitive_key",
    ["customer_phone", "shipping_address", "database_password", "api_key"],
)
def test_manifest_rejects_sensitive_or_pii_keys_before_schema_use(sensitive_key):
    manifest = _manifest(f"sensitive-{sensitive_key}", b"content")
    value = json.loads(encode_manifest_json(manifest))
    value["manifest"][sensitive_key] = "must-not-be-accepted"
    _assert_code(
        "SENSITIVE_MANIFEST_KEY_REJECTED",
        lambda: decode_manifest_json(_canonical(value)),
    )


def test_manifest_rejects_digest_corruption_truncation_duplicates_and_noncanonical():
    manifest = _manifest("manifest-corruption", b"content")
    encoded = encode_manifest_json(manifest)
    value = json.loads(encoded)
    value["manifest_sha256"] = _digest("wrong").hex()
    _assert_code(
        "MANIFEST_SHA256_MISMATCH",
        lambda: decode_manifest_json(_canonical(value)),
    )
    _assert_code("INVALID_MANIFEST_JSON", lambda: decode_manifest_json(encoded[:-7]))
    duplicate_key = encoded.replace(
        b'{"format_version":',
        b'{"format_version":"duplicate","format_version":',
        1,
    )
    _assert_code(
        "DUPLICATE_MANIFEST_JSON_KEY",
        lambda: decode_manifest_json(duplicate_key),
    )
    _assert_code(
        "NONCANONICAL_MANIFEST_JSON",
        lambda: decode_manifest_json(encoded + b"\n"),
    )


def test_manifest_rejects_path_traversal_in_published_name():
    manifest = _manifest("traversal-json", b"content")
    value = json.loads(encode_manifest_json(manifest))
    value["manifest"]["published_name"] = "../backup-escape.sql.gz"
    _assert_code(
        "INVALID_PUBLISHED_ARTIFACT_NAME",
        lambda: decode_manifest_json(_canonical(value)),
    )


def test_streaming_hash_reports_exact_sha256_and_size(tmp_path: Path):
    content = os.urandom(2 * 1024 * 1024 + 37)
    path = tmp_path / "payload.partial"
    path.write_bytes(content)

    result = stream_sha256_and_size(
        root=tmp_path,
        path=path,
        chunk_size=65537,
    )

    assert result.sha256 == hashlib.sha256(content).digest()
    assert result.size_bytes == len(content)


@pytest.mark.parametrize("mode", ["corrupt", "truncated"])
def test_publish_rejects_corrupt_or_truncated_partial(tmp_path: Path, mode: str):
    manifest, partial, content = _stage_partial(tmp_path, f"invalid-{mode}")
    if mode == "corrupt":
        partial.write_bytes(b"x" + content[1:])
        expected = "ARTIFACT_SHA256_MISMATCH"
    else:
        partial.write_bytes(content[:-1])
        expected = "ARTIFACT_SHA256_MISMATCH"
    _assert_code(
        expected,
        lambda: publish_verified_artifact(
            root=tmp_path,
            partial_artifact_path=partial,
            manifest=manifest,
            upstream_successful_stages=UPSTREAM_STAGES,
            database_now_utc=manifest.completed_at_utc,
        ),
    )
    assert partial.exists()
    assert not (tmp_path / manifest.published_name).exists()


def test_publish_checks_size_independently_from_sha256(tmp_path: Path):
    from dataclasses import replace

    manifest, partial, content = _stage_partial(tmp_path, "wrong-size")
    manifest = replace(
        manifest,
        artifact_sha256=_digest(content),
        size_bytes=len(content) + 1,
    )
    _assert_code(
        "ARTIFACT_SIZE_MISMATCH",
        lambda: publish_verified_artifact(
            root=tmp_path,
            partial_artifact_path=partial,
            manifest=manifest,
            upstream_successful_stages=UPSTREAM_STAGES,
            database_now_utc=manifest.completed_at_utc,
        ),
    )


def test_partial_must_be_exact_direct_child_of_absolute_root(tmp_path: Path):
    manifest, expected_partial, content = _stage_partial(tmp_path, "cross-directory")
    other = tmp_path.parent / f"outside-{manifest.artifact_id}.partial"
    other.write_bytes(content)
    error = _assert_code(
        "BACKUP_PATH_OUTSIDE_ROOT",
        lambda: publish_verified_artifact(
            root=tmp_path,
            partial_artifact_path=other,
            manifest=manifest,
            upstream_successful_stages=UPSTREAM_STAGES,
            database_now_utc=manifest.completed_at_utc,
        ),
    )
    assert str(tmp_path) not in str(error)
    assert expected_partial.exists()
    _assert_code(
        "BACKUP_ROOT_NOT_ABSOLUTE",
        lambda: stream_sha256_and_size(root="relative", path=expected_partial),
    )


def test_symlink_artifact_and_symlink_root_escape_are_rejected(tmp_path: Path):
    real_root = tmp_path / "real"
    real_root.mkdir()
    content = b"outside-content"
    manifest = _manifest("symlink", content)
    outside = tmp_path / "outside.sql.gz.partial"
    outside.write_bytes(content)
    partial = real_root / f"{manifest.published_name}.partial"
    partial.symlink_to(outside)
    _assert_code(
        "ARTIFACT_SYMLINK_REJECTED",
        lambda: publish_verified_artifact(
            root=real_root,
            partial_artifact_path=partial,
            manifest=manifest,
            upstream_successful_stages=UPSTREAM_STAGES,
            database_now_utc=manifest.completed_at_utc,
        ),
    )
    root_link = tmp_path / "root-link"
    root_link.symlink_to(real_root, target_is_directory=True)
    linked_partial = root_link / partial.name
    _assert_code(
        "BACKUP_ROOT_SYMLINK_REJECTED",
        lambda: publish_verified_artifact(
            root=root_link,
            partial_artifact_path=linked_partial,
            manifest=manifest,
            upstream_successful_stages=UPSTREAM_STAGES,
            database_now_utc=manifest.completed_at_utc,
        ),
    )


def test_existing_published_symlink_is_rejected_without_following_it(tmp_path: Path):
    manifest, partial, _ = _stage_partial(tmp_path, "published-symlink")
    outside = tmp_path.parent / f"outside-published-{manifest.artifact_id}"
    outside.write_bytes(b"outside-must-remain")
    published = tmp_path / manifest.published_name
    published.symlink_to(outside)
    _assert_code(
        "PUBLISHED_ARTIFACT_SYMLINK_REJECTED",
        lambda: publish_verified_artifact(
            root=tmp_path,
            partial_artifact_path=partial,
            manifest=manifest,
            upstream_successful_stages=UPSTREAM_STAGES,
            database_now_utc=manifest.completed_at_utc,
        ),
    )
    assert outside.read_bytes() == b"outside-must-remain"


def test_publish_fsyncs_and_atomically_links_manifest_then_artifact_without_replace(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest, partial, content = _stage_partial(tmp_path, "atomic")
    real_link = os.link
    publications: list[tuple[Path, Path]] = []

    def tracked_link(source, destination, *, follow_symlinks=True):
        publications.append((Path(source), Path(destination)))
        return real_link(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(backup_filesystem.os, "link", tracked_link)
    result = publish_verified_artifact(
        root=tmp_path,
        partial_artifact_path=partial,
        manifest=manifest,
        upstream_successful_stages=UPSTREAM_STAGES,
        database_now_utc=manifest.completed_at_utc,
    )

    assert publications == [
        (
            tmp_path / f"{manifest.published_name}.manifest.json.partial",
            tmp_path / f"{manifest.published_name}.manifest.json",
        ),
        (partial, tmp_path / manifest.published_name),
    ]
    assert not partial.exists()
    assert result.artifact_path.read_bytes() == content
    assert decode_manifest_json(result.manifest_path.read_bytes()) == manifest
    assert result.observation.successful_stages == frozenset(BackupStage)
    assert result.observation.atomic_publish_succeeded is True
    assert result.observation.observed_artifact_sha256 == manifest.artifact_sha256
    assert result.observation.observed_manifest_sha256 == manifest.manifest_sha256


def test_observation_is_accepted_by_domain_completion(tmp_path: Path):
    content = b"domain-completion-content" * 100
    manifest, partial, _ = _stage_partial(tmp_path, "domain-completion", content)
    lease = acquire_backup_lease(
        BackupLease.available(observed_at_utc=BASE),
        acquisition_id=_id("domain-completion/acquisition"),
        holder_id="nas-worker",
        database_now_utc=BASE,
        lease_duration=timedelta(minutes=10),
    )
    attempt = begin_backup_attempt(
        lease,
        attempt_id=manifest.attempt_id,
        partial_name=partial.name,
        database_now_utc=BASE,
    )
    publication = publish_verified_artifact(
        root=tmp_path,
        partial_artifact_path=partial,
        manifest=manifest,
        upstream_successful_stages=UPSTREAM_STAGES,
        database_now_utc=manifest.completed_at_utc,
    )

    completed = complete_backup(
        lease=lease,
        attempt=attempt,
        manifest=manifest,
        observation=publication.observation,
        existing_artifacts=(),
        database_now_utc=manifest.completed_at_utc,
    )

    assert completed.artifact.artifact_id == manifest.artifact_id
    assert completed.artifact.manifest_sha256 == manifest.manifest_sha256


def test_duplicate_publish_never_overwrites_existing_artifact(tmp_path: Path):
    manifest, partial, content = _stage_partial(tmp_path, "duplicate-publish")
    first = publish_verified_artifact(
        root=tmp_path,
        partial_artifact_path=partial,
        manifest=manifest,
        upstream_successful_stages=UPSTREAM_STAGES,
        database_now_utc=manifest.completed_at_utc,
    )
    before = first.artifact_path.read_bytes()
    _assert_code(
        "PUBLISHED_ARTIFACT_ALREADY_EXISTS",
        lambda: publish_verified_artifact(
            root=tmp_path,
            partial_artifact_path=partial,
            manifest=manifest,
            upstream_successful_stages=UPSTREAM_STAGES,
            database_now_utc=manifest.completed_at_utc,
        ),
    )
    assert before == content == first.artifact_path.read_bytes()


def test_exact_orphan_manifest_can_be_reused_after_artifact_rename_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest, partial, content = _stage_partial(tmp_path, "retry-after-rename")
    real_link = os.link

    def fail_artifact_publication(source, destination, *, follow_symlinks=True):
        if Path(destination).name == manifest.published_name:
            raise OSError("simulated without exposing it")
        return real_link(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(backup_filesystem.os, "link", fail_artifact_publication)
    _assert_code(
        "ARTIFACT_ATOMIC_PUBLISH_FAILED",
        lambda: publish_verified_artifact(
            root=tmp_path,
            partial_artifact_path=partial,
            manifest=manifest,
            upstream_successful_stages=UPSTREAM_STAGES,
            database_now_utc=manifest.completed_at_utc,
        ),
    )
    published_manifest = tmp_path / f"{manifest.published_name}.manifest.json"
    assert published_manifest.exists()
    assert partial.exists()
    assert not (tmp_path / manifest.published_name).exists()

    monkeypatch.setattr(backup_filesystem.os, "link", real_link)
    retried = publish_verified_artifact(
        root=tmp_path,
        partial_artifact_path=partial,
        manifest=manifest,
        upstream_successful_stages=UPSTREAM_STAGES,
        database_now_utc=manifest.completed_at_utc,
    )
    assert retried.artifact_path.read_bytes() == content
    assert retried.manifest_path == published_manifest


def test_concurrent_target_claim_is_never_overwritten(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    manifest, partial, _ = _stage_partial(tmp_path, "concurrent-claim")
    published = tmp_path / manifest.published_name
    rival_content = b"rival-publication-must-survive"
    real_link = os.link

    def race_link(source, destination, *, follow_symlinks=True):
        destination = Path(destination)
        if destination == published and not destination.exists():
            destination.write_bytes(rival_content)
        return real_link(source, destination, follow_symlinks=follow_symlinks)

    monkeypatch.setattr(backup_filesystem.os, "link", race_link)
    _assert_code(
        "PUBLISHED_ARTIFACT_ALREADY_EXISTS",
        lambda: publish_verified_artifact(
            root=tmp_path,
            partial_artifact_path=partial,
            manifest=manifest,
            upstream_successful_stages=UPSTREAM_STAGES,
            database_now_utc=manifest.completed_at_utc,
        ),
    )
    assert published.read_bytes() == rival_content
    assert partial.exists()


def test_corrupt_partial_manifest_fails_closed_without_publishing_artifact(
    tmp_path: Path,
):
    manifest, partial, _ = _stage_partial(tmp_path, "partial-manifest-corrupt")
    partial_manifest = tmp_path / f"{manifest.published_name}.manifest.json.partial"
    partial_manifest.write_bytes(encode_manifest_json(manifest)[:-5])
    _assert_code(
        "INVALID_MANIFEST_JSON",
        lambda: publish_verified_artifact(
            root=tmp_path,
            partial_artifact_path=partial,
            manifest=manifest,
            upstream_successful_stages=UPSTREAM_STAGES,
            database_now_utc=manifest.completed_at_utc,
        ),
    )
    assert partial.exists()
    assert partial_manifest.exists()
    assert not (tmp_path / manifest.published_name).exists()


def test_upstream_stage_and_future_clock_are_fail_closed(tmp_path: Path):
    manifest, partial, _ = _stage_partial(tmp_path, "preconditions")
    _assert_code(
        "UPSTREAM_STAGE_PROOF_INCOMPLETE",
        lambda: publish_verified_artifact(
            root=tmp_path,
            partial_artifact_path=partial,
            manifest=manifest,
            upstream_successful_stages=(BackupStage.DUMP, BackupStage.COMPRESSION),
            database_now_utc=manifest.completed_at_utc,
        ),
    )
    _assert_code(
        "ARTIFACT_TIME_IN_FUTURE",
        lambda: publish_verified_artifact(
            root=tmp_path,
            partial_artifact_path=partial,
            manifest=manifest,
            upstream_successful_stages=UPSTREAM_STAGES,
            database_now_utc=manifest.completed_at_utc - timedelta(microseconds=1),
        ),
    )
