from dataclasses import FrozenInstanceError
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.invitations import (
    AcceptanceChallengeProof,
    CoordinatingUserStatus,
    InvitationLockKind,
    InvitationRole,
    InvitationStateError,
    InvitationStatus,
    PhoneInvitationAggregate,
    TenantSeatSnapshot,
    accept_invitation,
    create_or_rotate_invitation,
    expire_invitation,
    revoke_invitation,
    verify_invitation_token,
)


PHONE = "+8613800138000"
USER_ID = UUID("10000000-0000-4000-8000-000000000001")
TENANT_A = UUID("20000000-0000-4000-8000-000000000001")
TENANT_B = UUID("20000000-0000-4000-8000-000000000002")
INVITATION_A = UUID("30000000-0000-4000-8000-000000000001")
INVITATION_B = UUID("30000000-0000-4000-8000-000000000002")
INVITATION_C = UUID("30000000-0000-4000-8000-000000000003")
MEMBERSHIP_A = UUID("40000000-0000-4000-8000-000000000001")
MEMBERSHIP_B = UUID("40000000-0000-4000-8000-000000000002")
CHALLENGE_A = UUID("50000000-0000-4000-8000-000000000001")
CHALLENGE_B = UUID("50000000-0000-4000-8000-000000000002")
CREATE_A = UUID("60000000-0000-4000-8000-000000000001")
CREATE_B = UUID("60000000-0000-4000-8000-000000000002")
ROTATE_A = UUID("60000000-0000-4000-8000-000000000003")
REVOKE_A = UUID("60000000-0000-4000-8000-000000000004")
EXPIRE_A = UUID("60000000-0000-4000-8000-000000000005")
ACCEPT_A = UUID("60000000-0000-4000-8000-000000000006")
ACCEPT_B = UUID("60000000-0000-4000-8000-000000000007")
COMPETING_ACTION = UUID("60000000-0000-4000-8000-000000000008")
NOW = datetime(2026, 8, 22, 12, tzinfo=timezone.utc)


def _empty():
    return PhoneInvitationAggregate.empty(
        canonical_phone=PHONE,
        coordinating_user_id=USER_ID,
    )


def _seat(
    tenant_id,
    *,
    active=0,
    pending=0,
    now=NOW,
    revision=1,
):
    return TenantSeatSnapshot(
        tenant_id=tenant_id,
        active_memberships=active,
        unexpired_pending_invitations=pending,
        guard_revision=revision,
        counted_at=now,
    )


def _create(
    aggregate,
    *,
    tenant_id=TENANT_A,
    invitation_id=INVITATION_A,
    role=InvitationRole.OPERATOR,
    active=0,
    pending=0,
    now=NOW,
    action_id=CREATE_A,
    idempotency_key="create-a",
    digest=b"a" * 32,
    expected_revision=None,
):
    return create_or_rotate_invitation(
        aggregate,
        tenant_id=tenant_id,
        new_invitation_id=invitation_id,
        role=role,
        tenant_allows_invitations=True,
        seat_snapshot=_seat(
            tenant_id,
            active=active,
            pending=pending,
            now=now,
        ),
        database_now=now,
        action_id=action_id,
        idempotency_key=idempotency_key,
        request_digest=digest,
        expected_invitation_revision=expected_revision,
    )


def _two_tenant_pending():
    first = _create(
        _empty(),
        tenant_id=TENANT_A,
        invitation_id=INVITATION_A,
        role=InvitationRole.ADMIN,
        active=8,
        pending=0,
        action_id=CREATE_A,
        idempotency_key="create-a",
        digest=b"a" * 32,
    )
    second = _create(
        first.aggregate,
        tenant_id=TENANT_B,
        invitation_id=INVITATION_B,
        role=InvitationRole.OPERATOR,
        active=7,
        pending=0,
        action_id=CREATE_B,
        idempotency_key="create-b",
        digest=b"b" * 32,
    )
    return first, second


