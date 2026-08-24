from __future__ import annotations

import hashlib
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from threading import Barrier
from uuid import UUID

import pytest
import sqlalchemy as sa

from inventory_control import ControlBase, ControlDatabase
from inventory_control.crypto import RootKey, derive_provider_account_fingerprint
from inventory_control.domain import EffectiveTenantGate, TenantRole
from inventory_control.integrations import (
    SfAdminClaimProof,
    SfClaimAuthorityDenied,
    SfClaimFenceConflict,
    SfClaimOwner,
    SfClaimPersistenceService,
    SfClaimState,
    SfClaimTransactionError,
    SfClaimUnavailable,
    SfDeletionClaimProof,
)
from inventory_control.models import ProviderAccountClaim, ProviderAccountClaimEvent


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
CLAIM = UUID("70000000-0000-4000-8000-000000000001")
TENANT_A = UUID("70000000-0000-4000-8000-000000000002")
TENANT_B = UUID("70000000-0000-4000-8000-000000000003")
ACCOUNT_A = UUID("70000000-0000-4000-8000-000000000004")
ACCOUNT_B = UUID("70000000-0000-4000-8000-000000000005")
WAREHOUSE_A = UUID("70000000-0000-4000-8000-000000000006")
WAREHOUSE_B = UUID("70000000-0000-4000-8000-000000000007")
USER_A = UUID("70000000-0000-4000-8000-000000000008")
USER_B = UUID("70000000-0000-4000-8000-000000000009")
SESSION_A = UUID("70000000-0000-4000-8000-00000000000a")
SESSION_B = UUID("70000000-0000-4000-8000-00000000000b")
OTP_A = UUID("70000000-0000-4000-8000-00000000000c")
OTP_B = UUID("70000000-0000-4000-8000-00000000000d")
ACTION_A = UUID("70000000-0000-4000-8000-00000000000e")
ACTION_B = UUID("70000000-0000-4000-8000-00000000000f")
RELEASE_ACTION = UUID("70000000-0000-4000-8000-000000000010")
DIGEST_A = hashlib.sha256(b"sf-claim-a").digest()
DIGEST_B = hashlib.sha256(b"sf-claim-b").digest()
RELEASE_DIGEST = hashlib.sha256(b"sf-release").digest()
PLAINTEXT_ACCOUNT = "0012345678"


@pytest.fixture
def control_database(mysql_control_database):
    return mysql_control_database


@pytest.fixture
def fingerprint():
    return derive_provider_account_fingerprint(
        root_key=RootKey(version=1, material=bytes(range(32))),
        provider="sf",
        canonical_account=PLAINTEXT_ACCOUNT,
    )


def _owner(*, second: bool = False) -> SfClaimOwner:
    return SfClaimOwner(
        tenant_uuid=TENANT_B if second else TENANT_A,
        provider_account_uuid=ACCOUNT_B if second else ACCOUNT_A,
        warehouse_uuid=WAREHOUSE_B if second else WAREHOUSE_A,
    )


def _admin_proof(
    *,
    second: bool = False,
    action: UUID | None = None,
    digest: bytes | None = None,
    purpose: str = "sf_account_bind",
    gate: EffectiveTenantGate = EffectiveTenantGate.ACTIVE,
) -> SfAdminClaimProof:
    return SfAdminClaimProof(
        tenant_uuid=TENANT_B if second else TENANT_A,
        actor_user_uuid=USER_B if second else USER_A,
        actor_session_uuid=SESSION_B if second else SESSION_A,
        role=TenantRole.ADMIN,
        effective_gate=gate,
        tenant_access_version=9 if second else 7,
        otp_challenge_uuid=OTP_B if second else OTP_A,
        otp_purpose=purpose,
        otp_action_uuid=action or (ACTION_B if second else ACTION_A),
        otp_request_digest=digest or (DIGEST_B if second else DIGEST_A),
        otp_consumed=True,
    )


def _service(session) -> SfClaimPersistenceService:
    return SfClaimPersistenceService(session, database_clock=lambda _: NOW)


