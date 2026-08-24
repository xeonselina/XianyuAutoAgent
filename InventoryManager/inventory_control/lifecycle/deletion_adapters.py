"""Control-database-only current-read evidence for D26 deletion.

This module deliberately proves only facts represented by current control
models: the current D58 run/hold tombstone disposition and the permanent SF
claim/event ledger.  The repository does not yet contain authoritative
provider-account/binding, reserved verification-operation, or D58
source-linked normalization-item inventories.  Consequently this adapter is
protocol-compatible but never upgrades its partial inspection into a complete
claim-release/destructive-cleanup authorization.  A caller must not treat
``verified=False`` as retryable success.

All reads are locking current reads in an explicit, clean caller-owned
transaction.  The adapter performs no provider, NAS, tenant-MySQL, commit, or
rollback operation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

import sqlalchemy as sa
from sqlalchemy.orm import Session, SessionTransactionOrigin

from inventory_control.lifecycle.deletion import (
    DeletionClaimReleaseEvidence,
    DeletionRequest,
    DeletionState,
    DeletionTransition,
    DeletionTombstone,
    DestructiveCleanupEvidence,
)
from inventory_control.lifecycle.deletion_persistence import (
    DeletionEvidenceVerification,
    DeletionPersistenceEvidenceError,
    RecoveryDispositionVerification,
    deletion_evidence_digest,
)
from inventory_control.models.provider_claims import (
    ProviderAccountClaim,
    ProviderAccountClaimEvent,
)
from inventory_control.models.recovery import (
    DisasterRecoveryRun,
    TenantRecoveryHold,
)


_ZERO_HASH = b"\x00" * 32
_CLAIM_RECEIPT_KINDS = {"claim_release", "destructive_cleanup"}


class DeletionControlEvidenceError(DeletionPersistenceEvidenceError):
    """Stable fail-closed rejection for corrupt or drifting control facts."""


@dataclass(frozen=True, slots=True)
class DeletionControlCurrentReadFacts:
    """Bounded proof of the subset available in today's control schema."""

    recovery_run_id: str
    recovery_hold_id: str
    recovery_hold_revision: int
    recovery_disposition_digest: bytes
    recovery_hold_disposition_verified: bool
    claims_scanned: int
    tenant_related_claims: int
    released_claims: int
    valid_new_owner_claims: int
    no_current_old_owner: bool
    claim_event_chains_verified: bool
    claim_release_provenance_verified: bool
    # These facts require authoritative models that do not exist yet.  They
    # stay explicit instead of being inferred from caller-supplied booleans.
    bidirectional_binding_inventory_verified: bool = False
    reserved_operations_inventory_verified: bool = False
    recovery_normalization_inventory_verified: bool = False

    @property
    def provable_subset_verified(self) -> bool:
        return bool(
            self.recovery_hold_disposition_verified
            and self.no_current_old_owner
            and self.claim_event_chains_verified
            and self.claim_release_provenance_verified
        )

    @property
    def complete_deletion_evidence_verified(self) -> bool:
        return bool(
            self.provable_subset_verified
            and self.bidirectional_binding_inventory_verified
            and self.reserved_operations_inventory_verified
            and self.recovery_normalization_inventory_verified
        )


