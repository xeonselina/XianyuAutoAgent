"""RFC 6238 TOTP and purpose-separated seed envelope primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct

from inventory_control.crypto import (
    CryptoCodecV1,
    EncryptedEnvelope,
    RootKey,
    decrypt_record,
    encrypt_record,
)


TOTP_SEED_BYTES = 20
TOTP_ALGORITHM = "SHA1"
TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30
TOTP_SECRET_REVISION = 1
TOTP_PURPOSE = "inventory-manager/platform-admin-totp/v1"
TOTP_AAD_PURPOSE = "inventory-manager/platform-admin-totp/aad/v1"


class IssuedTotpSeed:
    """One-shot base32 seed returned only to the binding UI boundary."""

    __slots__ = ("credential_id", "_base32_seed")

    def __init__(self, *, credential_id: str, seed: bytes) -> None:
        self.credential_id = credential_id
        self._base32_seed = base64.b32encode(seed).rstrip(b"=").decode("ascii")

    def take_base32_seed(self) -> str:
        if self._base32_seed is None:
            raise RuntimeError("TOTP seed is no longer available")
        seed = self._base32_seed
        self._base32_seed = None
        return seed

    def __repr__(self) -> str:
        return f"IssuedTotpSeed(credential_id={self.credential_id!r}, <redacted>)"


def generate_totp_seed() -> bytes:
    return secrets.token_bytes(TOTP_SEED_BYTES)


def generate_totp_code(
    seed: bytes,
    time_step: int,
    *,
    digits: int = TOTP_DIGITS,
    algorithm: str = TOTP_ALGORITHM,
) -> str:
    """Generate an RFC 6238 code for an already-computed integer time step."""

    if not isinstance(seed, bytes) or len(seed) < 16:
        raise ValueError("TOTP seed is invalid")
    if isinstance(time_step, bool) or not isinstance(time_step, int) or time_step < 0:
        raise ValueError("TOTP time step is invalid")
    if digits not in {6, 8} or algorithm != "SHA1":
        raise ValueError("TOTP parameters are unsupported")
    digest = hmac.digest(seed, struct.pack(">Q", time_step), hashlib.sha1)
    offset = digest[-1] & 0x0F
    binary = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{binary % (10**digits):0{digits}d}"


def find_accepted_totp_step(
    *,
    seed: bytes,
    presented_code: object,
    current_time_step: int,
    last_accepted_time_step: int | None,
    allowed_drift_steps: int = 1,
    digits: int = TOTP_DIGITS,
    algorithm: str = TOTP_ALGORITHM,
) -> int | None:
    """Return a matching strictly-new time step, or one fixed false result."""

    code_is_valid = bool(
        isinstance(presented_code, str)
        and len(presented_code) == digits
        and presented_code.isascii()
        and presented_code.isdigit()
    )
    candidate_code = presented_code if code_is_valid else "0" * digits
    if allowed_drift_steps not in {0, 1}:
        raise ValueError("TOTP drift must be zero or one time step")
    lower_bound = max(0, current_time_step - allowed_drift_steps)
    upper_bound = current_time_step + allowed_drift_steps
    matches: list[int] = []
    for time_step in range(lower_bound, upper_bound + 1):
        generated = generate_totp_code(
            seed, time_step, digits=digits, algorithm=algorithm
        )
        if hmac.compare_digest(candidate_code, generated):
            matches.append(time_step)
    if not code_is_valid or not matches:
        return None
    accepted_step = max(matches)
    if (
        last_accepted_time_step is not None
        and accepted_step <= last_accepted_time_step
    ):
        return None
    return accepted_step


def totp_time_step(unix_timestamp_seconds: int, *, period_seconds: int = 30) -> int:
    if (
        isinstance(unix_timestamp_seconds, bool)
        or not isinstance(unix_timestamp_seconds, int)
        or unix_timestamp_seconds < 0
        or period_seconds < 1
    ):
        raise ValueError("TOTP timestamp is invalid")
    return unix_timestamp_seconds // period_seconds


def encrypt_totp_seed(
    *,
    root_key: RootKey,
    credential_id: str,
    platform_admin_id: str,
    secret_revision: int,
    seed: bytes,
) -> EncryptedEnvelope:
    return encrypt_record(
        root_key=root_key,
        purpose=TOTP_PURPOSE,
        record_uuid=credential_id,
        revision=secret_revision,
        canonical_aad=canonical_totp_aad(
            credential_id=credential_id,
            platform_admin_id=platform_admin_id,
            secret_revision=secret_revision,
            root_key_version=root_key.version,
            crypto_version=1,
            aad_version=1,
        ),
        plaintext=seed,
    )


def decrypt_totp_seed(
    *,
    root_key: RootKey,
    credential_id: str,
    platform_admin_id: str,
    secret_revision: int,
    envelope: EncryptedEnvelope,
) -> bytes:
    seed = decrypt_record(
        root_key=root_key,
        envelope=envelope,
        purpose=TOTP_PURPOSE,
        record_uuid=credential_id,
        revision=secret_revision,
        canonical_aad=canonical_totp_aad(
            credential_id=credential_id,
            platform_admin_id=platform_admin_id,
            secret_revision=secret_revision,
            root_key_version=envelope.root_key_version,
            crypto_version=envelope.crypto_version,
            aad_version=envelope.aad_version,
        ),
    )
    if len(seed) < 16:
        raise ValueError("TOTP seed is invalid")
    return seed


def canonical_totp_aad(
    *,
    credential_id: str,
    platform_admin_id: str,
    secret_revision: int,
    root_key_version: int,
    crypto_version: int,
    aad_version: int,
) -> bytes:
    return CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain(TOTP_AAD_PURPOSE),
        CryptoCodecV1.uuid_bytes(credential_id),
        CryptoCodecV1.uuid_bytes(platform_admin_id),
        CryptoCodecV1.uint64(secret_revision),
        CryptoCodecV1.uint64(root_key_version),
        CryptoCodecV1.uint64(crypto_version),
        CryptoCodecV1.uint64(aad_version),
    )

