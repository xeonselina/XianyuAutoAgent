"""Purpose-separated deterministic tenant database password derivation."""

from __future__ import annotations

import base64
from enum import Enum

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .codec import CryptoCodecV1, UuidValue
from .errors import CryptoConfigurationError
from .root_key import RootKey

_DERIVATION_VERSION = 1
_PASSWORD_BYTES = 32


class DatabaseAccountKind(str, Enum):
    TENANT_DML = "tenant_dml"
    PLATFORM_READ = "platform_read"


_PASSWORD_DOMAINS = {
    DatabaseAccountKind.TENANT_DML: "inventory-manager/tenant-db-password/v1",
    DatabaseAccountKind.PLATFORM_READ: (
        "inventory-manager/platform-read-db-password/v1"
    ),
}


def derive_database_password(
    *,
    root_key: RootKey,
    account_kind: DatabaseAccountKind,
    tenant_uuid: UuidValue,
    database_uuid: UuidValue,
    account_username: str,
    credential_generation: int,
    derivation_version: int = _DERIVATION_VERSION,
) -> str:
    """Derive a 32-byte database password and return unpadded Base64URL text."""

    if not isinstance(root_key, RootKey):
        raise CryptoConfigurationError("root key is invalid")
    try:
        kind = DatabaseAccountKind(account_kind)
    except (TypeError, ValueError):
        raise CryptoConfigurationError("database account kind is unsupported") from None
    if derivation_version != _DERIVATION_VERSION:
        raise CryptoConfigurationError("password derivation version is unsupported")

    tenant_bytes = CryptoCodecV1.uuid_bytes(tenant_uuid)
    database_bytes = CryptoCodecV1.uuid_bytes(database_uuid)
    info = CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain(_PASSWORD_DOMAINS[kind]),
        tenant_bytes,
        database_bytes,
        CryptoCodecV1.ascii_text(account_username),
        CryptoCodecV1.uint64(credential_generation),
        CryptoCodecV1.uint64(root_key.version),
        CryptoCodecV1.uint64(derivation_version),
    )
    derived = HKDF(
        algorithm=hashes.SHA256(),
        length=_PASSWORD_BYTES,
        salt=database_bytes,
        info=info,
    ).derive(root_key._material_bytes())
    return base64.urlsafe_b64encode(derived).rstrip(b"=").decode("ascii")


def derive_tenant_dml_password(
    *,
    root_key: RootKey,
    tenant_uuid: UuidValue,
    database_uuid: UuidValue,
    account_username: str,
    credential_generation: int,
    derivation_version: int = _DERIVATION_VERSION,
) -> str:
    return derive_database_password(
        root_key=root_key,
        account_kind=DatabaseAccountKind.TENANT_DML,
        tenant_uuid=tenant_uuid,
        database_uuid=database_uuid,
        account_username=account_username,
        credential_generation=credential_generation,
        derivation_version=derivation_version,
    )


def derive_platform_read_password(
    *,
    root_key: RootKey,
    tenant_uuid: UuidValue,
    database_uuid: UuidValue,
    account_username: str,
    credential_generation: int,
    derivation_version: int = _DERIVATION_VERSION,
) -> str:
    return derive_database_password(
        root_key=root_key,
        account_kind=DatabaseAccountKind.PLATFORM_READ,
        tenant_uuid=tenant_uuid,
        database_uuid=database_uuid,
        account_username=account_username,
        credential_generation=credential_generation,
        derivation_version=derivation_version,
    )
