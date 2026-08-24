"""Encrypted TOTP and one-use recovery-code services for platform admins."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.crypto import (
    CryptoAuthenticationError,
    EncryptedEnvelope,
    RootKey,
    RootKeyRing,
)
from inventory_control.models.platform_identity import (
    PlatformAdmin,
    PlatformAdminRecoveryCode,
    PlatformAdminSetupChallenge,
    PlatformAdminTotpCredential,
)

from .tokens import digest_recovery_code, issue_recovery_code, verify_recovery_code
from .totp import (
    IssuedTotpSeed,
    TOTP_ALGORITHM,
    TOTP_DIGITS,
    TOTP_PERIOD_SECONDS,
    TOTP_SECRET_REVISION,
    decrypt_totp_seed,
    encrypt_totp_seed,
    find_accepted_totp_step,
    generate_totp_seed,
    totp_time_step,
)


_FACTOR_PROOF_SEAL = object()


class VerifiedPlatformFactor:
    """One-use in-memory proof consumed by platform session issuance."""

    __slots__ = (
        "platform_admin_id",
        "method",
        "factor_record_id",
        "totp_time_step",
        "verified_at",
        "_seal",
        "_available",
    )

    def __init__(
        self,
        *,
        platform_admin_id: str,
        method: str,
        factor_record_id: str,
        totp_time_step: int | None,
        verified_at: datetime,
        _seal: object,
    ) -> None:
        if _seal is not _FACTOR_PROOF_SEAL:
            raise RuntimeError("Platform factor proof cannot be constructed directly")
        self.platform_admin_id = platform_admin_id
        self.method = method
        self.factor_record_id = factor_record_id
        self.totp_time_step = totp_time_step
        self.verified_at = verified_at
        self._seal = _seal
        self._available = True

    def _claim(self) -> None:
        if self._seal is not _FACTOR_PROOF_SEAL or not self._available:
            raise RuntimeError("Platform factor proof is no longer available")
        self._available = False

    def __repr__(self) -> str:
        return (
            f"VerifiedPlatformFactor(method={self.method!r}, "
            "<credential-redacted>)"
        )


class IssuedRecoveryCodeBatch:
    __slots__ = ("platform_admin_id", "generation", "_plaintext_codes")

    def __init__(
        self,
        *,
        platform_admin_id: str,
        generation: int,
        plaintext_codes: tuple[str, ...],
    ) -> None:
        self.platform_admin_id = platform_admin_id
        self.generation = generation
        self._plaintext_codes = plaintext_codes

    def take_plaintext_codes(self) -> tuple[str, ...]:
        if self._plaintext_codes is None:
            raise RuntimeError("Recovery codes are no longer available")
        codes = self._plaintext_codes
        self._plaintext_codes = None
        return codes

    def __repr__(self) -> str:
        return (
            f"IssuedRecoveryCodeBatch(platform_admin_id={self.platform_admin_id!r}, "
            f"generation={self.generation!r}, <redacted>)"
        )


class PlatformFactorRejected(RuntimeError):
    code = "PLATFORM_FACTOR_REJECTED"

    def __init__(self) -> None:
        super().__init__("The platform authentication factor is invalid.")


class PlatformCurrentFactorService:
    """Verify either current platform MFA method behind one shared contract."""

    def __init__(
        self,
        *,
        totp_service: PlatformTotpService | None = None,
        recovery_code_service: PlatformRecoveryCodeService | None = None,
    ) -> None:
        self._totp_service = totp_service or PlatformTotpService()
        self._recovery_code_service = (
            recovery_code_service or PlatformRecoveryCodeService()
        )

    def verify(
        self,
        session: Session,
        *,
        platform_admin_id: str,
        factor_method: object,
        factor_value: object,
        key_ring: RootKeyRing,
        now: datetime,
        allowed_totp_drift_steps: int,
    ) -> VerifiedPlatformFactor:
        if not isinstance(key_ring, RootKeyRing):
            raise TypeError("key_ring must be a RootKeyRing")
        if factor_method == "totp":
            root_version = session.scalar(
                sa.select(PlatformAdminTotpCredential.root_key_version).where(
                    PlatformAdminTotpCredential.platform_admin_id
                    == platform_admin_id,
                    PlatformAdminTotpCredential.status == "confirmed",
                )
            )
            if root_version is None:
                raise PlatformFactorRejected()
            return self._totp_service.verify_current(
                session,
                platform_admin_id=platform_admin_id,
                presented_code=factor_value,
                root_key=key_ring.key_for_existing_reference(root_version),
                now=now,
                allowed_drift_steps=allowed_totp_drift_steps,
            )
        if factor_method == "recovery_code":
            return self._recovery_code_service.consume(
                session,
                platform_admin_id=platform_admin_id,
                presented_code=factor_value,
                now=now,
            )
        raise PlatformFactorRejected()


class PlatformTotpService:
    def __init__(self, *, seed_generator=generate_totp_seed) -> None:
        self._seed_generator = seed_generator

    def create_pending_binding(
        self,
        session: Session,
        *,
        platform_admin_id: str,
        root_key: RootKey,
        now: datetime | None = None,
    ) -> IssuedTotpSeed:
        current_time = _as_utc(now or _utc_now())
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == platform_admin_id)
            .with_for_update()
        )
        if admin is None or admin.status not in {
            "setup_pending",
            "recovery_pending",
        }:
            raise PlatformFactorRejected()
        setup_consumed = session.scalar(
            sa.select(sa.func.count(PlatformAdminSetupChallenge.id)).where(
                PlatformAdminSetupChallenge.platform_admin_id == admin.id,
                PlatformAdminSetupChallenge.setup_version == admin.setup_version,
                PlatformAdminSetupChallenge.state == "consumed",
            )
        )
        if admin.password_hash_encoded is None or setup_consumed != 1:
            raise PlatformFactorRejected()
        existing = list(
            session.scalars(
                sa.select(PlatformAdminTotpCredential)
                .where(
                    PlatformAdminTotpCredential.platform_admin_id == admin.id,
                    PlatformAdminTotpCredential.status.in_(
                        ("pending", "confirmed")
                    ),
                )
                .order_by(PlatformAdminTotpCredential.generation)
                .with_for_update()
            )
        )
        if existing:
            raise PlatformFactorRejected()
        seed = self._seed_generator()
        if not isinstance(seed, bytes) or len(seed) < 16:
            raise RuntimeError("TOTP seed generator returned an invalid value")
        credential_id = str(uuid4())
        envelope = encrypt_totp_seed(
            root_key=root_key,
            credential_id=credential_id,
            platform_admin_id=admin.id,
            secret_revision=TOTP_SECRET_REVISION,
            seed=seed,
        )
        credential = PlatformAdminTotpCredential(
            id=credential_id,
            platform_admin_id=admin.id,
            generation=admin.totp_generation,
            secret_revision=TOTP_SECRET_REVISION,
            status="pending",
            seed_nonce=envelope.nonce,
            seed_ciphertext=envelope.ciphertext,
            root_key_version=envelope.root_key_version,
            crypto_version=envelope.crypto_version,
            aad_version=envelope.aad_version,
            totp_algorithm=TOTP_ALGORITHM,
            totp_digits=TOTP_DIGITS,
            totp_period_seconds=TOTP_PERIOD_SECONDS,
            row_version=1,
            created_at=current_time,
        )
        session.add(credential)
        session.flush()
        return IssuedTotpSeed(credential_id=credential.id, seed=seed)

    def confirm_pending(
        self,
        session: Session,
        *,
        credential_id: str,
        presented_code: object,
        root_key: RootKey,
        now: datetime | None = None,
        allowed_drift_steps: int = 1,
    ) -> VerifiedPlatformFactor:
        current_time = _as_utc(now or _utc_now())
        summary = session.execute(
            sa.select(PlatformAdminTotpCredential.platform_admin_id).where(
                PlatformAdminTotpCredential.id == credential_id
            )
        ).scalar_one_or_none()
        if summary is None:
            raise PlatformFactorRejected()
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == summary)
            .with_for_update()
        )
        credential = session.scalar(
            sa.select(PlatformAdminTotpCredential)
            .where(PlatformAdminTotpCredential.id == credential_id)
            .with_for_update()
        )
        if (
            admin is None
            or credential is None
            or admin.status not in {"setup_pending", "recovery_pending"}
            or credential.platform_admin_id != admin.id
            or credential.generation != admin.totp_generation
            or credential.status != "pending"
        ):
            raise PlatformFactorRejected()
        accepted_step = self._accepted_step(
            credential=credential,
            presented_code=presented_code,
            root_key=root_key,
            now=current_time,
            allowed_drift_steps=allowed_drift_steps,
        )
        if accepted_step is None:
            raise PlatformFactorRejected()
        changed = session.execute(
            sa.update(PlatformAdminTotpCredential)
            .where(
                PlatformAdminTotpCredential.id == credential.id,
                PlatformAdminTotpCredential.row_version == credential.row_version,
                PlatformAdminTotpCredential.status == "pending",
                PlatformAdminTotpCredential.last_accepted_time_step.is_(None),
            )
            .values(
                status="confirmed",
                confirmed_at=current_time,
                last_accepted_time_step=accepted_step,
                row_version=credential.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise PlatformFactorRejected()
        session.expire(credential)
        return _factor_proof(
            admin_id=admin.id,
            method="totp",
            record_id=credential.id,
            time_step=accepted_step,
            now=current_time,
        )

    def verify_current(
        self,
        session: Session,
        *,
        platform_admin_id: str,
        presented_code: object,
        root_key: RootKey,
        now: datetime | None = None,
        allowed_drift_steps: int = 1,
    ) -> VerifiedPlatformFactor:
        current_time = _as_utc(now or _utc_now())
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == platform_admin_id)
            .with_for_update()
        )
        if admin is None or admin.status != "active":
            raise PlatformFactorRejected()
        credential = session.scalar(
            sa.select(PlatformAdminTotpCredential)
            .where(
                PlatformAdminTotpCredential.platform_admin_id == admin.id,
                PlatformAdminTotpCredential.status == "confirmed",
                PlatformAdminTotpCredential.generation == admin.totp_generation,
            )
            .with_for_update()
        )
        if credential is None:
            raise PlatformFactorRejected()
        accepted_step = self._accepted_step(
            credential=credential,
            presented_code=presented_code,
            root_key=root_key,
            now=current_time,
            allowed_drift_steps=allowed_drift_steps,
        )
        if accepted_step is None:
            raise PlatformFactorRejected()
        changed = session.execute(
            sa.update(PlatformAdminTotpCredential)
            .where(
                PlatformAdminTotpCredential.id == credential.id,
                PlatformAdminTotpCredential.row_version == credential.row_version,
                PlatformAdminTotpCredential.status == "confirmed",
                sa.or_(
                    PlatformAdminTotpCredential.last_accepted_time_step.is_(None),
                    PlatformAdminTotpCredential.last_accepted_time_step
                    < accepted_step,
                ),
            )
            .values(
                last_accepted_time_step=accepted_step,
                row_version=credential.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise PlatformFactorRejected()
        session.expire(credential)
        return _factor_proof(
            admin_id=admin.id,
            method="totp",
            record_id=credential.id,
            time_step=accepted_step,
            now=current_time,
        )

    def create_pending_replacement(
        self,
        session: Session,
        *,
        platform_admin_id: str,
        root_key: RootKey,
        now: datetime | None = None,
    ) -> IssuedTotpSeed:
        """Stage a new seed without disturbing the current confirmed seed."""

        current_time = _as_utc(now or _utc_now())
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == platform_admin_id)
            .with_for_update()
        )
        if admin is None or admin.status != "active":
            raise PlatformFactorRejected()
        credentials = list(
            session.scalars(
                sa.select(PlatformAdminTotpCredential)
                .where(PlatformAdminTotpCredential.platform_admin_id == admin.id)
                .order_by(PlatformAdminTotpCredential.generation)
                .with_for_update()
            )
        )
        current = [
            row
            for row in credentials
            if row.status == "confirmed"
            and row.generation == admin.totp_generation
        ]
        if len(current) != 1 or any(
            row.status == "confirmed" and row not in current
            for row in credentials
        ):
            raise PlatformFactorRejected()
        for row in credentials:
            if row.status == "pending":
                row.status = "revoked"
                row.retired_at = current_time
                row.row_version += 1

        generation = max(
            (row.generation for row in credentials),
            default=admin.totp_generation,
        ) + 1
        seed = self._seed_generator()
        if not isinstance(seed, bytes) or len(seed) < 16:
            raise RuntimeError("TOTP seed generator returned an invalid value")
        credential_id = str(uuid4())
        envelope = encrypt_totp_seed(
            root_key=root_key,
            credential_id=credential_id,
            platform_admin_id=admin.id,
            secret_revision=TOTP_SECRET_REVISION,
            seed=seed,
        )
        session.add(
            PlatformAdminTotpCredential(
                id=credential_id,
                platform_admin_id=admin.id,
                generation=generation,
                secret_revision=TOTP_SECRET_REVISION,
                status="pending",
                seed_nonce=envelope.nonce,
                seed_ciphertext=envelope.ciphertext,
                root_key_version=envelope.root_key_version,
                crypto_version=envelope.crypto_version,
                aad_version=envelope.aad_version,
                totp_algorithm=TOTP_ALGORITHM,
                totp_digits=TOTP_DIGITS,
                totp_period_seconds=TOTP_PERIOD_SECONDS,
                row_version=1,
                created_at=current_time,
            )
        )
        session.flush()
        return IssuedTotpSeed(credential_id=credential_id, seed=seed)

    def confirm_replacement(
        self,
        session: Session,
        *,
        platform_admin_id: str,
        credential_id: str,
        presented_code: object,
        root_key: RootKey,
        now: datetime | None = None,
        allowed_drift_steps: int = 1,
    ) -> int:
        """Atomically promote a staged seed and retire the old credential."""

        current_time = _as_utc(now or _utc_now())
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == platform_admin_id)
            .with_for_update()
        )
        credentials = list(
            session.scalars(
                sa.select(PlatformAdminTotpCredential)
                .where(
                    PlatformAdminTotpCredential.platform_admin_id
                    == platform_admin_id
                )
                .order_by(PlatformAdminTotpCredential.generation)
                .with_for_update()
            )
        )
        current = [
            row
            for row in credentials
            if row.status == "confirmed"
            and admin is not None
            and row.generation == admin.totp_generation
        ]
        pending = [
            row
            for row in credentials
            if row.id == credential_id and row.status == "pending"
        ]
        if (
            admin is None
            or admin.status != "active"
            or len(current) != 1
            or len(pending) != 1
            or pending[0].generation <= admin.totp_generation
            or any(
                row.status in {"pending", "confirmed"}
                and row not in {current[0], pending[0]}
                for row in credentials
            )
        ):
            raise PlatformFactorRejected()
        replacement = pending[0]
        accepted_step = self._accepted_step(
            credential=replacement,
            presented_code=presented_code,
            root_key=root_key,
            now=current_time,
            allowed_drift_steps=allowed_drift_steps,
        )
        if accepted_step is None:
            raise PlatformFactorRejected()

        current[0].status = "replaced"
        current[0].retired_at = current_time
        current[0].row_version += 1
        # Release the generated-current uniqueness slot before promoting the
        # replacement; ORM update ordering must not decide credential safety.
        session.flush([current[0]])
        replacement.status = "confirmed"
        replacement.confirmed_at = current_time
        replacement.last_accepted_time_step = accepted_step
        replacement.row_version += 1
        admin.totp_generation = replacement.generation
        admin.row_version += 1
        admin.updated_at = current_time
        session.flush()
        return replacement.generation

    @staticmethod
    def _accepted_step(
        *,
        credential: PlatformAdminTotpCredential,
        presented_code: object,
        root_key: RootKey,
        now: datetime,
        allowed_drift_steps: int,
    ) -> int | None:
        envelope = EncryptedEnvelope(
            nonce=bytes(credential.seed_nonce),
            ciphertext=bytes(credential.seed_ciphertext),
            root_key_version=credential.root_key_version,
            crypto_version=credential.crypto_version,
            aad_version=credential.aad_version,
        )
        try:
            seed = decrypt_totp_seed(
                root_key=root_key,
                credential_id=credential.id,
                platform_admin_id=credential.platform_admin_id,
                secret_revision=credential.secret_revision,
                envelope=envelope,
            )
        except (CryptoAuthenticationError, TypeError, ValueError):
            return None
        current_step = totp_time_step(
            int(now.timestamp()), period_seconds=credential.totp_period_seconds
        )
        return find_accepted_totp_step(
            seed=seed,
            presented_code=presented_code,
            current_time_step=current_step,
            last_accepted_time_step=credential.last_accepted_time_step,
            allowed_drift_steps=allowed_drift_steps,
            digits=credential.totp_digits,
            algorithm=credential.totp_algorithm,
        )


class PlatformRecoveryCodeService:
    def issue_codes(
        self,
        session: Session,
        *,
        platform_admin_id: str,
        count: int = 10,
        ttl: timedelta | None = None,
        now: datetime | None = None,
    ) -> IssuedRecoveryCodeBatch:
        if (
            isinstance(count, bool)
            or not isinstance(count, int)
            or not 6 <= count <= 20
        ):
            raise ValueError("recovery code count is invalid")
        if ttl is not None and ttl <= timedelta(0):
            raise ValueError("recovery code TTL is invalid")
        current_time = _as_utc(now or _utc_now())
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == platform_admin_id)
            .with_for_update()
        )
        if admin is None or admin.status not in {
            "setup_pending",
            "recovery_pending",
            "active",
        }:
            raise PlatformFactorRejected()
        confirmed_totp_count = session.scalar(
            sa.select(sa.func.count(PlatformAdminTotpCredential.id)).where(
                PlatformAdminTotpCredential.platform_admin_id == admin.id,
                PlatformAdminTotpCredential.generation == admin.totp_generation,
                PlatformAdminTotpCredential.status == "confirmed",
            )
        )
        if admin.password_hash_encoded is None or confirmed_totp_count != 1:
            raise PlatformFactorRejected()
        current_rows = list(
            session.scalars(
                sa.select(PlatformAdminRecoveryCode)
                .where(
                    PlatformAdminRecoveryCode.platform_admin_id == admin.id,
                    PlatformAdminRecoveryCode.generation
                    == admin.recovery_code_generation,
                )
                .order_by(PlatformAdminRecoveryCode.ordinal)
                .with_for_update()
            )
        )
        if current_rows:
            for row in current_rows:
                if row.state == "active":
                    row.state = "revoked"
                    row.revoked_at = current_time
                    row.row_version += 1
            admin.recovery_code_generation += 1
            admin.row_version += 1
        generation = admin.recovery_code_generation
        issued = tuple(issue_recovery_code() for _ in range(count))
        expires_at = current_time + ttl if ttl is not None else None
        for ordinal, token in enumerate(issued, start=1):
            session.add(
                PlatformAdminRecoveryCode(
                    platform_admin_id=admin.id,
                    generation=generation,
                    ordinal=ordinal,
                    token_digest_sha256=token.digest_sha256,
                    state="active",
                    row_version=1,
                    created_at=current_time,
                    expires_at=expires_at,
                )
            )
        session.flush()
        return IssuedRecoveryCodeBatch(
            platform_admin_id=admin.id,
            generation=generation,
            plaintext_codes=tuple(token.plaintext for token in issued),
        )

    def consume(
        self,
        session: Session,
        *,
        platform_admin_id: str,
        presented_code: object,
        now: datetime | None = None,
    ) -> VerifiedPlatformFactor:
        current_time = _as_utc(now or _utc_now())
        admin = session.scalar(
            sa.select(PlatformAdmin)
            .where(PlatformAdmin.id == platform_admin_id)
            .with_for_update()
        )
        if admin is None or admin.status != "active":
            raise PlatformFactorRejected()
        try:
            digest = digest_recovery_code(presented_code)
        except (TypeError, ValueError):
            digest = bytes(32)
        row = session.scalar(
            sa.select(PlatformAdminRecoveryCode)
            .where(
                PlatformAdminRecoveryCode.platform_admin_id == admin.id,
                PlatformAdminRecoveryCode.generation
                == admin.recovery_code_generation,
                PlatformAdminRecoveryCode.token_digest_sha256 == digest,
            )
            .with_for_update()
        )
        if (
            row is None
            or row.state != "active"
            or (row.expires_at is not None and current_time >= _as_utc(row.expires_at))
            or not verify_recovery_code(presented_code, row.token_digest_sha256)
        ):
            raise PlatformFactorRejected()
        changed = session.execute(
            sa.update(PlatformAdminRecoveryCode)
            .where(
                PlatformAdminRecoveryCode.id == row.id,
                PlatformAdminRecoveryCode.row_version == row.row_version,
                PlatformAdminRecoveryCode.state == "active",
                PlatformAdminRecoveryCode.consumed_at.is_(None),
                PlatformAdminRecoveryCode.revoked_at.is_(None),
                sa.or_(
                    PlatformAdminRecoveryCode.expires_at.is_(None),
                    PlatformAdminRecoveryCode.expires_at > current_time,
                ),
            )
            .values(
                state="consumed",
                consumed_at=current_time,
                row_version=row.row_version + 1,
            )
            .execution_options(synchronize_session=False)
        )
        if changed.rowcount != 1:
            raise PlatformFactorRejected()
        session.expire(row)
        return _factor_proof(
            admin_id=admin.id,
            method="recovery_code",
            record_id=row.id,
            time_step=None,
            now=current_time,
        )


def activate_admin_if_ready(
    session: Session,
    *,
    platform_admin_id: str,
    expected_setup_version: int,
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
        or admin.password_hash_encoded is None
    ):
        raise PlatformFactorRejected()
    setup_consumed = session.scalar(
        sa.select(sa.func.count(PlatformAdminSetupChallenge.id)).where(
            PlatformAdminSetupChallenge.platform_admin_id == admin.id,
            PlatformAdminSetupChallenge.setup_version == admin.setup_version,
            PlatformAdminSetupChallenge.state == "consumed",
        )
    )
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
    if setup_consumed != 1 or confirmed_totp != 1 or not active_recovery:
        raise PlatformFactorRejected()
    admin.status = "active"
    admin.updated_at = current_time
    admin.row_version += 1
    session.flush()


def _factor_proof(
    *,
    admin_id: str,
    method: str,
    record_id: str,
    time_step: int | None,
    now: datetime,
) -> VerifiedPlatformFactor:
    return VerifiedPlatformFactor(
        platform_admin_id=admin_id,
        method=method,
        factor_record_id=record_id,
        totp_time_step=time_step,
        verified_at=now,
        _seal=_FACTOR_PROOF_SEAL,
    )


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
