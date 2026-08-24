"""SF provider-account validation on the reusable ordinary-outbox runtime."""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Mapping, Protocol
from uuid import UUID, uuid5

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.crypto import SqlAlchemyRootKeyRegistry
from inventory_control.domain import EffectiveTenantGate, TenantRole
from inventory_control.integrations import (
    ProviderValidationOutcome,
    SfAdminClaimProof,
    SfClaimOwner,
    TenantIntegrationService,
    TenantProviderAccountService,
)
from inventory_control.jobs import (
    ControlTenantGateReader,
    ControlJobService,
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
from inventory_control.models import (
    ProviderAccountClaim,
    SmsChallenge,
    TenantIntegration,
    TenantIntegrationSecretRevision,
    TenantMembership,
    TenantProviderAccountSecretRevision,
    TenantSensitiveActionIntent,
    TenantSensitiveActionIntentChallenge,
    TenantUserSession,
    User,
)

from .validation_worker import (
    CredentialValidationDecision,
    CredentialValidationResult,
)
from .provider_binding_worker import (
    PROVIDER_BINDING_APPLY_EVENT_TYPE,
    PROVIDER_BINDING_REVISION_SOURCE_TYPE,
)


PROVIDER_ACCOUNT_VALIDATION_EVENT_TYPE = "sf_provider_account_validate"
PROVIDER_ACCOUNT_REVISION_SOURCE_TYPE = "tenant_provider_account_secret_revision"
_ATTEMPT_NAMESPACE = UUID("adf841cd-b1b5-5cbd-8678-f3998695220f")
_D48_PURPOSES = frozenset({"sf_account_bind", "sf_account_rebind"})


class SfProviderAccountValidationRequest:
    """One-shot bridge containing one exact API revision and account value."""

    __slots__ = (
        "tenant_id",
        "warehouse_id",
        "integration_id",
        "provider_account_id",
        "integration_revision_id",
        "account_revision_id",
        "attempt_id",
        "_integration_credentials",
        "_account_secret",
    )

    def __init__(
        self,
        *,
        tenant_id: str,
        warehouse_id: str,
        integration_id: str,
        provider_account_id: str,
        integration_revision_id: str,
        account_revision_id: str,
        attempt_id: str,
        integration_credentials: Mapping[str, str],
        account_secret: str,
    ) -> None:
        self.tenant_id = _uuid(tenant_id)
        self.warehouse_id = _uuid(warehouse_id)
        self.integration_id = _uuid(integration_id)
        self.provider_account_id = _uuid(provider_account_id)
        self.integration_revision_id = _uuid(integration_revision_id)
        self.account_revision_id = _uuid(account_revision_id)
        self.attempt_id = _uuid(attempt_id)
        self._integration_credentials = dict(integration_credentials)
        self._account_secret = account_secret

    def take_credentials(self) -> tuple[Mapping[str, str], str]:
        if self._integration_credentials is None or self._account_secret is None:
            raise RuntimeError("provider account credentials are no longer available")
        credentials = MappingProxyType(self._integration_credentials)
        account_secret = self._account_secret
        self._integration_credentials = None
        self._account_secret = None
        return credentials, account_secret

    def discard_credentials(self) -> None:
        self._integration_credentials = None
        self._account_secret = None

    def __repr__(self) -> str:
        return (
            "SfProviderAccountValidationRequest("
            f"account_revision_id={self.account_revision_id!r}, "
            "credentials=<redacted>)"
        )


class SfProviderAccountValidator(Protocol):
    def validate_account(
        self,
        request: SfProviderAccountValidationRequest,
    ) -> CredentialValidationResult: ...


@dataclass(frozen=True, slots=True)
class _LockedProviderAccountAuthority:
    tenant_authority: Any
    revision: TenantProviderAccountSecretRevision | None
    claim: ProviderAccountClaim | None
    integration: TenantIntegration | None
    integration_revision: TenantIntegrationSecretRevision | None
    input_valid: bool


class TenantProviderAccountOutboxAuthority:
    """Current D56 and exact account/integration/claim dispatch authority."""

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
    ) -> _LockedProviderAccountAuthority:
        del phase
        valid = bool(
            facts.tenant_id is not None
            and facts.tenant_access_version is not None
            and facts.source_type == PROVIDER_ACCOUNT_REVISION_SOURCE_TYPE
            and facts.event_type == PROVIDER_ACCOUNT_VALIDATION_EVENT_TYPE
        )
        if not valid:
            return _LockedProviderAccountAuthority(
                None, None, None, None, None, False
            )
        tenant = self._gate_reader.lock_current(
            session,
            tenant_id=facts.tenant_id,
            presented_access_version=facts.tenant_access_version,
        )
        revision = session.scalar(
            sa.select(TenantProviderAccountSecretRevision)
            .where(TenantProviderAccountSecretRevision.id == facts.source_uuid)
            .with_for_update()
        )
        claim = (
            None
            if revision is None
            else session.scalar(
                sa.select(ProviderAccountClaim)
                .where(
                    ProviderAccountClaim.id
                    == revision.provider_account_claim_id
                )
                .with_for_update()
            )
        )
        integration = (
            None
            if revision is None
            else session.scalar(
                sa.select(TenantIntegration)
                .where(TenantIntegration.id == revision.integration_id)
                .with_for_update()
            )
        )
        integration_revision = (
            None
            if revision is None
            else session.scalar(
                sa.select(TenantIntegrationSecretRevision)
                .where(
                    TenantIntegrationSecretRevision.id
                    == revision.validation_integration_secret_revision_id
                )
                .with_for_update()
            )
        )
        return _LockedProviderAccountAuthority(
            tenant,
            revision,
            claim,
            integration,
            integration_revision,
            True,
        )

    def evaluate_locked_outbox_authority(
        self,
        session: Session,
        *,
        locked_authority: _LockedProviderAccountAuthority,
        facts: OutboxAuthorityFacts,
        phase: OutboxAuthorityPhase,
        now,
    ) -> OutboxAuthorityVerdict:
        del session, phase
        locked = locked_authority
        if not isinstance(locked, _LockedProviderAccountAuthority):
            raise TypeError("locked provider-account authority is invalid")
        tenant_row = getattr(locked.tenant_authority, "tenant", None)
        tenant_version = getattr(tenant_row, "access_version", None)
        revision = locked.revision
        source_generation = (
            revision.revision_no if revision is not None else facts.source_generation
        )
        recovery_verified = bool(
            locked.tenant_authority is not None
            and getattr(locked.tenant_authority, "recovery_released", None) is True
        )
        if not locked.input_valid or locked.tenant_authority is None:
            return _verdict(
                allowed=False,
                recovery_verified=recovery_verified,
                source_generation=source_generation,
                tenant_version=tenant_version,
                reason="provider_account_authority_invalid",
            )
        current = self._gate_reader.evaluate_locked(
            locked.tenant_authority,
            now=now,
        )
        source_valid = _source_is_current(locked, facts=facts)
        allowed = bool(current.allowed and source_valid and recovery_verified)
        reason = (
            "authority_allowed"
            if allowed
            else (
                _reason_code(current.reason_code)
                if not current.allowed
                else "provider_account_source_stale"
            )
        )
        return _verdict(
            allowed=allowed,
            recovery_verified=recovery_verified,
            source_generation=source_generation,
            tenant_version=tenant_version,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class _ValidationAuthority:
    proof: SfAdminClaimProof
    owner: SfClaimOwner
    binding_revision: int


class SfProviderAccountProofResolver:
    """Rehydrate D48 proof only from current control rows and a consumed intent."""

    def resolve(
        self,
        session: Session,
        *,
        revision_uuid: str,
        now,
    ) -> _ValidationAuthority:
        revision = session.scalar(
            sa.select(TenantProviderAccountSecretRevision)
            .where(TenantProviderAccountSecretRevision.id == _uuid(revision_uuid))
            .with_for_update()
        )
        if revision is None:
            raise ValueError("provider account revision is unavailable")
        intent = session.scalar(
            sa.select(TenantSensitiveActionIntent)
            .where(
                TenantSensitiveActionIntent.id
                == revision.created_from_action_uuid
            )
            .with_for_update()
        )
        link = session.scalar(
            sa.select(TenantSensitiveActionIntentChallenge)
            .where(
                TenantSensitiveActionIntentChallenge.intent_id
                == revision.created_from_action_uuid,
                TenantSensitiveActionIntentChallenge.challenge_role == "primary",
            )
            .with_for_update()
        )
        challenge = (
            None
            if link is None
            else session.scalar(
                sa.select(SmsChallenge)
                .where(SmsChallenge.id == link.challenge_id)
                .with_for_update()
            )
        )
        user = session.scalar(
            sa.select(User)
            .where(User.id == revision.created_by_user_uuid)
            .with_for_update()
        )
        membership = session.scalar(
            sa.select(TenantMembership)
            .where(
                TenantMembership.tenant_id == revision.tenant_id,
                TenantMembership.user_id == revision.created_by_user_uuid,
            )
            .with_for_update()
        )
        actor_session = (
            None
            if intent is None
            else session.scalar(
                sa.select(TenantUserSession)
                .where(TenantUserSession.id == intent.actor_session_id)
                .with_for_update()
            )
        )
        claim = session.scalar(
            sa.select(ProviderAccountClaim)
            .where(
                ProviderAccountClaim.id == revision.provider_account_claim_id
            )
            .with_for_update()
        )
        selected_now = _as_utc(now)
        if not _d48_rows_are_current(
            revision=revision,
            intent=intent,
            link=link,
            challenge=challenge,
            user=user,
            membership=membership,
            actor_session=actor_session,
            claim=claim,
            now=selected_now,
        ):
            raise ValueError("provider account D48 authority is stale")
        owner = SfClaimOwner(
            tenant_uuid=UUID(revision.tenant_id),
            provider_account_uuid=UUID(revision.tenant_provider_account_id),
            warehouse_uuid=UUID(claim.current_warehouse_uuid),
        )
        return _ValidationAuthority(
            proof=SfAdminClaimProof(
                tenant_uuid=owner.tenant_uuid,
                actor_user_uuid=UUID(user.id),
                actor_session_uuid=UUID(actor_session.id),
                role=TenantRole.ADMIN,
                effective_gate=EffectiveTenantGate.ACTIVE,
                tenant_access_version=actor_session.tenant_access_version_at_issue,
                otp_challenge_uuid=UUID(challenge.id),
                otp_purpose=challenge.purpose,
                otp_action_uuid=UUID(revision.created_from_action_uuid),
                otp_request_digest=bytes(revision.request_digest),
                otp_consumed=True,
            ),
            owner=owner,
            binding_revision=revision.target_binding_revision,
        )


class _PreparedSfAccountValidation:
    __slots__ = ("_adapter", "_request", "_dispatched")

    def __init__(self, *, adapter, request) -> None:
        self._adapter = adapter
        self._request = request
        self._dispatched = False

    def dispatch_once(self) -> CredentialValidationResult:
        if self._dispatched:
            raise RuntimeError("provider account validation was already dispatched")
        self._dispatched = True
        try:
            result = self._adapter.validate_account(self._request)
            if not isinstance(result, CredentialValidationResult):
                raise TypeError("provider returned an invalid validation result")
            return result
        finally:
            self._request.discard_credentials()

    def __repr__(self) -> str:
        return "_PreparedSfAccountValidation(<redacted>)"


class TenantProviderAccountValidationHandler(OrdinaryOutboxHandler):
    """Validate exact encrypted API/account revisions and persist one result."""

    def __init__(
        self,
        *,
        root_key_directory: str | os.PathLike[str],
        validator: SfProviderAccountValidator,
        proof_resolver: SfProviderAccountProofResolver | None = None,
        job_service: ControlJobService | None = None,
    ) -> None:
        root = os.fspath(root_key_directory)
        if not isinstance(root, str) or not Path(root).is_absolute():
            raise ValueError("root_key_directory must be absolute")
        if not callable(getattr(validator, "validate_account", None)):
            raise TypeError("SF provider-account validator is invalid")
        self._root_key_directory = root
        self._validator = validator
        self._proof_resolver = proof_resolver or SfProviderAccountProofResolver()
        self._jobs = job_service or ControlJobService()

    def prepare_dispatch(self, session, *, lease, permit):
        payload = _payload(permit)
        revision_id = _uuid(payload.get("revision_uuid"))
        expected_row = _positive(payload.get("revision_row_version"))
        if (
            permit.event_type != PROVIDER_ACCOUNT_VALIDATION_EVENT_TYPE
            or permit.source_type != PROVIDER_ACCOUNT_REVISION_SOURCE_TYPE
            or permit.source_uuid != revision_id
            or lease.event_id != permit.event_id
            or lease.tenant_id is None
        ):
            raise ValueError("provider account validation facts are invalid")
        revision = session.get(TenantProviderAccountSecretRevision, revision_id)
        if (
            revision is None
            or revision.tenant_id != lease.tenant_id
            or revision.revision_no != permit.source_generation
        ):
            raise ValueError("provider account validation source is stale")
        attempt_id = _attempt_uuid(permit)
        account_service = TenantProviderAccountService(session)
        account_service.begin_provider_validation(
            revision_uuid=revision.id,
            attempt_uuid=attempt_id,
            expected_revision_row_version=expected_row,
        )
        key_ring = SqlAlchemyRootKeyRegistry(session=session).load(
            self._root_key_directory
        )
        account_key = key_ring.key_for_existing_reference(revision.root_key_version)
        integration_revision = session.get(
            TenantIntegrationSecretRevision,
            revision.validation_integration_secret_revision_id,
        )
        if integration_revision is None:
            raise ValueError("integration credential revision is unavailable")
        integration_key = key_ring.key_for_existing_reference(
            integration_revision.root_key_version
        )

        def with_account(account_secret):
            return TenantIntegrationService(session).use_exact_revision(
                revision_uuid=integration_revision.id,
                root_key=integration_key,
                consumer=lambda bundle: _PreparedSfAccountValidation(
                    adapter=self._validator,
                    request=SfProviderAccountValidationRequest(
                        tenant_id=revision.tenant_id,
                        warehouse_id=_claim_warehouse(session, revision),
                        integration_id=revision.integration_id,
                        provider_account_id=revision.tenant_provider_account_id,
                        integration_revision_id=integration_revision.id,
                        account_revision_id=revision.id,
                        attempt_id=attempt_id,
                        integration_credentials=bundle._provider_values(),
                        account_secret=account_secret._provider_value(),
                    ),
                ),
            )

        prepared = account_service.use_pending_revision_for_validation(
            revision_uuid=revision.id,
            attempt_uuid=attempt_id,
            root_key=account_key,
            consumer=with_account,
        )
        return PreparedOutboxDispatch(prepared)

    def execute(self, *, permit, prepared):
        del permit
        operation = prepared.value
        if not isinstance(operation, _PreparedSfAccountValidation):
            raise TypeError("prepared provider account validation is invalid")
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

    def persist_result(self, session, *, permit, result, completed_at):
        validation = _validation_result(result)
        if validation.decision is CredentialValidationDecision.UNKNOWN:
            raise ValueError("unknown validation requires reconciliation")
        kwargs = {}
        if validation.decision is CredentialValidationDecision.VALID:
            authority = self._proof_resolver.resolve(
                session,
                revision_uuid=permit.source_uuid,
                now=completed_at,
            )
            kwargs = {
                "proof": authority.proof,
                "owner": authority.owner,
                "binding_revision": authority.binding_revision,
            }
        revision = TenantProviderAccountService(
            session
        ).record_provider_validation_result(
            revision_uuid=permit.source_uuid,
            attempt_uuid=_attempt_uuid(permit),
            outcome=(
                ProviderValidationOutcome.SUCCESS
                if validation.decision is CredentialValidationDecision.VALID
                else ProviderValidationOutcome.DEFINITIVE_FAILURE
            ),
            provider_result_digest=validation.safe_facts_digest,
            safe_code=validation.safe_code,
            completed_at=completed_at,
            **kwargs,
        )
        if validation.decision is CredentialValidationDecision.VALID:
            authority = kwargs["proof"]
            self._jobs.enqueue_outbox(
                session,
                source_type=PROVIDER_BINDING_REVISION_SOURCE_TYPE,
                source_uuid=revision.revision_uuid,
                source_generation=revision.revision_no,
                event_type=PROVIDER_BINDING_APPLY_EVENT_TYPE,
                payload={"revision_uuid": revision.revision_uuid},
                idempotency_key=f"sf-binding-apply:{revision.revision_uuid}",
                tenant_id=revision.tenant_uuid,
                tenant_access_version=authority.tenant_access_version,
                max_attempts=1,
                available_at=completed_at,
            )

    def persist_unknown(
        self,
        session,
        *,
        permit,
        result,
        reason_code,
        completed_at,
    ):
        validation = result.value if result is not None else None
        if (
            isinstance(validation, CredentialValidationResult)
            and validation.decision is CredentialValidationDecision.UNKNOWN
        ):
            digest = validation.safe_facts_digest
            safe_code = validation.safe_code
        else:
            digest = hashlib.sha256(
                b"inventory-manager/provider-account-validation-unknown/v1\x00"
                + reason_code.encode("ascii", "strict")
            ).digest()
            safe_code = "VALIDATION_RESULT_UNKNOWN"
        TenantProviderAccountService(session).record_provider_validation_result(
            revision_uuid=permit.source_uuid,
            attempt_uuid=_attempt_uuid(permit),
            outcome=ProviderValidationOutcome.UNKNOWN,
            provider_result_digest=digest,
            safe_code=safe_code,
            completed_at=completed_at,
        )


def _source_is_current(locked, *, facts) -> bool:
    revision = locked.revision
    claim = locked.claim
    integration = locked.integration
    integration_revision = locked.integration_revision
    return bool(
        revision is not None
        and revision.tenant_id == facts.tenant_id
        and revision.revision_no == facts.source_generation
        and revision.status == "pending_validation"
        and revision.verification_status in ("not_attempted", "submitting")
        and claim is not None
        and claim.id == revision.provider_account_claim_id
        and claim.claim_generation == revision.expected_claim_generation
        and claim.row_version == revision.expected_claim_row_version
        and claim.claim_status in ("reserved", "active")
        and claim.current_provider_account_id
        == revision.tenant_provider_account_id
        and claim.current_tenant_id == revision.tenant_id
        and integration is not None
        and integration.id == revision.integration_id
        and integration.tenant_id == revision.tenant_id
        and integration.status == "active"
        and integration.row_version == revision.expected_integration_row_version
        and integration.current_secret_revision_id
        == revision.validation_integration_secret_revision_id
        and integration_revision is not None
        and integration_revision.id == integration.current_secret_revision_id
        and integration_revision.status == "current"
        and integration_revision.verification_status == "succeeded"
    )


def _d48_rows_are_current(
    *,
    revision,
    intent,
    link,
    challenge,
    user,
    membership,
    actor_session,
    claim,
    now,
) -> bool:
    return bool(
        intent is not None
        and intent.id == revision.created_from_action_uuid
        and intent.tenant_id == revision.tenant_id
        and intent.actor_user_id == revision.created_by_user_uuid
        and intent.purpose in _D48_PURPOSES
        and intent.status == "succeeded"
        and link is not None
        and challenge is not None
        and challenge.id == link.challenge_id
        and challenge.purpose == intent.purpose
        and challenge.tenant_id == revision.tenant_id
        and challenge.user_id == revision.created_by_user_uuid
        and challenge.actor_session_id == intent.actor_session_id
        and challenge.verification_state == "consumed"
        and challenge.consumed_at is not None
        and user is not None
        and user.status == "active"
        and membership is not None
        and membership.status == "active"
        and membership.role_key == TenantRole.ADMIN.value
        and actor_session is not None
        and actor_session.user_id == user.id
        and actor_session.auth_version_at_issue == user.auth_version
        and actor_session.revoked_at is None
        and _as_utc(actor_session.idle_expires_at) > now
        and _as_utc(actor_session.absolute_expires_at) > now
        and claim is not None
        and claim.current_provider_account_id
        == revision.tenant_provider_account_id
        and claim.current_tenant_id == revision.tenant_id
        and claim.current_warehouse_uuid is not None
        and claim.claim_generation == revision.expected_claim_generation
        and claim.row_version == revision.expected_claim_row_version
        and claim.claim_status in ("reserved", "active")
    )


def _claim_warehouse(session, revision) -> str:
    claim = session.get(ProviderAccountClaim, revision.provider_account_claim_id)
    if (
        claim is None
        or claim.current_provider_account_id != revision.tenant_provider_account_id
        or claim.current_tenant_id != revision.tenant_id
        or claim.current_warehouse_uuid is None
    ):
        raise ValueError("provider account claim owner is stale")
    return claim.current_warehouse_uuid


def _validation_result(result) -> CredentialValidationResult:
    value = result.value
    if not isinstance(value, CredentialValidationResult):
        raise TypeError("provider account validation result is invalid")
    return value


def _payload(permit) -> Mapping[str, Any]:
    if not isinstance(permit.payload, Mapping):
        raise ValueError("provider account validation payload is invalid")
    return permit.payload


def _attempt_uuid(permit) -> str:
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


def _as_utc(value):
    from datetime import timezone

    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _reason_code(value) -> str:
    if not isinstance(value, str) or not value:
        return "tenant_gate_denied"
    return value.lower().replace(" ", "_")[:64]


def _verdict(
    *,
    allowed,
    recovery_verified,
    source_generation,
    tenant_version,
    reason,
):
    return OutboxAuthorityVerdict(
        allowed=allowed,
        current_recovery_run_verified=recovery_verified,
        current_source_generation=source_generation,
        current_tenant_access_version=tenant_version,
        reason_code=reason,
    )


__all__ = [
    "PROVIDER_ACCOUNT_REVISION_SOURCE_TYPE",
    "PROVIDER_ACCOUNT_VALIDATION_EVENT_TYPE",
    "SfProviderAccountProofResolver",
    "SfProviderAccountValidationRequest",
    "SfProviderAccountValidator",
    "TenantProviderAccountOutboxAuthority",
    "TenantProviderAccountValidationHandler",
]