class ControlDatabaseDeletionEvidenceAdapter:
    """Protocol-compatible locking reader for the provable D26 subset."""

    def __call__(
        self,
        session: Session,
        *,
        receipt_kind: str,
        evidence: object,
        evidence_digest: bytes,
        prior_state: DeletionState,
        transition: DeletionTransition,
        database_now_utc: datetime,
    ) -> DeletionEvidenceVerification:
        facts = self.inspect_current(
            session,
            receipt_kind=receipt_kind,
            evidence=evidence,
            evidence_digest=evidence_digest,
            prior_state=prior_state,
            transition=transition,
            database_now_utc=database_now_utc,
        )
        return DeletionEvidenceVerification(
            verifier_kind=(
                "provider_claim_current_read"
                if receipt_kind == "claim_release"
                else "destructive_current_read"
            ),
            evidence_digest=bytes(evidence_digest),
            verified_at_utc=_aware_utc(database_now_utc),
            verified=facts.complete_deletion_evidence_verified,
            recovery_disposition=RecoveryDispositionVerification(
                recovery_run_id=facts.recovery_run_id,
                recovery_hold_id=facts.recovery_hold_id,
                recovery_hold_revision=facts.recovery_hold_revision,
                disposition_digest=facts.recovery_disposition_digest,
                all_required_dispositions_complete=(
                    facts.recovery_normalization_inventory_verified
                ),
            ),
        )

    def inspect_current(
        self,
        session: Session,
        *,
        receipt_kind: str,
        evidence: object,
        evidence_digest: bytes,
        prior_state: DeletionState,
        transition: DeletionTransition,
        database_now_utc: datetime,
    ) -> DeletionControlCurrentReadFacts:
        """Lock and inspect current D58 and SF claim facts without mutation."""

        _prepare(session)
        now = _aware_utc(database_now_utc)
        if receipt_kind not in _CLAIM_RECEIPT_KINDS:
            _fail("DELETION_CONTROL_EVIDENCE_KIND_UNSUPPORTED")
        expected_type = (
            DeletionClaimReleaseEvidence
            if receipt_kind == "claim_release"
            else DestructiveCleanupEvidence
        )
        if not isinstance(evidence, expected_type):
            _fail("DELETION_CONTROL_EVIDENCE_TYPE_INVALID")
        canonical_digest = deletion_evidence_digest(evidence)
        if (
            not isinstance(evidence_digest, bytes)
            or len(evidence_digest) != 32
            or not hmac.compare_digest(evidence_digest, canonical_digest)
        ):
            _fail("DELETION_CONTROL_EVIDENCE_DIGEST_MISMATCH")

        request, tombstone = _require_transition_scope(
            prior_state=prior_state,
            transition=transition,
            evidence=evidence,
        )

        # The coordinator has already locked tenant -> current run -> hold ->
        # deletion/action/tombstone -> route before invoking this adapter.  The
        # repeated run/hold reads are locking current reads and never reverse
        # that prefix.  Claim rows then follow in stable provider/UUID order,
        # and their append-only events are locked last.
        run = session.scalar(
            sa.select(DisasterRecoveryRun)
            .where(DisasterRecoveryRun.current_run_marker == "current")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if run is None:
            _fail("DELETION_CURRENT_RECOVERY_RUN_REQUIRED")
        hold = session.scalar(
            sa.select(TenantRecoveryHold)
            .where(
                TenantRecoveryHold.recovery_run_id == run.id,
                TenantRecoveryHold.tenant_id == str(transition.state.tenant_id),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if hold is None:
            _fail("DELETION_CURRENT_RECOVERY_HOLD_REQUIRED")
        _verify_hold(
            hold,
            request=request,
            tombstone=tombstone,
            database_id=str(transition.state.database_id),
            database_now=now,
        )

        claims = tuple(
            session.scalars(
                sa.select(ProviderAccountClaim)
                .where(ProviderAccountClaim.provider == "sf")
                .order_by(
                    ProviderAccountClaim.provider.asc(),
                    ProviderAccountClaim.id.asc(),
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
        claim_ids = tuple(row.id for row in claims)
        events: tuple[ProviderAccountClaimEvent, ...]
        if claim_ids:
            events = tuple(
                session.scalars(
                    sa.select(ProviderAccountClaimEvent)
                    .where(
                        ProviderAccountClaimEvent.provider_account_claim_id.in_(
                            claim_ids
                        )
                    )
                    .order_by(
                        ProviderAccountClaimEvent.provider_account_claim_id.asc(),
                        ProviderAccountClaimEvent.event_sequence.asc(),
                    )
                    .with_for_update()
                    .execution_options(populate_existing=True)
                )
            )
        else:
            events = ()

        by_claim: dict[str, list[ProviderAccountClaimEvent]] = {
            claim_id: [] for claim_id in claim_ids
        }
        for event in events:
            try:
                by_claim[event.provider_account_claim_id].append(event)
            except KeyError:
                _fail("DELETION_SF_CLAIM_EVENT_ORPHANED")

        tenant_id = str(transition.state.tenant_id)
        related = 0
        released = 0
        valid_new_owner = 0
        related_claim_rows: list[ProviderAccountClaim] = []
        for claim in claims:
            history = tuple(by_claim[claim.id])
            _verify_claim_chain(claim, history, database_now=now)
            touched = any(
                event.previous_tenant_id == tenant_id
                or event.new_tenant_id == tenant_id
                for event in history
            ) or claim.current_tenant_id == tenant_id
            if not touched:
                continue
            related += 1
            related_claim_rows.append(claim)
            if claim.current_tenant_id == tenant_id:
                _fail("DELETION_SF_CLAIM_OLD_OWNER_REMAINS")
            _verify_target_release_provenance(
                history,
                tenant_id=tenant_id,
                request=request,
                tombstone=tombstone,
            )
            if claim.claim_status == "released":
                released += 1
            else:
                valid_new_owner += 1

        disposition_digest = _disposition_digest(
            run=run,
            hold=hold,
            request=request,
            tombstone=tombstone,
            claims=related_claim_rows,
        )
        return DeletionControlCurrentReadFacts(
            recovery_run_id=run.id,
            recovery_hold_id=hold.id,
            recovery_hold_revision=hold.hold_revision,
            recovery_disposition_digest=disposition_digest,
            recovery_hold_disposition_verified=True,
            claims_scanned=len(claims),
            tenant_related_claims=related,
            released_claims=released,
            valid_new_owner_claims=valid_new_owner,
            no_current_old_owner=True,
            claim_event_chains_verified=True,
            claim_release_provenance_verified=True,
        )


def _prepare(session: Session) -> None:
    if not isinstance(session, Session):
        _fail("DELETION_CONTROL_EVIDENCE_TRANSACTION_REQUIRED")
    transaction = session.get_transaction()
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
    ):
        _fail("DELETION_CONTROL_EVIDENCE_TRANSACTION_REQUIRED")
    dirty = any(
        session.is_modified(instance, include_collections=True)
        for instance in session.dirty
    )
    if session.new or session.deleted or dirty:
        _fail("DELETION_CONTROL_EVIDENCE_CLEAN_UNIT_OF_WORK_REQUIRED")


def _require_transition_scope(
    *,
    prior_state: DeletionState,
    transition: DeletionTransition,
    evidence: DeletionClaimReleaseEvidence | DestructiveCleanupEvidence,
) -> tuple[DeletionRequest, DeletionTombstone]:
    if not isinstance(prior_state, DeletionState) or not isinstance(
        transition, DeletionTransition
    ):
        _fail("DELETION_CONTROL_EVIDENCE_STATE_INVALID")
    request = transition.state.request
    prior_request = prior_state.request
    if (
        request is None
        or prior_request is None
        or request.request_id != prior_request.request_id
        or transition.state.tenant_id != prior_state.tenant_id
        or transition.state.database_id != prior_state.database_id
        or request.current_action.action_id != evidence.action_id
        or request.execution_generation != evidence.execution_generation
        or request.executor_fencing_token != evidence.executor_fencing_token
        or transition.state.tenant_access_version
        != evidence.tenant_access_version
    ):
        _fail("DELETION_CONTROL_EVIDENCE_STATE_MISMATCH")
    tombstone = request.tombstone
    if (
        tombstone is None
        or tombstone.sequence != evidence.tombstone_sequence
        or tombstone.head_hash != evidence.tombstone_head_hash
    ):
        _fail("DELETION_CONTROL_EVIDENCE_TOMBSTONE_MISMATCH")
    return request, tombstone


def _verify_hold(
    hold: TenantRecoveryHold,
    *,
    request: DeletionRequest,
    tombstone: DeletionTombstone,
    database_id: str,
    database_now: datetime,
) -> None:
    tombstoned_at = _optional_utc(hold.tombstoned_at)
    if (
        hold.database_uuid != database_id
        or hold.state != "tombstoned"
        or hold.terminal_reason_code != "superseded_by_deletion"
        or hold.deletion_request_uuid != str(request.request_id)
        or hold.tombstone_ledger_sequence != tombstone.sequence
        or hold.tombstone_record_hash is None
        or not hmac.compare_digest(
            bytes(hold.tombstone_record_hash), tombstone.record_hash
        )
        or tombstoned_at is None
        or tombstoned_at < tombstone.recorded_at_utc
        or tombstoned_at > database_now
    ):
        _fail("DELETION_RECOVERY_DISPOSITION_MISMATCH")


def _verify_claim_chain(
    claim: ProviderAccountClaim,
    events: tuple[ProviderAccountClaimEvent, ...],
    *,
    database_now: datetime,
) -> None:
    _verify_claim_state_shape(claim)
    if claim.provider != "sf" or claim.claim_generation != claim.event_sequence + 1:
        _fail("DELETION_SF_CLAIM_CHAIN_INVALID")
    if claim.event_sequence == 0:
        if (
            events
            or claim.claim_generation != 1
            or claim.last_transition_event_id is not None
            or bytes(claim.event_head_hash) != _ZERO_HASH
        ):
            _fail("DELETION_SF_CLAIM_CHAIN_INVALID")
        return
    if len(events) != claim.event_sequence:
        _fail("DELETION_SF_CLAIM_CHAIN_INVALID")

    previous_status = "released"
    previous_owner: tuple[str, str, str] | None = None
    previous_hash = _ZERO_HASH
    previous_created_at: datetime | None = None
    for expected_sequence, event in enumerate(events, start=1):
        created_at = _database_utc(event.created_at)
        if (
            event.event_sequence != expected_sequence
            or event.claim_generation != expected_sequence + 1
            or event.from_status != previous_status
            or _event_owner(event, previous=True) != previous_owner
            or bytes(event.previous_event_hash) != previous_hash
            or created_at > database_now
            or (
                previous_created_at is not None
                and created_at < previous_created_at
            )
        ):
            _fail("DELETION_SF_CLAIM_CHAIN_INVALID")
        _verify_event_provenance_shape(event)
        new_owner = _event_owner(event, previous=False)
        _verify_owner_shape(
            status=event.to_status,
            provider_account_id=event.new_provider_account_id,
            tenant_id=event.new_tenant_id,
            warehouse_id=event.new_warehouse_uuid,
        )
        if (event.from_status, event.to_status) not in {
            ("released", "reserved"),
            ("reserved", "active"),
            ("reserved", "released"),
            ("active", "released"),
        }:
            _fail("DELETION_SF_CLAIM_CHAIN_INVALID")
        if not hmac.compare_digest(
            bytes(event.record_hash), _event_record_hash(claim, event)
        ):
            _fail("DELETION_SF_CLAIM_CHAIN_INVALID")
        previous_status = event.to_status
        previous_owner = new_owner
        previous_hash = bytes(event.record_hash)
        previous_created_at = created_at

    latest = events[-1]
    current_owner = _claim_owner(claim)
    if (
        claim.last_transition_event_id != latest.id
        or claim.claim_generation != latest.claim_generation
        or claim.event_sequence != latest.event_sequence
        or claim.claim_status != latest.to_status
        or current_owner != _event_owner(latest, previous=False)
        or not hmac.compare_digest(bytes(claim.event_head_hash), previous_hash)
        or claim.last_action_uuid != latest.source_action_uuid
        or claim.last_request_digest is None
        or not hmac.compare_digest(
            bytes(claim.last_request_digest), bytes(latest.request_digest)
        )
    ):
        _fail("DELETION_SF_CLAIM_OWNER_DRIFT")


def _verify_target_release_provenance(
    events: Iterable[ProviderAccountClaimEvent],
    *,
    tenant_id: str,
    request: DeletionRequest,
    tombstone: DeletionTombstone,
) -> None:
    acquired = False
    released = False
    for event in events:
        if event.new_tenant_id == tenant_id:
            acquired = True
            released = False
        if event.previous_tenant_id != tenant_id or event.to_status != "released":
            continue
        if _event_owner(event, previous=False) is not None:
            _fail("DELETION_SF_CLAIM_RELEASE_PROVENANCE_INVALID")
        if event.actor_type == "system_deletion":
            if (
                event.deletion_request_uuid != str(request.request_id)
                or event.source_action_uuid
                != str(request.current_action.action_id)
                or event.deletion_execution_generation
                != request.execution_generation
                or event.tombstone_sequence != tombstone.sequence
                or event.tombstone_record_hash is None
                or not hmac.compare_digest(
                    bytes(event.tombstone_record_hash), tombstone.record_hash
                )
            ):
                _fail("DELETION_SF_CLAIM_RELEASE_PROVENANCE_INVALID")
        elif event.actor_type == "tenant_admin":
            if (
                event.actor_user_uuid is None
                or event.actor_session_uuid is None
                or event.otp_challenge_uuid is None
                or event.deletion_request_uuid is not None
                or event.deletion_execution_generation is not None
                or event.tombstone_sequence is not None
                or event.tombstone_record_hash is not None
            ):
                _fail("DELETION_SF_CLAIM_RELEASE_PROVENANCE_INVALID")
        else:
            # No confirmed D26 rule allows a system_reconciler event to stand
            # in for this deletion's normal claim-release provenance.
            _fail("DELETION_SF_CLAIM_RELEASE_PROVENANCE_INVALID")
        released = True
    if acquired and not released:
        _fail("DELETION_SF_CLAIM_OLD_OWNER_REMAINS")


def _verify_owner_shape(
    *,
    status: str,
    provider_account_id: str | None,
    tenant_id: str | None,
    warehouse_id: str | None,
) -> None:
    owner = (provider_account_id, tenant_id, warehouse_id)
    if status == "released":
        valid = owner == (None, None, None)
    elif status in {"reserved", "active"}:
        valid = all(value is not None for value in owner)
    else:
        valid = False
    if not valid:
        _fail("DELETION_SF_CLAIM_OWNER_DRIFT")


def _verify_claim_state_shape(claim: ProviderAccountClaim) -> None:
    _verify_owner_shape(
        status=claim.claim_status,
        provider_account_id=claim.current_provider_account_id,
        tenant_id=claim.current_tenant_id,
        warehouse_id=claim.current_warehouse_uuid,
    )
    if claim.claim_status == "released":
        valid = bool(
            claim.reservation_action_uuid is None
            and claim.reservation_request_digest is None
            and claim.reservation_expires_at is None
            and claim.active_binding_revision is None
        )
    elif claim.claim_status == "reserved":
        valid = bool(
            claim.reservation_action_uuid is not None
            and claim.reservation_request_digest is not None
            and len(bytes(claim.reservation_request_digest)) == 32
            and claim.reservation_expires_at is not None
            and claim.active_binding_revision is None
        )
    else:
        valid = bool(
            claim.reservation_action_uuid is None
            and claim.reservation_request_digest is None
            and claim.reservation_expires_at is None
            and isinstance(claim.active_binding_revision, int)
            and claim.active_binding_revision >= 1
        )
    if not valid:
        _fail("DELETION_SF_CLAIM_OWNER_DRIFT")


def _verify_event_provenance_shape(event: ProviderAccountClaimEvent) -> None:
    if (
        len(bytes(event.request_digest)) != 32
        or len(bytes(event.transition_digest)) != 32
        or len(bytes(event.previous_event_hash)) != 32
        or len(bytes(event.record_hash)) != 32
    ):
        _fail("DELETION_SF_CLAIM_CHAIN_INVALID")
    if event.actor_type == "tenant_admin":
        valid = bool(
            event.actor_user_uuid is not None
            and event.actor_session_uuid is not None
            and event.otp_challenge_uuid is not None
            and event.deletion_request_uuid is None
            and event.deletion_execution_generation is None
            and event.tombstone_sequence is None
            and event.tombstone_record_hash is None
        )
    elif event.actor_type == "system_deletion":
        valid = bool(
            event.actor_user_uuid is None
            and event.actor_session_uuid is None
            and event.otp_challenge_uuid is None
            and event.deletion_request_uuid is not None
            and isinstance(event.deletion_execution_generation, int)
            and event.deletion_execution_generation >= 1
            and isinstance(event.tombstone_sequence, int)
            and event.tombstone_sequence >= 1
            and event.tombstone_record_hash is not None
            and len(bytes(event.tombstone_record_hash)) == 32
        )
    else:
        valid = False
    if not valid:
        _fail("DELETION_SF_CLAIM_RELEASE_PROVENANCE_INVALID")


def _event_owner(
    event: ProviderAccountClaimEvent,
    *,
    previous: bool,
) -> tuple[str, str, str] | None:
    values = (
        (
            event.previous_provider_account_id,
            event.previous_tenant_id,
            event.previous_warehouse_uuid,
        )
        if previous
        else (
            event.new_provider_account_id,
            event.new_tenant_id,
            event.new_warehouse_uuid,
        )
    )
    if values == (None, None, None):
        return None
    if any(value is None for value in values):
        _fail("DELETION_SF_CLAIM_OWNER_DRIFT")
    return values  # type: ignore[return-value]


def _claim_owner(claim: ProviderAccountClaim) -> tuple[str, str, str] | None:
    values = (
        claim.current_provider_account_id,
        claim.current_tenant_id,
        claim.current_warehouse_uuid,
    )
    if values == (None, None, None):
        return None
    if any(value is None for value in values):
        _fail("DELETION_SF_CLAIM_OWNER_DRIFT")
    return values  # type: ignore[return-value]


def _event_record_hash(
    claim: ProviderAccountClaim,
    event: ProviderAccountClaimEvent,
) -> bytes:
    owner = (
        _event_owner(event, previous=False)
        if event.from_status == "released"
        else _event_owner(event, previous=True)
    )
    if owner is None:
        _fail("DELETION_SF_CLAIM_CHAIN_INVALID")
    provider_account_id, tenant_id, warehouse_id = owner
    payload = {
        "claim_uuid": claim.id,
        "fingerprint_sha256": bytes(claim.account_fingerprint).hex(),
        "fingerprint_version": claim.fingerprint_version,
        "root_key_version": claim.fingerprint_root_key_version,
        "event_kind": _event_kind(event),
        "before_state": event.from_status,
        "after_state": event.to_status,
        "generation": event.claim_generation,
        "sequence": event.event_sequence,
        "action_uuid": event.source_action_uuid,
        "actor_type": event.actor_type,
        "tenant_uuid": tenant_id,
        "provider_account_uuid": provider_account_id,
        "warehouse_uuid": warehouse_id,
        "occurred_at": _database_utc(event.created_at).isoformat(),
        "previous_hash": bytes(event.previous_event_hash).hex(),
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "ascii"
        )
    ).digest()


def _event_kind(event: ProviderAccountClaimEvent) -> str:
    if (event.from_status, event.to_status) == ("released", "reserved"):
        return "reserved"
    if (event.from_status, event.to_status) == ("reserved", "active"):
        return "activated"
    if event.to_status == "released" and event.actor_type == "tenant_admin":
        return "released_by_admin"
    if event.to_status == "released" and event.actor_type == "system_deletion":
        return "released_by_deletion"
    _fail("DELETION_SF_CLAIM_CHAIN_INVALID")


def _disposition_digest(
    *,
    run: DisasterRecoveryRun,
    hold: TenantRecoveryHold,
    request: DeletionRequest,
    tombstone: DeletionTombstone,
    claims: Iterable[ProviderAccountClaim],
) -> bytes:
    claim_fences = [
        {
            "claim_uuid": claim.id,
            "generation": claim.claim_generation,
            "row_version": claim.row_version,
            "event_sequence": claim.event_sequence,
            "event_head_hash": bytes(claim.event_head_hash).hex(),
            "state": claim.claim_status,
        }
        for claim in claims
    ]
    payload = {
        "domain": "inventory-manager/deletion-control-current-read/v1",
        "recovery_run_uuid": run.id,
        "recovery_hold_uuid": hold.id,
        "recovery_hold_revision": hold.hold_revision,
        "tenant_uuid": str(tombstone.tenant_id),
        "deletion_request_uuid": str(request.request_id),
        "deletion_execution_generation": request.execution_generation,
        "tombstone_sequence": tombstone.sequence,
        "tombstone_record_hash": tombstone.record_hash.hex(),
        "claim_fences": claim_fences,
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "ascii"
        )
    ).digest()


def _database_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        _fail("DELETION_CONTROL_EVIDENCE_TIME_INVALID")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _aware_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        _fail("DELETION_CONTROL_EVIDENCE_TIME_INVALID")
    return value.astimezone(timezone.utc)


def _optional_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _database_utc(value)


def _fail(code: str) -> None:
    raise DeletionControlEvidenceError(code)


__all__ = [
    "ControlDatabaseDeletionEvidenceAdapter",
    "DeletionControlCurrentReadFacts",
    "DeletionControlEvidenceError",
]
