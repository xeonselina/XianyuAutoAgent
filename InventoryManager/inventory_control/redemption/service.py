"""Caller-transaction redemption-code generation and non-secret lookup."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.crypto import EncryptedEnvelope, RootKey
from inventory_control.models.platform_identity import PlatformAdmin
from inventory_control.models.redemption import RedemptionCode, RedemptionCodeBatch
from inventory_control.models.subscriptions import PlanRevision
from inventory_control.subscriptions import parse_core_entitlements

from .codes import CanonicalRedemptionCode, generate_redemption_code
from .envelope import RedemptionCodeSecretContext, encrypt_redemption_code


_CHANNEL = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")


class RedemptionBatchError(RuntimeError):
    pass


class RedemptionBatchConflictError(RedemptionBatchError):
    pass


class RedemptionGenerationDenied(RedemptionBatchError):
    pass


@dataclass(frozen=True, slots=True)
class IssuedRedemptionCode:
    code_uuid: UUID
    plaintext: CanonicalRedemptionCode = field(repr=False)


@dataclass(frozen=True, slots=True)
class GeneratedRedemptionBatch:
    batch_uuid: UUID
    created: bool
    issued_codes: tuple[IssuedRedemptionCode, ...] = field(repr=False)


@dataclass(frozen=True, slots=True)
class RedemptionCodePreview:
    eligible: bool
    code_uuid: UUID | None = None
    plan_revision_uuid: UUID | None = None
    service_duration_seconds: int | None = None
    redeem_before: datetime | None = None
    reason_code: str | None = None


class RedemptionCodeService:
    """Create encrypted code records without committing the caller's session."""

    def generate_batch(
        self,
        session: Session,
        *,
        root_key: RootKey,
        current_recovery_run_uuid: UUID,
        recovery_run_completed: bool,
        platform_admin_uuid: UUID,
        generation_request_uuid: UUID,
        plan_revision_uuid: UUID,
        name: str,
        quantity: int,
        service_duration: timedelta,
        redeem_before: datetime,
        database_now: datetime,
        channel: str | None = None,
        internal_note: str | None = None,
    ) -> GeneratedRedemptionBatch:
        now = _aware_utc("database_now", database_now)
        deadline = _aware_utc("redeem_before", redeem_before)
        run_uuid = _uuid("current_recovery_run_uuid", current_recovery_run_uuid)
        admin_uuid = _uuid("platform_admin_uuid", platform_admin_uuid)
        request_uuid = _uuid("generation_request_uuid", generation_request_uuid)
        plan_uuid = _uuid("plan_revision_uuid", plan_revision_uuid)
        if not recovery_run_completed:
            raise RedemptionGenerationDenied("RECOVERY_NOT_COMPLETED")
        if not isinstance(root_key, RootKey):
            raise TypeError("root_key must be a RootKey")
        normalized_name = _batch_name(name)
        normalized_channel = _optional_channel(channel)
        normalized_note = _optional_note(internal_note)
        count = _positive_integer("quantity", quantity)
        duration_seconds = _duration_seconds(service_duration)
        if deadline <= now:
            raise ValueError("redeem_before must be later than database_now")

        request_digest = _generation_digest(
            recovery_run_uuid=run_uuid,
            platform_admin_uuid=admin_uuid,
            plan_revision_uuid=plan_uuid,
            name=normalized_name,
            channel=normalized_channel,
            internal_note=normalized_note,
            quantity=count,
            service_duration_seconds=duration_seconds,
            redeem_before=deadline,
        )
        existing = session.scalar(
            sa.select(RedemptionCodeBatch)
            .where(
                RedemptionCodeBatch.generation_request_uuid == str(request_uuid)
            )
            .with_for_update()
        )
        if existing is not None:
            if existing.request_digest != request_digest:
                raise RedemptionBatchConflictError(
                    "generation request parameters changed"
                )
            # The original plaintext export is intentionally not reconstructed
            # as a historical batch export.
            return GeneratedRedemptionBatch(UUID(existing.id), False, ())

        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == str(admin_uuid))
            .with_for_update()
        )
        if admin is None or admin.status != "active":
            raise RedemptionGenerationDenied("PLATFORM_ADMIN_NOT_ACTIVE")
        plan = session.scalar(
            sa.select(PlanRevision)
            .where(PlanRevision.id == str(plan_uuid))
            .with_for_update()
        )
        if plan is None or not plan.active:
            raise RedemptionGenerationDenied("PLAN_NOT_ACTIVE")
        snapshot = parse_core_entitlements(
            schema_version=plan.entitlements_schema_version,
            entitlements=plan.entitlements_json,
        )
        if snapshot.digest_sha256 != plan.entitlements_digest:
            raise RedemptionGenerationDenied("PLAN_SNAPSHOT_INVALID")

        batch_uuid = uuid4()
        batch = RedemptionCodeBatch(
            id=str(batch_uuid),
            generation_request_uuid=str(request_uuid),
            request_digest=request_digest,
            name=normalized_name,
            channel=normalized_channel,
            internal_note=normalized_note,
            quantity=count,
            plan_revision_uuid=plan.id,
            entitlements_schema_version=plan.entitlements_schema_version,
            entitlements_json=plan.entitlements_json,
            entitlements_digest=plan.entitlements_digest,
            service_duration_seconds=duration_seconds,
            default_redeem_before=deadline,
            created_by_platform_admin_id=admin.id,
            created_at=now,
            plaintext_exported_at=now,
        )
        session.add(batch)

        issued: list[IssuedRedemptionCode] = []
        observed_hashes: set[bytes] = set()
        for _ in range(count):
            canonical = generate_redemption_code()
            # A collision is astronomically unlikely, but fail safely inside
            # this transaction rather than producing ambiguous lookup rows.
            if canonical.lookup_hash in observed_hashes:
                raise RedemptionBatchError("redemption code collision")
            observed_hashes.add(canonical.lookup_hash)
            code_uuid = uuid4()
            crypto_context_uuid = uuid4()
            context = RedemptionCodeSecretContext(
                code_uuid=code_uuid,
                crypto_context_uuid=crypto_context_uuid,
                batch_uuid=batch_uuid,
                plan_revision_uuid=plan_uuid,
                entitlements_schema_version=plan.entitlements_schema_version,
                entitlements_digest_sha256=plan.entitlements_digest,
                service_duration_seconds=duration_seconds,
                redeem_before=deadline,
                created_under_recovery_run_uuid=run_uuid,
                secret_revision=1,
            )
            envelope = encrypt_redemption_code(
                root_key=root_key,
                context=context,
                code=canonical,
            )
            session.add(
                _new_code_record(
                    code_uuid=code_uuid,
                    crypto_context_uuid=crypto_context_uuid,
                    batch_uuid=batch_uuid,
                    code=canonical,
                    envelope=envelope,
                    plan=plan,
                    service_duration_seconds=duration_seconds,
                    redeem_before=deadline,
                    recovery_run_uuid=run_uuid,
                    now=now,
                )
            )
            issued.append(IssuedRedemptionCode(code_uuid, canonical))
        session.flush()
        return GeneratedRedemptionBatch(batch_uuid, True, tuple(issued))

    def preview_for_update(
        self,
        session: Session,
        *,
        lookup_hash: bytes,
        current_recovery_run_uuid: UUID,
        recovery_run_completed: bool,
        database_now: datetime,
    ) -> RedemptionCodePreview:
        now = _aware_utc("database_now", database_now)
        run_uuid = _uuid("current_recovery_run_uuid", current_recovery_run_uuid)
        if not isinstance(lookup_hash, bytes) or len(lookup_hash) != 32:
            return RedemptionCodePreview(False, reason_code="CODE_NOT_REDEEMABLE")
        code = session.scalar(
            sa.select(RedemptionCode)
            .where(RedemptionCode.lookup_hash == lookup_hash)
            .with_for_update()
        )
        if code is None:
            return RedemptionCodePreview(False, reason_code="CODE_NOT_REDEEMABLE")
        if code.status == "active" and _as_utc(code.redeem_before) <= now:
            code.status = "expired"
            code.expired_at = now
            code.row_version += 1
            code.updated_at = now
            session.flush()
        if (
            not recovery_run_completed
            or code.created_under_recovery_run_uuid != str(run_uuid)
            or code.status != "active"
        ):
            return RedemptionCodePreview(False, reason_code="CODE_NOT_REDEEMABLE")
        return RedemptionCodePreview(
            True,
            code_uuid=UUID(code.id),
            plan_revision_uuid=UUID(code.plan_revision_uuid),
            service_duration_seconds=code.service_duration_seconds,
            redeem_before=_as_utc(code.redeem_before),
        )


