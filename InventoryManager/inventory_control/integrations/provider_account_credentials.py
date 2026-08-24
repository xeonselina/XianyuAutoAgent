"""SF monthly-account normalization and isolated encrypted envelopes."""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field
from uuid import UUID

from inventory_control.crypto import (
    CryptoCodecV1,
    CryptoError,
    EncryptedEnvelope,
    ProviderAccountFingerprint,
    RootKey,
    decrypt_record,
    encrypt_record,
)


ACCOUNT_SECRET_SCHEMA_VERSION = 1
ACCOUNT_SECRET_BUNDLE_VERSION = 1
ACCOUNT_CRYPTO_VERSION = 1
ACCOUNT_AAD_VERSION = 1
_MAX_ACCOUNT_BYTES = 128


class ProviderAccountCredentialError(RuntimeError):
    code = "PROVIDER_ACCOUNT_CREDENTIAL_ERROR"
    public_message = "provider account credential operation failed"

    def __init__(self) -> None:
        super().__init__(self.public_message)


class ProviderAccountCredentialInputError(ProviderAccountCredentialError):
    code = "PROVIDER_ACCOUNT_CREDENTIAL_INPUT_INVALID"
    public_message = "provider account credential input is invalid"


class ProviderAccountCredentialAuthenticationError(ProviderAccountCredentialError):
    code = "PROVIDER_ACCOUNT_CREDENTIAL_AUTHENTICATION_FAILED"
    public_message = "provider account credential authentication failed"


class CanonicalSfAccountSecret:
    """Exact v1 SF account text; deliberately absent from repr and DTOs."""

    __slots__ = ("_bytes",)

    def __init__(self, value: str) -> None:
        try:
            encoded = value.encode("ascii")
        except (AttributeError, UnicodeEncodeError):
            raise ProviderAccountCredentialInputError() from None
        if (
            not encoded
            or len(encoded) > _MAX_ACCOUNT_BYTES
            or value != value.strip()
            or any(byte < 0x21 or byte > 0x7E for byte in encoded)
        ):
            raise ProviderAccountCredentialInputError()
        self._bytes = encoded

    def __repr__(self) -> str:
        return "CanonicalSfAccountSecret(value=<redacted>)"

    @property
    def canonical_semantics_digest(self) -> bytes:
        return hashlib.sha256(self._bytes).digest()

    @property
    def masked_hint(self) -> str:
        visible = self._bytes[-4:].decode("ascii") if len(self._bytes) > 4 else ""
        return f"****{visible}"

    def _canonical_bytes(self) -> bytes:
        return bytes(self._bytes)

    def _provider_value(self) -> str:
        """Internal bridge for an immediately invoked provider adapter."""

        return self._bytes.decode("ascii")


@dataclass(frozen=True, slots=True)
class ProviderAccountSecretCryptoContext:
    """Immutable ownership and claim facts authenticated by one revision."""

    crypto_context_uuid: str
    tenant_uuid: str
    provider: str
    provider_account_uuid: str
    integration_uuid: str
    revision_no: int
    account_secret_schema_version: int
    account_secret_bundle_version: int
    canonical_semantics_digest: bytes = field(repr=False)
    provider_account_claim_uuid: str
    account_fingerprint: bytes = field(repr=False)
    fingerprint_version: int
    fingerprint_root_key_version: int
    expected_claim_generation: int
    root_key_version: int
    crypto_version: int = ACCOUNT_CRYPTO_VERSION
    aad_version: int = ACCOUNT_AAD_VERSION

    def __post_init__(self) -> None:
        try:
            for value in (
                self.crypto_context_uuid,
                self.tenant_uuid,
                self.provider_account_uuid,
                self.integration_uuid,
                self.provider_account_claim_uuid,
            ):
                UUID(value)
        except (ValueError, TypeError, AttributeError):
            raise ProviderAccountCredentialInputError() from None
        if (
            self.provider != "sf"
            or self.account_secret_schema_version != ACCOUNT_SECRET_SCHEMA_VERSION
            or self.account_secret_bundle_version != ACCOUNT_SECRET_BUNDLE_VERSION
            or self.fingerprint_version != 1
            or not _positive(self.revision_no)
            or not _positive(self.fingerprint_root_key_version)
            or not _positive(self.expected_claim_generation)
            or not _positive(self.root_key_version)
            or self.crypto_version != ACCOUNT_CRYPTO_VERSION
            or self.aad_version != ACCOUNT_AAD_VERSION
            or not isinstance(self.canonical_semantics_digest, bytes)
            or len(self.canonical_semantics_digest) != 32
            or not isinstance(self.account_fingerprint, bytes)
            or len(self.account_fingerprint) != 32
        ):
            raise ProviderAccountCredentialInputError()

    @property
    def purpose(self) -> str:
        return "inventory-manager/tenant-provider-account/sf/v1"

    def canonical_aad(self) -> bytes:
        return CryptoCodecV1.encode_parts(
            CryptoCodecV1.domain(
                "inventory-manager/tenant-provider-account/aad/v1"
            ),
            CryptoCodecV1.uuid_bytes(self.crypto_context_uuid),
            CryptoCodecV1.uuid_bytes(self.tenant_uuid),
            CryptoCodecV1.ascii_text(self.provider),
            CryptoCodecV1.uuid_bytes(self.provider_account_uuid),
            CryptoCodecV1.uuid_bytes(self.integration_uuid),
            CryptoCodecV1.uint64(self.revision_no),
            CryptoCodecV1.uint64(self.account_secret_schema_version),
            CryptoCodecV1.uint64(self.account_secret_bundle_version),
            self.canonical_semantics_digest,
            CryptoCodecV1.uuid_bytes(self.provider_account_claim_uuid),
            self.account_fingerprint,
            CryptoCodecV1.uint64(self.fingerprint_version),
            CryptoCodecV1.uint64(self.fingerprint_root_key_version),
            CryptoCodecV1.uint64(self.expected_claim_generation),
            CryptoCodecV1.uint64(self.root_key_version),
            CryptoCodecV1.uint64(self.crypto_version),
            CryptoCodecV1.uint64(self.aad_version),
        )


