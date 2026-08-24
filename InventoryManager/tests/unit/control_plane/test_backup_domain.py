from __future__ import annotations

from dataclasses import FrozenInstanceError, fields, replace
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from inventory_control.backups.domain import (
    BackupDomainError,
    BackupLease,
    BackupLeaseStatus,
    BackupManifest,
    BackupObservation,
    BackupStage,
    CompletedBackupArtifact,
    DatabaseKind,
    DatabaseSnapshot,
    RecoveryMarkerSnapshot,
    RetentionPolicy,
    acquire_backup_lease,
    begin_backup_attempt,
    complete_backup,
    plan_successful_point_retention,
    renew_backup_lease,
)


UTC = timezone.utc
BASE = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
ALL_STAGES = frozenset(BackupStage)


def _id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"inventory-manager-backup-test/{label}")


def _digest(label: str) -> bytes:
    import hashlib

    return hashlib.sha256(label.encode("ascii")).digest()


def _databases(*, tenant_label: str = "tenant") -> tuple[DatabaseSnapshot, ...]:
    return (
        DatabaseSnapshot(
            database_id=_id("control"),
            kind=DatabaseKind.CONTROL,
            schema_generation=11,
            schema_sha256=_digest("control-schema"),
            required_root_key_versions=(1, 2),
        ),
        DatabaseSnapshot(
            database_id=_id(tenant_label),
            kind=DatabaseKind.TENANT,
            schema_generation=7,
            schema_sha256=_digest(f"{tenant_label}-schema"),
            required_root_key_versions=(2,),
        ),
    )


def _marker(label: str = "marker") -> RecoveryMarkerSnapshot:
    return RecoveryMarkerSnapshot(
        installation_id=_id("installation"),
        recovery_run_id=_id("recovery-run"),
        marker_generation=3,
        marker_sha256=_digest(label),
    )


def _completion_inputs(
    label: str,
    *,
    snapshot_at: datetime = BASE + timedelta(minutes=2),
    completed_at: datetime | None = None,
):
    completed_at = completed_at or snapshot_at + timedelta(minutes=1)
    artifact_id = _id(f"artifact/{label}")
    attempt_id = _id(f"attempt/{label}")
    acquisition_id = _id(f"acquisition/{label}")
    published_name = f"backup-{artifact_id}.sql.gz"
    acquired_at = snapshot_at - timedelta(minutes=2)
    lease = acquire_backup_lease(
        BackupLease.available(observed_at_utc=acquired_at),
        acquisition_id=acquisition_id,
        holder_id=f"nas-worker-{label}",
        database_now_utc=acquired_at,
        lease_duration=timedelta(minutes=30),
    )
    attempt = begin_backup_attempt(
        lease,
        attempt_id=attempt_id,
        partial_name=f"{published_name}.partial",
        database_now_utc=acquired_at,
    )
    databases = _databases()
    manifest = BackupManifest(
        artifact_id=artifact_id,
        attempt_id=attempt_id,
        published_name=published_name,
        snapshot_at_utc=snapshot_at,
        completed_at_utc=completed_at,
        artifact_sha256=_digest(f"dump/{label}"),
        size_bytes=8192 + len(label),
        databases=databases,
        root_key_versions=(2, 1),
        recovery_marker=_marker(),
    )
    observation = BackupObservation(
        artifact_id=artifact_id,
        attempt_id=attempt_id,
        partial_name=f"{published_name}.partial",
        published_name=published_name,
        successful_stages=ALL_STAGES,
        atomic_publish_succeeded=True,
        observed_artifact_sha256=manifest.artifact_sha256,
        observed_manifest_sha256=manifest.manifest_sha256,
        observed_size_bytes=manifest.size_bytes,
        observed_databases=tuple(reversed(databases)),
        observed_root_key_versions=(2, 1),
        observed_recovery_marker=manifest.recovery_marker,
    )
    return lease, attempt, manifest, observation


def _complete(
    label: str,
    *,
    snapshot_at: datetime = BASE + timedelta(minutes=2),
) -> CompletedBackupArtifact:
    lease, attempt, manifest, observation = _completion_inputs(
        label, snapshot_at=snapshot_at
    )
    return complete_backup(
        lease=lease,
        attempt=attempt,
        manifest=manifest,
        observation=observation,
        existing_artifacts=(),
        database_now_utc=manifest.completed_at_utc,
    ).artifact


def _assert_code(code: str, call) -> None:
    with pytest.raises(BackupDomainError) as exc_info:
        call()
    assert exc_info.value.code == code
    assert str(exc_info.value) == code