def _challenge(invitation, *, challenge_id=CHALLENGE_A, **overrides):
    values = {
        "challenge_id": challenge_id,
        "invitation_id": invitation.invitation_id,
        "token_generation": invitation.token_generation,
        "canonical_phone": invitation.canonical_phone,
        "verified": True,
        "unconsumed": True,
    }
    values.update(overrides)
    return AcceptanceChallengeProof(**values)


def _accept(
    aggregate,
    *,
    invitation_id,
    plaintext_token,
    membership_id,
    action_id,
    challenge_id,
    idempotency_key,
    digest,
    seat_snapshots,
    now=NOW,
    expected_revision=1,
):
    invitation = next(
        record
        for record in aggregate.invitations
        if record.invitation_id == invitation_id
    )
    return accept_invitation(
        aggregate,
        invitation_id=invitation_id,
        submitted_token=plaintext_token,
        submitted_generation=invitation.token_generation,
        challenge=_challenge(invitation, challenge_id=challenge_id),
        membership_id=membership_id,
        winning_tenant_join_allowed=True,
        seat_snapshots=seat_snapshots,
        database_now=now,
        action_id=action_id,
        idempotency_key=idempotency_key,
        request_digest=digest,
        expected_invitation_revision=expected_revision,
    )


def test_create_reserves_one_seat_and_uses_exact_seven_day_window():
    transition = _create(_empty(), active=9)

    invitation = transition.primary_invitation
    projection = transition.seat_projections[0]
    assert invitation.status is InvitationStatus.PENDING
    assert invitation.expires_at == NOW + timedelta(days=7)
    assert invitation.token_generation == 1
    assert invitation.coordinating_user_id == USER_ID
    assert projection.occupied_before == 9
    assert projection.occupied_after == 10
    assert projection.pending_invitations_after == 1
    assert transition.released_reservations == 0
    assert transition.converted_reservations == 0


def test_create_rejects_the_eleventh_seat_without_changing_aggregate():
    initial = _empty()

    with pytest.raises(InvitationStateError) as error:
        _create(initial, active=10)

    assert error.value.code == "MEMBER_SEAT_LIMIT_EXCEEDED"
    assert initial.invitations == ()
    assert initial.action_receipts == ()


def test_same_tenant_phone_rotation_keeps_one_reservation_and_invalidates_token():
    created = _create(_empty(), active=9)
    old_token = created.issued_token.token.value
    old_record = created.primary_invitation
    rotated_at = NOW + timedelta(days=2)

    rotated = _create(
        created.aggregate,
        invitation_id=INVITATION_C,
        active=9,
        pending=1,
        now=rotated_at,
        action_id=ROTATE_A,
        idempotency_key="rotate-a",
        digest=b"r" * 32,
        expected_revision=old_record.revision,
    )

    current = rotated.primary_invitation
    assert current.invitation_id == INVITATION_A
    assert current.revision == old_record.revision + 1
    assert current.token_generation == old_record.token_generation + 1
    assert current.expires_at == rotated_at + timedelta(days=7)
    assert rotated.seat_projections[0].occupied_before == 10
    assert rotated.seat_projections[0].occupied_after == 10
    assert not verify_invitation_token(
        submitted_token=old_token,
        submitted_generation=old_record.token_generation,
        current=current.token,
        database_now=rotated_at,
    )


def test_rotation_cannot_change_immutable_role():
    created = _create(_empty(), role=InvitationRole.OPERATOR)

    with pytest.raises(InvitationStateError) as error:
        _create(
            created.aggregate,
            role=InvitationRole.ADMIN,
            pending=1,
            action_id=ROTATE_A,
            idempotency_key="rotate-role",
            digest=b"x" * 32,
            expected_revision=created.primary_invitation.revision,
        )

    assert error.value.code == "INVITATION_ROLE_IMMUTABLE"


