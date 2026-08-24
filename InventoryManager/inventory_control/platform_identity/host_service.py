"""Audited host-only bootstrap and recovery operations for platform admins."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.models import (
    PlatformAdmin,
    PlatformAdminRecoveryCode,
    PlatformAdminSession,
    PlatformAdminSetupChallenge,
    PlatformAdminTotpCredential,
    PlatformAuditLog,
)

from .setup_service import IssuedSetupChallenge, PlatformAdminSetupService
from .tokens import issue_setup_token
from .username import PlatformUsernameError, canonicalize_platform_username


_SAFE_REFERENCE = re.compile(r"[A-Za-z0-9_.:@/-]{1,128}\Z", re.ASCII)


class PlatformHostOperationRejected(RuntimeError):
    code = "PLATFORM_HOST_OPERATION_REJECTED"

    def __init__(self) -> None:
        super().__init__("The platform host operation was rejected.")


@dataclass(frozen=True, slots=True)
class PlatformAdminDisableResult:
    platform_admin_id: str
    revoked_session_count: int


@dataclass(frozen=True, slots=True)
class _LockedAdminAuthorities:
    setup: tuple[PlatformAdminSetupChallenge, ...]
    totp: tuple[PlatformAdminTotpCredential, ...]
    recovery: tuple[PlatformAdminRecoveryCode, ...]
    sessions: tuple[PlatformAdminSession, ...]


class PlatformAdminHostService:
    """Mutate only platform identity rows in a caller-owned host transaction."""

    def __init__(
        self,
        *,
        setup_service: PlatformAdminSetupService | None = None,
    ) -> None:
        self._setup_service = setup_service or PlatformAdminSetupService()

    def create_pending_admin(
        self,
        session: Session,
        *,
        username: object,
        setup_ttl: timedelta,
        os_operator_reference: str,
        command_id: str,
        now: datetime | None = None,
    ) -> IssuedSetupChallenge:
        _validate_host_evidence(os_operator_reference, command_id)
        current_time = _as_utc(now or _utc_now())
        issued = self._setup_service.create_pending_admin(
            session,
            username=username,
            ttl=setup_ttl,
            now=current_time,
        )
        session.add(
            _audit_row(
                action="platform_admin.bootstrap",
                command_template="inventoryctl platform-admin create",
                target_admin_id=issued.platform_admin_id,
                reason_code="platform_admin.bootstrap.succeeded",
                os_operator_reference=os_operator_reference,
                command_id=command_id,
                now=current_time,
            )
        )
        session.flush()
        return issued

    def begin_credential_recovery(
        self,
        session: Session,
        *,
        username: object,
        setup_ttl: timedelta,
        os_operator_reference: str,
        command_id: str,
        now: datetime | None = None,
    ) -> IssuedSetupChallenge:
        _validate_host_evidence(os_operator_reference, command_id)
        _validate_ttl(setup_ttl)
        current_time = _as_utc(now or _utc_now())
        try:
            canonical = canonicalize_platform_username(username)
        except PlatformUsernameError:
            raise PlatformHostOperationRejected() from None
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.username_canonical == canonical)
            .with_for_update()
        )
        if admin is None or admin.status not in {
            "active",
            "setup_pending",
            "recovery_pending",
        }:
            raise PlatformHostOperationRejected()

        authorities = _lock_admin_authorities(session, admin.id)
        _revoke_admin_authorities(
            authorities,
            now=current_time,
            session_reason_code="credential_recovery",
        )

        admin.status = "recovery_pending"
        admin.password_hash_encoded = None
        admin.password_hash_algorithm = None
        admin.password_hash_version = None
        admin.auth_version += 1
        admin.setup_version += 1
        admin.totp_generation += 1
        admin.recovery_code_generation += 1
        admin.updated_at = current_time
        admin.row_version += 1

        token = issue_setup_token()
        challenge = PlatformAdminSetupChallenge(
            platform_admin_id=admin.id,
            setup_version=admin.setup_version,
            token_digest_sha256=token.digest_sha256,
            state="active",
            row_version=1,
            created_at=current_time,
            expires_at=current_time + setup_ttl,
        )
        session.add(challenge)
        session.flush()
        session.add(
            _audit_row(
                action="platform_admin.credential_recovery",
                command_template="inventoryctl platform-admin reset",
                target_admin_id=admin.id,
                reason_code="platform_admin.credential_recovery.succeeded",
                os_operator_reference=os_operator_reference,
                command_id=command_id,
                now=current_time,
            )
        )
        session.flush()
        return IssuedSetupChallenge(
            platform_admin_id=admin.id,
            challenge_id=challenge.id,
            plaintext_token=token.plaintext,
            expires_at=challenge.expires_at,
        )

    def disable_admin(
        self,
        session: Session,
        *,
        username: object,
        os_operator_reference: str,
        command_id: str,
        now: datetime | None = None,
    ) -> PlatformAdminDisableResult:
        """Disable one active admin only after a fully active successor exists."""

        _validate_host_evidence(os_operator_reference, command_id)
        current_time = _as_utc(now or _utc_now())
        try:
            canonical = canonicalize_platform_username(username)
        except PlatformUsernameError:
            raise PlatformHostOperationRejected() from None
        admins = list(
            session.scalars(
                sa.select(PlatformAdmin)
                .order_by(PlatformAdmin.id)
                .with_for_update()
            )
        )
        target = next(
            (
                row
                for row in admins
                if row.username_canonical == canonical
                and row.status == "active"
            ),
            None,
        )
        if target is None or not any(
            row.id != target.id
            and row.status == "active"
            and _has_current_factors(session, row)
            for row in admins
        ):
            raise PlatformHostOperationRejected()

        authorities = _lock_admin_authorities(session, target.id)
        revoked_sessions = _revoke_admin_authorities(
            authorities,
            now=current_time,
            session_reason_code="platform_admin_disabled",
        )
        target.status = "disabled"
        target.disabled_at = current_time
        target.auth_version += 1
        target.updated_at = current_time
        target.row_version += 1
        session.add(
            _audit_row(
                action="platform_admin.disable",
                command_template="inventoryctl platform-admin disable",
                target_admin_id=target.id,
                reason_code="platform_admin.disable.succeeded",
                os_operator_reference=os_operator_reference,
                command_id=command_id,
                now=current_time,
            )
        )
        session.flush()
        return PlatformAdminDisableResult(
            platform_admin_id=target.id,
            revoked_session_count=revoked_sessions,
        )


def _lock_admin_authorities(
    session: Session,
    platform_admin_id: str,
) -> _LockedAdminAuthorities:
    def rows(model):
        return tuple(
            session.scalars(
                sa.select(model)
                .where(model.platform_admin_id == platform_admin_id)
                .order_by(model.id)
                .with_for_update()
            )
        )

    return _LockedAdminAuthorities(
        setup=rows(PlatformAdminSetupChallenge),
        totp=rows(PlatformAdminTotpCredential),
        recovery=rows(PlatformAdminRecoveryCode),
        sessions=rows(PlatformAdminSession),
    )


def _revoke_admin_authorities(
    authorities: _LockedAdminAuthorities,
    *,
    now: datetime,
    session_reason_code: str,
) -> int:
    for row in authorities.setup:
        if row.state == "active":
            row.state = "revoked"
            row.revoked_at = now
            row.row_version += 1
    for row in authorities.totp:
        if row.status in {"pending", "confirmed"}:
            row.status = "revoked"
            row.retired_at = now
            row.row_version += 1
    for row in authorities.recovery:
        if row.state == "active":
            row.state = "revoked"
            row.revoked_at = now
            row.row_version += 1
    revoked_sessions = 0
    for row in authorities.sessions:
        if row.revoked_at is None:
            row.revoked_at = now
            row.revoked_reason_code = session_reason_code
            revoked_sessions += 1
    return revoked_sessions


def _has_current_factors(session: Session, admin: PlatformAdmin) -> bool:
    if admin.password_hash_encoded is None:
        return False
    confirmed_totp = session.scalar(
        sa.select(sa.func.count(PlatformAdminTotpCredential.id)).where(
            PlatformAdminTotpCredential.platform_admin_id == admin.id,
            PlatformAdminTotpCredential.generation == admin.totp_generation,
            PlatformAdminTotpCredential.status == "confirmed",
        )
    )
    active_recovery = session.scalar(
        sa.select(sa.func.count(PlatformAdminRecoveryCode.id)).where(
            PlatformAdminRecoveryCode.platform_admin_id == admin.id,
            PlatformAdminRecoveryCode.generation
            == admin.recovery_code_generation,
            PlatformAdminRecoveryCode.state == "active",
        )
    )
    return confirmed_totp == 1 and bool(active_recovery)


def _audit_row(
    *,
    action: str,
    command_template: str,
    target_admin_id: str,
    reason_code: str,
    os_operator_reference: str,
    command_id: str,
    now: datetime,
) -> PlatformAuditLog:
    return PlatformAuditLog(
        actor_type="cli_break_glass",
        os_operator_reference=os_operator_reference,
        target_platform_admin_id=target_admin_id,
        route_or_command_template=command_template,
        action=action,
        access_mode="control",
        pii_revealed=False,
        outcome="succeeded",
        safe_reason_code=reason_code,
        request_id=command_id,
        correlation_id=command_id,
        created_at=now,
    )


def _validate_host_evidence(
    os_operator_reference: str,
    command_id: str,
) -> None:
    if (
        not isinstance(os_operator_reference, str)
        or _SAFE_REFERENCE.fullmatch(os_operator_reference) is None
        or not isinstance(command_id, str)
        or _SAFE_REFERENCE.fullmatch(command_id) is None
    ):
        raise ValueError("platform host evidence is invalid")


def _validate_ttl(value: timedelta) -> None:
    if (
        not isinstance(value, timedelta)
        or value <= timedelta(0)
        or value > timedelta(hours=1)
    ):
        raise ValueError("platform setup challenge TTL is invalid")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "PlatformAdminDisableResult",
    "PlatformAdminHostService",
    "PlatformHostOperationRejected",
]
