"""Concrete fence adapters for registration final publication.

The global adapter does not invent a new lease identity or expiry.  It reads
the immutable ready proof, requires that its original provisioning-purpose
schema-operation claim is still uninterrupted, and delegates every live-fence
check and release to ``SchemaOperationLeasePersistenceService`` inside a
caller-owned control-database transaction.  Ordinary renewals may advance the
singleton row version without changing the claim identity.

The advisory adapter accepts only a trusted factory keyed by immutable
``database_uuid``.  It never accepts a DSN, schema name, credential, or SQL
fragment.  One dedicated connection is retained from ``GET_LOCK`` through
the final ``IS_USED_LOCK`` checks and ``RELEASE_LOCK``; the connection is
always closed when acquisition fails or release completes.  The concrete
SQLAlchemy factory below resolves an explicit trusted provisioner ``Engine``.
It never reuses an application ``Session`` and discards a physical connection
after an uncertain/failed advisory-lock lifecycle so a MySQL session lock
cannot leak back into the pool.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from threading import RLock
from typing import Callable, Final, Mapping, Protocol, runtime_checkable
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine, RootTransaction
from sqlalchemy.orm import Session

from inventory_control.database import ControlDatabase
from inventory_control.fleet_migrations.runner import (
    MAX_ADVISORY_LOCK_TIMEOUT_SECONDS,
    advisory_lock_name,
)
from inventory_control.models.registration import (
    TenantRegistrationProvisioningProof,
)
from inventory_control.models.schema_operations import (
    PlatformSchemaOperationLease,
)
from inventory_control.schema_operations import (
    SCHEMA_OPERATION_LEASE_KEY,
    SchemaOperationLease,
    SchemaOperationLeasePersistenceService,
    SchemaOperationPurpose,
)

from .persistence import (
    REGISTRATION_PROVISIONING_PROOF_POLICY_VERSION,
    RegistrationSchemaOperationFence,
)
from .publication import (
    DatabaseAdvisoryLockHandle,
    GlobalSchemaPublicationFenceHandle,
    RegistrationFinalPublicationFenceError,
    RegistrationFinalPublicationInputError,
    RegistrationFinalPublicationRequest,
    registration_publication_lock_binding_digest,
)


_GET_LOCK: Final = sa.text(
    "SELECT GET_LOCK(:lock_name, :timeout_seconds)"
)
_IS_USED_LOCK: Final = sa.text("SELECT IS_USED_LOCK(:lock_name)")
_CONNECTION_ID: Final = sa.text("SELECT CONNECTION_ID()")
_RELEASE_LOCK: Final = sa.text("SELECT RELEASE_LOCK(:lock_name)")
_ADVISORY_PROOF_DOMAIN: Final = (
    b"inventory-manager/registration-publication-advisory/v1\x00"
)
_OWNER_ID: Final = re.compile(
    r"registration-final-[0-9a-f]{32}",
    re.ASCII,
)


ControlDatabaseClock = Callable[[Session], datetime]


@runtime_checkable
class DedicatedPublicationLockConnection(Protocol):
    """One checked-out physical connection retained for the whole lock hold."""

    def scalar(
        self,
        statement: object,
        parameters: Mapping[str, object] | None = None,
    ) -> object: ...

    def commit(self) -> None: ...

    def rollback(self) -> None: ...

    def close(self) -> None: ...


class DedicatedPublicationLockConnectionFactory(Protocol):
    """Resolve a trusted target instance from only its immutable DB UUID."""

    def __call__(
        self,
        database_uuid: UUID,
    ) -> DedicatedPublicationLockConnection: ...


class TrustedPublicationDatabaseEngineResolver(Protocol):
    """Resolve one provisioner engine from trusted immutable registry state."""

    def __call__(self, database_uuid: UUID) -> Engine: ...


class _SQLAlchemyDedicatedPublicationLockConnection:
    """Own one transaction and one checked-out DBAPI connection.

    A successful advisory lifecycle explicitly commits before close.  Every
    other close rolls back and invalidates the checkout, which forces the pool
    to physically close it.  That distinction matters for MySQL named locks:
    a plain transaction rollback does not release a session-level lock.
    """

    __slots__ = ("_connection", "_outcome", "_transaction")

    def __init__(
        self,
        *,
        connection: Connection,
        transaction: RootTransaction,
    ) -> None:
        self._connection = connection
        self._transaction = transaction
        self._outcome = "active"

    def scalar(
        self,
        statement: object,
        parameters: Mapping[str, object] | None = None,
    ) -> object:
        if self._outcome != "active":
            raise RegistrationFinalPublicationFenceError()
        return self._connection.scalar(statement, parameters)

    def commit(self) -> None:
        if self._outcome != "active":
            raise RegistrationFinalPublicationFenceError()
        self._transaction.commit()
        self._outcome = "committed"

    def rollback(self) -> None:
        if self._outcome != "active":
            return
        failure: Exception | None = None
        try:
            if self._transaction.is_active:
                self._transaction.rollback()
        except Exception as error:
            failure = error
        finally:
            self._outcome = "rolled_back"
            try:
                # Never return a connection with uncertain advisory ownership
                # to the pool. Invalidation closes the DBAPI connection after
                # the explicit transaction rollback above.
                self._connection.invalidate()
            except Exception as error:
                if failure is None:
                    failure = error
        if failure is not None:
            raise failure

    def close(self) -> None:
        if self._outcome == "closed":
            return
        failure: Exception | None = None
        try:
            if self._outcome == "active":
                self.rollback()
        except Exception as error:
            failure = error
        finally:
            self._outcome = "closed"
            try:
                self._connection.close()
            except Exception as error:
                if failure is None:
                    failure = error
        if failure is not None:
            raise failure


class SQLAlchemyDedicatedPublicationLockConnectionFactory:
    """Open dedicated connections from an explicit trusted engine resolver.

    The resolver is infrastructure-owned and receives only the immutable
    database UUID.  It must select the exact tenant-database instance used by
    provisioning; this adapter does not discover endpoints from environment
    variables, accept DSNs, or fall back to the control-database engine.
    Every call checks out an independently-owned physical connection and
    begins its own transaction.  It never accepts or reuses a business
    ``Session``.
    """

    __slots__ = ("_engine_resolver",)

    def __init__(
        self,
        *,
        engine_resolver: TrustedPublicationDatabaseEngineResolver,
    ) -> None:
        if not callable(engine_resolver):
            raise RegistrationFinalPublicationInputError()
        self._engine_resolver = engine_resolver

    def __call__(
        self,
        database_uuid: UUID,
    ) -> DedicatedPublicationLockConnection:
        if not isinstance(database_uuid, UUID):
            raise RegistrationFinalPublicationInputError()
        connection: Connection | None = None
        try:
            engine = self._engine_resolver(database_uuid)
            if not isinstance(engine, Engine):
                raise RegistrationFinalPublicationFenceError()
            connection = engine.connect()
            transaction = connection.begin()
            return _SQLAlchemyDedicatedPublicationLockConnection(
                connection=connection,
                transaction=transaction,
            )
        except RegistrationFinalPublicationInputError:
            raise
        except Exception:
            if connection is not None:
                try:
                    connection.close()
                except Exception:
                    pass
            raise RegistrationFinalPublicationFenceError() from None


class ControlDatabaseGlobalSchemaPublicationFencePort:
    """Use the ready proof's still-live global provisioning claim.

    ``acquire`` means acquiring a local handle to the already-held persisted
    claim.  It intentionally never claims or renews the singleton: neither a
    new owner nor a new expiry is present in the publication request.  If the
    ready proof's claim expired or turned over, publication fails closed.
    """

    __slots__ = ("_control_database", "_database_clock")

    def __init__(
        self,
        *,
        control_database: ControlDatabase,
        database_clock: ControlDatabaseClock | None = None,
    ) -> None:
        if not isinstance(control_database, ControlDatabase):
            raise RegistrationFinalPublicationInputError()
        if database_clock is not None and not callable(database_clock):
            raise RegistrationFinalPublicationInputError()
        self._control_database = control_database
        self._database_clock = database_clock

    def acquire(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
    ) -> GlobalSchemaPublicationFenceHandle:
        _request(request)
        try:
            with self._control_database.transaction() as session:
                recorded = _read_recorded_fence(session, request=request)
                current = self._require_uninterrupted_current(
                    session,
                    recorded=recorded,
                    minimum_row_version=recorded.row_version,
                )
        except RegistrationFinalPublicationInputError:
            raise
        except Exception:
            raise RegistrationFinalPublicationFenceError() from None
        return GlobalSchemaPublicationFenceHandle(
            schema_operation_fence=current,
            purpose="provisioning",
            request_binding_digest=(
                registration_publication_lock_binding_digest(request)
            ),
        )

    def require_current(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
    ) -> None:
        _request_and_global_handle(request, fence)
        try:
            with self._control_database.transaction() as session:
                self._require_request_fence_current(
                    session,
                    request=request,
                    fence=fence,
                )
        except RegistrationFinalPublicationInputError:
            raise
        except Exception:
            raise RegistrationFinalPublicationFenceError() from None

    def require_current_in_transaction(
        self,
        *,
        control_transaction: object,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
    ) -> None:
        _request_and_global_handle(request, fence)
        if not isinstance(control_transaction, Session):
            raise RegistrationFinalPublicationFenceError()
        try:
            if (
                control_transaction.get_bind()
                is not self._control_database.engine
            ):
                raise RegistrationFinalPublicationFenceError()
            self._require_request_fence_current(
                control_transaction,
                request=request,
                fence=fence,
            )
        except RegistrationFinalPublicationInputError:
            raise
        except Exception:
            raise RegistrationFinalPublicationFenceError() from None

    def release(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
    ) -> None:
        _request_and_global_handle(request, fence)
        try:
            with self._control_database.transaction() as session:
                recorded = _read_recorded_fence(session, request=request)
                expected = fence.schema_operation_fence
                _require_same_uninterrupted(
                    recorded=recorded,
                    current=expected,
                    minimum_row_version=recorded.row_version,
                )
                row = _lock_schema_lease_row(session)
                if _same_claim_already_released(row, expected=expected):
                    return
                current = _row_fence(row)
                _require_same_uninterrupted(
                    recorded=expected,
                    current=current,
                    minimum_row_version=expected.row_version,
                )
                _lease_service(
                    session,
                    database_clock=self._database_clock,
                ).release(
                    claim_id=current.claim_uuid,
                    owner_id=current.owner_id,
                    purpose=SchemaOperationPurpose.PROVISIONING,
                    fencing_token=current.fencing_token,
                    expected_row_version=current.row_version,
                )
        except RegistrationFinalPublicationInputError:
            raise
        except Exception:
            raise RegistrationFinalPublicationFenceError() from None

    def _require_request_fence_current(
        self,
        session: Session,
        *,
        request: RegistrationFinalPublicationRequest,
        fence: GlobalSchemaPublicationFenceHandle,
    ) -> None:
        recorded = _read_recorded_fence(session, request=request)
        expected = fence.schema_operation_fence
        _require_same_uninterrupted(
            recorded=recorded,
            current=expected,
            minimum_row_version=recorded.row_version,
        )
        self._require_uninterrupted_current(
            session,
            recorded=expected,
            minimum_row_version=expected.row_version,
        )

    def _require_uninterrupted_current(
        self,
        session: Session,
        *,
        recorded: RegistrationSchemaOperationFence,
        minimum_row_version: int,
    ) -> RegistrationSchemaOperationFence:
        row = _lock_schema_lease_row(session)
        current = _row_fence(row)
        _require_same_uninterrupted(
            recorded=recorded,
            current=current,
            minimum_row_version=minimum_row_version,
        )
        live = _lease_service(
            session,
            database_clock=self._database_clock,
        ).require_live_schema_operation_fence(
            claim_id=recorded.claim_uuid,
            owner_id=recorded.owner_id,
            purpose=SchemaOperationPurpose.PROVISIONING,
            generation=recorded.generation,
            fencing_token=recorded.fencing_token,
            expected_row_version=current.row_version,
        )
        return _domain_fence(live)


@dataclass(slots=True)
class _AdvisoryConnectionState:
    connection: DedicatedPublicationLockConnection = field(repr=False)
    database_uuid: UUID
    owner_id: str
    lock_name: str = field(repr=False)
    lock_key_sha256: bytes
    acquisition_proof_digest: bytes
    connection_id: int = field(repr=False)
    schema_claim_uuid: UUID
    schema_fencing_token: int


class DedicatedConnectionDatabaseAdvisoryPublicationLockPort:
    """Hold the database-scoped MySQL advisory lock on one connection."""

    __slots__ = (
        "_active_by_owner",
        "_active_connection_objects",
        "_active_database_uuids",
        "_connection_factory",
        "_gate",
        "_lock_timeout_seconds",
    )

    def __init__(
        self,
        *,
        connection_factory: DedicatedPublicationLockConnectionFactory,
        lock_timeout_seconds: int,
    ) -> None:
        if not callable(connection_factory) or (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, int)
            or not 1
            <= lock_timeout_seconds
            <= MAX_ADVISORY_LOCK_TIMEOUT_SECONDS
        ):
            raise RegistrationFinalPublicationInputError()
        self._connection_factory = connection_factory
        self._lock_timeout_seconds = lock_timeout_seconds
        self._gate = RLock()
        self._active_by_owner: dict[str, _AdvisoryConnectionState] = {}
        self._active_connection_objects: set[int] = set()
        self._active_database_uuids: set[UUID] = set()

    def acquire(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        schema_fence: GlobalSchemaPublicationFenceHandle,
    ) -> DatabaseAdvisoryLockHandle:
        _request_and_global_handle(request, schema_fence)
        database_uuid = request.database_uuid
        owner_id = f"registration-final-{uuid4().hex}"
        lock_name = advisory_lock_name(database_uuid)
        lock_key_sha256 = hashlib.sha256(lock_name.encode("ascii")).digest()
        connection: DedicatedPublicationLockConnection | None = None
        acquired = False
        lock_attempted = False
        owns_connection_lifecycle = False
        with self._gate:
            if database_uuid in self._active_database_uuids:
                raise RegistrationFinalPublicationFenceError()
            self._active_database_uuids.add(database_uuid)
        try:
            connection = self._connection_factory(database_uuid)
            if not isinstance(connection, DedicatedPublicationLockConnection):
                raise RegistrationFinalPublicationFenceError()
            connection_object = id(connection)
            with self._gate:
                if connection_object in self._active_connection_objects:
                    # The factory violated its dedicated-connection contract.
                    # Do not close a connection already owned by another hold.
                    connection = None
                    raise RegistrationFinalPublicationFenceError()
                self._active_connection_objects.add(connection_object)
                owns_connection_lifecycle = True
            connection_id = _positive_scalar(
                connection.scalar(_CONNECTION_ID)
            )
            lock_attempted = True
            acquired = _one(
                connection.scalar(
                    _GET_LOCK,
                    {
                        "lock_name": lock_name,
                        "timeout_seconds": self._lock_timeout_seconds,
                    },
                )
            )
            if not acquired or _positive_scalar(
                connection.scalar(
                    _IS_USED_LOCK,
                    {"lock_name": lock_name},
                )
            ) != connection_id:
                raise RegistrationFinalPublicationFenceError()
            proof = _advisory_acquisition_digest(
                database_uuid=database_uuid,
                owner_id=owner_id,
                lock_key_sha256=lock_key_sha256,
                connection_id=connection_id,
                schema_claim_uuid=schema_fence.claim_uuid,
                schema_fencing_token=schema_fence.fencing_token,
            )
            state = _AdvisoryConnectionState(
                connection=connection,
                database_uuid=database_uuid,
                owner_id=owner_id,
                lock_name=lock_name,
                lock_key_sha256=lock_key_sha256,
                acquisition_proof_digest=proof,
                connection_id=connection_id,
                schema_claim_uuid=schema_fence.claim_uuid,
                schema_fencing_token=schema_fence.fencing_token,
            )
            with self._gate:
                self._active_by_owner[owner_id] = state
            return _state_handle(state)
        except Exception:
            if connection is not None and owns_connection_lifecycle:
                if lock_attempted:
                    _best_effort_release(connection, lock_name=lock_name)
                _best_effort_rollback(connection)
                _best_effort_close(connection)
            with self._gate:
                self._active_by_owner.pop(owner_id, None)
                if connection is not None and owns_connection_lifecycle:
                    self._active_connection_objects.discard(id(connection))
                self._active_database_uuids.discard(database_uuid)
            raise RegistrationFinalPublicationFenceError() from None

    def require_current(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        schema_fence: GlobalSchemaPublicationFenceHandle,
        advisory_lock: DatabaseAdvisoryLockHandle,
    ) -> None:
        _request_and_advisory_handle(request, schema_fence, advisory_lock)
        with self._gate:
            state = self._active_by_owner.get(advisory_lock.owner_id)
            if state is None or not _handle_matches_state(advisory_lock, state):
                raise RegistrationFinalPublicationFenceError()
            try:
                _require_connection_owns_lock(state)
            except Exception:
                raise RegistrationFinalPublicationFenceError() from None

    def release(
        self,
        *,
        request: RegistrationFinalPublicationRequest,
        schema_fence: GlobalSchemaPublicationFenceHandle,
        advisory_lock: DatabaseAdvisoryLockHandle,
    ) -> None:
        _request_and_advisory_handle(request, schema_fence, advisory_lock)
        failed = False
        with self._gate:
            state = self._active_by_owner.pop(advisory_lock.owner_id, None)
            if state is None or not _handle_matches_state(advisory_lock, state):
                raise RegistrationFinalPublicationFenceError()
            self._active_database_uuids.discard(state.database_uuid)
            self._active_connection_objects.discard(id(state.connection))
            try:
                _require_connection_owns_lock(state)
            except Exception:
                failed = True
            try:
                if not _one(
                    state.connection.scalar(
                        _RELEASE_LOCK,
                        {"lock_name": state.lock_name},
                    )
                ):
                    failed = True
            except Exception:
                failed = True
            finally:
                if failed:
                    _best_effort_rollback(state.connection)
                else:
                    try:
                        state.connection.commit()
                    except Exception:
                        failed = True
                        _best_effort_rollback(state.connection)
                try:
                    state.connection.close()
                except Exception:
                    failed = True
        if failed:
            raise RegistrationFinalPublicationFenceError()


def _request(value: object) -> RegistrationFinalPublicationRequest:
    if not isinstance(value, RegistrationFinalPublicationRequest):
        raise RegistrationFinalPublicationInputError()
    return value


def _request_and_global_handle(
    request: object,
    fence: object,
) -> None:
    selected = _request(request)
    if (
        not isinstance(fence, GlobalSchemaPublicationFenceHandle)
        or not hmac.compare_digest(
            fence.request_binding_digest,
            registration_publication_lock_binding_digest(selected),
        )
        or fence.purpose != "provisioning"
    ):
        raise RegistrationFinalPublicationFenceError()


def _request_and_advisory_handle(
    request: object,
    schema_fence: object,
    advisory_lock: object,
) -> None:
    _request_and_global_handle(request, schema_fence)
    selected = _request(request)
    if (
        not isinstance(advisory_lock, DatabaseAdvisoryLockHandle)
        or advisory_lock.database_uuid != selected.database_uuid
        or advisory_lock.schema_claim_uuid != schema_fence.claim_uuid
        or advisory_lock.schema_fencing_token != schema_fence.fencing_token
        or _OWNER_ID.fullmatch(advisory_lock.owner_id) is None
    ):
        raise RegistrationFinalPublicationFenceError()


def _read_recorded_fence(
    session: Session,
    *,
    request: RegistrationFinalPublicationRequest,
) -> RegistrationSchemaOperationFence:
    proof = session.scalar(
        sa.select(TenantRegistrationProvisioningProof)
        .where(
            TenantRegistrationProvisioningProof.id
            == str(request.ready_proof_uuid)
        )
        .with_for_update()
        .execution_options(autoflush=False, populate_existing=True)
    )
    if (
        proof is None
        or proof.outcome != "ready"
        or proof.attempt_uuid != str(request.attempt_uuid)
        or proof.tenant_uuid != str(request.tenant_uuid)
        or proof.database_uuid != str(request.database_uuid)
        or proof.recovery_run_uuid
        != str(request.current_recovery_run_uuid)
        or proof.provisioning_execution_generation
        != request.provisioning_generation
        or proof.proof_policy_version
        != REGISTRATION_PROVISIONING_PROOF_POLICY_VERSION
        or not hmac.compare_digest(
            bytes(proof.result_request_digest),
            request.ready_proof_request_digest,
        )
        or proof.schema_operation_claim_uuid is None
        or proof.schema_operation_owner_id is None
        or proof.schema_operation_generation is None
        or proof.schema_operation_fencing_token is None
        or proof.schema_operation_row_version is None
    ):
        raise RegistrationFinalPublicationFenceError()
    try:
        return RegistrationSchemaOperationFence(
            claim_uuid=UUID(proof.schema_operation_claim_uuid),
            owner_id=proof.schema_operation_owner_id,
            generation=proof.schema_operation_generation,
            fencing_token=proof.schema_operation_fencing_token,
            row_version=proof.schema_operation_row_version,
        )
    except Exception:
        raise RegistrationFinalPublicationFenceError() from None


def _lock_schema_lease_row(
    session: Session,
) -> PlatformSchemaOperationLease:
    row = session.scalar(
        sa.select(PlatformSchemaOperationLease)
        .where(
            PlatformSchemaOperationLease.lease_key
            == SCHEMA_OPERATION_LEASE_KEY
        )
        .with_for_update()
        .execution_options(autoflush=False, populate_existing=True)
    )
    if row is None:
        raise RegistrationFinalPublicationFenceError()
    return row


def _row_fence(
    row: PlatformSchemaOperationLease,
) -> RegistrationSchemaOperationFence:
    if (
        row.state != "held"
        or row.purpose != "provisioning"
        or row.claim_id is None
        or row.owner_id is None
    ):
        raise RegistrationFinalPublicationFenceError()
    try:
        return RegistrationSchemaOperationFence(
            claim_uuid=UUID(row.claim_id),
            owner_id=row.owner_id,
            generation=row.generation,
            fencing_token=row.fencing_token,
            row_version=row.row_version,
        )
    except Exception:
        raise RegistrationFinalPublicationFenceError() from None


def _same_claim_already_released(
    row: PlatformSchemaOperationLease,
    *,
    expected: RegistrationSchemaOperationFence,
) -> bool:
    """Treat an observed release of this exact claim as cleanup success."""

    return bool(
        row.state == "available"
        and row.owner_id is None
        and row.claim_id is None
        and row.purpose is None
        and row.last_effect == "released"
        and row.last_claim_id == str(expected.claim_uuid)
        and row.generation == expected.generation
        and row.fencing_token == expected.fencing_token
        and row.row_version > expected.row_version
    )


def _domain_fence(
    lease: SchemaOperationLease,
) -> RegistrationSchemaOperationFence:
    if (
        lease.claim_id is None
        or lease.owner_id is None
        or lease.purpose is not SchemaOperationPurpose.PROVISIONING
    ):
        raise RegistrationFinalPublicationFenceError()
    return RegistrationSchemaOperationFence(
        claim_uuid=lease.claim_id,
        owner_id=lease.owner_id,
        generation=lease.generation,
        fencing_token=lease.fencing_token,
        row_version=lease.row_version,
    )


def _require_same_uninterrupted(
    *,
    recorded: RegistrationSchemaOperationFence,
    current: RegistrationSchemaOperationFence,
    minimum_row_version: int,
) -> None:
    if (
        current.claim_uuid != recorded.claim_uuid
        or current.owner_id != recorded.owner_id
        or current.generation != recorded.generation
        or current.fencing_token != recorded.fencing_token
        or current.row_version < minimum_row_version
    ):
        raise RegistrationFinalPublicationFenceError()


def _lease_service(
    session: Session,
    *,
    database_clock: ControlDatabaseClock | None,
) -> SchemaOperationLeasePersistenceService:
    return SchemaOperationLeasePersistenceService(
        session,
        database_clock=database_clock,
    )


def _positive_scalar(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise RegistrationFinalPublicationFenceError()
    return value


def _one(value: object) -> bool:
    return bool(not isinstance(value, bool) and value == 1)


def _advisory_acquisition_digest(
    *,
    database_uuid: UUID,
    owner_id: str,
    lock_key_sha256: bytes,
    connection_id: int,
    schema_claim_uuid: UUID,
    schema_fencing_token: int,
) -> bytes:
    payload = {
        "connection_id": connection_id,
        "database_uuid": str(database_uuid),
        "lock_key_sha256": lock_key_sha256.hex(),
        "owner_id": owner_id,
        "schema_claim_uuid": str(schema_claim_uuid),
        "schema_fencing_token": schema_fencing_token,
        "version": 1,
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(_ADVISORY_PROOF_DOMAIN + encoded).digest()


def _state_handle(
    state: _AdvisoryConnectionState,
) -> DatabaseAdvisoryLockHandle:
    return DatabaseAdvisoryLockHandle(
        database_uuid=state.database_uuid,
        owner_id=state.owner_id,
        lock_key_sha256=state.lock_key_sha256,
        acquisition_proof_digest=state.acquisition_proof_digest,
        schema_claim_uuid=state.schema_claim_uuid,
        schema_fencing_token=state.schema_fencing_token,
    )


def _handle_matches_state(
    handle: DatabaseAdvisoryLockHandle,
    state: _AdvisoryConnectionState,
) -> bool:
    return bool(
        handle.database_uuid == state.database_uuid
        and handle.owner_id == state.owner_id
        and hmac.compare_digest(
            handle.lock_key_sha256,
            state.lock_key_sha256,
        )
        and hmac.compare_digest(
            handle.acquisition_proof_digest,
            state.acquisition_proof_digest,
        )
        and handle.schema_claim_uuid == state.schema_claim_uuid
        and handle.schema_fencing_token == state.schema_fencing_token
    )


def _require_connection_owns_lock(state: _AdvisoryConnectionState) -> None:
    connection_id = _positive_scalar(state.connection.scalar(_CONNECTION_ID))
    owner = _positive_scalar(
        state.connection.scalar(
            _IS_USED_LOCK,
            {"lock_name": state.lock_name},
        )
    )
    if connection_id != state.connection_id or owner != connection_id:
        raise RegistrationFinalPublicationFenceError()


def _best_effort_release(
    connection: DedicatedPublicationLockConnection,
    *,
    lock_name: str,
) -> None:
    try:
        connection.scalar(
            _RELEASE_LOCK,
            {"lock_name": lock_name},
        )
    except Exception:
        pass


def _best_effort_close(
    connection: DedicatedPublicationLockConnection,
) -> None:
    try:
        connection.close()
    except Exception:
        pass


def _best_effort_rollback(
    connection: DedicatedPublicationLockConnection,
) -> None:
    try:
        connection.rollback()
    except Exception:
        pass


__all__ = [
    "ControlDatabaseGlobalSchemaPublicationFencePort",
    "DedicatedConnectionDatabaseAdvisoryPublicationLockPort",
    "DedicatedPublicationLockConnection",
    "DedicatedPublicationLockConnectionFactory",
    "SQLAlchemyDedicatedPublicationLockConnectionFactory",
    "TrustedPublicationDatabaseEngineResolver",
]