def test_create_at_expiry_boundary_terminalizes_old_record_and_reserves_once():
    created = _create(_empty(), active=9)
    boundary = created.primary_invitation.expires_at

    replacement = _create(
        created.aggregate,
        invitation_id=INVITATION_C,
        role=InvitationRole.ADMIN,
        active=9,
        pending=0,
        now=boundary,
        action_id=ROTATE_A,
        idempotency_key="create-after-expiry",
        digest=b"n" * 32,
        expected_revision=created.primary_invitation.revision,
    )

    old = next(
        record
        for record in replacement.aggregate.invitations
        if record.invitation_id == INVITATION_A
    )
    assert old.status is InvitationStatus.EXPIRED
    assert old.coordinating_user_id is None
    assert replacement.primary_invitation.invitation_id == INVITATION_C
    assert replacement.primary_invitation.role is InvitationRole.ADMIN
    assert replacement.seat_projections[0].occupied_after == 10
    assert replacement.released_reservations == 1


def test_competing_create_from_stale_absent_revision_does_not_rotate_winner():
    first = _create(_empty())

    with pytest.raises(InvitationStateError) as error:
        _create(
            first.aggregate,
            invitation_id=INVITATION_C,
            action_id=COMPETING_ACTION,
            idempotency_key="competing-create",
            digest=b"c" * 32,
            pending=1,
            expected_revision=None,
        )

    assert error.value.code == "STALE_INVITATION_REVISION"
    assert first.primary_invitation.token_generation == 1


def test_create_retry_is_idempotent_and_does_not_rotate_or_reserve_again():
    first = _create(_empty(), active=9)

    retry = _create(
        first.aggregate,
        invitation_id=INVITATION_C,
        active=10,
        pending=99,
        action_id=CREATE_A,
        idempotency_key="create-a",
        digest=b"a" * 32,
        expected_revision=None,
    )

    assert retry.idempotent
    assert retry.aggregate == first.aggregate
    assert retry.primary_invitation.token_generation == 1
    assert retry.issued_token is None
    assert retry.seat_projections == ()


def test_same_idempotency_scope_with_changed_digest_fails_closed():
    first = _create(_empty())

    with pytest.raises(InvitationStateError) as error:
        _create(
            first.aggregate,
            action_id=COMPETING_ACTION,
            idempotency_key="create-a",
            digest=b"z" * 32,
            pending=1,
            expected_revision=1,
        )

    assert error.value.code == "INVITATION_IDEMPOTENCY_CONFLICT"


def test_revoke_releases_exactly_one_unexpired_reservation_and_is_idempotent():
    created = _create(_empty())
    revoke_at = NOW + timedelta(hours=1)
    revoked = revoke_invitation(
        created.aggregate,
        invitation_id=INVITATION_A,
        seat_snapshot=_seat(TENANT_A, active=7, pending=3, now=revoke_at),
        database_now=revoke_at,
        action_id=REVOKE_A,
        idempotency_key="revoke-a",
        request_digest=b"v" * 32,
        expected_invitation_revision=1,
    )

    assert revoked.primary_invitation.status is InvitationStatus.REVOKED
    assert revoked.primary_invitation.coordinating_user_id is None
    assert revoked.seat_projections[0].pending_invitations_after == 2
    assert revoked.released_reservations == 1

    retry = revoke_invitation(
        revoked.aggregate,
        invitation_id=INVITATION_A,
        seat_snapshot=_seat(TENANT_A, active=7, pending=2, now=revoke_at),
        database_now=revoke_at,
        action_id=REVOKE_A,
        idempotency_key="revoke-a",
        request_digest=b"v" * 32,
        expected_invitation_revision=1,
    )
    assert retry.idempotent
    assert retry.aggregate == revoked.aggregate


