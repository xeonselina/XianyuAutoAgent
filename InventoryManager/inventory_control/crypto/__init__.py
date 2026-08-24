"""Versioned control-plane cryptographic primitives."""

from .codec import CryptoCodecV1
from .envelope import EncryptedEnvelope, decrypt_record, encrypt_record
from .errors import (
    CryptoAuthenticationError,
    CryptoConfigurationError,
    CryptoError,
    RootKeyLoadError,
)
from .keyring import (
    RootKeyLifecycle,
    RootKeyRing,
    RootKeyVersionFact,
    load_root_key_ring,
)
from .lifecycle import (
    RootKeyLifecycleConflictError,
    RootKeyLifecycleError,
    RootKeyLifecycleResult,
    RootKeyLifecycleTransactionError,
    RootKeyReferenceCount,
    RootKeyReferenceError,
    RootKeyReferenceInventory,
    SqlAlchemyRootKeyLifecycleService,
)
from .passwords import (
    DatabaseAccountKind,
    derive_database_password,
    derive_platform_read_password,
    derive_tenant_dml_password,
)
from .platform_auth import (
    PLATFORM_AUTH_SUBJECT_DIGEST_VERSION,
    derive_platform_auth_subject_digest,
)
from .provider_accounts import (
    ProviderAccountFingerprint,
    derive_provider_account_fingerprint,
)
from .registry import (
    RootKeyRegistryError,
    RootKeyRegistryTransactionError,
    SqlAlchemyRootKeyRegistry,
)
from .root_key import RootKey, load_root_key, root_key_fingerprint_sha256

__all__ = [
    "CryptoAuthenticationError",
    "CryptoCodecV1",
    "CryptoConfigurationError",
    "CryptoError",
    "DatabaseAccountKind",
    "EncryptedEnvelope",
    "RootKey",
    "RootKeyLifecycle",
    "RootKeyLifecycleConflictError",
    "RootKeyLifecycleError",
    "RootKeyLifecycleResult",
    "RootKeyLifecycleTransactionError",
    "RootKeyLoadError",
    "RootKeyRegistryError",
    "RootKeyRegistryTransactionError",
    "RootKeyRing",
    "RootKeyVersionFact",
    "RootKeyReferenceCount",
    "RootKeyReferenceError",
    "RootKeyReferenceInventory",
    "SqlAlchemyRootKeyRegistry",
    "SqlAlchemyRootKeyLifecycleService",
    "ProviderAccountFingerprint",
    "PLATFORM_AUTH_SUBJECT_DIGEST_VERSION",
    "decrypt_record",
    "derive_database_password",
    "derive_platform_read_password",
    "derive_platform_auth_subject_digest",
    "derive_provider_account_fingerprint",
    "derive_tenant_dml_password",
    "encrypt_record",
    "load_root_key",
    "load_root_key_ring",
    "root_key_fingerprint_sha256",
]
