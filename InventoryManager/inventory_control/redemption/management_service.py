"""Bounded platform list, reveal, and revocation operations for redemption codes."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session, aliased

from inventory_control.crypto import EncryptedEnvelope, RootKeyRing
from inventory_control.models import (
    RedemptionCode,
    RedemptionCodeBatch,
    RedemptionCodeReplacement,
    RegistrationIntegrityIncident,
    TenantRegistrationAttempt,
)

from .codes import CanonicalRedemptionCode
from .envelope import RedemptionCodeSecretContext, decrypt_redemption_code


REDEMPTION_CODE_STATUSES = frozenset(
    {"active", "reserved", "redeemed", "revoked", "expired", "recovery_revoked"}
)
_REASON_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,63}\Z")


class RedemptionCodeManagementError(RuntimeError):
    """Base class for a stable management-boundary rejection."""


class RedemptionCodeNotFound(RedemptionCodeManagementError):
    pass


class RedemptionCodeRevisionConflict(RedemptionCodeManagementError):
    pass


@dataclass(frozen=True, slots=True)
class RedemptionCodeListItem:
    code_uuid: UUID
    batch_uuid: UUID
    batch_name: str
    channel: str | None
    internal_note: str | None
    masked_code: str
    status: str
    row_version: int
    plan_revision_uuid: UUID
    service_duration_seconds: int
    redeem_before: datetime
    created_at: datetime
    reserved_attempt_uuid: UUID | None
    reserved_attempt_status: str | None
    redeemed_tenant_uuid: UUID | None
    redeemed_user_uuid: UUID | None
    redeemed_at: datetime | None
    revocation_reason_code: str | None
    replacement_status: str | None
    replacement_code_uuid: UUID | None


@dataclass(frozen=True, slots=True)
class RedemptionCodePage:
    items: tuple[RedemptionCodeListItem, ...]
    page: int
    page_size: int
    total: int


@dataclass(frozen=True, slots=True)
class RevealedRedemptionCode:
    code_uuid: UUID
    status: str
    row_version: int
    plaintext: CanonicalRedemptionCode = field(repr=False)


@dataclass(frozen=True, slots=True)
class RedemptionCodeRevocation:
    code_uuid: UUID
    status: str
    row_version: int
    changed: bool
    denial_reason: str | None


class RedemptionCodeManagementService:
    """Operate on code records without owning or committing the transaction."""

    def list_codes(
        self,
        session: Session,
        *,
        database_now: datetime,
        page: int,
        page_size: int,
        status: str | None = None,
    ) -> RedemptionCodePage:
        now = _aware_utc(database_now)
        selected_page = _bounded_integer("page", page, minimum=1, maximum=1_000_000)
        selected_size = _bounded_integer(
            "page_size", page_size, minimum=1, maximum=100
        )
        selected_status = _status_filter(status)
        predicate = _effective_status_predicate(
            status=selected_status,
            database_now=now,
        )
        reserved_attempt = aliased(TenantRegistrationAttempt)
        redeemed_attempt = aliased(TenantRegistrationAttempt)
        replacement = aliased(RedemptionCodeReplacement)
        incident = aliased(RegistrationIntegrityIncident)
        total = int(
            session.scalar(
                sa.select(sa.func.count(RedemptionCode.id)).where(predicate)
            )
            or 0
        )
        rows = session.execute(
            sa.select(
                RedemptionCode.id,
                RedemptionCode.batch_id,
                RedemptionCodeBatch.name.label("batch_name"),
                RedemptionCodeBatch.channel,
                RedemptionCodeBatch.internal_note,
                RedemptionCode.code_prefix,
                RedemptionCode.status,
                RedemptionCode.row_version,
                RedemptionCode.plan_revision_uuid,
                RedemptionCode.service_duration_seconds,
                RedemptionCode.redeem_before,
                RedemptionCode.created_at,
                RedemptionCode.reserved_registration_attempt_uuid,
                reserved_attempt.status.label("reserved_attempt_status"),
                RedemptionCode.redeemed_tenant_uuid,
                redeemed_attempt.user_id.label("redeemed_user_uuid"),
                RedemptionCode.redeemed_at,
                RedemptionCode.revocation_reason_code,
                replacement.replacement_code_uuid,
                incident.state.label("replacement_incident_state"),
            )
            .join(
                RedemptionCodeBatch,
                RedemptionCodeBatch.id == RedemptionCode.batch_id,
            )
            .outerjoin(
                reserved_attempt,
                reserved_attempt.id
                == RedemptionCode.reserved_registration_attempt_uuid,
            )
            .outerjoin(
                redeemed_attempt,
                redeemed_attempt.id
                == RedemptionCode.redeemed_registration_attempt_uuid,
            )
            .outerjoin(
                replacement,
                replacement.source_code_uuid == RedemptionCode.id,
            )
            .outerjoin(
                incident,
                sa.and_(
                    incident.attempt_uuid
                    == RedemptionCode.reserved_registration_attempt_uuid,
                    incident.state.in_(("open", "recovery_cleanup_pending")),
                ),
            )
            .where(predicate)
            .order_by(RedemptionCode.created_at.desc(), RedemptionCode.id.desc())
            .offset((selected_page - 1) * selected_size)
            .limit(selected_size)
        ).all()
        return RedemptionCodePage(
            items=tuple(_list_item(row, database_now=now) for row in rows),
            page=selected_page,
            page_size=selected_size,
            total=total,
        )

    def reveal_code(
        self,
        session: Session,
        *,
        code_uuid: UUID,
        root_key_ring: RootKeyRing,
    ) -> RevealedRedemptionCode:
        selected_uuid = _uuid(code_uuid)
        if not isinstance(root_key_ring, RootKeyRing):
            raise TypeError("root_key_ring must be a RootKeyRing")
        code = session.scalar(
            sa.select(RedemptionCode)
            .where(RedemptionCode.id == str(selected_uuid))
            .with_for_update()
        )
        if code is None:
            raise RedemptionCodeNotFound("redemption code is unavailable")
        plaintext = decrypt_redemption_code(
            root_key=root_key_ring.key_for_existing_reference(
                code.root_key_version
            ),
            context=_secret_context(code),
            envelope=EncryptedEnvelope(
                nonce=code.code_nonce,
                ciphertext=code.code_ciphertext,
                root_key_version=code.root_key_version,
                crypto_version=code.crypto_version,
                aad_version=code.aad_version,
            ),
        )
        return RevealedRedemptionCode(
            code_uuid=selected_uuid,
            status=code.status,
            row_version=code.row_version,
            plaintext=plaintext,
        )

    def revoke_code(
        self,
        session: Session,
        *,
        code_uuid: UUID,
        expected_row_version: int,
        reason_code: str,
        database_now: datetime,
    ) -> RedemptionCodeRevocation:
        selected_uuid = _uuid(code_uuid)
        expected_revision = _bounded_integer(
            "expected_row_version",
            expected_row_version,
            minimum=1,
            maximum=9_223_372_036_854_775_807,
        )
        selected_reason = _reason_code(reason_code)
        now = _aware_utc(database_now)
        code = session.scalar(
            sa.select(RedemptionCode)
            .where(RedemptionCode.id == str(selected_uuid))
            .with_for_update()
        )
        if code is None:
            raise RedemptionCodeNotFound("redemption code is unavailable")
        if (
            code.status == "revoked"
            and code.revocation_reason_code == selected_reason
        ):
            return _revocation(code, changed=False, denial_reason=None)
        if code.row_version != expected_revision:
            raise RedemptionCodeRevisionConflict(
                "redemption code revision changed"
            )
        if code.status == "active" and _as_utc(code.redeem_before) <= now:
            code.status = "expired"
            code.expired_at = now
            code.row_version += 1
            code.updated_at = now
            session.flush()
            return _revocation(
                code,
                changed=False,
                denial_reason="redemption_code.expired",
            )
        if code.status != "active":
            return _revocation(
                code,
                changed=False,
                denial_reason="redemption_code.not_revocable",
            )
        code.status = "revoked"
        code.revoked_at = now
        code.revocation_reason_code = selected_reason
        code.row_version += 1
        code.updated_at = now
        session.flush()
        return _revocation(code, changed=True, denial_reason=None)


def _effective_status_predicate(*, status: str | None, database_now: datetime):
    if status is None:
        return sa.true()
    if status == "active":
        return sa.and_(
            RedemptionCode.status == "active",
            RedemptionCode.redeem_before > database_now,
        )
    if status == "expired":
        return sa.or_(
            RedemptionCode.status == "expired",
            sa.and_(
                RedemptionCode.status == "active",
                RedemptionCode.redeem_before <= database_now,
            ),
        )
    return RedemptionCode.status == status


def _list_item(row, *, database_now: datetime) -> RedemptionCodeListItem:
    effective_status = (
        "expired"
        if row.status == "active" and _as_utc(row.redeem_before) <= database_now
        else row.status
    )
    return RedemptionCodeListItem(
        code_uuid=UUID(row.id),
        batch_uuid=UUID(row.batch_id),
        batch_name=row.batch_name,
        channel=row.channel,
        internal_note=row.internal_note,
        masked_code=f"{row.code_prefix}-****-****-****-****-****-**",
        status=effective_status,
        row_version=row.row_version,
        plan_revision_uuid=UUID(row.plan_revision_uuid),
        service_duration_seconds=row.service_duration_seconds,
        redeem_before=_as_utc(row.redeem_before),
        created_at=_as_utc(row.created_at),
        reserved_attempt_uuid=_optional_uuid(
            row.reserved_registration_attempt_uuid
        ),
        reserved_attempt_status=row.reserved_attempt_status,
        redeemed_tenant_uuid=_optional_uuid(row.redeemed_tenant_uuid),
        redeemed_user_uuid=_optional_uuid(row.redeemed_user_uuid),
        redeemed_at=(
            _as_utc(row.redeemed_at) if row.redeemed_at is not None else None
        ),
        revocation_reason_code=row.revocation_reason_code,
        replacement_status=(
            "issued"
            if row.replacement_code_uuid is not None
            else (
                "integrity_blocked"
                if row.replacement_incident_state is not None
                else None
            )
        ),
        replacement_code_uuid=_optional_uuid(row.replacement_code_uuid),
    )


def _secret_context(code: RedemptionCode) -> RedemptionCodeSecretContext:
    return RedemptionCodeSecretContext(
        code_uuid=UUID(code.id),
        crypto_context_uuid=UUID(code.crypto_context_uuid),
        batch_uuid=UUID(code.batch_id),
        plan_revision_uuid=UUID(code.plan_revision_uuid),
        entitlements_schema_version=code.entitlements_schema_version,
        entitlements_digest_sha256=code.entitlements_digest,
        service_duration_seconds=code.service_duration_seconds,
        redeem_before=_as_utc(code.redeem_before),
        created_under_recovery_run_uuid=UUID(
            code.created_under_recovery_run_uuid
        ),
        secret_revision=code.secret_revision,
    )


def _revocation(
    code: RedemptionCode,
    *,
    changed: bool,
    denial_reason: str | None,
) -> RedemptionCodeRevocation:
    return RedemptionCodeRevocation(
        code_uuid=UUID(code.id),
        status=code.status,
        row_version=code.row_version,
        changed=changed,
        denial_reason=denial_reason,
    )


def _status_filter(value: object) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or value not in REDEMPTION_CODE_STATUSES:
        raise ValueError("redemption code status is invalid")
    return value


def _reason_code(value: object) -> str:
    if not isinstance(value, str) or _REASON_CODE.fullmatch(value) is None:
        raise ValueError("revocation reason code is invalid")
    return value


def _bounded_integer(
    name: str,
    value: object,
    *,
    minimum: int,
    maximum: int,
) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > maximum
    ):
        raise ValueError(f"{name} is invalid")
    return value


def _uuid(value: object) -> UUID:
    if not isinstance(value, UUID):
        raise TypeError("code_uuid must be a UUID")
    return value


def _optional_uuid(value: str | None) -> UUID | None:
    return UUID(value) if value is not None else None


def _aware_utc(value: object) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError("database_now must be timezone-aware")
    return value.astimezone(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "REDEMPTION_CODE_STATUSES",
    "RedemptionCodeListItem",
    "RedemptionCodeManagementError",
    "RedemptionCodeManagementService",
    "RedemptionCodeNotFound",
    "RedemptionCodePage",
    "RedemptionCodeRevisionConflict",
    "RedemptionCodeRevocation",
    "RevealedRedemptionCode",
]
