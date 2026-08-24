from dataclasses import replace
from uuid import UUID

import pytest

from inventory_control.action_payload import CanonicalActionPayload
from inventory_control.crypto import RootKey
from inventory_control.sensitive_actions import (
    SENSITIVE_ACTION_CANONICALIZATION_VERSION,
    SENSITIVE_ACTION_CONTEXT_MAC_VERSION,
    SensitiveActionContext,
    calculate_sensitive_action_context_mac,
    verify_sensitive_action_context_mac,
)
from inventory_control.sms import SmsPurpose


ROOT_KEY = RootKey(version=7, material=bytes(range(32)))
INTENT_UUID = UUID("51000000-0000-4000-8000-000000000001")
TENANT_UUID = UUID("51000000-0000-4000-8000-000000000002")
USER_UUID = UUID("51000000-0000-4000-8000-000000000003")
SESSION_UUID = UUID("51000000-0000-4000-8000-000000000004")
TARGET_UUID = UUID("51000000-0000-4000-8000-000000000005")


def _context() -> SensitiveActionContext:
    return SensitiveActionContext(
        intent_uuid=INTENT_UUID,
        tenant_uuid=TENANT_UUID,
        actor_user_uuid=USER_UUID,
        actor_session_uuid=SESSION_UUID,
        purpose=SmsPurpose.GRANT_ADMIN,
        action_subtype="membership.change_role",
        target_type="tenant_membership",
        target_uuid=TARGET_UUID,
        expected_target_revision="row:4",
        action_payload=CanonicalActionPayload.from_value(
            {"role": "admin", "enabled": True}
        ),
        idempotency_key="member-admin-change:1",
    )


def test_context_mac_is_stable_and_payload_redacting() -> None:
    context = _context()
    context_mac = calculate_sensitive_action_context_mac(
        root_key=ROOT_KEY,
        context=context,
    )

    assert context.canonicalization_version == (
        SENSITIVE_ACTION_CANONICALIZATION_VERSION
    )
    assert len(context_mac) == 32
    assert context_mac.hex() == (
        "375fdb049fd2b00587df6b7929c3c9e5"
        "3eeab66dfbae9a53500913bb7109b459"
    )
    assert verify_sensitive_action_context_mac(
        root_key=ROOT_KEY,
        context=context,
        expected_mac=context_mac,
        mac_version=SENSITIVE_ACTION_CONTEXT_MAC_VERSION,
    )
    rendered = repr(context)
    assert "enabled" not in rendered
    assert str(TARGET_UUID) not in rendered


@pytest.mark.parametrize(
    "changed",
    [
        {"tenant_uuid": UUID("52000000-0000-4000-8000-000000000001")},
        {"actor_user_uuid": UUID("52000000-0000-4000-8000-000000000002")},
        {"actor_session_uuid": UUID("52000000-0000-4000-8000-000000000003")},
        {"action_subtype": "membership.disable"},
        {"expected_target_revision": "row:5"},
        {"idempotency_key": "member-admin-change:2"},
        {
            "action_payload": CanonicalActionPayload.from_value(
                {"role": "operator", "enabled": True}
            )
        },
    ],
)
def test_context_mac_rejects_rebound_action_facts(changed) -> None:
    original = _context()
    context_mac = calculate_sensitive_action_context_mac(
        root_key=ROOT_KEY,
        context=original,
    )

    assert not verify_sensitive_action_context_mac(
        root_key=ROOT_KEY,
        context=replace(original, **changed),
        expected_mac=context_mac,
        mac_version=SENSITIVE_ACTION_CONTEXT_MAC_VERSION,
    )


def test_context_rejects_non_d48_purpose_and_noncanonical_payload() -> None:
    with pytest.raises(ValueError, match="not a D48 purpose"):
        replace(_context(), purpose=SmsPurpose.LOGIN)
    with pytest.raises(ValueError, match="unsupported value"):
        CanonicalActionPayload.from_value({"amount": 1.5})


def test_context_mac_verifier_fails_closed_for_wrong_protocol_inputs() -> None:
    context = _context()
    assert not verify_sensitive_action_context_mac(
        root_key=ROOT_KEY,
        context=context,
        expected_mac=b"short",
        mac_version=SENSITIVE_ACTION_CONTEXT_MAC_VERSION,
    )
    assert not verify_sensitive_action_context_mac(
        root_key=ROOT_KEY,
        context=context,
        expected_mac=bytes(32),
        mac_version=999,
    )
