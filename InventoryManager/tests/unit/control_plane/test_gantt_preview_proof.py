from __future__ import annotations

import base64
import json
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.crypto import RootKey
from inventory_control.proofs import (
    GANTT_PREVIEW_MAX_TTL_SECONDS,
    GANTT_PREVIEW_PURPOSE,
    GanttPreviewAuthority,
    GanttPreviewContent,
    GanttPreviewProofError,
    issue_gantt_preview_proof,
    verify_gantt_preview_proof,
)


ROOT_KEY = RootKey(version=3, material=bytes(range(32)))
NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)


def _authority(**changes):
    values = {
        "tenant_uuid": UUID("10000000-0000-4000-8000-000000000001"),
        "actor_user_uuid": UUID("10000000-0000-4000-8000-000000000002"),
        "actor_session_uuid": UUID("10000000-0000-4000-8000-000000000003"),
        "user_auth_version": 4,
        "tenant_access_version": 8,
        "tenant_timezone": "Asia/Shanghai",
        "recovery_run_uuid": UUID("10000000-0000-4000-8000-000000000004"),
        "recovery_hold_uuid": UUID("10000000-0000-4000-8000-000000000005"),
        "recovery_hold_revision": 2,
    }
    values.update(changes)
    return GanttPreviewAuthority(**values)


def _content():
    return GanttPreviewContent.from_values(
        snapshot_hash="ab" * 32,
        decisions=[
            {
                "predecessor_rental_id": 20,
                "successor_rental_id": 21,
                "action": "separate",
            },
            {
                "predecessor_rental_id": 10,
                "successor_rental_id": 11,
                "action": "keep",
            },
        ],
        assignments={20: 4, 10: 3},
        preview_date=date(2026, 8, 22),
        solver_version="cp-sat-v1",
    )


def test_round_trip_binds_authority_snapshot_and_normalized_action() -> None:
    token = issue_gantt_preview_proof(
        root_key=ROOT_KEY,
        authority=_authority(),
        content=_content(),
        database_now=NOW,
    )

    verified = verify_gantt_preview_proof(
        token=token,
        root_key=ROOT_KEY,
        expected_authority=_authority(),
        database_now=NOW + timedelta(seconds=599),
    )

    assert GANTT_PREVIEW_PURPOSE.endswith("/v1")
    assert GANTT_PREVIEW_MAX_TTL_SECONDS == 600
    assert verified.content == _content()
    assert verified.content.assignments_dict() == {10: 3, 20: 4}
    assert [row[0] for row in verified.content.decisions] == [10, 20]
    assert verified.expires_at == NOW + timedelta(seconds=600)
    assert ROOT_KEY._material_bytes().hex() not in token


@pytest.mark.parametrize("tenant_timezone", ["", "Not/A-Timezone", None])
def test_authority_rejects_missing_or_invalid_tenant_timezone(
    tenant_timezone,
) -> None:
    with pytest.raises(GanttPreviewProofError, match="authority"):
        _authority(tenant_timezone=tenant_timezone)


def test_signing_key_uses_the_approved_exact_purpose_domain_vector() -> None:
    token = issue_gantt_preview_proof(
        root_key=ROOT_KEY,
        authority=_authority(),
        content=_content(),
        database_now=NOW,
        action_uuid=UUID("30000000-0000-4000-8000-000000000001"),
    )

    assert GANTT_PREVIEW_PURPOSE == (
        "inventory-manager/tenant-gantt-reorder-preview/v1"
    )
    assert token.split(".")[1] == (
        "OyLrmWX4mmFWlo0znkIkZzTL80Lh0IoUrS3ayDbPrH4"
    )


