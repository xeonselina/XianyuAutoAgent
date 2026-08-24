"""Caller-transactional persistence for the fenced registration workflow.

No method commits, rolls back, creates a tenant schema, or calls a provider.
The authority callback is the future 0011 integration point: it must perform a
locking current-read of the current host-recovery run and released hold before
returning.  This module then keeps the D54 lock order for every competing
registration mutation.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable, Protocol
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inventory_control.models.foundation import (
    DatabaseIdentityControlRecord,
    Tenant,
    TenantDatabase,
)
from inventory_control.models.identity import TenantMembership, User
from inventory_control.models.invitations import TenantInvitation
from inventory_control.models.redemption import RedemptionCode
from inventory_control.transactions import require_caller_transaction
from inventory_control.models.registration import (
    RedemptionCodeReplacement,
    RegistrationIntegrityIncident,
    TenantRegistrationAttempt,
    TenantRegistrationCommit,
    TenantRegistrationProvisioningProof,
)
from inventory_control.models.recovery import TenantRecoveryHold
from inventory_control.models.schema_operations import (
    PlatformSchemaOperationLease,
)
from inventory_control.models.sms import SmsChallenge
from inventory_control.models.subscriptions import (
    PlanRevision,
    Subscription,
    SubscriptionEvent,
)
from inventory_control.subscriptions.entitlements import (
    InvalidEntitlementSnapshotError,
    parse_core_entitlements,
)

from .types import REGISTRATION_LOCK_ORDER


REGISTRATION_RESERVATION_REVISION = "registration.reserve.v1"
REGISTRATION_RETRY_REVISION = "registration.retry.v1"
REGISTRATION_FINALIZATION_VERSION = 1
REGISTRATION_INTEGRITY_POLICY_VERSION = 1
REGISTRATION_PROVISIONING_PROOF_POLICY_VERSION = 1
REGISTRATION_PERSISTENCE_LOCK_ORDER = REGISTRATION_LOCK_ORDER

_CANONICAL_PHONE = re.compile(r"\+861[0-9]{10}", re.ASCII)
_SAFE_TOKEN = re.compile(r"[A-Za-z0-9._:/+-]{1,128}", re.ASCII)
_SAFE_ERROR_CODE = re.compile(r"[a-z0-9_.:-]{1,64}", re.ASCII)
_SLUG = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", re.ASCII)
_WORKER_TOKEN_DIGEST_DOMAIN = (
    b"inventory-manager/registration-worker-lease-token/v1\x00"
)
_SCHEMA_OPERATION_LEASE_KEY = "fleet_schema_operation"


class RegistrationPersistenceError(RuntimeError):
    code = "REGISTRATION_REJECTED"
    public_message = "registration could not be completed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class RegistrationTransactionError(RegistrationPersistenceError):
    code = "REGISTRATION_TRANSACTION_INVALID"


class RegistrationOtpError(RegistrationPersistenceError):
    code = "REGISTRATION_OTP_REJECTED"


class RegistrationCodeError(RegistrationPersistenceError):
    code = "REGISTRATION_CODE_REJECTED"


class RegistrationFenceError(RegistrationPersistenceError):
    code = "REGISTRATION_FENCE_LOST"


class RegistrationAuthorityError(RegistrationPersistenceError):
    code = "REGISTRATION_AUTHORITY_DENIED"


class RegistrationConflictError(RegistrationPersistenceError):
    code = "REGISTRATION_CONFLICT"


@dataclass(frozen=True, slots=True)
class RegistrationAuthorityFacts:
    """Facts returned only after locking the authoritative recovery rows."""

    current_recovery_run_uuid: UUID
    recovery_run_completed: bool
    external_marker_matches: bool
    marker_generation: int
    released_hold_uuid: UUID | None
    released_hold_revision: int | None
    released_hold_ready: bool

    def __post_init__(self) -> None:
        _uuid(self.current_recovery_run_uuid, "current_recovery_run_uuid")
        if self.released_hold_uuid is not None:
            _uuid(self.released_hold_uuid, "released_hold_uuid")
        _positive(self.marker_generation, "marker_generation")
        if self.released_hold_revision is not None:
            _positive(self.released_hold_revision, "released_hold_revision")
        if self.released_hold_ready and (
            self.released_hold_uuid is None or self.released_hold_revision is None
        ):
            raise ValueError("released hold readiness requires its anchors")
        for value, name in (
            (self.recovery_run_completed, "recovery_run_completed"),
            (self.external_marker_matches, "external_marker_matches"),
            (self.released_hold_ready, "released_hold_ready"),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"{name} must be a bool")


class RegistrationAuthorityCurrentRead(Protocol):
    """Lock current recovery-run/hold rows and return their current facts."""

    def __call__(
        self,
        session: Session,
        *,
        tenant_uuid: UUID,
        expected_recovery_run_uuid: UUID,
        database_now: datetime,
    ) -> RegistrationAuthorityFacts:
        ...


class RegistrationReleasedHoldBaselineWrite(Protocol):
    """Create/idempotently read a new tenant's released baseline hold."""

    def __call__(
        self,
        session: Session,
        *,
        tenant: Tenant,
        database_uuid: UUID,
        registration_commit_uuid: UUID,
        expected_recovery_run_uuid: UUID,
        expected_dml_login_state_version: int,
        database_now: datetime,
    ) -> RegistrationAuthorityFacts:
        ...


class RegistrationFinalFenceCurrentRead(Protocol):
    """Revalidate the publication fence inside this exact control transaction."""

    def __call__(self, *, control_transaction: Session) -> None:
        ...


DatabaseClock = Callable[[Session], datetime]


@dataclass(frozen=True, slots=True)
class RegistrationSchemaOperationFence:
    """Expected live identity of the fleet schema-operation singleton."""

    claim_uuid: UUID
    owner_id: str
    generation: int
    fencing_token: int
    row_version: int

    def __post_init__(self) -> None:
        _uuid(self.claim_uuid, "claim_uuid")
        _token(self.owner_id, "owner_id")
        _positive(self.generation, "generation")
        _positive(self.fencing_token, "fencing_token")
        _positive(self.row_version, "row_version")


@dataclass(frozen=True, slots=True)
class ProvisionedRegistrationFacts:
    """Immutable evidence produced outside this service without provider I/O."""

    tenant_uuid: UUID
    database_uuid: UUID
    provisioning_generation: int
    lease_owner: str
    lease_token: str
    schema_generation: int
    schema_digest: bytes
    database_identity_digest: bytes
    route_version: int
    initial_credential_generation: int
    dml_login_state_version: int
    default_warehouse_uuid: UUID
    default_warehouse_digest: bytes
    smoke_proof_digest: bytes
    advisory_lock_proof_digest: bytes
    backup_ddl_lease_held: bool
    database_advisory_lock_held: bool
    smoke_passed: bool
    business_route_unpublished: bool

    def __post_init__(self) -> None:
        _uuid(self.tenant_uuid, "tenant_uuid")
        _uuid(self.database_uuid, "database_uuid")
        _positive(self.provisioning_generation, "provisioning_generation")
        _token(self.lease_owner, "lease_owner")
        _token(self.lease_token, "lease_token")
        _positive(self.schema_generation, "schema_generation")
        _digest(self.schema_digest, "schema_digest")
        _digest(self.database_identity_digest, "database_identity_digest")
        _positive(self.route_version, "route_version")
        _positive(
            self.initial_credential_generation,
            "initial_credential_generation",
        )
        _positive(self.dml_login_state_version, "dml_login_state_version")
        _uuid(self.default_warehouse_uuid, "default_warehouse_uuid")
        _digest(self.default_warehouse_digest, "default_warehouse_digest")
        _digest(self.smoke_proof_digest, "smoke_proof_digest")
        _digest(
            self.advisory_lock_proof_digest,
            "advisory_lock_proof_digest",
        )
        for value, name in (
            (self.backup_ddl_lease_held, "backup_ddl_lease_held"),
            (self.database_advisory_lock_held, "database_advisory_lock_held"),
            (self.smoke_passed, "smoke_passed"),
            (self.business_route_unpublished, "business_route_unpublished"),
        ):
            if not isinstance(value, bool):
                raise TypeError(f"{name} must be a bool")

    @property
    def verified(self) -> bool:
        return bool(
            self.backup_ddl_lease_held
            and self.database_advisory_lock_held
            and self.smoke_passed
            and self.business_route_unpublished
        )


class RegistrationProvisioningCurrentRead(Protocol):
    """Read immutable tenant provisioning facts in the caller transaction.

    Implementations may inspect the tenant database only through the already
    fenced provisioning/advisory-lock context.  They must use the supplied
    Session for control reads and must not commit, roll back, or stage writes.
    """

    def __call__(
        self,
        session: Session,
        *,
        tenant_uuid: UUID,
        database_uuid: UUID,
        provisioning_generation: int,
        worker_lease_owner: str,
        worker_lease_token: str,
        schema_operation_fence: RegistrationSchemaOperationFence,
        database_now: datetime,
    ) -> ProvisionedRegistrationFacts:
        ...


@dataclass(frozen=True, slots=True)
class RegistrationFinalCommitPlan:
    registration_commit_uuid: UUID
    membership_uuid: UUID
    subscription_uuid: UUID
    subscription_event_uuid: UUID
    published_tenant_name: str
    published_slug: str
    idempotency_key: str
    commit_policy_version: int = REGISTRATION_FINALIZATION_VERSION

    def __post_init__(self) -> None:
        identities = (
            self.registration_commit_uuid,
            self.membership_uuid,
            self.subscription_uuid,
            self.subscription_event_uuid,
        )
        for value in identities:
            _uuid(value, "registration finalization UUID")
        if len(set(identities)) != len(identities):
            raise ValueError("registration finalization UUIDs must be distinct")
        _tenant_name(self.published_tenant_name)
        _slug(self.published_slug)
        _idempotency_key(self.idempotency_key)
        _positive(self.commit_policy_version, "commit_policy_version")


@dataclass(frozen=True, slots=True)
class RegistrationReservationResult:
    attempt_uuid: UUID
    user_uuid: UUID
    code_uuid: UUID
    tenant_uuid: UUID
    database_uuid: UUID
    status: str
    provisioning_generation: int
    row_version: int
    created: bool


@dataclass(frozen=True, slots=True)
class RegistrationRetryResult:
    attempt_uuid: UUID
    status: str
    provisioning_generation: int
    row_version: int
    created: bool


@dataclass(frozen=True, slots=True)
class RegistrationProvisioningClaimResult:
    attempt_uuid: UUID
    status: str
    provisioning_generation: int
    row_version: int
    created: bool


@dataclass(frozen=True, slots=True)
class RegistrationDatabaseReadyResult:
    attempt_uuid: UUID
    proof_uuid: UUID
    status: str
    provisioning_generation: int
    row_version: int
    created: bool


@dataclass(frozen=True, slots=True)
class RegistrationProvisioningFailureResult:
    attempt_uuid: UUID
    proof_uuid: UUID
    status: str
    provisioning_generation: int
    row_version: int
    created: bool


@dataclass(frozen=True, slots=True)
class RegistrationFinalizationResult:
    attempt_uuid: UUID
    status: str
    registration_commit_uuid: UUID | None
    membership_uuid: UUID | None
    subscription_uuid: UUID | None
    subscription_event_uuid: UUID | None
    resulting_attempt_row_version: int
    created: bool
    integrity_incident_uuid: UUID | None = None