def test_expiry_rejects_early_cleanup_and_releases_at_exact_boundary():
    created = _create(_empty())
    deadline = created.primary_invitation.expires_at

    with pytest.raises(InvitationStateError) as early_error:
        expire_invitation(
            created.aggregate,
            invitation_id=INVITATION_A,
            seat_snapshot=_seat(TENANT_A, pending=1, now=deadline - timedelta(microseconds=1)),
            database_now=deadline - timedelta(microseconds=1),
            action_id=EXPIRE_A,
            idempotency_key="expire-a",
            request_digest=b"e" * 32,
            expected_invitation_revision=1,
        )
    assert early_error.value.code == "INVITATION_NOT_EXPIRED"

    expired = expire_invitation(
        created.aggregate,
        invitation_id=INVITATION_A,
        seat_snapshot=_seat(TENANT_A, active=7, pending=2, now=deadline),
        database_now=deadline,
        action_id=EXPIRE_A,
        idempotency_key="expire-a",
        request_digest=b"e" * 32,
        expected_invitation_revision=1,
    )
    assert expired.primary_invitation.status is InvitationStatus.EXPIRED
    assert expired.seat_projections[0].pending_invitations_after == 2
    assert expired.released_reservations == 1


def test_accept_converts_winner_reservation_and_supersedes_other_tenants_atomically():
    first, pending = _two_tenant_pending()
    winner_token = first.issued_token.token.value

    accepted = _accept(
        pending.aggregate,
        invitation_id=INVITATION_A,
        plaintext_token=winner_token,
        membership_id=MEMBERSHIP_A,
        action_id=ACCEPT_A,
        challenge_id=CHALLENGE_A,
        idempotency_key="accept-a",
        digest=b"w" * 32,
        seat_snapshots=(
            _seat(TENANT_B, active=7, pending=1),
            _seat(TENANT_A, active=8, pending=1),
        ),
    )

    by_id = {
        invitation.invitation_id: invitation
        for invitation in accepted.aggregate.invitations
    }
    assert by_id[INVITATION_A].status is InvitationStatus.ACCEPTED
    assert by_id[INVITATION_B].status is InvitationStatus.SUPERSEDED
    assert all(
        invitation.coordinating_user_id is None
        for invitation in accepted.aggregate.invitations
    )
    assert accepted.aggregate.membership.membership_id == MEMBERSHIP_A
    assert accepted.aggregate.membership.tenant_id == TENANT_A
    assert accepted.aggregate.membership.role is InvitationRole.ADMIN
    assert accepted.aggregate.user_status is CoordinatingUserStatus.ACTIVE
    assert accepted.membership_created
    assert accepted.challenge_consumed
    assert accepted.converted_reservations == 1
    assert accepted.released_reservations == 1
    assert accepted.invalidated_invitation_ids == (INVITATION_B,)

    projections = {
        projection.tenant_id: projection
        for projection in accepted.seat_projections
    }
    assert projections[TENANT_A].active_memberships_after == 9
    assert projections[TENANT_A].pending_invitations_after == 0
    assert projections[TENANT_A].occupied_before == 9
    assert projections[TENANT_A].occupied_after == 9
    assert projections[TENANT_B].occupied_before == 8
    assert projections[TENANT_B].occupied_after == 7


def test_acceptance_lock_plan_places_all_tenants_before_same_order_guards():
    first, pending = _two_tenant_pending()
    accepted = _accept(
        pending.aggregate,
        invitation_id=INVITATION_A,
        plaintext_token=first.issued_token.token.value,
        membership_id=MEMBERSHIP_A,
        action_id=ACCEPT_A,
        challenge_id=CHALLENGE_A,
        idempotency_key="accept-a",
        digest=b"w" * 32,
        seat_snapshots=(
            _seat(TENANT_A, active=8, pending=1),
            _seat(TENANT_B, active=7, pending=1),
        ),
    )

    targets = accepted.lock_plan.targets
    kinds = [target.kind for target in targets]
    assert kinds[0] is InvitationLockKind.PHONE_IDENTITY
    tenant_targets = [
        target.resource_id
        for target in targets
        if target.kind is InvitationLockKind.TENANT
    ]
    guard_targets = [
        target.resource_id.split(":member_seats")[0]
        for target in targets
        if target.kind is InvitationLockKind.MEMBER_SEAT_GUARD
    ]
    assert tenant_targets == sorted((str(TENANT_A), str(TENANT_B)))
    assert guard_targets == tenant_targets
    assert max(
        index
        for index, kind in enumerate(kinds)
        if kind is InvitationLockKind.TENANT
    ) < min(
        index
        for index, kind in enumerate(kinds)
        if kind is InvitationLockKind.MEMBER_SEAT_GUARD
    )
    assert kinds[-2:] == [
        InvitationLockKind.CHALLENGE,
        InvitationLockKind.MEMBERSHIP,
    ]


