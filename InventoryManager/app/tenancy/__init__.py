"""Trusted tenancy contracts without Flask or ORM wiring."""

from .context import (
    PlatformTenantReadContext,
    TenantContext,
    TenantContextProvider,
    TenantContextSource,
)
from .database_identity import (
    DatabaseIdentity,
    DatabaseIdentityReader,
    ExpectedDatabaseIdentity,
    require_exactly_one_database_identity,
    verify_database_identity,
)
from .errors import TenancyError, TenancyErrorCode
from .sqlalchemy_identity import SqlAlchemyDatabaseIdentityReader

__all__ = [
    "DatabaseIdentity",
    "DatabaseIdentityReader",
    "ExpectedDatabaseIdentity",
    "PlatformTenantReadContext",
    "TenantContext",
    "TenantContextProvider",
    "TenantContextSource",
    "TenancyError",
    "TenancyErrorCode",
    "SqlAlchemyDatabaseIdentityReader",
    "require_exactly_one_database_identity",
    "verify_database_identity",
]