def _new_code_record(
    *,
    code_uuid: UUID,
    crypto_context_uuid: UUID,
    batch_uuid: UUID,
    code: CanonicalRedemptionCode,
    envelope: EncryptedEnvelope,
    plan: PlanRevision,
    service_duration_seconds: int,
    redeem_before: datetime,
    recovery_run_uuid: UUID,
    now: datetime,
) -> RedemptionCode:
    return RedemptionCode(
        id=str(code_uuid),
        crypto_context_uuid=str(crypto_context_uuid),
        batch_id=str(batch_uuid),
        code_prefix=code.prefix,
        lookup_hash=code.lookup_hash,
        code_ciphertext=envelope.ciphertext,
        code_nonce=envelope.nonce,
        secret_revision=1,
        root_key_version=envelope.root_key_version,
        crypto_version=envelope.crypto_version,
        aad_version=envelope.aad_version,
        status="active",
        plan_revision_uuid=plan.id,
        entitlements_schema_version=plan.entitlements_schema_version,
        entitlements_json=plan.entitlements_json,
        entitlements_digest=plan.entitlements_digest,
        service_duration_seconds=service_duration_seconds,
        redeem_before=redeem_before,
        created_under_recovery_run_uuid=str(recovery_run_uuid),
        created_at=now,
        updated_at=now,
    )


def _generation_digest(**values: object) -> bytes:
    encoded = {
        key: (
            value.isoformat()
            if isinstance(value, datetime)
            else str(value)
            if isinstance(value, UUID)
            else value
        )
        for key, value in values.items()
    }
    canonical = json.dumps(
        encoded,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")
    return hashlib.sha256(canonical).digest()


def _batch_name(value: object) -> str:
    if not isinstance(value, str):
        raise TypeError("name must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 160:
        raise ValueError("name is invalid")
    return normalized


def _optional_channel(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("channel must be a string")
    normalized = value.strip().lower()
    if _CHANNEL.fullmatch(normalized) is None:
        raise ValueError("channel is invalid")
    return normalized


def _optional_note(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise TypeError("internal_note must be a string")
    normalized = value.strip()
    if not normalized or len(normalized) > 500:
        raise ValueError("internal_note is invalid")
    return normalized


def _positive_integer(name: str, value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def _duration_seconds(value: object) -> int:
    if not isinstance(value, timedelta) or value <= timedelta(0):
        raise ValueError("service_duration must be a positive timedelta")
    seconds = value.total_seconds()
    if not seconds.is_integer() or seconds > 9_223_372_036_854_775_807:
        raise ValueError("service_duration must contain exact whole seconds")
    return int(seconds)


def _uuid(name: str, value: object) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError(f"{name} must be a UUID")
    return value


def _aware_utc(name: str, value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