def test_success_requires_all_receipts_and_returns_immutable_completed_artifact():
    lease, attempt, manifest, observation = _completion_inputs("success")

    result = complete_backup(
        lease=lease,
        attempt=attempt,
        manifest=manifest,
        observation=observation,
        existing_artifacts=(),
        database_now_utc=manifest.completed_at_utc,
    )

    assert result.artifact.published_name == manifest.published_name
    assert not result.artifact.published_name.endswith(".partial")
    assert result.artifact.databases == tuple(
        sorted(manifest.databases, key=lambda item: (item.kind.value, str(item.database_id)))
    )
    assert result.artifact.root_key_versions == (1, 2)
    assert result.lease.status is BackupLeaseStatus.AVAILABLE
    assert result.lease.generation == lease.generation
    assert result.lease.fencing_token == lease.fencing_token
    assert result.idempotent_replay is False
    with pytest.raises(FrozenInstanceError):
        result.artifact.size_bytes = 1  # type: ignore[misc]


@pytest.mark.parametrize("missing_stage", list(BackupStage))
def test_every_external_stage_is_mandatory(missing_stage: BackupStage):
    lease, attempt, manifest, observation = _completion_inputs(
        f"missing-{missing_stage.value}"
    )
    observation = replace(
        observation,
        successful_stages=ALL_STAGES - {missing_stage},
    )

    _assert_code(
        "INCOMPLETE_BACKUP_STAGES",
        lambda: complete_backup(
            lease=lease,
            attempt=attempt,
            manifest=manifest,
            observation=observation,
            existing_artifacts=(),
            database_now_utc=manifest.completed_at_utc,
        ),
    )


def test_partial_or_non_atomic_publication_never_becomes_completed():
    lease, attempt, manifest, observation = _completion_inputs("partial")
    partial_observation = replace(observation, atomic_publish_succeeded=False)
    _assert_code(
        "ATOMIC_PUBLISH_NOT_PROVEN",
        lambda: complete_backup(
            lease=lease,
            attempt=attempt,
            manifest=manifest,
            observation=partial_observation,
            existing_artifacts=(),
            database_now_utc=manifest.completed_at_utc,
        ),
    )
    _assert_code(
        "INVALID_PUBLISHED_ARTIFACT_NAME",
        lambda: replace(manifest, published_name=f"{manifest.published_name}.partial"),
    )


@pytest.mark.parametrize(
    ("mutation", "code"),
    [
        (
            lambda manifest, observation: replace(
                observation, observed_artifact_sha256=_digest("corrupt-dump")
            ),
            "ARTIFACT_SHA256_MISMATCH",
        ),
        (
            lambda manifest, observation: replace(
                observation, observed_manifest_sha256=_digest("corrupt-manifest")
            ),
            "MANIFEST_SHA256_MISMATCH",
        ),
        (
            lambda manifest, observation: replace(
                observation, observed_size_bytes=manifest.size_bytes + 1
            ),
            "ARTIFACT_SIZE_MISMATCH",
        ),
        (
            lambda manifest, observation: replace(
                observation, observed_databases=_databases(tenant_label="other-tenant")
            ),
            "DATABASE_SET_MISMATCH",
        ),
        (
            lambda manifest, observation: replace(
                observation, observed_recovery_marker=_marker("other-marker")
            ),
            "RECOVERY_MARKER_MISMATCH",
        ),
    ],
)
def test_completion_fails_closed_on_observed_metadata_mismatch(mutation, code):
    lease, attempt, manifest, observation = _completion_inputs(f"mismatch-{code}")
    observation = mutation(manifest, observation)

    _assert_code(
        code,
        lambda: complete_backup(
            lease=lease,
            attempt=attempt,
            manifest=manifest,
            observation=observation,
            existing_artifacts=(),
            database_now_utc=manifest.completed_at_utc,
        ),
    )


def test_missing_duplicate_and_incomplete_database_sets_fail_closed():
    control, tenant = _databases()
    _assert_code(
        "MISSING_DATABASE_SET",
        lambda: replace(
            _completion_inputs("missing-db")[2],
            databases=(),
            root_key_versions=(1,),
        ),
    )
    _assert_code(
        "DUPLICATE_DATABASE_IDENTITY",
        lambda: replace(
            _completion_inputs("duplicate-db")[2],
            databases=(control, tenant, tenant),
        ),
    )
    _assert_code(
        "INCOMPLETE_FULL_DATABASE_SET",
        lambda: replace(
            _completion_inputs("no-tenant-db")[2],
            databases=(control,),
            root_key_versions=(1, 2),
        ),
    )


