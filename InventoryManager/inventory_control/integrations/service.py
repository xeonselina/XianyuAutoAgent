"""Caller-transaction service for immutable tenant provider credentials.

This module performs no provider I/O and never commits or rolls back.  A
caller must open an explicit control-database transaction and must roll that
transaction back when a mutation raises.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Mapping, TypeVar
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, SessionTransactionOrigin

from inventory_control.crypto import CryptoCodecV1, EncryptedEnvelope, RootKey
from inventory_control.models.foundation import Tenant
from inventory_control.models.integrations import (
    TenantIntegration,
    TenantIntegrationSecretEnvelopeEvent,
    TenantIntegrationSecretRevision,
    TenantProviderDefault,
)

from .credentials import (
    AAD_VERSION,
    CREDENTIAL_BUNDLE_VERSION,
    CREDENTIAL_SCHEMA_VERSION,
    CRYPTO_VERSION,
    CanonicalProviderCredentialBundle,
    IntegrationSecretCryptoContext,
    canonicalize_provider_credentials,
    decrypt_provider_credentials,
    encrypt_provider_credentials,
    require_provider,
)
from .errors import (
    IntegrationCredentialAuthenticationError,
    IntegrationCredentialUnavailableError,
    IntegrationIdempotencyConflictError,
    IntegrationInputError,
    IntegrationNotFoundError,
    IntegrationPersistenceError,
    IntegrationStateConflictError,
    IntegrationTransactionRequiredError,
    IntegrationValidationUnknownError,
)


_SAFE_NAME = re.compile(r"^[^\x00-\x1f\x7f]{1,120}$")
_SAFE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,63}$")
_FORBIDDEN_CONFIG_KEY_PARTS = (
    "secret",
    "password",
    "passwd",
    "token",
    "credential",
    "checkword",
    "api_key",
    "partner_id",
    "app_key",
    "app_id",
)
_MAX_CONFIG_BYTES = 16_384
_T = TypeVar("_T")


class ProviderValidationOutcome(str, Enum):
    SUCCESS = "success"
    DEFINITIVE_FAILURE = "definitive_failure"
    UNKNOWN = "unknown"


class ProviderValidationReconciliation(str, Enum):
    CONFIRMED_SUCCESS = "confirmed_success"
    CONFIRMED_FAILURE = "confirmed_failure"
    STILL_UNKNOWN = "still_unknown"


@dataclass(frozen=True, slots=True)
class TenantIntegrationRef:
    integration_uuid: str
    tenant_uuid: str
    provider: str
    name: str
    status: str
    current_secret_revision_uuid: str | None
    row_version: int
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class IntegrationSecretRevisionRef:
    revision_uuid: str
    integration_uuid: str
    tenant_uuid: str
    provider: str
    revision_no: int
    status: str
    verification_status: str
    envelope_generation: int
    envelope_row_version: int
    row_version: int
    idempotent_replay: bool = False
    requires_reconciliation: bool = False


@dataclass(frozen=True, slots=True)
class IntegrationEnvelopeRotationRef:
    event_uuid: str
    revision_uuid: str
    envelope_generation: int
    root_key_version: int
    idempotent_replay: bool = False


@dataclass(frozen=True, slots=True)
class TenantProviderDefaultRef:
    tenant_uuid: str
    provider: str
    integration_uuid: str
    row_version: int
    idempotent_replay: bool = False


class TenantIntegrationService:
    """Control-plane mutations with exact-revision and CAS semantics."""

    def __init__(self, session: Session) -> None:
        if not isinstance(session, Session):
            raise IntegrationInputError()
        self._session = session

    def create_integration(
        self,
        *,
        integration_uuid: str | UUID,
        tenant_uuid: str | UUID,
        provider: str,
        name: str,
        config: Mapping[str, Any] | None = None,
    ) -> TenantIntegrationRef:
        """Create or replay a caller-preallocated stable integration identity."""

        self._require_transaction()
        integration_id = _uuid(integration_uuid)
        tenant_id = _uuid(tenant_uuid)
        selected_provider = require_provider(provider)
        normalized_name = _name(name)
        safe_config = _nonsecret_config(config or {})

        existing = self._session.get(TenantIntegration, integration_id)
        if existing is not None:
            if (
                existing.tenant_id != tenant_id
                or existing.provider != selected_provider
                or existing.name != normalized_name
                or existing.config_json != safe_config
            ):
                raise IntegrationIdempotencyConflictError()
            return _integration_ref(existing, replay=True)
        if self._session.get(Tenant, tenant_id) is None:
            raise IntegrationNotFoundError()

        row = TenantIntegration(
            id=integration_id,
            tenant_id=tenant_id,
            provider=selected_provider,
            name=normalized_name,
            config_json=safe_config,
            status="unconfigured",
            row_version=1,
        )
        try:
            with self._session.begin_nested():
                self._session.add(row)
                self._session.flush()
        except IntegrityError:
            existing = self._session.get(TenantIntegration, integration_id)
            if existing is None:
                raise IntegrationPersistenceError() from None
            if (
                existing.tenant_id != tenant_id
                or existing.provider != selected_provider
                or existing.name != normalized_name
                or existing.config_json != safe_config
            ):
                raise IntegrationIdempotencyConflictError() from None
            return _integration_ref(existing, replay=True)
        return _integration_ref(row)

    def create_pending_revision(
        self,
        *,
        integration_uuid: str | UUID,
        credentials: Mapping[str, str],
        root_key: RootKey,
        created_by_user_uuid: str | UUID,
        action_uuid: str | UUID,
        idempotency_key: str,
        expected_integration_row_version: int,
        expected_current_secret_revision_uuid: str | UUID | None,
    ) -> IntegrationSecretRevisionRef:
        """Append encrypted credentials without changing an existing current pointer."""

        self._require_transaction()
        integration_id = _uuid(integration_uuid)
        actor_id = _uuid(created_by_user_uuid)
        action_id = _uuid(action_uuid)
        request_key = _technical_key(idempotency_key)
        expected_row = _positive_int(expected_integration_row_version)
        expected_current = _optional_uuid(expected_current_secret_revision_uuid)
        if not isinstance(root_key, RootKey):
            raise IntegrationInputError()

        integration = self._lock_integration(integration_id)
        bundle = canonicalize_provider_credentials(integration.provider, credentials)
        request_digest = _request_digest(
            "inventory-manager/tenant-integration-revision-request/v1",
            CryptoCodecV1.uuid_bytes(integration.id),
            CryptoCodecV1.uuid_bytes(integration.tenant_id),
            CryptoCodecV1.ascii_text(integration.provider),
            CryptoCodecV1.uuid_bytes(actor_id),
            CryptoCodecV1.uuid_bytes(action_id),
            CryptoCodecV1.uint64(expected_row),
            _optional_uuid_part(expected_current),
            bundle.canonical_semantics_digest,
            CryptoCodecV1.uint64(root_key.version),
            CryptoCodecV1.ascii_text(request_key),
        )
        existing = self._session.scalar(
            sa.select(TenantIntegrationSecretRevision)
            .where(
                TenantIntegrationSecretRevision.request_idempotency_key
                == request_key
            )
            .with_for_update()
        )
        if existing is not None:
            return self._replay_pending_revision(
                existing,
                integration_id=integration_id,
                request_digest=request_digest,
            )
        if (
            integration.row_version != expected_row
            or integration.current_secret_revision_id != expected_current
            or integration.status not in (
                "unconfigured",
                "pending",
                "active",
                "inactive",
                "verification_failed",
            )
        ):
            raise IntegrationStateConflictError()

        latest = self._session.scalar(
            sa.select(sa.func.max(TenantIntegrationSecretRevision.revision_no)).where(
                TenantIntegrationSecretRevision.tenant_integration_id
                == integration.id
            )
        )
        revision_no = int(latest or 0) + 1
        revision_uuid = str(uuid4())
        crypto_context_uuid = str(uuid4())

        resulting_integration_row = integration.row_version
        update_integration_pending = integration.current_secret_revision_id is None
        if update_integration_pending:
            resulting_integration_row += 1
        context = IntegrationSecretCryptoContext(
            crypto_context_uuid=crypto_context_uuid,
            tenant_uuid=integration.tenant_id,
            provider=integration.provider,
            integration_uuid=integration.id,
            revision_no=revision_no,
            credential_schema_version=bundle.schema_version,
            credential_bundle_version=bundle.bundle_version,
            canonical_semantics_digest=bundle.canonical_semantics_digest,
            root_key_version=root_key.version,
        )
        envelope = encrypt_provider_credentials(
            root_key=root_key,
            context=context,
            bundle=bundle,
        )
        revision = TenantIntegrationSecretRevision(
            id=revision_uuid,
            tenant_integration_id=integration.id,
            tenant_id=integration.tenant_id,
            provider=integration.provider,
            revision_no=revision_no,
            crypto_context_uuid=crypto_context_uuid,
            credential_schema_version=CREDENTIAL_SCHEMA_VERSION,
            credential_bundle_version=CREDENTIAL_BUNDLE_VERSION,
            canonical_semantics_digest=bundle.canonical_semantics_digest,
            credentials_ciphertext=envelope.ciphertext,
            credentials_nonce=envelope.nonce,
            root_key_version=envelope.root_key_version,
            crypto_version=envelope.crypto_version,
            aad_version=envelope.aad_version,
            envelope_generation=1,
            envelope_row_version=1,
            status="pending_validation",
            created_from_action_uuid=action_id,
            created_by_user_uuid=actor_id,
            request_idempotency_key=request_key,
            request_digest=request_digest,
            expected_integration_row_version=resulting_integration_row,
            expected_current_secret_revision_id=expected_current,
            verification_status="not_attempted",
            row_version=1,
        )
        try:
            with self._session.begin_nested():
                if update_integration_pending:
                    integration.status = "pending"
                    integration.row_version = resulting_integration_row
                    integration.updated_at = _utc_now()
                self._session.add(revision)
                self._session.flush()
        except IntegrityError:
            existing = self._session.scalar(
                sa.select(TenantIntegrationSecretRevision).where(
                    TenantIntegrationSecretRevision.request_idempotency_key
                    == request_key
                )
            )
            if existing is None:
                raise IntegrationPersistenceError() from None
            return self._replay_pending_revision(
                existing,
                integration_id=integration_id,
                request_digest=request_digest,
            )
        return _revision_ref(revision)

    def begin_provider_validation(
        self,
        *,
        revision_uuid: str | UUID,
        attempt_uuid: str | UUID,
        expected_revision_row_version: int,
    ) -> IntegrationSecretRevisionRef:
        """Persist the provider-submitting boundary before any network call."""

        self._require_transaction()
        revision_id = _uuid(revision_uuid)
        attempt_id = _uuid(attempt_uuid)
        expected_row = _positive_int(expected_revision_row_version)
        revision = self._lock_revision(revision_id)
        if (
            revision.verification_status == "submitting"
            and revision.verification_attempt_uuid == attempt_id
        ):
            return _revision_ref(revision, replay=True)
        if revision.verification_status == "unknown":
            raise IntegrationValidationUnknownError()
        if (
            revision.status != "pending_validation"
            or revision.verification_status != "not_attempted"
            or revision.row_version != expected_row
        ):
            raise IntegrationStateConflictError()
        changed = self._session.execute(
            sa.update(TenantIntegrationSecretRevision)
            .where(
                TenantIntegrationSecretRevision.id == revision_id,
                TenantIntegrationSecretRevision.status == "pending_validation",
                TenantIntegrationSecretRevision.verification_status
                == "not_attempted",
                TenantIntegrationSecretRevision.row_version == expected_row,
            )
            .values(
                verification_status="submitting",
                verification_attempt_uuid=attempt_id,
                row_version=expected_row + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise IntegrationStateConflictError()
        return _revision_ref(self._refresh_revision(revision_id))

    def record_provider_validation_result(
        self,
        *,
        revision_uuid: str | UUID,
        attempt_uuid: str | UUID,
        outcome: ProviderValidationOutcome,
        provider_result_digest: bytes,
        safe_code: str,
        completed_at: datetime | None = None,
    ) -> IntegrationSecretRevisionRef:
        """Record one explicit provider result; unknown never changes current."""

        self._require_transaction()
        revision_id = _uuid(revision_uuid)
        attempt_id = _uuid(attempt_uuid)
        selected = _validation_outcome(outcome)
        result_digest = _digest32(provider_result_digest)
        result_code = _safe_code(safe_code)
        occurred_at = _datetime(completed_at or _utc_now())
        revision = self._lock_revision(revision_id)
        replay = self._validation_replay(
            revision,
            attempt_id=attempt_id,
            outcome=selected,
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
            if revision.verification_status == "unknown":
                raise IntegrationValidationUnknownError()
            raise IntegrationStateConflictError()
        return self._apply_validation_result(
            revision,
            outcome=selected,
            result_digest=result_digest,
            safe_code=result_code,
            occurred_at=occurred_at,
        )

    def reconcile_unknown_validation(
        self,
        *,
        revision_uuid: str | UUID,
        attempt_uuid: str | UUID,
        resolution: ProviderValidationReconciliation,
        provider_result_digest: bytes,
        safe_code: str,
        completed_at: datetime | None = None,
    ) -> IntegrationSecretRevisionRef:
        """Explicitly reconcile a prior unknown without submitting it again."""

        self._require_transaction()
        revision_id = _uuid(revision_uuid)
        attempt_id = _uuid(attempt_uuid)
        try:
            selected = ProviderValidationReconciliation(resolution)
        except (TypeError, ValueError):
            raise IntegrationInputError() from None
        result_digest = _digest32(provider_result_digest)
        result_code = _safe_code(safe_code)
        occurred_at = _datetime(completed_at or _utc_now())
        revision = self._lock_revision(revision_id)
        if (
            revision.status != "pending_validation"
            or revision.verification_status != "unknown"
            or revision.verification_attempt_uuid != attempt_id
        ):
            raise IntegrationStateConflictError()
        if selected is ProviderValidationReconciliation.STILL_UNKNOWN:
            if (
                bytes(revision.verification_result_digest) == result_digest
                and revision.verification_safe_code == result_code
            ):
                return _revision_ref(
                    revision, replay=True, requires_reconciliation=True
                )
            changed = self._session.execute(
                sa.update(TenantIntegrationSecretRevision)
                .where(
                    TenantIntegrationSecretRevision.id == revision.id,
                    TenantIntegrationSecretRevision.status == "pending_validation",
                    TenantIntegrationSecretRevision.verification_status == "unknown",
                    TenantIntegrationSecretRevision.row_version == revision.row_version,
                )
                .values(
                    verification_result_digest=result_digest,
                    verification_safe_code=result_code,
                    verification_completed_at=occurred_at,
                    row_version=revision.row_version + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise IntegrationStateConflictError()
            return _revision_ref(
                self._refresh_revision(revision.id),
                requires_reconciliation=True,
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
            expected_verification_status="unknown",
        )

    def use_exact_revision(
        self,
        *,
        revision_uuid: str | UUID,
        root_key: RootKey,
        consumer: Callable[[CanonicalProviderCredentialBundle], _T],
    ) -> _T:
        """Decrypt current/historical exact revision and invoke a local callback.

        The callback must only construct a short-lived in-memory provider
        configuration; provider I/O must happen after the control transaction.
        No current pointer or provider default is consulted on failure.
        """

        self._require_transaction()
        revision = self._session.get(
            TenantIntegrationSecretRevision, _uuid(revision_uuid)
        )
        if revision is None or revision.status not in ("current", "superseded"):
            raise IntegrationCredentialUnavailableError()
        return consumer(self._decrypt_revision(revision, root_key=root_key))

    def use_pending_revision_for_validation(
        self,
        *,
        revision_uuid: str | UUID,
        attempt_uuid: str | UUID,
        root_key: RootKey,
        consumer: Callable[[CanonicalProviderCredentialBundle], _T],
    ) -> _T:
        """Resolve only the submitting pending revision for its validation call."""

        self._require_transaction()
        revision = self._session.get(
            TenantIntegrationSecretRevision, _uuid(revision_uuid)
        )
        if (
            revision is None
            or revision.status != "pending_validation"
            or revision.verification_status != "submitting"
            or revision.verification_attempt_uuid != _uuid(attempt_uuid)
        ):
            raise IntegrationCredentialUnavailableError()
        return consumer(self._decrypt_revision(revision, root_key=root_key))

    def rewrap_exact_revision_envelope(
        self,
        *,
        revision_uuid: str | UUID,
        old_root_key: RootKey,
        new_root_key: RootKey,
        rotation_run_uuid: str | UUID,
        rotation_action_uuid: str | UUID,
        idempotency_key: str,
        expected_envelope_row_version: int,
    ) -> IntegrationEnvelopeRotationRef:
        """Re-encrypt the same business revision and append one rotation event."""

        self._require_transaction()
        revision_id = _uuid(revision_uuid)
        run_id = _uuid(rotation_run_uuid)
        action_id = _uuid(rotation_action_uuid)
        request_key = _technical_key(idempotency_key)
        expected_row = _positive_int(expected_envelope_row_version)
        if (
            not isinstance(old_root_key, RootKey)
            or not isinstance(new_root_key, RootKey)
            or new_root_key.version <= old_root_key.version
        ):
            raise IntegrationInputError()
        request_digest = _request_digest(
            "inventory-manager/tenant-integration-envelope-rotation-request/v1",
            CryptoCodecV1.uuid_bytes(revision_id),
            CryptoCodecV1.uuid_bytes(run_id),
            CryptoCodecV1.uuid_bytes(action_id),
            CryptoCodecV1.uint64(expected_row),
            CryptoCodecV1.uint64(old_root_key.version),
            CryptoCodecV1.uint64(new_root_key.version),
            CryptoCodecV1.ascii_text(request_key),
        )
        existing = self._session.scalar(
            sa.select(TenantIntegrationSecretEnvelopeEvent)
            .where(
                TenantIntegrationSecretEnvelopeEvent.idempotency_key == request_key
            )
            .with_for_update()
        )
        if existing is not None:
            if (
                existing.tenant_integration_secret_revision_id != revision_id
                or bytes(existing.request_digest) != request_digest
                or existing.to_root_key_version != new_root_key.version
            ):
                raise IntegrationIdempotencyConflictError()
            return _rotation_ref(existing, replay=True)

        revision = self._lock_revision(revision_id)
        if (
            revision.envelope_row_version != expected_row
            or revision.root_key_version != old_root_key.version
        ):
            raise IntegrationStateConflictError()
        bundle = self._decrypt_revision(revision, root_key=old_root_key)
        new_context = _crypto_context(revision, root_key_version=new_root_key.version)
        new_envelope = encrypt_provider_credentials(
            root_key=new_root_key,
            context=new_context,
            bundle=bundle,
        )
        next_generation = revision.envelope_generation + 1
        event = TenantIntegrationSecretEnvelopeEvent(
            id=str(uuid4()),
            tenant_integration_secret_revision_id=revision.id,
            envelope_generation=next_generation,
            from_root_key_version=revision.root_key_version,
            to_root_key_version=new_envelope.root_key_version,
            from_crypto_version=revision.crypto_version,
            to_crypto_version=new_envelope.crypto_version,
            from_aad_version=revision.aad_version,
            to_aad_version=new_envelope.aad_version,
            before_ciphertext_digest=hashlib.sha256(
                bytes(revision.credentials_ciphertext)
            ).digest(),
            after_ciphertext_digest=hashlib.sha256(
                new_envelope.ciphertext
            ).digest(),
            rotation_run_uuid=run_id,
            rotation_action_uuid=action_id,
            idempotency_key=request_key,
            request_digest=request_digest,
            safe_outcome="succeeded",
        )
        try:
            with self._session.begin_nested():
                changed = self._session.execute(
                    sa.update(TenantIntegrationSecretRevision)
                    .where(
                        TenantIntegrationSecretRevision.id == revision.id,
                        TenantIntegrationSecretRevision.envelope_row_version
                        == expected_row,
                        TenantIntegrationSecretRevision.root_key_version
                        == old_root_key.version,
                    )
                    .values(
                        credentials_ciphertext=new_envelope.ciphertext,
                        credentials_nonce=new_envelope.nonce,
                        root_key_version=new_envelope.root_key_version,
                        crypto_version=new_envelope.crypto_version,
                        aad_version=new_envelope.aad_version,
                        envelope_generation=next_generation,
                        envelope_row_version=expected_row + 1,
                        last_envelope_rotation_event_id=event.id,
                        row_version=revision.row_version + 1,
                    )
                    .execution_options(synchronize_session=False)
                )
                if changed.rowcount != 1:
                    raise IntegrationStateConflictError()
                self._session.add(event)
                self._session.flush()
        except IntegrityError:
            existing = self._session.scalar(
                sa.select(TenantIntegrationSecretEnvelopeEvent).where(
                    TenantIntegrationSecretEnvelopeEvent.idempotency_key
                    == request_key
                )
            )
            if (
                existing is None
                or existing.tenant_integration_secret_revision_id != revision_id
                or bytes(existing.request_digest) != request_digest
            ):
                raise IntegrationPersistenceError() from None
            return _rotation_ref(existing, replay=True)
        return _rotation_ref(event)

    def set_default_for_new_accounts(
        self,
        *,
        tenant_uuid: str | UUID,
        provider: str,
        integration_uuid: str | UUID,
        updated_by_user_uuid: str | UUID,
        expected_row_version: int | None,
    ) -> TenantProviderDefaultRef:
        """Set the selector used only while creating future provider accounts."""

        self._require_transaction()
        tenant_id = _uuid(tenant_uuid)
        selected_provider = require_provider(provider)
        integration_id = _uuid(integration_uuid)
        actor_id = _uuid(updated_by_user_uuid)
        if expected_row_version is not None:
            expected_row_version = _positive_int(expected_row_version)
        integration = self._lock_integration(integration_id)
        if (
            integration.tenant_id != tenant_id
            or integration.provider != selected_provider
            or integration.status != "active"
            or integration.current_secret_revision_id is None
        ):
            raise IntegrationCredentialUnavailableError()
        current = self._session.get(
            TenantIntegrationSecretRevision,
            integration.current_secret_revision_id,
        )
        if (
            current is None
            or current.tenant_integration_id != integration.id
            or current.status != "current"
            or current.verification_status != "succeeded"
        ):
            raise IntegrationCredentialUnavailableError()

        key = {"tenant_id": tenant_id, "provider": selected_provider}
        default = self._session.get(TenantProviderDefault, key)
        if default is None:
            if expected_row_version is not None:
                raise IntegrationStateConflictError()
            default = TenantProviderDefault(
                tenant_id=tenant_id,
                provider=selected_provider,
                integration_id=integration_id,
                updated_by=actor_id,
                row_version=1,
            )
            self._session.add(default)
            self._flush()
            return _default_ref(default)
        if default.integration_id == integration_id:
            return _default_ref(default, replay=True)
        if default.row_version != expected_row_version:
            raise IntegrationStateConflictError()
        changed = self._session.execute(
            sa.update(TenantProviderDefault)
            .where(
                TenantProviderDefault.tenant_id == tenant_id,
                TenantProviderDefault.provider == selected_provider,
                TenantProviderDefault.row_version == expected_row_version,
            )
            .values(
                integration_id=integration_id,
                updated_by=actor_id,
                row_version=expected_row_version + 1,
                updated_at=_utc_now(),
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise IntegrationStateConflictError()
        refreshed = self._session.get(TenantProviderDefault, key)
        self._session.refresh(refreshed)
        return _default_ref(refreshed)

    def resolve_default_for_new_account(
        self,
        *,
        tenant_uuid: str | UUID,
        provider: str,
    ) -> TenantProviderDefaultRef:
        """Resolve a creation default; never use this for historical work."""

        self._require_transaction()
        tenant_id = _uuid(tenant_uuid)
        selected_provider = require_provider(provider)
        default = self._session.get(
            TenantProviderDefault,
            {"tenant_id": tenant_id, "provider": selected_provider},
        )
        if default is None:
            raise IntegrationCredentialUnavailableError()
        integration = self._session.get(TenantIntegration, default.integration_id)
        if (
            integration is None
            or integration.tenant_id != tenant_id
            or integration.provider != selected_provider
            or integration.status != "active"
            or integration.current_secret_revision_id is None
        ):
            raise IntegrationCredentialUnavailableError()
        return _default_ref(default)

    def _apply_validation_result(
        self,
        revision: TenantIntegrationSecretRevision,
        *,
        outcome: ProviderValidationOutcome,
        result_digest: bytes,
        safe_code: str,
        occurred_at: datetime,
        expected_verification_status: str = "submitting",
    ) -> IntegrationSecretRevisionRef:
        if outcome is ProviderValidationOutcome.UNKNOWN:
            changed = self._session.execute(
                sa.update(TenantIntegrationSecretRevision)
                .where(
                    TenantIntegrationSecretRevision.id == revision.id,
                    TenantIntegrationSecretRevision.status == "pending_validation",
                    TenantIntegrationSecretRevision.verification_status
                    == expected_verification_status,
                    TenantIntegrationSecretRevision.row_version == revision.row_version,
                )
                .values(
                    verification_status="unknown",
                    verification_result_digest=result_digest,
                    verification_safe_code=safe_code,
                    verification_completed_at=occurred_at,
                    row_version=revision.row_version + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise IntegrationStateConflictError()
            return _revision_ref(
                self._refresh_revision(revision.id), requires_reconciliation=True
            )

        integration = self._lock_integration(revision.tenant_integration_id)
        if (
            integration.tenant_id != revision.tenant_id
            or integration.provider != revision.provider
        ):
            raise IntegrationStateConflictError()

        if outcome is ProviderValidationOutcome.DEFINITIVE_FAILURE:
            changed = self._session.execute(
                sa.update(TenantIntegrationSecretRevision)
                .where(
                    TenantIntegrationSecretRevision.id == revision.id,
                    TenantIntegrationSecretRevision.status == "pending_validation",
                    TenantIntegrationSecretRevision.verification_status
                    == expected_verification_status,
                    TenantIntegrationSecretRevision.row_version == revision.row_version,
                )
                .values(
                    status="revoked",
                    verification_status="failed",
                    verification_result_digest=result_digest,
                    verification_safe_code=safe_code,
                    verification_completed_at=occurred_at,
                    revoked_at=occurred_at,
                    row_version=revision.row_version + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if changed.rowcount != 1:
                raise IntegrationStateConflictError()
            if (
                revision.expected_current_secret_revision_id is None
                and integration.current_secret_revision_id is None
                and integration.row_version
                == revision.expected_integration_row_version
            ):
                integration_changed = self._session.execute(
                    sa.update(TenantIntegration)
                    .where(
                        TenantIntegration.id == integration.id,
                        TenantIntegration.row_version == integration.row_version,
                        TenantIntegration.current_secret_revision_id.is_(None),
                    )
                    .values(
                        status="verification_failed",
                        row_version=integration.row_version + 1,
                        updated_at=occurred_at,
                    )
                    .execution_options(synchronize_session=False)
                )
                if integration_changed.rowcount != 1:
                    raise IntegrationStateConflictError()
            return _revision_ref(self._refresh_revision(revision.id))

        if (
            integration.row_version != revision.expected_integration_row_version
            or integration.current_secret_revision_id
            != revision.expected_current_secret_revision_id
        ):
            raise IntegrationStateConflictError()

        previous_revision_id = revision.expected_current_secret_revision_id
        if previous_revision_id is not None:
            previous = self._session.execute(
                sa.update(TenantIntegrationSecretRevision)
                .where(
                    TenantIntegrationSecretRevision.id == previous_revision_id,
                    TenantIntegrationSecretRevision.tenant_integration_id
                    == integration.id,
                    TenantIntegrationSecretRevision.status == "current",
                    TenantIntegrationSecretRevision.verification_status == "succeeded",
                )
                .values(
                    status="superseded",
                    superseded_at=occurred_at,
                    row_version=TenantIntegrationSecretRevision.row_version + 1,
                )
                .execution_options(synchronize_session=False)
            )
            if previous.rowcount != 1:
                raise IntegrationStateConflictError()
        current = self._session.execute(
            sa.update(TenantIntegrationSecretRevision)
            .where(
                TenantIntegrationSecretRevision.id == revision.id,
                TenantIntegrationSecretRevision.status == "pending_validation",
                TenantIntegrationSecretRevision.verification_status
                == expected_verification_status,
                TenantIntegrationSecretRevision.row_version == revision.row_version,
            )
            .values(
                status="current",
                verification_status="succeeded",
                verification_result_digest=result_digest,
                verification_safe_code=safe_code,
                verification_completed_at=occurred_at,
                activated_at=occurred_at,
                row_version=revision.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if current.rowcount != 1:
            raise IntegrationStateConflictError()
        integration_changed = self._session.execute(
            sa.update(TenantIntegration)
            .where(
                TenantIntegration.id == integration.id,
                TenantIntegration.row_version == integration.row_version,
                _nullable_equal(
                    TenantIntegration.current_secret_revision_id,
                    previous_revision_id,
                ),
            )
            .values(
                current_secret_revision_id=revision.id,
                status="active",
                last_verified_at=occurred_at,
                row_version=integration.row_version + 1,
                updated_at=occurred_at,
            )
            .execution_options(synchronize_session=False)
        )
        if integration_changed.rowcount != 1:
            raise IntegrationStateConflictError()
        return _revision_ref(self._refresh_revision(revision.id))

    def _validation_replay(
        self,
        revision: TenantIntegrationSecretRevision,
        *,
        attempt_id: str,
        outcome: ProviderValidationOutcome,
        result_digest: bytes,
        safe_code: str,
    ) -> IntegrationSecretRevisionRef | None:
        expected_verification = {
            ProviderValidationOutcome.SUCCESS: "succeeded",
            ProviderValidationOutcome.DEFINITIVE_FAILURE: "failed",
            ProviderValidationOutcome.UNKNOWN: "unknown",
        }[outcome]
        if revision.verification_status != expected_verification:
            return None
        if (
            revision.verification_attempt_uuid != attempt_id
            or revision.verification_result_digest is None
            or bytes(revision.verification_result_digest) != result_digest
            or revision.verification_safe_code != safe_code
        ):
            raise IntegrationStateConflictError()
        return _revision_ref(
            revision,
            replay=True,
            requires_reconciliation=outcome is ProviderValidationOutcome.UNKNOWN,
        )

    def _replay_pending_revision(
        self,
        revision: TenantIntegrationSecretRevision,
        *,
        integration_id: str,
        request_digest: bytes,
    ) -> IntegrationSecretRevisionRef:
        if (
            revision.tenant_integration_id != integration_id
            or bytes(revision.request_digest) != request_digest
        ):
            raise IntegrationIdempotencyConflictError()
        return _revision_ref(
            revision,
            replay=True,
            requires_reconciliation=revision.verification_status == "unknown",
        )

    def _decrypt_revision(
        self,
        revision: TenantIntegrationSecretRevision,
        *,
        root_key: RootKey,
    ) -> CanonicalProviderCredentialBundle:
        try:
            envelope = EncryptedEnvelope(
                nonce=bytes(revision.credentials_nonce),
                ciphertext=bytes(revision.credentials_ciphertext),
                root_key_version=revision.root_key_version,
                crypto_version=revision.crypto_version,
                aad_version=revision.aad_version,
            )
            return decrypt_provider_credentials(
                root_key=root_key,
                context=_crypto_context(revision),
                envelope=envelope,
            )
        except IntegrationCredentialAuthenticationError:
            raise
        except Exception:
            # Mapped metadata is untrusted input at this boundary.  Never put
            # the malformed value or the encrypted bytes into an exception.
            raise IntegrationCredentialAuthenticationError() from None

    def _lock_integration(self, integration_id: str) -> TenantIntegration:
        integration = self._session.scalar(
            sa.select(TenantIntegration)
            .where(TenantIntegration.id == integration_id)
            .with_for_update()
        )
        if integration is None:
            raise IntegrationNotFoundError()
        return integration

    def _lock_revision(self, revision_id: str) -> TenantIntegrationSecretRevision:
        revision = self._session.scalar(
            sa.select(TenantIntegrationSecretRevision)
            .where(TenantIntegrationSecretRevision.id == revision_id)
            .with_for_update()
        )
        if revision is None:
            raise IntegrationNotFoundError()
        return revision

    def _refresh_revision(self, revision_id: str) -> TenantIntegrationSecretRevision:
        return self._session.execute(
            sa.select(TenantIntegrationSecretRevision)
            .where(TenantIntegrationSecretRevision.id == revision_id)
            .execution_options(populate_existing=True)
        ).scalar_one()

    def _flush(self) -> None:
        try:
            self._session.flush()
        except IntegrityError:
            raise IntegrationPersistenceError() from None

    def _require_transaction(self) -> None:
        transaction = self._session.get_transaction()
        if (
            transaction is None
            or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
        ):
            raise IntegrationTransactionRequiredError()


def _crypto_context(
    revision: TenantIntegrationSecretRevision,
    *,
    root_key_version: int | None = None,
) -> IntegrationSecretCryptoContext:
    return IntegrationSecretCryptoContext(
        crypto_context_uuid=revision.crypto_context_uuid,
        tenant_uuid=revision.tenant_id,
        provider=revision.provider,
        integration_uuid=revision.tenant_integration_id,
        revision_no=revision.revision_no,
        credential_schema_version=revision.credential_schema_version,
        credential_bundle_version=revision.credential_bundle_version,
        canonical_semantics_digest=bytes(revision.canonical_semantics_digest),
        root_key_version=(
            revision.root_key_version
            if root_key_version is None
            else root_key_version
        ),
        crypto_version=revision.crypto_version,
        aad_version=revision.aad_version,
    )


def _integration_ref(
    row: TenantIntegration,
    *,
    replay: bool = False,
) -> TenantIntegrationRef:
    return TenantIntegrationRef(
        integration_uuid=row.id,
        tenant_uuid=row.tenant_id,
        provider=row.provider,
        name=row.name,
        status=row.status,
        current_secret_revision_uuid=row.current_secret_revision_id,
        row_version=row.row_version,
        idempotent_replay=replay,
    )


def _revision_ref(
    row: TenantIntegrationSecretRevision,
    *,
    replay: bool = False,
    requires_reconciliation: bool = False,
) -> IntegrationSecretRevisionRef:
    return IntegrationSecretRevisionRef(
        revision_uuid=row.id,
        integration_uuid=row.tenant_integration_id,
        tenant_uuid=row.tenant_id,
        provider=row.provider,
        revision_no=row.revision_no,
        status=row.status,
        verification_status=row.verification_status,
        envelope_generation=row.envelope_generation,
        envelope_row_version=row.envelope_row_version,
        row_version=row.row_version,
        idempotent_replay=replay,
        requires_reconciliation=requires_reconciliation,
    )


def _rotation_ref(
    event: TenantIntegrationSecretEnvelopeEvent,
    *,
    replay: bool = False,
) -> IntegrationEnvelopeRotationRef:
    return IntegrationEnvelopeRotationRef(
        event_uuid=event.id,
        revision_uuid=event.tenant_integration_secret_revision_id,
        envelope_generation=event.envelope_generation,
        root_key_version=event.to_root_key_version,
        idempotent_replay=replay,
    )


def _default_ref(
    row: TenantProviderDefault,
    *,
    replay: bool = False,
) -> TenantProviderDefaultRef:
    return TenantProviderDefaultRef(
        tenant_uuid=row.tenant_id,
        provider=row.provider,
        integration_uuid=row.integration_id,
        row_version=row.row_version,
        idempotent_replay=replay,
    )


def _request_digest(domain: str, *parts: bytes) -> bytes:
    return hashlib.sha256(
        CryptoCodecV1.encode_parts(CryptoCodecV1.domain(domain), *parts)
    ).digest()


def _uuid(value: str | UUID) -> str:
    try:
        parsed = value if isinstance(value, UUID) else UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise IntegrationInputError() from None
    return str(parsed)


def _optional_uuid(value: str | UUID | None) -> str | None:
    return None if value is None else _uuid(value)


def _optional_uuid_part(value: str | None) -> bytes:
    return b"" if value is None else CryptoCodecV1.uuid_bytes(value)


def _technical_key(value: str) -> str:
    if not isinstance(value, str) or len(value) > 128:
        raise IntegrationInputError()
    try:
        CryptoCodecV1.ascii_text(value)
    except Exception:
        raise IntegrationInputError() from None
    return value


def _positive_int(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise IntegrationInputError()
    return value


def _name(value: str) -> str:
    if not isinstance(value, str) or _SAFE_NAME.fullmatch(value) is None:
        raise IntegrationInputError()
    if value != value.strip():
        raise IntegrationInputError()
    return value


def _safe_code(value: str) -> str:
    if not isinstance(value, str) or _SAFE_CODE.fullmatch(value) is None:
        raise IntegrationInputError()
    return value


def _digest32(value: bytes) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise IntegrationInputError()
    return bytes(value)


def _datetime(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise IntegrationInputError()
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validation_outcome(value: ProviderValidationOutcome) -> ProviderValidationOutcome:
    try:
        return ProviderValidationOutcome(value)
    except (TypeError, ValueError):
        raise IntegrationInputError() from None


def _nullable_equal(column: Any, value: str | None) -> Any:
    return column.is_(None) if value is None else column == value


def _nonsecret_config(value: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise IntegrationInputError()

    def copy_safe(item: Any, *, key: str | None = None, depth: int = 0) -> Any:
        if depth > 8:
            raise IntegrationInputError()
        if key is not None:
            lowered = key.lower()
            if any(part in lowered for part in _FORBIDDEN_CONFIG_KEY_PARTS):
                raise IntegrationInputError()
        if item is None or isinstance(item, (str, int, float, bool)):
            if isinstance(item, float) and (
                item != item or item in (float("inf"), float("-inf"))
            ):
                raise IntegrationInputError()
            return item
        if isinstance(item, Mapping):
            copied: dict[str, Any] = {}
            for nested_key, nested_value in item.items():
                if not isinstance(nested_key, str) or not nested_key:
                    raise IntegrationInputError()
                copied[nested_key] = copy_safe(
                    nested_value, key=nested_key, depth=depth + 1
                )
            return copied
        if isinstance(item, (list, tuple)):
            return [copy_safe(child, depth=depth + 1) for child in item]
        raise IntegrationInputError()

    copied = copy_safe(value)
    try:
        encoded = json.dumps(
            copied,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise IntegrationInputError() from None
    if len(encoded) > _MAX_CONFIG_BYTES:
        raise IntegrationInputError()
    return copied