def _reserve(control_database, fingerprint):
    with control_database.transaction() as session:
        return _service(session).reserve_claim(
            fingerprint=fingerprint,
            claim_uuid=CLAIM,
            owner=_owner(),
            proof=_admin_proof(),
            expected_generation=1,
            expected_row_version=1,
            action_uuid=ACTION_A,
            request_digest=DIGEST_A,
            reservation_expires_at=NOW + timedelta(minutes=10),
        )


def _activate(control_database, reserved):
    with control_database.transaction() as session:
        return _service(session).activate_claim(
            claim_uuid=reserved.claim_uuid,
            owner=_owner(),
            proof=_admin_proof(),
            expected_generation=reserved.generation,
            expected_row_version=reserved.row_version,
            action_uuid=ACTION_A,
            request_digest=DIGEST_A,
            binding_revision=3,
        )


def test_requires_an_explicit_clean_caller_transaction(
    control_database, fingerprint
):
    with control_database.new_session() as session:
        with pytest.raises(SfClaimTransactionError):
            _service(session).reserve_claim(
                fingerprint=fingerprint,
                owner=_owner(),
                proof=_admin_proof(),
                expected_generation=1,
                expected_row_version=1,
                action_uuid=ACTION_A,
                request_digest=DIGEST_A,
                reservation_expires_at=NOW + timedelta(minutes=10),
            )

    with control_database.new_session() as session:
        transaction = session.begin()
        try:
            session.add(ProviderAccountClaim(id=str(CLAIM)))
            with pytest.raises(SfClaimTransactionError):
                _service(session).reserve_claim(
                    fingerprint=fingerprint,
                    owner=_owner(),
                    proof=_admin_proof(),
                    expected_generation=1,
                    expected_row_version=1,
                    action_uuid=ACTION_A,
                    request_digest=DIGEST_A,
                    reservation_expires_at=NOW + timedelta(minutes=10),
                )
        finally:
            transaction.rollback()


def test_reserve_and_activate_cas_claim_with_append_only_events(
    control_database, fingerprint
):
    reserved = _reserve(control_database, fingerprint)
    active = _activate(control_database, reserved)

    assert reserved.state is SfClaimState.RESERVED
    assert active.state is SfClaimState.ACTIVE
    assert (reserved.generation, active.generation) == (2, 3)
    assert (reserved.row_version, active.row_version) == (2, 3)
    assert (reserved.event_sequence, active.event_sequence) == (1, 2)

    with control_database.new_session() as session:
        claim = session.get(ProviderAccountClaim, str(CLAIM))
        events = tuple(
            session.scalars(
                sa.select(ProviderAccountClaimEvent)
                .where(
                    ProviderAccountClaimEvent.provider_account_claim_id
                    == str(CLAIM)
                )
                .order_by(ProviderAccountClaimEvent.event_sequence)
            )
        )
        assert claim.claim_status == "active"
        assert claim.current_tenant_id == str(TENANT_A)
        assert claim.active_binding_revision == 3
        assert claim.last_transition_event_id == events[-1].id
        assert len(events) == 2
        assert events[0].from_status == "released"
        assert events[0].to_status == "reserved"
        assert events[1].from_status == "reserved"
        assert events[1].to_status == "active"
        assert events[1].previous_event_hash == events[0].record_hash
        assert claim.event_head_hash == events[1].record_hash


def test_exact_action_digest_replays_without_another_event(
    control_database, fingerprint
):
    reserved = _reserve(control_database, fingerprint)
    active = _activate(control_database, reserved)
    with control_database.transaction() as session:
        replay = _service(session).activate_claim(
            claim_uuid=active.claim_uuid,
            owner=_owner(),
            proof=_admin_proof(),
            expected_generation=reserved.generation,
            expected_row_version=reserved.row_version,
            action_uuid=ACTION_A,
            request_digest=DIGEST_A,
            binding_revision=3,
        )

    assert replay.idempotent_replay is True
    assert replay.transition_event_uuid is None
    assert replay.event_sequence == 2
    with control_database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(ProviderAccountClaimEvent)
        ) == 2


