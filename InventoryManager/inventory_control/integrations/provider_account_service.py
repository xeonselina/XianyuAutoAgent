"""Caller-transaction service for SF provider-account secret revisions."""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable, TypeVar
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from inventory_control.crypto import (
    CryptoConfigurationError,
    EncryptedEnvelope,
    ProviderAccountFingerprint,
    RootKey,
    derive_provider_account_fingerprint,
)
from inventory_control.database import read_database_utc_value
from inventory_control.domain import EffectiveTenantGate, TenantRole
from inventory_control.evidence import require_sha256_digest
from inventory_control.models.integrations import (
    TenantIntegration,
    TenantIntegrationSecretRevision,
)
from inventory_control.models.provider_accounts import (
    TenantProviderAccount,
    TenantProviderAccountSecretRevision,
)
from inventory_control.transactions import require_caller_transaction
from inventory_control.models.provider_claims import ProviderAccountClaim

from .provider_account_credentials import (
    ACCOUNT_AAD_VERSION,
    ACCOUNT_CRYPTO_VERSION,
    ACCOUNT_SECRET_BUNDLE_VERSION,
    ACCOUNT_SECRET_SCHEMA_VERSION,
    CanonicalSfAccountSecret,
    ProviderAccountCredentialAuthenticationError,
    ProviderAccountCredentialInputError,
    ProviderAccountSecretCryptoContext,
    canonicalize_sf_account_secret,
    decrypt_provider_account_secret,
    encrypt_provider_account_secret,
)
from .service import (
    ProviderValidationOutcome,
    ProviderValidationReconciliation,
)
from .sf_claim import SfAdminClaimProof, SfClaimOwner, SfClaimState
from .sf_claim_service import SfClaimPersistenceService


_SAFE_LABEL = re.compile(r"^[^\x00-\x1f\x7f]{1,120}$")
_SAFE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,63}$")
_T = TypeVar("_T")


class ProviderAccountServiceError(RuntimeError):
    code = "PROVIDER_ACCOUNT_OPERATION_FAILED"
    public_message = "provider account operation failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class ProviderAccountInputError(ProviderAccountServiceError):
    code = "PROVIDER_ACCOUNT_INPUT_INVALID"
    public_message = "provider account input is invalid"


class ProviderAccountNotFoundError(ProviderAccountServiceError):
    code = "PROVIDER_ACCOUNT_NOT_FOUND"
    public_message = "provider account was not found"


class ProviderAccountStateConflictError(ProviderAccountServiceError):
    code = "PROVIDER_ACCOUNT_STATE_CONFLICT"
    public_message = "provider account state changed"


class ProviderAccountIdempotencyConflictError(ProviderAccountServiceError):
    code = "PROVIDER_ACCOUNT_IDEMPOTENCY_CONFLICT"
    public_message = "provider account request conflicts with an earlier request"


class ProviderAccountCredentialUnavailableError(ProviderAccountServiceError):
    code = "PROVIDER_ACCOUNT_CREDENTIAL_UNAVAILABLE"
    public_message = "provider account credential is unavailable"


class ProviderAccountTransactionError(ProviderAccountServiceError):
    code = "PROVIDER_ACCOUNT_TRANSACTION_INVALID"
    public_message = "an explicit caller-owned transaction is required"


class ProviderAccountPersistenceError(ProviderAccountServiceError):
    code = "PROVIDER_ACCOUNT_PERSISTENCE_FAILED"
    public_message = "provider account state could not be persisted"


@dataclass(frozen=True, slots=True)
class ProviderAccountRevisionRef:
    revision_uuid: str
    provider_account_uuid: str
    tenant_uuid: str
    integration_uuid: str
    validation_integration_secret_revision_uuid: str
    revision_no: int
    status: str
    verification_status: str
    expected_claim_generation: int
    target_binding_revision: int
    activated_claim_generation: int | None
    row_version: int
    idempotent_replay: bool = False
    requires_reconciliation: bool = False


@dataclass(frozen=True, slots=True)
class ProviderAccountRef:
    provider_account_uuid: str
    tenant_uuid: str
    integration_uuid: str
    label: str
    masked_hint: str
    status: str
    row_version: int
    idempotent_replay: bool = False