def test_first_committed_membership_wins_and_loser_cannot_revive_invitation():
    first, pending = _two_tenant_pending()
    accepted = _accept(
        pending.aggregate,
        invitation_id=INVITATION_A,
        plaintext_token=first.issued_token.token.value,
        membership_id=MEMBERSHIP_A,
        action_id=ACCEPT_A,
        challenge_id=CHALLENGE_A,
        idempotency_key="accept-a",
        digest=b"w" * 32,
        seat_snapshots=(
            _seat(TENANT_A, active=8, pending=1),
            _seat(TENANT_B, active=7, pending=1),
        ),
    )

    with pytest.raises(InvitationStateError) as loser_error:
        _accept(
            accepted.aggregate,
            invitation_id=INVITATION_B,
            plaintext_token=pending.issued_token.token.value,
            membership_id=MEMBERSHIP_B,
            action_id=ACCEPT_B,
            challenge_id=CHALLENGE_B,
            idempotency_key="accept-b",
            digest=b"l" * 32,
            seat_snapshots=(
                _seat(TENANT_A, active=9, pending=0),
                _seat(TENANT_B, active=7, pending=0),
            ),
        )
    assert loser_error.value.code == "PHONE_MEMBERSHIP_ALREADY_CLAIMED"
    loser = next(
        invitation
        for invitation in accepted.aggregate.invitations
        if invitation.invitation_id == INVITATION_B
    )
    assert loser.status is InvitationStatus.SUPERSEDED


def test_losing_tenant_cleanup_requires_no_join_gate_or_permission_creation():
    first, pending = _two_tenant_pending()

    accepted = _accept(
        pending.aggregate,
        invitation_id=INVITATION_A,
        plaintext_token=first.issued_token.token.value,
        membership_id=MEMBERSHIP_A,
        action_id=ACCEPT_A,
        challenge_id=CHALLENGE_A,
        idempotency_key="accept-a",
        digest=b"w" * 32,
        seat_snapshots=(
            _seat(TENANT_A, active=8, pending=1),
            _seat(TENANT_B, active=9, pending=1),
        ),
    )

    loser_projection = next(
        projection
        for projection in accepted.seat_projections
        if projection.tenant_id == TENANT_B
    )
    assert loser_projection.occupied_before == 10
    assert loser_projection.occupied_after == 9
    assert accepted.aggregate.membership.tenant_id == TENANT_A
    assert all(
        claim.tenant_id == TENANT_A
        for claim in (accepted.aggregate.membership,)
    )


def test_acceptance_rejects_incomplete_seat_snapshots_without_consuming_challenge():
    first, pending = _two_tenant_pending()

    with pytest.raises(InvitationStateError) as error:
        _accept(
            pending.aggregate,
            invitation_id=INVITATION_A,
            plaintext_token=first.issued_token.token.value,
            membership_id=MEMBERSHIP_A,
            action_id=ACCEPT_A,
            challenge_id=CHALLENGE_A,
            idempotency_key="accept-a",
            digest=b"w" * 32,
            seat_snapshots=(_seat(TENANT_A, active=8, pending=1),),
        )

    assert error.value.code == "SEAT_SNAPSHOT_INCOMPLETE"
    assert pending.aggregate.membership is None
    assert all(
        invitation.status is InvitationStatus.PENDING
        for invitation in pending.aggregate.invitations
    )


