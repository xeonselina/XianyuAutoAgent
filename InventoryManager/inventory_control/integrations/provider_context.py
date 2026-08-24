"""Fail-closed SF credential-context resolution for new and historical work."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session, SessionTransactionOrigin

from inventory_control.models import (
    ProviderAccountClaim,
    TenantIntegration,
    TenantIntegrationSecretRevision,
    TenantProviderAccount,
    TenantProviderAccountSecretRevision,
)


class ProviderContextError(RuntimeError):
    code = "SF_PROVIDER_CONTEXT_INVALID"
    public_message = "SF provider context is unavailable"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class ProviderContextTransactionError(ProviderContextError):
    code = "SF_PROVIDER_CONTEXT_TRANSACTION_INVALID"
    public_message = "an explicit provider-context transaction is required"


@dataclass(frozen=True, slots=True)
class SfProviderExecutionContext:
    tenant_uuid: str
    warehouse_uuid: str
    provider_account_uuid: str
    integration_uuid: str
    integration_secret_revision_uuid: str
    provider_account_secret_revision_uuid: str
    global_claim_uuid: str
    claim_generation: int
    binding_revision: int
    masked_account_hint: str
    historical: bool = False


class SfProviderContextResolver:
    """Resolve exact IDs only; decryption remains in the provider boundary."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise ProviderContextTransactionError()
        self._session = session

    def resolve_current(
        self,
        *,
        tenant_uuid: str | UUID,
        warehouse_uuid: str | UUID,
        provider_account_uuid: str | UUID,
        binding_revision: int,
    ) -> SfProviderExecutionContext:
        """Resolve a new-operation context from one trusted warehouse binding."""

        self._require_transaction()
        tenant_id = _uuid(tenant_uuid)
        warehouse_id = _uuid(warehouse_uuid)
        account_id = _uuid(provider_account_uuid)
        selected_binding_revision = _positive(binding_revision)
        account = self._session.scalar(
            sa.select(TenantProviderAccount)
            .where(TenantProviderAccount.id == account_id)
            .with_for_update()
        )
        if (
            account is None
            or account.tenant_id != tenant_id
            or account.provider != "sf"
            or account.status != "active"
            or account.current_secret_revision_id is None
            or account.current_global_claim_id is None
            or account.current_claim_generation is None
        ):
            raise ProviderContextError()
        claim = self._session.scalar(
            sa.select(ProviderAccountClaim)
            .where(ProviderAccountClaim.id == account.current_global_claim_id)
            .with_for_update()
        )
        account_revision = self._session.scalar(
            sa.select(TenantProviderAccountSecretRevision)
            .where(
                TenantProviderAccountSecretRevision.id
                == account.current_secret_revision_id
            )
            .with_for_update()
        )
        integration = self._session.scalar(
            sa.select(TenantIntegration)
            .where(TenantIntegration.id == account.integration_id)
            .with_for_update()
        )
        integration_revision = (
            None
            if integration is None or integration.current_secret_revision_id is None
            else self._session.scalar(
                sa.select(TenantIntegrationSecretRevision)
                .where(
                    TenantIntegrationSecretRevision.id
                    == integration.current_secret_revision_id
                )
                .with_for_update()
            )
        )
        if not _current_facts_match(
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            account=account,
            account_revision=account_revision,
            claim=claim,
            integration=integration,
            integration_revision=integration_revision,
            binding_revision=selected_binding_revision,
        ):
            raise ProviderContextError()
        return SfProviderExecutionContext(
            tenant_uuid=tenant_id,
            warehouse_uuid=warehouse_id,
            provider_account_uuid=account.id,
            integration_uuid=integration.id,
            integration_secret_revision_uuid=integration_revision.id,
            provider_account_secret_revision_uuid=account_revision.id,
            global_claim_uuid=claim.id,
            claim_generation=claim.claim_generation,
            binding_revision=selected_binding_revision,
            masked_account_hint=account_revision.masked_hint,
        )

    def resolve_historical(
        self,
        *,
        tenant_uuid: str | UUID,
        warehouse_uuid: str | UUID,
        binding_revision: int,
        integration_secret_revision_uuid: str | UUID,
        provider_account_secret_revision_uuid: str | UUID,
    ) -> SfProviderExecutionContext:
        """Resolve shipment-frozen revisions without following current pointers."""

        self._require_transaction()
        tenant_id = _uuid(tenant_uuid)
        warehouse_id = _uuid(warehouse_uuid)
        selected_binding_revision = _positive(binding_revision)
        integration_revision_id = _uuid(integration_secret_revision_uuid)
        account_revision_id = _uuid(provider_account_secret_revision_uuid)
        account_revision = self._session.scalar(
            sa.select(TenantProviderAccountSecretRevision)
            .where(TenantProviderAccountSecretRevision.id == account_revision_id)
            .with_for_update()
        )
        integration_revision = self._session.scalar(
            sa.select(TenantIntegrationSecretRevision)
            .where(TenantIntegrationSecretRevision.id == integration_revision_id)
            .with_for_update()
        )
        if (
            account_revision is None
            or integration_revision is None
            or account_revision.tenant_id != tenant_id
            or integration_revision.tenant_id != tenant_id
            or account_revision.provider != "sf"
            or integration_revision.provider != "sf"
            or account_revision.integration_id
            != integration_revision.tenant_integration_id
            or account_revision.status not in ("current", "superseded")
            or integration_revision.status not in ("current", "superseded")
            or account_revision.verification_status != "succeeded"
            or integration_revision.verification_status != "succeeded"
            or account_revision.activated_claim_generation is None
        ):
            raise ProviderContextError()
        return SfProviderExecutionContext(
            tenant_uuid=tenant_id,
            warehouse_uuid=warehouse_id,
            provider_account_uuid=account_revision.tenant_provider_account_id,
            integration_uuid=account_revision.integration_id,
            integration_secret_revision_uuid=integration_revision.id,
            provider_account_secret_revision_uuid=account_revision.id,
            global_claim_uuid=account_revision.provider_account_claim_id,
            claim_generation=account_revision.activated_claim_generation,
            binding_revision=selected_binding_revision,
            masked_account_hint=account_revision.masked_hint,
            historical=True,
        )

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        if (
            transaction is None
            or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        ):
            raise ProviderContextTransactionError()


