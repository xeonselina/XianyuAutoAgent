"""Provider-validation handler for encrypted tenant credential revisions."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.crypto import SqlAlchemyRootKeyRegistry
from inventory_control.integrations import (
    ProviderValidationOutcome,
    TenantIntegrationService,
)
from inventory_control.jobs import (
    ControlTenantGateReader,
    OrdinaryOutboxHandler,
    OutboxAuthorityFacts,
    OutboxAuthorityPhase,
    OutboxAuthorityVerdict,
    OutboxDispatchPermit,
    OutboxHandlerResult,
    OutboxLease,
    OutboxResultDisposition,
    PreparedOutboxDispatch,
)
from inventory_control.models import TenantIntegrationSecretRevision


INTEGRATION_VALIDATION_EVENT_TYPE = "tenant_integration_credential_validate"
INTEGRATION_REVISION_SOURCE_TYPE = "tenant_integration_secret_revision"
_ATTEMPT_NAMESPACE = UUID("f7c9c868-946e-5d64-84f6-8bdb8bccd991")
_SAFE_CODE = re.compile(r"^[A-Z0-9][A-Z0-9_.:-]{0,63}$")


class CredentialValidationDecision(str, Enum):
    VALID = "valid"
    INVALID = "invalid"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True, repr=False)
class CredentialValidationResult:
    decision: CredentialValidationDecision
    safe_code: str
    safe_facts_digest: bytes = field(repr=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "decision",
            CredentialValidationDecision(self.decision),
        )
        if (
            not isinstance(self.safe_code, str)
            or _SAFE_CODE.fullmatch(self.safe_code) is None
            or not isinstance(self.safe_facts_digest, bytes)
            or len(self.safe_facts_digest) != 32
        ):
            raise ValueError("credential validation result is invalid")

    def __repr__(self) -> str:
        return (
            "CredentialValidationResult("
            f"decision={self.decision.value!r}, "
            f"safe_code={self.safe_code!r}, <redacted>)"
        )


class ProviderCredentialValidationRequest:
    """One-shot plaintext bridge from committed validation state to an adapter."""

    __slots__ = (
        "provider",
        "integration_id",
        "revision_id",
        "attempt_id",
        "_credentials",
    )

    def __init__(
        self,
        *,
        provider: str,
        integration_id: str,
        revision_id: str,
        attempt_id: str,
        credentials: Mapping[str, str],
    ) -> None:
        self.provider = provider
        self.integration_id = str(UUID(integration_id))
        self.revision_id = str(UUID(revision_id))
        self.attempt_id = str(UUID(attempt_id))
        self._credentials = dict(credentials)

    def take_credentials(self) -> Mapping[str, str]:
        if self._credentials is None:
            raise RuntimeError("provider credentials are no longer available")
        credentials = MappingProxyType(self._credentials)
        self._credentials = None
        return credentials

    def discard_credentials(self) -> None:
        self._credentials = None

    def __repr__(self) -> str:
        return (
            "ProviderCredentialValidationRequest("
            f"provider={self.provider!r}, revision_id={self.revision_id!r}, "
            "credentials=<redacted>)"
        )


class ProviderCredentialValidator(Protocol):
    def validate_credentials(
        self,
        request: ProviderCredentialValidationRequest,
    ) -> CredentialValidationResult: ...


@dataclass(frozen=True, slots=True)
class _LockedIntegrationOutboxAuthority:
    tenant_authority: Any
    revision: TenantIntegrationSecretRevision | None
    input_valid: bool


class TenantIntegrationOutboxAuthority:
    """D56 current gate plus exact credential-revision source authority."""

    def __init__(self, gate_reader: ControlTenantGateReader) -> None:
        if not isinstance(gate_reader, ControlTenantGateReader):
            raise TypeError("gate_reader must be a ControlTenantGateReader")
        self._gate_reader = gate_reader

    def lock_current_outbox_authority(
        self,
        session: Session,
        *,
        facts: OutboxAuthorityFacts,
        phase: OutboxAuthorityPhase,
    ) -> _LockedIntegrationOutboxAuthority:
        del phase
        valid = (
            facts.tenant_id is not None
            and facts.tenant_access_version is not None
            and facts.source_type == INTEGRATION_REVISION_SOURCE_TYPE
            and facts.event_type == INTEGRATION_VALIDATION_EVENT_TYPE
        )
        if not valid:
            return _LockedIntegrationOutboxAuthority(None, None, False)
        tenant_authority = self._gate_reader.lock_current(
            session,
            tenant_id=facts.tenant_id,
            presented_access_version=facts.tenant_access_version,
        )
        revision = session.scalar(
            sa.select(TenantIntegrationSecretRevision)
            .where(TenantIntegrationSecretRevision.id == facts.source_uuid)
            .with_for_update()
        )
        return _LockedIntegrationOutboxAuthority(
            tenant_authority,
            revision,
            True,
        )

    def evaluate_locked_outbox_authority(
        self,
        session: Session,
        *,
        locked_authority: _LockedIntegrationOutboxAuthority,
        facts: OutboxAuthorityFacts,
        phase: OutboxAuthorityPhase,
        now,
    ) -> OutboxAuthorityVerdict:
        del session, phase
        locked = locked_authority
        if not isinstance(locked, _LockedIntegrationOutboxAuthority):
            raise TypeError("locked integration authority is invalid")
        tenant = (
            getattr(locked.tenant_authority, "tenant", None)
            if locked.tenant_authority is not None
            else None
        )
        tenant_version = getattr(tenant, "access_version", None)
        revision = locked.revision
        source_generation = (
            revision.revision_no
            if revision is not None
            else facts.source_generation
        )
        recovery_verified = bool(
            locked.tenant_authority is not None
            and getattr(locked.tenant_authority, "recovery_released", None) is True
        )
        if not locked.input_valid or locked.tenant_authority is None:
            return OutboxAuthorityVerdict(
                allowed=False,
                current_recovery_run_verified=recovery_verified,
                current_source_generation=source_generation,
                current_tenant_access_version=tenant_version,
                reason_code="integration_authority_invalid",
            )
        current = self._gate_reader.evaluate_locked(
            locked.tenant_authority,
            now=now,
        )
        source_valid = bool(
            revision is not None
            and revision.tenant_id == facts.tenant_id
            and revision.revision_no == facts.source_generation
            and revision.status == "pending_validation"
            and revision.verification_status in ("not_attempted", "submitting")
        )
        allowed = bool(current.allowed and source_valid and recovery_verified)
        reason = (
            "authority_allowed"
            if allowed
            else (
                _reason_code(current.reason_code)
                if not current.allowed
                else "integration_source_stale"
            )
        )
        return OutboxAuthorityVerdict(
            allowed=allowed,
            current_recovery_run_verified=recovery_verified,
            current_source_generation=source_generation,
            current_tenant_access_version=tenant_version,
            reason_code=reason,
        )


class _PreparedCredentialValidation:
    __slots__ = ("_adapter", "_request", "_dispatched")

    def __init__(
        self,
        *,
        adapter: ProviderCredentialValidator,
        request: ProviderCredentialValidationRequest,
    ) -> None:
        self._adapter = adapter
        self._request = request
        self._dispatched = False

    def dispatch_once(self) -> CredentialValidationResult:
        if self._dispatched:
            raise RuntimeError("credential validation was already dispatched")
        self._dispatched = True
        try:
            result = self._adapter.validate_credentials(self._request)
            if not isinstance(result, CredentialValidationResult):
                raise TypeError("provider returned an invalid validation result")
            return result
        finally:
            self._request.discard_credentials()

    def __repr__(self) -> str:
        state = "dispatched" if self._dispatched else "prepared"
        return f"_PreparedCredentialValidation(state={state!r}, <redacted>)"


class TenantIntegrationCredentialValidationHandler(OrdinaryOutboxHandler):
    """Bind one outbox execution to one exact encrypted revision and attempt."""

    def __init__(
        self,
        *,
        root_key_directory: str | os.PathLike[str],
        validators: Mapping[str, ProviderCredentialValidator],
    ) -> None:
        root = os.fspath(root_key_directory)
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise ValueError("root_key_directory must be absolute")
        if not isinstance(validators, Mapping):
            raise TypeError("validators must be a mapping")
        self._root_key_directory = root
        self._validators = dict(validators)

    def prepare_dispatch(
        self,
        session: Session,
        *,
        lease: OutboxLease,
        permit: OutboxDispatchPermit,
    ) -> PreparedOutboxDispatch:
        payload = _payload(permit)
        revision_id = _uuid(payload.get("revision_uuid"))
        integration_id = _uuid(payload.get("integration_uuid"))
        provider = payload.get("provider")
        expected_row = _positive(payload.get("revision_row_version"))
        if (
            permit.event_type != INTEGRATION_VALIDATION_EVENT_TYPE
            or permit.source_type != INTEGRATION_REVISION_SOURCE_TYPE
            or permit.source_uuid != revision_id
            or lease.event_id != permit.event_id
            or lease.tenant_id is None
            or lease.tenant_id != permit.payload.get("tenant_uuid", lease.tenant_id)
            or not isinstance(provider, str)
        ):
            raise ValueError("integration validation outbox facts are invalid")
        adapter = self._validators.get(provider)
        if adapter is None or not callable(
            getattr(adapter, "validate_credentials", None)
        ):
            raise RuntimeError("provider credential validator is unavailable")
        revision = session.get(TenantIntegrationSecretRevision, revision_id)
        if (
            revision is None
            or revision.tenant_id != lease.tenant_id
            or revision.tenant_integration_id != integration_id
            or revision.provider != provider
            or revision.revision_no != permit.source_generation
        ):
            raise ValueError("integration validation source is stale")
        attempt_id = _attempt_uuid(permit)
        service = TenantIntegrationService(session)
        service.begin_provider_validation(
            revision_uuid=revision_id,
            attempt_uuid=attempt_id,
            expected_revision_row_version=expected_row,
        )
        root_key = SqlAlchemyRootKeyRegistry(session=session).load(
            self._root_key_directory
        ).key_for_existing_reference(revision.root_key_version)
        prepared = service.use_pending_revision_for_validation(
            revision_uuid=revision_id,
            attempt_uuid=attempt_id,
            root_key=root_key,
            consumer=lambda bundle: _PreparedCredentialValidation(
                adapter=adapter,
                request=ProviderCredentialValidationRequest(
                    provider=provider,
                    integration_id=integration_id,
                    revision_id=revision_id,
                    attempt_id=attempt_id,
                    credentials=bundle._provider_values(),
                ),
            ),
        )
        return PreparedOutboxDispatch(prepared)

    def execute(
        self,
        *,
        permit: OutboxDispatchPermit,
        prepared: PreparedOutboxDispatch,
    ) -> OutboxHandlerResult:
        del permit
        operation = prepared.value
        if not isinstance(operation, _PreparedCredentialValidation):
            raise TypeError("prepared credential validation is invalid")
        result = operation.dispatch_once()
        disposition = (
            OutboxResultDisposition.UNKNOWN
            if result.decision is CredentialValidationDecision.UNKNOWN
            else OutboxResultDisposition.COMPLETE
        )
        return OutboxHandlerResult(
            disposition,
            safe_code=result.safe_code,
            safe_facts_digest=result.safe_facts_digest,
            value=result,
            reason_code=(
                "provider_result_unknown"
                if disposition is OutboxResultDisposition.UNKNOWN
                else None
            ),
        )

    def persist_result(
        self,
        session: Session,
        *,
        permit: OutboxDispatchPermit,
        result: OutboxHandlerResult,
        completed_at,
    ) -> None:
        validation = result.value
        if not isinstance(validation, CredentialValidationResult):
            raise TypeError("credential validation result is invalid")
        if validation.decision is CredentialValidationDecision.UNKNOWN:
            raise ValueError("unknown validation requires reconciliation")
        outcome = (
            ProviderValidationOutcome.SUCCESS
            if validation.decision is CredentialValidationDecision.VALID
            else ProviderValidationOutcome.DEFINITIVE_FAILURE
        )
        TenantIntegrationService(session).record_provider_validation_result(
            revision_uuid=permit.source_uuid,
            attempt_uuid=_attempt_uuid(permit),
            outcome=outcome,
            provider_result_digest=validation.safe_facts_digest,
            safe_code=validation.safe_code,
            completed_at=completed_at,
        )

    def persist_unknown(
        self,
        session: Session,
        *,
        permit: OutboxDispatchPermit,
        result: OutboxHandlerResult | None,
        reason_code: str,
        completed_at,
    ) -> None:
        validation = result.value if result is not None else None
        if (
            isinstance(validation, CredentialValidationResult)
            and validation.decision is CredentialValidationDecision.UNKNOWN
        ):
            digest = validation.safe_facts_digest
            safe_code = validation.safe_code
        else:
            digest = hashlib.sha256(
                b"inventory-manager/integration-validation-unknown/v1\x00"
                + reason_code.encode("ascii", "strict")
            ).digest()
            safe_code = "VALIDATION_RESULT_UNKNOWN"
        TenantIntegrationService(session).record_provider_validation_result(
            revision_uuid=permit.source_uuid,
            attempt_uuid=_attempt_uuid(permit),
            outcome=ProviderValidationOutcome.UNKNOWN,
            provider_result_digest=digest,
            safe_code=safe_code,
            completed_at=completed_at,
        )


def _payload(permit: OutboxDispatchPermit) -> Mapping[str, Any]:
    if not isinstance(permit.payload, Mapping):
        raise ValueError("integration validation payload is invalid")
    return permit.payload


def _attempt_uuid(permit: OutboxDispatchPermit) -> str:
    return str(uuid5(
        _ATTEMPT_NAMESPACE,
        f"{permit.event_id}:{permit.execution_generation}",
    ))


def _uuid(value) -> str:
    return str(UUID(str(value)))


def _positive(value) -> int:
    if isinstance(value, bool):
        raise ValueError("positive integer is required")
    parsed = int(value)
    if parsed < 1 or str(parsed) != str(value):
        raise ValueError("positive integer is required")
    return parsed


def _reason_code(value) -> str:
    if not isinstance(value, str) or not value:
        return "tenant_gate_denied"
    normalized = re.sub(r"[^a-z0-9_.:-]+", "_", value.lower()).strip("_")
    return normalized[:64] or "tenant_gate_denied"


__all__ = [
    "CredentialValidationDecision",
    "CredentialValidationResult",
    "INTEGRATION_REVISION_SOURCE_TYPE",
    "INTEGRATION_VALIDATION_EVENT_TYPE",
    "ProviderCredentialValidationRequest",
    "ProviderCredentialValidator",
    "TenantIntegrationCredentialValidationHandler",
    "TenantIntegrationOutboxAuthority",
]
