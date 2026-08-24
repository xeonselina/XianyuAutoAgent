"""Generic record-level AES-256-GCM authenticated encryption."""

from __future__ import annotations

import secrets
from dataclasses import dataclass, field

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .codec import CryptoCodecV1, UuidValue
from .errors import CryptoAuthenticationError, CryptoConfigurationError
from .root_key import RootKey

_CRYPTO_VERSION = 1
_AAD_VERSION = 1
_AES_KEY_BYTES = 32
_GCM_NONCE_BYTES = 12
_GCM_TAG_BYTES = 16


@dataclass(frozen=True, slots=True)
class EncryptedEnvelope:
    """Persistable envelope metadata; ciphertext includes the GCM tag."""

    nonce: bytes = field(repr=False)
    ciphertext: bytes = field(repr=False)
    root_key_version: int
    crypto_version: int
    aad_version: int

    def __post_init__(self) -> None:
        if not isinstance(self.nonce, bytes) or len(self.nonce) != _GCM_NONCE_BYTES:
            raise CryptoConfigurationError("AES-GCM nonce must contain exactly 12 bytes")
        if (
            not isinstance(self.ciphertext, bytes)
            or len(self.ciphertext) < _GCM_TAG_BYTES
        ):
            raise CryptoConfigurationError("AES-GCM ciphertext is invalid")
        CryptoCodecV1.uint64(self.root_key_version)
        _require_supported_version(self.crypto_version, _CRYPTO_VERSION)
        _require_supported_version(self.aad_version, _AAD_VERSION)


def encrypt_record(
    *,
    root_key: RootKey,
    purpose: str,
    record_uuid: UuidValue,
    revision: int,
    canonical_aad: bytes,
    plaintext: bytes,
    crypto_version: int = _CRYPTO_VERSION,
    aad_version: int = _AAD_VERSION,
) -> EncryptedEnvelope:
    """Encrypt one record with a newly generated 96-bit GCM nonce."""

    key = _derive_record_key(
        root_key=root_key,
        purpose=purpose,
        record_uuid=record_uuid,
        revision=revision,
        crypto_version=crypto_version,
        aad_version=aad_version,
    )
    aad = _require_canonical_aad(canonical_aad)
    if not isinstance(plaintext, bytes):
        raise CryptoConfigurationError("record plaintext must be bytes")
    nonce = secrets.token_bytes(_GCM_NONCE_BYTES)
    ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
    return EncryptedEnvelope(
        nonce=nonce,
        ciphertext=ciphertext,
        root_key_version=root_key.version,
        crypto_version=crypto_version,
        aad_version=aad_version,
    )


def decrypt_record(
    *,
    root_key: RootKey,
    envelope: EncryptedEnvelope,
    purpose: str,
    record_uuid: UuidValue,
    revision: int,
    canonical_aad: bytes,
) -> bytes:
    """Authenticate and decrypt one record, failing without secret details."""

    if not isinstance(root_key, RootKey) or not isinstance(envelope, EncryptedEnvelope):
        raise CryptoConfigurationError("record crypto input is invalid")
    if root_key.version != envelope.root_key_version:
        raise CryptoAuthenticationError("record authentication failed")
    key = _derive_record_key(
        root_key=root_key,
        purpose=purpose,
        record_uuid=record_uuid,
        revision=revision,
        crypto_version=envelope.crypto_version,
        aad_version=envelope.aad_version,
    )
    aad = _require_canonical_aad(canonical_aad)
    try:
        return AESGCM(key).decrypt(envelope.nonce, envelope.ciphertext, aad)
    except InvalidTag:
        raise CryptoAuthenticationError("record authentication failed") from None


def _derive_record_key(
    *,
    root_key: RootKey,
    purpose: str,
    record_uuid: UuidValue,
    revision: int,
    crypto_version: int,
    aad_version: int,
) -> bytes:
    if not isinstance(root_key, RootKey):
        raise CryptoConfigurationError("root key is invalid")
    _require_supported_version(crypto_version, _CRYPTO_VERSION)
    _require_supported_version(aad_version, _AAD_VERSION)
    record_bytes = CryptoCodecV1.uuid_bytes(record_uuid)
    info = CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain(purpose),
        record_bytes,
        CryptoCodecV1.uint64(revision),
        CryptoCodecV1.uint64(root_key.version),
        CryptoCodecV1.uint64(crypto_version),
        CryptoCodecV1.uint64(aad_version),
    )
    return HKDF(
        algorithm=hashes.SHA256(),
        length=_AES_KEY_BYTES,
        salt=record_bytes,
        info=info,
    ).derive(root_key._material_bytes())


def _require_supported_version(value: int, supported: int) -> None:
    CryptoCodecV1.uint64(value)
    if value != supported:
        raise CryptoConfigurationError("crypto protocol version is unsupported")


def _require_canonical_aad(value: bytes) -> bytes:
    if not isinstance(value, bytes) or not value:
        raise CryptoConfigurationError("canonical AAD must be non-empty bytes")
    return value
