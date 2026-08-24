from __future__ import annotations

from datetime import datetime, timedelta
from uuid import UUID

import pytest

from inventory_control.crypto import RootKey
from inventory_control.invitations import (
    INVITATION_DEFAULT_LIFETIME,
    InvitationTokenError,
    derive_admin_invitation_token,
    issue_invitation_token,
    rotate_invitation_token,
    verify_invitation_token,
)


NOW = datetime(2026, 8, 22, 12, 0)


def test_invitation_token_is_high_entropy_hashed_and_hidden_from_repr() -> None:
    issued = issue_invitation_token(database_now=NOW)

    assert len(issued.token.value) == 43
    assert len(issued.persisted.token_digest_sha256) == 32
    assert issued.token.value.encode("ascii") not in issued.persisted.token_digest_sha256
    assert issued.token.value not in repr(issued.token)
    assert issued.token.value not in repr(issued.persisted)
    assert issued.persisted.expires_at == NOW + timedelta(days=7)
    assert INVITATION_DEFAULT_LIFETIME == timedelta(days=7)


def test_rotation_invalidates_old_generation_and_refreshes_seven_days() -> None:
    first = issue_invitation_token(database_now=NOW)
    rotated_at = NOW + timedelta(days=2)
    second = rotate_invitation_token(first.persisted, database_now=rotated_at)

    assert second.persisted.generation == first.persisted.generation + 1
    assert second.persisted.expires_at == rotated_at + timedelta(days=7)
    assert second.token.value != first.token.value
    assert not verify_invitation_token(
        submitted_token=first.token.value,
        submitted_generation=first.persisted.generation,
        current=second.persisted,
        database_now=rotated_at,
    )
    assert verify_invitation_token(
        submitted_token=second.token.value,
        submitted_generation=second.persisted.generation,
        current=second.persisted,
        database_now=rotated_at,
    )


def test_expiry_is_effective_without_waiting_for_cleanup_job() -> None:
    issued = issue_invitation_token(database_now=NOW)

    assert verify_invitation_token(
        submitted_token=issued.token.value,
        submitted_generation=1,
        current=issued.persisted,
        database_now=issued.persisted.expires_at - timedelta(microseconds=1),
    )
    assert not verify_invitation_token(
        submitted_token=issued.token.value,
        submitted_generation=1,
        current=issued.persisted,
        database_now=issued.persisted.expires_at,
    )


@pytest.mark.parametrize(
    ("token", "generation"),
    [
        (None, 1),
        ("", 1),
        ("x" * 42, 1),
        ("x" * 44, 1),
        ("!" * 43, 1),
        ("x" * 43, 0),
        ("x" * 43, True),
        ("x" * 43, "1"),
    ],
)
def test_malformed_and_stale_inputs_have_one_false_result(token, generation) -> None:
    current = issue_invitation_token(database_now=NOW).persisted

    assert not verify_invitation_token(
        submitted_token=token,
        submitted_generation=generation,
        current=current,
        database_now=NOW,
    )


def test_issue_rejects_invalid_generation() -> None:
    with pytest.raises(InvitationTokenError):
        issue_invitation_token(database_now=NOW, generation=0)


def test_admin_invitation_action_token_is_stable_and_domain_separated() -> None:
    action = UUID("41000000-0000-4000-8000-000000000004")
    root = RootKey(version=3, material=b"a" * 32)

    first = derive_admin_invitation_token(root_key=root, action_uuid=action)
    replay = derive_admin_invitation_token(root_key=root, action_uuid=action)
    other_action = derive_admin_invitation_token(
        root_key=root,
        action_uuid=UUID("41000000-0000-4000-8000-000000000005"),
    )
    other_root = derive_admin_invitation_token(
        root_key=RootKey(version=4, material=b"b" * 32),
        action_uuid=action,
    )

    assert first.value == replay.value
    assert len(first.value) == 43
    assert first.value not in repr(first)
    assert first.value != other_action.value
    assert first.value != other_root.value
