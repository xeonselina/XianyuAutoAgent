"""Safe exception types for control-plane cryptographic operations."""


class CryptoError(Exception):
    """Base class for expected cryptographic failures."""


class CryptoConfigurationError(CryptoError):
    """Raised when versioned cryptographic metadata is invalid or unsupported."""


class RootKeyLoadError(CryptoConfigurationError):
    """Raised when a root key cannot be loaded safely."""


class CryptoAuthenticationError(CryptoError):
    """Raised when an authenticated envelope cannot be verified."""