def test_manifest_root_key_set_must_exactly_match_database_requirements():
    manifest = _completion_inputs("root-set")[2]
    _assert_code(
        "ROOT_KEY_VERSION_SET_MISMATCH",
        lambda: replace(manifest, root_key_versions=(1,)),
    )
    _assert_code(
        "DUPLICATE_ROOT_KEY_VERSION",
        lambda: replace(manifest, root_key_versions=(1, 2, 2)),
    )


def test_manifest_and_artifact_shapes_have_no_secret_password_or_pii_fields():
    forbidden_fragments = (
        "secret",
        "password",
        "credential",
        "phone",
        "address",
        "customer",
        "name_plaintext",
        "key_material",
    )
    for domain_type in (
        BackupManifest,
        CompletedBackupArtifact,
        DatabaseSnapshot,
        RecoveryMarkerSnapshot,
    ):
        names = {field.name.lower() for field in fields(domain_type)}
        assert not any(
            fragment in name for fragment in forbidden_fragments for name in names
        )


def test_active_lease_rejects_overlap_and_replays_exact_acquisition():
    lease = BackupLease.available(observed_at_utc=BASE)
    acquisition_id = _id("lease-a")
    held = acquire_backup_lease(
        lease,
        acquisition_id=acquisition_id,
        holder_id="nas-a",
        database_now_utc=BASE,
        lease_duration=timedelta(minutes=10),
    )
    replay = acquire_backup_lease(
        held,
        acquisition_id=acquisition_id,
        holder_id="nas-a",
        database_now_utc=BASE + timedelta(minutes=1),
        lease_duration=timedelta(minutes=20),
    )
    assert replay is held
    _assert_code(
        "OVERLAPPING_BACKUP_LEASE",
        lambda: acquire_backup_lease(
            held,
            acquisition_id=_id("lease-b"),
            holder_id="nas-b",
            database_now_utc=BASE + timedelta(minutes=1),
            lease_duration=timedelta(minutes=10),
        ),
    )
    _assert_code(
        "DUPLICATE_LEASE_ACQUISITION_IDENTITY",
        lambda: acquire_backup_lease(
            held,
            acquisition_id=acquisition_id,
            holder_id="different-holder",
            database_now_utc=BASE + timedelta(minutes=1),
            lease_duration=timedelta(minutes=10),
        ),
    )


def test_expired_acquisition_identity_cannot_be_reused():
    current = BackupLease.available(observed_at_utc=BASE)
    acquisition_id = _id("expired-acquisition")
    held = acquire_backup_lease(
        current,
        acquisition_id=acquisition_id,
        holder_id="nas-a",
        database_now_utc=BASE,
        lease_duration=timedelta(minutes=10),
    )
    _assert_code(
        "LEASE_ACQUISITION_ALREADY_ENDED",
        lambda: acquire_backup_lease(
            held,
            acquisition_id=acquisition_id,
            holder_id="nas-a",
            database_now_utc=held.expires_at_utc,
            lease_duration=timedelta(minutes=10),
        ),
    )


def test_expired_takeover_increments_fence_and_stale_attempt_cannot_complete():
    old_lease, old_attempt, manifest, observation = _completion_inputs("takeover")
    takeover_at = old_lease.expires_at_utc
    new_lease = acquire_backup_lease(
        old_lease,
        acquisition_id=_id("takeover/new-acquisition"),
        holder_id="nas-new",
        database_now_utc=takeover_at,
        lease_duration=timedelta(minutes=10),
    )
    assert new_lease.generation == old_lease.generation + 1
    assert new_lease.fencing_token == old_lease.fencing_token + 1
    _assert_code(
        "STALE_BACKUP_LEASE_FENCE",
        lambda: complete_backup(
            lease=new_lease,
            attempt=old_attempt,
            manifest=manifest,
            observation=observation,
            existing_artifacts=(),
            database_now_utc=takeover_at,
        ),
    )


def test_lease_expiry_and_clock_boundaries_fail_closed():
    lease, attempt, manifest, observation = _completion_inputs("lease-boundary")
    _assert_code(
        "BACKUP_LEASE_EXPIRED",
        lambda: complete_backup(
            lease=lease,
            attempt=attempt,
            manifest=manifest,
            observation=observation,
            existing_artifacts=(),
            database_now_utc=lease.expires_at_utc,
        ),
    )
    _assert_code(
        "LEASE_CLOCK_MOVED_BACKWARDS",
        lambda: renew_backup_lease(
            lease,
            acquisition_id=lease.acquisition_id,
            lease_generation=lease.generation,
            fencing_token=lease.fencing_token,
            database_now_utc=lease.observed_at_utc - timedelta(microseconds=1),
            lease_duration=timedelta(minutes=5),
        ),
    )


