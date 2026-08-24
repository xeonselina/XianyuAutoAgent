"""Controlled, non-logging identity inputs for the default-tenant migration.

The migration needs the real display name and first Admin phone to create
control-plane rows, but neither value belongs in a manifest, journal, log, or
exception.  This module normalizes the values once and binds them to the
immutable tenant/database/migration identity with keyed commitments.
"""

from __future__ import annotations

import hashlib
import hmac
import re
import unicodedata
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Final, Mapping
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from inventory_control.crypto import CryptoCodecV1, RootKey
from inventory_control.identity import PhoneNormalizationError, normalize_tenant_phone


DEFAULT_TENANT_IDENTITY_INPUT_VERSION: Final[int] = 1
_COMMITMENT_PURPOSE: Final[str] = (
    "inventory-manager/default-tenant-identity-input-commitment/v1"
)
_KEY_PURPOSE: Final[str] = (
    "inventory-manager/default-tenant-identity-input-commitment-key/v1"
)
_SAFE_MIGRATION_KEY = re.compile(
    r"[A-Za-z0-9][A-Za-z0-9_.:/+-]{0,127}", re.ASCII
)
_PLACEHOLDER_KEYS: Final[frozenset[str]] = frozenset(
    {
        "default",
        "defaulttenant",
        "example",
        "exampletenant",
        "tenant",
        "test",
        "testtenant",
        "未命名",
        "默认",
        "默认租户",
        "测试",
        "测试租户",
        "示例",
        "示例租户",
    }
)


class DefaultTenantIdentityInputError(ValueError):
    """The controlled identity input is missing, ambiguous, or invalid."""

    def __init__(self) -> None:
        super().__init__("migration identity input rejected")


@dataclass(frozen=True, slots=True, repr=False)
class DefaultTenantIdentityInputs:
    """Normalized plaintext held only by the short-lived migration caller."""

    display_name: str = field(repr=False)
    first_admin_phone_e164: str = field(repr=False)
    display_name_commitment: bytes = field(repr=False)
    first_admin_phone_commitment: bytes = field(repr=False)
    commitment_root_key_version: int
    input_version: int = DEFAULT_TENANT_IDENTITY_INPUT_VERSION

    def __post_init__(self) -> None:
        if self.input_version != DEFAULT_TENANT_IDENTITY_INPUT_VERSION:
            raise DefaultTenantIdentityInputError()
        if (
            isinstance(self.commitment_root_key_version, bool)
            or not isinstance(self.commitment_root_key_version, int)
            or self.commitment_root_key_version < 1
        ):
            raise DefaultTenantIdentityInputError()
        if not isinstance(self.display_name, str) or not isinstance(
            self.first_admin_phone_e164, str
        ):
            raise DefaultTenantIdentityInputError()
        for value in (
            self.display_name_commitment,
            self.first_admin_phone_commitment,
        ):
            if not isinstance(value, bytes) or len(value) != 32:
                raise DefaultTenantIdentityInputError()

    def redacted_summary(self) -> Mapping[str, object]:
        return MappingProxyType(
            {
                "input_version": self.input_version,
                "commitment_root_key_version": self.commitment_root_key_version,
                "display_name_bound": True,
                "first_admin_phone_bound": True,
            }
        )

    def __repr__(self) -> str:
        return (
            "DefaultTenantIdentityInputs("
            f"input_version={self.input_version}, "
            f"commitment_root_key_version={self.commitment_root_key_version}, "
            "redacted=True)"
        )


def bind_default_tenant_identity_inputs(
    *,
    root_key: RootKey,
    tenant_uuid: UUID,
    database_uuid: UUID,
    migration_idempotency_key: str,
    display_name: object,
    first_admin_phone: object,
) -> DefaultTenantIdentityInputs:
    """Normalize two mandatory inputs and produce context-bound commitments."""

    if not isinstance(root_key, RootKey):
        raise DefaultTenantIdentityInputError()
    if (
        not isinstance(tenant_uuid, UUID)
        or not isinstance(database_uuid, UUID)
        or tenant_uuid == database_uuid
        or not isinstance(migration_idempotency_key, str)
        or _SAFE_MIGRATION_KEY.fullmatch(migration_idempotency_key) is None
    ):
        raise DefaultTenantIdentityInputError()

    normalized_name = _normalize_display_name(display_name)
    try:
        normalized_phone = normalize_tenant_phone(first_admin_phone)
    except (PhoneNormalizationError, TypeError):
        raise DefaultTenantIdentityInputError() from None

    context = CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain(_KEY_PURPOSE),
        CryptoCodecV1.uuid_bytes(tenant_uuid),
        CryptoCodecV1.uuid_bytes(database_uuid),
        CryptoCodecV1.ascii_text(migration_idempotency_key),
        CryptoCodecV1.uint64(root_key.version),
        CryptoCodecV1.uint64(DEFAULT_TENANT_IDENTITY_INPUT_VERSION),
    )
    commitment_key = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=hashlib.sha256(context).digest(),
        info=context,
    ).derive(root_key._material_bytes())

    return DefaultTenantIdentityInputs(
        display_name=normalized_name,
        first_admin_phone_e164=normalized_phone,
        display_name_commitment=_commit(
            commitment_key,
            field_name="display_name",
            normalized_value=normalized_name,
        ),
        first_admin_phone_commitment=_commit(
            commitment_key,
            field_name="first_admin_phone_e164",
            normalized_value=normalized_phone,
        ),
        commitment_root_key_version=root_key.version,
    )


def require_default_tenant_identity_inputs_match(
    manifest: object,
    inputs: DefaultTenantIdentityInputs,
) -> None:
    """Fail before writes when a retry supplies different controlled inputs."""

    # Local import keeps manifest construction independent from the input
    # binding helper while still requiring the exact public manifest type.
    from .manifest import DefaultTenantMigrationManifest

    if (
        not isinstance(manifest, DefaultTenantMigrationManifest)
        or not isinstance(inputs, DefaultTenantIdentityInputs)
        or not hmac.compare_digest(
            manifest.display_name_input_commitment,
            inputs.display_name_commitment,
        )
        or not hmac.compare_digest(
            manifest.first_admin_phone_input_commitment,
            inputs.first_admin_phone_commitment,
        )
    ):
        raise DefaultTenantIdentityInputError()


def _normalize_display_name(value: object) -> str:
    if not isinstance(value, str):
        raise DefaultTenantIdentityInputError()
    normalized = unicodedata.normalize("NFC", " ".join(value.split()))
    if not normalized or len(normalized) > 120:
        raise DefaultTenantIdentityInputError()
    if any(unicodedata.category(character).startswith("C") for character in normalized):
        raise DefaultTenantIdentityInputError()
    placeholder_key = "".join(
        character
        for character in unicodedata.normalize("NFKC", normalized).casefold()
        if character.isalnum()
    )
    if not placeholder_key or placeholder_key in _PLACEHOLDER_KEYS:
        raise DefaultTenantIdentityInputError()
    return normalized


def _commit(key: bytes, *, field_name: str, normalized_value: str) -> bytes:
    payload = CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain(_COMMITMENT_PURPOSE),
        CryptoCodecV1.ascii_text(field_name),
        normalized_value.encode("utf-8"),
        CryptoCodecV1.uint64(DEFAULT_TENANT_IDENTITY_INPUT_VERSION),
    )
    return hmac.digest(key, payload, "sha256")
