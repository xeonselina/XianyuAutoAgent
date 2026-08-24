"""Control-plane coordinator for one D48-authorized SF account submission."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session, SessionTransactionOrigin

from inventory_control.crypto import (
    CryptoConfigurationError,
    RootKey,
    derive_provider_account_fingerprint,
)
from inventory_control.models import ProviderAccountClaim, TenantProviderAccount

from .provider_account_credentials import (
    ProviderAccountCredentialInputError,
    canonicalize_sf_account_secret,
)
from .provider_account_service import (
    ProviderAccountInputError,
    ProviderAccountRevisionRef,
    ProviderAccountStateConflictError,
    ProviderAccountTransactionError,
    TenantProviderAccountService,
)
from .sf_claim import SfAdminClaimProof, SfClaimOwner
from .sf_claim_service import (
    SfClaimPersistenceResult,
    SfClaimPersistenceService,
)


@dataclass(frozen=True, slots=True)
class ProviderAccountBindingSubmission:
    revision: ProviderAccountRevisionRef
    claim_uuid: str
    claim_generation: int
    claim_row_version: int
    claim_was_reserved: bool
    idempotent_replay: bool


class TenantProviderAccountBindingCoordinator:
    """Compose claim reservation/reuse and encrypted revision persistence."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise ProviderAccountTransactionError()
        self._session = session

    def submit(
        self,
        *,
        provider_account_uuid: str | UUID,
        tenant_uuid: str | UUID,
        integration_uuid: str | UUID,
        warehouse_uuid: str | UUID,
        label: str,
        account_secret: str,
        root_key: RootKey,
        proof: SfAdminClaimProof,
        action_uuid: str | UUID,
        request_digest: bytes,
        idempotency_key: str,
        reservation_expires_at: datetime,
        expected_account_row_version: int | None,
        expected_current_secret_revision_uuid: str | UUID | None,
        expected_current_global_claim_uuid: str | UUID | None,
        target_binding_revision: int,
        expected_warehouse_provider_account_uuid: str | UUID | None,
        expected_warehouse_binding_revision: int | None,
    ) -> ProviderAccountBindingSubmission:
        self._require_transaction()
        account_id = _uuid(provider_account_uuid)
        tenant_id = _uuid(tenant_uuid)
        warehouse_id = _uuid(warehouse_uuid)
        if not isinstance(root_key, RootKey) or not isinstance(
            proof, SfAdminClaimProof
        ):
            raise ProviderAccountInputError()
        try:
            canonical = canonicalize_sf_account_secret(account_secret)
            fingerprint = derive_provider_account_fingerprint(
                root_key=root_key,
                provider="sf",
                canonical_account=canonical._provider_value(),
            )
        except (
            CryptoConfigurationError,
            ProviderAccountCredentialInputError,
        ):
            raise ProviderAccountInputError() from None
        owner = SfClaimOwner(
            tenant_uuid=UUID(tenant_id),
            provider_account_uuid=UUID(account_id),
            warehouse_uuid=UUID(warehouse_id),
        )
        account = self._session.scalar(
            sa.select(TenantProviderAccount)
            .where(TenantProviderAccount.id == account_id)
            .with_for_update()
        )
        active_claim = self._reusable_active_claim(
            account=account,
            owner=owner,
            fingerprint=fingerprint,
            expected_account_row_version=expected_account_row_version,
            expected_current_secret_revision_uuid=(
                expected_current_secret_revision_uuid
            ),
            expected_current_global_claim_uuid=(
                expected_current_global_claim_uuid
            ),
        )
        reserved = active_claim is None
        claim_result = (
            self._reserve_claim(
                fingerprint=fingerprint,
                owner=owner,
                proof=proof,
                action_uuid=action_uuid,
                request_digest=request_digest,
                reservation_expires_at=reservation_expires_at,
            )
            if reserved
            else None
        )
        claim_uuid = (
            str(claim_result.claim_uuid)
            if claim_result is not None
            else active_claim.id
        )
        claim_generation = (
            claim_result.generation
            if claim_result is not None
            else active_claim.claim_generation
        )
        claim_row_version = (
            claim_result.row_version
            if claim_result is not None
            else active_claim.row_version
        )
        revision = TenantProviderAccountService(
            self._session
        ).create_pending_revision(
            provider_account_uuid=account_id,
            tenant_uuid=tenant_id,
            integration_uuid=integration_uuid,
            warehouse_uuid=warehouse_id,
            label=label,
            account_secret=account_secret,
            root_key=root_key,
            claim_uuid=claim_uuid,
            expected_claim_generation=claim_generation,
            expected_claim_row_version=claim_row_version,
            target_binding_revision=target_binding_revision,
            expected_warehouse_provider_account_uuid=(
                expected_warehouse_provider_account_uuid
            ),
            expected_warehouse_binding_revision=(
                expected_warehouse_binding_revision
            ),
            created_by_user_uuid=proof.actor_user_uuid,
            action_uuid=action_uuid,
            request_digest=request_digest,
            idempotency_key=idempotency_key,
            expected_account_row_version=expected_account_row_version,
            expected_current_secret_revision_uuid=(
                expected_current_secret_revision_uuid
            ),
            expected_current_global_claim_uuid=(
                expected_current_global_claim_uuid
            ),
        )
        return ProviderAccountBindingSubmission(
            revision=revision,
            claim_uuid=claim_uuid,
            claim_generation=claim_generation,
            claim_row_version=claim_row_version,
            claim_was_reserved=reserved,
            idempotent_replay=revision.idempotent_replay or bool(
                claim_result is not None and claim_result.idempotent_replay
            ),
        )

    def _reserve_claim(
        self,
        *,
        fingerprint,
        owner,
        proof,
        action_uuid,
        request_digest,
        reservation_expires_at,
    ) -> SfClaimPersistenceResult:
        current = self._session.scalar(
            sa.select(ProviderAccountClaim)
            .where(
                ProviderAccountClaim.provider == fingerprint.provider,
                ProviderAccountClaim.account_fingerprint == fingerprint.digest,
            )
            .with_for_update()
        )
        expected_generation = 1 if current is None else current.claim_generation
        expected_row_version = 1 if current is None else current.row_version
        return SfClaimPersistenceService(self._session).reserve_claim(
            fingerprint=fingerprint,
            owner=owner,
            proof=proof,
            expected_generation=expected_generation,
            expected_row_version=expected_row_version,
            action_uuid=action_uuid,
            request_digest=request_digest,
            reservation_expires_at=_datetime(reservation_expires_at),
        )

    def _reusable_active_claim(
        self,
        *,
        account,
        owner,
        fingerprint,
        expected_account_row_version,
        expected_current_secret_revision_uuid,
        expected_current_global_claim_uuid,
    ) -> ProviderAccountClaim | None:
        if account is None or account.status != "active":
            return None
        expected_revision = _optional_uuid(expected_current_secret_revision_uuid)
        expected_claim = _optional_uuid(expected_current_global_claim_uuid)
        if (
            account.tenant_id != str(owner.tenant_uuid)
            or account.row_version != expected_account_row_version
            or account.current_secret_revision_id != expected_revision
            or account.current_global_claim_id != expected_claim
            or expected_claim is None
        ):
            raise ProviderAccountStateConflictError()
        claim = self._session.scalar(
            sa.select(ProviderAccountClaim)
            .where(ProviderAccountClaim.id == expected_claim)
            .with_for_update()
        )
        if (
            claim is None
            or claim.claim_status != "active"
            or claim.current_provider_account_id != account.id
            or claim.current_tenant_id != account.tenant_id
            or claim.current_warehouse_uuid != str(owner.warehouse_uuid)
            or claim.claim_generation != account.current_claim_generation
            or claim.fingerprint_version != fingerprint.fingerprint_version
            or claim.fingerprint_root_key_version
            != fingerprint.root_key_version
            or not hmac.compare_digest(
                bytes(claim.account_fingerprint), fingerprint.digest
            )
        ):
            raise ProviderAccountStateConflictError()
        return claim

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        if (
            transaction is None
            or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        ):
            raise ProviderAccountTransactionError()


def _uuid(value) -> str:
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError):
        raise ProviderAccountInputError() from None


def _optional_uuid(value) -> str | None:
    return None if value is None else _uuid(value)


def _datetime(value) -> datetime:
    if not isinstance(value, datetime):
        raise ProviderAccountInputError()
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "ProviderAccountBindingSubmission",
    "TenantProviderAccountBindingCoordinator",
]
