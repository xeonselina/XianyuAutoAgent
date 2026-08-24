"""Caller-transaction persistence for the global SF account claim.

The service accepts only an already-derived keyed fingerprint; provider account
plaintext has no place in this API or in either persistence model.  Every
mutation requires a clean, explicit caller-owned transaction.  The service
uses SAVEPOINTs to contain uniqueness races, but never commits or rolls back
the caller's outer transaction.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inventory_control.crypto import (
    CryptoConfigurationError,
    ProviderAccountFingerprint,
)
from inventory_control.database import read_database_utc_value
from inventory_control.models.provider_claims import (
    ProviderAccountClaim,
    ProviderAccountClaimEvent,
)
from inventory_control.transactions import require_caller_transaction

from .sf_claim import (
    SfAccountClaim,
    SfAdminClaimProof,
    SfClaimError,
    SfClaimEvent,
    SfClaimEventKind,
    SfClaimFenceConflict,
    SfClaimOwner,
    SfClaimState,
    SfClaimTransition,
    SfClaimUnavailable,
    SfDeletionClaimProof,
    activate_sf_claim as _reduce_activate,
    release_sf_claim as _reduce_release,
    reserve_sf_claim as _reduce_reserve,
)


_ZERO_HASH = b"\x00" * 32

_EVENT_SAFE_CODES = {
    SfClaimEventKind.RESERVED: (
        "SF_ACCOUNT_RESERVATION_REQUESTED",
        "SF_CLAIM_RESERVED",
    ),
    SfClaimEventKind.ACTIVATED: (
        "SF_ACCOUNT_VALIDATION_SUCCEEDED",
        "SF_CLAIM_ACTIVATED",
    ),
    SfClaimEventKind.RELEASED_BY_ADMIN: (
        "SF_ACCOUNT_ADMIN_UNBIND",
        "SF_CLAIM_RELEASED",
    ),
    SfClaimEventKind.RELEASED_BY_DELETION: (
        "TENANT_IRREVERSIBLE_DELETION",
        "SF_CLAIM_RELEASED",
    ),
}


class SfClaimPersistenceError(SfClaimError):
    """A non-disclosing persistence or stored-integrity failure."""

    code = "SF_CLAIM_PERSISTENCE_FAILED"
    public_message = "the SF account claim could not be persisted"


class SfClaimTransactionError(SfClaimPersistenceError):
    """The caller did not supply the required clean outer transaction."""

    code = "SF_CLAIM_TRANSACTION_INVALID"
    public_message = "an explicit clean caller-owned transaction is required"


@dataclass(frozen=True, slots=True)
class SfClaimPersistenceResult:
    """Non-secret mutation result safe to pass between control-plane services."""

    claim_uuid: UUID
    state: SfClaimState
    generation: int
    row_version: int
    event_sequence: int
    transition_event_uuid: UUID | None
    event_kind: SfClaimEventKind | None
    idempotent_replay: bool


DatabaseClock = Callable[[Session], datetime]
_TransitionFactory = Callable[[SfAccountClaim], SfClaimTransition]


class SfClaimPersistenceService:
    """Persist SF claim reducer transitions with locking and optimistic fences."""

    def __init__(
        self,
        session: Session,
        *,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not isinstance(session, Session):
            raise SfClaimTransactionError()
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._session = session
        self._database_clock = database_clock or _read_database_utc_now

    def reserve_claim(
        self,
        *,
        fingerprint: ProviderAccountFingerprint,
        owner: SfClaimOwner,
        proof: SfAdminClaimProof,
        expected_generation: int,
        expected_row_version: int,
        action_uuid: str | UUID,
        request_digest: bytes,
        reservation_expires_at: datetime,
        claim_uuid: str | UUID | None = None,
    ) -> SfClaimPersistenceResult:
        """Reserve the fingerprint, safely creating its permanent row if absent."""

        self._prepare()
        selected_fingerprint = _fingerprint(fingerprint)
        action_id = _uuid(action_uuid)
        candidate_id = uuid4() if claim_uuid is None else _uuid(claim_uuid)
        now = self._now()

        def transition(current: SfAccountClaim) -> SfClaimTransition:
            try:
                return _reduce_reserve(
                    current,
                    owner=owner,
                    proof=proof,
                    expected_generation=expected_generation,
                    expected_row_version=expected_row_version,
                    action_uuid=action_id,
                    request_digest=request_digest,
                    reservation_expires_at=reservation_expires_at,
                    database_now=now,
                )
            except SfClaimFenceConflict:
                # A uniqueness-race loser must not learn whether a different
                # tenant or warehouse owns the live claim merely because its
                # expected initial fence is now stale.
                if _is_currently_unavailable(current, database_now=now):
                    raise SfClaimUnavailable() from None
                raise

        # Do not take a next-key/gap lock before the permanent fingerprint row
        # exists.  On InnoDB, two first-time reservations can both acquire the
        # empty-range lock and then deadlock while inserting the same unique
        # fingerprint.  A non-locking existence read lets the unique index
        # serialize first creation; the loser is contained by the SAVEPOINT
        # below and then locking-reads the committed winner.
        row = self._find_by_fingerprint(selected_fingerprint)
        if row is not None:
            row = self._lock_by_fingerprint(selected_fingerprint)
            if row is None:
                raise SfClaimPersistenceError()
            return self._apply_existing(
                row,
                transition_factory=transition,
                proof=proof,
                request_digest=request_digest,
            )

        candidate = _new_unowned_row(
            claim_uuid=candidate_id,
            fingerprint=selected_fingerprint,
            database_now=now,
        )
        if self._session.get_bind().dialect.name in {"mysql", "mariadb"}:
            # InnoDB may roll back an entire transaction (and destroy its
            # SAVEPOINT) when two plain INSERTs race on the same unique key.
            # A no-op upsert makes the unique index serialize first creation
            # without treating the expected loser as a transaction deadlock.
            statement = mysql_insert(ProviderAccountClaim).values(
                {
                    column.key: getattr(candidate, column.key)
                    for column in ProviderAccountClaim.__table__.columns
                }
            )
            with self._session.begin_nested():
                self._session.execute(
                    statement.on_duplicate_key_update(
                        id=ProviderAccountClaim.id,
                    )
                )
                winner = self._lock_by_fingerprint(selected_fingerprint)
                if winner is None:
                    raise SfClaimPersistenceError()
                result = self._apply_existing(
                    winner,
                    transition_factory=transition,
                    proof=proof,
                    request_digest=request_digest,
                )
            return result
        try:
            with self._session.begin_nested():
                self._session.add(candidate)
                self._session.flush()
                current = _domain_claim(candidate, selected_fingerprint)
                reduced = transition(current)
                event_uuid = self._write_transition(
                    candidate,
                    before=current,
                    transition=reduced,
                    proof=proof,
                    request_digest=request_digest,
                )
            self._session.expire(candidate)
            return _result(reduced, event_uuid=event_uuid)
        except IntegrityError:
            # A concurrent insert may win the global fingerprint uniqueness
            # constraint.  The SAVEPOINT contains our candidate and lets this
            # transaction locking-read the winner without rolling back the
            # caller's work.
            self._session.expire_all()
            winner = self._lock_by_fingerprint(selected_fingerprint)
            if winner is None:
                raise SfClaimPersistenceError() from None
            return self._apply_existing(
                winner,
                transition_factory=transition,
                proof=proof,
                request_digest=request_digest,
            )

    def activate_claim(
        self,
        *,
        claim_uuid: str | UUID,
        owner: SfClaimOwner,
        proof: SfAdminClaimProof,
        expected_generation: int,
        expected_row_version: int,
        action_uuid: str | UUID,
        request_digest: bytes,
        binding_revision: int,
    ) -> SfClaimPersistenceResult:
        """Activate one current, unexpired reservation."""

        self._prepare()
        claim_id = _uuid(claim_uuid)
        action_id = _uuid(action_uuid)
        now = self._now()
        row = self._lock_by_id(claim_id)

        def transition(current: SfAccountClaim) -> SfClaimTransition:
            return _reduce_activate(
                current,
                owner=owner,
                proof=proof,
                expected_generation=expected_generation,
                expected_row_version=expected_row_version,
                action_uuid=action_id,
                request_digest=request_digest,
                binding_revision=binding_revision,
                database_now=now,
            )

        return self._apply_existing(
            row,
            transition_factory=transition,
            proof=proof,
            request_digest=request_digest,
        )

    def release_claim_by_admin(
        self,
        *,
        claim_uuid: str | UUID,
        proof: SfAdminClaimProof,
        expected_generation: int,
        expected_row_version: int,
        action_uuid: str | UUID,
        request_digest: bytes,
    ) -> SfClaimPersistenceResult:
        """Release a claim using active-tenant Admin/D48 authority."""

        if not isinstance(proof, SfAdminClaimProof):
            raise TypeError("proof must be an SfAdminClaimProof")
        return self.release_claim(
            claim_uuid=claim_uuid,
            proof=proof,
            expected_generation=expected_generation,
            expected_row_version=expected_row_version,
            action_uuid=action_uuid,
            request_digest=request_digest,
        )

    def release_claim_by_deletion(
        self,
        *,
        claim_uuid: str | UUID,
        proof: SfDeletionClaimProof,
        expected_generation: int,
        expected_row_version: int,
        action_uuid: str | UUID,
        request_digest: bytes,
    ) -> SfClaimPersistenceResult:
        """Release a claim using trusted irreversible D26 authority."""

        if not isinstance(proof, SfDeletionClaimProof):
            raise TypeError("proof must be an SfDeletionClaimProof")
        return self.release_claim(
            claim_uuid=claim_uuid,
            proof=proof,
            expected_generation=expected_generation,
            expected_row_version=expected_row_version,
            action_uuid=action_uuid,
            request_digest=request_digest,
        )

    def release_claim(
        self,
        *,
        claim_uuid: str | UUID,
        proof: SfAdminClaimProof | SfDeletionClaimProof,
        expected_generation: int,
        expected_row_version: int,
        action_uuid: str | UUID,
        request_digest: bytes,
    ) -> SfClaimPersistenceResult:
        """Release through the reducer-selected Admin or D26 authority path."""

        if not isinstance(proof, (SfAdminClaimProof, SfDeletionClaimProof)):
            raise TypeError("proof must be an SF claim authority proof")
        self._prepare()
        claim_id = _uuid(claim_uuid)
        action_id = _uuid(action_uuid)
        now = self._now()
        row = self._lock_by_id(claim_id)

        def transition(current: SfAccountClaim) -> SfClaimTransition:
            return _reduce_release(
                current,
                proof=proof,
                expected_generation=expected_generation,
                expected_row_version=expected_row_version,
                action_uuid=action_id,
                request_digest=request_digest,
                database_now=now,
            )

        return self._apply_existing(
            row,
            transition_factory=transition,
            proof=proof,
            request_digest=request_digest,
        )

    # Concise aliases keep the service comfortable at orchestration call sites.
    reserve = reserve_claim
    activate = activate_claim
    release_by_admin = release_claim_by_admin
    release_by_deletion = release_claim_by_deletion

    def _prepare(self) -> None:
        require_caller_transaction(
            self._session,
            SfClaimTransactionError,
            clean=True,
        )

    def _now(self) -> datetime:
        return _as_utc(self._database_clock(self._session))

    def _lock_by_fingerprint(
        self,
        fingerprint: ProviderAccountFingerprint,
    ) -> ProviderAccountClaim | None:
        return self._session.scalar(
            sa.select(ProviderAccountClaim)
            .where(
                ProviderAccountClaim.provider == fingerprint.provider,
                ProviderAccountClaim.account_fingerprint == fingerprint.digest,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _find_by_fingerprint(
        self,
        fingerprint: ProviderAccountFingerprint,
    ) -> ProviderAccountClaim | None:
        return self._session.scalar(
            sa.select(ProviderAccountClaim).where(
                ProviderAccountClaim.provider == fingerprint.provider,
                ProviderAccountClaim.account_fingerprint == fingerprint.digest,
            )
        )

    def _lock_by_id(self, claim_uuid: UUID) -> ProviderAccountClaim:
        row = self._session.scalar(
            sa.select(ProviderAccountClaim)
            .where(ProviderAccountClaim.id == str(claim_uuid))
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise SfClaimFenceConflict()
        return row

    def _apply_existing(
        self,
        row: ProviderAccountClaim,
        *,
        transition_factory: _TransitionFactory,
        proof: SfAdminClaimProof | SfDeletionClaimProof,
        request_digest: bytes,
    ) -> SfClaimPersistenceResult:
        row_uuid = UUID(row.id)
        current = _domain_claim(row)
        reduced = transition_factory(current)
        if reduced.idempotent_replay:
            self._verify_replay_event(
                row,
                current=current,
                request_digest=request_digest,
            )
            return _result(reduced, event_uuid=None)

        try:
            with self._session.begin_nested():
                event_uuid = self._write_transition(
                    row,
                    before=current,
                    transition=reduced,
                    proof=proof,
                    request_digest=request_digest,
                )
            self._session.expire(row)
            return _result(reduced, event_uuid=event_uuid)
        except IntegrityError:
            # A second line of defence if a dialect cannot retain the expected
            # row/gap lock.  Re-read current state and accept only an exact
            # reducer replay; every other integrity conflict remains opaque.
            self._session.expire_all()
            refreshed = self._lock_by_id(row_uuid)
            latest = _domain_claim(refreshed)
            retried = transition_factory(latest)
            if not retried.idempotent_replay:
                raise SfClaimPersistenceError() from None
            self._verify_replay_event(
                refreshed,
                current=latest,
                request_digest=request_digest,
            )
            return _result(retried, event_uuid=None)

    def _write_transition(
        self,
        row: ProviderAccountClaim,
        *,
        before: SfAccountClaim,
        transition: SfClaimTransition,
        proof: SfAdminClaimProof | SfDeletionClaimProof,
        request_digest: bytes,
    ) -> UUID:
        after = transition.claim
        event = transition.event
        if transition.idempotent_replay or event is None:
            raise SfClaimPersistenceError()
        _verify_transition(before, after=after, event=event)

        try:
            reason_code, outcome_code = _EVENT_SAFE_CODES[event.event_kind]
        except KeyError:
            raise SfClaimPersistenceError() from None
        provenance = _event_provenance(proof, actor_type=event.actor_type)
        event_uuid = uuid4()
        transition_digest = _transition_digest(
            fingerprint=before.fingerprint,
            before=before,
            after=after,
            event_kind=event.event_kind,
            action_uuid=event.action_uuid,
            request_digest=request_digest,
            occurred_at=event.occurred_at,
            previous_hash=event.previous_hash,
            record_hash=event.record_hash,
            proof=proof,
            safe_reason_code=reason_code,
            safe_outcome_code=outcome_code,
        )

        previous_owner = before.owner
        new_owner = after.owner
        orm_event = ProviderAccountClaimEvent(
            id=str(event_uuid),
            provider_account_claim_id=row.id,
            claim_generation=event.generation,
            event_sequence=event.sequence,
            from_status=event.before_state.value,
            to_status=event.after_state.value,
            previous_provider_account_id=_owner_value(
                previous_owner, "provider_account_uuid"
            ),
            previous_tenant_id=_owner_value(previous_owner, "tenant_uuid"),
            previous_warehouse_uuid=_owner_value(previous_owner, "warehouse_uuid"),
            new_provider_account_id=_owner_value(new_owner, "provider_account_uuid"),
            new_tenant_id=_owner_value(new_owner, "tenant_uuid"),
            new_warehouse_uuid=_owner_value(new_owner, "warehouse_uuid"),
            actor_type=event.actor_type,
            actor_user_uuid=provenance["actor_user_uuid"],
            actor_session_uuid=provenance["actor_session_uuid"],
            otp_challenge_uuid=provenance["otp_challenge_uuid"],
            source_action_uuid=str(event.action_uuid),
            request_digest=bytes(request_digest),
            deletion_request_uuid=provenance["deletion_request_uuid"],
            deletion_execution_generation=provenance["deletion_execution_generation"],
            tombstone_sequence=provenance["tombstone_sequence"],
            tombstone_record_hash=provenance["tombstone_record_hash"],
            transition_digest=transition_digest,
            previous_event_hash=event.previous_hash,
            record_hash=event.record_hash,
            safe_reason_code=reason_code,
            safe_outcome_code=outcome_code,
            created_at=event.occurred_at,
        )

        changed = self._session.execute(
            sa.update(ProviderAccountClaim)
            .where(
                ProviderAccountClaim.id == row.id,
                ProviderAccountClaim.provider == before.fingerprint.provider,
                ProviderAccountClaim.account_fingerprint == before.fingerprint.digest,
                ProviderAccountClaim.claim_generation == before.generation,
                ProviderAccountClaim.row_version == before.row_version,
                ProviderAccountClaim.event_sequence == before.event_sequence,
                ProviderAccountClaim.event_head_hash == before.event_head_hash,
            )
            .values(
                current_provider_account_id=_owner_value(
                    after.owner, "provider_account_uuid"
                ),
                current_tenant_id=_owner_value(after.owner, "tenant_uuid"),
                current_warehouse_uuid=_owner_value(after.owner, "warehouse_uuid"),
                claim_status=after.state.value,
                claim_generation=after.generation,
                reservation_action_uuid=_optional_uuid_text(
                    after.reservation_action_uuid
                ),
                reservation_request_digest=after.reservation_request_digest,
                reservation_expires_at=after.reservation_expires_at,
                active_binding_revision=after.active_binding_revision,
                last_action_uuid=_optional_uuid_text(after.last_action_uuid),
                last_request_digest=after.last_request_digest,
                last_transition_event_id=str(event_uuid),
                event_sequence=after.event_sequence,
                event_head_hash=after.event_head_hash,
                row_version=after.row_version,
                updated_at=event.occurred_at,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise SfClaimFenceConflict()
        self._session.add(orm_event)
        self._session.flush()
        return event_uuid

    def _verify_replay_event(
        self,
        row: ProviderAccountClaim,
        *,
        current: SfAccountClaim,
        request_digest: bytes,
    ) -> None:
        if row.last_transition_event_id is None or current.event_sequence < 1:
            raise SfClaimPersistenceError()
        event = self._session.scalar(
            sa.select(ProviderAccountClaimEvent)
            .where(
                ProviderAccountClaimEvent.id == row.last_transition_event_id,
                ProviderAccountClaimEvent.provider_account_claim_id == row.id,
            )
            .with_for_update()
        )
        if (
            event is None
            or event.claim_generation != current.generation
            or event.event_sequence != current.event_sequence
            or event.to_status != current.state.value
            or not _stored_owner_matches_current(event, current.owner)
            or event.source_action_uuid != _optional_uuid_text(current.last_action_uuid)
            or not hmac.compare_digest(
                bytes(event.request_digest), bytes(request_digest)
            )
            or not hmac.compare_digest(
                bytes(event.record_hash), current.event_head_hash
            )
        ):
            raise SfClaimPersistenceError()


# More explicit method aliases for callers that name the provider operation.
SfClaimPersistenceService.reserve_sf_claim = SfClaimPersistenceService.reserve_claim
SfClaimPersistenceService.activate_sf_claim = SfClaimPersistenceService.activate_claim
SfClaimPersistenceService.release_sf_claim_by_admin = (
    SfClaimPersistenceService.release_claim_by_admin
)
SfClaimPersistenceService.release_sf_claim_by_deletion = (
    SfClaimPersistenceService.release_claim_by_deletion
)


def _new_unowned_row(
    *,
    claim_uuid: UUID,
    fingerprint: ProviderAccountFingerprint,
    database_now: datetime,
) -> ProviderAccountClaim:
    return ProviderAccountClaim(
        id=str(claim_uuid),
        provider=fingerprint.provider,
        account_fingerprint=bytes(fingerprint.digest),
        fingerprint_version=fingerprint.fingerprint_version,
        fingerprint_root_key_version=fingerprint.root_key_version,
        current_provider_account_id=None,
        current_tenant_id=None,
        current_warehouse_uuid=None,
        claim_status=SfClaimState.RELEASED.value,
        claim_generation=1,
        reservation_action_uuid=None,
        reservation_request_digest=None,
        reservation_expires_at=None,
        active_binding_revision=None,
        last_action_uuid=None,
        last_request_digest=None,
        last_transition_event_id=None,
        event_sequence=0,
        event_head_hash=_ZERO_HASH,
        row_version=1,
        created_at=database_now,
        updated_at=database_now,
    )


def _domain_claim(
    row: ProviderAccountClaim,
    expected_fingerprint: ProviderAccountFingerprint | None = None,
) -> SfAccountClaim:
    try:
        fingerprint = ProviderAccountFingerprint(
            provider=row.provider,
            fingerprint_version=row.fingerprint_version,
            root_key_version=row.fingerprint_root_key_version,
            digest=bytes(row.account_fingerprint),
        )
        if expected_fingerprint is not None and (
            fingerprint.provider != expected_fingerprint.provider
            or fingerprint.fingerprint_version
            != expected_fingerprint.fingerprint_version
            or fingerprint.root_key_version != expected_fingerprint.root_key_version
            or not hmac.compare_digest(fingerprint.digest, expected_fingerprint.digest)
        ):
            raise ValueError("fingerprint metadata changed")

        owner_values = (
            row.current_tenant_id,
            row.current_provider_account_id,
            row.current_warehouse_uuid,
        )
        owner = None
        if any(value is not None for value in owner_values):
            if any(value is None for value in owner_values):
                raise ValueError("claim owner is incomplete")
            owner = SfClaimOwner(
                tenant_uuid=UUID(row.current_tenant_id),
                provider_account_uuid=UUID(row.current_provider_account_id),
                warehouse_uuid=UUID(row.current_warehouse_uuid),
            )

        return SfAccountClaim(
            claim_uuid=UUID(row.id),
            fingerprint=fingerprint,
            state=SfClaimState(row.claim_status),
            generation=row.claim_generation,
            row_version=row.row_version,
            owner=owner,
            reservation_action_uuid=_optional_uuid(row.reservation_action_uuid),
            reservation_request_digest=(
                None
                if row.reservation_request_digest is None
                else bytes(row.reservation_request_digest)
            ),
            reservation_expires_at=row.reservation_expires_at,
            active_binding_revision=row.active_binding_revision,
            last_action_uuid=_optional_uuid(row.last_action_uuid),
            last_request_digest=(
                None
                if row.last_request_digest is None
                else bytes(row.last_request_digest)
            ),
            event_sequence=row.event_sequence,
            event_head_hash=bytes(row.event_head_hash),
        )
    except (
        AttributeError,
        CryptoConfigurationError,
        TypeError,
        ValueError,
    ):
        raise SfClaimPersistenceError() from None


def _verify_transition(
    before: SfAccountClaim,
    *,
    after: SfAccountClaim,
    event: SfClaimEvent,
) -> None:
    expected_event_owner = (
        after.owner if event.event_kind is SfClaimEventKind.RESERVED else before.owner
    )
    if (
        after.claim_uuid != before.claim_uuid
        or after.fingerprint != before.fingerprint
        or after.generation != before.generation + 1
        or after.row_version != before.row_version + 1
        or after.event_sequence != before.event_sequence + 1
        or event.claim_uuid != before.claim_uuid
        or event.before_state is not before.state
        or event.after_state is not after.state
        or event.generation != after.generation
        or event.sequence != after.event_sequence
        or event.previous_hash != before.event_head_hash
        or event.record_hash != after.event_head_hash
        or expected_event_owner is None
        or event.tenant_uuid != expected_event_owner.tenant_uuid
        or event.provider_account_uuid != expected_event_owner.provider_account_uuid
        or event.warehouse_uuid != expected_event_owner.warehouse_uuid
    ):
        raise SfClaimPersistenceError()


def _event_provenance(
    proof: SfAdminClaimProof | SfDeletionClaimProof,
    *,
    actor_type: str,
) -> dict[str, object]:
    if isinstance(proof, SfAdminClaimProof) and actor_type == "tenant_admin":
        return {
            "actor_user_uuid": str(proof.actor_user_uuid),
            "actor_session_uuid": str(proof.actor_session_uuid),
            "otp_challenge_uuid": str(proof.otp_challenge_uuid),
            "deletion_request_uuid": None,
            "deletion_execution_generation": None,
            "tombstone_sequence": None,
            "tombstone_record_hash": None,
        }
    if isinstance(proof, SfDeletionClaimProof) and actor_type == "system_deletion":
        return {
            "actor_user_uuid": None,
            "actor_session_uuid": None,
            "otp_challenge_uuid": None,
            "deletion_request_uuid": str(proof.deletion_request_uuid),
            "deletion_execution_generation": proof.execution_generation,
            "tombstone_sequence": proof.tombstone_sequence,
            "tombstone_record_hash": bytes(proof.tombstone_record_hash),
        }
    raise SfClaimPersistenceError()


def _transition_digest(
    *,
    fingerprint: ProviderAccountFingerprint,
    before: SfAccountClaim,
    after: SfAccountClaim,
    event_kind: SfClaimEventKind,
    action_uuid: UUID,
    request_digest: bytes,
    occurred_at: datetime,
    previous_hash: bytes,
    record_hash: bytes,
    proof: SfAdminClaimProof | SfDeletionClaimProof,
    safe_reason_code: str,
    safe_outcome_code: str,
) -> bytes:
    if isinstance(proof, SfAdminClaimProof):
        proof_payload = {
            "kind": "tenant_admin",
            "tenant_uuid": str(proof.tenant_uuid),
            "actor_user_uuid": str(proof.actor_user_uuid),
            "actor_session_uuid": str(proof.actor_session_uuid),
            "role": proof.role.value,
            "effective_gate": proof.effective_gate.value,
            "tenant_access_version": proof.tenant_access_version,
            "otp_challenge_uuid": str(proof.otp_challenge_uuid),
            "otp_purpose": proof.otp_purpose,
            "otp_action_uuid": str(proof.otp_action_uuid),
            "otp_request_digest": proof.otp_request_digest.hex(),
            "otp_consumed": proof.otp_consumed,
        }
    elif isinstance(proof, SfDeletionClaimProof):
        proof_payload = {
            "kind": "system_deletion",
            "tenant_uuid": str(proof.tenant_uuid),
            "deletion_request_uuid": str(proof.deletion_request_uuid),
            "action_uuid": str(proof.action_uuid),
            "execution_generation": proof.execution_generation,
            "fencing_token": proof.fencing_token,
            "tombstone_sequence": proof.tombstone_sequence,
            "tombstone_record_hash": proof.tombstone_record_hash.hex(),
            "offsite_acknowledged": proof.offsite_acknowledged,
            "irreversible_deletion": proof.irreversible_deletion,
        }
    else:
        raise SfClaimPersistenceError()

    payload = {
        "domain": "inventory-manager/sf-claim-transition/v1",
        "claim_uuid": str(before.claim_uuid),
        "provider": fingerprint.provider,
        "fingerprint_version": fingerprint.fingerprint_version,
        "fingerprint_root_key_version": fingerprint.root_key_version,
        "fingerprint": fingerprint.digest.hex(),
        "from_status": before.state.value,
        "to_status": after.state.value,
        "claim_generation": after.generation,
        "event_sequence": after.event_sequence,
        "previous_owner": _owner_payload(before.owner),
        "new_owner": _owner_payload(after.owner),
        "event_kind": event_kind.value,
        "source_action_uuid": str(action_uuid),
        "request_digest": bytes(request_digest).hex(),
        "occurred_at": _as_utc(occurred_at).isoformat(),
        "previous_event_hash": bytes(previous_hash).hex(),
        "record_hash": bytes(record_hash).hex(),
        "safe_reason_code": safe_reason_code,
        "safe_outcome_code": safe_outcome_code,
        "proof": proof_payload,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("ascii")
    ).digest()


def _owner_payload(owner: SfClaimOwner | None) -> dict[str, str] | None:
    if owner is None:
        return None
    return {
        "tenant_uuid": str(owner.tenant_uuid),
        "provider_account_uuid": str(owner.provider_account_uuid),
        "warehouse_uuid": str(owner.warehouse_uuid),
    }


def _owner_value(owner: SfClaimOwner | None, attribute: str) -> str | None:
    if owner is None:
        return None
    return str(getattr(owner, attribute))


def _stored_owner_matches_current(
    event: ProviderAccountClaimEvent,
    owner: SfClaimOwner | None,
) -> bool:
    return (
        event.new_tenant_id == _owner_value(owner, "tenant_uuid")
        and event.new_provider_account_id
        == _owner_value(owner, "provider_account_uuid")
        and event.new_warehouse_uuid == _owner_value(owner, "warehouse_uuid")
    )


def _is_currently_unavailable(
    claim: SfAccountClaim,
    *,
    database_now: datetime,
) -> bool:
    if claim.state is SfClaimState.ACTIVE:
        return True
    return bool(
        claim.state is SfClaimState.RESERVED
        and claim.reservation_expires_at is not None
        and _as_utc(claim.reservation_expires_at) > database_now
    )


def _result(
    transition: SfClaimTransition,
    *,
    event_uuid: UUID | None,
) -> SfClaimPersistenceResult:
    return SfClaimPersistenceResult(
        claim_uuid=transition.claim.claim_uuid,
        state=transition.claim.state,
        generation=transition.claim.generation,
        row_version=transition.claim.row_version,
        event_sequence=transition.claim.event_sequence,
        transition_event_uuid=event_uuid,
        event_kind=(None if transition.event is None else transition.event.event_kind),
        idempotent_replay=transition.idempotent_replay,
    )


def _fingerprint(value: object) -> ProviderAccountFingerprint:
    if not isinstance(value, ProviderAccountFingerprint):
        raise TypeError("fingerprint must be a ProviderAccountFingerprint")
    return value


def _uuid(value: str | UUID) -> UUID:
    if isinstance(value, UUID):
        selected = value
    elif isinstance(value, str):
        try:
            selected = UUID(value)
        except ValueError:
            raise ValueError("technical identity is invalid") from None
    else:
        raise ValueError("technical identity is invalid")
    if selected.int == 0:
        raise ValueError("technical identity is invalid")
    return selected


def _optional_uuid(value: str | None) -> UUID | None:
    return None if value is None else _uuid(value)


def _optional_uuid_text(value: UUID | None) -> str | None:
    return None if value is None else str(value)


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise SfClaimPersistenceError()
    if value.tzinfo is None:
        # MySQL and MariaDB control databases are required to run in UTC.
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _read_database_utc_now(session: Session) -> datetime:
    return _as_utc(read_database_utc_value(session))


__all__ = [
    "SfClaimPersistenceError",
    "SfClaimPersistenceResult",
    "SfClaimPersistenceService",
    "SfClaimTransactionError",
]
