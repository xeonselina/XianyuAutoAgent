from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from uuid import UUID

import pytest

from inventory_control.crypto import RootKey, derive_provider_account_fingerprint
from inventory_control.domain import EffectiveTenantGate, TenantRole
from inventory_control.integrations import (
    SfAccountClaim,
    SfAdminClaimProof,
    SfClaimAuthorityDenied,
    SfClaimEventKind,
    SfClaimFenceConflict,
    SfClaimIdempotencyConflict,
    SfClaimOwner,
    SfClaimState,
    SfClaimUnavailable,
    SfDeletionClaimProof,
    activate_sf_claim,
    release_sf_claim,
    reserve_sf_claim,
)


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
CLAIM = UUID("10000000-0000-4000-8000-000000000001")
TENANT_A = UUID("10000000-0000-4000-8000-000000000002")
TENANT_B = UUID("10000000-0000-4000-8000-000000000003")
ACCOUNT_A = UUID("10000000-0000-4000-8000-000000000004")
ACCOUNT_B = UUID("10000000-0000-4000-8000-000000000005")
WAREHOUSE_A = UUID("10000000-0000-4000-8000-000000000006")
WAREHOUSE_B = UUID("10000000-0000-4000-8000-000000000007")
USER = UUID("10000000-0000-4000-8000-000000000008")
SESSION = UUID("10000000-0000-4000-8000-000000000009")
OTP = UUID("10000000-0000-4000-8000-00000000000a")
ACTION = UUID("10000000-0000-4000-8000-00000000000b")
OTHER_ACTION = UUID("10000000-0000-4000-8000-00000000000c")
DIGEST = hashlib.sha256(b"claim-request-a").digest()
OTHER_DIGEST = hashlib.sha256(b"claim-request-b").digest()


def _owner(*, tenant=TENANT_A, account=ACCOUNT_A, warehouse=WAREHOUSE_A):
    return SfClaimOwner(tenant, account, warehouse)


def _proof(
    *,
    tenant=TENANT_A,
    action=ACTION,
    digest=DIGEST,
    purpose="sf_account_bind",
    gate=EffectiveTenantGate.ACTIVE,
    role=TenantRole.ADMIN,
    consumed=True,
):
    return SfAdminClaimProof(
        tenant_uuid=tenant,
        actor_user_uuid=USER,
        actor_session_uuid=SESSION,
        role=role,
        effective_gate=gate,
        tenant_access_version=7,
        otp_challenge_uuid=OTP,
        otp_purpose=purpose,
        otp_action_uuid=action,
        otp_request_digest=digest,
        otp_consumed=consumed,
    )


def _claim():
    fingerprint = derive_provider_account_fingerprint(
        root_key=RootKey(version=1, material=bytes(range(32))),
        provider="sf",
        canonical_account="0012345678",
    )
    return SfAccountClaim.unowned(claim_uuid=CLAIM, fingerprint=fingerprint)


def _reserved(*, owner=None, proof=None, action=ACTION, digest=DIGEST):
    claim = _claim()
    return reserve_sf_claim(
        claim,
        owner=owner or _owner(),
        proof=proof or _proof(action=action, digest=digest),
        expected_generation=claim.generation,
        expected_row_version=claim.row_version,
        action_uuid=action,
        request_digest=digest,
        reservation_expires_at=NOW + timedelta(minutes=10),
        database_now=NOW,
    ).claim


def _active():
    reserved = _reserved()
    return activate_sf_claim(
        reserved,
        owner=_owner(),
        proof=_proof(),
        expected_generation=reserved.generation,
        expected_row_version=reserved.row_version,
        action_uuid=ACTION,
        request_digest=DIGEST,
        binding_revision=3,
        database_now=NOW + timedelta(minutes=1),
    ).claim