def test_future_artifact_time_fails_closed():
    lease, attempt, manifest, observation = _completion_inputs("future-time")
    _assert_code(
        "ARTIFACT_TIME_IN_FUTURE",
        lambda: complete_backup(
            lease=lease,
            attempt=attempt,
            manifest=manifest,
            observation=observation,
            existing_artifacts=(),
            database_now_utc=manifest.completed_at_utc - timedelta(microseconds=1),
        ),
    )


def test_completion_retry_is_idempotent_after_lease_release():
    lease, attempt, manifest, observation = _completion_inputs("replay")
    first = complete_backup(
        lease=lease,
        attempt=attempt,
        manifest=manifest,
        observation=observation,
        existing_artifacts=(),
        database_now_utc=manifest.completed_at_utc,
    )
    replay = complete_backup(
        lease=first.lease,
        attempt=attempt,
        manifest=manifest,
        observation=observation,
        existing_artifacts=(first.artifact,),
        database_now_utc=manifest.completed_at_utc + timedelta(hours=1),
    )
    assert replay.artifact == first.artifact
    assert replay.lease is first.lease
    assert replay.idempotent_replay is True


def test_duplicate_artifact_identity_with_different_facts_fails_closed():
    existing = _complete("duplicate-id")
    lease, attempt, manifest, observation = _completion_inputs("other-attempt")
    manifest = replace(
        manifest,
        artifact_id=existing.artifact_id,
        published_name=existing.published_name,
    )
    observation = replace(
        observation,
        artifact_id=existing.artifact_id,
        published_name=existing.published_name,
        partial_name=f"{existing.published_name}.partial",
        observed_manifest_sha256=manifest.manifest_sha256,
    )
    attempt = replace(attempt, partial_name=f"{existing.published_name}.partial")
    _assert_code(
        "DUPLICATE_ARTIFACT_IDENTITY",
        lambda: complete_backup(
            lease=lease,
            attempt=attempt,
            manifest=manifest,
            observation=observation,
            existing_artifacts=(existing,),
            database_now_utc=manifest.completed_at_utc,
        ),
    )


def test_one_attempt_cannot_publish_two_artifact_identities():
    existing = _complete("attempt-identity-existing")
    lease, attempt, manifest, observation = _completion_inputs(
        "attempt-identity-new"
    )
    attempt = replace(attempt, attempt_id=existing.attempt_id)
    manifest = replace(manifest, attempt_id=existing.attempt_id)
    observation = replace(
        observation,
        attempt_id=existing.attempt_id,
        observed_manifest_sha256=manifest.manifest_sha256,
    )
    _assert_code(
        "DUPLICATE_ATTEMPT_IDENTITY",
        lambda: complete_backup(
            lease=lease,
            attempt=attempt,
            manifest=manifest,
            observation=observation,
            existing_artifacts=(existing,),
            database_now_utc=manifest.completed_at_utc,
        ),
    )


def test_retention_selects_exact_successful_point_counts_and_unions_tiers():
    artifacts = tuple(
        _complete(
            f"retention-{index}",
            snapshot_at=BASE + timedelta(days=index, minutes=2),
        )
        for index in range(400)
    )
    newest = artifacts[-1]
    plan = plan_successful_point_retention(
        artifacts,
        newly_verified_artifact_id=newest.artifact_id,
        policy=RetentionPolicy("Asia/Shanghai"),
        database_now_utc=newest.completed_at_utc,
    )

    assert len(plan.hourly_artifact_ids) == 48
    assert len(plan.daily_artifact_ids) == 30
    assert len(plan.monthly_artifact_ids) == 12
    assert set(plan.retained_artifact_ids) == (
        set(plan.hourly_artifact_ids)
        | set(plan.daily_artifact_ids)
        | set(plan.monthly_artifact_ids)
    )
    assert set(plan.cleanup_candidate_ids).isdisjoint(plan.retained_artifact_ids)
    assert set(plan.cleanup_candidate_ids) | set(plan.retained_artifact_ids) == {
        artifact.artifact_id for artifact in artifacts
    }
    assert newest.artifact_id in plan.retained_artifact_ids