class RegistrationPersistenceService:
    """Coordinate registration mutations inside one clean caller transaction."""

    def __init__(
        self,
        *,
        authority_current_read: RegistrationAuthorityCurrentRead,
        released_hold_baseline_write: (
            RegistrationReleasedHoldBaselineWrite | None
        ) = None,
        provisioning_current_read: RegistrationProvisioningCurrentRead | None = None,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not callable(authority_current_read):
            raise TypeError("authority_current_read must be callable")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        if released_hold_baseline_write is not None and not callable(
            released_hold_baseline_write
        ):
            raise TypeError("released_hold_baseline_write must be callable")
        if provisioning_current_read is not None and not callable(
            provisioning_current_read
        ):
            raise TypeError("provisioning_current_read must be callable")
        self._authority_current_read = authority_current_read
        self._released_hold_baseline_write = released_hold_baseline_write
        self._provisioning_current_read = provisioning_current_read
        self._database_clock = database_clock or _read_database_utc_now

    def reserve_after_verified_otp(
        self,
        session: Session,
        *,
        challenge_uuid: str | UUID,
        user_uuid: str | UUID,
        code_lookup_hash: bytes,
        attempt_uuid: str | UUID,
        provisional_tenant_uuid: str | UUID,
        provisional_database_uuid: str | UUID,
        requested_tenant_name: str,
        idempotency_key: str,
        expected_code_row_version: int,
        current_recovery_run_uuid: str | UUID,
    ) -> RegistrationReservationResult:
        self._prepare(session)
        challenge_id = str(_uuid(challenge_uuid, "challenge_uuid"))
        user_id = str(_uuid(user_uuid, "user_uuid"))
        attempt_id = str(_uuid(attempt_uuid, "attempt_uuid"))
        tenant_id = str(_uuid(provisional_tenant_uuid, "provisional_tenant_uuid"))
        database_id = str(_uuid(provisional_database_uuid, "provisional_database_uuid"))
        run_uuid = _uuid(
            current_recovery_run_uuid,
            "current_recovery_run_uuid",
        )
        lookup_hash = _lookup_hash(code_lookup_hash)
        name = _tenant_name(requested_tenant_name)
        key = _idempotency_key(idempotency_key)
        code_revision = _positive(
            expected_code_row_version,
            "expected_code_row_version",
        )
        request_digest = reservation_action_digest(
            user_uuid=user_id,
            code_lookup_hash=lookup_hash,
            attempt_uuid=attempt_id,
            provisional_tenant_uuid=tenant_id,
            provisional_database_uuid=database_id,
            requested_tenant_name=name,
            idempotency_key=key,
            expected_code_row_version=code_revision,
            current_recovery_run_uuid=str(run_uuid),
        )

        code_id = session.scalar(
            sa.select(RedemptionCode.id).where(
                RedemptionCode.lookup_hash == lookup_hash
            )
        )
        if code_id is None:
            raise RegistrationCodeError()

        user = self._lock_user(session, user_id)
        blocking_memberships = self._lock_user_memberships(session, user.id)
        challenge = self._lock_challenge(session, challenge_id)
        self._lock_phone_invitations(session, user.phone_e164)
        tenant = session.scalar(
            sa.select(Tenant).where(Tenant.id == tenant_id).with_for_update()
        )
        # The authority callback owns the run/hold locks in the required
        # tenant-first prefix.  Its timestamp is observational only; all OTP,
        # code, and lease decisions below use a fresh database timestamp after
        # every authoritative row in this mutation has been locked.
        authority_observed_at = self._now(session)
        authority = self._read_authority(
            session,
            tenant_uuid=UUID(tenant_id),
            expected_run_uuid=run_uuid,
            database_now=authority_observed_at,
            require_released_hold=False,
        )
        attempts = self._lock_attempt_candidates(
            session,
            attempt_id=attempt_id,
            code_id=code_id,
            idempotency_key=key,
        )
        code = session.scalar(
            sa.select(RedemptionCode)
            .where(RedemptionCode.id == code_id)
            .with_for_update()
        )
        if code is None:  # pragma: no cover - deleted rows are restricted
            raise RegistrationCodeError()
        now = self._now(session)

        self._require_register_challenge(
            challenge,
            user=user,
            expected_digest=request_digest,
            expected_revision=REGISTRATION_RESERVATION_REVISION,
            database_now=now,
        )
        if len(attempts) > 1:
            raise RegistrationConflictError()
        if attempts:
            return self._reservation_replay(
                attempts[0],
                code=code,
                user=user,
                tenant_uuid=tenant_id,
                database_uuid=database_id,
                requested_name=name,
                idempotency_key=key,
                request_digest=request_digest,
            )

        self._require_user_available(user, blocking_memberships)
        if tenant is not None:
            raise RegistrationConflictError()
        self._require_active_code(
            code,
            current_run_uuid=run_uuid,
            expected_row_version=code_revision,
            database_now=now,
        )

        tenant = Tenant(
            id=tenant_id,
            name=None,
            slug=None,
            public_identity_published_at=None,
            status="provisioning",
            access_version=1,
            row_version=1,
            created_at=now,
            updated_at=now,
        )
        attempt = TenantRegistrationAttempt(
            id=attempt_id,
            user_id=user.id,
            redemption_code_id=code.id,
            requested_tenant_name=name,
            provisional_tenant_uuid=tenant_id,
            provisional_database_uuid=database_id,
            status="reserved",
            idempotency_key=key,
            request_digest=request_digest,
            provisioning_execution_generation=1,
            attempt_count=0,
            recovery_run_uuid=str(authority.current_recovery_run_uuid),
            row_version=1,
            created_at=now,
            updated_at=now,
        )
        try:
            with session.begin_nested():
                session.add_all((tenant, attempt))
                changed = session.execute(
                    sa.update(RedemptionCode)
                    .where(
                        RedemptionCode.id == code.id,
                        RedemptionCode.status == "active",
                        RedemptionCode.row_version == code_revision,
                        RedemptionCode.created_under_recovery_run_uuid == str(run_uuid),
                        RedemptionCode.reserved_user_uuid.is_(None),
                        RedemptionCode.reserved_registration_attempt_uuid.is_(None),
                    )
                    .values(
                        status="reserved",
                        reserved_user_uuid=user.id,
                        reserved_registration_attempt_uuid=attempt_id,
                        row_version=code_revision + 1,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    raise RegistrationFenceError()
                session.flush()
        except IntegrityError:
            raise RegistrationConflictError() from None
        session.expire(code)
        return _reservation_result(attempt, created=True)

    def claim_provisioning_worker(
        self,
        session: Session,
        *,
        attempt_uuid: str | UUID,
        expected_attempt_row_version: int,
        expected_provisioning_generation: int,
        expected_code_row_version: int,
        lease_owner: str,
        lease_token: str,
        lease_expires_at: datetime,
        current_recovery_run_uuid: str | UUID,
    ) -> RegistrationProvisioningClaimResult:
        """Claim reserved work or take over an expired same-generation lease."""

        self._prepare(session)
        attempt_id = str(_uuid(attempt_uuid, "attempt_uuid"))
        attempt_revision = _positive(
            expected_attempt_row_version,
            "expected_attempt_row_version",
        )
        generation = _positive(
            expected_provisioning_generation,
            "expected_provisioning_generation",
        )
        code_revision = _positive(
            expected_code_row_version,
            "expected_code_row_version",
        )
        owner = _token(lease_owner, "lease_owner")
        token = _token(lease_token, "lease_token")
        expires_at = _as_database_utc(lease_expires_at)
        run_uuid = _uuid(
            current_recovery_run_uuid,
            "current_recovery_run_uuid",
        )

        summary = session.get(TenantRegistrationAttempt, attempt_id)
        if summary is None:
            raise RegistrationConflictError()
        user = self._lock_user(session, summary.user_id)
        self._lock_phone_invitations(session, user.phone_e164)
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == summary.provisional_tenant_uuid)
            .with_for_update()
        )
        if tenant is None:
            raise RegistrationConflictError()
        authority_observed_at = self._now(session)
        authority = self._read_authority(
            session,
            tenant_uuid=UUID(tenant.id),
            expected_run_uuid=run_uuid,
            database_now=authority_observed_at,
            require_released_hold=False,
        )
        self._lock_route_if_present(
            session,
            tenant_id=tenant.id,
            database_uuid=summary.provisional_database_uuid,
        )
        attempt = self._lock_attempt(session, attempt_id)
        proofs = self._lock_provisioning_proofs(
            session,
            attempt_uuid=attempt.id,
            provisioning_generation=generation,
        )
        replacement = self._lock_replacement(session, attempt.id)
        code = self._lock_registration_code(
            session,
            attempt.redemption_code_id,
        )
        blocking_memberships = self._lock_user_memberships(session, user.id)
        now = self._now(session)

        self._require_mutation_identity(
            attempt=attempt,
            user=user,
            tenant=tenant,
            authority=authority,
            current_run_uuid=run_uuid,
        )
        self._require_user_available(user, blocking_memberships)
        if replacement is not None:
            raise RegistrationFenceError()
        self._require_reserved_code(
            code,
            attempt=attempt,
            user=user,
            current_run_uuid=run_uuid,
            expected_row_version=code_revision,
        )
        if expires_at <= now:
            raise RegistrationFenceError()

        if (
            attempt.status in {"provisioning", "ready"}
            and attempt.row_version == attempt_revision + 1
            and attempt.provisioning_execution_generation == generation
            and attempt.lease_owner == owner
            and attempt.lease_token is not None
            and hmac.compare_digest(attempt.lease_token, token)
            and _as_database_utc(attempt.lease_expires_at) == expires_at
            and expires_at > now
        ):
            return _provisioning_claim_result(attempt, created=False)

        if (
            attempt.row_version != attempt_revision
            or attempt.provisioning_execution_generation != generation
            or attempt.status not in {"reserved", "provisioning", "ready"}
        ):
            raise RegistrationFenceError()

        previous_owner = attempt.lease_owner
        previous_token = attempt.lease_token
        previous_expiry = attempt.lease_expires_at
        if attempt.status == "reserved":
            if any(
                value is not None
                for value in (previous_owner, previous_token, previous_expiry)
            ):
                raise RegistrationFenceError()
        else:
            if (
                previous_owner is None
                or previous_token is None
                or previous_expiry is None
                or _as_database_utc(previous_expiry) > now
                or hmac.compare_digest(previous_token, token)
            ):
                raise RegistrationFenceError()
            if attempt.status == "ready" and not any(
                proof.outcome == "ready"
                and proof.worker_lease_owner == previous_owner
                and hmac.compare_digest(
                    bytes(proof.worker_lease_token_digest),
                    _worker_token_digest(previous_token),
                )
                for proof in proofs
            ):
                raise RegistrationFenceError()

        conditions = [
            TenantRegistrationAttempt.id == attempt.id,
            TenantRegistrationAttempt.row_version == attempt_revision,
            TenantRegistrationAttempt.provisioning_execution_generation == generation,
            TenantRegistrationAttempt.status == attempt.status,
        ]
        for column, previous in (
            (TenantRegistrationAttempt.lease_owner, previous_owner),
            (TenantRegistrationAttempt.lease_token, previous_token),
            (TenantRegistrationAttempt.lease_expires_at, previous_expiry),
        ):
            conditions.append(
                column.is_(None) if previous is None else column == previous
            )
        changed = session.execute(
            sa.update(TenantRegistrationAttempt)
            .where(*conditions)
            .values(
                status="provisioning",
                lease_owner=owner,
                lease_token=token,
                lease_expires_at=expires_at,
                attempt_count=attempt.attempt_count + 1,
                last_safe_error_code=None,
                row_version=attempt_revision + 1,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise RegistrationFenceError()
        session.expire(attempt)
        session.flush()
        return _provisioning_claim_result(attempt, created=True)

    def record_database_ready(
        self,
        session: Session,
        *,
        attempt_uuid: str | UUID,
        expected_attempt_row_version: int,
        expected_provisioning_generation: int,
        expected_code_row_version: int,
        current_recovery_run_uuid: str | UUID,
        schema_operation_fence: RegistrationSchemaOperationFence,
        provisioned: ProvisionedRegistrationFacts,
    ) -> RegistrationDatabaseReadyResult:
        """Persist trusted physical readiness behind both worker fences."""

        self._prepare(session)
        if not isinstance(
            schema_operation_fence,
            RegistrationSchemaOperationFence,
        ):
            raise TypeError("schema_operation_fence is invalid")
        if not isinstance(provisioned, ProvisionedRegistrationFacts):
            raise TypeError("provisioned facts are invalid")
        if not provisioned.verified:
            raise RegistrationFenceError()
        attempt_id = str(_uuid(attempt_uuid, "attempt_uuid"))
        attempt_revision = _positive(
            expected_attempt_row_version,
            "expected_attempt_row_version",
        )
        generation = _positive(
            expected_provisioning_generation,
            "expected_provisioning_generation",
        )
        code_revision = _positive(
            expected_code_row_version,
            "expected_code_row_version",
        )
        run_uuid = _uuid(
            current_recovery_run_uuid,
            "current_recovery_run_uuid",
        )
        request_digest = _database_ready_request_digest(
            attempt_uuid=attempt_id,
            expected_attempt_row_version=attempt_revision,
            expected_provisioning_generation=generation,
            expected_code_row_version=code_revision,
            current_recovery_run_uuid=run_uuid,
            schema_operation_fence=schema_operation_fence,
            provisioned=provisioned,
        )

        summary = session.get(TenantRegistrationAttempt, attempt_id)
        if summary is None:
            raise RegistrationConflictError()
        user = self._lock_user(session, summary.user_id)
        self._lock_phone_invitations(session, user.phone_e164)
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == summary.provisional_tenant_uuid)
            .with_for_update()
        )
        if tenant is None:
            raise RegistrationConflictError()
        authority_observed_at = self._now(session)
        authority = self._read_authority(
            session,
            tenant_uuid=UUID(tenant.id),
            expected_run_uuid=run_uuid,
            database_now=authority_observed_at,
            require_released_hold=False,
        )
        route, identity = self._lock_route_and_identity(
            session,
            tenant_id=tenant.id,
            database_uuid=summary.provisional_database_uuid,
        )
        attempt = self._lock_attempt(session, attempt_id)
        proofs = self._lock_provisioning_proofs(
            session,
            attempt_uuid=attempt.id,
            provisioning_generation=generation,
        )
        replacement = self._lock_replacement(session, attempt.id)
        code = self._lock_registration_code(
            session,
            attempt.redemption_code_id,
        )
        blocking_memberships = self._lock_user_memberships(session, user.id)
        schema_lease = self._lock_schema_operation_lease(session)
        locked_at = self._now(session)

        self._require_mutation_identity(
            attempt=attempt,
            user=user,
            tenant=tenant,
            authority=authority,
            current_run_uuid=run_uuid,
        )
        self._require_user_available(user, blocking_memberships)
        if replacement is not None:
            raise RegistrationFenceError()
        self._require_reserved_code(
            code,
            attempt=attempt,
            user=user,
            current_run_uuid=run_uuid,
            expected_row_version=code_revision,
        )
        proof = _matching_worker_proof(
            proofs,
            worker_lease_owner=provisioned.lease_owner,
            worker_lease_token=provisioned.lease_token,
        )
        if proof is not None:
            if (
                attempt.status != "ready"
                or attempt.row_version != attempt_revision + 1
                or attempt.provisioning_execution_generation != generation
                or attempt.lease_owner != provisioned.lease_owner
                or attempt.lease_token is None
                or not hmac.compare_digest(
                    attempt.lease_token,
                    provisioned.lease_token,
                )
                or proof.outcome != "ready"
                or proof.expected_attempt_row_version != attempt_revision
                or not hmac.compare_digest(
                    bytes(proof.result_request_digest),
                    request_digest,
                )
            ):
                raise RegistrationConflictError()
            self._require_proof_matches_expected(proof, provisioned)
            return _database_ready_result(
                attempt,
                proof,
                created=False,
            )

        if (
            attempt.status != "provisioning"
            or attempt.row_version != attempt_revision
            or attempt.provisioning_execution_generation != generation
        ):
            raise RegistrationFenceError()
        self._require_current_worker(
            attempt,
            owner=provisioned.lease_owner,
            token=provisioned.lease_token,
            generation=generation,
            database_now=locked_at,
        )
        self._require_live_schema_operation_fence(
            schema_lease,
            expected=schema_operation_fence,
            database_now=locked_at,
        )
        observed = self._read_provisioned_facts(
            session,
            tenant_uuid=UUID(tenant.id),
            database_uuid=UUID(route.database_uuid),
            provisioning_generation=generation,
            worker_lease_owner=provisioned.lease_owner,
            worker_lease_token=provisioned.lease_token,
            schema_operation_fence=schema_operation_fence,
            database_now=locked_at,
        )
        now = self._now(session)
        self._require_current_worker(
            attempt,
            owner=provisioned.lease_owner,
            token=provisioned.lease_token,
            generation=generation,
            database_now=now,
        )
        self._require_live_schema_operation_fence(
            schema_lease,
            expected=schema_operation_fence,
            database_now=now,
        )
        if not hmac.compare_digest(
            _provisioned_facts_digest(observed),
            _provisioned_facts_digest(provisioned),
        ):
            raise RegistrationFenceError()
        self._require_provisioned_facts(
            attempt=attempt,
            tenant=tenant,
            route=route,
            identity=identity,
            provisioned=observed,
        )

        proof = TenantRegistrationProvisioningProof(
            id=str(uuid4()),
            attempt_uuid=attempt.id,
            user_uuid=user.id,
            tenant_uuid=tenant.id,
            database_uuid=route.database_uuid,
            recovery_run_uuid=str(authority.current_recovery_run_uuid),
            provisioning_execution_generation=generation,
            expected_attempt_row_version=attempt_revision,
            worker_lease_owner=provisioned.lease_owner,
            worker_lease_token_digest=_worker_token_digest(provisioned.lease_token),
            worker_lease_expires_at=_as_database_utc(attempt.lease_expires_at),
            outcome="ready",
            safe_error_code=None,
            result_request_digest=request_digest,
            schema_operation_claim_uuid=str(schema_operation_fence.claim_uuid),
            schema_operation_owner_id=schema_operation_fence.owner_id,
            schema_operation_generation=schema_operation_fence.generation,
            schema_operation_fencing_token=(schema_operation_fence.fencing_token),
            schema_operation_row_version=schema_operation_fence.row_version,
            schema_generation=observed.schema_generation,
            schema_digest=observed.schema_digest,
            database_identity_digest=observed.database_identity_digest,
            route_version=observed.route_version,
            initial_credential_generation=(observed.initial_credential_generation),
            dml_login_state_version=observed.dml_login_state_version,
            default_warehouse_uuid=str(observed.default_warehouse_uuid),
            default_warehouse_digest=observed.default_warehouse_digest,
            smoke_proof_digest=observed.smoke_proof_digest,
            advisory_lock_proof_digest=observed.advisory_lock_proof_digest,
            proof_policy_version=REGISTRATION_PROVISIONING_PROOF_POLICY_VERSION,
            recorded_at=now,
        )
        try:
            with session.begin_nested():
                session.add(proof)
                changed = session.execute(
                    sa.update(TenantRegistrationAttempt)
                    .where(
                        TenantRegistrationAttempt.id == attempt.id,
                        TenantRegistrationAttempt.status == "provisioning",
                        TenantRegistrationAttempt.row_version == attempt_revision,
                        TenantRegistrationAttempt.provisioning_execution_generation
                        == generation,
                        TenantRegistrationAttempt.lease_owner
                        == provisioned.lease_owner,
                        TenantRegistrationAttempt.lease_token
                        == provisioned.lease_token,
                    )
                    .values(
                        status="ready",
                        row_version=attempt_revision + 1,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    raise RegistrationFenceError()
                session.flush()
        except IntegrityError:
            raise RegistrationConflictError() from None
        session.expire(attempt)
        return _database_ready_result(attempt, proof, created=True)

    def record_provisioning_failure(
        self,
        session: Session,
        *,
        attempt_uuid: str | UUID,
        expected_attempt_row_version: int,
        expected_provisioning_generation: int,
        expected_code_row_version: int,
        lease_owner: str,
        lease_token: str,
        safe_error_code: str,
        current_recovery_run_uuid: str | UUID,
    ) -> RegistrationProvisioningFailureResult:
        """Record one safe failure while preserving the code reservation."""

        self._prepare(session)
        attempt_id = str(_uuid(attempt_uuid, "attempt_uuid"))
        attempt_revision = _positive(
            expected_attempt_row_version,
            "expected_attempt_row_version",
        )
        generation = _positive(
            expected_provisioning_generation,
            "expected_provisioning_generation",
        )
        code_revision = _positive(
            expected_code_row_version,
            "expected_code_row_version",
        )
        owner = _token(lease_owner, "lease_owner")
        token = _token(lease_token, "lease_token")
        reason = _safe_error_code(safe_error_code)
        run_uuid = _uuid(
            current_recovery_run_uuid,
            "current_recovery_run_uuid",
        )
        request_digest = _provisioning_failure_request_digest(
            attempt_uuid=attempt_id,
            expected_attempt_row_version=attempt_revision,
            expected_provisioning_generation=generation,
            expected_code_row_version=code_revision,
            lease_owner=owner,
            lease_token=token,
            safe_error_code=reason,
            current_recovery_run_uuid=run_uuid,
        )

        summary = session.get(TenantRegistrationAttempt, attempt_id)
        if summary is None:
            raise RegistrationConflictError()
        user = self._lock_user(session, summary.user_id)
        self._lock_phone_invitations(session, user.phone_e164)
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == summary.provisional_tenant_uuid)
            .with_for_update()
        )
        if tenant is None:
            raise RegistrationConflictError()
        authority_observed_at = self._now(session)
        authority = self._read_authority(
            session,
            tenant_uuid=UUID(tenant.id),
            expected_run_uuid=run_uuid,
            database_now=authority_observed_at,
            require_released_hold=False,
        )
        self._lock_route_if_present(
            session,
            tenant_id=tenant.id,
            database_uuid=summary.provisional_database_uuid,
        )
        attempt = self._lock_attempt(session, attempt_id)
        proofs = self._lock_provisioning_proofs(
            session,
            attempt_uuid=attempt.id,
            provisioning_generation=generation,
        )
        replacement = self._lock_replacement(session, attempt.id)
        code = self._lock_registration_code(
            session,
            attempt.redemption_code_id,
        )
        blocking_memberships = self._lock_user_memberships(session, user.id)
        now = self._now(session)

        self._require_mutation_identity(
            attempt=attempt,
            user=user,
            tenant=tenant,
            authority=authority,
            current_run_uuid=run_uuid,
        )
        self._require_user_available(user, blocking_memberships)
        if replacement is not None:
            raise RegistrationFenceError()
        self._require_reserved_code(
            code,
            attempt=attempt,
            user=user,
            current_run_uuid=run_uuid,
            expected_row_version=code_revision,
        )
        proof = _matching_worker_proof(
            proofs,
            worker_lease_owner=owner,
            worker_lease_token=token,
        )
        if proof is not None:
            if (
                proof.outcome != "failed"
                or proof.expected_attempt_row_version != attempt_revision
                or not hmac.compare_digest(
                    bytes(proof.result_request_digest),
                    request_digest,
                )
                or attempt.status != "failed"
                or attempt.row_version != attempt_revision + 1
                or attempt.provisioning_execution_generation != generation
                or attempt.last_safe_error_code != reason
                or any(
                    value is not None
                    for value in (
                        attempt.lease_owner,
                        attempt.lease_token,
                        attempt.lease_expires_at,
                    )
                )
            ):
                raise RegistrationConflictError()
            return _provisioning_failure_result(
                attempt,
                proof,
                created=False,
            )

        if (
            attempt.status != "provisioning"
            or attempt.row_version != attempt_revision
            or attempt.provisioning_execution_generation != generation
        ):
            raise RegistrationFenceError()
        self._require_current_worker(
            attempt,
            owner=owner,
            token=token,
            generation=generation,
            database_now=now,
        )
        proof = TenantRegistrationProvisioningProof(
            id=str(uuid4()),
            attempt_uuid=attempt.id,
            user_uuid=user.id,
            tenant_uuid=tenant.id,
            database_uuid=attempt.provisional_database_uuid,
            recovery_run_uuid=str(authority.current_recovery_run_uuid),
            provisioning_execution_generation=generation,
            expected_attempt_row_version=attempt_revision,
            worker_lease_owner=owner,
            worker_lease_token_digest=_worker_token_digest(token),
            worker_lease_expires_at=_as_database_utc(attempt.lease_expires_at),
            outcome="failed",
            safe_error_code=reason,
            result_request_digest=request_digest,
            proof_policy_version=REGISTRATION_PROVISIONING_PROOF_POLICY_VERSION,
            recorded_at=now,
        )
        try:
            with session.begin_nested():
                session.add(proof)
                changed = session.execute(
                    sa.update(TenantRegistrationAttempt)
                    .where(
                        TenantRegistrationAttempt.id == attempt.id,
                        TenantRegistrationAttempt.status == "provisioning",
                        TenantRegistrationAttempt.row_version == attempt_revision,
                        TenantRegistrationAttempt.provisioning_execution_generation
                        == generation,
                        TenantRegistrationAttempt.lease_owner == owner,
                        TenantRegistrationAttempt.lease_token == token,
                    )
                    .values(
                        status="failed",
                        lease_owner=None,
                        lease_token=None,
                        lease_expires_at=None,
                        last_safe_error_code=reason,
                        row_version=attempt_revision + 1,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    raise RegistrationFenceError()
                session.flush()
        except IntegrityError:
            raise RegistrationConflictError() from None
        session.expire(attempt)
        return _provisioning_failure_result(attempt, proof, created=True)

    def retry_failed_after_verified_otp(
        self,
        session: Session,
        *,
        challenge_uuid: str | UUID,
        attempt_uuid: str | UUID,
        expected_attempt_row_version: int,
        expected_provisioning_generation: int,
        expected_code_row_version: int,
        lease_owner: str,
        lease_token: str,
        lease_expires_at: datetime,
        current_recovery_run_uuid: str | UUID,
    ) -> RegistrationRetryResult:
        self._prepare(session)
        challenge_id = str(_uuid(challenge_uuid, "challenge_uuid"))
        attempt_id = str(_uuid(attempt_uuid, "attempt_uuid"))
        attempt_revision = _positive(
            expected_attempt_row_version,
            "expected_attempt_row_version",
        )
        generation = _positive(
            expected_provisioning_generation,
            "expected_provisioning_generation",
        )
        code_revision = _positive(
            expected_code_row_version,
            "expected_code_row_version",
        )
        owner = _token(lease_owner, "lease_owner")
        token = _token(lease_token, "lease_token")
        expires_at = _as_database_utc(lease_expires_at)
        run_uuid = _uuid(
            current_recovery_run_uuid,
            "current_recovery_run_uuid",
        )

        summary = session.get(TenantRegistrationAttempt, attempt_id)
        if summary is None:
            raise RegistrationConflictError()
        user = self._lock_user(session, summary.user_id)
        blocking_memberships = self._lock_user_memberships(session, user.id)
        challenge = self._lock_challenge(session, challenge_id)
        self._lock_phone_invitations(session, user.phone_e164)
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == summary.provisional_tenant_uuid)
            .with_for_update()
        )
        if tenant is None:
            raise RegistrationConflictError()
        authority_observed_at = self._now(session)
        authority = self._read_authority(
            session,
            tenant_uuid=UUID(tenant.id),
            expected_run_uuid=run_uuid,
            database_now=authority_observed_at,
            require_released_hold=False,
        )
        self._lock_route_if_present(
            session,
            tenant_id=tenant.id,
            database_uuid=summary.provisional_database_uuid,
        )
        attempt = session.scalar(
            sa.select(TenantRegistrationAttempt)
            .where(TenantRegistrationAttempt.id == attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if attempt is None:  # pragma: no cover - restricted deletion
            raise RegistrationConflictError()
        replacement = session.scalar(
            sa.select(RedemptionCodeReplacement)
            .where(RedemptionCodeReplacement.source_attempt_uuid == attempt.id)
            .with_for_update()
        )
        code = session.scalar(
            sa.select(RedemptionCode)
            .where(RedemptionCode.id == attempt.redemption_code_id)
            .with_for_update()
        )
        if code is None:
            raise RegistrationCodeError()
        now = self._now(session)
        if expires_at <= now:
            raise ValueError("lease_expires_at must be in the future")

        request_digest = retry_action_digest(
            attempt_uuid=attempt_id,
            user_uuid=attempt.user_id,
            canonical_phone=user.phone_e164,
            phone_normalization_version=user.phone_normalization_version,
            expected_attempt_row_version=attempt_revision,
            expected_provisioning_generation=generation,
            expected_code_row_version=code_revision,
            lease_owner=owner,
            lease_token=token,
            lease_expires_at=expires_at,
            current_recovery_run_uuid=str(run_uuid),
        )
        self._require_register_challenge(
            challenge,
            user=user,
            expected_digest=request_digest,
            expected_revision=REGISTRATION_RETRY_REVISION,
            database_now=now,
        )
        if replacement is not None:
            raise RegistrationFenceError()

        if (
            attempt.status == "provisioning"
            and attempt.provisioning_execution_generation == generation + 1
            and attempt.row_version == attempt_revision + 1
            and attempt.lease_owner == owner
            and attempt.lease_token == token
            and _as_database_utc(attempt.lease_expires_at) == expires_at
        ):
            return _retry_result(attempt, created=False)

        self._require_user_available(user, blocking_memberships)
        if (
            attempt.status not in {"failed", "identity_conflict", "security_blocked"}
            or attempt.row_version != attempt_revision
            or attempt.provisioning_execution_generation != generation
            or attempt.lease_owner is not None
            or attempt.lease_token is not None
            or attempt.lease_expires_at is not None
            or attempt.recovery_run_uuid != str(authority.current_recovery_run_uuid)
        ):
            raise RegistrationFenceError()
        self._require_reserved_code(
            code,
            attempt=attempt,
            user=user,
            current_run_uuid=run_uuid,
            expected_row_version=code_revision,
        )

        changed = session.execute(
            sa.update(TenantRegistrationAttempt)
            .where(
                TenantRegistrationAttempt.id == attempt.id,
                TenantRegistrationAttempt.row_version == attempt_revision,
                TenantRegistrationAttempt.provisioning_execution_generation
                == generation,
                TenantRegistrationAttempt.status.in_(
                    ("failed", "identity_conflict", "security_blocked")
                ),
                TenantRegistrationAttempt.lease_owner.is_(None),
                TenantRegistrationAttempt.lease_token.is_(None),
                TenantRegistrationAttempt.lease_expires_at.is_(None),
            )
            .values(
                status="provisioning",
                provisioning_execution_generation=generation + 1,
                lease_owner=owner,
                lease_token=token,
                lease_expires_at=expires_at,
                attempt_count=attempt.attempt_count + 1,
                last_safe_error_code=None,
                row_version=attempt_revision + 1,
                updated_at=now,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise RegistrationFenceError()
        session.expire(attempt)
        session.flush()
        return _retry_result(attempt, created=True)

    def read_finalization_replay(
        self,
        session: Session,
        *,
        attempt_uuid: str | UUID,
        tenant_uuid: str | UUID,
        database_uuid: str | UUID,
        expected_attempt_row_version: int,
        expected_code_row_version: int,
        current_recovery_run_uuid: str | UUID,
        provisioning_generation: int,
        ready_proof_uuid: str | UUID,
        ready_proof_request_digest: bytes,
        plan: RegistrationFinalCommitPlan,
    ) -> RegistrationFinalizationResult | None:
        """Read an exact completed finalization without requiring a live lease.

        ``None`` means the exact ready request has no publication footprint and
        may continue through the normal live schema/advisory fences.  A result
        is returned only when every immutable final anchor and the persisted
        original request digest agree.  Partial anchors, a different completed
        request, and caller-input drift all fail closed.

        The method is read-only and caller-transactional.  It follows the
        finalizer's control-row lock order, never calls a tenant database, and
        cannot authorize an unpublished request.
        """

        self._prepare(session)
        if not isinstance(plan, RegistrationFinalCommitPlan):
            raise TypeError("final commit plan is invalid")
        attempt_id = str(_uuid(attempt_uuid, "attempt_uuid"))
        tenant_id = str(_uuid(tenant_uuid, "tenant_uuid"))
        database_id = str(_uuid(database_uuid, "database_uuid"))
        attempt_revision = _positive(
            expected_attempt_row_version,
            "expected_attempt_row_version",
        )
        code_revision = _positive(
            expected_code_row_version,
            "expected_code_row_version",
        )
        run_uuid = _uuid(
            current_recovery_run_uuid,
            "current_recovery_run_uuid",
        )
        generation = _positive(
            provisioning_generation,
            "provisioning_generation",
        )
        proof_id = str(_uuid(ready_proof_uuid, "ready_proof_uuid"))
        proof_request_digest = _digest(
            ready_proof_request_digest,
            "ready_proof_request_digest",
        )

        summary = session.get(TenantRegistrationAttempt, attempt_id)
        if summary is None:
            raise RegistrationConflictError()
        user = self._lock_user(session, summary.user_id)
        self._lock_user_memberships(session, user.id)
        self._lock_phone_invitations(session, user.phone_e164)
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == summary.provisional_tenant_uuid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if tenant is None:
            raise RegistrationConflictError()
        authority_observed_at = self._now(session)
        authority = self._read_authority(
            session,
            tenant_uuid=UUID(tenant.id),
            expected_run_uuid=run_uuid,
            database_now=authority_observed_at,
            require_released_hold=bool(
                tenant.status == "active" or summary.status == "active"
            ),
            allow_historical_replay=True,
        )
        route, _identity = self._lock_route_and_identity(
            session,
            tenant_id=tenant.id,
            database_uuid=summary.provisional_database_uuid,
        )
        attempt = self._lock_attempt(session, attempt_id)
        proofs = self._lock_provisioning_proofs(
            session,
            attempt_uuid=attempt.id,
            provisioning_generation=generation,
        )
        replacements, incidents = self._lock_finalization_conflicts(
            session,
            attempt_uuid=attempt.id,
            code_uuid=attempt.redemption_code_id,
        )
        code = self._lock_registration_code(
            session,
            attempt.redemption_code_id,
        )

        proof = next((item for item in proofs if item.id == proof_id), None)
        if (
            attempt.provisional_tenant_uuid != tenant_id
            or attempt.provisional_database_uuid != database_id
            or attempt.recovery_run_uuid != str(run_uuid)
            or attempt.provisioning_execution_generation != generation
            or route.tenant_id != tenant_id
            or route.database_uuid != database_id
            or proof is None
            or proof.outcome != "ready"
            or proof.attempt_uuid != attempt_id
            or proof.user_uuid != attempt.user_id
            or proof.tenant_uuid != tenant_id
            or proof.database_uuid != database_id
            or proof.recovery_run_uuid != str(run_uuid)
            or proof.provisioning_execution_generation != generation
            or proof.proof_policy_version
            != REGISTRATION_PROVISIONING_PROOF_POLICY_VERSION
            or not hmac.compare_digest(
                bytes(proof.result_request_digest),
                proof_request_digest,
            )
        ):
            raise RegistrationConflictError()
        _require_ready_proof_integrity(
            proof,
            expected_code_row_version=code_revision,
        )
        if replacements:
            raise RegistrationConflictError()

        provisioned = _replay_provisioned_anchors(proof)
        anchors = _read_anchor_evidence(
            session,
            attempt=attempt,
            tenant=tenant,
            route=route,
            code=code,
            plan=plan,
            authority=authority,
            provisioned=provisioned,
            proof=proof,
            expected_attempt_row_version=attempt_revision,
            expected_code_row_version=code_revision,
            lock=True,
            replacements=replacements,
            incidents=incidents,
            require_persisted_baseline=(self._released_hold_baseline_write is not None),
        )
        if anchors.complete:
            return anchors.result(created=False)
        if anchors.has_partial or anchors.request_conflict:
            raise RegistrationConflictError()
        self._require_authority_facts(
            authority,
            expected_run_uuid=run_uuid,
            require_released_hold=False,
        )
        _require_exact_provisional_replay_state(
            attempt=attempt,
            tenant=tenant,
            route=route,
            code=code,
            proof=proof,
            expected_attempt_row_version=attempt_revision,
            expected_code_row_version=code_revision,
            expected_provisioning_generation=generation,
        )
        return None

    def finalize_registration(
        self,
        session: Session,
        *,
        attempt_uuid: str | UUID,
        expected_attempt_row_version: int,
        expected_code_row_version: int,
        current_recovery_run_uuid: str | UUID,
        provisioned: ProvisionedRegistrationFacts,
        plan: RegistrationFinalCommitPlan,
        fence_current_read: RegistrationFinalFenceCurrentRead,
    ) -> RegistrationFinalizationResult:
        self._prepare(session)
        if not callable(fence_current_read):
            raise RegistrationFenceError()
        if not isinstance(provisioned, ProvisionedRegistrationFacts):
            raise TypeError("provisioned facts are invalid")
        if not isinstance(plan, RegistrationFinalCommitPlan):
            raise TypeError("final commit plan is invalid")
        if not provisioned.verified:
            raise RegistrationFenceError()
        attempt_id = str(_uuid(attempt_uuid, "attempt_uuid"))
        attempt_revision = _positive(
            expected_attempt_row_version,
            "expected_attempt_row_version",
        )
        code_revision = _positive(
            expected_code_row_version,
            "expected_code_row_version",
        )
        run_uuid = _uuid(
            current_recovery_run_uuid,
            "current_recovery_run_uuid",
        )

        summary = session.get(TenantRegistrationAttempt, attempt_id)
        if summary is None:
            raise RegistrationConflictError()
        user = self._lock_user(session, summary.user_id)
        blocking_memberships = self._lock_user_memberships(session, user.id)
        invitations = self._lock_phone_invitations(session, user.phone_e164)
        tenant = session.scalar(
            sa.select(Tenant)
            .where(Tenant.id == summary.provisional_tenant_uuid)
            .with_for_update()
        )
        if tenant is None:
            raise RegistrationConflictError()
        authority_observed_at = self._now(session)
        authority = self._read_authority(
            session,
            tenant_uuid=UUID(tenant.id),
            expected_run_uuid=run_uuid,
            database_now=authority_observed_at,
            require_released_hold=(self._released_hold_baseline_write is None),
            allow_historical_replay=True,
        )
        route, identity = self._lock_route_and_identity(
            session,
            tenant_id=tenant.id,
            database_uuid=summary.provisional_database_uuid,
        )
        attempt = session.scalar(
            sa.select(TenantRegistrationAttempt)
            .where(TenantRegistrationAttempt.id == attempt_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if attempt is None:
            raise RegistrationConflictError()
        proofs = self._lock_provisioning_proofs(
            session,
            attempt_uuid=attempt.id,
            provisioning_generation=provisioned.provisioning_generation,
        )
        proof = _matching_worker_proof(
            proofs,
            worker_lease_owner=provisioned.lease_owner,
            worker_lease_token=provisioned.lease_token,
        )
        if (
            proof is None
            or proof.outcome != "ready"
            or proof.attempt_uuid != attempt.id
            or proof.user_uuid != attempt.user_id
            or proof.tenant_uuid != tenant.id
            or proof.database_uuid != route.database_uuid
            or proof.recovery_run_uuid != str(run_uuid)
        ):
            raise RegistrationFenceError()
        try:
            self._require_proof_matches_expected(proof, provisioned)
        except RegistrationFenceError:
            if attempt.status == "active":
                raise RegistrationConflictError() from None
            raise
        replacements, incidents = self._lock_finalization_conflicts(
            session,
            attempt_uuid=attempt.id,
            code_uuid=attempt.redemption_code_id,
        )
        code = session.scalar(
            sa.select(RedemptionCode)
            .where(RedemptionCode.id == attempt.redemption_code_id)
            .with_for_update()
        )
        if code is None:
            raise RegistrationCodeError()
        if attempt.status != "active" and code.row_version != code_revision:
            raise RegistrationCodeError()
        _require_ready_proof_integrity(
            proof,
            expected_code_row_version=code_revision,
        )
        if replacements:
            raise RegistrationFenceError()

        anchors = self._lock_final_anchors(
            session,
            attempt=attempt,
            tenant=tenant,
            route=route,
            code=code,
            plan=plan,
            authority=authority,
            provisioned=provisioned,
            proof=proof,
            expected_attempt_row_version=attempt_revision,
            expected_code_row_version=code_revision,
            replacements=replacements,
            incidents=incidents,
        )
        # This is the only safe publication-fence insertion point: all normal
        # registration rows and immutable anchors are locked, while no block,
        # integrity incident, released baseline, public identity, subscription,
        # membership, commit, code, attempt, or route mutation has occurred.
        # The concrete publication adapter wraps this callback and verifies it
        # completed before allowing this same Session transaction to commit.
        if anchors.complete:
            try:
                fence_result = fence_current_read(control_transaction=session)
            except RegistrationPersistenceError:
                raise
            except Exception:
                raise RegistrationFenceError() from None
            if fence_result is not None:
                raise RegistrationFenceError()
            return anchors.result(created=False)
        if anchors.request_conflict:
            raise RegistrationConflictError()
        self._require_authority_facts(
            authority,
            expected_run_uuid=run_uuid,
            require_released_hold=(self._released_hold_baseline_write is None),
        )
        try:
            fence_result = fence_current_read(control_transaction=session)
        except RegistrationPersistenceError:
            raise
        except Exception:
            raise RegistrationFenceError() from None
        if fence_result is not None:
            raise RegistrationFenceError()
        now = self._now(session)
        if anchors.has_partial:
            return self._integrity_block(
                session,
                attempt=attempt,
                code=code,
                tenant=tenant,
                authority=authority,
                anchors=anchors,
                database_now=now,
            )

        if (
            attempt.status not in {"ready", "committing"}
            or attempt.row_version != attempt_revision
            or attempt.provisioning_execution_generation
            != provisioned.provisioning_generation
            or attempt.lease_owner != provisioned.lease_owner
            or attempt.lease_token != provisioned.lease_token
            or _as_database_utc(attempt.lease_expires_at) <= now
            or attempt.recovery_run_uuid != str(run_uuid)
        ):
            raise RegistrationFenceError()
        self._require_reserved_code(
            code,
            attempt=attempt,
            user=user,
            current_run_uuid=run_uuid,
            expected_row_version=code_revision,
        )
        self._require_provisioned_facts(
            attempt=attempt,
            tenant=tenant,
            route=route,
            identity=identity,
            provisioned=provisioned,
        )

        if user.status == "disabled":
            return self._block_attempt(
                session,
                attempt,
                status="security_blocked",
                reason="registration_user_disabled",
                database_now=now,
            )
        if user.status != "active":
            raise RegistrationFenceError()
        if blocking_memberships:
            return self._block_attempt(
                session,
                attempt,
                status="identity_conflict",
                reason="registration_membership_exists",
                database_now=now,
            )
        if attempt.requested_tenant_name != plan.published_tenant_name:
            raise RegistrationFenceError()

        snapshot = _validated_code_snapshot(code)
        plan_revision = session.get(PlanRevision, code.plan_revision_uuid)
        if (
            plan_revision is None
            or plan_revision.entitlements_schema_version != snapshot.schema_version
            or not hmac.compare_digest(
                bytes(plan_revision.entitlements_digest),
                snapshot.digest_sha256,
            )
        ):
            raise RegistrationCodeError()
        if self._released_hold_baseline_write is not None:
            authority = self._write_released_hold_baseline(
                session,
                tenant=tenant,
                database_uuid=provisioned.database_uuid,
                registration_commit_uuid=plan.registration_commit_uuid,
                expected_run_uuid=run_uuid,
                expected_dml_login_state_version=(provisioned.dml_login_state_version),
                database_now=now,
            )
            # The baseline writer may itself acquire recovery authority rows.
            # Refresh database time before the publication CAS so a wait at
            # that boundary cannot extend an expired provisioning lease.
            now = self._now(session)
            if _as_database_utc(attempt.lease_expires_at) <= now:
                raise RegistrationFenceError()

        try:
            expires_at = now + timedelta(seconds=code.service_duration_seconds)
        except OverflowError:
            raise RegistrationCodeError() from None

        entity_link_digest = _entity_link_digest(
            attempt=attempt,
            code=code,
            authority=authority,
            provisioned=provisioned,
            proof=proof,
            plan=plan,
        )
        final_request_digest = _final_request_digest(
            attempt=attempt,
            code=code,
            authority=authority,
            provisioned=provisioned,
            proof=proof,
            plan=plan,
            expected_attempt_row_version=attempt_revision,
            expected_code_row_version=code_revision,
        )
        tenant_revision = tenant.row_version
        committing_revision = attempt_revision
        try:
            with session.begin_nested():
                if attempt.status == "ready":
                    changed = session.execute(
                        sa.update(TenantRegistrationAttempt)
                        .where(
                            TenantRegistrationAttempt.id == attempt.id,
                            TenantRegistrationAttempt.status == "ready",
                            TenantRegistrationAttempt.row_version == attempt_revision,
                            TenantRegistrationAttempt.provisioning_execution_generation
                            == provisioned.provisioning_generation,
                            TenantRegistrationAttempt.lease_owner
                            == provisioned.lease_owner,
                            TenantRegistrationAttempt.lease_token
                            == provisioned.lease_token,
                        )
                        .values(
                            status="committing",
                            row_version=attempt_revision + 1,
                            updated_at=now,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if changed.rowcount != 1:
                        raise RegistrationFenceError()
                    committing_revision += 1

                membership = TenantMembership(
                    id=str(plan.membership_uuid),
                    tenant_id=tenant.id,
                    user_id=user.id,
                    role_key="admin",
                    status="active",
                    source_type="registration",
                    source_uuid=str(plan.registration_commit_uuid),
                    registration_commit_uuid=str(plan.registration_commit_uuid),
                    row_version=1,
                    created_at=now,
                    updated_at=now,
                )
                subscription = Subscription(
                    id=str(plan.subscription_uuid),
                    tenant_id=tenant.id,
                    plan_revision_uuid=code.plan_revision_uuid,
                    entitlements_schema_version=snapshot.schema_version,
                    entitlements_json=code.entitlements_json,
                    entitlements_digest=snapshot.digest_sha256,
                    status="active",
                    expires_at=expires_at,
                    row_version=1,
                    provider="manual",
                    provider_ref=None,
                    created_from_registration_commit_uuid=str(
                        plan.registration_commit_uuid
                    ),
                    created_at=now,
                    updated_at=now,
                )
                event = SubscriptionEvent(
                    id=str(plan.subscription_event_uuid),
                    tenant_id=tenant.id,
                    subscription_id=subscription.id,
                    event_type="activated",
                    source_type="registration",
                    source_uuid=str(plan.registration_commit_uuid),
                    consumed_code_uuid=code.id,
                    before_plan_revision_uuid=None,
                    after_plan_revision_uuid=code.plan_revision_uuid,
                    before_entitlements_digest=None,
                    after_entitlements_digest=snapshot.digest_sha256,
                    exact_duration_seconds=code.service_duration_seconds,
                    signed_delta_days=None,
                    calculation_base_at=now,
                    database_effective_at=now,
                    before_expires_at=None,
                    after_expires_at=expires_at,
                    before_status=None,
                    after_status="active",
                    expected_subscription_row_version=None,
                    idempotency_key=plan.idempotency_key,
                    request_digest=final_request_digest,
                    canonicalization_version=REGISTRATION_FINALIZATION_VERSION,
                    platform_actor_id=None,
                    platform_session_id=None,
                    factor_method=None,
                    factor_accepted_at=None,
                    reason_code="registration",
                    note=None,
                    offline_reference=None,
                    created_at=now,
                )
                commit = TenantRegistrationCommit(
                    id=str(plan.registration_commit_uuid),
                    attempt_uuid=attempt.id,
                    code_uuid=code.id,
                    tenant_uuid=tenant.id,
                    database_uuid=route.database_uuid,
                    user_uuid=user.id,
                    membership_uuid=membership.id,
                    subscription_uuid=subscription.id,
                    subscription_event_uuid=event.id,
                    recovery_run_uuid=str(authority.current_recovery_run_uuid),
                    provisioning_execution_generation_at_commit=(
                        provisioned.provisioning_generation
                    ),
                    plan_revision_uuid=code.plan_revision_uuid,
                    entitlements_schema_version=snapshot.schema_version,
                    entitlements_digest=snapshot.digest_sha256,
                    service_duration_seconds=code.service_duration_seconds,
                    published_tenant_name_digest=_sha256_text(
                        plan.published_tenant_name
                    ),
                    published_slug_digest=_sha256_text(plan.published_slug),
                    schema_generation=provisioned.schema_generation,
                    database_identity_digest=(provisioned.database_identity_digest),
                    released_hold_uuid=str(authority.released_hold_uuid),
                    released_hold_revision_at_commit=(authority.released_hold_revision),
                    initial_route_version=provisioned.route_version,
                    initial_credential_generation=(
                        provisioned.initial_credential_generation
                    ),
                    commit_policy_version=plan.commit_policy_version,
                    entity_link_digest=entity_link_digest,
                    committed_at=now,
                )
                # The final commit references the three anchors by immutable
                # UUID.  Flush them in dependency order because MySQL enforces
                # these FKs immediately and several cycle-breaking FKs use
                # ``use_alter``, so ORM table sorting alone is insufficient.
                session.add_all((membership, subscription))
                session.flush()
                session.add(event)
                session.flush()
                session.add(commit)

                tenant_changed = session.execute(
                    sa.update(Tenant)
                    .where(
                        Tenant.id == tenant.id,
                        Tenant.status == "provisioning",
                        Tenant.row_version == tenant_revision,
                        Tenant.name.is_(None),
                        Tenant.slug.is_(None),
                        Tenant.public_identity_published_at.is_(None),
                    )
                    .values(
                        name=plan.published_tenant_name,
                        slug=plan.published_slug,
                        public_identity_published_at=now,
                        status="active",
                        row_version=tenant_revision + 1,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if tenant_changed.rowcount != 1:
                    raise RegistrationFenceError()

                code_changed = session.execute(
                    sa.update(RedemptionCode)
                    .where(
                        RedemptionCode.id == code.id,
                        RedemptionCode.status == "reserved",
                        RedemptionCode.row_version == code_revision,
                        RedemptionCode.reserved_user_uuid == user.id,
                        RedemptionCode.reserved_registration_attempt_uuid == attempt.id,
                        RedemptionCode.created_under_recovery_run_uuid == str(run_uuid),
                    )
                    .values(
                        status="redeemed",
                        redeemed_tenant_uuid=tenant.id,
                        redeemed_registration_attempt_uuid=attempt.id,
                        registration_commit_uuid=str(plan.registration_commit_uuid),
                        redeemed_at=now,
                        row_version=code_revision + 1,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if code_changed.rowcount != 1:
                    raise RegistrationFenceError()

                attempt_changed = session.execute(
                    sa.update(TenantRegistrationAttempt)
                    .where(
                        TenantRegistrationAttempt.id == attempt.id,
                        TenantRegistrationAttempt.status == "committing",
                        TenantRegistrationAttempt.row_version == committing_revision,
                        TenantRegistrationAttempt.provisioning_execution_generation
                        == provisioned.provisioning_generation,
                        TenantRegistrationAttempt.lease_owner
                        == provisioned.lease_owner,
                        TenantRegistrationAttempt.lease_token
                        == provisioned.lease_token,
                    )
                    .values(
                        status="active",
                        registration_commit_uuid=str(plan.registration_commit_uuid),
                        lease_owner=None,
                        lease_token=None,
                        lease_expires_at=None,
                        row_version=committing_revision + 1,
                        completed_at=now,
                        updated_at=now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if attempt_changed.rowcount != 1:
                    raise RegistrationFenceError()

                route.activated_by_registration_commit_uuid = str(
                    plan.registration_commit_uuid
                )
                route.activation_route_version = provisioned.route_version
                route.activation_credential_generation = (
                    provisioned.initial_credential_generation
                )
                route.status = "ready"
                route.row_version += 1
                route.updated_at = now
                identity.last_verified_at = now
                for invitation in invitations:
                    invitation.status = "superseded"
                    invitation.user_id = None
                    invitation.superseded_at = now
                    invitation.terminal_reason_code = "registration_committed"
                    invitation.row_version += 1
                    invitation.updated_at = now
                session.flush()
        except IntegrityError:
            session.expire_all()
            refreshed = self._lock_final_anchors_by_attempt(
                session,
                attempt_uuid=attempt_id,
                plan=plan,
                authority=authority,
                provisioned=provisioned,
                proof=proof,
                expected_attempt_row_version=attempt_revision,
                expected_code_row_version=code_revision,
            )
            if refreshed.complete:
                return refreshed.result(created=False)
            if refreshed.request_conflict:
                raise RegistrationConflictError()
            if refreshed.has_partial:
                refreshed_attempt = session.get(
                    TenantRegistrationAttempt,
                    attempt_id,
                )
                refreshed_code = session.get(
                    RedemptionCode,
                    code.id,
                )
                refreshed_tenant = session.get(Tenant, tenant.id)
                return self._integrity_block(
                    session,
                    attempt=refreshed_attempt,
                    code=refreshed_code,
                    tenant=refreshed_tenant,
                    authority=authority,
                    anchors=refreshed,
                    database_now=now,
                )
            raise RegistrationConflictError() from None

        session.expire_all()
        completed = self._lock_final_anchors_by_attempt(
            session,
            attempt_uuid=attempt_id,
            plan=plan,
            authority=authority,
            provisioned=provisioned,
            proof=proof,
            expected_attempt_row_version=attempt_revision,
            expected_code_row_version=code_revision,
        )
        if not completed.complete:  # pragma: no cover - defensive invariant
            raise RuntimeError("registration finalization anchors were not persisted")
        return completed.result(created=True)

    def _prepare(self, session: Session) -> None:
        _require_clean_caller_transaction(session)

    def _now(self, session: Session) -> datetime:
        return _as_database_utc(self._database_clock(session))

    def _lock_attempt(
        self,
        session: Session,
        attempt_uuid: str,
    ) -> TenantRegistrationAttempt:
        attempt = session.scalar(
            sa.select(TenantRegistrationAttempt)
            .where(TenantRegistrationAttempt.id == attempt_uuid)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if attempt is None:
            raise RegistrationConflictError()
        return attempt

    def _lock_provisioning_proofs(
        self,
        session: Session,
        *,
        attempt_uuid: str,
        provisioning_generation: int,
    ) -> tuple[TenantRegistrationProvisioningProof, ...]:
        return tuple(
            session.scalars(
                sa.select(TenantRegistrationProvisioningProof)
                .where(
                    TenantRegistrationProvisioningProof.attempt_uuid == attempt_uuid,
                    TenantRegistrationProvisioningProof.provisioning_execution_generation
                    == provisioning_generation,
                )
                .order_by(TenantRegistrationProvisioningProof.id)
                .with_for_update()
            )
        )

    def _lock_replacement(
        self,
        session: Session,
        attempt_uuid: str,
    ) -> RedemptionCodeReplacement | None:
        return session.scalar(
            sa.select(RedemptionCodeReplacement)
            .where(RedemptionCodeReplacement.source_attempt_uuid == attempt_uuid)
            .with_for_update()
        )

    def _lock_finalization_conflicts(
        self,
        session: Session,
        *,
        attempt_uuid: str,
        code_uuid: str,
    ) -> tuple[
        tuple[RedemptionCodeReplacement, ...],
        tuple[RegistrationIntegrityIncident, ...],
    ]:
        """Lock every D54/D58 fact that can invalidate final publication.

        A replacement may be linked through either the attempt or its source
        code after recovery normalization.  Terminal ``resolved_committed``
        incidents are retained as legitimate history; open/pending incidents
        remain a hard publication blocker.
        """

        replacements = tuple(
            session.scalars(
                sa.select(RedemptionCodeReplacement)
                .where(
                    sa.or_(
                        RedemptionCodeReplacement.source_attempt_uuid == attempt_uuid,
                        RedemptionCodeReplacement.source_code_uuid == code_uuid,
                    )
                )
                .order_by(RedemptionCodeReplacement.id)
                .with_for_update()
            )
        )
        incidents = tuple(
            session.scalars(
                sa.select(RegistrationIntegrityIncident)
                .where(RegistrationIntegrityIncident.attempt_uuid == attempt_uuid)
                .order_by(RegistrationIntegrityIncident.id)
                .with_for_update()
            )
        )
        return replacements, incidents

    def _lock_registration_code(
        self,
        session: Session,
        code_uuid: str,
    ) -> RedemptionCode:
        code = session.scalar(
            sa.select(RedemptionCode)
            .where(RedemptionCode.id == code_uuid)
            .with_for_update()
        )
        if code is None:
            raise RegistrationCodeError()
        return code

    def _lock_schema_operation_lease(
        self,
        session: Session,
    ) -> PlatformSchemaOperationLease:
        lease = session.scalar(
            sa.select(PlatformSchemaOperationLease)
            .where(
                PlatformSchemaOperationLease.lease_key == _SCHEMA_OPERATION_LEASE_KEY
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if lease is None:
            raise RegistrationFenceError()
        return lease

    def _require_mutation_identity(
        self,
        *,
        attempt: TenantRegistrationAttempt,
        user: User,
        tenant: Tenant,
        authority: RegistrationAuthorityFacts,
        current_run_uuid: UUID,
    ) -> None:
        if (
            attempt.user_id != user.id
            or attempt.provisional_tenant_uuid != tenant.id
            or attempt.provisional_database_uuid is None
            or attempt.recovery_run_uuid != str(current_run_uuid)
            or authority.current_recovery_run_uuid != current_run_uuid
            or tenant.status != "provisioning"
            or tenant.name is not None
            or tenant.slug is not None
            or tenant.public_identity_published_at is not None
        ):
            raise RegistrationFenceError()

    def _require_current_worker(
        self,
        attempt: TenantRegistrationAttempt,
        *,
        owner: str,
        token: str,
        generation: int,
        database_now: datetime,
    ) -> None:
        if (
            attempt.provisioning_execution_generation != generation
            or attempt.lease_owner != owner
            or attempt.lease_token is None
            or not hmac.compare_digest(attempt.lease_token, token)
            or attempt.lease_expires_at is None
            or _as_database_utc(attempt.lease_expires_at) <= database_now
        ):
            raise RegistrationFenceError()

    def _require_live_schema_operation_fence(
        self,
        row: PlatformSchemaOperationLease,
        *,
        expected: RegistrationSchemaOperationFence,
        database_now: datetime,
    ) -> None:
        if (
            row.state != "held"
            or row.purpose != "provisioning"
            or row.claim_id != str(expected.claim_uuid)
            or row.last_claim_id != row.claim_id
            or row.owner_id != expected.owner_id
            or row.generation != expected.generation
            or row.fencing_token != expected.fencing_token
            or row.row_version != expected.row_version
            or row.last_effect not in {"claimed", "renewed"}
            or row.acquired_at is None
            or row.expires_at is None
            or _as_database_utc(row.acquired_at) > database_now
            or _as_database_utc(row.expires_at) <= database_now
        ):
            raise RegistrationFenceError()

    def _read_provisioned_facts(
        self,
        session: Session,
        *,
        tenant_uuid: UUID,
        database_uuid: UUID,
        provisioning_generation: int,
        worker_lease_owner: str,
        worker_lease_token: str,
        schema_operation_fence: RegistrationSchemaOperationFence,
        database_now: datetime,
    ) -> ProvisionedRegistrationFacts:
        callback = self._provisioning_current_read
        if callback is None:
            raise RegistrationFenceError()
        transaction = session.get_transaction()
        try:
            facts = callback(
                session,
                tenant_uuid=tenant_uuid,
                database_uuid=database_uuid,
                provisioning_generation=provisioning_generation,
                worker_lease_owner=worker_lease_owner,
                worker_lease_token=worker_lease_token,
                schema_operation_fence=schema_operation_fence,
                database_now=database_now,
            )
        except Exception:
            raise RegistrationFenceError() from None
        if (
            session.get_transaction() is not transaction
            or not isinstance(facts, ProvisionedRegistrationFacts)
            or not facts.verified
        ):
            raise RegistrationFenceError()
        try:
            _require_clean_caller_transaction(session)
        except RegistrationTransactionError:
            raise RegistrationFenceError() from None
        return facts

    def _require_proof_matches_expected(
        self,
        proof: TenantRegistrationProvisioningProof,
        expected: ProvisionedRegistrationFacts,
    ) -> None:
        if (
            proof.outcome != "ready"
            or proof.user_uuid is None
            or proof.tenant_uuid != str(expected.tenant_uuid)
            or proof.database_uuid != str(expected.database_uuid)
            or proof.provisioning_execution_generation
            != expected.provisioning_generation
            or proof.worker_lease_owner != expected.lease_owner
            or not hmac.compare_digest(
                bytes(proof.worker_lease_token_digest),
                _worker_token_digest(expected.lease_token),
            )
            or proof.schema_generation != expected.schema_generation
            or proof.schema_digest is None
            or not hmac.compare_digest(
                bytes(proof.schema_digest),
                expected.schema_digest,
            )
            or proof.database_identity_digest is None
            or not hmac.compare_digest(
                bytes(proof.database_identity_digest),
                expected.database_identity_digest,
            )
            or proof.route_version != expected.route_version
            or proof.initial_credential_generation
            != expected.initial_credential_generation
            or proof.dml_login_state_version != expected.dml_login_state_version
            or proof.default_warehouse_uuid != str(expected.default_warehouse_uuid)
            or proof.default_warehouse_digest is None
            or not hmac.compare_digest(
                bytes(proof.default_warehouse_digest),
                expected.default_warehouse_digest,
            )
            or proof.smoke_proof_digest is None
            or not hmac.compare_digest(
                bytes(proof.smoke_proof_digest),
                expected.smoke_proof_digest,
            )
            or proof.advisory_lock_proof_digest is None
            or not hmac.compare_digest(
                bytes(proof.advisory_lock_proof_digest),
                expected.advisory_lock_proof_digest,
            )
            or proof.proof_policy_version
            != REGISTRATION_PROVISIONING_PROOF_POLICY_VERSION
            or not expected.verified
        ):
            raise RegistrationFenceError()

    def _lock_user(self, session: Session, user_id: str) -> User:
        user = session.scalar(
            sa.select(User).where(User.id == user_id).with_for_update()
        )
        if user is None:
            raise RegistrationOtpError()
        return user

    def _lock_challenge(
        self,
        session: Session,
        challenge_id: str,
    ) -> SmsChallenge:
        challenge = session.scalar(
            sa.select(SmsChallenge)
            .where(SmsChallenge.id == challenge_id)
            .with_for_update()
        )
        if challenge is None:
            raise RegistrationOtpError()
        return challenge

    def _lock_phone_invitations(
        self,
        session: Session,
        phone: str,
    ) -> tuple[TenantInvitation, ...]:
        return tuple(
            session.scalars(
                sa.select(TenantInvitation)
                .where(
                    TenantInvitation.phone_e164 == phone,
                    TenantInvitation.status == "pending",
                )
                .order_by(TenantInvitation.tenant_id, TenantInvitation.id)
                .with_for_update()
            )
        )

    def _lock_user_memberships(
        self,
        session: Session,
        user_id: str,
    ) -> tuple[TenantMembership, ...]:
        return tuple(
            session.scalars(
                sa.select(TenantMembership)
                .where(
                    TenantMembership.user_id == user_id,
                    TenantMembership.status != "released",
                )
                .order_by(TenantMembership.tenant_id, TenantMembership.id)
                .with_for_update()
            )
        )

    def _require_user_available(
        self,
        user: User,
        blocking_memberships: tuple[TenantMembership, ...],
    ) -> None:
        if (
            user.status != "active"
            or user.phone_verified_at is None
            or _CANONICAL_PHONE.fullmatch(user.phone_e164) is None
            or user.phone_normalization_version < 1
            or blocking_memberships
        ):
            raise RegistrationOtpError()

    def _read_authority(
        self,
        session: Session,
        *,
        tenant_uuid: UUID,
        expected_run_uuid: UUID,
        database_now: datetime,
        require_released_hold: bool,
        allow_historical_replay: bool = False,
    ) -> RegistrationAuthorityFacts:
        try:
            facts = self._authority_current_read(
                session,
                tenant_uuid=tenant_uuid,
                expected_recovery_run_uuid=expected_run_uuid,
                database_now=database_now,
            )
        except Exception:
            raise RegistrationAuthorityError() from None
        if not isinstance(facts, RegistrationAuthorityFacts):
            raise RegistrationAuthorityError()
        if not facts.recovery_run_completed or not facts.external_marker_matches:
            raise RegistrationAuthorityError()
        if not allow_historical_replay:
            self._require_authority_facts(
                facts,
                expected_run_uuid=expected_run_uuid,
                require_released_hold=require_released_hold,
            )
        return facts

    def _require_authority_facts(
        self,
        facts: RegistrationAuthorityFacts,
        *,
        expected_run_uuid: UUID,
        require_released_hold: bool,
    ) -> None:
        """Require current publication authority for a not-yet-committed row.

        Historical committed replays deliberately validate their immutable
        commit-time run/hold anchors instead.  Current D58 holds, subscription
        gates, and later account rotations must not erase that history.
        """

        if (
            facts.current_recovery_run_uuid != expected_run_uuid
            or not facts.recovery_run_completed
            or not facts.external_marker_matches
            or (
                require_released_hold
                and (
                    not facts.released_hold_ready
                    or facts.released_hold_uuid is None
                    or facts.released_hold_revision is None
                )
            )
        ):
            raise RegistrationAuthorityError()

    def _write_released_hold_baseline(
        self,
        session: Session,
        *,
        tenant: Tenant,
        database_uuid: UUID,
        registration_commit_uuid: UUID,
        expected_run_uuid: UUID,
        expected_dml_login_state_version: int,
        database_now: datetime,
    ) -> RegistrationAuthorityFacts:
        callback = self._released_hold_baseline_write
        if callback is None:  # pragma: no cover - guarded by caller
            raise RegistrationAuthorityError()
        try:
            with session.begin_nested():
                facts = callback(
                    session,
                    tenant=tenant,
                    database_uuid=database_uuid,
                    registration_commit_uuid=registration_commit_uuid,
                    expected_recovery_run_uuid=expected_run_uuid,
                    expected_dml_login_state_version=(expected_dml_login_state_version),
                    database_now=database_now,
                )
                if (
                    not isinstance(facts, RegistrationAuthorityFacts)
                    or facts.current_recovery_run_uuid != expected_run_uuid
                    or not facts.recovery_run_completed
                    or not facts.external_marker_matches
                    or not facts.released_hold_ready
                    or facts.released_hold_uuid is None
                    or facts.released_hold_revision is None
                ):
                    raise RegistrationAuthorityError()
        except Exception:
            raise RegistrationAuthorityError() from None
        return facts

    def _lock_attempt_candidates(
        self,
        session: Session,
        *,
        attempt_id: str,
        code_id: str,
        idempotency_key: str,
    ) -> tuple[TenantRegistrationAttempt, ...]:
        return tuple(
            session.scalars(
                sa.select(TenantRegistrationAttempt)
                .where(
                    sa.or_(
                        TenantRegistrationAttempt.id == attempt_id,
                        TenantRegistrationAttempt.redemption_code_id == code_id,
                        TenantRegistrationAttempt.idempotency_key == idempotency_key,
                    )
                )
                .order_by(TenantRegistrationAttempt.id)
                .with_for_update()
            )
        )

    def _lock_route_if_present(
        self,
        session: Session,
        *,
        tenant_id: str,
        database_uuid: str | None,
    ) -> TenantDatabase | None:
        if database_uuid is None:
            return None
        return session.scalar(
            sa.select(TenantDatabase)
            .where(
                TenantDatabase.tenant_id == tenant_id,
                TenantDatabase.database_uuid == database_uuid,
            )
            .with_for_update()
        )

    def _lock_route_and_identity(
        self,
        session: Session,
        *,
        tenant_id: str,
        database_uuid: str | None,
    ) -> tuple[TenantDatabase, DatabaseIdentityControlRecord]:
        route = self._lock_route_if_present(
            session,
            tenant_id=tenant_id,
            database_uuid=database_uuid,
        )
        if route is None:
            raise RegistrationFenceError()
        identity = session.scalar(
            sa.select(DatabaseIdentityControlRecord)
            .where(
                DatabaseIdentityControlRecord.tenant_id == tenant_id,
                DatabaseIdentityControlRecord.database_uuid == database_uuid,
            )
            .with_for_update()
        )
        if identity is None:
            raise RegistrationFenceError()
        return route, identity

    def _require_register_challenge(
        self,
        challenge: SmsChallenge,
        *,
        user: User,
        expected_digest: bytes,
        expected_revision: str,
        database_now: datetime,
    ) -> None:
        consumed_at = (
            _as_database_utc(challenge.consumed_at)
            if challenge.consumed_at is not None
            else None
        )
        if (
            challenge.purpose != "register"
            or challenge.verification_state != "consumed"
            or challenge.delivery_state not in {"sent", "send_unknown"}
            or challenge.user_id != user.id
            or challenge.tenant_id is not None
            or challenge.actor_session_id is not None
            or challenge.canonical_phone_e164 != user.phone_e164
            or challenge.phone_normalization_version != user.phone_normalization_version
            or challenge.phone_metadata_version != user.phone_metadata_version
            or challenge.authoritative_revision != expected_revision
            or consumed_at is None
            or consumed_at > database_now
            or consumed_at < _as_database_utc(challenge.created_at)
            or consumed_at >= _as_database_utc(challenge.expires_at)
            or not hmac.compare_digest(
                bytes(challenge.action_payload_digest_sha256),
                expected_digest,
            )
        ):
            raise RegistrationOtpError()

    def _require_active_code(
        self,
        code: RedemptionCode,
        *,
        current_run_uuid: UUID,
        expected_row_version: int,
        database_now: datetime,
    ) -> None:
        if (
            code.status != "active"
            or code.row_version != expected_row_version
            or code.created_under_recovery_run_uuid != str(current_run_uuid)
            or _as_database_utc(code.redeem_before) <= database_now
            or code.reserved_user_uuid is not None
            or code.reserved_registration_attempt_uuid is not None
        ):
            raise RegistrationCodeError()
        _validated_code_snapshot(code)

    def _require_reserved_code(
        self,
        code: RedemptionCode,
        *,
        attempt: TenantRegistrationAttempt,
        user: User,
        current_run_uuid: UUID,
        expected_row_version: int,
    ) -> None:
        if (
            code.status != "reserved"
            or code.row_version != expected_row_version
            or code.created_under_recovery_run_uuid != str(current_run_uuid)
            or code.reserved_user_uuid != user.id
            or code.reserved_registration_attempt_uuid != attempt.id
            or code.redeemed_tenant_uuid is not None
            or code.registration_commit_uuid is not None
        ):
            raise RegistrationCodeError()
        _validated_code_snapshot(code)

    def _reservation_replay(
        self,
        attempt: TenantRegistrationAttempt,
        *,
        code: RedemptionCode,
        user: User,
        tenant_uuid: str,
        database_uuid: str,
        requested_name: str,
        idempotency_key: str,
        request_digest: bytes,
    ) -> RegistrationReservationResult:
        code_matches = bool(
            code.id == attempt.redemption_code_id
            and code.reserved_user_uuid == user.id
            and code.reserved_registration_attempt_uuid == attempt.id
            and code.status in {"reserved", "redeemed", "recovery_revoked", "revoked"}
        )
        if (
            attempt.user_id != user.id
            or attempt.provisional_tenant_uuid != tenant_uuid
            or attempt.provisional_database_uuid != database_uuid
            or attempt.requested_tenant_name != requested_name
            or attempt.idempotency_key != idempotency_key
            or not hmac.compare_digest(bytes(attempt.request_digest), request_digest)
            or not code_matches
        ):
            raise RegistrationConflictError()
        return _reservation_result(attempt, created=False)

    def _require_provisioned_facts(
        self,
        *,
        attempt: TenantRegistrationAttempt,
        tenant: Tenant,
        route: TenantDatabase,
        identity: DatabaseIdentityControlRecord,
        provisioned: ProvisionedRegistrationFacts,
    ) -> None:
        if (
            str(provisioned.tenant_uuid) != tenant.id
            or attempt.provisional_tenant_uuid != tenant.id
            or str(provisioned.database_uuid) != route.database_uuid
            or attempt.provisional_database_uuid != route.database_uuid
            or route.tenant_id != tenant.id
            or route.status != "provisional"
            or route.route_version != provisioned.route_version
            or route.activated_by_registration_commit_uuid is not None
            or route.activation_route_version is not None
            or route.activation_credential_generation is not None
            or not isinstance(route.dml_username, str)
            or not route.dml_username.strip()
            or route.dml_credential_generation
            != provisioned.initial_credential_generation
            or not _positive_metadata_version(route.dml_root_key_version)
            or not _positive_metadata_version(route.dml_derivation_version)
            or route.dml_desired_login_state != "active"
            or route.dml_observed_login_state != "active"
            or route.dml_login_state_version != provisioned.dml_login_state_version
            or route.dml_desired_state_recovery_run_id is not None
            or not isinstance(route.platform_read_username, str)
            or not route.platform_read_username.strip()
            or not _positive_metadata_version(route.platform_read_credential_generation)
            or not _positive_metadata_version(route.platform_read_root_key_version)
            or not _positive_metadata_version(route.platform_read_derivation_version)
            or route.platform_read_route_version != provisioned.route_version
            or not _positive_metadata_version(route.row_version)
            or not isinstance(route.schema_version, str)
            or not route.schema_version.strip()
            or identity.tenant_id != tenant.id
            or identity.database_uuid != route.database_uuid
            or identity.expected_schema_generation != provisioned.schema_generation
            or identity.observed_schema_generation != provisioned.schema_generation
            or tenant.status != "provisioning"
            or tenant.name is not None
            or tenant.slug is not None
            or tenant.public_identity_published_at is not None
        ):
            raise RegistrationFenceError()

    def _block_attempt(
        self,
        session: Session,
        attempt: TenantRegistrationAttempt,
        *,
        status: str,
        reason: str,
        database_now: datetime,
    ) -> RegistrationFinalizationResult:
        attempt.status = status
        attempt.lease_owner = None
        attempt.lease_token = None
        attempt.lease_expires_at = None
        attempt.last_safe_error_code = reason
        attempt.row_version += 1
        attempt.updated_at = database_now
        session.flush()
        return RegistrationFinalizationResult(
            attempt_uuid=UUID(attempt.id),
            status=status,
            registration_commit_uuid=None,
            membership_uuid=None,
            subscription_uuid=None,
            subscription_event_uuid=None,
            resulting_attempt_row_version=attempt.row_version,
            created=False,
        )

    def _lock_final_anchors(
        self,
        session: Session,
        *,
        attempt: TenantRegistrationAttempt,
        tenant: Tenant,
        route: TenantDatabase,
        code: RedemptionCode,
        plan: RegistrationFinalCommitPlan,
        authority: RegistrationAuthorityFacts,
        provisioned: ProvisionedRegistrationFacts,
        proof: TenantRegistrationProvisioningProof,
        expected_attempt_row_version: int,
        expected_code_row_version: int,
        replacements: tuple[RedemptionCodeReplacement, ...],
        incidents: tuple[RegistrationIntegrityIncident, ...],
    ) -> _AnchorEvidence:
        return _read_anchor_evidence(
            session,
            attempt=attempt,
            tenant=tenant,
            route=route,
            code=code,
            plan=plan,
            authority=authority,
            provisioned=provisioned,
            proof=proof,
            expected_attempt_row_version=expected_attempt_row_version,
            expected_code_row_version=expected_code_row_version,
            lock=True,
            replacements=replacements,
            incidents=incidents,
            require_persisted_baseline=(self._released_hold_baseline_write is not None),
        )

    def _lock_final_anchors_by_attempt(
        self,
        session: Session,
        *,
        attempt_uuid: str,
        plan: RegistrationFinalCommitPlan,
        authority: RegistrationAuthorityFacts,
        provisioned: ProvisionedRegistrationFacts,
        proof: TenantRegistrationProvisioningProof,
        expected_attempt_row_version: int,
        expected_code_row_version: int,
    ) -> _AnchorEvidence:
        attempt = session.scalar(
            sa.select(TenantRegistrationAttempt)
            .where(TenantRegistrationAttempt.id == attempt_uuid)
            .with_for_update()
        )
        if attempt is None:
            raise RegistrationConflictError()
        replacements, incidents = self._lock_finalization_conflicts(
            session,
            attempt_uuid=attempt.id,
            code_uuid=attempt.redemption_code_id,
        )
        tenant = session.get(Tenant, attempt.provisional_tenant_uuid)
        route = session.scalar(
            sa.select(TenantDatabase).where(
                TenantDatabase.database_uuid == attempt.provisional_database_uuid
            )
        )
        code = session.get(RedemptionCode, attempt.redemption_code_id)
        if tenant is None or route is None or code is None:
            raise RegistrationConflictError()
        return _read_anchor_evidence(
            session,
            attempt=attempt,
            tenant=tenant,
            route=route,
            code=code,
            plan=plan,
            authority=authority,
            provisioned=provisioned,
            proof=proof,
            expected_attempt_row_version=expected_attempt_row_version,
            expected_code_row_version=expected_code_row_version,
            lock=True,
            replacements=replacements,
            incidents=incidents,
            require_persisted_baseline=(self._released_hold_baseline_write is not None),
        )

    def _integrity_block(
        self,
        session: Session,
        *,
        attempt: TenantRegistrationAttempt,
        code: RedemptionCode,
        tenant: Tenant,
        authority: RegistrationAuthorityFacts,
        anchors: _AnchorEvidence,
        database_now: datetime,
    ) -> RegistrationFinalizationResult:
        existing = session.scalar(
            sa.select(RegistrationIntegrityIncident)
            .where(
                RegistrationIntegrityIncident.attempt_uuid == attempt.id,
                RegistrationIntegrityIncident.state.in_(
                    ("open", "recovery_cleanup_pending")
                ),
            )
            .with_for_update()
        )
        if existing is None:
            existing = RegistrationIntegrityIncident(
                id=str(uuid4()),
                attempt_uuid=attempt.id,
                code_uuid=code.id,
                user_uuid=attempt.user_id,
                provisional_tenant_uuid=attempt.provisional_tenant_uuid,
                provisional_database_uuid=attempt.provisional_database_uuid,
                detected_attempt_status=attempt.status,
                detected_replacement_uuid=(attempt.superseded_by_replacement_uuid),
                provisioning_generation=(attempt.provisioning_execution_generation),
                presence_bitmap=anchors.presence_bitmap,
                presence_digest=anchors.presence_digest,
                current_recovery_run_uuid=str(authority.current_recovery_run_uuid),
                marker_generation=authority.marker_generation,
                state="open",
                resolution_source=None,
                evidence_policy_version=REGISTRATION_INTEGRITY_POLICY_VERSION,
                safe_evidence_reference=(f"registration-finalization/v1:{attempt.id}"),
                decision_digest=None,
                platform_audit_uuid=None,
                row_version=1,
                detected_at=database_now,
                resolved_at=None,
            )
            session.add(existing)
        if (
            attempt.status not in {"active", "integrity_blocked"}
            and attempt.registration_commit_uuid is None
        ):
            attempt.status = "integrity_blocked"
            attempt.provisioning_execution_generation += 1
            attempt.lease_owner = None
            attempt.lease_token = None
            attempt.lease_expires_at = None
            attempt.last_safe_error_code = "registration_anchor_mismatch"
            attempt.row_version += 1
            attempt.updated_at = database_now
        session.flush()
        return RegistrationFinalizationResult(
            attempt_uuid=UUID(attempt.id),
            status="integrity_blocked",
            registration_commit_uuid=None,
            membership_uuid=None,
            subscription_uuid=None,
            subscription_event_uuid=None,
            resulting_attempt_row_version=attempt.row_version,
            created=False,
            integrity_incident_uuid=UUID(existing.id),
        )


@dataclass(frozen=True, slots=True)
class _ReplayProvisionedAnchors:
    """Non-secret immutable provisioning fields needed by commit digests."""

    tenant_uuid: UUID
    database_uuid: UUID
    provisioning_generation: int
    schema_generation: int
    schema_digest: bytes
    database_identity_digest: bytes
    route_version: int
    initial_credential_generation: int
    dml_login_state_version: int


@dataclass(frozen=True, slots=True)
class _AnchorEvidence:
    attempt: TenantRegistrationAttempt
    code: RedemptionCode
    tenant: Tenant
    route: TenantDatabase
    commit: TenantRegistrationCommit | None
    membership: TenantMembership | None
    subscription: Subscription | None
    event: SubscriptionEvent | None
    plan: RegistrationFinalCommitPlan
    presence_bitmap: int
    presence_digest: bytes
    complete: bool
    has_partial: bool
    request_conflict: bool

    def result(self, *, created: bool) -> RegistrationFinalizationResult:
        if not self.complete or self.commit is None:
            raise RuntimeError("registration anchors are incomplete")
        return RegistrationFinalizationResult(
            attempt_uuid=UUID(self.attempt.id),
            status="active",
            registration_commit_uuid=UUID(self.commit.id),
            membership_uuid=UUID(self.commit.membership_uuid),
            subscription_uuid=UUID(self.commit.subscription_uuid),
            subscription_event_uuid=UUID(self.commit.subscription_event_uuid),
            resulting_attempt_row_version=self.attempt.row_version,
            created=created,
        )


def reservation_action_digest(**values: object) -> bytes:
    """Canonical SMS action digest for initial code reservation."""

    required = {
        "user_uuid",
        "code_lookup_hash",
        "attempt_uuid",
        "provisional_tenant_uuid",
        "provisional_database_uuid",
        "requested_tenant_name",
        "idempotency_key",
        "expected_code_row_version",
        "current_recovery_run_uuid",
    }
    if set(values) != required:
        raise ValueError("reservation action fields are incomplete")
    return _canonical_digest(
        operation=REGISTRATION_RESERVATION_REVISION,
        **values,
    )


def retry_action_digest(**values: object) -> bytes:
    """Canonical SMS action digest for one failed-attempt generation advance."""

    required = {
        "attempt_uuid",
        "user_uuid",
        "canonical_phone",
        "phone_normalization_version",
        "expected_attempt_row_version",
        "expected_provisioning_generation",
        "expected_code_row_version",
        "lease_owner",
        "lease_token",
        "lease_expires_at",
        "current_recovery_run_uuid",
    }
    if set(values) != required:
        raise ValueError("retry action fields are incomplete")
    return _canonical_digest(
        operation=REGISTRATION_RETRY_REVISION,
        **values,
    )


def _read_anchor_evidence(
    session: Session,
    *,
    attempt: TenantRegistrationAttempt,
    tenant: Tenant,
    route: TenantDatabase,
    code: RedemptionCode,
    plan: RegistrationFinalCommitPlan,
    authority: RegistrationAuthorityFacts,
    provisioned: ProvisionedRegistrationFacts | _ReplayProvisionedAnchors,
    proof: TenantRegistrationProvisioningProof,
    expected_attempt_row_version: int,
    expected_code_row_version: int,
    lock: bool,
    replacements: tuple[RedemptionCodeReplacement, ...],
    incidents: tuple[RegistrationIntegrityIncident, ...],
    require_persisted_baseline: bool,
) -> _AnchorEvidence:
    commit_statement = sa.select(TenantRegistrationCommit).where(
        sa.or_(
            TenantRegistrationCommit.id == str(plan.registration_commit_uuid),
            TenantRegistrationCommit.attempt_uuid == attempt.id,
            TenantRegistrationCommit.code_uuid == code.id,
            TenantRegistrationCommit.tenant_uuid == tenant.id,
            TenantRegistrationCommit.database_uuid == route.database_uuid,
        )
    )
    if lock:
        commit_statement = commit_statement.with_for_update()
    commits = tuple(session.scalars(commit_statement))
    commit = commits[0] if len(commits) == 1 else None

    if commit is None:
        membership_predicate = sa.or_(
            TenantMembership.id == str(plan.membership_uuid),
            TenantMembership.registration_commit_uuid
            == str(plan.registration_commit_uuid),
            sa.and_(
                TenantMembership.tenant_id == tenant.id,
                TenantMembership.user_id == attempt.user_id,
                TenantMembership.source_type == "registration",
            ),
        )
        subscription_predicate = sa.or_(
            Subscription.id == str(plan.subscription_uuid),
            Subscription.created_from_registration_commit_uuid
            == str(plan.registration_commit_uuid),
            Subscription.tenant_id == tenant.id,
        )
        event_predicate = sa.or_(
            SubscriptionEvent.id == str(plan.subscription_event_uuid),
            SubscriptionEvent.source_uuid == str(plan.registration_commit_uuid),
            SubscriptionEvent.idempotency_key == plan.idempotency_key,
            SubscriptionEvent.consumed_code_uuid == code.id,
        )
    else:
        membership_predicate = sa.or_(
            TenantMembership.id == commit.membership_uuid,
            TenantMembership.registration_commit_uuid == commit.id,
        )
        subscription_predicate = sa.or_(
            Subscription.id == commit.subscription_uuid,
            Subscription.created_from_registration_commit_uuid == commit.id,
        )
        event_predicate = sa.or_(
            SubscriptionEvent.id == commit.subscription_event_uuid,
            SubscriptionEvent.source_uuid == commit.id,
        )
    membership = _one_anchor(
        session,
        sa.select(TenantMembership).where(membership_predicate),
        lock=lock,
    )
    subscription = _one_anchor(
        session,
        sa.select(Subscription).where(subscription_predicate),
        lock=lock,
    )
    event = _one_anchor(
        session,
        sa.select(SubscriptionEvent).where(event_predicate),
        lock=lock,
    )
    membership_present = bool(
        session.scalar(sa.select(sa.exists().where(membership_predicate)))
    )
    subscription_present = bool(
        session.scalar(sa.select(sa.exists().where(subscription_predicate)))
    )
    event_present = bool(session.scalar(sa.select(sa.exists().where(event_predicate))))

    baseline_statement = (
        sa.select(TenantRecoveryHold)
        .where(
            sa.or_(
                TenantRecoveryHold.created_from_registration_commit_uuid
                == str(plan.registration_commit_uuid),
                sa.and_(
                    TenantRecoveryHold.tenant_id == tenant.id,
                    TenantRecoveryHold.database_uuid == route.database_uuid,
                    TenantRecoveryHold.created_from_registration_commit_uuid.is_not(
                        None
                    ),
                ),
                *(
                    (TenantRecoveryHold.id == commit.released_hold_uuid,)
                    if commit is not None
                    else ()
                ),
            )
        )
        .order_by(TenantRecoveryHold.id)
    )
    if lock:
        baseline_statement = baseline_statement.with_for_update()
    baseline_holds = tuple(session.scalars(baseline_statement))
    baseline_hold = baseline_holds[0] if len(baseline_holds) == 1 else None

    flags = {
        "commit": bool(commits),
        "attempt": bool(
            attempt.status == "active" or attempt.registration_commit_uuid is not None
        ),
        "code": bool(
            code.status == "redeemed" or code.registration_commit_uuid is not None
        ),
        "tenant_publication": bool(
            tenant.status != "provisioning"
            or tenant.public_identity_published_at is not None
            or tenant.name is not None
            or tenant.slug is not None
        ),
        "route_activation": bool(
            route.status != "provisional"
            or route.activated_by_registration_commit_uuid is not None
            or route.activation_route_version is not None
            or route.activation_credential_generation is not None
        ),
        "membership": membership_present,
        "subscription": subscription_present,
        "event": event_present,
        "released_hold_baseline": bool(baseline_holds),
        "replacement": bool(replacements),
        "integrity_incident": bool(incidents),
    }
    bitmap = sum((1 << index) for index, value in enumerate(flags.values()) if value)
    presence_digest = _canonical_digest(
        attempt_uuid=attempt.id,
        code_uuid=code.id,
        tenant_uuid=tenant.id,
        database_uuid=route.database_uuid,
        planned_commit_uuid=str(plan.registration_commit_uuid),
        matches=flags,
        commit_ids=sorted(item.id for item in commits),
        membership_uuid=membership.id if membership is not None else None,
        subscription_uuid=subscription.id if subscription is not None else None,
        event_uuid=event.id if event is not None else None,
        route_activation_commit_uuid=(route.activated_by_registration_commit_uuid),
        route_activation_version=route.activation_route_version,
        route_activation_credential_generation=(route.activation_credential_generation),
        baseline_holds=[
            {
                "id": hold.id,
                "source": hold.created_from_registration_commit_uuid,
                "initial_revision": hold.initial_hold_revision,
            }
            for hold in baseline_holds
        ],
        replacement_ids=[item.id for item in replacements],
        incident_states=[{"id": item.id, "state": item.state} for item in incidents],
    )
    baseline_matches_commit = bool(
        commit is not None
        and baseline_hold is not None
        and len(baseline_holds) == 1
        and baseline_hold.id == commit.released_hold_uuid
        and baseline_hold.tenant_id == commit.tenant_uuid
        and baseline_hold.database_uuid == commit.database_uuid
        and baseline_hold.created_from_registration_commit_uuid == commit.id
        and baseline_hold.initial_hold_revision
        == commit.released_hold_revision_at_commit
    )
    baseline_complete = bool(
        baseline_matches_commit
        or (not require_persisted_baseline and not baseline_holds)
    )
    incident_lineage_complete = all(
        incident.state == "resolved_committed" for incident in incidents
    )
    commit_authority = (
        _historical_commit_authority(commit) if commit is not None else authority
    )
    core_storage_complete = bool(
        len(commits) == 1
        and commit is not None
        and membership is not None
        and subscription is not None
        and event is not None
        and commit.attempt_uuid == attempt.id
        and commit.code_uuid == code.id
        and commit.tenant_uuid == tenant.id
        and commit.database_uuid == route.database_uuid
        and commit.user_uuid == attempt.user_id
        and commit.recovery_run_uuid == proof.recovery_run_uuid
        and commit.provisioning_execution_generation_at_commit
        == provisioned.provisioning_generation
        and commit.schema_generation == provisioned.schema_generation
        and hmac.compare_digest(
            bytes(commit.database_identity_digest),
            provisioned.database_identity_digest,
        )
        and attempt.status == "active"
        and attempt.registration_commit_uuid == commit.id
        and code.status == "redeemed"
        and code.registration_commit_uuid == commit.id
        and code.redeemed_registration_attempt_uuid == attempt.id
        and code.redeemed_tenant_uuid == tenant.id
        and code.reserved_user_uuid == attempt.user_id
        and code.reserved_registration_attempt_uuid == attempt.id
        and tenant.status != "provisioning"
        and tenant.name is not None
        and tenant.slug is not None
        and tenant.public_identity_published_at is not None
        and route.status in {"ready", "retired"}
        and route.activated_by_registration_commit_uuid == commit.id
        and route.activation_route_version == commit.initial_route_version
        and route.activation_credential_generation
        == commit.initial_credential_generation
        and membership.id == commit.membership_uuid
        and membership.tenant_id == tenant.id
        and membership.user_id == attempt.user_id
        and membership.role_key == "admin"
        and membership.status in {"active", "disabled", "released"}
        and membership.source_type == "registration"
        and membership.source_uuid == commit.id
        and membership.registration_commit_uuid == commit.id
        and subscription.id == commit.subscription_uuid
        and subscription.tenant_id == tenant.id
        and subscription.created_from_registration_commit_uuid == commit.id
        and event.id == commit.subscription_event_uuid
        and event.subscription_id == subscription.id
        and event.tenant_id == tenant.id
        and event.source_type == "registration"
        and event.event_type == "activated"
        and event.after_status == "active"
        and event.source_uuid == commit.id
        and event.consumed_code_uuid == code.id
        and event.after_plan_revision_uuid == commit.plan_revision_uuid
        and hmac.compare_digest(
            bytes(event.after_entitlements_digest),
            bytes(commit.entitlements_digest),
        )
        and event.exact_duration_seconds == commit.service_duration_seconds
        and code.plan_revision_uuid == commit.plan_revision_uuid
        and code.entitlements_schema_version == commit.entitlements_schema_version
        and hmac.compare_digest(
            bytes(code.entitlements_digest),
            bytes(commit.entitlements_digest),
        )
        and code.service_duration_seconds == commit.service_duration_seconds
    )
    storage_complete = bool(
        core_storage_complete
        and baseline_complete
        and not replacements
        and incident_lineage_complete
    )
    request_matches = bool(
        storage_complete
        and commit.id == str(plan.registration_commit_uuid)
        and commit.membership_uuid == str(plan.membership_uuid)
        and commit.subscription_uuid == str(plan.subscription_uuid)
        and commit.subscription_event_uuid == str(plan.subscription_event_uuid)
        and commit.commit_policy_version == plan.commit_policy_version
        and hmac.compare_digest(
            bytes(commit.published_tenant_name_digest),
            _sha256_text(plan.published_tenant_name),
        )
        and hmac.compare_digest(
            bytes(commit.published_slug_digest),
            _sha256_text(plan.published_slug),
        )
        and event.idempotency_key == plan.idempotency_key
        and event.canonicalization_version == REGISTRATION_FINALIZATION_VERSION
        and hmac.compare_digest(
            bytes(event.request_digest),
            _final_request_digest(
                attempt=attempt,
                code=code,
                authority=commit_authority,
                provisioned=provisioned,
                proof=proof,
                plan=plan,
                expected_attempt_row_version=(expected_attempt_row_version),
                expected_code_row_version=expected_code_row_version,
            ),
        )
        and hmac.compare_digest(
            bytes(commit.entity_link_digest),
            _entity_link_digest(
                attempt=attempt,
                code=code,
                authority=commit_authority,
                provisioned=provisioned,
                proof=proof,
                plan=plan,
            ),
        )
    )
    return _AnchorEvidence(
        attempt=attempt,
        code=code,
        tenant=tenant,
        route=route,
        commit=commit,
        membership=membership,
        subscription=subscription,
        event=event,
        plan=plan,
        presence_bitmap=bitmap,
        presence_digest=presence_digest,
        complete=request_matches,
        has_partial=bool(bitmap and not core_storage_complete),
        request_conflict=bool(core_storage_complete and not request_matches),
    )


def _one_anchor(session: Session, statement, *, lock: bool):
    if lock:
        statement = statement.with_for_update()
    rows = tuple(session.scalars(statement))
    if len(rows) > 1:
        return None
    return rows[0] if rows else None


def _historical_commit_authority(
    commit: TenantRegistrationCommit,
) -> RegistrationAuthorityFacts:
    """Rebuild only immutable commit-time authority used by link digests."""

    try:
        return RegistrationAuthorityFacts(
            current_recovery_run_uuid=UUID(commit.recovery_run_uuid),
            recovery_run_completed=True,
            external_marker_matches=True,
            marker_generation=1,
            released_hold_uuid=UUID(commit.released_hold_uuid),
            released_hold_revision=commit.released_hold_revision_at_commit,
            released_hold_ready=True,
        )
    except (TypeError, ValueError):
        raise RegistrationConflictError() from None


def _require_exact_provisional_replay_state(
    *,
    attempt: TenantRegistrationAttempt,
    tenant: Tenant,
    route: TenantDatabase,
    code: RedemptionCode,
    proof: TenantRegistrationProvisioningProof,
    expected_attempt_row_version: int,
    expected_code_row_version: int,
    expected_provisioning_generation: int,
) -> None:
    """Permit ``None`` only for an intact, still-unpublished ready request."""

    if (
        attempt.status not in {"ready", "committing"}
        or attempt.row_version != expected_attempt_row_version
        or attempt.provisioning_execution_generation != expected_provisioning_generation
        or attempt.registration_commit_uuid is not None
        or attempt.superseded_by_replacement_uuid is not None
        or tenant.status != "provisioning"
        or tenant.name is not None
        or tenant.slug is not None
        or tenant.public_identity_published_at is not None
        or route.status != "provisional"
        or route.activated_by_registration_commit_uuid is not None
        or route.activation_route_version is not None
        or route.activation_credential_generation is not None
        or route.route_version != proof.route_version
        or route.dml_credential_generation != proof.initial_credential_generation
        or route.dml_login_state_version != proof.dml_login_state_version
        or code.status != "reserved"
        or code.row_version != expected_code_row_version
        or code.registration_commit_uuid is not None
        or code.redeemed_registration_attempt_uuid is not None
        or code.redeemed_tenant_uuid is not None
        or code.reserved_registration_attempt_uuid != attempt.id
        or code.reserved_user_uuid != attempt.user_id
    ):
        raise RegistrationConflictError()


def _positive_metadata_version(value: object) -> bool:
    """Reject bools and missing/non-positive published route metadata."""

    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _validated_code_snapshot(code: RedemptionCode):
    try:
        snapshot = parse_core_entitlements(
            schema_version=code.entitlements_schema_version,
            entitlements=code.entitlements_json,
        )
    except InvalidEntitlementSnapshotError:
        raise RegistrationCodeError() from None
    if (
        not hmac.compare_digest(
            snapshot.digest_sha256,
            bytes(code.entitlements_digest),
        )
        or code.service_duration_seconds < 1
    ):
        raise RegistrationCodeError()
    return snapshot


def _reservation_result(
    attempt: TenantRegistrationAttempt,
    *,
    created: bool,
) -> RegistrationReservationResult:
    return RegistrationReservationResult(
        attempt_uuid=UUID(attempt.id),
        user_uuid=UUID(attempt.user_id),
        code_uuid=UUID(attempt.redemption_code_id),
        tenant_uuid=UUID(attempt.provisional_tenant_uuid),
        database_uuid=UUID(attempt.provisional_database_uuid),
        status=attempt.status,
        provisioning_generation=attempt.provisioning_execution_generation,
        row_version=attempt.row_version,
        created=created,
    )


def _retry_result(
    attempt: TenantRegistrationAttempt,
    *,
    created: bool,
) -> RegistrationRetryResult:
    return RegistrationRetryResult(
        attempt_uuid=UUID(attempt.id),
        status=attempt.status,
        provisioning_generation=attempt.provisioning_execution_generation,
        row_version=attempt.row_version,
        created=created,
    )


def _provisioning_claim_result(
    attempt: TenantRegistrationAttempt,
    *,
    created: bool,
) -> RegistrationProvisioningClaimResult:
    return RegistrationProvisioningClaimResult(
        attempt_uuid=UUID(attempt.id),
        status=attempt.status,
        provisioning_generation=attempt.provisioning_execution_generation,
        row_version=attempt.row_version,
        created=created,
    )


def _database_ready_result(
    attempt: TenantRegistrationAttempt,
    proof: TenantRegistrationProvisioningProof,
    *,
    created: bool,
) -> RegistrationDatabaseReadyResult:
    return RegistrationDatabaseReadyResult(
        attempt_uuid=UUID(attempt.id),
        proof_uuid=UUID(proof.id),
        status=attempt.status,
        provisioning_generation=attempt.provisioning_execution_generation,
        row_version=attempt.row_version,
        created=created,
    )


def _provisioning_failure_result(
    attempt: TenantRegistrationAttempt,
    proof: TenantRegistrationProvisioningProof,
    *,
    created: bool,
) -> RegistrationProvisioningFailureResult:
    return RegistrationProvisioningFailureResult(
        attempt_uuid=UUID(attempt.id),
        proof_uuid=UUID(proof.id),
        status=attempt.status,
        provisioning_generation=attempt.provisioning_execution_generation,
        row_version=attempt.row_version,
        created=created,
    )


def _matching_worker_proof(
    proofs: tuple[TenantRegistrationProvisioningProof, ...],
    *,
    worker_lease_owner: str,
    worker_lease_token: str,
) -> TenantRegistrationProvisioningProof | None:
    digest = _worker_token_digest(worker_lease_token)
    matches = tuple(
        proof
        for proof in proofs
        if proof.worker_lease_owner == worker_lease_owner
        and hmac.compare_digest(
            bytes(proof.worker_lease_token_digest),
            digest,
        )
    )
    if len(matches) > 1:
        raise RegistrationConflictError()
    return matches[0] if matches else None


def _replay_provisioned_anchors(
    proof: TenantRegistrationProvisioningProof,
) -> _ReplayProvisionedAnchors:
    """Rebuild only non-secret fields persisted in an immutable ready proof."""

    if (
        proof.outcome != "ready"
        or proof.schema_generation is None
        or proof.schema_digest is None
        or proof.database_identity_digest is None
        or proof.route_version is None
        or proof.initial_credential_generation is None
        or proof.dml_login_state_version is None
    ):
        raise RegistrationConflictError()
    try:
        return _ReplayProvisionedAnchors(
            tenant_uuid=UUID(proof.tenant_uuid),
            database_uuid=UUID(proof.database_uuid),
            provisioning_generation=_positive(
                proof.provisioning_execution_generation,
                "proof provisioning_generation",
            ),
            schema_generation=_positive(
                proof.schema_generation,
                "proof schema_generation",
            ),
            schema_digest=_digest(
                bytes(proof.schema_digest),
                "proof schema_digest",
            ),
            database_identity_digest=_digest(
                bytes(proof.database_identity_digest),
                "proof database_identity_digest",
            ),
            route_version=_positive(
                proof.route_version,
                "proof route_version",
            ),
            initial_credential_generation=(
                _positive(
                    proof.initial_credential_generation,
                    "proof initial_credential_generation",
                )
            ),
            dml_login_state_version=_positive(
                proof.dml_login_state_version,
                "proof dml_login_state_version",
            ),
        )
    except (TypeError, ValueError):
        raise RegistrationConflictError() from None


def _database_ready_request_digest(
    *,
    attempt_uuid: str,
    expected_attempt_row_version: int,
    expected_provisioning_generation: int,
    expected_code_row_version: int,
    current_recovery_run_uuid: UUID,
    schema_operation_fence: RegistrationSchemaOperationFence,
    provisioned: ProvisionedRegistrationFacts,
) -> bytes:
    return _database_ready_canonical_digest(
        attempt_uuid=attempt_uuid,
        expected_attempt_row_version=expected_attempt_row_version,
        expected_provisioning_generation=expected_provisioning_generation,
        expected_code_row_version=expected_code_row_version,
        current_recovery_run_uuid=current_recovery_run_uuid,
        schema_claim_uuid=schema_operation_fence.claim_uuid,
        schema_owner_id=schema_operation_fence.owner_id,
        schema_generation=schema_operation_fence.generation,
        schema_fencing_token=schema_operation_fence.fencing_token,
        schema_row_version=schema_operation_fence.row_version,
        provisioned_digest=_provisioned_facts_digest(provisioned),
    )


def _database_ready_canonical_digest(
    *,
    attempt_uuid: str,
    expected_attempt_row_version: int,
    expected_provisioning_generation: int,
    expected_code_row_version: int,
    current_recovery_run_uuid: UUID,
    schema_claim_uuid: UUID,
    schema_owner_id: str,
    schema_generation: int,
    schema_fencing_token: int,
    schema_row_version: int,
    provisioned_digest: bytes,
) -> bytes:
    return _canonical_digest(
        operation="registration.database-ready.v1",
        attempt_uuid=attempt_uuid,
        expected_attempt_row_version=expected_attempt_row_version,
        expected_provisioning_generation=expected_provisioning_generation,
        expected_code_row_version=expected_code_row_version,
        current_recovery_run_uuid=current_recovery_run_uuid,
        schema_claim_uuid=schema_claim_uuid,
        schema_owner_id=schema_owner_id,
        schema_generation=schema_generation,
        schema_fencing_token=schema_fencing_token,
        schema_row_version=schema_row_version,
        provisioned_digest=provisioned_digest,
    )


def _require_ready_proof_integrity(
    proof: TenantRegistrationProvisioningProof,
    *,
    expected_code_row_version: int,
) -> None:
    """Re-authenticate a ready proof from its persisted immutable payload.

    The caller-provided digest is only an equality key.  Publication also
    rebuilds the original canonical database-ready request, including the
    worker-token digest, schema-operation fence, default warehouse, smoke and
    advisory-lock evidence.  Any field drift therefore fails closed.
    """

    try:
        if (
            proof.outcome != "ready"
            or proof.safe_error_code is not None
            or proof.proof_policy_version
            != REGISTRATION_PROVISIONING_PROOF_POLICY_VERSION
            or proof.schema_operation_claim_uuid is None
            or proof.schema_operation_owner_id is None
            or proof.schema_operation_generation is None
            or proof.schema_operation_fencing_token is None
            or proof.schema_operation_row_version is None
            or proof.schema_generation is None
            or proof.schema_digest is None
            or proof.database_identity_digest is None
            or proof.route_version is None
            or proof.initial_credential_generation is None
            or proof.dml_login_state_version is None
            or proof.default_warehouse_uuid is None
            or proof.default_warehouse_digest is None
            or proof.smoke_proof_digest is None
            or proof.advisory_lock_proof_digest is None
        ):
            raise RegistrationConflictError()
        provisioned_digest = _canonical_digest(
            tenant_uuid=_uuid(proof.tenant_uuid, "proof tenant_uuid"),
            database_uuid=_uuid(proof.database_uuid, "proof database_uuid"),
            provisioning_generation=_positive(
                proof.provisioning_execution_generation,
                "proof provisioning_generation",
            ),
            lease_owner=_token(proof.worker_lease_owner, "proof lease_owner"),
            lease_token_digest=_digest(
                bytes(proof.worker_lease_token_digest),
                "proof worker_lease_token_digest",
            ),
            schema_generation=_positive(
                proof.schema_generation,
                "proof schema_generation",
            ),
            schema_digest=_digest(
                bytes(proof.schema_digest),
                "proof schema_digest",
            ),
            database_identity_digest=_digest(
                bytes(proof.database_identity_digest),
                "proof database_identity_digest",
            ),
            route_version=_positive(proof.route_version, "proof route_version"),
            initial_credential_generation=_positive(
                proof.initial_credential_generation,
                "proof initial_credential_generation",
            ),
            dml_login_state_version=_positive(
                proof.dml_login_state_version,
                "proof dml_login_state_version",
            ),
            default_warehouse_uuid=_uuid(
                proof.default_warehouse_uuid,
                "proof default_warehouse_uuid",
            ),
            default_warehouse_digest=_digest(
                bytes(proof.default_warehouse_digest),
                "proof default_warehouse_digest",
            ),
            smoke_proof_digest=_digest(
                bytes(proof.smoke_proof_digest),
                "proof smoke_proof_digest",
            ),
            advisory_lock_proof_digest=_digest(
                bytes(proof.advisory_lock_proof_digest),
                "proof advisory_lock_proof_digest",
            ),
            backup_ddl_lease_held=True,
            database_advisory_lock_held=True,
            smoke_passed=True,
            business_route_unpublished=True,
        )
        rebuilt = _database_ready_canonical_digest(
            attempt_uuid=str(_uuid(proof.attempt_uuid, "proof attempt_uuid")),
            expected_attempt_row_version=_positive(
                proof.expected_attempt_row_version,
                "proof expected_attempt_row_version",
            ),
            expected_provisioning_generation=_positive(
                proof.provisioning_execution_generation,
                "proof provisioning_generation",
            ),
            expected_code_row_version=_positive(
                expected_code_row_version,
                "expected_code_row_version",
            ),
            current_recovery_run_uuid=_uuid(
                proof.recovery_run_uuid,
                "proof recovery_run_uuid",
            ),
            schema_claim_uuid=_uuid(
                proof.schema_operation_claim_uuid,
                "proof schema_operation_claim_uuid",
            ),
            schema_owner_id=_token(
                proof.schema_operation_owner_id,
                "proof schema_operation_owner_id",
            ),
            schema_generation=_positive(
                proof.schema_operation_generation,
                "proof schema_operation_generation",
            ),
            schema_fencing_token=_positive(
                proof.schema_operation_fencing_token,
                "proof schema_operation_fencing_token",
            ),
            schema_row_version=_positive(
                proof.schema_operation_row_version,
                "proof schema_operation_row_version",
            ),
            provisioned_digest=provisioned_digest,
        )
    except RegistrationConflictError:
        raise
    except (TypeError, ValueError):
        raise RegistrationConflictError() from None
    if not hmac.compare_digest(bytes(proof.result_request_digest), rebuilt):
        raise RegistrationConflictError()


def _provisioning_failure_request_digest(
    *,
    attempt_uuid: str,
    expected_attempt_row_version: int,
    expected_provisioning_generation: int,
    expected_code_row_version: int,
    lease_owner: str,
    lease_token: str,
    safe_error_code: str,
    current_recovery_run_uuid: UUID,
) -> bytes:
    return _canonical_digest(
        operation="registration.provisioning-failure.v1",
        attempt_uuid=attempt_uuid,
        expected_attempt_row_version=expected_attempt_row_version,
        expected_provisioning_generation=expected_provisioning_generation,
        expected_code_row_version=expected_code_row_version,
        lease_owner=lease_owner,
        lease_token_digest=_worker_token_digest(lease_token),
        safe_error_code=safe_error_code,
        current_recovery_run_uuid=current_recovery_run_uuid,
    )


def _provisioned_facts_digest(facts: ProvisionedRegistrationFacts) -> bytes:
    if not isinstance(facts, ProvisionedRegistrationFacts):
        raise TypeError("provisioned facts are invalid")
    return _canonical_digest(
        tenant_uuid=facts.tenant_uuid,
        database_uuid=facts.database_uuid,
        provisioning_generation=facts.provisioning_generation,
        lease_owner=facts.lease_owner,
        lease_token_digest=_worker_token_digest(facts.lease_token),
        schema_generation=facts.schema_generation,
        schema_digest=facts.schema_digest,
        database_identity_digest=facts.database_identity_digest,
        route_version=facts.route_version,
        initial_credential_generation=facts.initial_credential_generation,
        dml_login_state_version=facts.dml_login_state_version,
        default_warehouse_uuid=facts.default_warehouse_uuid,
        default_warehouse_digest=facts.default_warehouse_digest,
        smoke_proof_digest=facts.smoke_proof_digest,
        advisory_lock_proof_digest=facts.advisory_lock_proof_digest,
        backup_ddl_lease_held=facts.backup_ddl_lease_held,
        database_advisory_lock_held=facts.database_advisory_lock_held,
        smoke_passed=facts.smoke_passed,
        business_route_unpublished=facts.business_route_unpublished,
    )


def _worker_token_digest(token: str) -> bytes:
    selected = _token(token, "lease_token")
    return hashlib.sha256(
        _WORKER_TOKEN_DIGEST_DOMAIN + selected.encode("ascii")
    ).digest()


def _entity_link_digest(
    *,
    attempt: TenantRegistrationAttempt,
    code: RedemptionCode,
    authority: RegistrationAuthorityFacts,
    provisioned: ProvisionedRegistrationFacts | _ReplayProvisionedAnchors,
    proof: TenantRegistrationProvisioningProof,
    plan: RegistrationFinalCommitPlan,
) -> bytes:
    return _canonical_digest(
        attempt_uuid=attempt.id,
        user_uuid=attempt.user_id,
        code_uuid=code.id,
        tenant_uuid=str(provisioned.tenant_uuid),
        database_uuid=str(provisioned.database_uuid),
        registration_commit_uuid=str(plan.registration_commit_uuid),
        membership_uuid=str(plan.membership_uuid),
        subscription_uuid=str(plan.subscription_uuid),
        subscription_event_uuid=str(plan.subscription_event_uuid),
        recovery_run_uuid=str(authority.current_recovery_run_uuid),
        released_hold_uuid=str(authority.released_hold_uuid),
        released_hold_revision=authority.released_hold_revision,
        provisioning_generation=provisioned.provisioning_generation,
        schema_generation=provisioned.schema_generation,
        schema_digest=provisioned.schema_digest,
        database_identity_digest=provisioned.database_identity_digest,
        route_version=provisioned.route_version,
        credential_generation=provisioned.initial_credential_generation,
        dml_login_state_version=provisioned.dml_login_state_version,
        provisioning_proof_uuid=proof.id,
        provisioning_proof_request_digest=bytes(proof.result_request_digest),
        worker_lease_owner=proof.worker_lease_owner,
        worker_lease_token_digest=bytes(proof.worker_lease_token_digest),
    )


def _final_request_digest(
    *,
    attempt: TenantRegistrationAttempt,
    code: RedemptionCode,
    authority: RegistrationAuthorityFacts,
    provisioned: ProvisionedRegistrationFacts | _ReplayProvisionedAnchors,
    proof: TenantRegistrationProvisioningProof,
    plan: RegistrationFinalCommitPlan,
    expected_attempt_row_version: int,
    expected_code_row_version: int,
) -> bytes:
    return _canonical_digest(
        operation="registration.finalize.v1",
        attempt_uuid=attempt.id,
        code_uuid=code.id,
        code_row_version=expected_code_row_version,
        attempt_row_version=expected_attempt_row_version,
        recovery_run_uuid=str(authority.current_recovery_run_uuid),
        provisioned_link_digest=_entity_link_digest(
            attempt=attempt,
            code=code,
            authority=authority,
            provisioned=provisioned,
            proof=proof,
            plan=plan,
        ),
        idempotency_key=plan.idempotency_key,
    )


def _canonical_digest(**values: object) -> bytes:
    def encode(value: object):
        if isinstance(value, bytes):
            return value.hex()
        if isinstance(value, UUID):
            return str(value)
        if isinstance(value, datetime):
            return _as_database_utc(value).isoformat()
        if isinstance(value, dict):
            return {key: encode(item) for key, item in sorted(value.items())}
        if isinstance(value, (list, tuple)):
            return [encode(item) for item in value]
        if isinstance(value, (str, int, bool)) or value is None:
            return value
        raise TypeError("registration digest value is invalid")

    encoded = {key: encode(value) for key, value in sorted(values.items())}
    payload = json.dumps(
        encoded,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(payload).digest()


def _read_database_utc_now(session: Session) -> datetime:
    dialect_name = session.get_bind().dialect.name
    statement = _database_utc_now_statement(dialect_name)
    return _as_database_utc(session.scalar(statement))


def _database_utc_now_statement(dialect_name: str):
    if dialect_name not in {"mysql", "mariadb"}:
        raise RegistrationTransactionError()
    # CURRENT_TIMESTAMP follows the connection/session timezone and defaults
    # to second precision. Registration fences require one server UTC clock
    # with microsecond fidelity.
    return sa.text("SELECT UTC_TIMESTAMP(6)")


def _as_database_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RegistrationTransactionError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _uuid(value: object, field_name: str) -> UUID:
    if isinstance(value, UUID):
        return value
    if isinstance(value, str):
        try:
            parsed = UUID(value)
        except ValueError:
            pass
        else:
            if str(parsed) == value.lower():
                return parsed
    raise ValueError(f"{field_name} is invalid")


def _positive(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _digest(value: object, field_name: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError(f"{field_name} must be a 32-byte digest")
    return value


def _lookup_hash(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise RegistrationCodeError()
    return value


def _token(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SAFE_TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field_name} is invalid")
    return value


def _safe_error_code(value: object) -> str:
    if not isinstance(value, str) or _SAFE_ERROR_CODE.fullmatch(value) is None:
        raise ValueError("safe_error_code is invalid")
    return value


def _tenant_name(value: object) -> str:
    if not isinstance(value, str):
        raise ValueError("tenant name is invalid")
    normalized = value.strip()
    if not normalized or len(normalized) > 255:
        raise ValueError("tenant name is invalid")
    return normalized


def _slug(value: object) -> str:
    if not isinstance(value, str) or _SLUG.fullmatch(value) is None:
        raise ValueError("tenant slug is invalid")
    return value


def _idempotency_key(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 128
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError("idempotency_key is invalid")
    return value


def _sha256_text(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


def _require_clean_caller_transaction(session: Session) -> None:
    require_caller_transaction(
        session,
        RegistrationTransactionError,
        invalid_session_error=RegistrationTransactionError,
        clean=True,
    )