def test_stale_fences_fail_without_changing_claim_or_event(
    control_database, fingerprint
):
    reserved = _reserve(control_database, fingerprint)
    with pytest.raises(SfClaimFenceConflict):
        with control_database.transaction() as session:
            _service(session).activate_claim(
                claim_uuid=reserved.claim_uuid,
                owner=_owner(),
                proof=_admin_proof(),
                expected_generation=1,
                expected_row_version=1,
                action_uuid=ACTION_A,
                request_digest=DIGEST_A,
                binding_revision=3,
            )
    with control_database.new_session() as session:
        claim = session.get(ProviderAccountClaim, str(CLAIM))
        assert claim.claim_status == "reserved"
        assert claim.claim_generation == 2
        assert session.scalar(
            sa.select(sa.func.count()).select_from(ProviderAccountClaimEvent)
        ) == 1


def test_admin_and_d26_release_store_complete_available_provenance(
    control_database, fingerprint
):
    active = _activate(control_database, _reserve(control_database, fingerprint))
    admin_proof = _admin_proof(
        action=RELEASE_ACTION,
        digest=RELEASE_DIGEST,
        purpose="sf_account_unbind",
    )
    with control_database.transaction() as session:
        released = _service(session).release_claim_by_admin(
            claim_uuid=active.claim_uuid,
            proof=admin_proof,
            expected_generation=active.generation,
            expected_row_version=active.row_version,
            action_uuid=RELEASE_ACTION,
            request_digest=RELEASE_DIGEST,
        )
    with control_database.new_session() as session:
        event = session.get(
            ProviderAccountClaimEvent, str(released.transition_event_uuid)
        )
        assert event.actor_type == "tenant_admin"
        assert event.actor_user_uuid == str(USER_A)
        assert event.actor_session_uuid == str(SESSION_A)
        assert event.otp_challenge_uuid == str(OTP_A)
        assert event.source_action_uuid == str(RELEASE_ACTION)
        assert event.request_digest == RELEASE_DIGEST
        assert event.previous_tenant_id == str(TENANT_A)
        assert event.new_tenant_id is None
        assert event.deletion_request_uuid is None
        assert len(event.transition_digest) == 32

    rebound_action = UUID("70000000-0000-4000-8000-000000000011")
    rebound_digest = hashlib.sha256(b"rebound").digest()
    rebound_proof = _admin_proof(
        action=rebound_action,
        digest=rebound_digest,
        purpose="sf_account_rebind",
    )
    with control_database.transaction() as session:
        rebound = _service(session).reserve_claim(
            fingerprint=fingerprint,
            owner=_owner(),
            proof=rebound_proof,
            expected_generation=released.generation,
            expected_row_version=released.row_version,
            action_uuid=rebound_action,
            request_digest=rebound_digest,
            reservation_expires_at=NOW + timedelta(minutes=20),
        )

    deletion_action = UUID("70000000-0000-4000-8000-000000000012")
    deletion_digest = hashlib.sha256(b"d26-release").digest()
    tombstone_hash = hashlib.sha256(b"offsite-tombstone").digest()
    deletion_proof = SfDeletionClaimProof(
        tenant_uuid=TENANT_A,
        deletion_request_uuid=UUID("70000000-0000-4000-8000-000000000013"),
        action_uuid=deletion_action,
        execution_generation=4,
        fencing_token=11,
        tombstone_sequence=19,
        tombstone_record_hash=tombstone_hash,
        offsite_acknowledged=True,
        irreversible_deletion=True,
    )
    with control_database.transaction() as session:
        deleted = _service(session).release_claim_by_deletion(
            claim_uuid=rebound.claim_uuid,
            proof=deletion_proof,
            expected_generation=rebound.generation,
            expected_row_version=rebound.row_version,
            action_uuid=deletion_action,
            request_digest=deletion_digest,
        )
    with control_database.new_session() as session:
        event = session.get(
            ProviderAccountClaimEvent, str(deleted.transition_event_uuid)
        )
        assert event.actor_type == "system_deletion"
        assert event.actor_user_uuid is None
        assert event.actor_session_uuid is None
        assert event.otp_challenge_uuid is None
        assert event.deletion_request_uuid == str(
            deletion_proof.deletion_request_uuid
        )
        assert event.deletion_execution_generation == 4
        assert event.tombstone_sequence == 19
        assert event.tombstone_record_hash == tombstone_hash
        assert event.new_provider_account_id is None
        assert event.new_tenant_id is None
        assert event.new_warehouse_uuid is None


