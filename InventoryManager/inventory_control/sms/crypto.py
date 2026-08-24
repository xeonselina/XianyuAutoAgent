"""Purpose-separated HMAC protocol for six-digit SMS challenges."""

from __future__ import annotations

import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from inventory_control.crypto.codec import CryptoCodecV1
from inventory_control.crypto.errors import CryptoConfigurationError
from inventory_control.crypto.root_key import RootKey

from .contracts import SmsChallengeContext


SMS_HMAC_PROTOCOL_VERSION = 1
_HMAC_KEY_BYTES = 32
_CODE_KEY_DOMAIN = "inventory-manager/sms-challenge-code/v1"
_CODE_BINDING_DOMAIN = "inventory-manager/sms-challenge-binding/v1"


def calculate_code_hmac(
    *,
    root_key: RootKey,
    challenge_id: str,
    context: SmsChallengeContext,
    plaintext_code: str,
    protocol_version: int = SMS_HMAC_PROTOCOL_VERSION,
) -> bytes:
    """Return the context-bound HMAC persisted for one challenge."""

    if not isinstance(root_key, RootKey):
        raise CryptoConfigurationError("SMS challenge root key is invalid")
    if protocol_version != SMS_HMAC_PROTOCOL_VERSION:
        raise CryptoConfigurationError("SMS HMAC protocol version is unsupported")
    if not isinstance(context, SmsChallengeContext):
        raise CryptoConfigurationError("SMS challenge context is invalid")
    if (
        not isinstance(plaintext_code, str)
        or len(plaintext_code) != 6
        or not plaintext_code.isascii()
        or not plaintext_code.isdigit()
    ):
        raise CryptoConfigurationError("SMS verification code is invalid")

    challenge_bytes = CryptoCodecV1.uuid_bytes(challenge_id)
    info = CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain(_CODE_KEY_DOMAIN),
        challenge_bytes,
        CryptoCodecV1.uint64(root_key.version),
        CryptoCodecV1.uint64(protocol_version),
    )
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=_HMAC_KEY_BYTES,
        salt=challenge_bytes,
        info=info,
    ).derive(root_key._material_bytes())
    message = CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain(_CODE_BINDING_DOMAIN),
        CryptoCodecV1.ascii_text(context.purpose.value),
        CryptoCodecV1.ascii_text(context.phone.e164),
        _optional_uuid(context.user_id),
        _optional_uuid(context.tenant_id),
        _optional_uuid(context.actor_session_id),
        context.action_payload.digest_sha256,
        CryptoCodecV1.ascii_text(context.authoritative_revision),
        CryptoCodecV1.uint64(context.phone.normalization_version),
        CryptoCodecV1.ascii_text(context.phone.metadata_version),
        CryptoCodecV1.uint64(root_key.version),
        CryptoCodecV1.uint64(protocol_version),
        plaintext_code.encode("ascii"),
    )
    return hmac.digest(key, message, "sha256")


def verify_code_hmac(
    *,
    root_key: RootKey,
    challenge_id: str,
    context: SmsChallengeContext,
    plaintext_code: str,
    expected_hmac: bytes,
    protocol_version: int,
) -> bool:
    """Verify with fixed-size constant-time comparison and a safe false result."""

    if not isinstance(expected_hmac, bytes) or len(expected_hmac) != 32:
        return False
    try:
        candidate = calculate_code_hmac(
            root_key=root_key,
            challenge_id=challenge_id,
            context=context,
            plaintext_code=plaintext_code,
            protocol_version=protocol_version,
        )
    except (CryptoConfigurationError, TypeError, ValueError):
        return False
    return hmac.compare_digest(candidate, expected_hmac)


def _optional_uuid(value: str | None) -> bytes:
    return b"" if value is None else CryptoCodecV1.uuid_bytes(value)
