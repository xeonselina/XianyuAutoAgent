from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

import pytest

from inventory_control.backups.acknowledgements import (
    AcknowledgementKind,
    AcknowledgementSafeResult,
    AcknowledgementSubmission,
    BackupAcknowledgementConflict,
    BackupAcknowledgementError,
    CompletedArtifactBinding,
    FreshnessState,
    accept_acknowledgement,
    acknowledgement_request_digest,
    evaluate_acknowledgement_freshness,
)


UTC = timezone.utc
BASE = datetime(2026, 8, 22, 8, 0, 0, 123456, tzinfo=UTC)


def _id(label: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"inventory-manager-backup-ack/{label}")


def _digest(label: str) -> bytes:
    return hashlib.sha256(label.encode("ascii")).digest()


def _artifact(label: str = "one", *, completed_at: datetime = BASE):
    return CompletedArtifactBinding(
        artifact_id=_id(f"artifact/{label}"),
        manifest_sha256=_digest(f"manifest/{label}"),
        artifact_sha256=_digest(f"artifact/{label}"),
        completed_at_utc=completed_at,
    )


def _submission(
    artifact: CompletedArtifactBinding,
    *,
    kind: AcknowledgementKind,
    generation: int,
    key: str,
    reported_at: datetime,
) -> AcknowledgementSubmission:
    result = (
        AcknowledgementSafeResult.VERIFIED
        if kind is AcknowledgementKind.BACKUP_STATUS
        else AcknowledgementSafeResult.SYNCED
    )
    request_digest = acknowledgement_request_digest(
        kind=kind,
        artifact_id=artifact.artifact_id,
        manifest_sha256=artifact.manifest_sha256,
        artifact_sha256=artifact.artifact_sha256,
        source_generation=generation,
        idempotency_key=key,
        safe_result=result,
        reported_at_utc=reported_at,
    )
    return AcknowledgementSubmission(
        kind=kind,
        artifact_id=artifact.artifact_id,
        manifest_sha256=artifact.manifest_sha256,
        artifact_sha256=artifact.artifact_sha256,
        source_generation=generation,
        idempotency_key=key,
        request_digest=request_digest,
        safe_result=result,
        reported_at_utc=reported_at,
    )


def test_request_digest_is_stable_purpose_separated_and_parameter_bound():
    artifact = _artifact()
    submission = _submission(
        artifact,
        kind=AcknowledgementKind.BACKUP_STATUS,
        generation=7,
        key="backup-status-7",
        reported_at=BASE + timedelta(minutes=2),
    )
    assert len(submission.request_digest) == 32
    assert submission.request_digest == acknowledgement_request_digest(
        kind=submission.kind,
        artifact_id=submission.artifact_id,
        manifest_sha256=submission.manifest_sha256,
        artifact_sha256=submission.artifact_sha256,
        source_generation=submission.source_generation,
        idempotency_key=submission.idempotency_key,
        safe_result=submission.safe_result,
        reported_at_utc=submission.reported_at_utc,
    )

    with pytest.raises(BackupAcknowledgementError) as caught:
        replace(submission, source_generation=8)
    assert caught.value.code == "ACK_REQUEST_DIGEST_MISMATCH"

    with pytest.raises(BackupAcknowledgementError) as caught:
        AcknowledgementSubmission(
            **{
                **{
                    name: getattr(submission, name)
                    for name in submission.__dataclass_fields__
                },
                "safe_result": AcknowledgementSafeResult.SYNCED,
            }
        )
    assert caught.value.code == "ACK_SAFE_RESULT_KIND_MISMATCH"


def test_backup_and_sync_ack_slots_are_independent_and_exactly_replay():
    artifact = _artifact()
    backup_request = _submission(
        artifact,
        kind=AcknowledgementKind.BACKUP_STATUS,
        generation=11,
        key="backup-status-11",
        reported_at=BASE + timedelta(minutes=2),
    )
    backup = accept_acknowledgement(
        artifact=artifact,
        submission=backup_request,
        existing_acknowledgements=(),
        database_now_utc=BASE + timedelta(minutes=3),
    )
    assert backup.idempotent_replay is False

    sync_request = _submission(
        artifact,
        kind=AcknowledgementKind.SYNC_STATUS,
        generation=11,
        key="sync-status-11",
        reported_at=BASE + timedelta(minutes=4),
    )
    sync = accept_acknowledgement(
        artifact=artifact,
        submission=sync_request,
        existing_acknowledgements=(backup.acknowledgement,),
        database_now_utc=BASE + timedelta(minutes=5),
    )
    assert sync.idempotent_replay is False
    assert sync.acknowledgement.kind is AcknowledgementKind.SYNC_STATUS

    replay = accept_acknowledgement(
        artifact=artifact,
        submission=backup_request,
        existing_acknowledgements=(
            backup.acknowledgement,
            sync.acknowledgement,
        ),
        database_now_utc=BASE + timedelta(hours=1),
    )
    assert replay.idempotent_replay is True
    assert replay.acknowledgement == backup.acknowledgement
    assert replay.acknowledgement.received_at_utc == BASE + timedelta(minutes=3)