def test_acceptance_rejects_invalid_eleventh_seat_current_read():
    created = _create(_empty(), active=9)

    with pytest.raises(InvitationStateError) as error:
        _accept(
            created.aggregate,
            invitation_id=INVITATION_A,
            plaintext_token=created.issued_token.token.value,
            membership_id=MEMBERSHIP_A,
            action_id=ACCEPT_A,
            challenge_id=CHALLENGE_A,
            idempotency_key="accept-over-cap",
            digest=b"o" * 32,
            seat_snapshots=(_seat(TENANT_A, active=10, pending=1),),
        )

    assert error.value.code == "MEMBER_SEAT_LIMIT_EXCEEDED"
    assert created.aggregate.membership is None


def test_acceptance_requires_current_token_generation_and_bound_challenge():
    created = _create(_empty())
    old_token = created.issued_token.token.value
    rotated = _create(
        created.aggregate,
        pending=1,
        action_id=ROTATE_A,
        idempotency_key="rotate-a",
        digest=b"r" * 32,
        expected_revision=1,
    )
    current = rotated.primary_invitation

    with pytest.raises(InvitationStateError) as token_error:
        accept_invitation(
            rotated.aggregate,
            invitation_id=INVITATION_A,
            submitted_token=old_token,
            submitted_generation=1,
            challenge=_challenge(current),
            membership_id=MEMBERSHIP_A,
            winning_tenant_join_allowed=True,
            seat_snapshots=(_seat(TENANT_A, pending=1),),
            database_now=NOW,
            action_id=ACCEPT_A,
            idempotency_key="accept-old-token",
            request_digest=b"t" * 32,
            expected_invitation_revision=2,
        )
    assert token_error.value.code == "INVITATION_CREDENTIAL_INVALID"

    with pytest.raises(InvitationStateError) as challenge_error:
        accept_invitation(
            rotated.aggregate,
            invitation_id=INVITATION_A,
            submitted_token=rotated.issued_token.token.value,
            submitted_generation=2,
            challenge=_challenge(current, token_generation=1),
            membership_id=MEMBERSHIP_A,
            winning_tenant_join_allowed=True,
            seat_snapshots=(_seat(TENANT_A, pending=1),),
            database_now=NOW,
            action_id=ACCEPT_A,
            idempotency_key="accept-old-challenge",
            request_digest=b"h" * 32,
            expected_invitation_revision=2,
        )
    assert challenge_error.value.code == "INVITATION_CREDENTIAL_INVALID"


def test_acceptance_expiry_boundary_fails_closed_without_membership():
    created = _create(_empty())
    deadline = created.primary_invitation.expires_at

    with pytest.raises(InvitationStateError) as error:
        _accept(
            created.aggregate,
            invitation_id=INVITATION_A,
            plaintext_token=created.issued_token.token.value,
            membership_id=MEMBERSHIP_A,
            action_id=ACCEPT_A,
            challenge_id=CHALLENGE_A,
            idempotency_key="accept-expired",
            digest=b"e" * 32,
            seat_snapshots=(_seat(TENANT_A, pending=0, now=deadline),),
            now=deadline,
        )

    assert error.value.code == "INVITATION_EXPIRED"
    assert created.aggregate.membership is None


def test_acceptance_retry_returns_original_membership_without_consuming_again():
    first, pending = _two_tenant_pending()
    accepted = _accept(
        pending.aggregate,
        invitation_id=INVITATION_A,
        plaintext_token=first.issued_token.token.value,
        membership_id=MEMBERSHIP_A,
        action_id=ACCEPT_A,
        challenge_id=CHALLENGE_A,
        idempotency_key="accept-a",
        digest=b"w" * 32,
        seat_snapshots=(
            _seat(TENANT_A, active=8, pending=1),
            _seat(TENANT_B, active=7, pending=1),
        ),
    )

    retry = accept_invitation(
        accepted.aggregate,
        invitation_id=INVITATION_A,
        submitted_token="invalid",
        submitted_generation=0,
        challenge=_challenge(accepted.primary_invitation),
        membership_id=MEMBERSHIP_A,
        winning_tenant_join_allowed=False,
        seat_snapshots=(),
        database_now=NOW + timedelta(days=30),
        action_id=ACCEPT_A,
        idempotency_key="accept-a",
        request_digest=b"w" * 32,
        expected_invitation_revision=1,
    )

    assert retry.idempotent
    assert retry.aggregate == accepted.aggregate
    assert retry.aggregate.membership.membership_id == MEMBERSHIP_A
    assert retry.membership_created is False
    assert retry.challenge_consumed is False


