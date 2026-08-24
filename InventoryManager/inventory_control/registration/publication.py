"""Fenced final publication of an already-ready registration tenant.

This boundary deliberately does not create or bootstrap a tenant schema.  It
accepts only an immutable ready proof already persisted by registration
provisioning.  Before a first publication, that proof's schema-operation claim
must still be the same uninterrupted claim (ordinary row-version renewal is
allowed).  The service reacquires the database-scoped advisory lock and
delegates the all-or-nothing control-plane publication to an injected final-
commit port.  An exact already-committed replay does not republish or depend on
the historical proof fence still being leased.

No DSN, password, tenant schema name, tenant-database connection, or provider
client crosses this module.  The concrete final-commit adapter owns only one
control-database transaction.  A failed or response-unknown final commit is
resolved by a locking current-read observation: either the exact registration
commit is complete or the route remains unpublished.  A partial state is
always fail-closed.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Final, Protocol
from uuid import UUID

from inventory_control.database import ControlDatabase

from .persistence import (
    REGISTRATION_PROVISIONING_PROOF_POLICY_VERSION,
    ProvisionedRegistrationFacts,
    RegistrationConflictError,
    RegistrationFinalCommitPlan,
    RegistrationFinalizationResult,
    RegistrationPersistenceError,
    RegistrationPersistenceService,
    RegistrationSchemaOperationFence,
)


REGISTRATION_FINAL_PUBLICATION_PROTOCOL_VERSION: Final = 2
_DIGEST_BYTES: Final = 32
_SAFE_ID: Final = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}", re.ASCII)
_SAFE_TOKEN: Final = re.compile(r"[A-Za-z0-9._:/+-]{1,128}", re.ASCII)
_AUTHORITY_DOMAIN: Final = b"inventory-manager/registration-publication/v2\x00"


class RegistrationFinalPublicationError(RuntimeError):
    """Stable publication failure without endpoint or credential details."""

    code = "REGISTRATION_FINAL_PUBLICATION_FAILED"

    def __init__(self) -> None:
        super().__init__(self.code)


class RegistrationFinalPublicationInputError(RegistrationFinalPublicationError):
    code = "REGISTRATION_FINAL_PUBLICATION_INPUT_INVALID"


class RegistrationFinalPublicationFenceError(RegistrationFinalPublicationError):
    code = "REGISTRATION_FINAL_PUBLICATION_FENCE_REJECTED"


class RegistrationFinalPublicationUnpublished(
    RegistrationFinalPublicationError
):
    code = "REGISTRATION_FINAL_PUBLICATION_REMAINED_UNPUBLISHED"


class RegistrationFinalPublicationInvariantError(
    RegistrationFinalPublicationError
):
    code = "REGISTRATION_FINAL_PUBLICATION_INVARIANT_VIOLATION"


class RegistrationFinalPublicationReleaseError(
    RegistrationFinalPublicationError
):
    code = "REGISTRATION_FINAL_PUBLICATION_LOCK_RELEASE_FAILED"


class ReadyPublicationState(str, Enum):
    PROVISIONAL_READY = "provisional_ready"
    COMMITTED = "committed"


class PublicationObservationState(str, Enum):
    UNPUBLISHED = "unpublished"
    COMMITTED = "committed"
    INCONSISTENT = "inconsistent"


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class RegistrationFinalPublicationRequest:
    """Non-secret job input bound to one immutable ready proof."""

    attempt_uuid: UUID
    tenant_uuid: UUID
    database_uuid: UUID
    current_recovery_run_uuid: UUID
    provisioning_generation: int
    expected_attempt_row_version: int
    expected_code_row_version: int
    ready_proof_uuid: UUID
    ready_proof_request_digest: bytes
    lock_idempotency_key: str
    plan: RegistrationFinalCommitPlan
    protocol_version: int = REGISTRATION_FINAL_PUBLICATION_PROTOCOL_VERSION

    def __post_init__(self) -> None:
        for value in (
            self.attempt_uuid,
            self.tenant_uuid,
            self.database_uuid,
            self.current_recovery_run_uuid,
            self.ready_proof_uuid,
        ):
            _uuid(value)
        if len(
            {
                self.attempt_uuid,
                self.tenant_uuid,
                self.database_uuid,
                self.current_recovery_run_uuid,
                self.ready_proof_uuid,
            }
        ) != 5:
            raise RegistrationFinalPublicationInputError()
        for value in (
            self.provisioning_generation,
            self.expected_attempt_row_version,
            self.expected_code_row_version,
        ):
            _positive(value)
        _digest(self.ready_proof_request_digest)
        _safe_id(self.lock_idempotency_key)
        if not isinstance(self.plan, RegistrationFinalCommitPlan):
            raise RegistrationFinalPublicationInputError()
        if self.protocol_version != REGISTRATION_FINAL_PUBLICATION_PROTOCOL_VERSION:
            raise RegistrationFinalPublicationInputError()

    def __repr__(self) -> str:
        return (
            "RegistrationFinalPublicationRequest("
            f"attempt_uuid={self.attempt_uuid!s}, "
            f"ready_proof_uuid={self.ready_proof_uuid!s}, "
            "authority='<committed>')"
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class ProvisionalTenantEndpoint:
    """Safe control projection; it contains no database locator or secret."""

    tenant_uuid: UUID
    database_uuid: UUID
    endpoint_identity_digest: bytes
    route_version: int
    initial_credential_generation: int
    dml_login_state_version: int
    status: str
    activated_by_registration_commit_uuid: UUID | None

    def __post_init__(self) -> None:
        _uuid(self.tenant_uuid)
        _uuid(self.database_uuid)
        _digest(self.endpoint_identity_digest)
        for value in (
            self.route_version,
            self.initial_credential_generation,
            self.dml_login_state_version,
        ):
            _positive(value)
        if self.status not in {"provisional", "ready"}:
            raise RegistrationFinalPublicationInputError()
        if self.activated_by_registration_commit_uuid is not None:
            _uuid(self.activated_by_registration_commit_uuid)
        if (self.status == "provisional") != (
            self.activated_by_registration_commit_uuid is None
        ):
            raise RegistrationFinalPublicationInputError()

    def __repr__(self) -> str:
        return (
            "ProvisionalTenantEndpoint("
            f"database_uuid={self.database_uuid!s}, status={self.status!r}, "
            "locator='<redacted>')"
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class PersistedTenantReadyProof:
    """Immutable proof projection; bootstrap internals stay outside this API."""

    proof_uuid: UUID
    request_digest: bytes
    tenant_uuid: UUID
    database_uuid: UUID
    provisioning_generation: int
    schema_generation: int
    schema_digest: bytes
    database_identity_digest: bytes
    smoke_proof_digest: bytes
    advisory_lock_proof_digest: bytes
    recorded_schema_fence: RegistrationSchemaOperationFence
    proof_policy_version: int

    def __post_init__(self) -> None:
        for value in (self.proof_uuid, self.tenant_uuid, self.database_uuid):
            _uuid(value)
        for value in (
            self.request_digest,
            self.schema_digest,
            self.database_identity_digest,
            self.smoke_proof_digest,
            self.advisory_lock_proof_digest,
        ):
            _digest(value)
        _positive(self.provisioning_generation)
        _positive(self.schema_generation)
        if not isinstance(
            self.recorded_schema_fence,
            RegistrationSchemaOperationFence,
        ):
            raise RegistrationFinalPublicationInputError()
        if (
            self.proof_policy_version
            != REGISTRATION_PROVISIONING_PROOF_POLICY_VERSION
        ):
            raise RegistrationFinalPublicationInputError()

    def __repr__(self) -> str:
        return (
            "PersistedTenantReadyProof("
            f"proof_uuid={self.proof_uuid!s}, digests='<sha256>')"
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class GlobalSchemaPublicationFenceHandle:
    """A current global lease explicitly bound to this publication request."""

    schema_operation_fence: RegistrationSchemaOperationFence
    purpose: str
    request_binding_digest: bytes

    def __post_init__(self) -> None:
        if not isinstance(
            self.schema_operation_fence,
            RegistrationSchemaOperationFence,
        ):
            raise RegistrationFinalPublicationInputError()
        if self.purpose != "provisioning":
            raise RegistrationFinalPublicationInputError()
        _digest(self.request_binding_digest)

    @property
    def claim_uuid(self) -> UUID:
        return self.schema_operation_fence.claim_uuid

    @property
    def fencing_token(self) -> int:
        return self.schema_operation_fence.fencing_token

    def __repr__(self) -> str:
        return (
            "GlobalSchemaPublicationFenceHandle("
            "purpose='provisioning', fence='<redacted>')"
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class RegistrationFinalPublicationAuthority:
    """Locking current-read result immediately before final publication."""

    state: ReadyPublicationState
    attempt_uuid: UUID
    tenant_uuid: UUID
    database_uuid: UUID
    current_recovery_run_uuid: UUID
    provisioning_generation: int
    attempt_row_version: int
    code_row_version: int
    tenant_status: str
    attempt_status: str
    endpoint: ProvisionalTenantEndpoint
    ready_proof: PersistedTenantReadyProof
    provisioned: ProvisionedRegistrationFacts = field(repr=False)
    existing_registration_commit_uuid: UUID | None = None

    def __post_init__(self) -> None:
        try:
            state = ReadyPublicationState(self.state)
        except (TypeError, ValueError):
            raise RegistrationFinalPublicationInputError() from None
        object.__setattr__(self, "state", state)
        for value in (
            self.attempt_uuid,
            self.tenant_uuid,
            self.database_uuid,
            self.current_recovery_run_uuid,
        ):
            _uuid(value)
        for value in (
            self.provisioning_generation,
            self.attempt_row_version,
            self.code_row_version,
        ):
            _positive(value)
        if not isinstance(self.endpoint, ProvisionalTenantEndpoint):
            raise RegistrationFinalPublicationInputError()
        if not isinstance(self.ready_proof, PersistedTenantReadyProof):
            raise RegistrationFinalPublicationInputError()
        if not isinstance(self.provisioned, ProvisionedRegistrationFacts):
            raise RegistrationFinalPublicationInputError()
        if self.existing_registration_commit_uuid is not None:
            _uuid(self.existing_registration_commit_uuid)
        if state is ReadyPublicationState.PROVISIONAL_READY:
            if (
                self.tenant_status != "provisioning"
                or self.attempt_status not in {"ready", "committing"}
                or self.endpoint.status != "provisional"
                or self.existing_registration_commit_uuid is not None
            ):
                raise RegistrationFinalPublicationInputError()
        elif (
            self.tenant_status != "active"
            or self.attempt_status != "active"
            or self.endpoint.status != "ready"
            or self.existing_registration_commit_uuid is None
            or self.endpoint.activated_by_registration_commit_uuid
            != self.existing_registration_commit_uuid
        ):
            raise RegistrationFinalPublicationInputError()

    @property
    def digest(self) -> bytes:
        payload = {
            "attempt_row_version": self.attempt_row_version,
            "attempt_status": self.attempt_status,
            "attempt_uuid": str(self.attempt_uuid),
            "code_row_version": self.code_row_version,
            "database_uuid": str(self.database_uuid),
            "endpoint_identity_digest": self.endpoint.endpoint_identity_digest.hex(),
            "endpoint_status": self.endpoint.status,
            "existing_registration_commit_uuid": (
                None
                if self.existing_registration_commit_uuid is None
                else str(self.existing_registration_commit_uuid)
            ),
            "provisioning_generation": self.provisioning_generation,
            "ready_proof_request_digest": self.ready_proof.request_digest.hex(),
            "ready_proof_uuid": str(self.ready_proof.proof_uuid),
            "recovery_run_uuid": str(self.current_recovery_run_uuid),
            "state": self.state.value,
            "tenant_status": self.tenant_status,
            "tenant_uuid": str(self.tenant_uuid),
            "worker_lease_token_digest": _worker_token_digest(
                self.provisioned.lease_token
            ).hex(),
        }
        return hashlib.sha256(_AUTHORITY_DOMAIN + _canonical_json(payload)).digest()

    def __repr__(self) -> str:
        return (
            "RegistrationFinalPublicationAuthority("
            f"state={self.state.value!r}, authority_digest={self.digest.hex()!r}, "
            "endpoint='<redacted>', worker_fence='<redacted>')"
        )


@dataclass(frozen=True, slots=True, repr=False, kw_only=True)
class DatabaseAdvisoryLockHandle:
    database_uuid: UUID
    owner_id: str
    lock_key_sha256: bytes
    acquisition_proof_digest: bytes
    schema_claim_uuid: UUID
    schema_fencing_token: int

    def __post_init__(self) -> None:
        _uuid(self.database_uuid)
        _uuid(self.schema_claim_uuid)
        _safe_id(self.owner_id)
        _digest(self.lock_key_sha256)
        _digest(self.acquisition_proof_digest)
        _positive(self.schema_fencing_token)

    def __repr__(self) -> str:
        return (
            "DatabaseAdvisoryLockHandle("
            f"database_uuid={self.database_uuid!s}, held=True, "
            "lock_identity='<sha256>')"
        )


@dataclass(frozen=True, slots=True, kw_only=True)
class RegistrationPublicationObservation:
    state: PublicationObservationState
    attempt_uuid: UUID
    tenant_uuid: UUID
    database_uuid: UUID
    ready_proof_uuid: UUID
    ready_proof_request_digest: bytes
    route_status: str
    tenant_status: str
    attempt_status: str
    registration_commit_uuid: UUID | None
    route_activation_commit_uuid: UUID | None

    def __post_init__(self) -> None:
        try:
            state = PublicationObservationState(self.state)
        except (TypeError, ValueError):
            raise RegistrationFinalPublicationInputError() from None
        object.__setattr__(self, "state", state)
        for value in (
            self.attempt_uuid,
            self.tenant_uuid,
            self.database_uuid,
            self.ready_proof_uuid,
        ):
            _uuid(value)
        _digest(self.ready_proof_request_digest)
        if self.registration_commit_uuid is not None:
            _uuid(self.registration_commit_uuid)
        if self.route_activation_commit_uuid is not None:
            _uuid(self.route_activation_commit_uuid)
        if state is PublicationObservationState.COMMITTED:
            if (
                self.route_status != "ready"
                or self.tenant_status != "active"
                or self.attempt_status != "active"
                or self.registration_commit_uuid is None
                or self.route_activation_commit_uuid
                != self.registration_commit_uuid
            ):
                raise RegistrationFinalPublicationInputError()
        elif state is PublicationObservationState.UNPUBLISHED:
            if (
                self.route_status != "provisional"
                or self.tenant_status != "provisioning"
                or self.attempt_status
                not in {
                    "ready",
                    "committing",
                    "identity_conflict",
                    "security_blocked",
                    "integrity_blocked",
                }
                or self.registration_commit_uuid is not None
                or self.route_activation_commit_uuid is not None
            ):
                raise RegistrationFinalPublicationInputError()


@dataclass(frozen=True, slots=True)
class RegistrationFinalPublicationResult:
    attempt_uuid: UUID
    tenant_uuid: UUID
    database_uuid: UUID
    status: str
    route_published: bool
    registration_commit_uuid: UUID | None
    ready_proof_uuid: UUID
    finalization_created: bool
    reconciled_after_unknown: bool
    integrity_incident_uuid: UUID | None = None


class GlobalSchemaPublicationFencePort(Protocol):
    """Acquire/revalidate/release the persisted provisioning-purpose mutex."""

    def acquire(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
    ) -> GlobalSchemaPublicationFenceHandle: ...

    def require_current(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
    ) -> None: ...

    def require_current_in_transaction(
        self,
        *,
        control_transaction: object,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
    ) -> None:
        """Lock/current-read the fence inside the final control transaction.

        The implementation must use ``control_transaction`` for the read/CAS
        and retain that row lock through the transaction commit.  A separate
        preflight transaction does not satisfy this contract.
        """
        ...

    def release(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
    ) -> None: ...


class DatabaseAdvisoryPublicationLockPort(Protocol):
    """Own the MySQL lock keyed only by the immutable database UUID."""

    def acquire(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        schema_fence: GlobalSchemaPublicationFenceHandle,
    ) -> DatabaseAdvisoryLockHandle: ...

    def require_current(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        schema_fence: GlobalSchemaPublicationFenceHandle,
        advisory_lock: DatabaseAdvisoryLockHandle,
    ) -> None: ...

    def release(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        schema_fence: GlobalSchemaPublicationFenceHandle,
        advisory_lock: DatabaseAdvisoryLockHandle,
    ) -> None: ...


class RegistrationReadyPublicationCurrentRead(Protocol):
    """Lock control rows and rebuild authority from the persisted ready proof."""

    def __call__(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        schema_fence: GlobalSchemaPublicationFenceHandle,
        advisory_lock: DatabaseAdvisoryLockHandle,
    ) -> RegistrationFinalPublicationAuthority: ...


class RegistrationCommittedPublicationCurrentRead(Protocol):
    """Current-read exact immutable final anchors before acquiring live locks.

    ``None`` means that the exact ready request has no publication footprint.
    Implementations MUST fail closed for partial anchors or any request drift;
    they must never translate those states to ``None``.
    """

    def __call__(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
    ) -> RegistrationFinalizationResult | None: ...


class RegistrationFinalCommitFenceCurrentRead(Protocol):
    """Mandatory one-shot fence read owned by the final control transaction."""

    def __call__(self, *, control_transaction: object) -> None: ...


class RegistrationAtomicFinalCommitPort(Protocol):
    """Run ``finalize_registration`` in one caller-owned control transaction.

    The implementation must invoke ``fence_current_read`` with that same open
    transaction after acquiring its normal control-row locks and before any
    finalization mutation.  It must not catch a failure from that callback or
    commit in another transaction.
    """

    def finalize(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        authority: RegistrationFinalPublicationAuthority,
        schema_fence: GlobalSchemaPublicationFenceHandle,
        advisory_lock: DatabaseAdvisoryLockHandle,
        fence_current_read: RegistrationFinalCommitFenceCurrentRead,
    ) -> RegistrationFinalizationResult: ...


class RegistrationPersistenceAtomicFinalCommitPort:
    """Commit through the real persistence service in one owned transaction.

    The persistence service owns the normal registration lock order and calls
    the guarded fence current-read at the sole pre-mutation insertion point.
    This adapter additionally verifies that callback completed before leaving
    ``ControlDatabase.transaction()``; an omitted callback therefore rolls the
    transaction back instead of being detected after publication committed.
    """

    __slots__ = ("_control_database", "_persistence")

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        persistence: RegistrationPersistenceService,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise RegistrationFinalPublicationInputError()
        if not isinstance(persistence, RegistrationPersistenceService):
            raise RegistrationFinalPublicationInputError()
        self._control_database = control_database
        self._persistence = persistence

    def finalize(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        authority: RegistrationFinalPublicationAuthority,
        schema_fence: GlobalSchemaPublicationFenceHandle,
        advisory_lock: DatabaseAdvisoryLockHandle,
        fence_current_read: RegistrationFinalCommitFenceCurrentRead,
    ) -> RegistrationFinalizationResult:
        if (
            not isinstance(request, RegistrationFinalPublicationRequest)
            or not isinstance(authority, RegistrationFinalPublicationAuthority)
            or not isinstance(schema_fence, GlobalSchemaPublicationFenceHandle)
            or not isinstance(advisory_lock, DatabaseAdvisoryLockHandle)
            or not callable(fence_current_read)
        ):
            raise RegistrationFinalPublicationInputError()
        _require_authority_matches(request, authority, schema_fence)
        if (
            advisory_lock.database_uuid != request.database_uuid
            or advisory_lock.schema_claim_uuid != schema_fence.claim_uuid
            or advisory_lock.schema_fencing_token != schema_fence.fencing_token
        ):
            raise RegistrationFinalPublicationFenceError()

        with self._control_database.transaction() as control_transaction:
            guarded_fence_read = _PersistenceFinalFenceCurrentRead(
                expected_control_transaction=control_transaction,
                delegate=fence_current_read,
            )
            result = self._persistence.finalize_registration(
                control_transaction,
                attempt_uuid=request.attempt_uuid,
                expected_attempt_row_version=(
                    request.expected_attempt_row_version
                ),
                expected_code_row_version=request.expected_code_row_version,
                current_recovery_run_uuid=request.current_recovery_run_uuid,
                provisioned=authority.provisioned,
                plan=request.plan,
                fence_current_read=guarded_fence_read,
            )
            if (
                not guarded_fence_read.completed
                or not isinstance(result, RegistrationFinalizationResult)
            ):
                raise RegistrationFinalPublicationInvariantError()
            return result


class RegistrationPersistenceCommittedPublicationCurrentRead:
    """Read an exact committed replay in one control-database transaction."""

    __slots__ = ("_control_database", "_persistence")

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        persistence: RegistrationPersistenceService,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise RegistrationFinalPublicationInputError()
        if not isinstance(persistence, RegistrationPersistenceService):
            raise RegistrationFinalPublicationInputError()
        self._control_database = control_database
        self._persistence = persistence

    def __call__(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
    ) -> RegistrationFinalizationResult | None:
        if not isinstance(request, RegistrationFinalPublicationRequest):
            raise RegistrationFinalPublicationInputError()
        try:
            with self._control_database.transaction() as control_transaction:
                result = self._persistence.read_finalization_replay(
                    control_transaction,
                    attempt_uuid=request.attempt_uuid,
                    tenant_uuid=request.tenant_uuid,
                    database_uuid=request.database_uuid,
                    expected_attempt_row_version=(
                        request.expected_attempt_row_version
                    ),
                    expected_code_row_version=request.expected_code_row_version,
                    current_recovery_run_uuid=(
                        request.current_recovery_run_uuid
                    ),
                    provisioning_generation=request.provisioning_generation,
                    ready_proof_uuid=request.ready_proof_uuid,
                    ready_proof_request_digest=(
                        request.ready_proof_request_digest
                    ),
                    plan=request.plan,
                )
        except RegistrationConflictError:
            raise RegistrationFinalPublicationInvariantError() from None
        except RegistrationPersistenceError:
            raise RegistrationFinalPublicationFenceError() from None
        except RegistrationFinalPublicationError:
            raise
        except Exception:
            raise RegistrationFinalPublicationFenceError() from None
        if result is not None and not isinstance(
            result,
            RegistrationFinalizationResult,
        ):
            raise RegistrationFinalPublicationInvariantError()
        return result


class RegistrationPublicationCurrentObservation(Protocol):
    """Resolve response loss as exact committed, unpublished, or inconsistent."""

    def __call__(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        authority: RegistrationFinalPublicationAuthority,
        schema_fence: GlobalSchemaPublicationFenceHandle,
        advisory_lock: DatabaseAdvisoryLockHandle,
    ) -> RegistrationPublicationObservation: ...


class RegistrationFinalPublicationService:
    """Publish only after current ready proof and both external fences agree."""

    __slots__ = (
        "_advisory_locks",
        "_committed_current_read",
        "_current_observation",
        "_final_commit",
        "_global_fences",
        "_ready_current_read",
    )

    def __init__(
        self,
        *,
        global_fences: GlobalSchemaPublicationFencePort,
        advisory_locks: DatabaseAdvisoryPublicationLockPort,
        committed_current_read: RegistrationCommittedPublicationCurrentRead,
        ready_current_read: RegistrationReadyPublicationCurrentRead,
        final_commit: RegistrationAtomicFinalCommitPort,
        current_observation: RegistrationPublicationCurrentObservation,
    ) -> None:
        for value, methods in (
            (
                global_fences,
                (
                    "acquire",
                    "require_current",
                    "require_current_in_transaction",
                    "release",
                ),
            ),
            (advisory_locks, ("acquire", "require_current", "release")),
            (final_commit, ("finalize",)),
        ):
            if any(not callable(getattr(value, method, None)) for method in methods):
                raise RegistrationFinalPublicationInputError()
        if (
            not callable(committed_current_read)
            or not callable(ready_current_read)
            or not callable(current_observation)
        ):
            raise RegistrationFinalPublicationInputError()
        self._global_fences = global_fences
        self._advisory_locks = advisory_locks
        self._committed_current_read = committed_current_read
        self._ready_current_read = ready_current_read
        self._final_commit = final_commit
        self._current_observation = current_observation

    def publish(
        self,
        request: RegistrationFinalPublicationRequest,
    ) -> RegistrationFinalPublicationResult:
        if not isinstance(request, RegistrationFinalPublicationRequest):
            raise RegistrationFinalPublicationInputError()
        replay = self._read_committed_replay(request)
        if replay is not None:
            return _result_from_committed_replay(
                request=request,
                finalization=replay,
                reconciled_after_unknown=False,
            )
        fence: GlobalSchemaPublicationFenceHandle | None = None
        advisory: DatabaseAdvisoryLockHandle | None = None
        authority: RegistrationFinalPublicationAuthority | None = None
        pending_error: Exception | None = None
        result: RegistrationFinalPublicationResult | None = None
        try:
            fence = self._acquire_global_fence(request)
            self._validate_global_fence(request, fence)
            self._require_global_fence(request, fence)
            advisory = self._acquire_advisory(request, fence)
            self._validate_advisory(request, fence, advisory)
            self._require_advisory(request, fence, advisory)
            self._require_global_fence(request, fence)
            authority = self._read_authority(request, fence, advisory)
            _require_authority_matches(request, authority, fence)
            self._require_advisory(request, fence, advisory)
            self._require_global_fence(request, fence)

            finalization: RegistrationFinalizationResult | None = None
            finalization_error: Exception | None = None
            final_fence_read = _FinalCommitFenceCurrentRead(
                request=request,
                fence=fence,
                global_fences=self._global_fences,
            )
            try:
                finalization = self._final_commit.finalize(
                    request=request,
                    authority=authority,
                    schema_fence=fence,
                    advisory_lock=advisory,
                    fence_current_read=final_fence_read,
                )
                if not isinstance(finalization, RegistrationFinalizationResult):
                    raise RegistrationFinalPublicationInvariantError()
            except Exception as error:
                finalization_error = error
                finalization = None

            observation = self._observe(
                request,
                authority,
                fence,
                advisory,
            )
            result = _resolve_publication(
                request=request,
                finalization=finalization,
                observation=observation,
                finalization_was_unknown=finalization_error is not None,
                final_fence_was_current=final_fence_read.completed,
            )
            if finalization_error is not None and not result.route_published:
                pending_error = RegistrationFinalPublicationUnpublished()
        except RegistrationFinalPublicationError as error:
            pending_error = error
        except Exception:
            pending_error = RegistrationFinalPublicationFenceError()

        release_error = _release_locks(
            request=request,
            fence=fence,
            advisory=advisory,
            global_fences=self._global_fences,
            advisory_locks=self._advisory_locks,
        )
        if release_error:
            raise RegistrationFinalPublicationReleaseError()
        if pending_error is not None:
            if isinstance(
                pending_error,
                (
                    RegistrationFinalPublicationFenceError,
                    RegistrationFinalPublicationUnpublished,
                ),
            ):
                replay = self._read_committed_replay(request)
                if replay is not None:
                    return _result_from_committed_replay(
                        request=request,
                        finalization=replay,
                        reconciled_after_unknown=True,
                    )
            raise pending_error
        if result is None:  # pragma: no cover - defensive invariant
            raise RegistrationFinalPublicationInvariantError()
        return result

    def _read_committed_replay(
        self,
        request: RegistrationFinalPublicationRequest,
    ) -> RegistrationFinalizationResult | None:
        try:
            result = self._committed_current_read(request=request)
        except RegistrationFinalPublicationError:
            raise
        except Exception:
            raise RegistrationFinalPublicationFenceError() from None
        if result is not None and not isinstance(
            result,
            RegistrationFinalizationResult,
        ):
            raise RegistrationFinalPublicationInvariantError()
        return result

    def _acquire_global_fence(
        self,
        request: RegistrationFinalPublicationRequest,
    ) -> GlobalSchemaPublicationFenceHandle:
        return self._global_fences.acquire(request=request)

    def _validate_global_fence(
        self,
        request: RegistrationFinalPublicationRequest,
        fence: object,
    ) -> None:
        if (
            not isinstance(fence, GlobalSchemaPublicationFenceHandle)
            or not hmac.compare_digest(
                fence.request_binding_digest,
                registration_publication_lock_binding_digest(request),
            )
        ):
            raise RegistrationFinalPublicationFenceError()

    def _require_global_fence(
        self,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
    ) -> None:
        self._global_fences.require_current(request=request, fence=fence)

    def _acquire_advisory(
        self,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
    ) -> DatabaseAdvisoryLockHandle:
        return self._advisory_locks.acquire(
            request=request,
            schema_fence=fence,
        )

    def _validate_advisory(
        self,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
        advisory: object,
    ) -> None:
        if (
            not isinstance(advisory, DatabaseAdvisoryLockHandle)
            or advisory.database_uuid != request.database_uuid
            or advisory.schema_claim_uuid != fence.claim_uuid
            or advisory.schema_fencing_token != fence.fencing_token
        ):
            raise RegistrationFinalPublicationFenceError()

    def _require_advisory(
        self,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
        advisory: DatabaseAdvisoryLockHandle,
    ) -> None:
        self._advisory_locks.require_current(
            request=request,
            schema_fence=fence,
            advisory_lock=advisory,
        )

    def _read_authority(
        self,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
        advisory: DatabaseAdvisoryLockHandle,
    ) -> RegistrationFinalPublicationAuthority:
        authority = self._ready_current_read(
            request=request,
            schema_fence=fence,
            advisory_lock=advisory,
        )
        if not isinstance(authority, RegistrationFinalPublicationAuthority):
            raise RegistrationFinalPublicationFenceError()
        return authority

    def _observe(
        self,
        request: RegistrationFinalPublicationRequest,
        authority: RegistrationFinalPublicationAuthority,
        fence: GlobalSchemaPublicationFenceHandle,
        advisory: DatabaseAdvisoryLockHandle,
    ) -> RegistrationPublicationObservation:
        self._require_advisory(request, fence, advisory)
        self._require_global_fence(request, fence)
        observation = self._current_observation(
            request=request,
            authority=authority,
            schema_fence=fence,
            advisory_lock=advisory,
        )
        if not isinstance(observation, RegistrationPublicationObservation):
            raise RegistrationFinalPublicationInvariantError()
        _require_observation_matches_request(request, observation)
        return observation


def _require_authority_matches(
    request: RegistrationFinalPublicationRequest,
    authority: RegistrationFinalPublicationAuthority,
    fence: GlobalSchemaPublicationFenceHandle,
) -> None:
    proof = authority.ready_proof
    endpoint = authority.endpoint
    provisioned = authority.provisioned
    if (
        authority.attempt_uuid != request.attempt_uuid
        or authority.tenant_uuid != request.tenant_uuid
        or authority.database_uuid != request.database_uuid
        or authority.current_recovery_run_uuid
        != request.current_recovery_run_uuid
        or authority.provisioning_generation
        != request.provisioning_generation
        or authority.attempt_row_version
        != request.expected_attempt_row_version
        or authority.code_row_version != request.expected_code_row_version
        or proof.proof_uuid != request.ready_proof_uuid
        or not hmac.compare_digest(
            proof.request_digest,
            request.ready_proof_request_digest,
        )
        or proof.tenant_uuid != request.tenant_uuid
        or proof.database_uuid != request.database_uuid
        or proof.provisioning_generation != request.provisioning_generation
        or endpoint.tenant_uuid != request.tenant_uuid
        or endpoint.database_uuid != request.database_uuid
        or provisioned.tenant_uuid != request.tenant_uuid
        or provisioned.database_uuid != request.database_uuid
        or provisioned.provisioning_generation
        != request.provisioning_generation
        or provisioned.schema_generation != proof.schema_generation
        or not hmac.compare_digest(provisioned.schema_digest, proof.schema_digest)
        or not hmac.compare_digest(
            provisioned.database_identity_digest,
            proof.database_identity_digest,
        )
        or not hmac.compare_digest(
            provisioned.smoke_proof_digest,
            proof.smoke_proof_digest,
        )
        or not hmac.compare_digest(
            provisioned.advisory_lock_proof_digest,
            proof.advisory_lock_proof_digest,
        )
        or provisioned.route_version != endpoint.route_version
        or provisioned.initial_credential_generation
        != endpoint.initial_credential_generation
        or provisioned.dml_login_state_version
        != endpoint.dml_login_state_version
        or not provisioned.verified
        or not provisioned.business_route_unpublished
    ):
        raise RegistrationFinalPublicationFenceError()
    if authority.state is ReadyPublicationState.PROVISIONAL_READY:
        if not _same_uninterrupted_schema_fence(
            recorded=proof.recorded_schema_fence,
            current=fence.schema_operation_fence,
        ):
            raise RegistrationFinalPublicationFenceError()
        return
    if (
        authority.existing_registration_commit_uuid
        != request.plan.registration_commit_uuid
    ):
        raise RegistrationFinalPublicationFenceError()


def _same_uninterrupted_schema_fence(
    *,
    recorded: RegistrationSchemaOperationFence,
    current: RegistrationSchemaOperationFence,
) -> bool:
    return bool(
        current.claim_uuid == recorded.claim_uuid
        and current.owner_id == recorded.owner_id
        and current.generation == recorded.generation
        and current.fencing_token == recorded.fencing_token
        and current.row_version >= recorded.row_version
    )


def _require_observation_matches_request(
    request: RegistrationFinalPublicationRequest,
    observation: RegistrationPublicationObservation,
) -> None:
    if (
        observation.attempt_uuid != request.attempt_uuid
        or observation.tenant_uuid != request.tenant_uuid
        or observation.database_uuid != request.database_uuid
        or observation.ready_proof_uuid != request.ready_proof_uuid
        or not hmac.compare_digest(
            observation.ready_proof_request_digest,
            request.ready_proof_request_digest,
        )
    ):
        raise RegistrationFinalPublicationInvariantError()


def _result_from_committed_replay(
    *,
    request: RegistrationFinalPublicationRequest,
    finalization: RegistrationFinalizationResult,
    reconciled_after_unknown: bool,
) -> RegistrationFinalPublicationResult:
    plan = request.plan
    if (
        finalization.status != "active"
        or finalization.attempt_uuid != request.attempt_uuid
        or finalization.registration_commit_uuid
        != plan.registration_commit_uuid
        or finalization.membership_uuid != plan.membership_uuid
        or finalization.subscription_uuid != plan.subscription_uuid
        or finalization.subscription_event_uuid
        != plan.subscription_event_uuid
        or finalization.created
        or finalization.integrity_incident_uuid is not None
        or isinstance(finalization.resulting_attempt_row_version, bool)
        or not isinstance(finalization.resulting_attempt_row_version, int)
        or finalization.resulting_attempt_row_version < 1
    ):
        raise RegistrationFinalPublicationInvariantError()
    return RegistrationFinalPublicationResult(
        attempt_uuid=request.attempt_uuid,
        tenant_uuid=request.tenant_uuid,
        database_uuid=request.database_uuid,
        status="active",
        route_published=True,
        registration_commit_uuid=plan.registration_commit_uuid,
        ready_proof_uuid=request.ready_proof_uuid,
        finalization_created=False,
        reconciled_after_unknown=reconciled_after_unknown,
        integrity_incident_uuid=None,
    )


def _resolve_publication(
    *,
    request: RegistrationFinalPublicationRequest,
    finalization: RegistrationFinalizationResult | None,
    observation: RegistrationPublicationObservation,
    finalization_was_unknown: bool,
    final_fence_was_current: bool,
) -> RegistrationFinalPublicationResult:
    if finalization is not None and not final_fence_was_current:
        raise RegistrationFinalPublicationInvariantError()
    if observation.state is PublicationObservationState.INCONSISTENT:
        raise RegistrationFinalPublicationInvariantError()
    if observation.state is PublicationObservationState.COMMITTED:
        if not final_fence_was_current:
            raise RegistrationFinalPublicationInvariantError()
        if (
            observation.registration_commit_uuid
            != request.plan.registration_commit_uuid
        ):
            raise RegistrationFinalPublicationInvariantError()
        if finalization is not None and (
            finalization.status != "active"
            or finalization.attempt_uuid != request.attempt_uuid
            or finalization.registration_commit_uuid
            != request.plan.registration_commit_uuid
        ):
            raise RegistrationFinalPublicationInvariantError()
        return RegistrationFinalPublicationResult(
            attempt_uuid=request.attempt_uuid,
            tenant_uuid=request.tenant_uuid,
            database_uuid=request.database_uuid,
            status="active",
            route_published=True,
            registration_commit_uuid=request.plan.registration_commit_uuid,
            ready_proof_uuid=request.ready_proof_uuid,
            finalization_created=(
                False if finalization is None else finalization.created
            ),
            reconciled_after_unknown=finalization_was_unknown,
            integrity_incident_uuid=None,
        )

    if finalization is None:
        return RegistrationFinalPublicationResult(
            attempt_uuid=request.attempt_uuid,
            tenant_uuid=request.tenant_uuid,
            database_uuid=request.database_uuid,
            status=observation.attempt_status,
            route_published=False,
            registration_commit_uuid=None,
            ready_proof_uuid=request.ready_proof_uuid,
            finalization_created=False,
            reconciled_after_unknown=finalization_was_unknown,
            integrity_incident_uuid=None,
        )
    if (
        finalization.attempt_uuid != request.attempt_uuid
        or finalization.registration_commit_uuid is not None
        or finalization.status != observation.attempt_status
        or finalization.status
        not in {"identity_conflict", "security_blocked", "integrity_blocked"}
    ):
        raise RegistrationFinalPublicationInvariantError()
    return RegistrationFinalPublicationResult(
        attempt_uuid=request.attempt_uuid,
        tenant_uuid=request.tenant_uuid,
        database_uuid=request.database_uuid,
        status=finalization.status,
        route_published=False,
        registration_commit_uuid=None,
        ready_proof_uuid=request.ready_proof_uuid,
        finalization_created=finalization.created,
        reconciled_after_unknown=False,
        integrity_incident_uuid=finalization.integrity_incident_uuid,
    )


class _FinalCommitFenceCurrentRead:
    """One-shot adapter that makes the transactional fence read observable."""

    __slots__ = ("_completed", "_fence", "_global_fences", "_request")

    def __init__(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
        global_fences: GlobalSchemaPublicationFencePort,
    ) -> None:
        self._request = request
        self._fence = fence
        self._global_fences = global_fences
        self._completed = False

    @property
    def completed(self) -> bool:
        return self._completed

    def __call__(self, *, control_transaction: object) -> None:
        if self._completed or control_transaction is None:
            raise RegistrationFinalPublicationInvariantError()
        try:
            result = self._global_fences.require_current_in_transaction(
                control_transaction=control_transaction,
                request=self._request,
                fence=self._fence,
            )
        except RegistrationFinalPublicationError:
            raise
        except Exception:
            raise RegistrationFinalPublicationFenceError() from None
        if result is not None:
            raise RegistrationFinalPublicationFenceError()
        self._completed = True


class _PersistenceFinalFenceCurrentRead:
    """Require the real persistence hook to use the adapter's open Session."""

    __slots__ = (
        "_completed",
        "_delegate",
        "_expected_control_transaction",
    )

    def __init__(
        self,
        *,
        expected_control_transaction: object,
        delegate: RegistrationFinalCommitFenceCurrentRead,
    ) -> None:
        if expected_control_transaction is None or not callable(delegate):
            raise RegistrationFinalPublicationInputError()
        self._expected_control_transaction = expected_control_transaction
        self._delegate = delegate
        self._completed = False

    @property
    def completed(self) -> bool:
        return self._completed

    def __call__(self, *, control_transaction: object) -> None:
        if (
            self._completed
            or control_transaction is not self._expected_control_transaction
        ):
            raise RegistrationFinalPublicationInvariantError()
        result = self._delegate(control_transaction=control_transaction)
        if result is not None:
            raise RegistrationFinalPublicationFenceError()
        self._completed = True