@pytest.mark.parametrize(
    "changed_authority",
    [
        _authority(tenant_uuid=UUID("20000000-0000-4000-8000-000000000001")),
        _authority(actor_user_uuid=UUID("20000000-0000-4000-8000-000000000002")),
        _authority(
            actor_session_uuid=UUID("20000000-0000-4000-8000-000000000003")
        ),
        _authority(user_auth_version=5),
        _authority(tenant_access_version=9),
        _authority(tenant_timezone="UTC"),
        _authority(recovery_run_uuid=UUID("20000000-0000-4000-8000-000000000004")),
        _authority(recovery_hold_uuid=UUID("20000000-0000-4000-8000-000000000005")),
        _authority(recovery_hold_revision=3),
    ],
)
def test_cross_authority_and_stale_revision_replay_is_rejected(changed_authority) -> None:
    token = issue_gantt_preview_proof(
        root_key=ROOT_KEY,
        authority=_authority(),
        content=_content(),
        database_now=NOW,
    )

    with pytest.raises(GanttPreviewProofError, match="invalid or stale"):
        verify_gantt_preview_proof(
            token=token,
            root_key=ROOT_KEY,
            expected_authority=changed_authority,
            database_now=NOW,
        )


def test_expired_and_not_yet_valid_proofs_are_rejected() -> None:
    token = issue_gantt_preview_proof(
        root_key=ROOT_KEY,
        authority=_authority(),
        content=_content(),
        database_now=NOW,
        ttl=timedelta(seconds=10),
    )

    for now in (NOW - timedelta(seconds=1), NOW + timedelta(seconds=10)):
        with pytest.raises(GanttPreviewProofError):
            verify_gantt_preview_proof(
                token=token,
                root_key=ROOT_KEY,
                expected_authority=_authority(),
                database_now=now,
            )


def test_payload_and_signature_tampering_are_rejected() -> None:
    token = issue_gantt_preview_proof(
        root_key=ROOT_KEY,
        authority=_authority(),
        content=_content(),
        database_now=NOW,
    )
    payload_segment, signature_segment = token.split(".")

    def decode(segment):
        return base64.urlsafe_b64decode(segment + "=" * ((4 - len(segment) % 4) % 4))

    payload = json.loads(decode(payload_segment))
    payload["snapshot_hash"] = "cd" * 32
    tampered_payload_segment = base64.urlsafe_b64encode(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    tampered = [
        f"{tampered_payload_segment}.{signature_segment}",
        f"{payload_segment}.{'A' if signature_segment[0] != 'A' else 'B'}{signature_segment[1:]}",
    ]

    for candidate in tampered:
        with pytest.raises(GanttPreviewProofError):
            verify_gantt_preview_proof(
                token=candidate,
                root_key=ROOT_KEY,
                expected_authority=_authority(),
                database_now=NOW,
            )


def test_wrong_root_version_or_material_cannot_verify() -> None:
    token = issue_gantt_preview_proof(
        root_key=ROOT_KEY,
        authority=_authority(),
        content=_content(),
        database_now=NOW,
    )

    wrong_keys = [
        RootKey(version=4, material=bytes(range(32))),
        RootKey(version=3, material=b"x" * 32),
    ]
    for key in wrong_keys:
        with pytest.raises(GanttPreviewProofError):
            verify_gantt_preview_proof(
                token=token,
                root_key=key,
                expected_authority=_authority(),
                database_now=NOW,
            )


@pytest.mark.parametrize(
    "token",
    [None, "", "legacy-itsdangerous-token", "a.b.c", "!" * 100, "a" * 65_537],
)
def test_legacy_and_malformed_tokens_share_one_error(token) -> None:
    with pytest.raises(GanttPreviewProofError) as caught:
        verify_gantt_preview_proof(
            token=token,
            root_key=ROOT_KEY,
            expected_authority=_authority(),
            database_now=NOW,
        )
    assert str(caught.value) == "preview proof is invalid or stale"


@pytest.mark.parametrize(
    "ttl",
    [timedelta(0), timedelta(seconds=601), timedelta(microseconds=1)],
)
def test_issuer_rejects_unapproved_ttl(ttl) -> None:
    with pytest.raises(GanttPreviewProofError, match="TTL"):
        issue_gantt_preview_proof(
            root_key=ROOT_KEY,
            authority=_authority(),
            content=_content(),
            database_now=NOW,
            ttl=ttl,
        )