def test_bucket_representative_is_latest_snapshot_and_timezone_is_explicit():
    first = _complete("bucket-first", snapshot_at=BASE + timedelta(minutes=5))
    latest = _complete("bucket-latest", snapshot_at=BASE + timedelta(minutes=55))
    next_hour = _complete("bucket-next", snapshot_at=BASE + timedelta(hours=1))
    plan = plan_successful_point_retention(
        (first, latest, next_hour),
        newly_verified_artifact_id=next_hour.artifact_id,
        policy=RetentionPolicy("UTC"),
        database_now_utc=next_hour.completed_at_utc,
    )
    assert first.artifact_id not in plan.hourly_artifact_ids
    assert latest.artifact_id in plan.hourly_artifact_ids
    assert next_hour.artifact_id in plan.hourly_artifact_ids
    assert plan.daily_artifact_ids == (next_hour.artifact_id,)
    assert plan.monthly_artifact_ids == (next_hour.artifact_id,)

    utc_day_one = _complete(
        "timezone-day-one", snapshot_at=datetime(2026, 1, 1, 15, 30, tzinfo=UTC)
    )
    utc_day_two = _complete(
        "timezone-day-two", snapshot_at=datetime(2026, 1, 1, 16, 30, tzinfo=UTC)
    )
    shanghai = plan_successful_point_retention(
        (utc_day_one, utc_day_two),
        newly_verified_artifact_id=utc_day_two.artifact_id,
        policy=RetentionPolicy("Asia/Shanghai"),
        database_now_utc=utc_day_two.completed_at_utc,
    )
    utc = plan_successful_point_retention(
        (utc_day_one, utc_day_two),
        newly_verified_artifact_id=utc_day_two.artifact_id,
        policy=RetentionPolicy("UTC"),
        database_now_utc=utc_day_two.completed_at_utc,
    )
    assert len(shanghai.daily_artifact_ids) == 2
    assert utc.daily_artifact_ids == (utc_day_two.artifact_id,)


def test_cleanup_requires_newest_verified_artifact_and_rejects_missing_trigger():
    older = _complete("cleanup-older", snapshot_at=BASE)
    newer = _complete("cleanup-newer", snapshot_at=BASE + timedelta(hours=1))
    _assert_code(
        "RETENTION_TRIGGER_NOT_LATEST_SUCCESS",
        lambda: plan_successful_point_retention(
            (older, newer),
            newly_verified_artifact_id=older.artifact_id,
            policy=RetentionPolicy("UTC"),
            database_now_utc=newer.completed_at_utc,
        ),
    )
    _assert_code(
        "NEW_VERIFIED_ARTIFACT_MISSING",
        lambda: plan_successful_point_retention(
            (older, newer),
            newly_verified_artifact_id=_id("not-present"),
            policy=RetentionPolicy("UTC"),
            database_now_utc=newer.completed_at_utc,
        ),
    )


def test_retention_fails_closed_on_corruption_duplicates_and_future_clock():
    first = _complete("integrity-first", snapshot_at=BASE)
    second = _complete("integrity-second", snapshot_at=BASE + timedelta(hours=1))
    _assert_code(
        "DUPLICATE_ARTIFACT_IDENTITY",
        lambda: plan_successful_point_retention(
            (first, first, second),
            newly_verified_artifact_id=second.artifact_id,
            policy=RetentionPolicy("UTC"),
            database_now_utc=second.completed_at_utc,
        ),
    )
    _assert_code(
        "ARTIFACT_TIME_IN_FUTURE",
        lambda: plan_successful_point_retention(
            (first, second),
            newly_verified_artifact_id=second.artifact_id,
            policy=RetentionPolicy("UTC"),
            database_now_utc=second.completed_at_utc - timedelta(microseconds=1),
        ),
    )
    object.__setattr__(first, "size_bytes", first.size_bytes + 1)
    _assert_code(
        "CORRUPT_COMPLETED_ARTIFACT_RECORD",
        lambda: plan_successful_point_retention(
            (first, second),
            newly_verified_artifact_id=second.artifact_id,
            policy=RetentionPolicy("UTC"),
            database_now_utc=second.completed_at_utc,
        ),
    )


def test_retention_policy_is_fixed_and_requires_real_timezone():
    _assert_code(
        "UNSUPPORTED_RETENTION_POLICY",
        lambda: RetentionPolicy("UTC", hourly_success_points=47),
    )
    _assert_code(
        "INVALID_RETENTION_TIMEZONE",
        lambda: RetentionPolicy("not/a-timezone"),
    )
