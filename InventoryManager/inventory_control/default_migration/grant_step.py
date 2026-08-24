"""D60 subscription step bound to a verified default-migration journal.

The caller owns the final control-database transaction.  This adapter derives
every grant identity from the immutable migration manifest and exposes no
duration parameter.  It refuses to run until backfill/reconciliation evidence
has been durably recorded, while retries after that point return the existing
ledger grant through ``SubscriptionLedgerService`` idempotency.
"""

from __future__ import annotations

from sqlalchemy.orm import Session

from inventory_control.subscriptions import (
    DefaultTenantGrantResult,
    SubscriptionLedgerService,
)

from .manifest import (
    DefaultTenantMigrationManifest,
    MigrationJournal,
    MigrationManifestMismatchError,
    MigrationOrderError,
    MigrationPhase,
)


class DefaultTenantMigrationGrantWriter:
    """Write or replay the manifest's one fixed initial migration grant."""

    def __init__(
        self,
        *,
        ledger_service: SubscriptionLedgerService | None = None,
    ) -> None:
        if ledger_service is not None and not isinstance(
            ledger_service, SubscriptionLedgerService
        ):
            raise TypeError("subscription ledger service is invalid")
        self._ledger = ledger_service or SubscriptionLedgerService()

    def write(
        self,
        session: Session,
        *,
        manifest: DefaultTenantMigrationManifest,
        journal: MigrationJournal,
    ) -> DefaultTenantGrantResult:
        if not isinstance(manifest, DefaultTenantMigrationManifest):
            raise TypeError("manifest is invalid")
        if not isinstance(journal, MigrationJournal):
            raise TypeError("migration journal is invalid")
        if journal.manifest_digest != manifest.digest:
            raise MigrationManifestMismatchError(
                "grant journal belongs to another immutable manifest"
            )
        if MigrationPhase.BACKFILL_VERIFY not in {
            item.phase for item in journal.completed
        }:
            raise MigrationOrderError(
                "default migration grant requires passed backfill reconciliation"
            )
        return self._ledger.record_default_tenant_migration_grant(
            session,
            tenant_uuid=manifest.tenant_uuid,
            database_uuid=manifest.database_uuid,
            baseline_migration_id=manifest.baseline_migration_id,
            migration_idempotency_key=manifest.migration_idempotency_key,
            plan_revision_uuid=manifest.core_plan_revision_uuid,
        )


__all__ = ["DefaultTenantMigrationGrantWriter"]
