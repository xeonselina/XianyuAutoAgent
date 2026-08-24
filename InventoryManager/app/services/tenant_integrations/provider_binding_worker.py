"""Idempotent tenant-binding leg of the SF provider-account saga."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Protocol
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.services.warehouse import WarehouseProviderBindingService
from inventory_control.jobs import (
    ControlTenantGateReader,
    OrdinaryOutboxHandler,
    OutboxAuthorityFacts,
    OutboxAuthorityPhase,
    OutboxAuthorityVerdict,
    OutboxHandlerResult,
    OutboxResultDisposition,
    PreparedOutboxDispatch,
)
from inventory_control.models import (
    ProviderAccountClaim,
    ProviderAccountClaimEvent,
    TenantProviderAccount,
    TenantProviderAccountSecretRevision,
)


PROVIDER_BINDING_APPLY_EVENT_TYPE = "sf_warehouse_binding_apply"
PROVIDER_BINDING_REMOVE_EVENT_TYPE = "sf_warehouse_binding_remove"
PROVIDER_BINDING_REVISION_SOURCE_TYPE = "tenant_provider_account_secret_revision"
PROVIDER_CLAIM_RELEASE_SOURCE_TYPE = "provider_account_claim_release"


@dataclass(frozen=True, slots=True, repr=False)
class SfWarehouseBindingApplyRequest:
    tenant_id: str
    tenant_access_version: int
    warehouse_id: str
    provider_account_id: str
    account_revision_id: str
    account_revision_no: int
    target_binding_revision: int
    expected_provider_account_id: str | None
    expected_binding_revision: int | None
    actor_user_id: str
    verified_at: Any

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "warehouse_id",
            "provider_account_id",
            "account_revision_id",
            "actor_user_id",
        ):
            object.__setattr__(self, name, _uuid(getattr(self, name)))
        if self.expected_provider_account_id is not None:
            object.__setattr__(
                self,
                "expected_provider_account_id",
                _uuid(self.expected_provider_account_id),
            )
        _positive(self.tenant_access_version)
        _positive(self.account_revision_no)
        _positive(self.target_binding_revision)
        if self.expected_binding_revision is not None:
            _positive(self.expected_binding_revision)

    def __repr__(self) -> str:
        return (
            "SfWarehouseBindingApplyRequest("
            f"tenant_id={self.tenant_id!r}, warehouse_id={self.warehouse_id!r}, "
            f"account_revision_id={self.account_revision_id!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class SfWarehouseBindingApplyResult:
    safe_code: str
    safe_facts_digest: bytes = field(repr=False)
    binding_revision: int
    idempotent_replay: bool

    def __post_init__(self) -> None:
        if (
            not isinstance(self.safe_code, str)
            or not self.safe_code
            or not isinstance(self.safe_facts_digest, bytes)
            or len(self.safe_facts_digest) != 32
            or not isinstance(self.idempotent_replay, bool)
        ):
            raise ValueError("warehouse binding result is invalid")
        _positive(self.binding_revision)

    def __repr__(self) -> str:
        return (
            "SfWarehouseBindingApplyResult("
            f"safe_code={self.safe_code!r}, binding_revision="
            f"{self.binding_revision!r}, <redacted>)"
        )


@dataclass(frozen=True, slots=True, repr=False)
class SfWarehouseBindingRemoveRequest:
    tenant_id: str
    tenant_access_version: int
    warehouse_id: str
    provider_account_id: str
    claim_id: str
    release_generation: int
    expected_binding_revision: int
    actor_user_id: str
    occurred_at: Any

    def __post_init__(self) -> None:
        for name in (
            "tenant_id",
            "warehouse_id",
            "provider_account_id",
            "claim_id",
            "actor_user_id",
        ):
            object.__setattr__(self, name, _uuid(getattr(self, name)))
        _positive(self.tenant_access_version)
        _positive(self.release_generation)
        _positive(self.expected_binding_revision)

    def __repr__(self) -> str:
        return (
            "SfWarehouseBindingRemoveRequest("
            f"tenant_id={self.tenant_id!r}, warehouse_id={self.warehouse_id!r}, "
            f"claim_id={self.claim_id!r})"
        )


class TenantWarehouseBindingApplier(Protocol):
    def apply_binding(
        self,
        request: SfWarehouseBindingApplyRequest,
    ) -> SfWarehouseBindingApplyResult: ...

    def remove_binding(
        self,
        request: SfWarehouseBindingRemoveRequest,
    ) -> SfWarehouseBindingApplyResult: ...


class SqlAlchemyTenantWarehouseBindingApplier:
    """Apply a trusted worker command through an injected tenant DML engine."""

    def __init__(
        self,
        *,
        engine_resolver: Callable[
            [SfWarehouseBindingApplyRequest | SfWarehouseBindingRemoveRequest],
            Engine,
        ],
    ) -> None:
        if not callable(engine_resolver):
            raise TypeError("engine_resolver must be callable")
        self._engine_resolver = engine_resolver

    def apply_binding(
        self,
        request: SfWarehouseBindingApplyRequest,
    ) -> SfWarehouseBindingApplyResult:
        if not isinstance(request, SfWarehouseBindingApplyRequest):
            raise TypeError("warehouse binding request is invalid")
        engine = self._engine_resolver(request)
        if not isinstance(engine, Engine):
            raise RuntimeError("tenant DML engine is unavailable")
        with Session(bind=engine, autoflush=False, expire_on_commit=False) as session:
            with session.begin():
                result = WarehouseProviderBindingService(session).bind_sf_account(
                    warehouse_uuid=request.warehouse_id,
                    provider_account_uuid=request.provider_account_id,
                    binding_revision=request.target_binding_revision,
                    actor_user_uuid=request.actor_user_id,
                    verified_at=request.verified_at,
                    expected_provider_account_uuid=(
                        request.expected_provider_account_id
                    ),
                    expected_binding_revision=request.expected_binding_revision,
                )
        return SfWarehouseBindingApplyResult(
            safe_code="WAREHOUSE_BINDING_APPLIED",
            safe_facts_digest=_binding_digest(request),
            binding_revision=result.binding_revision,
            idempotent_replay=result.idempotent_replay,
        )

    def remove_binding(
        self,
        request: SfWarehouseBindingRemoveRequest,
    ) -> SfWarehouseBindingApplyResult:
        if not isinstance(request, SfWarehouseBindingRemoveRequest):
            raise TypeError("warehouse unbinding request is invalid")
        engine = self._engine_resolver(request)
        if not isinstance(engine, Engine):
            raise RuntimeError("tenant DML engine is unavailable")
        with Session(bind=engine, autoflush=False, expire_on_commit=False) as session:
            with session.begin():
                result = WarehouseProviderBindingService(
                    session
                ).unbind_sf_account(
                    warehouse_uuid=request.warehouse_id,
                    provider_account_uuid=request.provider_account_id,
                    expected_binding_revision=request.expected_binding_revision,
                    actor_user_uuid=request.actor_user_id,
                    occurred_at=request.occurred_at,
                )
        return SfWarehouseBindingApplyResult(
            safe_code="WAREHOUSE_BINDING_REMOVED",
            safe_facts_digest=_unbinding_digest(request),
            binding_revision=result.binding_revision,
            idempotent_replay=result.idempotent_replay,
        )


@dataclass(frozen=True, slots=True)
class _LockedBindingAuthority:
    tenant_authority: Any
    revision: TenantProviderAccountSecretRevision | None
    account: TenantProviderAccount | None
    claim: ProviderAccountClaim | None
    input_valid: bool


class TenantProviderBindingOutboxAuthority:
    """Allow only an active exact account/claim revision to reach tenant DML."""

    def __init__(self, gate_reader: ControlTenantGateReader) -> None:
        if not isinstance(gate_reader, ControlTenantGateReader):
            raise TypeError("gate_reader must be a ControlTenantGateReader")
        self._gate_reader = gate_reader

    def lock_current_outbox_authority(self, session, *, facts, phase):
        del phase
        valid = bool(
            facts.tenant_id is not None
            and facts.tenant_access_version is not None
            and facts.source_type == PROVIDER_BINDING_REVISION_SOURCE_TYPE
            and facts.event_type == PROVIDER_BINDING_APPLY_EVENT_TYPE
        )
        if not valid:
            return _LockedBindingAuthority(None, None, None, None, False)
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
        account = (
            None
            if revision is None
            else session.scalar(
                sa.select(TenantProviderAccount)
                .where(
                    TenantProviderAccount.id
                    == revision.tenant_provider_account_id
                )
                .with_for_update()
            )
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
        return _LockedBindingAuthority(tenant, revision, account, claim, True)

    def evaluate_locked_outbox_authority(
        self,
        session,
        *,
        locked_authority,
        facts,
        phase,
        now,
    ):
        del session, phase
        locked = locked_authority
        if not isinstance(locked, _LockedBindingAuthority):
            raise TypeError("locked warehouse binding authority is invalid")
        tenant_row = getattr(locked.tenant_authority, "tenant", None)
        tenant_version = getattr(tenant_row, "access_version", None)
        source_generation = (
            locked.revision.revision_no
            if locked.revision is not None
            else facts.source_generation
        )
        recovery_verified = bool(
            locked.tenant_authority is not None
            and getattr(locked.tenant_authority, "recovery_released", None) is True
        )
        if not locked.input_valid or locked.tenant_authority is None:
            return _verdict(
                False,
                recovery_verified,
                source_generation,
                tenant_version,
                "provider_binding_authority_invalid",
            )
        current = self._gate_reader.evaluate_locked(
            locked.tenant_authority,
            now=now,
        )
        source_valid = _binding_source_is_current(locked, facts=facts)
        allowed = bool(current.allowed and source_valid and recovery_verified)
        reason = (
            "authority_allowed"
            if allowed
            else (
                _reason_code(current.reason_code)
                if not current.allowed
                else "provider_binding_source_stale"
            )
        )
        return _verdict(
            allowed,
            recovery_verified,
            source_generation,
            tenant_version,
            reason,
        )


class TenantProviderBindingApplyHandler(OrdinaryOutboxHandler):
    def __init__(self, *, applier: TenantWarehouseBindingApplier) -> None:
        if not callable(getattr(applier, "apply_binding", None)):
            raise TypeError("tenant warehouse binding applier is invalid")
        self._applier = applier

    def prepare_dispatch(self, session, *, lease, permit):
        if (
            permit.event_type != PROVIDER_BINDING_APPLY_EVENT_TYPE
            or permit.source_type != PROVIDER_BINDING_REVISION_SOURCE_TYPE
            or lease.event_id != permit.event_id
            or lease.tenant_id is None
        ):
            raise ValueError("warehouse binding outbox facts are invalid")
        revision = session.get(
            TenantProviderAccountSecretRevision,
            permit.source_uuid,
        )
        account = (
            None
            if revision is None
            else session.get(
                TenantProviderAccount,
                revision.tenant_provider_account_id,
            )
        )
        claim = (
            None
            if revision is None
            else session.get(ProviderAccountClaim, revision.provider_account_claim_id)
        )
        if not _binding_rows_match(
            revision=revision,
            account=account,
            claim=claim,
            tenant_id=lease.tenant_id,
            source_generation=permit.source_generation,
        ):
            raise ValueError("warehouse binding source is stale")
        return PreparedOutboxDispatch(SfWarehouseBindingApplyRequest(
            tenant_id=revision.tenant_id,
            tenant_access_version=lease.tenant_access_version,
            warehouse_id=claim.current_warehouse_uuid,
            provider_account_id=account.id,
            account_revision_id=revision.id,
            account_revision_no=revision.revision_no,
            target_binding_revision=revision.target_binding_revision,
            expected_provider_account_id=(
                revision.expected_warehouse_provider_account_id
            ),
            expected_binding_revision=(
                revision.expected_warehouse_binding_revision
            ),
            actor_user_id=revision.created_by_user_uuid,
            verified_at=revision.verification_completed_at,
        ))

    def execute(self, *, permit, prepared):
        del permit
        request = prepared.value
        if not isinstance(request, SfWarehouseBindingApplyRequest):
            raise TypeError("prepared warehouse binding request is invalid")
        result = self._applier.apply_binding(request)
        if not isinstance(result, SfWarehouseBindingApplyResult):
            raise TypeError("tenant binding applier returned an invalid result")
        return OutboxHandlerResult(
            OutboxResultDisposition.COMPLETE,
            safe_code=result.safe_code,
            safe_facts_digest=result.safe_facts_digest,
            value=result,
        )

    def persist_result(self, session, *, permit, result, completed_at):
        del session, permit, completed_at
        if not isinstance(result.value, SfWarehouseBindingApplyResult):
            raise TypeError("warehouse binding result is invalid")

    def persist_unknown(
        self,
        session,
        *,
        permit,
        result,
        reason_code,
        completed_at,
    ):
        del session, permit, result, reason_code, completed_at


@dataclass(frozen=True, slots=True)
class _LockedUnbindingAuthority:
    tenant_authority: Any
    release_event: ProviderAccountClaimEvent | None
    account: TenantProviderAccount | None
    input_valid: bool


class TenantProviderUnbindingOutboxAuthority:
    """Authorize cleanup from the immutable release event, not current owner."""

    def __init__(self, gate_reader: ControlTenantGateReader) -> None:
        if not isinstance(gate_reader, ControlTenantGateReader):
            raise TypeError("gate_reader must be a ControlTenantGateReader")
        self._gate_reader = gate_reader

    def lock_current_outbox_authority(self, session, *, facts, phase):
        del phase
        valid = bool(
            facts.tenant_id is not None
            and facts.tenant_access_version is not None
            and facts.source_type == PROVIDER_CLAIM_RELEASE_SOURCE_TYPE
            and facts.event_type == PROVIDER_BINDING_REMOVE_EVENT_TYPE
        )
        if not valid:
            return _LockedUnbindingAuthority(None, None, None, False)
        tenant = self._gate_reader.lock_current(
            session,
            tenant_id=facts.tenant_id,
            presented_access_version=facts.tenant_access_version,
        )
        event = session.scalar(
            sa.select(ProviderAccountClaimEvent)
            .where(
                ProviderAccountClaimEvent.provider_account_claim_id
                == facts.source_uuid,
                ProviderAccountClaimEvent.claim_generation
                == facts.source_generation,
            )
            .with_for_update()
        )
        account = (
            None
            if event is None or event.previous_provider_account_id is None
            else session.scalar(
                sa.select(TenantProviderAccount)
                .where(
                    TenantProviderAccount.id
                    == event.previous_provider_account_id
                )
                .with_for_update()
            )
        )
        return _LockedUnbindingAuthority(tenant, event, account, True)

    def evaluate_locked_outbox_authority(
        self,
        session,
        *,
        locked_authority,
        facts,
        phase,
        now,
    ):
        del session, phase
        locked = locked_authority
        if not isinstance(locked, _LockedUnbindingAuthority):
            raise TypeError("locked warehouse unbinding authority is invalid")
        tenant_row = getattr(locked.tenant_authority, "tenant", None)
        tenant_version = getattr(tenant_row, "access_version", None)
        recovery_verified = bool(
            locked.tenant_authority is not None
            and getattr(locked.tenant_authority, "recovery_released", None) is True
        )
        if not locked.input_valid or locked.tenant_authority is None:
            return _verdict(
                False,
                recovery_verified,
                facts.source_generation,
                tenant_version,
                "provider_unbinding_authority_invalid",
            )
        current = self._gate_reader.evaluate_locked(
            locked.tenant_authority,
            now=now,
        )
        event = locked.release_event
        account = locked.account
        source_valid = bool(
            event is not None
            and event.provider_account_claim_id == facts.source_uuid
            and event.claim_generation == facts.source_generation
            and event.to_status == "released"
            and event.actor_type == "tenant_admin"
            and event.previous_tenant_id == facts.tenant_id
            and event.previous_provider_account_id is not None
            and event.previous_warehouse_uuid is not None
            and event.actor_user_uuid is not None
            and event.actor_session_uuid is not None
            and event.otp_challenge_uuid is not None
            and account is not None
            and account.id == event.previous_provider_account_id
            and account.tenant_id == facts.tenant_id
            and account.status == "inactive"
            and account.current_global_claim_id is None
            and account.current_claim_generation is None
        )
        allowed = bool(current.allowed and source_valid and recovery_verified)
        reason = (
            "authority_allowed"
            if allowed
            else (
                _reason_code(current.reason_code)
                if not current.allowed
                else "provider_unbinding_source_stale"
            )
        )
        return _verdict(
            allowed,
            recovery_verified,
            facts.source_generation,
            tenant_version,
            reason,
        )


class TenantProviderBindingRemoveHandler(OrdinaryOutboxHandler):
    def __init__(self, *, applier: TenantWarehouseBindingApplier) -> None:
        if not callable(getattr(applier, "remove_binding", None)):
            raise TypeError("tenant warehouse binding applier is invalid")
        self._applier = applier

    def prepare_dispatch(self, session, *, lease, permit):
        payload = permit.payload
        if (
            permit.event_type != PROVIDER_BINDING_REMOVE_EVENT_TYPE
            or permit.source_type != PROVIDER_CLAIM_RELEASE_SOURCE_TYPE
            or lease.event_id != permit.event_id
            or lease.tenant_id is None
            or not isinstance(payload, Mapping)
        ):
            raise ValueError("warehouse unbinding outbox facts are invalid")
        event = session.scalar(
            sa.select(ProviderAccountClaimEvent).where(
                ProviderAccountClaimEvent.provider_account_claim_id
                == permit.source_uuid,
                ProviderAccountClaimEvent.claim_generation
                == permit.source_generation,
            )
        )
        if (
            event is None
            or event.to_status != "released"
            or event.previous_tenant_id != lease.tenant_id
            or event.previous_provider_account_id
            != _uuid(payload.get("provider_account_uuid"))
            or event.previous_warehouse_uuid
            != _uuid(payload.get("warehouse_uuid"))
            or event.actor_user_uuid is None
        ):
            raise ValueError("warehouse unbinding source is stale")
        return PreparedOutboxDispatch(SfWarehouseBindingRemoveRequest(
            tenant_id=lease.tenant_id,
            tenant_access_version=lease.tenant_access_version,
            warehouse_id=event.previous_warehouse_uuid,
            provider_account_id=event.previous_provider_account_id,
            claim_id=event.provider_account_claim_id,
            release_generation=event.claim_generation,
            expected_binding_revision=_positive(
                payload.get("expected_binding_revision")
            ),
            actor_user_id=event.actor_user_uuid,
            occurred_at=event.created_at,
        ))

    def execute(self, *, permit, prepared):
        del permit
        request = prepared.value
        if not isinstance(request, SfWarehouseBindingRemoveRequest):
            raise TypeError("prepared warehouse unbinding request is invalid")
        result = self._applier.remove_binding(request)
        if not isinstance(result, SfWarehouseBindingApplyResult):
            raise TypeError("tenant unbinding applier returned an invalid result")
        return OutboxHandlerResult(
            OutboxResultDisposition.COMPLETE,
            safe_code=result.safe_code,
            safe_facts_digest=result.safe_facts_digest,
            value=result,
        )

    def persist_result(self, session, *, permit, result, completed_at):
        del session, permit, completed_at
        if not isinstance(result.value, SfWarehouseBindingApplyResult):
            raise TypeError("warehouse unbinding result is invalid")

    def persist_unknown(
        self,
        session,
        *,
        permit,
        result,
        reason_code,
        completed_at,
    ):
        del session, permit, result, reason_code, completed_at


def _binding_source_is_current(locked, *, facts) -> bool:
    return _binding_rows_match(
        revision=locked.revision,
        account=locked.account,
        claim=locked.claim,
        tenant_id=facts.tenant_id,
        source_generation=facts.source_generation,
    )


def _binding_rows_match(
    *,
    revision,
    account,
    claim,
    tenant_id,
    source_generation,
) -> bool:
    return bool(
        revision is not None
        and revision.tenant_id == tenant_id
        and revision.revision_no == source_generation
        and revision.status == "current"
        and revision.verification_status == "succeeded"
        and revision.verification_completed_at is not None
        and account is not None
        and account.id == revision.tenant_provider_account_id
        and account.tenant_id == revision.tenant_id
        and account.status == "active"
        and account.current_secret_revision_id == revision.id
        and account.current_global_claim_id == revision.provider_account_claim_id
        and account.current_claim_generation == revision.activated_claim_generation
        and claim is not None
        and claim.id == revision.provider_account_claim_id
        and claim.claim_status == "active"
        and claim.claim_generation == revision.activated_claim_generation
        and claim.current_provider_account_id == account.id
        and claim.current_tenant_id == revision.tenant_id
        and claim.current_warehouse_uuid is not None
        and claim.active_binding_revision == revision.target_binding_revision
    )


def _binding_digest(request) -> bytes:
    values = (
        request.tenant_id,
        request.warehouse_id,
        request.provider_account_id,
        request.account_revision_id,
        str(request.account_revision_no),
        str(request.target_binding_revision),
    )
    return hashlib.sha256(
        b"inventory-manager/sf-warehouse-binding-result/v1\x00"
        + b"\x00".join(value.encode("ascii") for value in values)
    ).digest()


def _unbinding_digest(request) -> bytes:
    values = (
        request.tenant_id,
        request.warehouse_id,
        request.provider_account_id,
        request.claim_id,
        str(request.release_generation),
        str(request.expected_binding_revision),
    )
    return hashlib.sha256(
        b"inventory-manager/sf-warehouse-unbinding-result/v1\x00"
        + b"\x00".join(value.encode("ascii") for value in values)
    ).digest()


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
    return value.lower().replace(" ", "_")[:64]


def _verdict(allowed, recovery, generation, tenant_version, reason):
    return OutboxAuthorityVerdict(
        allowed=allowed,
        current_recovery_run_verified=recovery,
        current_source_generation=generation,
        current_tenant_access_version=tenant_version,
        reason_code=reason,
    )


__all__ = [
    "PROVIDER_BINDING_APPLY_EVENT_TYPE",
    "PROVIDER_BINDING_REMOVE_EVENT_TYPE",
    "PROVIDER_BINDING_REVISION_SOURCE_TYPE",
    "PROVIDER_CLAIM_RELEASE_SOURCE_TYPE",
    "SfWarehouseBindingApplyRequest",
    "SfWarehouseBindingApplyResult",
    "SfWarehouseBindingRemoveRequest",
    "SqlAlchemyTenantWarehouseBindingApplier",
    "TenantProviderBindingApplyHandler",
    "TenantProviderBindingRemoveHandler",
    "TenantProviderBindingOutboxAuthority",
    "TenantProviderUnbindingOutboxAuthority",
    "TenantWarehouseBindingApplier",
]