def _current_facts_match(
    *,
    tenant_id: str,
    warehouse_id: str,
    account: TenantProviderAccount,
    account_revision: TenantProviderAccountSecretRevision | None,
    claim: ProviderAccountClaim | None,
    integration: TenantIntegration | None,
    integration_revision: TenantIntegrationSecretRevision | None,
    binding_revision: int,
) -> bool:
    return bool(
        claim is not None
        and account_revision is not None
        and integration is not None
        and integration_revision is not None
        and claim.provider == "sf"
        and claim.claim_status == "active"
        and claim.current_tenant_id == tenant_id
        and claim.current_warehouse_uuid == warehouse_id
        and claim.current_provider_account_id == account.id
        and claim.claim_generation == account.current_claim_generation
        and claim.active_binding_revision == binding_revision
        and account_revision.tenant_provider_account_id == account.id
        and account_revision.tenant_id == tenant_id
        and account_revision.provider == "sf"
        and account_revision.integration_id == account.integration_id
        and account_revision.provider_account_claim_id == claim.id
        and account_revision.status == "current"
        and account_revision.verification_status == "succeeded"
        and account_revision.activated_claim_generation == claim.claim_generation
        and account_revision.masked_hint == account.masked_hint
        and account_revision.fingerprint_version == claim.fingerprint_version
        and account_revision.fingerprint_root_key_version
        == claim.fingerprint_root_key_version
        and hmac.compare_digest(
            bytes(account_revision.account_fingerprint),
            bytes(claim.account_fingerprint),
        )
        and integration.tenant_id == tenant_id
        and integration.provider == "sf"
        and integration.status == "active"
        and integration.current_secret_revision_id == integration_revision.id
        and integration_revision.tenant_integration_id == integration.id
        and integration_revision.tenant_id == tenant_id
        and integration_revision.provider == "sf"
        and integration_revision.status == "current"
        and integration_revision.verification_status == "succeeded"
    )


def _uuid(value: str | UUID) -> str:
    try:
        selected = value if isinstance(value, UUID) else UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ProviderContextError() from None
    return str(selected)


def _positive(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProviderContextError()
    return value