def test_reserve_and_activate_advance_each_generation_and_chain_events():
    claim = _claim()
    reserved = reserve_sf_claim(
        claim,
        owner=_owner(),
        proof=_proof(),
        expected_generation=1,
        expected_row_version=1,
        action_uuid=ACTION,
        request_digest=DIGEST,
        reservation_expires_at=NOW + timedelta(minutes=10),
        database_now=NOW,
    )
    assert reserved.claim.state is SfClaimState.RESERVED
    assert reserved.claim.generation == 2
    assert reserved.claim.row_version == 2
    assert reserved.event.event_kind is SfClaimEventKind.RESERVED
    assert reserved.event.previous_hash == b"\x00" * 32

    active = activate_sf_claim(
        reserved.claim,
        owner=_owner(),
        proof=_proof(),
        expected_generation=2,
        expected_row_version=2,
        action_uuid=ACTION,
        request_digest=DIGEST,
        binding_revision=9,
        database_now=NOW + timedelta(minutes=1),
    )
    assert active.claim.state is SfClaimState.ACTIVE
    assert active.claim.generation == 3
    assert active.claim.row_version == 3
    assert active.claim.active_binding_revision == 9
    assert active.event.previous_hash == reserved.event.record_hash
    assert active.claim.event_head_hash == active.event.record_hash


def test_exact_response_loss_replays_but_changed_request_is_rejected():
    reserved = _reserved()
    replay = reserve_sf_claim(
        reserved,
        owner=_owner(),
        proof=_proof(),
        expected_generation=1,
        expected_row_version=1,
        action_uuid=ACTION,
        request_digest=DIGEST,
        reservation_expires_at=NOW + timedelta(minutes=10),
        database_now=NOW,
    )
    assert replay.idempotent_replay and replay.event is None
    assert replay.claim is reserved

    with pytest.raises(SfClaimIdempotencyConflict):
        reserve_sf_claim(
            reserved,
            owner=_owner(),
            proof=_proof(digest=OTHER_DIGEST),
            expected_generation=reserved.generation,
            expected_row_version=reserved.row_version,
            action_uuid=ACTION,
            request_digest=OTHER_DIGEST,
            reservation_expires_at=NOW + timedelta(minutes=10),
            database_now=NOW,
        )


def test_other_warehouse_or_tenant_receives_only_non_disclosing_unavailable():
    active = _active()
    other_owner = _owner(
        tenant=TENANT_B,
        account=ACCOUNT_B,
        warehouse=WAREHOUSE_B,
    )
    with pytest.raises(SfClaimUnavailable) as caught:
        reserve_sf_claim(
            active,
            owner=other_owner,
            proof=_proof(
                tenant=TENANT_B,
                action=OTHER_ACTION,
                digest=OTHER_DIGEST,
            ),
            expected_generation=active.generation,
            expected_row_version=active.row_version,
            action_uuid=OTHER_ACTION,
            request_digest=OTHER_DIGEST,
            reservation_expires_at=NOW + timedelta(minutes=10),
            database_now=NOW,
        )
    assert caught.value.code == "SF_ACCOUNT_UNAVAILABLE"
    assert str(TENANT_A) not in str(caught.value)
    assert str(WAREHOUSE_A) not in str(caught.value)


@pytest.mark.parametrize(
    "proof",
    [
        _proof(role=TenantRole.OPERATOR),
        _proof(gate=EffectiveTenantGate.EXPIRED),
        _proof(gate=EffectiveTenantGate.SUSPENDED),
        _proof(consumed=False),
        _proof(tenant=TENANT_B),
    ],
)
def test_bind_requires_active_admin_and_exact_consumed_d48_proof(proof):
    claim = _claim()
    with pytest.raises(SfClaimAuthorityDenied):
        reserve_sf_claim(
            claim,
            owner=_owner(),
            proof=proof,
            expected_generation=1,
            expected_row_version=1,
            action_uuid=ACTION,
            request_digest=DIGEST,
            reservation_expires_at=NOW + timedelta(minutes=10),
            database_now=NOW,
        )


def test_stale_reservation_can_be_reclaimed_but_old_worker_cannot_activate():
    old = _reserved()
    new_owner = _owner(tenant=TENANT_B, account=ACCOUNT_B, warehouse=WAREHOUSE_B)
    reclaimed = reserve_sf_claim(
        old,
        owner=new_owner,
        proof=_proof(
            tenant=TENANT_B,
            action=OTHER_ACTION,
            digest=OTHER_DIGEST,
        ),
        expected_generation=old.generation,
        expected_row_version=old.row_version,
        action_uuid=OTHER_ACTION,
        request_digest=OTHER_DIGEST,
        reservation_expires_at=NOW + timedelta(minutes=30),
        database_now=NOW + timedelta(minutes=11),
    ).claim
    assert reclaimed.generation == old.generation + 1
    assert reclaimed.owner == new_owner

    with pytest.raises(SfClaimFenceConflict):
        activate_sf_claim(
            reclaimed,
            owner=_owner(),
            proof=_proof(),
            expected_generation=old.generation,
            expected_row_version=old.row_version,
            action_uuid=ACTION,
            request_digest=DIGEST,
            binding_revision=3,
            database_now=NOW + timedelta(minutes=12),
        )