def test_reducer_rejection_does_not_leave_an_empty_permanent_row(
    control_database, fingerprint
):
    denied = _admin_proof(gate=EffectiveTenantGate.EXPIRED)
    with control_database.transaction() as session:
        with pytest.raises(SfClaimAuthorityDenied):
            _service(session).reserve_claim(
                fingerprint=fingerprint,
                claim_uuid=CLAIM,
                owner=_owner(),
                proof=denied,
                expected_generation=1,
                expected_row_version=1,
                action_uuid=ACTION_A,
                request_digest=DIGEST_A,
                reservation_expires_at=NOW + timedelta(minutes=10),
            )
    with control_database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(ProviderAccountClaim)
        ) == 0


def test_outer_rollback_reverts_claim_and_event(control_database, fingerprint):
    with control_database.new_session() as session:
        transaction = session.begin()
        _service(session).reserve_claim(
            fingerprint=fingerprint,
            claim_uuid=CLAIM,
            owner=_owner(),
            proof=_admin_proof(),
            expected_generation=1,
            expected_row_version=1,
            action_uuid=ACTION_A,
            request_digest=DIGEST_A,
            reservation_expires_at=NOW + timedelta(minutes=10),
        )
        transaction.rollback()

    with control_database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(ProviderAccountClaim)
        ) == 0
        assert session.scalar(
            sa.select(sa.func.count()).select_from(ProviderAccountClaimEvent)
        ) == 0


@pytest.mark.parametrize("_race_attempt", range(5))
def test_concurrent_fingerprint_race_has_one_winner_and_no_owner_disclosure(
    control_database, fingerprint, _race_attempt
):
    barrier = Barrier(2)

    def compete(second: bool):
        action = ACTION_B if second else ACTION_A
        digest = DIGEST_B if second else DIGEST_A
        claim = UUID(
            "70000000-0000-4000-8000-000000000021"
            if second
            else "70000000-0000-4000-8000-000000000020"
        )
        barrier.wait()
        try:
            with control_database.transaction() as session:
                result = _service(session).reserve_claim(
                    fingerprint=fingerprint,
                    claim_uuid=claim,
                    owner=_owner(second=second),
                    proof=_admin_proof(second=second),
                    expected_generation=1,
                    expected_row_version=1,
                    action_uuid=action,
                    request_digest=digest,
                    reservation_expires_at=NOW + timedelta(minutes=10),
                )
            return result
        except SfClaimUnavailable as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = tuple(executor.map(compete, (False, True)))

    winners = [item for item in outcomes if not isinstance(item, Exception)]
    losers = [item for item in outcomes if isinstance(item, SfClaimUnavailable)]
    assert len(winners) == 1
    assert len(losers) == 1
    rendered = repr(losers[0])
    for secret_owner_identity in (TENANT_A, TENANT_B, WAREHOUSE_A, WAREHOUSE_B):
        assert str(secret_owner_identity) not in rendered

    with control_database.new_session() as session:
        assert session.scalar(
            sa.select(sa.func.count()).select_from(ProviderAccountClaim)
        ) == 1
        assert session.scalar(
            sa.select(sa.func.count()).select_from(ProviderAccountClaimEvent)
        ) == 1


def test_claim_storage_never_contains_provider_account_plaintext(
    control_database, fingerprint
):
    _reserve(control_database, fingerprint)
    with control_database.new_session() as session:
        claim = session.get(ProviderAccountClaim, str(CLAIM))
        event = session.scalar(sa.select(ProviderAccountClaimEvent))
        stored_values = tuple(claim.__dict__.values()) + tuple(event.__dict__.values())
        assert PLAINTEXT_ACCOUNT not in {
            value for value in stored_values if isinstance(value, str)
        }
        assert bytes(claim.account_fingerprint) == fingerprint.digest
        assert bytes(claim.account_fingerprint) != PLAINTEXT_ACCOUNT.encode("ascii")