def canonicalize_sf_account_secret(value: str) -> CanonicalSfAccountSecret:
    """Apply the v1 identity normalization without trimming leading zeroes."""

    return CanonicalSfAccountSecret(value)


def validate_account_fingerprint(
    *,
    context: ProviderAccountSecretCryptoContext,
    fingerprint: ProviderAccountFingerprint,
) -> None:
    """Fail closed when the claim fingerprint and envelope context diverge."""

    if (
        not isinstance(context, ProviderAccountSecretCryptoContext)
        or not isinstance(fingerprint, ProviderAccountFingerprint)
        or fingerprint.provider != context.provider
        or fingerprint.fingerprint_version != context.fingerprint_version
        or fingerprint.root_key_version != context.fingerprint_root_key_version
        or not hmac.compare_digest(fingerprint.digest, context.account_fingerprint)
    ):
        raise ProviderAccountCredentialInputError()


def encrypt_provider_account_secret(
    *,
    root_key: RootKey,
    context: ProviderAccountSecretCryptoContext,
    secret: CanonicalSfAccountSecret,
) -> EncryptedEnvelope:
    if (
        not isinstance(root_key, RootKey)
        or not isinstance(context, ProviderAccountSecretCryptoContext)
        or not isinstance(secret, CanonicalSfAccountSecret)
        or root_key.version != context.root_key_version
        or not hmac.compare_digest(
            secret.canonical_semantics_digest,
            context.canonical_semantics_digest,
        )
    ):
        raise ProviderAccountCredentialInputError()
    try:
        return encrypt_record(
            root_key=root_key,
            purpose=context.purpose,
            record_uuid=context.crypto_context_uuid,
            revision=context.revision_no,
            canonical_aad=context.canonical_aad(),
            plaintext=secret._canonical_bytes(),
            crypto_version=context.crypto_version,
            aad_version=context.aad_version,
        )
    except CryptoError:
        raise ProviderAccountCredentialInputError() from None


def decrypt_provider_account_secret(
    *,
    root_key: RootKey,
    context: ProviderAccountSecretCryptoContext,
    envelope: EncryptedEnvelope,
) -> CanonicalSfAccountSecret:
    if (
        not isinstance(root_key, RootKey)
        or not isinstance(context, ProviderAccountSecretCryptoContext)
        or not isinstance(envelope, EncryptedEnvelope)
        or envelope.root_key_version != context.root_key_version
        or envelope.crypto_version != context.crypto_version
        or envelope.aad_version != context.aad_version
    ):
        raise ProviderAccountCredentialAuthenticationError()
    try:
        plaintext = decrypt_record(
            root_key=root_key,
            envelope=envelope,
            purpose=context.purpose,
            record_uuid=context.crypto_context_uuid,
            revision=context.revision_no,
            canonical_aad=context.canonical_aad(),
        )
        secret = CanonicalSfAccountSecret(plaintext.decode("ascii"))
        if (
            secret._canonical_bytes() != plaintext
            or not hmac.compare_digest(
                secret.canonical_semantics_digest,
                context.canonical_semantics_digest,
            )
        ):
            raise ValueError
        return secret
    except (
        CryptoError,
        ProviderAccountCredentialInputError,
        UnicodeError,
        ValueError,
        TypeError,
    ):
        raise ProviderAccountCredentialAuthenticationError() from None


def _positive(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1
