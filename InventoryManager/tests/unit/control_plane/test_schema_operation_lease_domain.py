from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.schema_operations.domain import (
    SchemaOperationLease,
    SchemaOperationLeaseEffect,
    SchemaOperationLeaseExpired,
    SchemaOperationLeaseFenceConflict,
    SchemaOperationLeaseIdempotencyConflict,
    SchemaOperationLeaseInvalid,
    SchemaOperationLeaseState,
    SchemaOperationLeaseUnavailable,
    SchemaOperationPurpose,
    claim_schema_operation_lease,
    release_schema_operation_lease,
    renew_schema_operation_lease,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
CLAIM_A = UUID("92000000-0000-4000-8000-000000000001")
CLAIM_B = UUID("92000000-0000-4000-8000-000000000002")


def _available() -> SchemaOperationLease:
    return SchemaOperationLease.available(observed_at=NOW)


def _claim(
    current: SchemaOperationLease,
    *,
    claim_id: UUID = CLAIM_A,
    owner_id: str = "schema-worker-a",
    purpose: SchemaOperationPurpose = SchemaOperationPurpose.PROVISIONING,
    expected_row_version: int | None = None,
    expires_at: datetime | None = None,
    now: datetime = NOW,
):
    return claim_schema_operation_lease(
        current,
        claim_id=claim_id,
        owner_id=owner_id,
        purpose=purpose,
        expected_row_version=(
            current.row_version
            if expected_row_version is None
            else expected_row_version
        ),
        lease_expires_at=expires_at or NOW + timedelta(minutes=10),
        database_now=now,
    )


def test_claim_assigns_monotonic_generation_fence_and_exact_replay():
    initial = _available()
    claimed = _claim(initial)

    assert claimed.effect is SchemaOperationLeaseEffect.CLAIMED
    assert not claimed.idempotent_replay
    assert claimed.lease.state is SchemaOperationLeaseState.HELD
    assert (
        claimed.lease.generation,
        claimed.lease.fencing_token,
        claimed.lease.row_version,
    ) == (1, 1, 2)
    assert claimed.lease.last_claim_id == CLAIM_A
    assert len(claimed.lease.last_request_digest or b"") == 32

    replay = _claim(claimed.lease, expected_row_version=1)
    assert replay.idempotent_replay
    assert replay.lease == claimed.lease


def test_claim_replay_requires_the_exact_request_identity():
    claimed = _claim(_available()).lease

    with pytest.raises(SchemaOperationLeaseIdempotencyConflict):
        _claim(
            claimed,
            purpose=SchemaOperationPurpose.BACKUP,
            expected_row_version=1,
        )
    with pytest.raises(SchemaOperationLeaseIdempotencyConflict):
        _claim(
            claimed,
            expires_at=NOW + timedelta(minutes=11),
            expected_row_version=1,
        )


def test_different_purposes_share_one_mutex_and_expiry_allows_takeover():
    first = _claim(
        _available(),
        purpose=SchemaOperationPurpose.BACKUP,
        expires_at=NOW + timedelta(minutes=5),
    ).lease

    with pytest.raises(SchemaOperationLeaseUnavailable):
        _claim(
            first,
            claim_id=CLAIM_B,
            owner_id="restore-worker",
            purpose=SchemaOperationPurpose.RESTORE,
            expires_at=NOW + timedelta(minutes=20),
            now=NOW + timedelta(minutes=1),
        )

    takeover = _claim(
        first,
        claim_id=CLAIM_B,
        owner_id="restore-worker",
        purpose=SchemaOperationPurpose.RESTORE,
        expires_at=NOW + timedelta(minutes=20),
        now=NOW + timedelta(minutes=5),
    ).lease
    assert takeover.purpose is SchemaOperationPurpose.RESTORE
    assert (takeover.generation, takeover.fencing_token) == (2, 2)
    assert takeover.row_version == 3


def test_expired_owner_cannot_replay_or_renew():
    expiry = NOW + timedelta(minutes=5)
    claimed = _claim(_available(), expires_at=expiry).lease

    with pytest.raises(SchemaOperationLeaseExpired):
        _claim(
            claimed,
            expected_row_version=1,
            expires_at=expiry + timedelta(minutes=5),
            now=expiry,
        )
    with pytest.raises(SchemaOperationLeaseExpired):
        renew_schema_operation_lease(
            claimed,
            claim_id=CLAIM_A,
            owner_id="schema-worker-a",
            purpose=SchemaOperationPurpose.PROVISIONING,
            fencing_token=1,
            expected_row_version=2,
            lease_expires_at=NOW + timedelta(minutes=20),
            database_now=expiry,
        )


def test_renew_is_exactly_replayable_and_preserves_the_fence():
    claimed = _claim(_available()).lease
    new_expiry = NOW + timedelta(minutes=20)
    renewed = renew_schema_operation_lease(
        claimed,
        claim_id=CLAIM_A,
        owner_id="schema-worker-a",
        purpose=SchemaOperationPurpose.PROVISIONING,
        fencing_token=claimed.fencing_token,
        expected_row_version=claimed.row_version,
        lease_expires_at=new_expiry,
        database_now=NOW + timedelta(minutes=1),
    )
    assert renewed.effect is SchemaOperationLeaseEffect.RENEWED
    assert renewed.lease.expires_at == new_expiry
    assert renewed.lease.fencing_token == claimed.fencing_token
    assert renewed.lease.generation == claimed.generation
    assert renewed.lease.row_version == claimed.row_version + 1

    replay = renew_schema_operation_lease(
        renewed.lease,
        claim_id=CLAIM_A,
        owner_id="schema-worker-a",
        purpose=SchemaOperationPurpose.PROVISIONING,
        fencing_token=claimed.fencing_token,
        expected_row_version=claimed.row_version,
        lease_expires_at=new_expiry,
        database_now=NOW + timedelta(minutes=2),
    )
    assert replay.idempotent_replay
    assert replay.lease == renewed.lease


def test_renew_rejects_shortening_and_stale_fences():
    claimed = _claim(_available()).lease
    with pytest.raises(SchemaOperationLeaseInvalid):
        renew_schema_operation_lease(
            claimed,
            claim_id=CLAIM_A,
            owner_id="schema-worker-a",
            purpose=SchemaOperationPurpose.PROVISIONING,
            fencing_token=claimed.fencing_token,
            expected_row_version=claimed.row_version,
            lease_expires_at=claimed.expires_at,
            database_now=NOW + timedelta(minutes=1),
        )
    with pytest.raises(SchemaOperationLeaseFenceConflict):
        renew_schema_operation_lease(
            claimed,
            claim_id=CLAIM_A,
            owner_id="schema-worker-a",
            purpose=SchemaOperationPurpose.PROVISIONING,
            fencing_token=claimed.fencing_token + 1,
            expected_row_version=claimed.row_version,
            lease_expires_at=NOW + timedelta(minutes=20),
            database_now=NOW + timedelta(minutes=1),
        )


def test_release_exact_replay_and_claim_aba_are_fenced():
    claimed = _claim(_available()).lease
    released = release_schema_operation_lease(
        claimed,
        claim_id=CLAIM_A,
        owner_id="schema-worker-a",
        purpose=SchemaOperationPurpose.PROVISIONING,
        fencing_token=claimed.fencing_token,
        expected_row_version=claimed.row_version,
        database_now=NOW + timedelta(minutes=1),
    )
    assert released.effect is SchemaOperationLeaseEffect.RELEASED
    assert released.lease.state is SchemaOperationLeaseState.AVAILABLE
    assert released.lease.fencing_token == claimed.fencing_token

    replay = release_schema_operation_lease(
        released.lease,
        claim_id=CLAIM_A,
        owner_id="schema-worker-a",
        purpose=SchemaOperationPurpose.PROVISIONING,
        fencing_token=claimed.fencing_token,
        expected_row_version=claimed.row_version,
        database_now=NOW + timedelta(minutes=2),
    )
    assert replay.idempotent_replay

    with pytest.raises(SchemaOperationLeaseIdempotencyConflict):
        _claim(
            released.lease,
            claim_id=CLAIM_A,
            expected_row_version=1,
            now=NOW + timedelta(minutes=2),
            expires_at=NOW + timedelta(minutes=30),
        )


def test_stale_release_cannot_clear_a_takeover_owner():
    expiry = NOW + timedelta(minutes=5)
    first = _claim(_available(), expires_at=expiry).lease
    takeover = _claim(
        first,
        claim_id=CLAIM_B,
        owner_id="migration-worker",
        purpose=SchemaOperationPurpose.FLEET_MIGRATION,
        expires_at=NOW + timedelta(minutes=20),
        now=expiry,
    ).lease

    with pytest.raises(SchemaOperationLeaseFenceConflict):
        release_schema_operation_lease(
            takeover,
            claim_id=CLAIM_A,
            owner_id="schema-worker-a",
            purpose=SchemaOperationPurpose.PROVISIONING,
            fencing_token=first.fencing_token,
            expected_row_version=first.row_version,
            database_now=expiry + timedelta(seconds=1),
        )
    assert takeover.claim_id == CLAIM_B


def test_errors_are_fixed_and_do_not_echo_paths_or_credentials():
    sensitive = "/srv/backups/prod.sql:database-password"
    with pytest.raises(SchemaOperationLeaseInvalid) as captured:
        _claim(_available(), owner_id=sensitive)

    rendered = str(captured.value)
    assert rendered == SchemaOperationLeaseInvalid.public_message
    assert sensitive not in rendered


def test_clock_regression_fails_closed():
    claimed = _claim(_available()).lease
    with pytest.raises(SchemaOperationLeaseFenceConflict):
        release_schema_operation_lease(
            claimed,
            claim_id=CLAIM_A,
            owner_id="schema-worker-a",
            purpose=SchemaOperationPurpose.PROVISIONING,
            fencing_token=claimed.fencing_token,
            expected_row_version=claimed.row_version,
            database_now=NOW - timedelta(microseconds=1),
        )
