"""Caller-owned control-DB persistence for tenant fleet migrations.

This module never opens a tenant connection and never executes DDL.  It only
persists non-secret control metadata after revalidating the registered route,
database identity record, and the shared ``fleet_migration`` schema-operation
fence.  The external runner remains responsible for the per-database advisory
lock and for producing a trusted :class:`FleetMigrationObservation`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from inventory_control.models.fleet_migrations import TenantFleetMigration
from inventory_control.models.foundation import (
    DatabaseIdentityControlRecord,
    Tenant,
    TenantDatabase,
)
from inventory_control.schema_operations import (
    SchemaOperationLeasePersistenceService,
    SchemaOperationPurpose,
)

from .domain import (
    FleetMigrationError,
    FleetMigrationFenceConflict,
    FleetMigrationObservation,
    FleetMigrationObservationRejected,
    FleetMigrationState,
    FleetMigrationTarget,
    FleetMigrationTransition,
    FleetRouteDisposition,
    FleetSchemaIdentity,
    begin_fleet_migration,
    fail_fleet_migration,
    retry_fleet_migration,
    succeed_fleet_migration,
)


_OWNER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_REQUEST_DOMAIN = b"inventory-manager/fleet-migration-request/v1\x00"


class FleetMigrationPersistenceError(FleetMigrationError):
    code = "FLEET_MIGRATION_PERSISTENCE_FAILED"
    public_message = "the tenant schema migration could not be persisted"


class FleetMigrationTransactionError(FleetMigrationPersistenceError):
    code = "FLEET_MIGRATION_TRANSACTION_INVALID"
    public_message = "an explicit clean caller-owned transaction is required"


class FleetMigrationStoredStateError(FleetMigrationPersistenceError):
    code = "FLEET_MIGRATION_STORED_STATE_INVALID"
    public_message = "the tenant schema migration state is invalid"


class FleetMigrationControlIdentityError(FleetMigrationPersistenceError):
    code = "FLEET_MIGRATION_CONTROL_IDENTITY_MISMATCH"
    public_message = "the tenant schema migration identity was rejected"


@dataclass(frozen=True, slots=True, kw_only=True)
class FleetSchemaOperationFence:
    """The exact non-secret shared-lease identity carried by a runner."""

    claim_id: UUID
    owner_id: str
    generation: int
    fencing_token: int
    row_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.claim_id, UUID) or self.claim_id.int == 0:
            raise TypeError("claim_id must be a non-zero UUID")
        if not isinstance(self.owner_id, str) or _OWNER.fullmatch(
            self.owner_id
        ) is None:
            raise ValueError("owner_id is invalid")
        for name in ("generation", "fencing_token", "row_version"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(f"{name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class FleetMigrationPersistenceResult:
    target: FleetMigrationTarget
    route_disposition: FleetRouteDisposition
    created: bool
    idempotent_replay: bool

    @property
    def migration_uuid(self) -> UUID:
        return self.target.migration_uuid


DatabaseClock = Callable[[Session], datetime]


class FleetMigrationPersistenceService:
    """Persist one tenant migration state machine in a caller transaction."""

    __slots__ = ("_database_clock", "_session")

    def __init__(
        self,
        session: Session,
        *,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not isinstance(session, Session):
            raise FleetMigrationTransactionError()
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._session = session
        self._database_clock = database_clock or _read_database_utc_now

    def queue(
        self,
        *,
        migration_uuid: UUID,
        source: FleetSchemaIdentity,
        target: FleetSchemaIdentity,
    ) -> FleetMigrationPersistenceResult:
        """Create the unique N-1 to N target or return its exact replay."""

        self._prepare()
        migration_id = _uuid(migration_uuid)
        if not isinstance(source, FleetSchemaIdentity) or not isinstance(
            target,
            FleetSchemaIdentity,
        ):
            raise FleetMigrationControlIdentityError()
        # Constructing the domain target below is the final adjacency check;
        # reject cross-database inputs before any row lock is taken.
        if not source.same_database(target):
            raise FleetMigrationControlIdentityError()

        tenant, route, identity = self._lock_control_identity(source)
        row = self._lock_target_generation(source, target)
        expected_control = (
            _expected_control_identity(_domain_target(row))
            if row is not None
            else source
        )
        self._require_control_identity(
            tenant,
            route,
            identity,
            expected=expected_control,
            queue_source=source if row is None else None,
        )
        # The authoritative clock is intentionally sampled after all control
        # identity and target-generation locks.
        now = self._now()
        queue_digest = _queue_request_digest(
            migration_uuid=migration_id,
            source=source,
            target=target,
        )

        if row is not None:
            return self._queue_replay(
                row,
                migration_uuid=migration_id,
                source=source,
                target=target,
                queue_digest=queue_digest,
            )

        queued = FleetMigrationTarget.queued(
            migration_uuid=migration_id,
            source=source,
            target=target,
            database_now=now,
        )
        candidate = _new_row(
            queued,
            queue_digest=queue_digest,
            database_now=now,
        )
        try:
            with self._session.begin_nested():
                self._bind_queue_identity(identity, source=source)
                self._session.add(candidate)
                self._session.flush()
        except IntegrityError:
            raise FleetMigrationFenceConflict() from None
        except SQLAlchemyError:
            raise FleetMigrationPersistenceError() from None
        self._session.expire(candidate)
        self._session.expire(identity)
        return FleetMigrationPersistenceResult(
            target=queued,
            route_disposition=FleetRouteDisposition.ROUTABLE_PREVIOUS,
            created=True,
            idempotent_replay=False,
        )

    def begin(
        self,
        *,
        migration_uuid: UUID,
        expected_row_version: int,
        observation: FleetMigrationObservation,
        schema_operation_fence: FleetSchemaOperationFence,
    ) -> FleetMigrationPersistenceResult:
        return self._mutate(
            migration_uuid=migration_uuid,
            operation="begin",
            expected_row_version=expected_row_version,
            expected_operation_generation=None,
            observation=observation,
            safe_error_code=None,
            schema_operation_fence=schema_operation_fence,
            reducer=lambda current, now: begin_fleet_migration(
                current,
                expected_row_version=expected_row_version,
                observation=observation,
                database_now=now,
            ),
        )

    def succeed(
        self,
        *,
        migration_uuid: UUID,
        expected_row_version: int,
        expected_operation_generation: int,
        observation: FleetMigrationObservation,
        schema_operation_fence: FleetSchemaOperationFence,
    ) -> FleetMigrationPersistenceResult:
        return self._mutate(
            migration_uuid=migration_uuid,
            operation="succeed",
            expected_row_version=expected_row_version,
            expected_operation_generation=expected_operation_generation,
            observation=observation,
            safe_error_code=None,
            schema_operation_fence=schema_operation_fence,
            reducer=lambda current, now: succeed_fleet_migration(
                current,
                expected_row_version=expected_row_version,
                expected_operation_generation=expected_operation_generation,
                observation=observation,
                database_now=now,
            ),
        )

    def fail(
        self,
        *,
        migration_uuid: UUID,
        expected_row_version: int,
        expected_operation_generation: int,
        observation: FleetMigrationObservation,
        safe_error_code: str,
        schema_operation_fence: FleetSchemaOperationFence,
    ) -> FleetMigrationPersistenceResult:
        return self._mutate(
            migration_uuid=migration_uuid,
            operation="fail",
            expected_row_version=expected_row_version,
            expected_operation_generation=expected_operation_generation,
            observation=observation,
            safe_error_code=safe_error_code,
            schema_operation_fence=schema_operation_fence,
            reducer=lambda current, now: fail_fleet_migration(
                current,
                expected_row_version=expected_row_version,
                expected_operation_generation=expected_operation_generation,
                observation=observation,
                safe_error_code=safe_error_code,
                database_now=now,
            ),
        )

    def retry(
        self,
        *,
        migration_uuid: UUID,
        expected_row_version: int,
        observation: FleetMigrationObservation,
        schema_operation_fence: FleetSchemaOperationFence,
    ) -> FleetMigrationPersistenceResult:
        return self._mutate(
            migration_uuid=migration_uuid,
            operation="retry",
            expected_row_version=expected_row_version,
            expected_operation_generation=None,
            observation=observation,
            safe_error_code=None,
            schema_operation_fence=schema_operation_fence,
            reducer=lambda current, now: retry_fleet_migration(
                current,
                expected_row_version=expected_row_version,
                observation=observation,
                database_now=now,
            ),
        )

    queue_migration = queue
    begin_migration = begin
    succeed_migration = succeed
    fail_migration = fail
    retry_migration = retry

    def _mutate(
        self,
        *,
        migration_uuid: UUID,
        operation: str,
        expected_row_version: int,
        expected_operation_generation: int | None,
        observation: FleetMigrationObservation,
        safe_error_code: str | None,
        schema_operation_fence: FleetSchemaOperationFence,
        reducer,
    ) -> FleetMigrationPersistenceResult:
        self._prepare()
        migration_id = _uuid(migration_uuid)
        if not isinstance(observation, FleetMigrationObservation):
            raise FleetMigrationControlIdentityError()
        if not isinstance(schema_operation_fence, FleetSchemaOperationFence):
            raise FleetMigrationControlIdentityError()

        try:
            snapshot = self._session.scalar(
                sa.select(TenantFleetMigration)
                .where(
                    TenantFleetMigration.migration_uuid
                    == str(migration_id)
                )
                .execution_options(autoflush=False, populate_existing=True)
            )
        except SQLAlchemyError:
            raise FleetMigrationPersistenceError() from None
        if snapshot is None:
            raise FleetMigrationFenceConflict()
        snapshot_tenant = _canonical_uuid(snapshot.tenant_id)
        snapshot_database = _canonical_uuid(snapshot.database_uuid)

        tenant, route, identity = self._lock_control_identity_by_ids(
            snapshot_tenant,
            snapshot_database,
        )
        row = self._lock_migration(migration_id)
        if (
            row is None
            or row.tenant_id != str(snapshot_tenant)
            or row.database_uuid != str(snapshot_database)
        ):
            raise FleetMigrationFenceConflict()
        current = _domain_target(row)
        self._require_control_identity(
            tenant,
            route,
            identity,
            expected=_expected_control_identity(current),
        )

        # This is deliberately the public shared-lease persistence boundary.
        # It locks and validates the singleton after the tenant-first control
        # rows, matching the final-CAS lock order used by other consumers.
        SchemaOperationLeasePersistenceService(
            self._session,
            database_clock=self._database_clock,
        ).require_live_fence(
            claim_id=schema_operation_fence.claim_id,
            owner_id=schema_operation_fence.owner_id,
            purpose=SchemaOperationPurpose.FLEET_MIGRATION,
            generation=schema_operation_fence.generation,
            fencing_token=schema_operation_fence.fencing_token,
            expected_row_version=schema_operation_fence.row_version,
        )
        # Sample again after every row lock and the live global fence.
        now = self._now()
        _require_fresh_observation(
            row,
            identity=identity,
            current=current,
            observation=observation,
            database_now=now,
        )
        request_digest = _transition_request_digest(
            operation=operation,
            migration_uuid=migration_id,
            expected_row_version=expected_row_version,
            expected_operation_generation=expected_operation_generation,
            observation=observation,
            safe_error_code=safe_error_code,
            fence=schema_operation_fence,
        )
        if _is_exact_replay(
            row,
            operation=operation,
            expected_row_version=expected_row_version,
            request_digest=request_digest,
        ):
            return FleetMigrationPersistenceResult(
                target=current,
                route_disposition=_stored_disposition(row),
                created=False,
                idempotent_replay=True,
            )

        transition = reducer(current, now)
        self._apply_transition(
            row,
            route=route,
            identity=identity,
            before=current,
            transition=transition,
            operation=operation,
            request_digest=request_digest,
            observation=observation,
            fence=schema_operation_fence,
            database_now=now,
        )
        return FleetMigrationPersistenceResult(
            target=transition.target,
            route_disposition=transition.route_disposition,
            created=False,
            idempotent_replay=False,
        )

    def _apply_transition(
        self,
        row: TenantFleetMigration,
        *,
        route: TenantDatabase,
        identity: DatabaseIdentityControlRecord,
        before: FleetMigrationTarget,
        transition: FleetMigrationTransition,
        operation: str,
        request_digest: bytes,
        observation: FleetMigrationObservation,
        fence: FleetSchemaOperationFence,
        database_now: datetime,
    ) -> None:
        after = transition.target
        if (
            after.row_version != before.row_version + 1
            or after.migration_uuid != before.migration_uuid
            or not after.source.same_schema(before.source)
            or not after.target.same_schema(before.target)
        ):
            raise FleetMigrationPersistenceError()
        expected_after = (
            after.target
            if transition.route_disposition
            is FleetRouteDisposition.ROUTABLE_CURRENT
            else after.source
        )
        identity_version = identity.row_version
        route_version = route.row_version
        route_changed = route.schema_version != expected_after.schema_revision
        identity_matches = after.source.same_database(observation.identity)
        try:
            with self._session.begin_nested():
                changed = self._session.execute(
                    sa.update(TenantFleetMigration)
                    .where(
                        TenantFleetMigration.migration_uuid == row.migration_uuid,
                        TenantFleetMigration.row_version == before.row_version,
                        TenantFleetMigration.state == before.state.value,
                        TenantFleetMigration.operation_generation
                        == before.operation_generation,
                    )
                    .values(
                        state=after.state.value,
                        route_disposition=transition.route_disposition.value,
                        attempt_count=after.attempt_count,
                        operation_generation=after.operation_generation,
                        row_version=after.row_version,
                        last_transition=operation,
                        last_transition_from_row_version=before.row_version,
                        last_request_digest=request_digest,
                        schema_operation_claim_uuid=str(fence.claim_id),
                        schema_operation_owner_id=fence.owner_id,
                        schema_operation_generation=fence.generation,
                        schema_operation_fencing_token=fence.fencing_token,
                        schema_operation_row_version=fence.row_version,
                        last_observed_tenant_uuid=str(
                            observation.identity.tenant_uuid
                        ),
                        last_observed_database_uuid=str(
                            observation.identity.database_uuid
                        ),
                        last_observed_schema_generation=(
                            observation.identity.schema_generation
                        ),
                        last_observed_schema_revision=(
                            observation.identity.schema_revision
                        ),
                        last_observed_schema_sha256=(
                            observation.identity.schema_sha256
                        ),
                        last_observed_at=observation.observed_at,
                        safe_error_code=after.safe_error_code,
                        started_at=after.started_at,
                        completed_at=after.completed_at,
                        updated_at=database_now,
                    )
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    raise FleetMigrationFenceConflict()

                identity_changed = self._session.execute(
                    sa.update(DatabaseIdentityControlRecord)
                    .where(
                        DatabaseIdentityControlRecord.tenant_id
                        == identity.tenant_id,
                        DatabaseIdentityControlRecord.database_uuid
                        == identity.database_uuid,
                        DatabaseIdentityControlRecord.row_version
                        == identity_version,
                    )
                    .values(
                        expected_schema_generation=(
                            expected_after.schema_generation
                        ),
                        expected_schema_revision=(
                            expected_after.schema_revision
                        ),
                        expected_schema_sha256=expected_after.schema_sha256,
                        observed_schema_generation=(
                            observation.identity.schema_generation
                            if identity_matches
                            else None
                        ),
                        observed_schema_revision=(
                            observation.identity.schema_revision
                            if identity_matches
                            else None
                        ),
                        observed_schema_sha256=(
                            observation.identity.schema_sha256
                            if identity_matches
                            else None
                        ),
                        last_verified_at=observation.observed_at,
                        row_version=identity_version + 1,
                    )
                    .execution_options(synchronize_session=False)
                )
                if identity_changed.rowcount != 1:
                    raise FleetMigrationFenceConflict()

                if route_changed:
                    route_changed_result = self._session.execute(
                        sa.update(TenantDatabase)
                        .where(
                            TenantDatabase.tenant_id == route.tenant_id,
                            TenantDatabase.database_uuid
                            == route.database_uuid,
                            TenantDatabase.row_version == route_version,
                            TenantDatabase.status == "ready",
                        )
                        .values(
                            schema_version=expected_after.schema_revision,
                            row_version=route_version + 1,
                            updated_at=database_now,
                        )
                        .execution_options(synchronize_session=False)
                    )
                    if route_changed_result.rowcount != 1:
                        raise FleetMigrationFenceConflict()
                self._session.flush()
        except FleetMigrationError:
            raise
        except SQLAlchemyError:
            raise FleetMigrationPersistenceError() from None
        self._session.expire(row)
        self._session.expire(route)
        self._session.expire(identity)

    def _queue_replay(
        self,
        row: TenantFleetMigration,
        *,
        migration_uuid: UUID,
        source: FleetSchemaIdentity,
        target: FleetSchemaIdentity,
        queue_digest: bytes,
    ) -> FleetMigrationPersistenceResult:
        current = _domain_target(row)
        if (
            current.migration_uuid != migration_uuid
            or not current.source.same_schema(source)
            or not current.target.same_schema(target)
            or not hmac.compare_digest(
                bytes(row.queue_request_digest),
                queue_digest,
            )
        ):
            raise FleetMigrationFenceConflict()
        return FleetMigrationPersistenceResult(
            target=current,
            route_disposition=_stored_disposition(row),
            created=False,
            idempotent_replay=True,
        )

    def _lock_control_identity(
        self,
        source: FleetSchemaIdentity,
    ) -> tuple[Tenant, TenantDatabase, DatabaseIdentityControlRecord]:
        return self._lock_control_identity_by_ids(
            source.tenant_uuid,
            source.database_uuid,
        )

    def _lock_control_identity_by_ids(
        self,
        tenant_uuid: UUID,
        database_uuid: UUID,
    ) -> tuple[Tenant, TenantDatabase, DatabaseIdentityControlRecord]:
        try:
            tenant = self._session.scalar(
                sa.select(Tenant)
                .where(Tenant.id == str(tenant_uuid))
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
            route = self._session.scalar(
                sa.select(TenantDatabase)
                .where(
                    TenantDatabase.tenant_id == str(tenant_uuid),
                    TenantDatabase.database_uuid == str(database_uuid),
                )
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
            identity = self._session.scalar(
                sa.select(DatabaseIdentityControlRecord)
                .where(
                    DatabaseIdentityControlRecord.tenant_id
                    == str(tenant_uuid),
                    DatabaseIdentityControlRecord.database_uuid
                    == str(database_uuid),
                )
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
        except SQLAlchemyError:
            raise FleetMigrationPersistenceError() from None
        if tenant is None or route is None or identity is None:
            raise FleetMigrationControlIdentityError()
        return tenant, route, identity

    def _lock_target_generation(
        self,
        source: FleetSchemaIdentity,
        target: FleetSchemaIdentity,
    ) -> TenantFleetMigration | None:
        try:
            return self._session.scalar(
                sa.select(TenantFleetMigration)
                .where(
                    TenantFleetMigration.tenant_id
                    == str(source.tenant_uuid),
                    TenantFleetMigration.database_uuid
                    == str(source.database_uuid),
                    TenantFleetMigration.target_schema_generation
                    == target.schema_generation,
                )
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
        except SQLAlchemyError:
            raise FleetMigrationPersistenceError() from None

    def _lock_migration(
        self,
        migration_uuid: UUID,
    ) -> TenantFleetMigration | None:
        try:
            return self._session.scalar(
                sa.select(TenantFleetMigration)
                .where(
                    TenantFleetMigration.migration_uuid
                    == str(migration_uuid)
                )
                .with_for_update()
                .execution_options(autoflush=False, populate_existing=True)
            )
        except SQLAlchemyError:
            raise FleetMigrationPersistenceError() from None

    def _require_control_identity(
        self,
        tenant: Tenant,
        route: TenantDatabase,
        identity: DatabaseIdentityControlRecord,
        *,
        expected: FleetSchemaIdentity,
        queue_source: FleetSchemaIdentity | None = None,
    ) -> None:
        try:
            tenant_uuid = _canonical_uuid(tenant.id)
            database_uuid = _canonical_uuid(route.database_uuid)
            identity_tenant = _canonical_uuid(identity.tenant_id)
            identity_database = _canonical_uuid(identity.database_uuid)
        except (TypeError, ValueError):
            raise FleetMigrationControlIdentityError() from None
        if (
            tenant_uuid != expected.tenant_uuid
            or database_uuid != expected.database_uuid
            or identity_tenant != expected.tenant_uuid
            or identity_database != expected.database_uuid
            or route.tenant_id != tenant.id
            or tenant.status in {"provisioning", "deleted"}
            or route.status != "ready"
            or route.schema_version != expected.schema_revision
            or identity.expected_schema_generation
            != expected.schema_generation
            or not _positive(identity.row_version)
            or not _positive(route.row_version)
        ):
            raise FleetMigrationControlIdentityError()

        expected_metadata = _identity_metadata(
            identity.expected_schema_revision,
            identity.expected_schema_sha256,
        )
        if expected_metadata is not None and not _metadata_matches(
            expected_metadata,
            expected,
        ):
            raise FleetMigrationControlIdentityError()
        if expected_metadata is None and queue_source is None:
            raise FleetMigrationControlIdentityError()

        observed_metadata = _identity_metadata(
            identity.observed_schema_revision,
            identity.observed_schema_sha256,
        )
        if queue_source is not None:
            if identity.observed_schema_generation != queue_source.schema_generation:
                raise FleetMigrationControlIdentityError()
            if observed_metadata is not None and not _metadata_matches(
                observed_metadata,
                queue_source,
            ):
                raise FleetMigrationControlIdentityError()
        elif observed_metadata is None:
            if identity.observed_schema_generation is not None:
                raise FleetMigrationControlIdentityError()
        elif identity.observed_schema_generation is None:
            raise FleetMigrationControlIdentityError()

    def _bind_queue_identity(
        self,
        identity: DatabaseIdentityControlRecord,
        *,
        source: FleetSchemaIdentity,
    ) -> None:
        expected_metadata = _identity_metadata(
            identity.expected_schema_revision,
            identity.expected_schema_sha256,
        )
        observed_metadata = _identity_metadata(
            identity.observed_schema_revision,
            identity.observed_schema_sha256,
        )
        if expected_metadata is not None and observed_metadata is not None:
            return
        before = identity.row_version
        changed = self._session.execute(
            sa.update(DatabaseIdentityControlRecord)
            .where(
                DatabaseIdentityControlRecord.tenant_id == identity.tenant_id,
                DatabaseIdentityControlRecord.database_uuid
                == identity.database_uuid,
                DatabaseIdentityControlRecord.row_version == before,
            )
            .values(
                expected_schema_revision=source.schema_revision,
                expected_schema_sha256=source.schema_sha256,
                observed_schema_revision=source.schema_revision,
                observed_schema_sha256=source.schema_sha256,
                row_version=before + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise FleetMigrationFenceConflict()

    def _prepare(self) -> None:
        transaction = self._session.get_transaction()
        if (
            transaction is None
            or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        ):
            raise FleetMigrationTransactionError()
        dirty = any(
            self._session.is_modified(instance, include_collections=True)
            for instance in self._session.dirty
        )
        if self._session.new or self._session.deleted or dirty:
            raise FleetMigrationTransactionError()
        _materialize_sqlite_outer_transaction(self._session)

    def _now(self) -> datetime:
        try:
            return _as_utc(self._database_clock(self._session))
        except FleetMigrationError:
            raise
        except Exception:
            raise FleetMigrationStoredStateError() from None


def _new_row(
    target: FleetMigrationTarget,
    *,
    queue_digest: bytes,
    database_now: datetime,
) -> TenantFleetMigration:
    return TenantFleetMigration(
        migration_uuid=str(target.migration_uuid),
        tenant_id=str(target.source.tenant_uuid),
        database_uuid=str(target.source.database_uuid),
        source_schema_generation=target.source.schema_generation,
        source_schema_revision=target.source.schema_revision,
        source_schema_sha256=target.source.schema_sha256,
        target_schema_generation=target.target.schema_generation,
        target_schema_revision=target.target.schema_revision,
        target_schema_sha256=target.target.schema_sha256,
        last_observed_tenant_uuid=None,
        last_observed_database_uuid=None,
        last_observed_schema_generation=None,
        last_observed_schema_revision=None,
        last_observed_schema_sha256=None,
        state=target.state.value,
        route_disposition=FleetRouteDisposition.ROUTABLE_PREVIOUS.value,
        attempt_count=target.attempt_count,
        operation_generation=target.operation_generation,
        row_version=target.row_version,
        last_transition="queue",
        last_transition_from_row_version=0,
        queue_request_digest=queue_digest,
        last_request_digest=queue_digest,
        schema_operation_claim_uuid=None,
        schema_operation_owner_id=None,
        schema_operation_generation=None,
        schema_operation_fencing_token=None,
        schema_operation_row_version=None,
        safe_error_code=None,
        queued_at=target.queued_at,
        started_at=None,
        completed_at=None,
        last_observed_at=None,
        created_at=database_now,
        updated_at=database_now,
    )


def _domain_target(row: TenantFleetMigration) -> FleetMigrationTarget:
    try:
        source = FleetSchemaIdentity(
            tenant_uuid=_canonical_uuid(row.tenant_id),
            database_uuid=_canonical_uuid(row.database_uuid),
            schema_generation=row.source_schema_generation,
            schema_revision=row.source_schema_revision,
            schema_sha256=bytes(row.source_schema_sha256),
        )
        target = FleetSchemaIdentity(
            tenant_uuid=source.tenant_uuid,
            database_uuid=source.database_uuid,
            schema_generation=row.target_schema_generation,
            schema_revision=row.target_schema_revision,
            schema_sha256=bytes(row.target_schema_sha256),
        )
        observed = None
        observed_values = (
            row.last_observed_tenant_uuid,
            row.last_observed_database_uuid,
            row.last_observed_schema_generation,
            row.last_observed_schema_revision,
            row.last_observed_schema_sha256,
        )
        if any(value is not None for value in observed_values):
            if any(value is None for value in observed_values):
                raise ValueError("incomplete observation")
            observed = FleetSchemaIdentity(
                tenant_uuid=_canonical_uuid(row.last_observed_tenant_uuid),
                database_uuid=_canonical_uuid(
                    row.last_observed_database_uuid
                ),
                schema_generation=row.last_observed_schema_generation,
                schema_revision=row.last_observed_schema_revision,
                schema_sha256=bytes(row.last_observed_schema_sha256),
            )
        return FleetMigrationTarget(
            migration_uuid=_canonical_uuid(row.migration_uuid),
            source=source,
            target=target,
            state=FleetMigrationState(row.state),
            attempt_count=row.attempt_count,
            operation_generation=row.operation_generation,
            row_version=row.row_version,
            queued_at=_as_utc(row.queued_at),
            started_at=_optional_utc(row.started_at),
            completed_at=_optional_utc(row.completed_at),
            last_observed=observed,
            safe_error_code=row.safe_error_code,
        )
    except FleetMigrationStoredStateError:
        raise
    except (FleetMigrationError, TypeError, ValueError):
        raise FleetMigrationStoredStateError() from None


def _expected_control_identity(
    target: FleetMigrationTarget,
) -> FleetSchemaIdentity:
    return target.target if target.state is FleetMigrationState.SUCCEEDED else target.source


def _stored_disposition(row: TenantFleetMigration) -> FleetRouteDisposition:
    try:
        return FleetRouteDisposition(row.route_disposition)
    except (TypeError, ValueError):
        raise FleetMigrationStoredStateError() from None


def _is_exact_replay(
    row: TenantFleetMigration,
    *,
    operation: str,
    expected_row_version: int,
    request_digest: bytes,
) -> bool:
    try:
        return bool(
            row.row_version == expected_row_version + 1
            and row.last_transition_from_row_version == expected_row_version
            and row.last_transition == operation
            and hmac.compare_digest(
                bytes(row.last_request_digest),
                request_digest,
            )
        )
    except (TypeError, ValueError):
        raise FleetMigrationStoredStateError() from None


def _require_fresh_observation(
    row: TenantFleetMigration,
    *,
    identity: DatabaseIdentityControlRecord,
    current: FleetMigrationTarget,
    observation: FleetMigrationObservation,
    database_now: datetime,
) -> None:
    if observation.observed_at > database_now:
        raise FleetMigrationObservationRejected()
    floors = (
        current.queued_at,
        _optional_utc(row.last_observed_at),
        _optional_utc(identity.last_verified_at),
    )
    if any(
        floor is not None and observation.observed_at < floor
        for floor in floors
    ):
        raise FleetMigrationObservationRejected()


def _queue_request_digest(
    *,
    migration_uuid: UUID,
    source: FleetSchemaIdentity,
    target: FleetSchemaIdentity,
) -> bytes:
    return _digest_payload(
        {
            "operation": "queue",
            "migration_uuid": str(migration_uuid),
            "source": _identity_payload(source),
            "target": _identity_payload(target),
        }
    )


def _transition_request_digest(
    *,
    operation: str,
    migration_uuid: UUID,
    expected_row_version: int,
    expected_operation_generation: int | None,
    observation: FleetMigrationObservation,
    safe_error_code: str | None,
    fence: FleetSchemaOperationFence,
) -> bytes:
    return _digest_payload(
        {
            "operation": operation,
            "migration_uuid": str(migration_uuid),
            "expected_row_version": expected_row_version,
            "expected_operation_generation": expected_operation_generation,
            "observation": {
                **_identity_payload(observation.identity),
                "observed_at": _utc_text(observation.observed_at),
            },
            "safe_error_code": safe_error_code,
            "schema_operation_fence": {
                "claim_id": str(fence.claim_id),
                "owner_id": fence.owner_id,
                "generation": fence.generation,
                "fencing_token": fence.fencing_token,
                "row_version": fence.row_version,
            },
        }
    )


def _identity_payload(value: FleetSchemaIdentity) -> dict[str, object]:
    return {
        "tenant_uuid": str(value.tenant_uuid),
        "database_uuid": str(value.database_uuid),
        "schema_generation": value.schema_generation,
        "schema_revision": value.schema_revision,
        "schema_sha256": value.schema_sha256.hex(),
    }


def _digest_payload(payload: dict[str, object]) -> bytes:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(_REQUEST_DOMAIN + encoded).digest()


def _identity_metadata(
    revision: object | None,
    digest: object | None,
) -> tuple[str, bytes] | None:
    if revision is None and digest is None:
        return None
    if not isinstance(revision, str) or digest is None:
        raise FleetMigrationControlIdentityError()
    try:
        selected = bytes(digest)
    except (TypeError, ValueError):
        raise FleetMigrationControlIdentityError() from None
    if len(selected) != 32:
        raise FleetMigrationControlIdentityError()
    return revision, selected


def _metadata_matches(
    metadata: tuple[str, bytes],
    expected: FleetSchemaIdentity,
) -> bool:
    return bool(
        metadata[0] == expected.schema_revision
        and hmac.compare_digest(metadata[1], expected.schema_sha256)
    )


def _uuid(value: object) -> UUID:
    if not isinstance(value, UUID) or value.int == 0:
        raise FleetMigrationControlIdentityError()
    return value


def _canonical_uuid(value: object) -> UUID:
    if not isinstance(value, str):
        raise ValueError("invalid UUID")
    selected = UUID(value)
    if selected.int == 0 or str(selected) != value:
        raise ValueError("invalid UUID")
    return selected


def _positive(value: object) -> bool:
    return bool(
        not isinstance(value, bool)
        and isinstance(value, int)
        and value >= 1
    )


def _read_database_utc_now(session: Session) -> datetime:
    if session.get_bind().dialect.name in {"mysql", "mariadb"}:
        return _as_utc(session.scalar(sa.text("SELECT UTC_TIMESTAMP(6)")))
    return _as_utc(session.scalar(sa.select(sa.func.current_timestamp())))


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise FleetMigrationStoredStateError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _optional_utc(value: object | None) -> datetime | None:
    return None if value is None else _as_utc(value)


def _utc_text(value: datetime) -> str:
    return _as_utc(value).isoformat(timespec="microseconds").replace(
        "+00:00",
        "Z",
    )


def _materialize_sqlite_outer_transaction(session: Session) -> None:
    connection = session.connection()
    if connection.dialect.name != "sqlite":
        return
    driver_connection = getattr(connection.connection, "driver_connection", None)
    if driver_connection is not None and not driver_connection.in_transaction:
        connection.exec_driver_sql("BEGIN IMMEDIATE")


__all__ = [
    "FleetMigrationControlIdentityError",
    "FleetMigrationPersistenceError",
    "FleetMigrationPersistenceResult",
    "FleetMigrationPersistenceService",
    "FleetMigrationStoredStateError",
    "FleetMigrationTransactionError",
    "FleetSchemaOperationFence",
]
