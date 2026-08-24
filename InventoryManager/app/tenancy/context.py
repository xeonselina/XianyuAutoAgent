"""Trusted tenant-routing context contracts.

This module has no HTTP/request adapter by design.  Only a server-verified
session resolver or a claimed background job may construct and provide a
``TenantContext``.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable
from uuid import UUID


class TenantContextSource(str, Enum):
    """Server-controlled provenance for a tenant context."""

    WEB_SESSION = "web_session"
    WORKER_JOB = "worker_job"


def _require_uuid(field_name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be a UUID")
    if value.int == 0:
        raise ValueError(f"{field_name} must not be the nil UUID")


def _require_version(field_name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 1:
        raise ValueError(f"{field_name} must be positive")


def _require_reference(field_name: str, value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty canonical value")


@dataclass(frozen=True, slots=True)
class TenantContext:
    """Minimal trusted routing identity for one unit of work.

    No database name, URL, DSN, or client-supplied selector belongs in this
    value.  Authorization permissions remain in the separate authentication
    context; this contract carries only the identity and version needed by the
    future tenant router.
    """

    tenant_id: UUID
    access_version: int
    source: TenantContextSource
    principal_ref: str
    source_ref: str
    request_id: str

    def __post_init__(self) -> None:
        _require_uuid("tenant_id", self.tenant_id)
        _require_version("access_version", self.access_version)
        if not isinstance(self.source, TenantContextSource):
            raise TypeError("source must be a TenantContextSource")
        _require_reference("principal_ref", self.principal_ref)
        _require_reference("source_ref", self.source_ref)
        _require_reference("request_id", self.request_id)


@dataclass(frozen=True, slots=True)
class PlatformTenantReadContext:
    """Trusted platform selection for one tenant's read-only projection.

    This type is intentionally unrelated to :class:`TenantContext`.  It cannot
    be used to authorize tenant DML, worker work, provider calls, or
    impersonation.
    """

    target_tenant_id: UUID
    target_access_version: int
    platform_admin_id: UUID
    platform_session_id: UUID
    read_policy_version: int
    request_id: str

    def __post_init__(self) -> None:
        _require_uuid("target_tenant_id", self.target_tenant_id)
        _require_version("target_access_version", self.target_access_version)
        _require_uuid("platform_admin_id", self.platform_admin_id)
        _require_uuid("platform_session_id", self.platform_session_id)
        _require_version("read_policy_version", self.read_policy_version)
        _require_reference("request_id", self.request_id)


@runtime_checkable
class TenantContextProvider(Protocol):
    """Provides context already established by a trusted server adapter."""

    def require_current(self) -> TenantContext:
        """Return the current trusted context or fail closed."""

        ...
