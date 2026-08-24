"""Safe control-plane settings projection for tenant SF accounts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.models import (
    ProviderAccountClaim,
    ProviderAccountClaimEvent,
    TenantIntegration,
    TenantProviderAccount,
    TenantProviderAccountSecretRevision,
)
from inventory_control.transactions import require_caller_transaction

from .provider_account_service import ProviderAccountStateConflictError


@dataclass(frozen=True, slots=True)
class ProviderAccountSettingsRef:
    provider_account_uuid: str
    integration_uuid: str
    integration_name: str
    label: str
    masked_hint: str
    status: str
    verification_status: str
    warehouse_uuid: str
    binding_revision: int
    last_verified_at: datetime | None
    row_version: int


class TenantProviderAccountQueryService:
    """Read a validated metadata-only projection in the caller transaction."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._session = session

    def list_sf_accounts(
        self,
        *,
        tenant_uuid: str | UUID,
    ) -> tuple[ProviderAccountSettingsRef, ...]:
        self._require_transaction()
        tenant_id = _uuid(tenant_uuid)
        accounts = tuple(
            self._session.execute(
                sa.select(TenantProviderAccount)
                .where(
                    TenantProviderAccount.tenant_id == tenant_id,
                    TenantProviderAccount.provider == "sf",
                )
                .order_by(
                    TenantProviderAccount.created_at.asc(),
                    TenantProviderAccount.id.asc(),
                )
            ).scalars()
        )
        if not accounts:
            return ()
        account_ids = tuple(account.id for account in accounts)
        integrations = {
            row.id: row
            for row in self._session.execute(
                sa.select(TenantIntegration).where(
                    TenantIntegration.tenant_id == tenant_id,
                    TenantIntegration.provider == "sf",
                    TenantIntegration.id.in_(
                        tuple({account.integration_id for account in accounts})
                    ),
                )
            ).scalars()
        }
        revisions = tuple(
            self._session.execute(
                sa.select(TenantProviderAccountSecretRevision)
                .where(
                    TenantProviderAccountSecretRevision.tenant_id == tenant_id,
                    TenantProviderAccountSecretRevision.tenant_provider_account_id.in_(
                        account_ids
                    ),
                )
                .order_by(
                    TenantProviderAccountSecretRevision.tenant_provider_account_id.asc(),
                    TenantProviderAccountSecretRevision.revision_no.desc(),
                )
            ).scalars()
        )
        latest_by_account: dict[str, TenantProviderAccountSecretRevision] = {}
        revision_by_id = {revision.id: revision for revision in revisions}
        for revision in revisions:
            latest_by_account.setdefault(
                revision.tenant_provider_account_id,
                revision,
            )
        claim_ids = tuple(
            sorted(
                {
                    account.current_global_claim_id
                    for account in accounts
                    if account.current_global_claim_id is not None
                }
                | {
                    revision.provider_account_claim_id
                    for revision in latest_by_account.values()
                }
            )
        )
        claims = {
            claim.id: claim
            for claim in self._session.execute(
                sa.select(ProviderAccountClaim).where(
                    ProviderAccountClaim.id.in_(claim_ids)
                )
            ).scalars()
        }
        release_events = tuple(
            self._session.execute(
                sa.select(ProviderAccountClaimEvent)
                .where(
                    ProviderAccountClaimEvent.previous_provider_account_id.in_(
                        account_ids
                    ),
                    ProviderAccountClaimEvent.to_status == "released",
                )
                .order_by(
                    ProviderAccountClaimEvent.previous_provider_account_id.asc(),
                    ProviderAccountClaimEvent.claim_generation.desc(),
                )
            ).scalars()
        )
        release_by_account: dict[str, ProviderAccountClaimEvent] = {}
        for event in release_events:
            release_by_account.setdefault(
                event.previous_provider_account_id,
                event,
            )

        result = []
        for account in accounts:
            integration = integrations.get(account.integration_id)
            latest = latest_by_account.get(account.id)
            current = (
                None
                if account.current_secret_revision_id is None
                else revision_by_id.get(account.current_secret_revision_id)
            )
            selected = current or latest
            claim = (
                None
                if selected is None
                else claims.get(selected.provider_account_claim_id)
            )
            release_event = release_by_account.get(account.id)
            _validate_projection(
                account=account,
                integration=integration,
                selected_revision=selected,
                current_revision=current,
                claim=claim,
                release_event=release_event,
                tenant_id=tenant_id,
            )
            result.append(
                ProviderAccountSettingsRef(
                    provider_account_uuid=account.id,
                    integration_uuid=integration.id,
                    integration_name=integration.name,
                    label=account.label,
                    masked_hint=account.masked_hint,
                    status=account.status,
                    verification_status=selected.verification_status,
                    warehouse_uuid=(
                        claim.current_warehouse_uuid
                        if account.status != "inactive"
                        else release_event.previous_warehouse_uuid
                    ),
                    binding_revision=(
                        claim.active_binding_revision
                        if account.status == "active"
                        else selected.target_binding_revision
                    ),
                    last_verified_at=account.last_verified_at,
                    row_version=account.row_version,
                )
            )
        return tuple(result)

    def _require_transaction(self) -> None:
        require_caller_transaction(
            self._session,
            lambda: RuntimeError("an explicit caller-owned transaction is required"),
        )