def test_stale_revision_loses_after_rotation_without_consuming_invitation():
    created = _create(_empty())
    rotated = _create(
        created.aggregate,
        pending=1,
        action_id=ROTATE_A,
        idempotency_key="rotate-a",
        digest=b"r" * 32,
        expected_revision=1,
    )

    with pytest.raises(InvitationStateError) as error:
        _accept(
            rotated.aggregate,
            invitation_id=INVITATION_A,
            plaintext_token=rotated.issued_token.token.value,
            membership_id=MEMBERSHIP_A,
            action_id=ACCEPT_A,
            challenge_id=CHALLENGE_A,
            idempotency_key="accept-stale",
            digest=b"s" * 32,
            seat_snapshots=(_seat(TENANT_A, pending=1),),
            expected_revision=1,
        )

    assert error.value.code == "STALE_INVITATION_REVISION"
    assert rotated.primary_invitation.status is InvitationStatus.PENDING


def test_times_are_normalized_to_utc_and_naive_database_time_is_rejected():
    shanghai_now = datetime(
        2026,
        8,
        22,
        20,
        tzinfo=timezone(timedelta(hours=8)),
    )
    created = _create(_empty(), now=shanghai_now)

    assert created.primary_invitation.expires_at == NOW + timedelta(days=7)
    assert created.seat_projections[0].occupied_after == 1

    with pytest.raises(InvitationStateError) as error:
        _create(
            _empty(),
            now=NOW.replace(tzinfo=None),
            action_id=COMPETING_ACTION,
            idempotency_key="naive-time",
            digest=b"n" * 32,
        )
    assert error.value.code == "INVITATION_TIME_MUST_BE_TIMEZONE_AWARE"


def test_disabled_identity_and_unknown_phone_fail_before_invitation_creation():
    disabled = PhoneInvitationAggregate.empty(
        canonical_phone=PHONE,
        coordinating_user_id=USER_ID,
        user_status=CoordinatingUserStatus.DISABLED,
    )
    with pytest.raises(InvitationStateError) as disabled_error:
        _create(disabled)
    assert disabled_error.value.code == "INVITATION_IDENTITY_INELIGIBLE"

    with pytest.raises(ValueError, match="canonical_phone"):
        PhoneInvitationAggregate.empty(
            canonical_phone="13800138000",
            coordinating_user_id=USER_ID,
        )


def test_records_aggregate_seat_projection_and_lock_plan_are_immutable():
    first, pending = _two_tenant_pending()
    accepted = _accept(
        pending.aggregate,
        invitation_id=INVITATION_A,
        plaintext_token=first.issued_token.token.value,
        membership_id=MEMBERSHIP_A,
        action_id=ACCEPT_A,
        challenge_id=CHALLENGE_A,
        idempotency_key="accept-a",
        digest=b"w" * 32,
        seat_snapshots=(
            _seat(TENANT_A, active=8, pending=1),
            _seat(TENANT_B, active=7, pending=1),
        ),
    )

    with pytest.raises(FrozenInstanceError):
        accepted.primary_invitation.status = InvitationStatus.PENDING
    with pytest.raises(FrozenInstanceError):
        accepted.aggregate.membership = None
    with pytest.raises(FrozenInstanceError):
        accepted.seat_projections[0].active_memberships_after = 99
    with pytest.raises(FrozenInstanceError):
        accepted.lock_plan.targets = ()
