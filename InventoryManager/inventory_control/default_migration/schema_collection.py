"""Schema-generation and digest collectors backed by the fleet observer."""

from __future__ import annotations

from dataclasses import dataclass

from inventory_control.fleet_migrations import (
    FleetMigrationObservation,
    TenantMigrationExecutionContext,
    TenantMigrationObservationPhase,
    TrustedTenantMigrationObserver,
)

from .collection import MigrationReconciliationCollectionError
from .manifest import DefaultTenantMigrationManifest
from .reconciliation import (
    ReconciliationObservation,
    ReconciliationRequirement,
    ReconciliationScope,
)


class TenantSchemaObservationCollectorSet:
    """Share one post-DDL inventory observation across two policy keys.

    The supplied connection is already selected and independently authorized
    by the fleet-migration composition root.  This adapter neither selects a
    database nor performs DDL and does not include observer diagnostics in its
    stable failure.
    """

    __slots__ = (
        "_connection",
        "_context",
        "_manifest_digest",
        "_observation",
        "_observer",
    )

    def __init__(
        self,
        *,
        observer: TrustedTenantMigrationObserver,
        connection: object,
        context: TenantMigrationExecutionContext,
    ) -> None:
        if (
            not isinstance(observer, TrustedTenantMigrationObserver)
            or not isinstance(context, TenantMigrationExecutionContext)
            or connection is None
            or not context.source.same_database(context.target)
        ):
            raise MigrationReconciliationCollectionError()
        self._observer = observer
        self._connection = connection
        self._context = context
        self._manifest_digest: bytes | None = None
        self._observation: FleetMigrationObservation | None = None

    def collectors(
        self,
        *,
        generation_key: str,
        digest_key: str,
    ) -> tuple["TenantSchemaObservationCollector", ...]:
        selected = (
            TenantSchemaObservationCollector(
                key=generation_key,
                scope=ReconciliationScope.SCHEMA_GENERATION,
                collector_set=self,
            ),
            TenantSchemaObservationCollector(
                key=digest_key,
                scope=ReconciliationScope.SCHEMA_DIGEST,
                collector_set=self,
            ),
        )
        return tuple(sorted(selected, key=lambda item: item.key))

    def observe(
        self,
        manifest: DefaultTenantMigrationManifest,
    ) -> FleetMigrationObservation:
        if not isinstance(manifest, DefaultTenantMigrationManifest):
            raise MigrationReconciliationCollectionError()
        if (
            manifest.tenant_uuid != self._context.target.tenant_uuid
            or manifest.database_uuid != self._context.target.database_uuid
        ):
            raise MigrationReconciliationCollectionError()
        if self._manifest_digest is not None:
            if self._manifest_digest != manifest.digest:
                raise MigrationReconciliationCollectionError()
            if self._observation is None:
                raise MigrationReconciliationCollectionError()
            return self._observation
        try:
            observed = self._observer.observe(
                self._connection,
                phase=TenantMigrationObservationPhase.AFTER_DDL,
                context=self._context,
            )
        except Exception:
            raise MigrationReconciliationCollectionError() from None
        if (
            not isinstance(observed, FleetMigrationObservation)
            or not observed.identity.same_database(self._context.target)
            or observed.identity.schema_revision
            != self._context.target.schema_revision
        ):
            raise MigrationReconciliationCollectionError()
        self._manifest_digest = manifest.digest
        self._observation = observed
        return observed


@dataclass(frozen=True, slots=True)
class TenantSchemaObservationCollector:
    key: str
    scope: ReconciliationScope
    collector_set: TenantSchemaObservationCollectorSet

    def __post_init__(self) -> None:
        if (
            not isinstance(self.key, str)
            or not self.key
            or self.scope
            not in {
                ReconciliationScope.SCHEMA_GENERATION,
                ReconciliationScope.SCHEMA_DIGEST,
            }
            or not isinstance(
                self.collector_set, TenantSchemaObservationCollectorSet
            )
        ):
            raise MigrationReconciliationCollectionError()

    def collect(
        self,
        *,
        manifest: DefaultTenantMigrationManifest,
        requirement: ReconciliationRequirement,
    ) -> ReconciliationObservation:
        if (
            not isinstance(requirement, ReconciliationRequirement)
            or requirement.key != self.key
            or requirement.scope is not self.scope
        ):
            raise MigrationReconciliationCollectionError()
        observation = self.collector_set.observe(manifest)
        value: int | bytes
        if self.scope is ReconciliationScope.SCHEMA_GENERATION:
            value = observation.identity.schema_generation
        else:
            value = observation.identity.schema_sha256
        return ReconciliationObservation(key=self.key, observed=value)


__all__ = [
    "TenantSchemaObservationCollector",
    "TenantSchemaObservationCollectorSet",
]
