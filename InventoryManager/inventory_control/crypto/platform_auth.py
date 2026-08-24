"""Purpose-separated subject digests for platform-authentication throttles."""

from __future__ import annotations

import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .codec import CryptoCodecV1
from .errors import CryptoConfigurationError
from .root_key import RootKey


PLATFORM_AUTH_SUBJECT_DIGEST_VERSION = 1
_SUBJECT_KEY_DOMAIN = "inventory-manager/platform-auth-rate-subject-key/v1"
_SUBJECT_BINDING_DOMAIN = "inventory-manager/platform-auth-rate-subject/v1"
_SUBJECT_TYPES = frozenset({"username", "ip", "device"})


def derive_platform_auth_subject_digest(
    *,
    root_key: RootKey,
    subject_type: str,
    subject_value: str,
    protocol_version: int = PLATFORM_AUTH_SUBJECT_DIGEST_VERSION,
) -> bytes:
    """Return a non-reversible, purpose-bound digest for one throttle subject.

    The control database stores only this digest.  It cannot be reused as a
    tenant SMS subject, provider fingerprint, or credential verifier.
    """

    if not isinstance(root_key, RootKey):
        raise CryptoConfigurationError("platform auth root key is invalid")
    if protocol_version != PLATFORM_AUTH_SUBJECT_DIGEST_VERSION:
        raise CryptoConfigurationError(
            "platform auth subject protocol version is unsupported"
        )
    if subject_type not in _SUBJECT_TYPES:
        raise CryptoConfigurationError("platform auth subject type is invalid")
    if (
        not isinstance(subject_value, str)
        or not 1 <= len(subject_value) <= 255
    ):
        raise CryptoConfigurationError("platform auth subject value is invalid")
    try:
        value_bytes = subject_value.encode("utf-8")
    except UnicodeEncodeError:
        raise CryptoConfigurationError(
            "platform auth subject value is invalid"
        ) from None
    if len(value_bytes) > 1024 or any(byte == 0 for byte in value_bytes):
        raise CryptoConfigurationError("platform auth subject value is invalid")

    domain = CryptoCodecV1.domain(_SUBJECT_KEY_DOMAIN)
    info = CryptoCodecV1.encode_parts(
        domain,
        CryptoCodecV1.uint64(root_key.version),
        CryptoCodecV1.uint64(protocol_version),
    )
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=domain,
        info=info,
    ).derive(root_key._material_bytes())
    message = CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain(_SUBJECT_BINDING_DOMAIN),
        CryptoCodecV1.ascii_text(subject_type),
        value_bytes,
        CryptoCodecV1.uint64(root_key.version),
        CryptoCodecV1.uint64(protocol_version),
    )
    return hmac.digest(key, message, "sha256")
