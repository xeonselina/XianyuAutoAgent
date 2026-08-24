"""Stable, non-sensitive errors for tenant routing boundaries."""

from enum import Enum
from typing import Dict


class TenancyErrorCode(str, Enum):
    """Machine-readable failures shared by tenancy adapters."""

    TENANT_CONTEXT_REQUIRED = "TENANT_CONTEXT_REQUIRED"
    UNTRUSTED_TENANT_SELECTOR = "UNTRUSTED_TENANT_SELECTOR"
    TENANT_ROUTE_UNAVAILABLE = "TENANT_ROUTE_UNAVAILABLE"
    DATABASE_IDENTITY_MISSING = "DATABASE_IDENTITY_MISSING"
    DATABASE_IDENTITY_CARDINALITY = "DATABASE_IDENTITY_CARDINALITY"
    DATABASE_IDENTITY_MISMATCH = "DATABASE_IDENTITY_MISMATCH"
    STALE_TENANT_ACCESS_VERSION = "STALE_TENANT_ACCESS_VERSION"


_PUBLIC_MESSAGES: Dict[TenancyErrorCode, str] = {
    TenancyErrorCode.TENANT_CONTEXT_REQUIRED: (
        "A trusted tenant context is required."
    ),
    TenancyErrorCode.UNTRUSTED_TENANT_SELECTOR: (
        "The tenant selector is not trusted."
    ),
    TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE: (
        "The tenant route is unavailable."
    ),
    TenancyErrorCode.DATABASE_IDENTITY_MISSING: (
        "The database identity record is missing."
    ),
    TenancyErrorCode.DATABASE_IDENTITY_CARDINALITY: (
        "The database identity record is invalid."
    ),
    TenancyErrorCode.DATABASE_IDENTITY_MISMATCH: (
        "The database identity could not be verified."
    ),
    TenancyErrorCode.STALE_TENANT_ACCESS_VERSION: (
        "The tenant access version is stale."
    ),
}


class TenancyError(RuntimeError):
    """A fail-closed tenancy error with fixed public output.

    The constructor intentionally accepts no free-form message or diagnostic
    values.  Adapters may attach private diagnostics to structured security
    telemetry, but schema names, connection details, and compared identities
    must never be added to this exception.
    """

    __slots__ = ("_code", "_public_message")

    def __init__(self, code: TenancyErrorCode) -> None:
        if not isinstance(code, TenancyErrorCode):
            raise TypeError("code must be a TenancyErrorCode")

        public_message = _PUBLIC_MESSAGES[code]
        self._code = code.value
        self._public_message = public_message
        super().__init__(public_message)

    @property
    def code(self) -> str:
        """Return the stable machine-readable code."""

        return self._code

    @property
    def public_message(self) -> str:
        """Return the fixed, non-sensitive client-safe message."""

        return self._public_message