class TenantProviderAccountService:
    """Persist exact account revisions and coordinate claim activation fences."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise ProviderAccountTransactionError()
        self._session = session

    def create_pending_revision(
        self,
        *,
        provider_account_uuid: str | UUID,
        tenant_uuid: str | UUID,
        integration_uuid: str | UUID,
        warehouse_uuid: str | UUID,
        label: str,
        account_secret: str,
        root_key: RootKey,
        claim_uuid: str | UUID,
        expected_claim_generation: int,
        expected_claim_row_version: int,
        target_binding_revision: int,
        expected_warehouse_provider_account_uuid: str | UUID | None,
        expected_warehouse_binding_revision: int | None,
        created_by_user_uuid: str | UUID,
        action_uuid: str | UUID,
        request_digest: bytes,
        idempotency_key: str,
        expected_account_row_version: int | None,
        expected_current_secret_revision_uuid: str | UUID | None,
        expected_current_global_claim_uuid: str | UUID | None,
    ) -> ProviderAccountRevisionRef:
        """Append a pending account value after the caller reserved its claim."""

        self._require_transaction()
        account_id = _uuid(provider_account_uuid)
        tenant_id = _uuid(tenant_uuid)
        integration_id = _uuid(integration_uuid)
        warehouse_id = _uuid(warehouse_uuid)
        selected_claim_id = _uuid(claim_uuid)
        actor_id = _uuid(created_by_user_uuid)
        action_id = _uuid(action_uuid)
        selected_label = _label(label)
        selected_digest = require_sha256_digest(
            request_digest,
            ProviderAccountInputError,
        )
        request_key = _technical_key(idempotency_key)
        expected_claim_gen = _positive(expected_claim_generation)
        expected_claim_row = _positive(expected_claim_row_version)
        target_binding = _positive(target_binding_revision)
        expected_warehouse_account = _optional_uuid(
            expected_warehouse_provider_account_uuid
        )
        expected_warehouse_binding = _optional_positive(
            expected_warehouse_binding_revision
        )
        expected_account_row = _optional_positive(expected_account_row_version)
        expected_current_revision = _optional_uuid(
            expected_current_secret_revision_uuid
        )
        expected_current_claim = _optional_uuid(expected_current_global_claim_uuid)
        if not isinstance(root_key, RootKey):
            raise ProviderAccountInputError()
        try:
            secret = canonicalize_sf_account_secret(account_secret)
            fingerprint = derive_provider_account_fingerprint(
                root_key=root_key,
                provider="sf",
                canonical_account=secret._provider_value(),
            )
        except (CryptoConfigurationError, ProviderAccountCredentialInputError):
            raise ProviderAccountInputError() from None

        existing = self._session.scalar(
            sa.select(TenantProviderAccountSecretRevision)
            .where(
                TenantProviderAccountSecretRevision.request_idempotency_key
                == request_key
            )
            .with_for_update()
        )
        if existing is not None:
            return self._replay_pending(
                existing,
                account_id=account_id,
                claim_id=selected_claim_id,
                request_digest=selected_digest,
                semantics_digest=secret.canonical_semantics_digest,
                expected_claim_generation=expected_claim_gen,
                target_binding_revision=target_binding,
                expected_warehouse_account=expected_warehouse_account,
                expected_warehouse_binding=expected_warehouse_binding,
            )

        integration, integration_revision = self._lock_active_integration(
            integration_id,
            tenant_id=tenant_id,
        )
        self._lock_claim_context(
            selected_claim_id,
            fingerprint=fingerprint,
            account_id=account_id,
            tenant_id=tenant_id,
            warehouse_id=warehouse_id,
            action_id=action_id,
            request_digest=selected_digest,
            expected_generation=expected_claim_gen,
            expected_row_version=expected_claim_row,
            expected_current_claim_id=expected_current_claim,
        )
        account = self._lock_account(account_id)
        account_was_absent = account is None
        if account is None:
            if (
                expected_account_row is not None
                or expected_current_revision is not None
                or expected_current_claim is not None
            ):
                raise ProviderAccountStateConflictError()
            account = TenantProviderAccount(
                id=account_id,
                tenant_id=tenant_id,
                provider="sf",
                integration_id=integration_id,
                label=selected_label,
                masked_hint=secret.masked_hint,
                status="pending",
                row_version=1,
            )
            self._session.add(account)
            self._flush()
            expected_account_row = 1
        elif (
            account.tenant_id != tenant_id
            or account.provider != "sf"
            or account.integration_id != integration_id
            or account.label != selected_label
            or account.row_version != expected_account_row
            or account.current_secret_revision_id != expected_current_revision
            or account.current_global_claim_id != expected_current_claim
            or (
                expected_current_claim is not None
                and account.current_claim_generation != expected_claim_gen
            )
            or account.status not in ("active", "inactive", "verification_failed")
        ):
            raise ProviderAccountStateConflictError()

        revision_no = (
            self._session.scalar(
                sa.select(
                    sa.func.coalesce(
                        sa.func.max(TenantProviderAccountSecretRevision.revision_no),
                        0,
                    )
                ).where(
                    TenantProviderAccountSecretRevision.tenant_provider_account_id
                    == account_id
                )
            )
            + 1
        )
        context = ProviderAccountSecretCryptoContext(
            crypto_context_uuid=str(uuid4()),
            tenant_uuid=tenant_id,
            provider="sf",
            provider_account_uuid=account_id,
            integration_uuid=integration_id,
            revision_no=revision_no,
            account_secret_schema_version=ACCOUNT_SECRET_SCHEMA_VERSION,
            account_secret_bundle_version=ACCOUNT_SECRET_BUNDLE_VERSION,
            canonical_semantics_digest=secret.canonical_semantics_digest,
            provider_account_claim_uuid=selected_claim_id,
            account_fingerprint=fingerprint.digest,
            fingerprint_version=fingerprint.fingerprint_version,
            fingerprint_root_key_version=fingerprint.root_key_version,
            expected_claim_generation=expected_claim_gen,
            root_key_version=root_key.version,
            crypto_version=ACCOUNT_CRYPTO_VERSION,
            aad_version=ACCOUNT_AAD_VERSION,
        )
        envelope = encrypt_provider_account_secret(
            root_key=root_key,
            context=context,
            secret=secret,
        )
        revision = TenantProviderAccountSecretRevision(
            id=str(uuid4()),
            tenant_provider_account_id=account_id,
            tenant_id=tenant_id,
            provider="sf",
            integration_id=integration_id,
            revision_no=revision_no,
            crypto_context_uuid=context.crypto_context_uuid,
            account_secret_schema_version=context.account_secret_schema_version,
            account_secret_bundle_version=context.account_secret_bundle_version,
            canonical_semantics_digest=context.canonical_semantics_digest,
            account_secret_ciphertext=envelope.ciphertext,
            account_secret_nonce=envelope.nonce,
            root_key_version=envelope.root_key_version,
            crypto_version=envelope.crypto_version,
            aad_version=envelope.aad_version,
            provider_account_claim_id=selected_claim_id,
            account_fingerprint=fingerprint.digest,
            fingerprint_version=fingerprint.fingerprint_version,
            fingerprint_root_key_version=fingerprint.root_key_version,
            expected_claim_generation=expected_claim_gen,
            expected_claim_row_version=expected_claim_row,
            target_binding_revision=target_binding,
            expected_warehouse_provider_account_id=expected_warehouse_account,
            expected_warehouse_binding_revision=expected_warehouse_binding,
            masked_hint=secret.masked_hint,
            created_from_action_uuid=action_id,
            created_by_user_uuid=actor_id,
            request_idempotency_key=request_key,
            request_digest=selected_digest,
            expected_account_absent=account_was_absent,
            expected_account_row_version=expected_account_row,
            expected_integration_row_version=integration.row_version,
            validation_integration_secret_revision_id=integration_revision.id,
            expected_current_secret_revision_id=expected_current_revision,
            expected_current_global_claim_id=expected_current_claim,
            row_version=1,
        )
        try:
            with self._session.begin_nested():
                self._session.add(revision)
                self._session.flush()
        except IntegrityError:
            self._session.expire_all()
            winner = self._session.scalar(
                sa.select(TenantProviderAccountSecretRevision).where(
                    TenantProviderAccountSecretRevision.request_idempotency_key
                    == request_key
                )
            )
            if winner is None:
                raise ProviderAccountPersistenceError() from None
            return self._replay_pending(
                winner,
                account_id=account_id,
                claim_id=selected_claim_id,
                request_digest=selected_digest,
                semantics_digest=secret.canonical_semantics_digest,
                expected_claim_generation=expected_claim_gen,
                target_binding_revision=target_binding,
                expected_warehouse_account=expected_warehouse_account,
                expected_warehouse_binding=expected_warehouse_binding,
            )
        return _revision_ref(revision)

    def begin_provider_validation(
        self,
        *,
        revision_uuid: str | UUID,
        attempt_uuid: str | UUID,
        expected_revision_row_version: int,
    ) -> ProviderAccountRevisionRef:
        self._require_transaction()
        revision_id = _uuid(revision_uuid)
        attempt_id = _uuid(attempt_uuid)
        expected_row = _positive(expected_revision_row_version)
        revision = self._lock_revision(revision_id)
        if (
            revision.status != "pending_validation"
            or revision.verification_status != "not_attempted"
            or revision.row_version != expected_row
        ):
            if (
                revision.status == "pending_validation"
                and revision.verification_status == "submitting"
                and revision.verification_attempt_uuid == attempt_id
            ):
                return _revision_ref(revision, replay=True)
            raise ProviderAccountStateConflictError()
        changed = self._session.execute(
            sa.update(TenantProviderAccountSecretRevision)
            .where(
                TenantProviderAccountSecretRevision.id == revision_id,
                TenantProviderAccountSecretRevision.status == "pending_validation",
                TenantProviderAccountSecretRevision.verification_status
                == "not_attempted",
                TenantProviderAccountSecretRevision.row_version == expected_row,
            )
            .values(
                verification_status="submitting",
                verification_attempt_uuid=attempt_id,
                row_version=expected_row + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise ProviderAccountStateConflictError()
        return _revision_ref(self._refresh_revision(revision_id))

    def use_pending_revision_for_validation(
        self,
        *,
        revision_uuid: str | UUID,
        attempt_uuid: str | UUID,
        root_key: RootKey,
        consumer: Callable[[CanonicalSfAccountSecret], _T],
    ) -> _T:
        self._require_transaction()
        revision = self._session.get(
            TenantProviderAccountSecretRevision, _uuid(revision_uuid)
        )
        if (
            revision is None
            or revision.status != "pending_validation"
            or revision.verification_status != "submitting"
            or revision.verification_attempt_uuid != _uuid(attempt_uuid)
            or not callable(consumer)
        ):
            raise ProviderAccountCredentialUnavailableError()
        return consumer(self._decrypt_revision(revision, root_key=root_key))

    def use_unknown_revision_for_reconciliation(
        self,
        *,
        revision_uuid: str | UUID,
        attempt_uuid: str | UUID,
        root_key: RootKey,
        consumer: Callable[[CanonicalSfAccountSecret], _T],
    ) -> _T:
        """Resolve one quarantined revision for a read-only provider query."""

        self._require_transaction()
        revision = self._session.get(
            TenantProviderAccountSecretRevision, _uuid(revision_uuid)
        )
        if (
            revision is None
            or revision.status != "pending_validation"
            or revision.verification_status != "unknown"
            or revision.verification_attempt_uuid != _uuid(attempt_uuid)
            or not callable(consumer)
        ):
            raise ProviderAccountCredentialUnavailableError()
        return consumer(self._decrypt_revision(revision, root_key=root_key))

    def record_provider_validation_result(
        self,
        *,
        revision_uuid: str | UUID,
        attempt_uuid: str | UUID,
        outcome: ProviderValidationOutcome,
        provider_result_digest: bytes,
        safe_code: str,
        proof: SfAdminClaimProof | None = None,
        owner: SfClaimOwner | None = None,
        binding_revision: int | None = None,
        completed_at: datetime | None = None,
    ) -> ProviderAccountRevisionRef:
        self._require_transaction()
        revision_id = _uuid(revision_uuid)
        attempt_id = _uuid(attempt_uuid)
        try:
            selected_outcome = ProviderValidationOutcome(outcome)
        except (TypeError, ValueError):
            raise ProviderAccountInputError() from None
        result_digest = require_sha256_digest(
            provider_result_digest,
            ProviderAccountInputError,
        )
        result_code = _safe_code(safe_code)
        occurred_at = _datetime(completed_at or datetime.now(timezone.utc))
        revision = self._lock_revision(revision_id)
        replay = self._validation_replay(
            revision,
            attempt_id=attempt_id,
            outcome=selected_outcome,
            result_digest=result_digest,
            safe_code=result_code,
        )
        if replay is not None:
            return replay
        if (
            revision.status != "pending_validation"
            or revision.verification_status != "submitting"
            or revision.verification_attempt_uuid != attempt_id
        ):
            raise ProviderAccountStateConflictError()

        return self._apply_validation_result(
            revision,
            outcome=selected_outcome,
            result_digest=result_digest,
            safe_code=result_code,
            occurred_at=occurred_at,
            proof=proof,
            owner=owner,
            binding_revision=binding_revision,
            expected_verification_status="submitting",
        )

    def reconcile_unknown_validation(
        self,
        *,
        revision_uuid: str | UUID,
        attempt_uuid: str | UUID,
        resolution: ProviderValidationReconciliation,
        provider_result_digest: bytes,
        safe_code: str,
        proof: SfAdminClaimProof | None = None,
        owner: SfClaimOwner | None = None,
        binding_revision: int | None = None,
        completed_at: datetime | None = None,
    ) -> ProviderAccountRevisionRef:
        """Resolve one quarantined result without resubmitting the account."""

        self._require_transaction()
        revision_id = _uuid(revision_uuid)
        attempt_id = _uuid(attempt_uuid)
        try:
            selected = ProviderValidationReconciliation(resolution)
        except (TypeError, ValueError):
            raise ProviderAccountInputError() from None
        result_digest = require_sha256_digest(
            provider_result_digest,
            ProviderAccountInputError,
        )
        result_code = _safe_code(safe_code)
        occurred_at = _datetime(completed_at or datetime.now(timezone.utc))
        revision = self._lock_revision(revision_id)
        if (
            revision.status != "pending_validation"
            or revision.verification_status != "unknown"
            or revision.verification_attempt_uuid != attempt_id
        ):
            raise ProviderAccountStateConflictError()
        if selected is ProviderValidationReconciliation.STILL_UNKNOWN:
            if (
                hmac.compare_digest(
                    bytes(revision.verification_result_digest),
                    result_digest,
                )
                and revision.verification_safe_code == result_code
            ):
                return _revision_ref(
                    revision,
                    replay=True,
                    requires_reconciliation=True,
                )
            return self._record_nonfinal_result(
                revision,
                verification_status="unknown",
                result_digest=result_digest,
                safe_code=result_code,
                occurred_at=occurred_at,
                expected_verification_status="unknown",
            )
        outcome = (
            ProviderValidationOutcome.SUCCESS
            if selected is ProviderValidationReconciliation.CONFIRMED_SUCCESS
            else ProviderValidationOutcome.DEFINITIVE_FAILURE
        )
        return self._apply_validation_result(
            revision,
            outcome=outcome,
            result_digest=result_digest,
            safe_code=result_code,
            occurred_at=occurred_at,
            proof=proof,
            owner=owner,
            binding_revision=binding_revision,
            expected_verification_status="unknown",
        )

    def _apply_validation_result(
        self,
        revision: TenantProviderAccountSecretRevision,
        *,
        outcome: ProviderValidationOutcome,
        result_digest: bytes,
        safe_code: str,
        occurred_at: datetime,
        proof: SfAdminClaimProof | None,
        owner: SfClaimOwner | None,
        binding_revision: int | None,
        expected_verification_status: str,
    ) -> ProviderAccountRevisionRef:
        if outcome is ProviderValidationOutcome.UNKNOWN:
            if expected_verification_status != "submitting":
                raise ProviderAccountStateConflictError()
            return self._record_nonfinal_result(
                revision,
                verification_status="unknown",
                result_digest=result_digest,
                safe_code=safe_code,
                occurred_at=occurred_at,
                expected_verification_status=expected_verification_status,
            )
        if outcome is ProviderValidationOutcome.DEFINITIVE_FAILURE:
            result = self._record_nonfinal_result(
                revision,
                verification_status="failed",
                result_digest=result_digest,
                safe_code=safe_code,
                occurred_at=occurred_at,
                expected_verification_status=expected_verification_status,
            )
            account = self._lock_required_account(revision.tenant_provider_account_id)
            if (
                revision.expected_current_secret_revision_id is None
                and account.current_secret_revision_id is None
                and account.row_version == revision.expected_account_row_version
            ):
                changed = self._session.execute(
                    sa.update(TenantProviderAccount)
                    .where(
                        TenantProviderAccount.id == account.id,
                        TenantProviderAccount.row_version == account.row_version,
                        TenantProviderAccount.current_secret_revision_id.is_(None),
                    )
                    .values(
                        status="verification_failed",
                        row_version=account.row_version + 1,
                        updated_at=occurred_at,
                    )
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    raise ProviderAccountStateConflictError()
            return result

        if (
            not isinstance(proof, SfAdminClaimProof)
            or not isinstance(owner, SfClaimOwner)
            or owner.provider_account_uuid != UUID(revision.tenant_provider_account_id)
            or owner.tenant_uuid != UUID(revision.tenant_id)
            or binding_revision is None
        ):
            raise ProviderAccountInputError()
        self._require_current_admin_proof(
            proof,
            owner=owner,
            action_uuid=revision.created_from_action_uuid,
            request_digest=bytes(revision.request_digest),
        )
        integration, integration_revision = self._lock_active_integration(
            revision.integration_id,
            tenant_id=revision.tenant_id,
        )
        if (
            integration.row_version != revision.expected_integration_row_version
            or integration_revision.id
            != revision.validation_integration_secret_revision_id
        ):
            raise ProviderAccountStateConflictError()

        selected_binding_revision = _positive(binding_revision)
        if selected_binding_revision != revision.target_binding_revision:
            raise ProviderAccountStateConflictError()
        claim = self._session.scalar(
            sa.select(ProviderAccountClaim)
            .where(ProviderAccountClaim.id == revision.provider_account_claim_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if claim is None:
            raise ProviderAccountStateConflictError()
        if claim.claim_status == SfClaimState.RESERVED.value:
            claim_result = SfClaimPersistenceService(self._session).activate_claim(
                claim_uuid=revision.provider_account_claim_id,
                owner=owner,
                proof=proof,
                expected_generation=revision.expected_claim_generation,
                expected_row_version=revision.expected_claim_row_version,
                action_uuid=revision.created_from_action_uuid,
                request_digest=bytes(revision.request_digest),
                binding_revision=selected_binding_revision,
            )
            activated_claim_generation = claim_result.generation
            if claim_result.state is not SfClaimState.ACTIVE:
                raise ProviderAccountStateConflictError()
        elif (
            claim.claim_status == SfClaimState.ACTIVE.value
            and claim.claim_generation == revision.expected_claim_generation
            and claim.row_version == revision.expected_claim_row_version
            and claim.current_provider_account_id == revision.tenant_provider_account_id
            and claim.current_tenant_id == revision.tenant_id
            and claim.current_warehouse_uuid == str(owner.warehouse_uuid)
            and claim.active_binding_revision == selected_binding_revision
            and revision.expected_current_global_claim_id == claim.id
        ):
            activated_claim_generation = claim.claim_generation
        else:
            raise ProviderAccountStateConflictError()

        account = self._lock_required_account(revision.tenant_provider_account_id)
        if (
            account.tenant_id != revision.tenant_id
            or account.provider != revision.provider
            or account.integration_id != revision.integration_id
            or account.row_version != revision.expected_account_row_version
            or account.current_secret_revision_id
            != revision.expected_current_secret_revision_id
            or account.current_global_claim_id
            != revision.expected_current_global_claim_id
            or (
                account.current_global_claim_id is not None
                and account.current_claim_generation
                != revision.expected_claim_generation
            )
            or (
                account.current_global_claim_id is not None
                and account.current_global_claim_id
                != revision.provider_account_claim_id
            )
        ):
            raise ProviderAccountStateConflictError()

        previous_revision_id = revision.expected_current_secret_revision_id
        if previous_revision_id is not None:
            previous = self._session.execute(
                sa.update(TenantProviderAccountSecretRevision)
                .where(
                    TenantProviderAccountSecretRevision.id == previous_revision_id,
                    TenantProviderAccountSecretRevision.tenant_provider_account_id
                    == account.id,
                    TenantProviderAccountSecretRevision.status == "current",
                    TenantProviderAccountSecretRevision.verification_status
                    == "succeeded",
                )
                .values(
                    status="superseded",
                    superseded_at=occurred_at,
                    row_version=TenantProviderAccountSecretRevision.row_version + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if previous.rowcount != 1:
                raise ProviderAccountStateConflictError()
        current = self._session.execute(
            sa.update(TenantProviderAccountSecretRevision)
            .where(
                TenantProviderAccountSecretRevision.id == revision.id,
                TenantProviderAccountSecretRevision.status == "pending_validation",
                TenantProviderAccountSecretRevision.verification_status
                == expected_verification_status,
                TenantProviderAccountSecretRevision.row_version == revision.row_version,
            )
            .values(
                status="current",
                verification_status="succeeded",
                verification_result_digest=result_digest,
                verification_safe_code=safe_code,
                verification_completed_at=occurred_at,
                activated_claim_generation=activated_claim_generation,
                activated_at=occurred_at,
                row_version=revision.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if current.rowcount != 1:
            raise ProviderAccountStateConflictError()
        account_changed = self._session.execute(
            sa.update(TenantProviderAccount)
            .where(
                TenantProviderAccount.id == account.id,
                TenantProviderAccount.row_version == account.row_version,
                _nullable_equal(
                    TenantProviderAccount.current_secret_revision_id,
                    previous_revision_id,
                ),
                _nullable_equal(
                    TenantProviderAccount.current_global_claim_id,
                    revision.expected_current_global_claim_id,
                ),
            )
            .values(
                current_secret_revision_id=revision.id,
                current_global_claim_id=revision.provider_account_claim_id,
                current_claim_generation=activated_claim_generation,
                masked_hint=revision.masked_hint,
                status="active",
                last_verified_at=occurred_at,
                row_version=account.row_version + 1,
                updated_at=occurred_at,
            )
            .execution_options(synchronize_session=False)
        )
        if account_changed.rowcount != 1:
            raise ProviderAccountStateConflictError()
        return _revision_ref(self._refresh_revision(revision.id))

    def use_exact_revision(
        self,
        *,
        revision_uuid: str | UUID,
        root_key: RootKey,
        consumer: Callable[[CanonicalSfAccountSecret], _T],
    ) -> _T:
        """Resolve only the stored historical UUID; never follow current pointers."""

        self._require_transaction()
        revision = self._session.get(
            TenantProviderAccountSecretRevision, _uuid(revision_uuid)
        )
        if (
            revision is None
            or revision.status not in ("current", "superseded")
            or not callable(consumer)
        ):
            raise ProviderAccountCredentialUnavailableError()
        return consumer(self._decrypt_revision(revision, root_key=root_key))

    def release_current_claim(
        self,
        *,
        provider_account_uuid: str | UUID,
        warehouse_uuid: str | UUID,
        proof: SfAdminClaimProof,
        action_uuid: str | UUID,
        request_digest: bytes,
        expected_account_row_version: int,
        expected_claim_generation: int,
        expected_claim_row_version: int,
    ) -> ProviderAccountRef:
        """D50 release and account deactivation in one control transaction."""

        self._require_transaction()
        account_id = _uuid(provider_account_uuid)
        warehouse_id = _uuid(warehouse_uuid)
        action_id = _uuid(action_uuid)
        selected_digest = require_sha256_digest(
            request_digest,
            ProviderAccountInputError,
        )
        expected_account_row = _positive(expected_account_row_version)
        expected_claim_gen = _positive(expected_claim_generation)
        expected_claim_row = _positive(expected_claim_row_version)
        if not isinstance(proof, SfAdminClaimProof):
            raise ProviderAccountInputError()
        account = self._lock_required_account(account_id)
        if (
            account.status == "inactive"
            and account.current_global_claim_id is None
            and account.current_claim_generation is None
            and account.row_version == expected_account_row + 1
        ):
            current_revision = (
                None
                if account.current_secret_revision_id is None
                else self._session.get(
                    TenantProviderAccountSecretRevision,
                    account.current_secret_revision_id,
                )
            )
            if current_revision is None:
                raise ProviderAccountStateConflictError()
            claim = self._session.scalar(
                sa.select(ProviderAccountClaim)
                .where(
                    ProviderAccountClaim.id
                    == current_revision.provider_account_claim_id,
                    ProviderAccountClaim.last_action_uuid == action_id,
                    ProviderAccountClaim.last_request_digest == selected_digest,
                    ProviderAccountClaim.claim_status == SfClaimState.RELEASED.value,
                    ProviderAccountClaim.claim_generation == expected_claim_gen + 1,
                )
                .with_for_update()
            )
            if claim is not None:
                return _account_ref(account, replay=True)
            raise ProviderAccountStateConflictError()
        if (
            account.status != "active"
            or account.tenant_id != str(proof.tenant_uuid)
            or account.row_version != expected_account_row
            or account.current_global_claim_id is None
            or account.current_claim_generation != expected_claim_gen
        ):
            raise ProviderAccountStateConflictError()
        claim = self._session.scalar(
            sa.select(ProviderAccountClaim)
            .where(ProviderAccountClaim.id == account.current_global_claim_id)
            .with_for_update()
        )
        if (
            claim is None
            or claim.claim_status != SfClaimState.ACTIVE.value
            or claim.claim_generation != expected_claim_gen
            or claim.row_version != expected_claim_row
            or claim.current_provider_account_id != account.id
            or claim.current_tenant_id != account.tenant_id
            or claim.current_warehouse_uuid != warehouse_id
        ):
            raise ProviderAccountStateConflictError()
        released = SfClaimPersistenceService(self._session).release_claim_by_admin(
            claim_uuid=claim.id,
            proof=proof,
            expected_generation=expected_claim_gen,
            expected_row_version=expected_claim_row,
            action_uuid=action_id,
            request_digest=selected_digest,
        )
        if released.state is not SfClaimState.RELEASED:
            raise ProviderAccountStateConflictError()
        changed = self._session.execute(
            sa.update(TenantProviderAccount)
            .where(
                TenantProviderAccount.id == account.id,
                TenantProviderAccount.status == "active",
                TenantProviderAccount.row_version == expected_account_row,
                TenantProviderAccount.current_global_claim_id == claim.id,
                TenantProviderAccount.current_claim_generation == expected_claim_gen,
            )
            .values(
                current_global_claim_id=None,
                current_claim_generation=None,
                status="inactive",
                row_version=expected_account_row + 1,
                updated_at=self._database_now(),
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise ProviderAccountStateConflictError()
        return _account_ref(self._refresh_account(account.id))

    def _record_nonfinal_result(
        self,
        revision: TenantProviderAccountSecretRevision,
        *,
        verification_status: str,
        result_digest: bytes,
        safe_code: str,
        occurred_at: datetime,
        expected_verification_status: str = "submitting",
    ) -> ProviderAccountRevisionRef:
        values: dict[str, object] = {
            "verification_status": verification_status,
            "verification_result_digest": result_digest,
            "verification_safe_code": safe_code,
            "verification_completed_at": occurred_at,
            "row_version": revision.row_version + 1,
        }
        if verification_status == "failed":
            values.update(status="revoked", revoked_at=occurred_at)
        changed = self._session.execute(
            sa.update(TenantProviderAccountSecretRevision)
            .where(
                TenantProviderAccountSecretRevision.id == revision.id,
                TenantProviderAccountSecretRevision.status == "pending_validation",
                TenantProviderAccountSecretRevision.verification_status
                == expected_verification_status,
                TenantProviderAccountSecretRevision.row_version == revision.row_version,
            )
            .values(**values)
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise ProviderAccountStateConflictError()
        return _revision_ref(
            self._refresh_revision(revision.id),
            requires_reconciliation=verification_status == "unknown",
        )

    def _validation_replay(
        self,
        revision: TenantProviderAccountSecretRevision,
        *,
        attempt_id: str,
        outcome: ProviderValidationOutcome,
        result_digest: bytes,
        safe_code: str,
    ) -> ProviderAccountRevisionRef | None:
        expected = {
            ProviderValidationOutcome.SUCCESS: "succeeded",
            ProviderValidationOutcome.DEFINITIVE_FAILURE: "failed",
            ProviderValidationOutcome.UNKNOWN: "unknown",
        }[outcome]
        if revision.verification_status != expected:
            return None
        if (
            revision.verification_attempt_uuid != attempt_id
            or revision.verification_result_digest is None
            or not hmac.compare_digest(
                bytes(revision.verification_result_digest), result_digest
            )
            or revision.verification_safe_code != safe_code
        ):
            raise ProviderAccountStateConflictError()
        return _revision_ref(
            revision,
            replay=True,
            requires_reconciliation=outcome is ProviderValidationOutcome.UNKNOWN,
        )

    def _replay_pending(
        self,
        revision: TenantProviderAccountSecretRevision,
        *,
        account_id: str,
        claim_id: str,
        request_digest: bytes,
        semantics_digest: bytes,
        expected_claim_generation: int,
        target_binding_revision: int,
        expected_warehouse_account: str | None,
        expected_warehouse_binding: int | None,
    ) -> ProviderAccountRevisionRef:
        if (
            revision.tenant_provider_account_id != account_id
            or revision.provider_account_claim_id != claim_id
            or revision.expected_claim_generation != expected_claim_generation
            or revision.target_binding_revision != target_binding_revision
            or revision.expected_warehouse_provider_account_id
            != expected_warehouse_account
            or revision.expected_warehouse_binding_revision
            != expected_warehouse_binding
            or not hmac.compare_digest(bytes(revision.request_digest), request_digest)
            or not hmac.compare_digest(
                bytes(revision.canonical_semantics_digest), semantics_digest
            )
        ):
            raise ProviderAccountIdempotencyConflictError()
        return _revision_ref(
            revision,
            replay=True,
            requires_reconciliation=revision.verification_status == "unknown",
        )

    def _lock_active_integration(
        self,
        integration_id: str,
        *,
        tenant_id: str,
    ) -> tuple[TenantIntegration, TenantIntegrationSecretRevision]:
        integration = self._session.scalar(
            sa.select(TenantIntegration)
            .where(TenantIntegration.id == integration_id)
            .with_for_update()
        )
        if (
            integration is None
            or integration.tenant_id != tenant_id
            or integration.provider != "sf"
            or integration.status != "active"
            or integration.current_secret_revision_id is None
        ):
            raise ProviderAccountCredentialUnavailableError()
        revision = self._session.get(
            TenantIntegrationSecretRevision,
            integration.current_secret_revision_id,
        )
        if (
            revision is None
            or revision.tenant_integration_id != integration.id
            or revision.tenant_id != tenant_id
            or revision.provider != "sf"
            or revision.status != "current"
            or revision.verification_status != "succeeded"
        ):
            raise ProviderAccountCredentialUnavailableError()
        return integration, revision

    def _lock_claim_context(
        self,
        claim_id: str,
        *,
        fingerprint: ProviderAccountFingerprint,
        account_id: str,
        tenant_id: str,
        warehouse_id: str,
        action_id: str,
        request_digest: bytes,
        expected_generation: int,
        expected_row_version: int,
        expected_current_claim_id: str | None,
    ) -> ProviderAccountClaim:
        claim = self._session.scalar(
            sa.select(ProviderAccountClaim)
            .where(ProviderAccountClaim.id == claim_id)
            .with_for_update()
        )
        expires_at = None if claim is None else claim.reservation_expires_at
        owner_matches = bool(
            claim is not None
            and claim.current_provider_account_id == account_id
            and claim.current_tenant_id == tenant_id
            and claim.current_warehouse_uuid == warehouse_id
        )
        fingerprint_matches = bool(
            claim is not None
            and claim.provider == "sf"
            and hmac.compare_digest(
                bytes(claim.account_fingerprint), fingerprint.digest
            )
            and claim.fingerprint_version == fingerprint.fingerprint_version
            and claim.fingerprint_root_key_version == fingerprint.root_key_version
        )
        fence_matches = bool(
            claim is not None
            and claim.claim_generation == expected_generation
            and claim.row_version == expected_row_version
        )
        reserved_matches = bool(
            claim is not None
            and claim.claim_status == SfClaimState.RESERVED.value
            and claim.reservation_action_uuid == action_id
            and claim.reservation_request_digest is not None
            and hmac.compare_digest(
                bytes(claim.reservation_request_digest), request_digest
            )
            and expires_at is not None
            and _datetime(expires_at) > self._database_now()
        )
        active_matches = bool(
            claim is not None
            and claim.claim_status == SfClaimState.ACTIVE.value
            and expected_current_claim_id == claim.id
            and claim.active_binding_revision is not None
        )
        if not (
            claim is not None
            and fingerprint_matches
            and fence_matches
            and owner_matches
            and (reserved_matches or active_matches)
        ):
            raise ProviderAccountStateConflictError()
        return claim

    def _database_now(self) -> datetime:
        return _datetime(read_database_utc_value(self._session))

    @staticmethod
    def _require_current_admin_proof(
        proof: SfAdminClaimProof,
        *,
        owner: SfClaimOwner,
        action_uuid: str,
        request_digest: bytes,
    ) -> None:
        if (
            proof.tenant_uuid != owner.tenant_uuid
            or proof.role is not TenantRole.ADMIN
            or proof.effective_gate is not EffectiveTenantGate.ACTIVE
            or not proof.otp_consumed
            or proof.otp_purpose not in {"sf_account_bind", "sf_account_rebind"}
            or str(proof.otp_action_uuid) != action_uuid
            or not hmac.compare_digest(proof.otp_request_digest, request_digest)
        ):
            raise ProviderAccountStateConflictError()

    def _lock_account(self, account_id: str) -> TenantProviderAccount | None:
        return self._session.scalar(
            sa.select(TenantProviderAccount)
            .where(TenantProviderAccount.id == account_id)
            .with_for_update()
        )

    def _lock_required_account(self, account_id: str) -> TenantProviderAccount:
        account = self._lock_account(account_id)
        if account is None:
            raise ProviderAccountNotFoundError()
        return account

    def _refresh_account(self, account_id: str) -> TenantProviderAccount:
        return self._session.execute(
            sa.select(TenantProviderAccount)
            .where(TenantProviderAccount.id == account_id)
            .execution_options(populate_existing=True)
        ).scalar_one()

    def _lock_revision(self, revision_id: str) -> TenantProviderAccountSecretRevision:
        revision = self._session.scalar(
            sa.select(TenantProviderAccountSecretRevision)
            .where(TenantProviderAccountSecretRevision.id == revision_id)
            .with_for_update()
        )
        if revision is None:
            raise ProviderAccountNotFoundError()
        return revision

    def _refresh_revision(
        self, revision_id: str
    ) -> TenantProviderAccountSecretRevision:
        return self._session.execute(
            sa.select(TenantProviderAccountSecretRevision)
            .where(TenantProviderAccountSecretRevision.id == revision_id)
            .execution_options(populate_existing=True)
        ).scalar_one()

    def _decrypt_revision(
        self,
        revision: TenantProviderAccountSecretRevision,
        *,
        root_key: RootKey,
    ) -> CanonicalSfAccountSecret:
        try:
            envelope = EncryptedEnvelope(
                nonce=bytes(revision.account_secret_nonce),
                ciphertext=bytes(revision.account_secret_ciphertext),
                root_key_version=revision.root_key_version,
                crypto_version=revision.crypto_version,
                aad_version=revision.aad_version,
            )
            return decrypt_provider_account_secret(
                root_key=root_key,
                context=_crypto_context(revision),
                envelope=envelope,
            )
        except ProviderAccountCredentialAuthenticationError:
            raise
        except Exception:
            raise ProviderAccountCredentialAuthenticationError() from None

    def _flush(self) -> None:
        try:
            self._session.flush()
        except IntegrityError:
            raise ProviderAccountPersistenceError() from None

    def _require_transaction(self) -> None:
        require_caller_transaction(
            self._session,
            ProviderAccountTransactionError,
        )


def _crypto_context(
    revision: TenantProviderAccountSecretRevision,
) -> ProviderAccountSecretCryptoContext:
    return ProviderAccountSecretCryptoContext(
        crypto_context_uuid=revision.crypto_context_uuid,
        tenant_uuid=revision.tenant_id,
        provider=revision.provider,
        provider_account_uuid=revision.tenant_provider_account_id,
        integration_uuid=revision.integration_id,
        revision_no=revision.revision_no,
        account_secret_schema_version=revision.account_secret_schema_version,
        account_secret_bundle_version=revision.account_secret_bundle_version,
        canonical_semantics_digest=bytes(revision.canonical_semantics_digest),
        provider_account_claim_uuid=revision.provider_account_claim_id,
        account_fingerprint=bytes(revision.account_fingerprint),
        fingerprint_version=revision.fingerprint_version,
        fingerprint_root_key_version=revision.fingerprint_root_key_version,
        expected_claim_generation=revision.expected_claim_generation,
        root_key_version=revision.root_key_version,
        crypto_version=revision.crypto_version,
        aad_version=revision.aad_version,
    )


def _revision_ref(
    row: TenantProviderAccountSecretRevision,
    *,
    replay: bool = False,
    requires_reconciliation: bool = False,
) -> ProviderAccountRevisionRef:
    return ProviderAccountRevisionRef(
        revision_uuid=row.id,
        provider_account_uuid=row.tenant_provider_account_id,
        tenant_uuid=row.tenant_id,
        integration_uuid=row.integration_id,
        validation_integration_secret_revision_uuid=(
            row.validation_integration_secret_revision_id
        ),
        revision_no=row.revision_no,
        status=row.status,
        verification_status=row.verification_status,
        expected_claim_generation=row.expected_claim_generation,
        target_binding_revision=row.target_binding_revision,
        activated_claim_generation=row.activated_claim_generation,
        row_version=row.row_version,
        idempotent_replay=replay,
        requires_reconciliation=requires_reconciliation,
    )


def _account_ref(
    row: TenantProviderAccount,
    *,
    replay: bool = False,
) -> ProviderAccountRef:
    return ProviderAccountRef(
        provider_account_uuid=row.id,
        tenant_uuid=row.tenant_id,
        integration_uuid=row.integration_id,
        label=row.label,
        masked_hint=row.masked_hint,
        status=row.status,
        row_version=row.row_version,
        idempotent_replay=replay,
    )


def _uuid(value: str | UUID) -> str:
    try:
        selected = value if isinstance(value, UUID) else UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ProviderAccountInputError() from None
    return str(selected)


def _optional_uuid(value: str | UUID | None) -> str | None:
    return None if value is None else _uuid(value)


def _positive(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProviderAccountInputError()
    return value


def _optional_positive(value: int | None) -> int | None:
    return None if value is None else _positive(value)


def _label(value: str) -> str:
    if (
        not isinstance(value, str)
        or value != value.strip()
        or _SAFE_LABEL.fullmatch(value) is None
    ):
        raise ProviderAccountInputError()
    return value


def _technical_key(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > 128
        or not value.isascii()
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in value)
    ):
        raise ProviderAccountInputError()
    return value


def _safe_code(value: str) -> str:
    if not isinstance(value, str) or _SAFE_CODE.fullmatch(value) is None:
        raise ProviderAccountInputError()
    return value


def _datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise ProviderAccountInputError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _nullable_equal(column: object, value: str | None):
    return column.is_(None) if value is None else column == value
