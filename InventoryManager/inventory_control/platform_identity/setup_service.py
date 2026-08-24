"""Caller-transactional platform-admin setup challenge workflow."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.models.platform_identity import (
    PlatformAdmin,
    PlatformAdminSetupChallenge,
)

from .passwords import PlatformPasswordHasher
from .tokens import digest_setup_token, issue_setup_token, verify_setup_token
from .username import canonicalize_platform_username


@dataclass(frozen=True, slots=True, repr=False)
class IssuedSetupChallenge:
    platform_admin_id: str
    challenge_id: str
    plaintext_token: str
    expires_at: datetime

    def __repr__(self) -> str:
        return (
            f"IssuedSetupChallenge(platform_admin_id={self.platform_admin_id!r}, "
            f"challenge_id={self.challenge_id!r}, <redacted>)"
        )


@dataclass(frozen=True, slots=True)
class SetupChallengeResult:
    accepted: bool
    platform_admin_id: str | None
    reason_code: str


@dataclass(frozen=True, slots=True)
class ConsumedSetupAuthority:
    platform_admin_id: str
    setup_version: int
    expires_at: datetime


_REJECTED = SetupChallengeResult(
    accepted=False,
    platform_admin_id=None,
    reason_code="PLATFORM_SETUP_REJECTED",
)


class PlatformAdminSetupService:
    """Create and consume short-lived setup credentials without committing."""

    def create_pending_admin(
        self,
        session: Session,
        *,
        username: object,
        ttl: timedelta = timedelta(minutes=15),
        now: datetime | None = None,
    ) -> IssuedSetupChallenge:
        if ttl <= timedelta(0) or ttl > timedelta(hours=1):
            raise ValueError("platform setup challenge TTL is invalid")
        current_time = _as_utc(now or _utc_now())
        admin = PlatformAdmin(
            username_canonical=canonicalize_platform_username(username),
            status="setup_pending",
            auth_version=1,
            setup_version=1,
            totp_generation=1,
            recovery_code_generation=1,
            row_version=1,
            created_at=current_time,
            updated_at=current_time,
        )
        session.add(admin)
        session.flush()
        token = issue_setup_token()
        challenge = PlatformAdminSetupChallenge(
            platform_admin_id=admin.id,
            setup_version=admin.setup_version,
            token_digest_sha256=token.digest_sha256,
            state="active",
            row_version=1,
            created_at=current_time,
            expires_at=current_time + ttl,
        )
        session.add(challenge)
        session.flush()
        return IssuedSetupChallenge(
            platform_admin_id=admin.id,
            challenge_id=challenge.id,
            plaintext_token=token.plaintext,
            expires_at=challenge.expires_at,
        )

    def consume(
        self,
        session: Session,
        *,
        presented_token: object,
        now: datetime | None = None,
    ) -> SetupChallengeResult:
        current_time = _as_utc(now or _utc_now())
        try:
            token_digest = digest_setup_token(presented_token)
        except (TypeError, ValueError):
            token_digest = bytes(32)
        summary = session.execute(
            sa.select(
                PlatformAdminSetupChallenge.id,
                PlatformAdminSetupChallenge.platform_admin_id,
            ).where(
                PlatformAdminSetupChallenge.token_digest_sha256 == token_digest
            )
        ).one_or_none()
        if summary is None:
            return _REJECTED
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == summary.platform_admin_id)
            .with_for_update()
        )
        challenge = session.scalar(
            sa.select(PlatformAdminSetupChallenge)
            .where(PlatformAdminSetupChallenge.id == summary.id)
            .with_for_update()
        )
        if (
            admin is None
            or challenge is None
            or admin.status not in {"setup_pending", "recovery_pending"}
            or challenge.setup_version != admin.setup_version
            or challenge.state != "active"
            or current_time >= _as_utc(challenge.expires_at)
            or not verify_setup_token(
                presented_token, challenge.token_digest_sha256
            )
        ):
            return _REJECTED
        changed = session.execute(
            sa.update(PlatformAdminSetupChallenge)
            .where(
                PlatformAdminSetupChallenge.id == challenge.id,
                PlatformAdminSetupChallenge.row_version == challenge.row_version,
                PlatformAdminSetupChallenge.state == "active",
                PlatformAdminSetupChallenge.expires_at > current_time,
            )
            .values(
                state="consumed",
                consumed_at=current_time,
                row_version=challenge.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            return _REJECTED
        session.expire(challenge)
        return SetupChallengeResult(
            accepted=True,
            platform_admin_id=admin.id,
            reason_code="PLATFORM_SETUP_CONSUMED",
        )

    def set_password(
        self,
        session: Session,
        *,
        platform_admin_id: str,
        expected_setup_version: int,
        password: object,
        hasher: PlatformPasswordHasher,
        now: datetime | None = None,
    ) -> None:
        current_time = _as_utc(now or _utc_now())
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == platform_admin_id)
            .with_for_update()
        )
        if (
            admin is None
            or admin.status not in {"setup_pending", "recovery_pending"}
            or admin.setup_version != expected_setup_version
        ):
            raise RuntimeError("Platform setup state is unavailable.")
        consumed_setup_count = session.scalar(
            sa.select(sa.func.count(PlatformAdminSetupChallenge.id)).where(
                PlatformAdminSetupChallenge.platform_admin_id == admin.id,
                PlatformAdminSetupChallenge.setup_version == admin.setup_version,
                PlatformAdminSetupChallenge.state == "consumed",
            )
        )
        if consumed_setup_count != 1:
            raise RuntimeError("Platform setup state is unavailable.")
        password_hash = hasher.hash(password)
        if admin.status == "recovery_pending":
            # A reset account must never reactivate sessions issued before the
            # break-glass recovery flow began.
            admin.auth_version += 1
        admin.password_hash_encoded = password_hash.encoded
        admin.password_hash_algorithm = password_hash.algorithm
        admin.password_hash_version = password_hash.version
        admin.updated_at = current_time
        admin.row_version += 1
        session.flush()

    def authorize_consumed(
        self,
        session: Session,
        *,
        presented_token: object,
        now: datetime | None = None,
    ) -> ConsumedSetupAuthority:
        """Resolve the consumed setup bearer for the remainder of one setup."""

        current_time = _as_utc(now or _utc_now())
        try:
            token_digest = digest_setup_token(presented_token)
        except (TypeError, ValueError):
            token_digest = bytes(32)
        summary = session.execute(
            sa.select(
                PlatformAdminSetupChallenge.id,
                PlatformAdminSetupChallenge.platform_admin_id,
            ).where(
                PlatformAdminSetupChallenge.token_digest_sha256 == token_digest
            )
        ).one_or_none()
        if summary is None:
            raise RuntimeError("Platform setup state is unavailable.")
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == summary.platform_admin_id)
            .with_for_update()
        )
        challenge = session.scalar(
            sa.select(PlatformAdminSetupChallenge)
            .where(PlatformAdminSetupChallenge.id == summary.id)
            .with_for_update()
        )
        if (
            admin is None
            or challenge is None
            or admin.status not in {"setup_pending", "recovery_pending"}
            or challenge.setup_version != admin.setup_version
            or challenge.state != "consumed"
            or current_time >= _as_utc(challenge.expires_at)
            or not verify_setup_token(
                presented_token, challenge.token_digest_sha256
            )
        ):
            raise RuntimeError("Platform setup state is unavailable.")
        return ConsumedSetupAuthority(
            platform_admin_id=admin.id,
            setup_version=admin.setup_version,
            expires_at=_as_utc(challenge.expires_at),
        )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
