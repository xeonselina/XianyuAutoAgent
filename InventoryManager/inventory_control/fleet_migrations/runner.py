"""Dedicated-connection boundary for one tenant schema migration.

The runner owns neither the control transaction nor the tenant connection. It
accepts no SQL text, schema name, DSN, or credential.  A trusted process-local
registry supplies a version-locked callable, while a trusted observer reads
the immutable database identity and schema digest through the already-bound
tenant connection.

This is an upgrade boundary for an already identified tenant database, not a
bootstrapper.  The locked pre-DDL observation must equal the bundle's exact
N-1 source identity; an empty or otherwise unknown schema is rejected.

MySQL DDL can implicitly commit before and after a statement.  Consequently
this boundary never claims atomic rollback: once the bundle callable starts,
any error is reported with ``ddl_may_have_committed=True`` and a best-effort
post-DDL observation.  The caller must close the dedicated connection when
the advisory lock could not be confirmed released, then use the observation
with the control-plane persistence state machine to converge or retry.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from enum import Enum
from types import MappingProxyType
from typing import Callable, Mapping, Protocol, runtime_checkable
from uuid import UUID

import sqlalchemy as sa

from .domain import FleetMigrationObservation, FleetSchemaIdentity
from .persistence import FleetSchemaOperationFence


_BUNDLE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,95}$")
_BUNDLE_REVISION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.+-]{0,127}$")
_MANIFEST_DOMAIN = b"inventory-manager/tenant-migration-bundle/v1\x00"
_LOCK_DOMAIN = b"inventory-manager/tenant-migration-lock/v1\x00"
_GET_LOCK = sa.text("SELECT GET_LOCK(:lock_name, :timeout_seconds)")
_RELEASE_LOCK = sa.text("SELECT RELEASE_LOCK(:lock_name)")
MAX_ADVISORY_LOCK_NAME_LENGTH = 64
MAX_ADVISORY_LOCK_TIMEOUT_SECONDS = 30


class TenantMigrationRunnerError(RuntimeError):
    code = "TENANT_MIGRATION_RUNNER_REJECTED"
    public_message = "the tenant schema migration execution was rejected"

    def __init__(
        self,
        *,
        post_observation: FleetMigrationObservation | None = None,
        lock_release_confirmed: bool | None = None,
        ddl_may_have_committed: bool = False,
    ) -> None:
        super().__init__(self.public_message)
        self.post_observation = post_observation
        self.lock_release_confirmed = lock_release_confirmed
        self.ddl_may_have_committed = ddl_may_have_committed

    @property
    def connection_must_close(self) -> bool:
        return self.lock_release_confirmed is False

    def __repr__(self) -> str:
        return f"{type(self).__name__}(code={self.code!r})"


class TenantMigrationPlanError(TenantMigrationRunnerError):
    code = "TENANT_MIGRATION_PLAN_INVALID"
    public_message = "the tenant schema migration plan was rejected"


class TenantMigrationLockUnavailable(TenantMigrationRunnerError):
    code = "TENANT_MIGRATION_LOCK_UNAVAILABLE"
    public_message = "the tenant schema migration lock is unavailable"


class TenantMigrationObservationError(TenantMigrationRunnerError):
    code = "TENANT_MIGRATION_OBSERVATION_INVALID"
    public_message = "the tenant schema observation was rejected"


class TenantMigrationIdentityMismatch(TenantMigrationRunnerError):
    code = "TENANT_MIGRATION_IDENTITY_MISMATCH"
    public_message = "the tenant database identity did not match"


class TenantMigrationFenceError(TenantMigrationRunnerError):
    code = "TENANT_MIGRATION_FENCE_INVALID"
    public_message = "the tenant schema migration fence changed"


class TenantMigrationDdlError(TenantMigrationRunnerError):
    code = "TENANT_MIGRATION_DDL_FAILED"
    public_message = "the tenant schema migration step failed"


class TenantMigrationPostconditionError(TenantMigrationRunnerError):
    code = "TENANT_MIGRATION_POSTCONDITION_FAILED"
    public_message = "the tenant schema migration result was rejected"


class TenantMigrationObservationPhase(str, Enum):
    BEFORE_DDL = "before_ddl"
    AFTER_DDL = "after_ddl"
    AFTER_FAILED_DDL = "after_failed_ddl"


class TenantMigrationFencePhase(str, Enum):
    BEFORE_DDL = "before_ddl"
    AFTER_DDL = "after_ddl"


class _LockAcquisition(str, Enum):
    ACQUIRED = "acquired"
    DENIED = "denied"
    UNKNOWN = "unknown"


@runtime_checkable
class TenantMigrationConnection(Protocol):
    """Minimal dedicated-connection surface used directly by the runner."""

    def scalar(
        self,
        statement: object,
        parameters: Mapping[str, object] | None = None,
    ) -> object: ...


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantMigrationBundleReference:
    bundle_id: str
    bundle_revision: str
    bundle_sha256: bytes

    def __post_init__(self) -> None:
        _bundle_name(self.bundle_id)
        _bundle_revision(self.bundle_revision)
        _digest(self.bundle_sha256)


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantMigrationExecutionContext:
    migration_uuid: UUID
    operation_generation: int
    schema_operation_fence: FleetSchemaOperationFence
    bundle_id: str
    bundle_revision: str
    bundle_sha256: bytes
    source: FleetSchemaIdentity
    target: FleetSchemaIdentity
    ddl_is_transactional: bool = field(default=False, init=False)
    ddl_implicit_commit_possible: bool = field(default=True, init=False)

    def __post_init__(self) -> None:
        _uuid(self.migration_uuid)
        _positive(self.operation_generation)
        if not isinstance(
            self.schema_operation_fence,
            FleetSchemaOperationFence,
        ):
            raise TenantMigrationPlanError()
        _bundle_name(self.bundle_id)
        _bundle_revision(self.bundle_revision)
        _digest(self.bundle_sha256)
        _adjacent_identities(self.source, self.target)


TenantMigrationApply = Callable[
    [TenantMigrationConnection, TenantMigrationExecutionContext],
    None,
]


@dataclass(frozen=True, slots=True, kw_only=True)
class VersionLockedTenantMigrationBundle:
    """An internal build artifact, never constructed from request SQL."""

    bundle_id: str
    bundle_revision: str
    implementation_sha256: bytes
    source: FleetSchemaIdentity
    target: FleetSchemaIdentity
    apply: TenantMigrationApply = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        _bundle_name(self.bundle_id)
        _bundle_revision(self.bundle_revision)
        _digest(self.implementation_sha256)
        _adjacent_identities(self.source, self.target)
        if not callable(self.apply):
            raise TenantMigrationPlanError()

    @property
    def bundle_sha256(self) -> bytes:
        return _bundle_manifest_digest(self)

    def reference(self) -> TenantMigrationBundleReference:
        return TenantMigrationBundleReference(
            bundle_id=self.bundle_id,
            bundle_revision=self.bundle_revision,
            bundle_sha256=self.bundle_sha256,
        )


class StaticTenantMigrationBundleRegistry:
    """Immutable process-local registry populated only by application code."""

    __slots__ = ("_bundles",)

    def __init__(
        self,
        bundles: tuple[VersionLockedTenantMigrationBundle, ...],
    ) -> None:
        if not isinstance(bundles, tuple) or not bundles:
            raise TenantMigrationPlanError()
        selected: dict[
            tuple[str, str],
            VersionLockedTenantMigrationBundle,
        ] = {}
        for bundle in bundles:
            if not isinstance(bundle, VersionLockedTenantMigrationBundle):
                raise TenantMigrationPlanError()
            key = (bundle.bundle_id, bundle.bundle_revision)
            if key in selected:
                raise TenantMigrationPlanError()
            selected[key] = bundle
        self._bundles = MappingProxyType(selected)

    def resolve(
        self,
        reference: TenantMigrationBundleReference,
    ) -> VersionLockedTenantMigrationBundle:
        if not isinstance(reference, TenantMigrationBundleReference):
            raise TenantMigrationPlanError()
        bundle = self._bundles.get(
            (reference.bundle_id, reference.bundle_revision)
        )
        if bundle is None or not hmac.compare_digest(
            bundle.bundle_sha256,
            reference.bundle_sha256,
        ):
            raise TenantMigrationPlanError()
        return bundle


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantMigrationRunRequest:
    migration_uuid: UUID
    operation_generation: int
    schema_operation_fence: FleetSchemaOperationFence
    bundle: TenantMigrationBundleReference

    def __post_init__(self) -> None:
        _uuid(self.migration_uuid)
        _positive(self.operation_generation)
        if not isinstance(
            self.schema_operation_fence,
            FleetSchemaOperationFence,
        ) or not isinstance(self.bundle, TenantMigrationBundleReference):
            raise TenantMigrationPlanError()


@runtime_checkable
class TrustedTenantMigrationObserver(Protocol):
    def observe(
        self,
        connection: TenantMigrationConnection,
        *,
        phase: TenantMigrationObservationPhase,
        context: TenantMigrationExecutionContext,
    ) -> FleetMigrationObservation: ...


@runtime_checkable
class CurrentSchemaOperationFenceValidator(Protocol):
    def require_current(
        self,
        *,
        fence: FleetSchemaOperationFence,
        phase: TenantMigrationFencePhase,
        context: TenantMigrationExecutionContext,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class TenantMigrationRunResult:
    final_observation: FleetMigrationObservation
    context: TenantMigrationExecutionContext
    advisory_lock_release_confirmed: bool
    ddl_is_transactional: bool = field(default=False, init=False)
    ddl_implicit_commit_possible: bool = field(default=True, init=False)

    @property
    def connection_must_close(self) -> bool:
        return not self.advisory_lock_release_confirmed


class TenantMigrationRunner:
    """Run one exact N-1 to N registry bundle on a dedicated connection."""

    __slots__ = (
        "_bundle_registry",
        "_fence_validator",
        "_lock_timeout_seconds",
        "_observer",
    )

    def __init__(
        self,
        *,
        bundle_registry: StaticTenantMigrationBundleRegistry,
        observer: TrustedTenantMigrationObserver,
        fence_validator: CurrentSchemaOperationFenceValidator,
        lock_timeout_seconds: int = 5,
    ) -> None:
        if not isinstance(
            bundle_registry,
            StaticTenantMigrationBundleRegistry,
        ) or not isinstance(observer, TrustedTenantMigrationObserver) or not isinstance(
            fence_validator,
            CurrentSchemaOperationFenceValidator,
        ):
            raise TenantMigrationPlanError()
        if (
            isinstance(lock_timeout_seconds, bool)
            or not isinstance(lock_timeout_seconds, int)
            or not 1
            <= lock_timeout_seconds
            <= MAX_ADVISORY_LOCK_TIMEOUT_SECONDS
        ):
            raise TenantMigrationPlanError()
        self._bundle_registry = bundle_registry
        self._observer = observer
        self._fence_validator = fence_validator
        self._lock_timeout_seconds = lock_timeout_seconds

    def run(
        self,
        *,
        connection: TenantMigrationConnection,
        request: TenantMigrationRunRequest,
    ) -> TenantMigrationRunResult:
        if not isinstance(connection, TenantMigrationConnection) or not isinstance(
            request,
            TenantMigrationRunRequest,
        ):
            raise TenantMigrationPlanError()
        bundle = self._bundle_registry.resolve(request.bundle)
        context = TenantMigrationExecutionContext(
            migration_uuid=request.migration_uuid,
            operation_generation=request.operation_generation,
            schema_operation_fence=request.schema_operation_fence,
            bundle_id=bundle.bundle_id,
            bundle_revision=bundle.bundle_revision,
            bundle_sha256=bundle.bundle_sha256,
            source=bundle.source,
            target=bundle.target,
        )
        lock_name = advisory_lock_name(bundle.source.database_uuid)
        lock_acquisition = _acquire_lock(
            connection,
            lock_name=lock_name,
            timeout_seconds=self._lock_timeout_seconds,
        )
        if lock_acquisition is not _LockAcquisition.ACQUIRED:
            # A driver error can arrive after MySQL acquired the lock but
            # before its result reached this process.  Try to release on that
            # ambiguous path and force connection disposal unless release was
            # positively confirmed.  A normal server-side denial never gave
            # this dedicated connection ownership, so it needs no release.
            release_confirmed = None
            if lock_acquisition is _LockAcquisition.UNKNOWN:
                release_confirmed = _release_lock(
                    connection,
                    lock_name=lock_name,
                )
            raise TenantMigrationLockUnavailable(
                lock_release_confirmed=release_confirmed,
            )

        failure: _PendingFailure | None = None
        final_observation: FleetMigrationObservation | None = None
        ddl_started = False
        try:
            try:
                before = self._observe(
                    connection,
                    phase=TenantMigrationObservationPhase.BEFORE_DDL,
                    context=context,
                )
            except TenantMigrationRunnerError as error:
                failure = _PendingFailure(type(error), None, False)
            else:
                if not bundle.source.same_schema(before.identity):
                    failure = _PendingFailure(
                        TenantMigrationIdentityMismatch,
                        before,
                        False,
                    )
                else:
                    try:
                        self._require_fence(
                            phase=TenantMigrationFencePhase.BEFORE_DDL,
                            context=context,
                        )
                    except TenantMigrationRunnerError as error:
                        failure = _PendingFailure(type(error), before, False)

            if failure is None:
                ddl_started = True
                try:
                    bundle.apply(connection, context)
                except Exception:
                    failure = _PendingFailure(
                        TenantMigrationDdlError,
                        self._optional_observation(
                            connection,
                            phase=(
                                TenantMigrationObservationPhase.AFTER_FAILED_DDL
                            ),
                            context=context,
                        ),
                        True,
                    )

            if failure is None:
                try:
                    self._require_fence(
                        phase=TenantMigrationFencePhase.AFTER_DDL,
                        context=context,
                    )
                except TenantMigrationRunnerError as error:
                    failure = _PendingFailure(
                        type(error),
                        self._optional_observation(
                            connection,
                            phase=TenantMigrationObservationPhase.AFTER_DDL,
                            context=context,
                        ),
                        True,
                    )

            if failure is None:
                try:
                    final_observation = self._observe(
                        connection,
                        phase=TenantMigrationObservationPhase.AFTER_DDL,
                        context=context,
                    )
                except TenantMigrationRunnerError as error:
                    failure = _PendingFailure(type(error), None, True)
                else:
                    if not bundle.target.same_schema(final_observation.identity):
                        failure = _PendingFailure(
                            TenantMigrationPostconditionError,
                            final_observation,
                            True,
                        )
        finally:
            release_confirmed = _release_lock(
                connection,
                lock_name=lock_name,
            )

        if failure is not None:
            raise failure.error_type(
                post_observation=failure.observation,
                lock_release_confirmed=release_confirmed,
                ddl_may_have_committed=(
                    ddl_started or failure.ddl_may_have_committed
                ),
            ) from None
        if final_observation is None:  # pragma: no cover - defensive invariant
            raise TenantMigrationObservationError(
                lock_release_confirmed=release_confirmed,
                ddl_may_have_committed=True,
            )
        return TenantMigrationRunResult(
            final_observation=final_observation,
            context=context,
            advisory_lock_release_confirmed=release_confirmed,
        )

    def _observe(
        self,
        connection: TenantMigrationConnection,
        *,
        phase: TenantMigrationObservationPhase,
        context: TenantMigrationExecutionContext,
    ) -> FleetMigrationObservation:
        try:
            observed = self._observer.observe(
                connection,
                phase=phase,
                context=context,
            )
        except Exception:
            raise TenantMigrationObservationError() from None
        if not isinstance(observed, FleetMigrationObservation):
            raise TenantMigrationObservationError()
        return observed

    def _optional_observation(
        self,
        connection: TenantMigrationConnection,
        *,
        phase: TenantMigrationObservationPhase,
        context: TenantMigrationExecutionContext,
    ) -> FleetMigrationObservation | None:
        try:
            return self._observe(
                connection,
                phase=phase,
                context=context,
            )
        except TenantMigrationRunnerError:
            return None

    def _require_fence(
        self,
        *,
        phase: TenantMigrationFencePhase,
        context: TenantMigrationExecutionContext,
    ) -> None:
        try:
            result = self._fence_validator.require_current(
                fence=context.schema_operation_fence,
                phase=phase,
                context=context,
            )
        except Exception:
            raise TenantMigrationFenceError() from None
        if result is not None:
            raise TenantMigrationFenceError()


@dataclass(frozen=True, slots=True)
class _PendingFailure:
    error_type: type[TenantMigrationRunnerError]
    observation: FleetMigrationObservation | None
    ddl_may_have_committed: bool


def advisory_lock_name(database_uuid: UUID) -> str:
    """Return a bounded non-PII lock name shared by every DB generation."""

    _uuid(database_uuid)
    digest = hashlib.sha256(
        _LOCK_DOMAIN + database_uuid.bytes
    ).hexdigest()[:48]
    selected = f"im:fm:{digest}"
    if len(selected.encode("ascii")) > MAX_ADVISORY_LOCK_NAME_LENGTH:
        raise TenantMigrationPlanError()
    return selected


def _acquire_lock(
    connection: TenantMigrationConnection,
    *,
    lock_name: str,
    timeout_seconds: int,
) -> _LockAcquisition:
    try:
        result = connection.scalar(
            _GET_LOCK,
            {
                "lock_name": lock_name,
                "timeout_seconds": timeout_seconds,
            },
        )
    except Exception:
        return _LockAcquisition.UNKNOWN
    if not isinstance(result, bool) and result == 1:
        return _LockAcquisition.ACQUIRED
    if not isinstance(result, bool) and result == 0:
        return _LockAcquisition.DENIED
    return _LockAcquisition.UNKNOWN


def _release_lock(
    connection: TenantMigrationConnection,
    *,
    lock_name: str,
) -> bool:
    try:
        result = connection.scalar(
            _RELEASE_LOCK,
            {"lock_name": lock_name},
        )
    except Exception:
        return False
    return bool(not isinstance(result, bool) and result == 1)


def _bundle_manifest_digest(
    bundle: VersionLockedTenantMigrationBundle,
) -> bytes:
    payload = {
        "bundle_id": bundle.bundle_id,
        "bundle_revision": bundle.bundle_revision,
        "implementation_sha256": bundle.implementation_sha256.hex(),
        "source": _identity_payload(bundle.source),
        "target": _identity_payload(bundle.target),
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(_MANIFEST_DOMAIN + encoded).digest()


def _identity_payload(value: FleetSchemaIdentity) -> dict[str, object]:
    return {
        "tenant_uuid": str(value.tenant_uuid),
        "database_uuid": str(value.database_uuid),
        "schema_generation": value.schema_generation,
        "schema_revision": value.schema_revision,
        "schema_sha256": value.schema_sha256.hex(),
    }


def _adjacent_identities(
    source: object,
    target: object,
) -> None:
    if (
        not isinstance(source, FleetSchemaIdentity)
        or not isinstance(target, FleetSchemaIdentity)
        or not source.same_database(target)
        or target.schema_generation != source.schema_generation + 1
        or source.schema_revision == target.schema_revision
        or hmac.compare_digest(source.schema_sha256, target.schema_sha256)
    ):
        raise TenantMigrationPlanError()


def _bundle_name(value: object) -> None:
    if not isinstance(value, str) or _BUNDLE_NAME.fullmatch(value) is None:
        raise TenantMigrationPlanError()


def _bundle_revision(value: object) -> None:
    if not isinstance(value, str) or _BUNDLE_REVISION.fullmatch(value) is None:
        raise TenantMigrationPlanError()


def _digest(value: object) -> None:
    if not isinstance(value, bytes) or len(value) != 32:
        raise TenantMigrationPlanError()


def _uuid(value: object) -> None:
    if not isinstance(value, UUID) or value.int == 0:
        raise TenantMigrationPlanError()


def _positive(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TenantMigrationPlanError()


__all__ = [
    "CurrentSchemaOperationFenceValidator",
    "MAX_ADVISORY_LOCK_NAME_LENGTH",
    "MAX_ADVISORY_LOCK_TIMEOUT_SECONDS",
    "StaticTenantMigrationBundleRegistry",
    "TenantMigrationBundleReference",
    "TenantMigrationConnection",
    "TenantMigrationDdlError",
    "TenantMigrationExecutionContext",
    "TenantMigrationFenceError",
    "TenantMigrationFencePhase",
    "TenantMigrationIdentityMismatch",
    "TenantMigrationLockUnavailable",
    "TenantMigrationObservationError",
    "TenantMigrationObservationPhase",
    "TenantMigrationPlanError",
    "TenantMigrationPostconditionError",
    "TenantMigrationRunRequest",
    "TenantMigrationRunResult",
    "TenantMigrationRunner",
    "TenantMigrationRunnerError",
    "TrustedTenantMigrationObserver",
    "VersionLockedTenantMigrationBundle",
    "advisory_lock_name",
]
