"""Control-only projections for tenant member and invitation screens."""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.invitations import InvitationToken, InvitationTokenError
from inventory_control.models import Tenant, TenantInvitation, TenantMembership, User


class InvitationQueryRejected(RuntimeError):
    """Stable non-enumerating credential rejection."""


@dataclass(frozen=True, slots=True)
class InvitationCredentialView:
    invitation_uuid: UUID
    tenant_uuid: UUID
    user_uuid: UUID
    tenant_name: str
    canonical_phone: str
    role: str
    token_generation: int
    expires_at: datetime
    invitation_row_version: int
    tenant_access_version: int

    @property
    def masked_phone(self) -> str:
        return _mask_phone(self.canonical_phone)


class TenantInvitationQueryService:
    """Produce bounded DTOs without opening any tenant business database."""

    @staticmethod
    def list_for_tenant(
        session: Session,
        *,
        tenant_id: str,
        database_now: datetime,
    ) -> dict[str, object]:
        now = _as_utc(database_now)
        members = session.execute(
            sa.select(
                TenantMembership.id,
                TenantMembership.role_key,
                TenantMembership.status,
                TenantMembership.row_version,
                User.phone_e164,
            )
            .join(User, User.id == TenantMembership.user_id)
            .where(
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.status.in_(("active", "disabled")),
            )
            .order_by(TenantMembership.created_at, TenantMembership.id)
            .limit(100)
        ).all()
        invitations = session.execute(
            sa.select(
                TenantInvitation.id,
                TenantInvitation.role_key,
                TenantInvitation.status,
                TenantInvitation.phone_e164,
                TenantInvitation.token_generation,
                TenantInvitation.expires_at,
                TenantInvitation.row_version,
                TenantInvitation.created_at,
            )
            .where(TenantInvitation.tenant_id == tenant_id)
            .order_by(TenantInvitation.created_at.desc(), TenantInvitation.id)
            .limit(100)
        ).all()
        active_members = sum(row.status == "active" for row in members)
        pending_invitations = sum(
            row.status == "pending" and _as_utc(row.expires_at) > now
            for row in invitations
        )
        return {
            "seat_usage": {
                "active_members": active_members,
                "pending_invitations": pending_invitations,
                "used": active_members + pending_invitations,
                "limit": 10,
            },
            "members": [
                {
                    "membership_id": row.id,
                    "role": row.role_key,
                    "status": row.status,
                    "masked_phone": _mask_phone(row.phone_e164),
                    "row_version": row.row_version,
                }
                for row in members
            ],
            "invitations": [
                {
                    "invitation_id": row.id,
                    "role": row.role_key,
                    "status": _display_status(row, now=now),
                    "phone": row.phone_e164,
                    "masked_phone": _mask_phone(row.phone_e164),
                    "token_generation": row.token_generation,
                    "expires_at": _iso(row.expires_at),
                    "row_version": row.row_version,
                    "created_at": _iso(row.created_at),
                }
                for row in invitations
            ],
        }

    @staticmethod
    def resolve_credential(
        session: Session,
        *,
        invitation_id: object,
        submitted_token: object,
        submitted_generation: object,
        database_now: datetime,
    ) -> InvitationCredentialView:
        invitation_uuid = _uuid(invitation_id)
        generation = _positive(submitted_generation)
        try:
            token = InvitationToken(submitted_token)
        except InvitationTokenError:
            raise InvitationQueryRejected() from None
        row = session.execute(
            sa.select(TenantInvitation, Tenant, User)
            .join(Tenant, Tenant.id == TenantInvitation.tenant_id)
            .join(User, User.id == TenantInvitation.user_id)
            .where(TenantInvitation.id == str(invitation_uuid))
        ).one_or_none()
        now = _as_utc(database_now)
        if (
            row is None
            or row.TenantInvitation.status != "pending"
            or row.TenantInvitation.token_generation != generation
            or _as_utc(row.TenantInvitation.expires_at) <= now
            or not hmac.compare_digest(
                bytes(row.TenantInvitation.token_hash), token.digest_sha256
            )
            or row.User.status not in {"unverified", "active"}
        ):
            raise InvitationQueryRejected()
        return InvitationCredentialView(
            invitation_uuid=UUID(row.TenantInvitation.id),
            tenant_uuid=UUID(row.Tenant.id),
            user_uuid=UUID(row.User.id),
            tenant_name=(row.Tenant.name or "租户")[:80],
            canonical_phone=row.User.phone_e164,
            role=row.TenantInvitation.role_key,
            token_generation=row.TenantInvitation.token_generation,
            expires_at=_as_utc(row.TenantInvitation.expires_at),
            invitation_row_version=row.TenantInvitation.row_version,
            tenant_access_version=row.Tenant.access_version,
        )


def _display_status(row, *, now: datetime) -> str:
    if row.status == "pending" and _as_utc(row.expires_at) <= now:
        return "expired"
    return row.status


def _mask_phone(value: str) -> str:
    return f"{value[:5]}****{value[-4:]}"


def _uuid(value: object) -> UUID:
    try:
        parsed = UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise InvitationQueryRejected() from None
    if str(parsed) != str(value).lower():
        raise InvitationQueryRejected()
    return parsed


def _positive(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise InvitationQueryRejected()
    return value


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise InvitationQueryRejected()
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _iso(value: datetime) -> str:
    return _as_utc(value).isoformat().replace("+00:00", "Z")


__all__ = [
    "InvitationCredentialView",
    "InvitationQueryRejected",
    "TenantInvitationQueryService",
]
