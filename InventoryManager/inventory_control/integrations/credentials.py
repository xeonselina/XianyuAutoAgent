"""Canonical provider bundles and purpose-separated encrypted envelopes.

The bundle object is deliberately not a response DTO.  Its representation is
redacted and callers should only receive one inside the short-lived callback
used by :class:`TenantIntegrationService`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Mapping
from uuid import UUID

from inventory_control.crypto import (
    CryptoCodecV1,
    CryptoError,
    EncryptedEnvelope,
    RootKey,
    decrypt_record,
    encrypt_record,
)

from .errors import (
    IntegrationCredentialAuthenticationError,
    IntegrationInputError,
)


CREDENTIAL_SCHEMA_VERSION = 1
CREDENTIAL_BUNDLE_VERSION = 1
CRYPTO_VERSION = 1
AAD_VERSION = 1

_PROVIDER_KEYS = MappingProxyType(
    {
        "sf": frozenset(("partner_id", "checkword")),
        "xianyu": frozenset(("app_key", "app_secret")),
        "kuaimai": frozenset(("app_id", "app_secret")),
    }
)
_MAX_CREDENTIAL_UTF8_BYTES = 4096


class CanonicalProviderCredentialBundle:
    """Validated credentials with stable bytes and an always-redacted repr."""

    __slots__ = ("provider", "schema_version", "bundle_version", "_values", "_bytes")

    def __init__(
        self,
        *,
        provider: str,
        values: Mapping[str, str],
        schema_version: int = CREDENTIAL_SCHEMA_VERSION,
        bundle_version: int = CREDENTIAL_BUNDLE_VERSION,
    ) -> None:
        normalized_provider = require_provider(provider)
        if schema_version != CREDENTIAL_SCHEMA_VERSION:
            raise IntegrationInputError()
        if bundle_version != CREDENTIAL_BUNDLE_VERSION:
            raise IntegrationInputError()
        if (
            not isinstance(values, Mapping)
            or set(values) != _PROVIDER_KEYS[normalized_provider]
        ):
            raise IntegrationInputError()

        copied: dict[str, str] = {}
        for key in sorted(values):
            value = values[key]
            if not isinstance(value, str) or not value:
                raise IntegrationInputError()
            try:
                encoded = value.encode("utf-8")
            except UnicodeEncodeError:
                raise IntegrationInputError() from None
            if (
                len(encoded) > _MAX_CREDENTIAL_UTF8_BYTES
                or any(
                    ord(character) < 0x20 or ord(character) == 0x7F
                    for character in value
                )
            ):
                raise IntegrationInputError()
            copied[key] = value

        canonical = json.dumps(
            copied,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
        self.provider = normalized_provider
        self.schema_version = schema_version
        self.bundle_version = bundle_version
        self._values = MappingProxyType(copied)
        self._bytes = canonical

    def __repr__(self) -> str:
        return (
            "CanonicalProviderCredentialBundle("
            f"provider={self.provider!r}, schema_version={self.schema_version}, "
            f"bundle_version={self.bundle_version}, credentials=<redacted>)"
        )

    @property
    def canonical_semantics_digest(self) -> bytes:
        return hashlib.sha256(self._bytes).digest()

    def _canonical_bytes(self) -> bytes:
        return bytes(self._bytes)

    def _provider_values(self) -> Mapping[str, str]:
        """Internal bridge for the immediately invoked provider callback."""

        return self._values


@dataclass(frozen=True, slots=True)
class IntegrationSecretCryptoContext:
    """Immutable facts authenticated by one encrypted business revision."""

    crypto_context_uuid: str
    tenant_uuid: str
    provider: str
    integration_uuid: str
    revision_no: int
    credential_schema_version: int
    credential_bundle_version: int
    canonical_semantics_digest: bytes = field(repr=False)
    root_key_version: int
    crypto_version: int = CRYPTO_VERSION
    aad_version: int = AAD_VERSION

    def __post_init__(self) -> None:
        try:
            UUID(self.crypto_context_uuid)
            UUID(self.tenant_uuid)
            UUID(self.integration_uuid)
        except (ValueError, TypeError, AttributeError):
            raise IntegrationInputError() from None
        require_provider(self.provider)
        if (
            isinstance(self.revision_no, bool)
            or not isinstance(self.revision_no, int)
            or self.revision_no < 1
            or self.credential_schema_version != CREDENTIAL_SCHEMA_VERSION
            or self.credential_bundle_version != CREDENTIAL_BUNDLE_VERSION
            or self.crypto_version != CRYPTO_VERSION
            or self.aad_version != AAD_VERSION
            or isinstance(self.root_key_version, bool)
            or not isinstance(self.root_key_version, int)
            or self.root_key_version < 1
            or not isinstance(self.canonical_semantics_digest, bytes)
            or len(self.canonical_semantics_digest) != 32
        ):
            raise IntegrationInputError()

    @property
    def purpose(self) -> str:
        return f"inventory-manager/tenant-integration/{self.provider}/v1"

    def canonical_aad(self) -> bytes:
        return CryptoCodecV1.encode_parts(
            CryptoCodecV1.domain("inventory-manager/tenant-integration/aad/v1"),
            CryptoCodecV1.uuid_bytes(self.crypto_context_uuid),
            CryptoCodecV1.uuid_bytes(self.tenant_uuid),
            CryptoCodecV1.ascii_text(self.provider),
            CryptoCodecV1.uuid_bytes(self.integration_uuid),
            CryptoCodecV1.uint64(self.revision_no),
            CryptoCodecV1.uint64(self.credential_schema_version),
            CryptoCodecV1.uint64(self.credential_bundle_version),
            self.canonical_semantics_digest,
            CryptoCodecV1.uint64(self.root_key_version),
            CryptoCodecV1.uint64(self.crypto_version),
            CryptoCodecV1.uint64(self.aad_version),
        )


def canonicalize_provider_credentials(
    provider: str,
    credentials: Mapping[str, str],
) -> CanonicalProviderCredentialBundle:
    return CanonicalProviderCredentialBundle(provider=provider, values=credentials)


def encrypt_provider_credentials(
    *,
    root_key: RootKey,
    context: IntegrationSecretCryptoContext,
    bundle: CanonicalProviderCredentialBundle,
) -> EncryptedEnvelope:
    if not isinstance(root_key, RootKey) or not isinstance(
        context, IntegrationSecretCryptoContext
    ) or not isinstance(bundle, CanonicalProviderCredentialBundle):
        raise IntegrationInputError()
    if (
        root_key.version != context.root_key_version
        or bundle.provider != context.provider
        or bundle.schema_version != context.credential_schema_version
        or bundle.bundle_version != context.credential_bundle_version
        or not hmac.compare_digest(
            bundle.canonical_semantics_digest,
            context.canonical_semantics_digest,
        )
    ):
        raise IntegrationInputError()
    try:
        return encrypt_record(
            root_key=root_key,
            purpose=context.purpose,
            record_uuid=context.crypto_context_uuid,
            revision=context.revision_no,
            canonical_aad=context.canonical_aad(),
            plaintext=bundle._canonical_bytes(),
            crypto_version=context.crypto_version,
            aad_version=context.aad_version,
        )
    except CryptoError:
        raise IntegrationInputError() from None


def decrypt_provider_credentials(
    *,
    root_key: RootKey,
    context: IntegrationSecretCryptoContext,
    envelope: EncryptedEnvelope,
) -> CanonicalProviderCredentialBundle:
    """Authenticate, parse, and re-canonicalize without exposing failure detail."""

    if not isinstance(root_key, RootKey) or not isinstance(
        context, IntegrationSecretCryptoContext
    ) or not isinstance(envelope, EncryptedEnvelope):
        raise IntegrationCredentialAuthenticationError()
    if (
        envelope.root_key_version != context.root_key_version
        or envelope.crypto_version != context.crypto_version
        or envelope.aad_version != context.aad_version
    ):
        raise IntegrationCredentialAuthenticationError()
    try:
        plaintext = decrypt_record(
            root_key=root_key,
            envelope=envelope,
            purpose=context.purpose,
            record_uuid=context.crypto_context_uuid,
            revision=context.revision_no,
            canonical_aad=context.canonical_aad(),
        )
        parsed = json.loads(plaintext.decode("utf-8"))
        bundle = CanonicalProviderCredentialBundle(
            provider=context.provider,
            values=parsed,
            schema_version=context.credential_schema_version,
            bundle_version=context.credential_bundle_version,
        )
        if (
            bundle._canonical_bytes() != plaintext
            or not hmac.compare_digest(
                bundle.canonical_semantics_digest,
                context.canonical_semantics_digest,
            )
        ):
            raise ValueError
        return bundle
    except (CryptoError, IntegrationInputError, UnicodeError, ValueError, TypeError):
        raise IntegrationCredentialAuthenticationError() from None


def require_provider(value: str) -> str:
    if not isinstance(value, str) or value not in _PROVIDER_KEYS:
        raise IntegrationInputError()
    return value
