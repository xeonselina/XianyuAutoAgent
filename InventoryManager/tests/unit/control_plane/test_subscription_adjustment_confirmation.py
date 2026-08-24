from __future__ import annotations

import base64
import json
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.crypto import RootKey
from inventory_control.proofs import (
    SubscriptionAdjustmentConfirmationError,
    SubscriptionAdjustmentFences,
    issue_subscription_adjustment_confirmation,
    subscription_adjustment_preview_digest,
    verify_subscription_adjustment_confirmation,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
ROOT_KEY = RootKey(version=1, material=bytes(range(32)))
ACTOR_ID = UUID("c1000000-0000-4000-8000-000000000001")
SESSION_ID = UUID("c1000000-0000-4000-8000-000000000002")
ACTION_ID = UUID("c1000000-0000-4000-8000-000000000003")


def _fences(**overrides) -> SubscriptionAdjustmentFences:
    values = {
        "tenant_uuid": UUID("c1000000-0000-4000-8000-000000000010"),
        "tenant_row_version": 4,
        "tenant_access_version": 7,
        "subscription_uuid": UUID("c1000000-0000-4000-8000-000000000011"),
        "subscription_row_version": 3,
        "recovery_run_uuid": UUID("c1000000-0000-4000-8000-000000000012"),
        "recovery_run_row_version": 2,
        "recovery_hold_uuid": UUID("c1000000-0000-4000-8000-000000000013"),
        "recovery_hold_revision": 5,
        "recovery_hold_row_version": 6,
        "deletion_request_uuid": None,
        "deletion_request_revision": None,
        "deletion_row_version": None,
        "suspension_uuid": None,
        "suspension_row_version": None,
        "suspension_generation": None,
        "suspension_action_uuid": None,
        "suspension_action_row_version": None,
    }
    values.update(overrides)
    return SubscriptionAdjustmentFences(**values)


def _issue(**overrides) -> str:
    values = {
        "root_key": ROOT_KEY,
        "fences": _fences(),
        "platform_actor_uuid": ACTOR_ID,
        "platform_session_uuid": SESSION_ID,
        "platform_auth_version": 8,
        "request_digest": b"r" * 32,
        "preview_digest": b"p" * 32,
        "database_now": NOW,
        "action_uuid": ACTION_ID,
    }
    values.update(overrides)
    return issue_subscription_adjustment_confirmation(**values)


def _verify(token: object, **overrides):
    values = {
        "token": token,
        "root_key": ROOT_KEY,
        "expected_platform_actor_uuid": ACTOR_ID,
        "expected_platform_session_uuid": SESSION_ID,
        "expected_platform_auth_version": 8,
        "expected_request_digest": b"r" * 32,
        "database_now": NOW + timedelta(seconds=1),
    }
    values.update(overrides)
    return verify_subscription_adjustment_confirmation(**values)


def test_confirmation_round_trip_binds_optional_lifecycle_fences():
    fences = _fences(
        suspension_uuid=UUID("c1000000-0000-4000-8000-000000000020"),
        suspension_row_version=9,
        suspension_generation=4,
        suspension_action_uuid=UUID(
            "c1000000-0000-4000-8000-000000000021"
        ),
        suspension_action_row_version=2,
    )

    verified = _verify(_issue(fences=fences))

    assert verified.action_uuid == ACTION_ID
    assert verified.fences == fences
    assert verified.request_digest == b"r" * 32
    assert verified.preview_digest == b"p" * 32
    assert verified.expires_at - verified.issued_at == timedelta(minutes=5)
    assert "rrrr" not in repr(verified)


@pytest.mark.parametrize(
    "override",
    [
        {"expected_platform_actor_uuid": UUID("c1000000-0000-4000-8000-000000000099")},
        {"expected_platform_session_uuid": UUID("c1000000-0000-4000-8000-000000000099")},
        {"expected_platform_auth_version": 9},
        {"expected_request_digest": b"x" * 32},
        {"database_now": NOW + timedelta(minutes=5)},
        {"root_key": RootKey(version=2, material=bytes(reversed(range(32))))},
    ],
)
def test_confirmation_rejects_changed_authority_request_expiry_or_key(override):
    with pytest.raises(SubscriptionAdjustmentConfirmationError):
        _verify(_issue(), **override)


def test_confirmation_rejects_canonical_payload_tampering():
    token = _issue()
    payload_segment, signature_segment = token.split(".")
    padding = "=" * ((4 - len(payload_segment) % 4) % 4)
    payload = json.loads(
        base64.urlsafe_b64decode(payload_segment + padding).decode("ascii")
    )
    payload["subscription_row_version"] = 99
    changed = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).rstrip(b"=").decode("ascii")

    with pytest.raises(SubscriptionAdjustmentConfirmationError):
        _verify(f"{changed}.{signature_segment}")


def test_preview_digest_is_deterministic_and_changes_with_visible_result():
    values = {
        "database_effective_at": NOW,
        "calculation_base_at": NOW + timedelta(days=2),
        "before_expires_at": NOW + timedelta(days=2),
        "after_expires_at": NOW + timedelta(days=5),
        "before_status": "active",
        "after_status": "active",
    }
    first = subscription_adjustment_preview_digest(**values)
    assert first == subscription_adjustment_preview_digest(**values)
    assert len(first) == 32
    assert first != subscription_adjustment_preview_digest(
        **{**values, "after_expires_at": NOW + timedelta(days=6)}
    )


def test_fences_reject_partially_present_optional_aggregate():
    with pytest.raises(SubscriptionAdjustmentConfirmationError):
        _fences(
            suspension_uuid=UUID(
                "c1000000-0000-4000-8000-000000000020"
            )
        )