def _validate_projection(
    *,
    account,
    integration,
    selected_revision,
    current_revision,
    claim,
    release_event,
    tenant_id,
) -> None:
    base_valid = bool(
        integration is not None
        and integration.id == account.integration_id
        and integration.tenant_id == tenant_id
        and integration.provider == "sf"
        and selected_revision is not None
        and selected_revision.tenant_provider_account_id == account.id
        and selected_revision.tenant_id == tenant_id
        and selected_revision.integration_id == integration.id
        and selected_revision.provider == "sf"
        and claim is not None
        and claim.id == selected_revision.provider_account_claim_id
    )
    if not base_valid:
        raise ProviderAccountStateConflictError()
    if account.status == "active":
        valid = bool(
            current_revision is selected_revision
            and selected_revision.status == "current"
            and selected_revision.verification_status == "succeeded"
            and selected_revision.activated_claim_generation
            == account.current_claim_generation
            and account.current_global_claim_id == claim.id
            and claim.claim_status == "active"
            and claim.claim_generation == account.current_claim_generation
            and claim.current_provider_account_id == account.id
            and claim.current_tenant_id == tenant_id
            and claim.active_binding_revision
            == selected_revision.target_binding_revision
        )
    elif account.status == "pending":
        valid = bool(
            account.current_secret_revision_id is None
            and account.current_global_claim_id is None
            and selected_revision.status == "pending_validation"
            and selected_revision.verification_status
            in {"not_attempted", "submitting", "unknown"}
            and claim.claim_status == "reserved"
            and claim.current_provider_account_id == account.id
            and claim.current_tenant_id == tenant_id
            and claim.current_warehouse_uuid is not None
        )
    elif account.status == "inactive":
        valid = bool(
            current_revision is selected_revision
            and selected_revision.status == "current"
            and selected_revision.verification_status == "succeeded"
            and account.current_global_claim_id is None
            and account.current_claim_generation is None
            and release_event is not None
            and release_event.provider_account_claim_id == claim.id
            and release_event.previous_provider_account_id == account.id
            and release_event.previous_tenant_id == tenant_id
            and release_event.previous_warehouse_uuid is not None
        )
    elif account.status == "verification_failed":
        valid = bool(
            account.current_secret_revision_id is None
            and account.current_global_claim_id is None
            and selected_revision.status == "revoked"
            and selected_revision.verification_status == "failed"
        )
    else:
        valid = False
    if not valid:
        raise ProviderAccountStateConflictError()


def _uuid(value) -> str:
    return str(UUID(str(value)))


__all__ = [
    "ProviderAccountSettingsRef",
    "TenantProviderAccountQueryService",
]
