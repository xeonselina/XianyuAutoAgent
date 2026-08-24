from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.routing import (
    ACCOUNT_MUTATION_ACCOUNT_ORDER,
    AccountCandidatePreparationProof,
    AccountGeneration,
    AccountKind,
    AccountLeaseEffectKind,
    AccountLoginState,
    AccountMutationFenceConflict,
    AccountMutationIdempotencyConflict,
    AccountMutationLease,
    AccountMutationLeaseExpired,
    AccountMutationLeaseUnavailable,
    AccountMutationOrderError,
    AccountMutationProofRejected,
    AccountMutationStateConflict,
    AccountRevocationProof,
    AccountRotationPurpose,
    AccountRotationState,
    AccountUnlockAuthority,
    AccountUnlockAuthorityProof,
    begin_account_candidate_testing,
    begin_previous_account_draining,
    claim_account_mutation_lease,
    fail_account_rotation,
    mark_account_candidate_prepared,
    order_account_kinds,
    release_account_mutation_lease,
    renew_account_mutation_lease,
    require_account_kind_order,
    revoke_previous_account,
    start_account_rotation,
    switch_account_candidate,
    verify_account_candidate,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
TENANT = UUID("80000000-0000-4000-8000-000000000001")
DATABASE = UUID("80000000-0000-4000-8000-000000000002")
ROTATION = UUID("80000000-0000-4000-8000-000000000003")
OWNER_A = "worker-a"
OWNER_B = "worker-b"
PREVIOUS = AccountGeneration(
    username="tenant_dml_g7",
    credential_generation=7,
    root_key_version=2,
    derivation_version=1,
)
CANDIDATE = AccountGeneration(
    username="tenant_dml_g8",
    credential_generation=8,
    root_key_version=3,
    derivation_version=2,
)


def _unclaimed(kind: AccountKind = AccountKind.DML) -> AccountMutationLease:
    return AccountMutationLease.unclaimed(
        tenant_uuid=TENANT,
        account_kind=kind,
    )


def _claim(
    *,
    kind: AccountKind = AccountKind.DML,
    purpose: AccountRotationPurpose = AccountRotationPurpose.SUSPENSION_RESOLVE,
    owner: str = OWNER_A,
    expires_at: datetime | None = None,
) -> AccountMutationLease:
    return claim_account_mutation_lease(
        _unclaimed(kind),
        owner=owner,
        purpose=purpose.value,
        expected_row_version=1,
        lease_expires_at=expires_at or NOW + timedelta(minutes=10),
        database_now=NOW,
    ).lease


def _start(
    lease: AccountMutationLease,
    *,
    purpose: AccountRotationPurpose = AccountRotationPurpose.SUSPENSION_RESOLVE,
    desired: AccountLoginState = AccountLoginState.LOCKED,
):
    return start_account_rotation(
        rotation_uuid=ROTATION,
        tenant_uuid=TENANT,
        database_uuid=DATABASE,
        account_kind=AccountKind.DML,
        purpose=purpose,
        previous=PREVIOUS,
        candidate=CANDIDATE,
        inherited_desired_login_state=desired,
        expected_tenant_access_version=13,
        expected_route_version=9,
        expected_login_state_version=6,
        lease=lease,
        database_now=NOW,
    )


def _preparation_proof(**changes) -> AccountCandidatePreparationProof:
    values = {
        "rotation_uuid": ROTATION,
        "tenant_uuid": TENANT,
        "database_uuid": DATABASE,
        "account_kind": AccountKind.DML,
        "candidate": CANDIDATE,
        "candidate_created": True,
        "candidate_locked": True,
        "candidate_unpublished": True,
    }
    values.update(changes)
    return AccountCandidatePreparationProof(**values)


def _unlock_proof(
    lease: AccountMutationLease,
    *,
    authority: AccountUnlockAuthority = AccountUnlockAuthority.SUSPENSION_RESOLVE,
    **changes,
) -> AccountUnlockAuthorityProof:
    values = {
        "rotation_uuid": ROTATION,
        "tenant_uuid": TENANT,
        "database_uuid": DATABASE,
        "account_kind": AccountKind.DML,
        "previous": PREVIOUS,
        "candidate": CANDIDATE,
        "authority": authority,
        "expected_tenant_access_version": 13,
        "expected_route_version": 9,
        "expected_login_state_version": 6,
        "lease_owner": OWNER_A,
        "lease_fencing_token": lease.fencing_token,
        "database_identity_verified": True,
        "positive_permissions_verified": True,
        "cross_schema_rejected": True,
        "candidate_unpublished": True,
        "other_generations_locked": True,
        "advisory_lock_held": True,
        "application_route_denied": True,
    }
    values.update(changes)
    return AccountUnlockAuthorityProof(**values)


def _revocation_proof(lease: AccountMutationLease, **changes):
    values = {
        "rotation_uuid": ROTATION,
        "tenant_uuid": TENANT,
        "database_uuid": DATABASE,
        "account_kind": AccountKind.DML,
        "previous": PREVIOUS,
        "candidate": CANDIDATE,
        "lease_owner": OWNER_A,
        "lease_fencing_token": lease.fencing_token,
        "candidate_published": True,
        "previous_locked": True,
        "previous_connections_drained": True,
        "previous_revoked": True,
    }
    values.update(changes)
    return AccountRevocationProof(**values)


def _prepared(lease: AccountMutationLease):
    started = _start(lease).rotation
    return mark_account_candidate_prepared(
        started,
        lease=lease,
        proof=_preparation_proof(),
        database_now=NOW,
    ).rotation


def _verified(lease: AccountMutationLease):
    prepared = _prepared(lease)
    testing = begin_account_candidate_testing(
        prepared,
        lease=lease,
        proof=_unlock_proof(lease),
        database_now=NOW,
    ).rotation
    return verify_account_candidate(
        testing,
        lease=lease,
        proof=_unlock_proof(lease),
        database_now=NOW,
    ).rotation


def test_lease_claim_is_fenced_and_exact_response_loss_replays():
    initial = _unclaimed()
    claimed = claim_account_mutation_lease(
        initial,
        owner=OWNER_A,
        purpose=AccountRotationPurpose.STANDARD.value,
        expected_row_version=1,
        lease_expires_at=NOW + timedelta(minutes=5),
        database_now=NOW,
    )
    assert claimed.effect is AccountLeaseEffectKind.CLAIMED
    assert claimed.lease.fencing_token == 1
    assert claimed.lease.row_version == 2

    replay = claim_account_mutation_lease(
        claimed.lease,
        owner=OWNER_A,
        purpose=AccountRotationPurpose.STANDARD.value,
        expected_row_version=1,
        lease_expires_at=NOW + timedelta(minutes=5),
        database_now=NOW + timedelta(seconds=1),
    )
    assert replay.idempotent_replay is True
    assert replay.lease is claimed.lease
    assert replay.effect is AccountLeaseEffectKind.NONE


def test_live_lease_blocks_competitor_then_expiry_allows_fenced_takeover():
    first = _claim(
        purpose=AccountRotationPurpose.STANDARD,
        expires_at=NOW + timedelta(minutes=5),
    )
    with pytest.raises(AccountMutationLeaseUnavailable) as caught:
        claim_account_mutation_lease(
            first,
            owner=OWNER_B,
            purpose=AccountRotationPurpose.STANDARD.value,
            expected_row_version=first.row_version,
            lease_expires_at=NOW + timedelta(minutes=10),
            database_now=NOW + timedelta(minutes=1),
        )
    assert OWNER_A not in str(caught.value)

    takeover = claim_account_mutation_lease(
        first,
        owner=OWNER_B,
        purpose=AccountRotationPurpose.STANDARD.value,
        expected_row_version=first.row_version,
        lease_expires_at=NOW + timedelta(minutes=15),
        database_now=NOW + timedelta(minutes=5),
    ).lease
    assert takeover.owner == OWNER_B
    assert takeover.fencing_token == first.fencing_token + 1
    assert takeover.row_version == first.row_version + 1

    with pytest.raises(AccountMutationFenceConflict):
        renew_account_mutation_lease(
            takeover,
            owner=OWNER_A,
            fencing_token=first.fencing_token,
            expected_row_version=takeover.row_version,
            lease_expires_at=NOW + timedelta(minutes=20),
            database_now=NOW + timedelta(minutes=6),
        )


def test_renew_and_release_preserve_token_and_are_replay_safe():
    claimed = _claim(purpose=AccountRotationPurpose.STANDARD)
    renewed = renew_account_mutation_lease(
        claimed,
        owner=OWNER_A,
        fencing_token=claimed.fencing_token,
        expected_row_version=claimed.row_version,
        lease_expires_at=NOW + timedelta(minutes=20),
        database_now=NOW + timedelta(minutes=1),
    )
    assert renewed.effect is AccountLeaseEffectKind.RENEWED
    assert renewed.lease.fencing_token == claimed.fencing_token
    replay = renew_account_mutation_lease(
        renewed.lease,
        owner=OWNER_A,
        fencing_token=claimed.fencing_token,
        expected_row_version=claimed.row_version,
        lease_expires_at=NOW + timedelta(minutes=20),
        database_now=NOW + timedelta(minutes=2),
    )
    assert replay.idempotent_replay

    released = release_account_mutation_lease(
        renewed.lease,
        owner=OWNER_A,
        fencing_token=claimed.fencing_token,
        expected_row_version=renewed.lease.row_version,
        database_now=NOW + timedelta(minutes=3),
    )
    assert released.effect is AccountLeaseEffectKind.RELEASED
    assert released.lease.owner is None
    assert released.lease.fencing_token == claimed.fencing_token
    release_replay = release_account_mutation_lease(
        released.lease,
        owner=OWNER_A,
        fencing_token=claimed.fencing_token,
        expected_row_version=renewed.lease.row_version,
        database_now=NOW + timedelta(minutes=4),
    )
    assert release_replay.idempotent_replay


def test_expired_owner_cannot_renew_or_release():
    claimed = _claim(
        purpose=AccountRotationPurpose.STANDARD,
        expires_at=NOW + timedelta(minutes=1),
    )
    with pytest.raises(AccountMutationLeaseExpired):
        renew_account_mutation_lease(
            claimed,
            owner=OWNER_A,
            fencing_token=claimed.fencing_token,
            expected_row_version=claimed.row_version,
            lease_expires_at=NOW + timedelta(minutes=10),
            database_now=NOW + timedelta(minutes=1),
        )
    with pytest.raises(AccountMutationLeaseExpired):
        release_account_mutation_lease(
            claimed,
            owner=OWNER_A,
            fencing_token=claimed.fencing_token,
            expected_row_version=claimed.row_version,
            database_now=NOW + timedelta(minutes=1),
        )


def test_multi_account_order_is_always_dml_then_platform_read():
    assert ACCOUNT_MUTATION_ACCOUNT_ORDER == (
        AccountKind.DML,
        AccountKind.PLATFORM_READ,
    )
    assert order_account_kinds(
        (AccountKind.PLATFORM_READ, AccountKind.DML)
    ) == (AccountKind.DML, AccountKind.PLATFORM_READ)
    assert require_account_kind_order(
        (AccountKind.DML, AccountKind.PLATFORM_READ)
    ) == (AccountKind.DML, AccountKind.PLATFORM_READ)
    with pytest.raises(AccountMutationOrderError):
        require_account_kind_order(
            (AccountKind.PLATFORM_READ, AccountKind.DML)
        )
    with pytest.raises(AccountMutationOrderError):
        order_account_kinds((AccountKind.DML, AccountKind.DML))


def test_rotation_creation_binds_fences_and_candidate_starts_locked_unpublished():
    lease = _claim()
    started = _start(lease)
    rotation = started.rotation
    assert rotation.state is AccountRotationState.PREPARING
    assert rotation.from_username == PREVIOUS.username
    assert rotation.to_username == CANDIDATE.username
    assert rotation.from_generation == 7
    assert rotation.to_generation == 8
    assert rotation.expected_tenant_access_version == 13
    assert rotation.expected_route_version == 9
    assert rotation.expected_login_state_version == 6
    assert rotation.lease_owner == OWNER_A
    assert rotation.lease_fencing_token == lease.fencing_token
    assert rotation.candidate_locked is True
    assert rotation.candidate_published is False
    assert started.effects.create_candidate_locked is True
    assert started.effects.candidate_must_remain_unpublished is True

    replay = start_account_rotation(
        current=rotation,
        rotation_uuid=ROTATION,
        tenant_uuid=TENANT,
        database_uuid=DATABASE,
        account_kind=AccountKind.DML,
        purpose=AccountRotationPurpose.SUSPENSION_RESOLVE,
        previous=PREVIOUS,
        candidate=CANDIDATE,
        inherited_desired_login_state=AccountLoginState.LOCKED,
        expected_tenant_access_version=13,
        expected_route_version=9,
        expected_login_state_version=6,
        lease=lease,
        database_now=lease.expires_at,
    )
    assert replay.idempotent_replay
    assert replay.rotation is rotation


def test_standard_rotation_in_locked_state_stops_at_prepared_locked():
    lease = _claim(purpose=AccountRotationPurpose.STANDARD)
    started = _start(
        lease,
        purpose=AccountRotationPurpose.STANDARD,
        desired=AccountLoginState.LOCKED,
    ).rotation
    prepared = mark_account_candidate_prepared(
        started,
        lease=lease,
        proof=_preparation_proof(),
        database_now=NOW,
    )
    assert prepared.rotation.state is AccountRotationState.PREPARED_LOCKED
    assert prepared.rotation.candidate_locked is True
    assert prepared.rotation.candidate_published is False

    with pytest.raises(AccountMutationStateConflict) as caught:
        begin_account_candidate_testing(
            prepared.rotation,
            lease=lease,
            proof=_unlock_proof(
                lease,
                authority=AccountUnlockAuthority.ACTIVE_ROTATION,
            ),
            database_now=NOW,
        )
    assert caught.value.effects.publish_candidate is False
    assert caught.value.effects.lock_candidate is True
    assert caught.value.effects.candidate_must_remain_unpublished is True


@pytest.mark.parametrize(
    "invalid_fact",
    [
        "database_identity_verified",
        "positive_permissions_verified",
        "cross_schema_rejected",
        "candidate_unpublished",
        "other_generations_locked",
        "advisory_lock_held",
        "application_route_denied",
    ],
)
def test_unlock_proof_failure_never_publishes_and_returns_safe_effects(
    invalid_fact,
):
    lease = _claim()
    prepared = _prepared(lease)
    proof = _unlock_proof(lease, **{invalid_fact: False})
    with pytest.raises(AccountMutationProofRejected) as caught:
        begin_account_candidate_testing(
            prepared,
            lease=lease,
            proof=proof,
            database_now=NOW,
        )
    effects = caught.value.effects
    assert effects.publish_candidate is False
    assert effects.lock_candidate is True
    assert effects.candidate_must_remain_unpublished is True
    assert effects.lock_other_generations is True
    assert effects.route_must_remain_denied is True
    assert prepared.candidate_published is False


def test_every_rotation_crash_boundary_replays_without_advancing_again():
    lease = _claim()
    started_transition = _start(lease)
    start_replay = start_account_rotation(
        current=started_transition.rotation,
        rotation_uuid=ROTATION,
        tenant_uuid=TENANT,
        database_uuid=DATABASE,
        account_kind=AccountKind.DML,
        purpose=AccountRotationPurpose.SUSPENSION_RESOLVE,
        previous=PREVIOUS,
        candidate=CANDIDATE,
        inherited_desired_login_state=AccountLoginState.LOCKED,
        expected_tenant_access_version=13,
        expected_route_version=9,
        expected_login_state_version=6,
        lease=lease,
        database_now=NOW,
    )
    assert start_replay.idempotent_replay

    prepared = mark_account_candidate_prepared(
        started_transition.rotation,
        lease=lease,
        proof=_preparation_proof(),
        database_now=NOW,
    )
    prepared_replay = mark_account_candidate_prepared(
        prepared.rotation,
        lease=lease,
        proof=_preparation_proof(),
        database_now=NOW,
    )
    assert prepared_replay.idempotent_replay

    testing = begin_account_candidate_testing(
        prepared.rotation,
        lease=lease,
        proof=_unlock_proof(lease),
        database_now=NOW,
    )
    testing_replay = begin_account_candidate_testing(
        testing.rotation,
        lease=lease,
        proof=_unlock_proof(lease),
        database_now=NOW,
    )
    assert testing_replay.idempotent_replay

    verified = verify_account_candidate(
        testing.rotation,
        lease=lease,
        proof=_unlock_proof(lease),
        database_now=NOW,
    )
    verified_replay = verify_account_candidate(
        verified.rotation,
        lease=lease,
        proof=_unlock_proof(lease),
        database_now=NOW,
    )
    assert verified_replay.idempotent_replay

    switched = switch_account_candidate(
        verified.rotation,
        lease=lease,
        proof=_unlock_proof(lease),
        database_now=NOW,
    )
    switched_replay = switch_account_candidate(
        switched.rotation,
        lease=lease,
        proof=_unlock_proof(lease),
        database_now=NOW,
    )
    assert switched_replay.idempotent_replay
    assert switched.effects.publish_candidate is True
    assert switched.effects.resulting_route_version == 10
    assert switched.rotation.previous_locked is True
    assert switched.rotation.candidate_published is True

    draining = begin_previous_account_draining(
        switched.rotation,
        lease=lease,
        database_now=NOW,
    )
    draining_replay = begin_previous_account_draining(
        draining.rotation,
        lease=lease,
        database_now=NOW,
    )
    assert draining_replay.idempotent_replay
    assert draining.effects.drain_previous_generation is True

    revoked = revoke_previous_account(
        draining.rotation,
        lease=lease,
        proof=_revocation_proof(lease),
        database_now=NOW,
    )
    revoked_replay = revoke_previous_account(
        revoked.rotation,
        lease=lease,
        proof=_revocation_proof(lease),
        database_now=NOW,
    )
    assert revoked_replay.idempotent_replay
    assert revoked.rotation.state is AccountRotationState.REVOKED
    assert revoked.rotation.previous_locked is True
    assert revoked.rotation.previous_revoked is True
    assert revoked.effects.revoke_previous_generation is True


def test_stale_token_or_expired_lease_cannot_switch_verified_candidate():
    lease = _claim(expires_at=NOW + timedelta(minutes=1))
    verified = _verified(lease)

    with pytest.raises(AccountMutationLeaseExpired) as expired:
        switch_account_candidate(
            verified,
            lease=lease,
            proof=_unlock_proof(lease),
            database_now=NOW + timedelta(minutes=1),
        )
    assert expired.value.effects.publish_candidate is False
    assert verified.candidate_published is False

    takeover = claim_account_mutation_lease(
        lease,
        owner=OWNER_B,
        purpose=AccountRotationPurpose.SUSPENSION_RESOLVE.value,
        expected_row_version=lease.row_version,
        lease_expires_at=NOW + timedelta(minutes=20),
        database_now=NOW + timedelta(minutes=1),
    ).lease
    with pytest.raises(AccountMutationFenceConflict) as fenced:
        switch_account_candidate(
            verified,
            lease=takeover,
            proof=_unlock_proof(lease),
            database_now=NOW + timedelta(minutes=2),
        )
    assert fenced.value.effects.publish_candidate is False
    assert fenced.value.effects.lock_other_generations is True


def test_out_of_order_or_changed_replay_is_rejected_without_publication():
    lease = _claim()
    prepared = _prepared(lease)
    with pytest.raises(AccountMutationStateConflict) as out_of_order:
        switch_account_candidate(
            prepared,
            lease=lease,
            proof=_unlock_proof(lease),
            database_now=NOW,
        )
    assert out_of_order.value.effects.publish_candidate is False

    testing = begin_account_candidate_testing(
        prepared,
        lease=lease,
        proof=_unlock_proof(lease),
        database_now=NOW,
    ).rotation
    changed = _unlock_proof(lease, expected_route_version=10)
    with pytest.raises(AccountMutationIdempotencyConflict) as conflict:
        begin_account_candidate_testing(
            testing,
            lease=lease,
            proof=changed,
            database_now=NOW,
        )
    assert conflict.value.effects.publish_candidate is False


def test_failed_boundary_converges_locked_and_replays_exactly():
    lease = _claim()
    prepared = _prepared(lease)
    failed = fail_account_rotation(
        prepared,
        lease=lease,
        safe_error_code="CANDIDATE_CONNECTION_FAILED",
        database_now=NOW,
    )
    assert failed.rotation.state is AccountRotationState.FAILED
    assert failed.rotation.candidate_locked is True
    assert failed.rotation.previous_locked is True
    assert failed.rotation.candidate_published is False
    assert failed.effects.route_must_remain_denied is True

    replay = fail_account_rotation(
        failed.rotation,
        lease=lease,
        safe_error_code="CANDIDATE_CONNECTION_FAILED",
        database_now=NOW + timedelta(hours=1),
    )
    assert replay.idempotent_replay
    with pytest.raises(AccountMutationIdempotencyConflict):
        fail_account_rotation(
            failed.rotation,
            lease=lease,
            safe_error_code="DIFFERENT_FAILURE",
            database_now=NOW,
        )


def test_protocol_values_do_not_contain_password_material():
    lease = _claim()
    rotation = _start(lease).rotation
    rendered = repr(rotation).lower()
    assert "password" not in rendered
    assert "ciphertext" not in rendered
    assert "secret" not in rendered
    assert not hasattr(rotation, "password")