def _release_locks(
    *,
    request: RegistrationFinalPublicationRequest,
    fence: GlobalSchemaPublicationFenceHandle | None,
    advisory: DatabaseAdvisoryLockHandle | None,
    global_fences: GlobalSchemaPublicationFencePort,
    advisory_locks: DatabaseAdvisoryPublicationLockPort,
) -> bool:
    failed = False
    if advisory is not None and fence is not None:
        try:
            advisory_locks.release(
                request=request,
                schema_fence=fence,
                advisory_lock=advisory,
            )
        except Exception:
            failed = True
    if fence is not None:
        try:
            global_fences.release(request=request, fence=fence)
        except Exception:
            failed = True
    return failed


def _worker_token_digest(value: object) -> bytes:
    if not isinstance(value, str) or _SAFE_TOKEN.fullmatch(value) is None:
        raise RegistrationFinalPublicationInputError()
    return hashlib.sha256(
        b"inventory-manager/registration-worker-lease-token/v1\x00"
        + value.encode("ascii")
    ).digest()


def registration_publication_lock_binding_digest(
    request: RegistrationFinalPublicationRequest,
) -> bytes:
    if not isinstance(request, RegistrationFinalPublicationRequest):
        raise RegistrationFinalPublicationInputError()
    payload = {
        "attempt_uuid": str(request.attempt_uuid),
        "current_recovery_run_uuid": str(request.current_recovery_run_uuid),
        "database_uuid": str(request.database_uuid),
        "expected_attempt_row_version": request.expected_attempt_row_version,
        "expected_code_row_version": request.expected_code_row_version,
        "lock_idempotency_key": request.lock_idempotency_key,
        "membership_uuid": str(request.plan.membership_uuid),
        "plan_idempotency_key": request.plan.idempotency_key,
        "plan_policy_version": request.plan.commit_policy_version,
        "protocol_version": request.protocol_version,
        "provisioning_generation": request.provisioning_generation,
        "published_slug_digest": hashlib.sha256(
            request.plan.published_slug.encode("utf-8")
        ).hexdigest(),
        "published_tenant_name_digest": hashlib.sha256(
            request.plan.published_tenant_name.encode("utf-8")
        ).hexdigest(),
        "ready_proof_request_digest": request.ready_proof_request_digest.hex(),
        "ready_proof_uuid": str(request.ready_proof_uuid),
        "registration_commit_uuid": str(
            request.plan.registration_commit_uuid
        ),
        "subscription_event_uuid": str(request.plan.subscription_event_uuid),
        "subscription_uuid": str(request.plan.subscription_uuid),
        "tenant_uuid": str(request.tenant_uuid),
    }
    return hashlib.sha256(_AUTHORITY_DOMAIN + _canonical_json(payload)).digest()


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _uuid(value: object) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise RegistrationFinalPublicationInputError()
    return value


