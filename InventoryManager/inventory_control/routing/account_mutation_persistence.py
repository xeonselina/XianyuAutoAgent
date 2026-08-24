"""Caller-owned SQLAlchemy persistence for account-mutation reducers.

Lease methods are deliberately limited to the single lease table and are
intended to run in dedicated short transactions.  Rotation methods persist
only control-plane state with an optimistic row fence.  They do not acquire,
hold, or claim to prove a MySQL advisory lock, an application route gate, or
any external account operation; callers must establish those boundaries and
provide the reducer proof facts.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from inventory_control.database import read_database_utc_value
from inventory_control.models.account_mutations import (
    TenantDatabaseAccountMutationLease,
    TenantDatabaseAccountRotation,
)

from .account_mutation import (
    AccountCandidatePreparationProof,
    AccountGeneration,
    AccountLeaseEffectKind,
    AccountLeaseTransition,
    AccountMutationEffects,
    AccountMutationError,
    AccountMutationFenceConflict,
    AccountMutationLease,
    AccountRevocationProof,
    AccountRotation,
    AccountRotationPurpose,
    AccountRotationTransition,
    AccountUnlockAuthorityProof,
    begin_account_candidate_testing as _reduce_begin_testing,
    begin_previous_account_draining as _reduce_begin_draining,
    claim_account_mutation_lease as _reduce_claim_lease,
    fail_account_rotation as _reduce_fail,
    mark_account_candidate_prepared as _reduce_prepare,
    release_account_mutation_lease as _reduce_release_lease,
    renew_account_mutation_lease as _reduce_renew_lease,
    revoke_previous_account as _reduce_revoke,
    start_account_rotation as _reduce_start,
    switch_account_candidate as _reduce_switch,
    verify_account_candidate as _reduce_verify,
)
from .identity import AccountKind
from .router import AccountLoginState


class AccountMutationPersistenceError(AccountMutationError):
    """Stable failure for persistence or stored-state corruption."""

    code = "ACCOUNT_MUTATION_PERSISTENCE_FAILED"
    public_message = "the database account mutation could not be persisted"


class AccountMutationTransactionError(AccountMutationPersistenceError):
    """The caller did not provide a clean explicit transaction."""

    code = "ACCOUNT_MUTATION_TRANSACTION_INVALID"
    public_message = "an explicit clean caller-owned transaction is required"


class AccountMutationStoredStateError(AccountMutationPersistenceError):
    """A persisted lease or rotation does not satisfy domain invariants."""

    code = "ACCOUNT_MUTATION_STORED_STATE_INVALID"
    public_message = "the database account mutation state is invalid"


@dataclass(frozen=True, slots=True)
class AccountMutationLeasePersistenceResult:
    lease: AccountMutationLease
    effect: AccountLeaseEffectKind
    idempotent_replay: bool


@dataclass(frozen=True, slots=True)
class AccountRotationPersistenceResult:
    rotation_row_uuid: UUID
    rotation: AccountRotation
    row_version: int
    effects: AccountMutationEffects
    idempotent_replay: bool

    @property
    def rotation_uuid(self) -> UUID:
        return self.rotation.rotation_uuid


DatabaseClock = Callable[[Session], datetime]
_LeaseFactory = Callable[
    [AccountMutationLease, datetime],
    AccountLeaseTransition,
]
_RotationFactory = Callable[
    [AccountRotation, AccountMutationLease, datetime],
    AccountRotationTransition,
]


class AccountMutationLeasePersistenceService:
    """Persist lease reducers in a lease-row-only caller transaction."""

    def __init__(
        self,
        session: Session,
        *,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not isinstance(session, Session):
            raise AccountMutationTransactionError()
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._session = session
        self._database_clock = database_clock or _read_database_utc_now

    def claim_lease(
        self,
        *,
        tenant_uuid: str | UUID,
        account_kind: AccountKind,
        owner: str,
        purpose: str,
        expected_row_version: int,
        lease_expires_at: datetime,
    ) -> AccountMutationLeasePersistenceResult:
        """Claim or take over exactly one tenant/account-kind lease row."""

        self._prepare()
        tenant_id = _uuid(tenant_uuid)
        selected_kind = _account_kind(account_kind)

        def reduce(
            current: AccountMutationLease,
            database_now: datetime,
        ) -> AccountLeaseTransition:
            return _reduce_claim_lease(
                current,
                owner=owner,
                purpose=purpose,
                expected_row_version=expected_row_version,
                lease_expires_at=lease_expires_at,
                database_now=database_now,
            )

        row = self._lock_lease(tenant_id, selected_kind)
        now = self._now()
        if row is not None:
            return self._apply_existing(
                row,
                reducer=reduce,
                database_now=now,
                replay_expected_row_version=expected_row_version,
            )

        initial = AccountMutationLease.unclaimed(
            tenant_uuid=tenant_id,
            account_kind=selected_kind,
        )
        reduced = reduce(initial, now)
        candidate = _new_lease_row(reduced.lease, database_now=now)
        try:
            with self._session.begin_nested():
                self._session.add(candidate)
                self._session.flush()
            self._session.expire(candidate)
            return _lease_result(reduced)
        except IntegrityError:
            # The unique composite primary key linearizes first creation.  A
            # loser accepts only the pure reducer's exact replay outcome.
            self._session.expire_all()
            winner = self._lock_lease(tenant_id, selected_kind)
            if winner is None:
                raise AccountMutationPersistenceError() from None
            winner_now = self._now()
            return self._apply_existing(
                winner,
                reducer=reduce,
                database_now=winner_now,
                replay_expected_row_version=expected_row_version,
            )

    def renew_lease(
        self,
        *,
        tenant_uuid: str | UUID,
        account_kind: AccountKind,
        owner: str,
        fencing_token: int,
        expected_row_version: int,
        lease_expires_at: datetime,
    ) -> AccountMutationLeasePersistenceResult:
        """Extend a current lease without changing its fencing token."""

        def reduce(
            current: AccountMutationLease,
            database_now: datetime,
        ) -> AccountLeaseTransition:
            return _reduce_renew_lease(
                current,
                owner=owner,
                fencing_token=fencing_token,
                expected_row_version=expected_row_version,
                lease_expires_at=lease_expires_at,
                database_now=database_now,
            )

        return self._mutate_existing(
            tenant_uuid=tenant_uuid,
            account_kind=account_kind,
            reducer=reduce,
        )

    def release_lease(
        self,
        *,
        tenant_uuid: str | UUID,
        account_kind: AccountKind,
        owner: str,
        fencing_token: int,
        expected_row_version: int,
    ) -> AccountMutationLeasePersistenceResult:
        """Release one lease while retaining its monotonic fencing token."""

        def reduce(
            current: AccountMutationLease,
            database_now: datetime,
        ) -> AccountLeaseTransition:
            return _reduce_release_lease(
                current,
                owner=owner,
                fencing_token=fencing_token,
                expected_row_version=expected_row_version,
                database_now=database_now,
            )

        return self._mutate_existing(
            tenant_uuid=tenant_uuid,
            account_kind=account_kind,
            reducer=reduce,
        )

    claim = claim_lease
    renew = renew_lease
    release = release_lease

    def _mutate_existing(
        self,
        *,
        tenant_uuid: str | UUID,
        account_kind: AccountKind,
        reducer: _LeaseFactory,
    ) -> AccountMutationLeasePersistenceResult:
        self._prepare()
        tenant_id = _uuid(tenant_uuid)
        selected_kind = _account_kind(account_kind)
        row = self._lock_lease(tenant_id, selected_kind)
        if row is None:
            raise AccountMutationFenceConflict()
        now = self._now()
        return self._apply_existing(row, reducer=reducer, database_now=now)

    def _apply_existing(
        self,
        row: TenantDatabaseAccountMutationLease,
        *,
        reducer: _LeaseFactory,
        database_now: datetime,
        replay_expected_row_version: int | None = None,
    ) -> AccountMutationLeasePersistenceResult:
        before = _domain_lease(row)
        reduced = reducer(before, database_now)
        if reduced.idempotent_replay:
            if (
                replay_expected_row_version is not None
                and before.row_version != replay_expected_row_version + 1
            ):
                raise AccountMutationFenceConflict()
            return _lease_result(reduced)

        after = reduced.lease
        _verify_lease_transition(before, after)
        try:
            with self._session.begin_nested():
                changed = self._session.execute(
                    sa.update(TenantDatabaseAccountMutationLease)
                    .where(
                        TenantDatabaseAccountMutationLease.tenant_id
                        == row.tenant_id,
                        TenantDatabaseAccountMutationLease.account_kind
                        == row.account_kind,
                        TenantDatabaseAccountMutationLease.fencing_token
                        == before.fencing_token,
                        TenantDatabaseAccountMutationLease.row_version
                        == before.row_version,
                        TenantDatabaseAccountMutationLease.lease_owner
                        == before.owner,
                        TenantDatabaseAccountMutationLease.lease_purpose
                        == before.purpose,
                        TenantDatabaseAccountMutationLease.lease_expires_at
                        == before.expires_at,
                    )
                    .values(
                        fencing_token=after.fencing_token,
                        lease_owner=after.owner,
                        lease_purpose=after.purpose,
                        lease_expires_at=after.expires_at,
                        row_version=after.row_version,
                        updated_at=database_now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    raise AccountMutationFenceConflict()
                self._session.flush()
        except IntegrityError:
            raise AccountMutationPersistenceError() from None
        self._session.expire(row)
        return _lease_result(reduced)

    def _lock_lease(
        self,
        tenant_uuid: UUID,
        account_kind: AccountKind,
    ) -> TenantDatabaseAccountMutationLease | None:
        return self._session.scalar(
            sa.select(TenantDatabaseAccountMutationLease)
            .where(
                TenantDatabaseAccountMutationLease.tenant_id
                == str(tenant_uuid),
                TenantDatabaseAccountMutationLease.account_kind
                == account_kind.value,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _prepare(self) -> None:
        _prepare_session(self._session)

    def _now(self) -> datetime:
        return _as_utc(self._database_clock(self._session))


class AccountRotationPersistenceService:
    """Low-level reducer persistence; external locks remain caller-owned."""

    def __init__(
        self,
        session: Session,
        *,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not isinstance(session, Session):
            raise AccountMutationTransactionError()
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._session = session
        self._database_clock = database_clock or _read_database_utc_now

    def start_rotation(
        self,
        *,
        rotation_uuid: str | UUID,
        tenant_uuid: str | UUID,
        database_uuid: str | UUID,
        account_kind: AccountKind,
        purpose: AccountRotationPurpose,
        previous: AccountGeneration,
        candidate: AccountGeneration,
        inherited_desired_login_state: AccountLoginState,
        expected_tenant_access_version: int,
        expected_route_version: int,
        expected_login_state_version: int,
        expected_row_version: int = 0,
    ) -> AccountRotationPersistenceResult:
        """Create a locked, unpublished rotation or return its exact replay."""

        self._prepare()
        rotation_id = _uuid(rotation_uuid)
        tenant_id = _uuid(tenant_uuid)
        selected_kind = _account_kind(account_kind)
        row = self._lock_rotation(rotation_id)
        lease_row = self._lock_required_lease(tenant_id, selected_kind)
        now = self._now()
        lease = _domain_lease(lease_row)
        current = None if row is None else _domain_rotation(row)
        reduced = _reduce_start(
            current=current,
            rotation_uuid=rotation_id,
            tenant_uuid=tenant_id,
            database_uuid=_uuid(database_uuid),
            account_kind=selected_kind,
            purpose=purpose,
            previous=previous,
            candidate=candidate,
            inherited_desired_login_state=inherited_desired_login_state,
            expected_tenant_access_version=expected_tenant_access_version,
            expected_route_version=expected_route_version,
            expected_login_state_version=expected_login_state_version,
            lease=lease,
            database_now=now,
        )
        if row is not None:
            if not reduced.idempotent_replay:
                raise AccountMutationPersistenceError()
            return _rotation_result(row, reduced, row_version=row.row_version)
        if expected_row_version != 0:
            raise AccountMutationFenceConflict(reduced.effects)

        candidate_row = _new_rotation_row(reduced.rotation, database_now=now)
        try:
            with self._session.begin_nested():
                self._session.add(candidate_row)
                self._session.flush()
            self._session.expire(candidate_row)
            return _rotation_result(candidate_row, reduced, row_version=1)
        except IntegrityError:
            self._session.expire_all()
            winner = self._lock_rotation(rotation_id)
            if winner is None:
                raise AccountMutationPersistenceError() from None
            winner_lease = self._lock_required_lease(tenant_id, selected_kind)
            winner_now = self._now()
            replay = _reduce_start(
                current=_domain_rotation(winner),
                rotation_uuid=rotation_id,
                tenant_uuid=tenant_id,
                database_uuid=_uuid(database_uuid),
                account_kind=selected_kind,
                purpose=purpose,
                previous=previous,
                candidate=candidate,
                inherited_desired_login_state=inherited_desired_login_state,
                expected_tenant_access_version=expected_tenant_access_version,
                expected_route_version=expected_route_version,
                expected_login_state_version=expected_login_state_version,
                lease=_domain_lease(winner_lease),
                database_now=winner_now,
            )
            if not replay.idempotent_replay:
                raise AccountMutationPersistenceError() from None
            return _rotation_result(
                winner,
                replay,
                row_version=winner.row_version,
            )

    def prepare_rotation(
        self,
        *,
        rotation_uuid: str | UUID,
        expected_row_version: int,
        proof: AccountCandidatePreparationProof,
    ) -> AccountRotationPersistenceResult:
        return self._mutate(
            rotation_uuid=rotation_uuid,
            expected_row_version=expected_row_version,
            reducer=lambda current, lease, now: _reduce_prepare(
                current,
                lease=lease,
                proof=proof,
                database_now=now,
            ),
        )

    def begin_candidate_testing(
        self,
        *,
        rotation_uuid: str | UUID,
        expected_row_version: int,
        proof: AccountUnlockAuthorityProof,
    ) -> AccountRotationPersistenceResult:
        return self._mutate(
            rotation_uuid=rotation_uuid,
            expected_row_version=expected_row_version,
            reducer=lambda current, lease, now: _reduce_begin_testing(
                current,
                lease=lease,
                proof=proof,
                database_now=now,
            ),
        )

    def verify_candidate(
        self,
        *,
        rotation_uuid: str | UUID,
        expected_row_version: int,
        proof: AccountUnlockAuthorityProof,
    ) -> AccountRotationPersistenceResult:
        return self._mutate(
            rotation_uuid=rotation_uuid,
            expected_row_version=expected_row_version,
            reducer=lambda current, lease, now: _reduce_verify(
                current,
                lease=lease,
                proof=proof,
                database_now=now,
            ),
        )

    def switch_candidate(
        self,
        *,
        rotation_uuid: str | UUID,
        expected_row_version: int,
        proof: AccountUnlockAuthorityProof,
    ) -> AccountRotationPersistenceResult:
        return self._mutate(
            rotation_uuid=rotation_uuid,
            expected_row_version=expected_row_version,
            reducer=lambda current, lease, now: _reduce_switch(
                current,
                lease=lease,
                proof=proof,
                database_now=now,
            ),
        )

    def begin_draining(
        self,
        *,
        rotation_uuid: str | UUID,
        expected_row_version: int,
    ) -> AccountRotationPersistenceResult:
        return self._mutate(
            rotation_uuid=rotation_uuid,
            expected_row_version=expected_row_version,
            reducer=lambda current, lease, now: _reduce_begin_draining(
                current,
                lease=lease,
                database_now=now,
            ),
        )

    def revoke_previous(
        self,
        *,
        rotation_uuid: str | UUID,
        expected_row_version: int,
        proof: AccountRevocationProof,
    ) -> AccountRotationPersistenceResult:
        return self._mutate(
            rotation_uuid=rotation_uuid,
            expected_row_version=expected_row_version,
            reducer=lambda current, lease, now: _reduce_revoke(
                current,
                lease=lease,
                proof=proof,
                database_now=now,
            ),
        )

    def fail_rotation(
        self,
        *,
        rotation_uuid: str | UUID,
        expected_row_version: int,
        safe_error_code: str,
    ) -> AccountRotationPersistenceResult:
        return self._mutate(
            rotation_uuid=rotation_uuid,
            expected_row_version=expected_row_version,
            reducer=lambda current, lease, now: _reduce_fail(
                current,
                lease=lease,
                safe_error_code=safe_error_code,
                database_now=now,
            ),
        )

    start = start_rotation
    prepare = prepare_rotation
    test_candidate = begin_candidate_testing
    verify = verify_candidate
    switch = switch_candidate
    drain = begin_draining
    revoke = revoke_previous
    fail = fail_rotation

    def _mutate(
        self,
        *,
        rotation_uuid: str | UUID,
        expected_row_version: int,
        reducer: _RotationFactory,
    ) -> AccountRotationPersistenceResult:
        self._prepare()
        rotation_id = _uuid(rotation_uuid)
        row = self._lock_rotation(rotation_id)
        if row is None:
            raise AccountMutationFenceConflict()
        before = _domain_rotation(row)
        lease_row = self._lock_required_lease(
            before.tenant_uuid,
            before.account_kind,
        )
        now = self._now()
        reduced = reducer(before, _domain_lease(lease_row), now)
        if reduced.idempotent_replay:
            return _rotation_result(row, reduced, row_version=row.row_version)
        if row.row_version != expected_row_version:
            raise AccountMutationFenceConflict(reduced.effects)
        _verify_rotation_transition(before, reduced.rotation)

        try:
            with self._session.begin_nested():
                changed = self._session.execute(
                    sa.update(TenantDatabaseAccountRotation)
                    .where(
                        TenantDatabaseAccountRotation.id == row.id,
                        TenantDatabaseAccountRotation.rotation_id
                        == str(before.rotation_uuid),
                        TenantDatabaseAccountRotation.row_version
                        == expected_row_version,
                        TenantDatabaseAccountRotation.transition_sequence
                        == before.transition_sequence,
                        TenantDatabaseAccountRotation.state
                        == before.state.value,
                        TenantDatabaseAccountRotation.last_action
                        == (
                            None
                            if before.last_action is None
                            else before.last_action.value
                        ),
                        TenantDatabaseAccountRotation.last_request_digest
                        == before.last_request_digest,
                    )
                    .values(
                        state=reduced.rotation.state.value,
                        candidate_locked=reduced.rotation.candidate_locked,
                        candidate_published=(
                            reduced.rotation.candidate_published
                        ),
                        previous_locked=reduced.rotation.previous_locked,
                        previous_revoked=reduced.rotation.previous_revoked,
                        transition_sequence=(
                            reduced.rotation.transition_sequence
                        ),
                        last_action=reduced.rotation.last_action.value,
                        last_request_digest=(
                            reduced.rotation.last_request_digest
                        ),
                        safe_error_code=reduced.rotation.safe_error_code,
                        row_version=expected_row_version + 1,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    raise AccountMutationFenceConflict(reduced.effects)
                self._session.flush()
        except IntegrityError:
            raise AccountMutationPersistenceError(reduced.effects) from None
        self._session.expire(row)
        return _rotation_result(
            row,
            reduced,
            row_version=expected_row_version + 1,
        )

    def _lock_rotation(
        self,
        rotation_uuid: UUID,
    ) -> TenantDatabaseAccountRotation | None:
        return self._session.scalar(
            sa.select(TenantDatabaseAccountRotation)
            .where(
                TenantDatabaseAccountRotation.rotation_id
                == str(rotation_uuid)
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )

    def _lock_required_lease(
        self,
        tenant_uuid: UUID,
        account_kind: AccountKind,
    ) -> TenantDatabaseAccountMutationLease:
        row = self._session.scalar(
            sa.select(TenantDatabaseAccountMutationLease)
            .where(
                TenantDatabaseAccountMutationLease.tenant_id
                == str(tenant_uuid),
                TenantDatabaseAccountMutationLease.account_kind
                == account_kind.value,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if row is None:
            raise AccountMutationFenceConflict()
        return row

    def _prepare(self) -> None:
        _prepare_session(self._session)

    def _now(self) -> datetime:
        return _as_utc(self._database_clock(self._session))


def _new_lease_row(
    lease: AccountMutationLease,
    *,
    database_now: datetime,
) -> TenantDatabaseAccountMutationLease:
    return TenantDatabaseAccountMutationLease(
        tenant_id=str(lease.tenant_uuid),
        account_kind=lease.account_kind.value,
        fencing_token=lease.fencing_token,
        lease_owner=lease.owner,
        lease_purpose=lease.purpose,
        lease_expires_at=lease.expires_at,
        row_version=lease.row_version,
        created_at=database_now,
        updated_at=database_now,
    )


def _new_rotation_row(
    rotation: AccountRotation,
    *,
    database_now: datetime,
) -> TenantDatabaseAccountRotation:
    if rotation.last_action is None or rotation.last_request_digest is None:
        raise AccountMutationPersistenceError()
    return TenantDatabaseAccountRotation(
        id=str(uuid4()),
        rotation_id=str(rotation.rotation_uuid),
        tenant_id=str(rotation.tenant_uuid),
        database_uuid=str(rotation.database_uuid),
        account_kind=rotation.account_kind.value,
        purpose=rotation.purpose.value,
        from_username=rotation.previous.username,
        from_credential_generation=rotation.previous.credential_generation,
        from_root_key_version=rotation.previous.root_key_version,
        from_derivation_version=rotation.previous.derivation_version,
        to_username=rotation.candidate.username,
        to_credential_generation=rotation.candidate.credential_generation,
        to_root_key_version=rotation.candidate.root_key_version,
        to_derivation_version=rotation.candidate.derivation_version,
        inherited_desired_login_state=(
            rotation.inherited_desired_login_state.value
        ),
        expected_tenant_access_version=(
            rotation.expected_tenant_access_version
        ),
        expected_route_version=rotation.expected_route_version,
        expected_login_state_version=rotation.expected_login_state_version,
        lease_owner=rotation.lease_owner,
        lease_purpose=rotation.lease_purpose,
        lease_fencing_token=rotation.lease_fencing_token,
        state=rotation.state.value,
        candidate_locked=rotation.candidate_locked,
        candidate_published=rotation.candidate_published,
        previous_locked=rotation.previous_locked,
        previous_revoked=rotation.previous_revoked,
        transition_sequence=rotation.transition_sequence,
        last_action=rotation.last_action.value,
        last_request_digest=rotation.last_request_digest,
        safe_error_code=rotation.safe_error_code,
        row_version=1,
        created_at=database_now,
        updated_at=database_now,
    )


def _domain_lease(
    row: TenantDatabaseAccountMutationLease,
) -> AccountMutationLease:
    try:
        return AccountMutationLease(
            tenant_uuid=UUID(row.tenant_id),
            account_kind=AccountKind(row.account_kind),
            fencing_token=row.fencing_token,
            owner=row.lease_owner,
            purpose=row.lease_purpose,
            expires_at=(
                None
                if row.lease_expires_at is None
                else _as_utc(row.lease_expires_at)
            ),
            row_version=row.row_version,
        )
    except (TypeError, ValueError):
        raise AccountMutationStoredStateError() from None


def _domain_rotation(
    row: TenantDatabaseAccountRotation,
) -> AccountRotation:
    try:
        return AccountRotation(
            rotation_uuid=UUID(row.rotation_id),
            tenant_uuid=UUID(row.tenant_id),
            database_uuid=UUID(row.database_uuid),
            account_kind=AccountKind(row.account_kind),
            purpose=AccountRotationPurpose(row.purpose),
            previous=AccountGeneration(
                username=row.from_username,
                credential_generation=row.from_credential_generation,
                root_key_version=row.from_root_key_version,
                derivation_version=row.from_derivation_version,
            ),
            candidate=AccountGeneration(
                username=row.to_username,
                credential_generation=row.to_credential_generation,
                root_key_version=row.to_root_key_version,
                derivation_version=row.to_derivation_version,
            ),
            inherited_desired_login_state=AccountLoginState(
                row.inherited_desired_login_state
            ),
            expected_tenant_access_version=(
                row.expected_tenant_access_version
            ),
            expected_route_version=row.expected_route_version,
            expected_login_state_version=row.expected_login_state_version,
            lease_owner=row.lease_owner,
            lease_purpose=row.lease_purpose,
            lease_fencing_token=row.lease_fencing_token,
            state=row.state,
            candidate_locked=row.candidate_locked,
            candidate_published=row.candidate_published,
            previous_locked=row.previous_locked,
            previous_revoked=row.previous_revoked,
            transition_sequence=row.transition_sequence,
            last_action=row.last_action,
            last_request_digest=bytes(row.last_request_digest),
            safe_error_code=row.safe_error_code,
        )
    except (TypeError, ValueError):
        raise AccountMutationStoredStateError() from None


def _verify_lease_transition(
    before: AccountMutationLease,
    after: AccountMutationLease,
) -> None:
    if (
        before.tenant_uuid != after.tenant_uuid
        or before.account_kind is not after.account_kind
        or after.row_version != before.row_version + 1
        or after.fencing_token < before.fencing_token
        or after.fencing_token > before.fencing_token + 1
    ):
        raise AccountMutationPersistenceError()


def _verify_rotation_transition(
    before: AccountRotation,
    after: AccountRotation,
) -> None:
    immutable_before = (
        before.rotation_uuid,
        before.tenant_uuid,
        before.database_uuid,
        before.account_kind,
        before.purpose,
        before.previous,
        before.candidate,
        before.inherited_desired_login_state,
        before.expected_tenant_access_version,
        before.expected_route_version,
        before.expected_login_state_version,
        before.lease_owner,
        before.lease_purpose,
        before.lease_fencing_token,
    )
    immutable_after = (
        after.rotation_uuid,
        after.tenant_uuid,
        after.database_uuid,
        after.account_kind,
        after.purpose,
        after.previous,
        after.candidate,
        after.inherited_desired_login_state,
        after.expected_tenant_access_version,
        after.expected_route_version,
        after.expected_login_state_version,
        after.lease_owner,
        after.lease_purpose,
        after.lease_fencing_token,
    )
    if (
        immutable_before != immutable_after
        or after.transition_sequence != before.transition_sequence + 1
    ):
        raise AccountMutationPersistenceError()


def _lease_result(
    transition: AccountLeaseTransition,
) -> AccountMutationLeasePersistenceResult:
    return AccountMutationLeasePersistenceResult(
        lease=transition.lease,
        effect=transition.effect,
        idempotent_replay=transition.idempotent_replay,
    )


def _rotation_result(
    row: TenantDatabaseAccountRotation,
    transition: AccountRotationTransition,
    *,
    row_version: int,
) -> AccountRotationPersistenceResult:
    return AccountRotationPersistenceResult(
        rotation_row_uuid=UUID(row.id),
        rotation=transition.rotation,
        row_version=row_version,
        effects=transition.effects,
        idempotent_replay=transition.idempotent_replay,
    )


def _prepare_session(session: Session) -> None:
    transaction = session.get_transaction()
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
    ):
        raise AccountMutationTransactionError()
    dirty = any(
        session.is_modified(instance, include_collections=True)
        for instance in session.dirty
    )
    if session.new or session.deleted or dirty:
        raise AccountMutationTransactionError()
    _materialize_sqlite_outer_transaction(session)


def _materialize_sqlite_outer_transaction(session: Session) -> None:
    connection = session.connection()
    if connection.dialect.name != "sqlite":
        return
    driver_connection = getattr(connection.connection, "driver_connection", None)
    if driver_connection is not None and not driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")


def _read_database_utc_now(session: Session) -> datetime:
    return _as_utc(read_database_utc_value(session))


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise AccountMutationPersistenceError()
    if value.tzinfo is None:
        # Control MySQL is UTC and SQLite drops timezone information in tests.
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


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


def _account_kind(value: AccountKind) -> AccountKind:
    try:
        return AccountKind(value)
    except (TypeError, ValueError):
        raise ValueError("account kind is unsupported") from None


__all__ = [
    "AccountMutationLeasePersistenceResult",
    "AccountMutationLeasePersistenceService",
    "AccountMutationPersistenceError",
    "AccountMutationStoredStateError",
    "AccountMutationTransactionError",
    "AccountRotationPersistenceResult",
    "AccountRotationPersistenceService",
]
