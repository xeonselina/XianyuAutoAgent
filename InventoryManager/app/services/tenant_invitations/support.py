"""Shared validation, projection, crypto, and gate helpers for invitations."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import NAMESPACE_URL, UUID, uuid5

import sqlalchemy as sa

from inventory_control.crypto import RootKey, SqlAlchemyRootKeyRegistry
from inventory_control.database import read_database_utc_value
from inventory_control.domain import EffectiveTenantGate
from inventory_control.invitations import (
    InvitationConflictError,
    InvitationCredentialError,
    InvitationIdentityError,
    InvitationJoinGateFacts,
    InvitationRole,
    InvitationSeatLimitError,
    InvitationStaleRevisionError,
    InvitationTenantGateError,
    accept_invitation_challenge_context,
)
from inventory_control.models import SmsChallenge, TenantInvitation, User
from inventory_control.recovery import RecoveryAuthorityService
from inventory_control.sms import CanonicalSmsPhone, SmsChallengeContext
from inventory_control.tenant_http import TenantHttpError

from .contracts import (
    TenantInvitationConflictRejected,
    TenantInvitationCredentialRejected,
    TenantInvitationInputRejected,
    TenantInvitationRuntimeUnavailable,
    TenantInvitationSeatLimitRejected,
)
from .query_service import InvitationCredentialView


class InvitationJoinGate:
    __slots__ = ("_recovery",)

    def __init__(self) -> None:
        self._recovery = RecoveryAuthorityService()

    def __call__(self, session, *, tenant, database_now):
        del database_now
        decision = self._recovery.read_tenant_gate(
            session,
            tenant=tenant,
            presented_access_version=tenant.access_version,
        )
        return InvitationJoinGateFacts(
            tenant_uuid=UUID(tenant.id),
            access_version=tenant.access_version,
            join_allowed=decision.gate is EffectiveTenantGate.ACTIVE,
        )


def challenge_root_key(session, *, challenge_id, root_key_directory) -> RootKey:
    challenge_uuid = parse_uuid(challenge_id)
    version = session.scalar(
        sa.select(SmsChallenge.root_key_version).where(
            SmsChallenge.id == str(challenge_uuid)
        )
    )
    if version is None:
        raise InvitationCredentialError()
    return SqlAlchemyRootKeyRegistry(session=session).load(
        root_key_directory
    ).key_for_existing_reference(version)


def acceptance_context(
    credential: InvitationCredentialView,
) -> SmsChallengeContext:
    return accept_invitation_challenge_context(
        phone=CanonicalSmsPhone.from_input(credential.canonical_phone),
        user_uuid=credential.user_uuid,
        tenant_uuid=credential.tenant_uuid,
        invitation_uuid=credential.invitation_uuid,
        token_generation=credential.token_generation,
        invitation_row_version=credential.invitation_row_version,
    )


def translate_persistence(
    exc: Exception,
    *,
    public_credential: bool = False,
):
    if isinstance(exc, TenantHttpError):
        return exc
    if isinstance(exc, InvitationSeatLimitError):
        return TenantInvitationSeatLimitRejected()
    if isinstance(exc, (InvitationConflictError, InvitationStaleRevisionError)):
        return TenantInvitationConflictRejected()
    if isinstance(
        exc,
        (InvitationCredentialError, InvitationIdentityError, InvitationTenantGateError),
    ):
        return (
            TenantInvitationCredentialRejected()
            if public_credential
            else TenantInvitationConflictRejected()
        )
    if isinstance(exc, (ValueError, TypeError)):
        return TenantInvitationInputRejected()
    return TenantInvitationRuntimeUnavailable()


def public_credential(value: InvitationCredentialView) -> dict[str, object]:
    return {
        "invitation_id": str(value.invitation_uuid),
        "tenant_name": value.tenant_name,
        "role": value.role,
        "masked_phone": value.masked_phone,
        "expires_at": iso(value.expires_at),
    }


def challenge_receipt(value) -> dict[str, object]:
    return {
        "challenge_id": value.challenge_id,
        "expires_in_seconds": value.expires_in_seconds,
        "resend_after_seconds": value.resend_after_seconds,
    }


def invitation_path(result) -> str:
    return (
        "/invite#invitation="
        f"{result.invitation_uuid}&generation={result.token_generation}"
        f"&token={result.token.value}"
    )


def membership_uuid(invitation_id: UUID, challenge_id: UUID) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"inventory:invitation-membership:{invitation_id}:{challenge_id}",
    )


def requires_admin_challenge(
    session,
    *,
    tenant_id: str,
    target_phone: CanonicalSmsPhone,
    selected_role: InvitationRole,
    expected_revision: int | None,
    database_now: datetime,
) -> bool:
    if selected_role is not InvitationRole.ADMIN:
        return False
    if expected_revision is None:
        return True
    pending = session.scalar(
        sa.select(TenantInvitation).where(
            TenantInvitation.tenant_id == tenant_id,
            TenantInvitation.phone_e164 == target_phone.e164,
            TenantInvitation.status == "pending",
        )
    )
    return not bool(
        pending is not None
        and pending.role_key == InvitationRole.ADMIN.value
        and pending.row_version == expected_revision
        and as_utc(pending.expires_at) > database_now
    )


def user_phone(session, user_id: str) -> CanonicalSmsPhone:
    row = session.get(User, user_id)
    if row is None:
        raise InvitationIdentityError()
    return CanonicalSmsPhone(
        e164=row.phone_e164,
        normalization_version=row.phone_normalization_version,
        metadata_version=row.phone_metadata_version,
    )


def parse_phone(value: object) -> CanonicalSmsPhone:
    if not isinstance(value, str):
        raise TenantInvitationInputRejected()
    try:
        return CanonicalSmsPhone.from_input(value)
    except (TypeError, ValueError):
        raise TenantInvitationInputRejected() from None


def parse_role(value: object) -> InvitationRole:
    try:
        return InvitationRole(value)
    except (TypeError, ValueError):
        raise TenantInvitationInputRejected() from None


def parse_uuid(value: object) -> UUID:
    try:
        parsed = UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise TenantInvitationInputRejected() from None
    if str(parsed) != str(value).lower():
        raise TenantInvitationInputRejected()
    return parsed


def positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise TenantInvitationInputRejected()
    return value


def optional_positive(value: object) -> int | None:
    if value is None:
        return None
    return positive(value)


def database_now(session) -> datetime:
    value = read_database_utc_value(session)
    if not isinstance(value, datetime):
        raise TenantInvitationRuntimeUnavailable()
    return as_utc(value)


def as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TenantInvitationRuntimeUnavailable()
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def iso(value: datetime) -> str:
    return as_utc(value).isoformat().replace("+00:00", "Z")


__all__ = [
    "InvitationJoinGate",
    "acceptance_context",
    "challenge_receipt",
    "challenge_root_key",
    "database_now",
    "invitation_path",
    "iso",
    "membership_uuid",
    "optional_positive",
    "parse_phone",
    "parse_role",
    "parse_uuid",
    "positive",
    "public_credential",
    "requires_admin_challenge",
    "translate_persistence",
    "user_phone",
]