def _positive(value: object) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise RegistrationFinalPublicationInputError()
    return value


def _digest(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != _DIGEST_BYTES:
        raise RegistrationFinalPublicationInputError()
    return value


def _safe_id(value: object) -> str:
    if not isinstance(value, str) or _SAFE_ID.fullmatch(value) is None:
        raise RegistrationFinalPublicationInputError()
    return value


__all__ = [
    "REGISTRATION_FINAL_PUBLICATION_PROTOCOL_VERSION",
    "DatabaseAdvisoryLockHandle",
    "DatabaseAdvisoryPublicationLockPort",
    "GlobalSchemaPublicationFenceHandle",
    "GlobalSchemaPublicationFencePort",
    "PersistedTenantReadyProof",
    "ProvisionalTenantEndpoint",
    "PublicationObservationState",
    "ReadyPublicationState",
    "RegistrationAtomicFinalCommitPort",
    "RegistrationCommittedPublicationCurrentRead",
    "RegistrationPersistenceCommittedPublicationCurrentRead",
    "RegistrationPersistenceAtomicFinalCommitPort",
    "RegistrationFinalCommitFenceCurrentRead",
    "RegistrationFinalPublicationAuthority",
    "RegistrationFinalPublicationError",
    "RegistrationFinalPublicationFenceError",
    "RegistrationFinalPublicationInputError",
    "RegistrationFinalPublicationInvariantError",
    "RegistrationFinalPublicationReleaseError",
    "RegistrationFinalPublicationRequest",
    "RegistrationFinalPublicationResult",
    "RegistrationFinalPublicationService",
    "RegistrationFinalPublicationUnpublished",
    "RegistrationPublicationCurrentObservation",
    "RegistrationPublicationObservation",
    "RegistrationReadyPublicationCurrentRead",
    "registration_publication_lock_binding_digest",
]
