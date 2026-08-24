"""Purpose-separated keyed fingerprints for global provider-account claims."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .codec import CryptoCodecV1
from .errors import CryptoConfigurationError
from .root_key import RootKey


_SUPPORTED_PROVIDER = "sf"
_FINGERPRINT_VERSION = 1
_FINGERPRINT_BYTES = 32
_MAX_CANONICAL_ACCOUNT_BYTES = 128


@dataclass(frozen=True, slots=True, repr=False)
class ProviderAccountFingerprint:
    """Opaque claim identity; never suitable for tenant output or logs."""

    provider: str
    fingerprint_version: int
    root_key_version: int
    digest: bytes = field(repr=False)

    def __post_init__(self) -> None:
        if self.provider != _SUPPORTED_PROVIDER:
            raise CryptoConfigurationError("provider account fingerprint is invalid")
        if self.fingerprint_version != _FINGERPRINT_VERSION:
            raise CryptoConfigurationError("provider account fingerprint is invalid")
        CryptoCodecV1.uint64(self.root_key_version)
        if not isinstance(self.digest, bytes) or len(self.digest) != 32:
            raise CryptoConfigurationError("provider account fingerprint is invalid")

    def __repr__(self) -> str:
        return (
            "ProviderAccountFingerprint("
            f"provider={self.provider!r}, "
            f"fingerprint_version={self.fingerprint_version}, "
            f"root_key_version={self.root_key_version}, digest=<redacted>)"
        )


def derive_provider_account_fingerprint(
    *,
    root_key: RootKey,
    provider: str,
    canonical_account: str,
    fingerprint_version: int = _FINGERPRINT_VERSION,
) -> ProviderAccountFingerprint:
    """Fingerprint one provider-normalized account without reversible storage.

    Provider normalization intentionally happens before this boundary.  The
    function treats the resulting printable ASCII text as an exact byte string
    and therefore never strips or numerically reinterprets leading zeroes.
    """

    if not isinstance(root_key, RootKey):
        raise CryptoConfigurationError("root key is invalid")
    if provider != _SUPPORTED_PROVIDER:
        raise CryptoConfigurationError("provider account fingerprint is unsupported")
    if fingerprint_version != _FINGERPRINT_VERSION:
        raise CryptoConfigurationError(
            "provider account fingerprint version is unsupported"
        )
    try:
        account_bytes = canonical_account.encode("ascii")
    except (AttributeError, UnicodeEncodeError):
        raise CryptoConfigurationError(
            "canonical provider account is invalid"
        ) from None
    if (
        not account_bytes
        or len(account_bytes) > _MAX_CANONICAL_ACCOUNT_BYTES
        or canonical_account != canonical_account.strip()
        or any(byte < 0x21 or byte > 0x7E for byte in account_bytes)
    ):
        raise CryptoConfigurationError("canonical provider account is invalid")

    domain = CryptoCodecV1.domain(
        "inventory-manager/provider-account-fingerprint/sf/v1"
    )
    derivation_context = CryptoCodecV1.encode_parts(
        domain,
        CryptoCodecV1.uint64(root_key.version),
        CryptoCodecV1.uint64(fingerprint_version),
    )
    fingerprint_key = HKDF(
        algorithm=hashes.SHA256(),
        length=_FINGERPRINT_BYTES,
        salt=hashlib.sha256(domain).digest(),
        info=derivation_context,
    ).derive(root_key._material_bytes())
    message = CryptoCodecV1.encode_parts(
        domain,
        CryptoCodecV1.ascii_text(provider),
        CryptoCodecV1.uint64(fingerprint_version),
        account_bytes,
    )
    digest = hmac.new(fingerprint_key, message, hashlib.sha256).digest()
    return ProviderAccountFingerprint(
        provider=provider,
        fingerprint_version=fingerprint_version,
        root_key_version=root_key.version,
        digest=digest,
    )