def test_same_kind_artifact_or_idempotency_slot_rejects_changed_parameters():
    artifact = _artifact()
    first_request = _submission(
        artifact,
        kind=AcknowledgementKind.BACKUP_STATUS,
        generation=3,
        key="backup-status-3",
        reported_at=BASE + timedelta(minutes=1),
    )
    first = accept_acknowledgement(
        artifact=artifact,
        submission=first_request,
        existing_acknowledgements=(),
        database_now_utc=BASE + timedelta(minutes=2),
    ).acknowledgement
    changed = _submission(
        artifact,
        kind=AcknowledgementKind.BACKUP_STATUS,
        generation=4,
        key="backup-status-4",
        reported_at=BASE + timedelta(minutes=3),
    )
    with pytest.raises(BackupAcknowledgementConflict):
        accept_acknowledgement(
            artifact=artifact,
            submission=changed,
            existing_acknowledgements=(first,),
            database_now_utc=BASE + timedelta(minutes=4),
        )

    other = _artifact("other")
    reused_key = _submission(
        other,
        kind=AcknowledgementKind.BACKUP_STATUS,
        generation=5,
        key=first.idempotency_key,
        reported_at=BASE + timedelta(minutes=5),
    )
    with pytest.raises(BackupAcknowledgementConflict):
        accept_acknowledgement(
            artifact=other,
            submission=reused_key,
            existing_acknowledgements=(first,),
            database_now_utc=BASE + timedelta(minutes=6),
        )


def test_ack_must_match_authoritative_completed_artifact_digests():
    artifact = _artifact()
    request = _submission(
        artifact,
        kind=AcknowledgementKind.SYNC_STATUS,
        generation=1,
        key="sync-status-1",
        reported_at=BASE + timedelta(minutes=1),
    )
    changed_artifact = replace(artifact, artifact_sha256=_digest("changed"))
    with pytest.raises(BackupAcknowledgementError) as caught:
        accept_acknowledgement(
            artifact=changed_artifact,
            submission=request,
            existing_acknowledgements=(),
            database_now_utc=BASE + timedelta(minutes=2),
        )
    assert caught.value.code == "ACK_COMPLETED_ARTIFACT_MISMATCH"


def test_freshness_is_independent_and_uses_restore_point_not_delayed_ack_time():
    old = _artifact("old", completed_at=BASE)
    backup_request = _submission(
        old,
        kind=AcknowledgementKind.BACKUP_STATUS,
        generation=1,
        key="backup-status-old",
        reported_at=BASE + timedelta(hours=4),
    )
    backup = accept_acknowledgement(
        artifact=old,
        submission=backup_request,
        existing_acknowledgements=(),
        database_now_utc=BASE + timedelta(hours=4, minutes=1),
    ).acknowledgement

    missing_sync = evaluate_acknowledgement_freshness(
        (backup,),
        database_now_utc=BASE + timedelta(hours=4, minutes=2),
        backup_maximum_age=timedelta(minutes=90),
        sync_maximum_age=timedelta(hours=6),
    )
    assert missing_sync.latest_verified_backup.state is FreshnessState.STALE
    assert missing_sync.latest_verified_backup.age == timedelta(hours=4, minutes=2)
    assert missing_sync.latest_cloud_sync.state is FreshnessState.MISSING

    recent = _artifact("recent", completed_at=BASE + timedelta(hours=4))
    sync_request = _submission(
        recent,
        kind=AcknowledgementKind.SYNC_STATUS,
        generation=2,
        key="sync-status-recent",
        reported_at=BASE + timedelta(hours=4, minutes=3),
    )
    sync = accept_acknowledgement(
        artifact=recent,
        submission=sync_request,
        existing_acknowledgements=(),
        database_now_utc=BASE + timedelta(hours=4, minutes=4),
    ).acknowledgement
    snapshot = evaluate_acknowledgement_freshness(
        (backup, sync),
        database_now_utc=BASE + timedelta(hours=4, minutes=5),
        backup_maximum_age=timedelta(minutes=90),
        sync_maximum_age=timedelta(minutes=30),
    )
    assert snapshot.latest_verified_backup.state is FreshnessState.STALE
    assert snapshot.latest_cloud_sync.state is FreshnessState.FRESH
    assert snapshot.latest_cloud_sync.latest_artifact_id == recent.artifact_id