def test_active_admin_unbind_releases_owner_but_preserves_event_history():
    active = _active()
    release_action = OTHER_ACTION
    released = release_sf_claim(
        active,
        proof=_proof(
            action=release_action,
            digest=OTHER_DIGEST,
            purpose="sf_account_unbind",
        ),
        expected_generation=active.generation,
        expected_row_version=active.row_version,
        action_uuid=release_action,
        request_digest=OTHER_DIGEST,
        database_now=NOW + timedelta(minutes=2),
    )
    assert released.claim.state is SfClaimState.RELEASED
    assert released.claim.owner is None
    assert released.claim.generation == active.generation + 1
    assert released.event.event_kind is SfClaimEventKind.RELEASED_BY_ADMIN
    assert released.event.tenant_uuid == TENANT_A

    replay = release_sf_claim(
        released.claim,
        proof=_proof(
            action=release_action,
            digest=OTHER_DIGEST,
            purpose="sf_account_unbind",
        ),
        expected_generation=active.generation,
        expected_row_version=active.row_version,
        action_uuid=release_action,
        request_digest=OTHER_DIGEST,
        database_now=NOW + timedelta(minutes=3),
    )
    assert replay.idempotent_replay


def test_expired_or_suspended_admin_has_no_unbind_exception():
    active = _active()
    for gate in (EffectiveTenantGate.EXPIRED, EffectiveTenantGate.SUSPENDED):
        with pytest.raises(SfClaimAuthorityDenied):
            release_sf_claim(
                active,
                proof=_proof(
                    action=OTHER_ACTION,
                    digest=OTHER_DIGEST,
                    purpose="sf_account_unbind",
                    gate=gate,
                ),
                expected_generation=active.generation,
                expected_row_version=active.row_version,
                action_uuid=OTHER_ACTION,
                request_digest=OTHER_DIGEST,
                database_now=NOW,
            )


def test_system_deletion_release_requires_irreversible_offsite_ack():
    active = _active()
    base = SfDeletionClaimProof(
        tenant_uuid=TENANT_A,
        deletion_request_uuid=UUID("20000000-0000-4000-8000-000000000001"),
        action_uuid=OTHER_ACTION,
        execution_generation=4,
        fencing_token=8,
        tombstone_sequence=10,
        tombstone_record_hash=hashlib.sha256(b"tombstone").digest(),
        offsite_acknowledged=True,
        irreversible_deletion=True,
    )
    for invalid in (
        replace(base, offsite_acknowledged=False),
        replace(base, irreversible_deletion=False),
        replace(base, tenant_uuid=TENANT_B),
    ):
        with pytest.raises(SfClaimAuthorityDenied):
            release_sf_claim(
                active,
                proof=invalid,
                expected_generation=active.generation,
                expected_row_version=active.row_version,
                action_uuid=OTHER_ACTION,
                request_digest=OTHER_DIGEST,
                database_now=NOW,
            )

    released = release_sf_claim(
        active,
        proof=base,
        expected_generation=active.generation,
        expected_row_version=active.row_version,
        action_uuid=OTHER_ACTION,
        request_digest=OTHER_DIGEST,
        database_now=NOW,
    )
    assert released.event.event_kind is SfClaimEventKind.RELEASED_BY_DELETION
    assert released.event.actor_type == "system_deletion"


def test_event_contains_only_technical_ids_and_hash_chain():
    reserved = reserve_sf_claim(
        _claim(),
        owner=_owner(),
        proof=_proof(),
        expected_generation=1,
        expected_row_version=1,
        action_uuid=ACTION,
        request_digest=DIGEST,
        reservation_expires_at=NOW + timedelta(minutes=10),
        database_now=NOW,
    )
    rendered = repr(reserved.event)
    assert "0012345678" not in rendered
    assert "password" not in rendered.lower()
    assert "secret" not in rendered.lower()
    assert len(reserved.event.record_hash) == 32
