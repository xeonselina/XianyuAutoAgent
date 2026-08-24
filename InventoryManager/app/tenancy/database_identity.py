"""Pure contracts for verifying immutable tenant database identity."""

from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from typing import Iterable, Protocol, TypeVar, runtime_checkable
from uuid import UUID

from .errors import TenancyError, TenancyErrorCode


def _require_uuid(field_name: str, value: object) -> None:
    if not isinstance(value, UUID):
        raise TypeError(f"{field_name} must be a UUID")
    if value.int == 0:
        raise ValueError(f"{field_name} must not be the nil UUID")


def _require_generation(value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("schema_generation must be an integer")
    if value < 1:
        raise ValueError("schema_generation must be positive")


@dataclass(frozen=True, slots=True)
class DatabaseIdentity:
    """The single immutable identity record observed in a tenant database."""

    tenant_id: UUID
    database_uuid: UUID
    created_at: datetime
    schema_generation: int

    def __post_init__(self) -> None:
        _require_uuid("tenant_id", self.tenant_id)
        _require_uuid("database_uuid", self.database_uuid)
        if not isinstance(self.created_at, datetime):
            raise TypeError("created_at must be a datetime")
        _require_generation(self.schema_generation)


@dataclass(frozen=True, slots=True)
class ExpectedDatabaseIdentity:
    """Trusted control-plane identity expected for a resolved route."""

    tenant_id: UUID
    database_uuid: UUID
    schema_generation: int

    def __post_init__(self) -> None:
        _require_uuid("tenant_id", self.tenant_id)
        _require_uuid("database_uuid", self.database_uuid)
        _require_generation(self.schema_generation)


ConnectionT_contra = TypeVar("ConnectionT_contra", contravariant=True)


@runtime_checkable
class DatabaseIdentityReader(Protocol[ConnectionT_contra]):
    """Reads exactly one identity through an adapter-owned connection.

    Concrete adapters are responsible for issuing a fixed query and converting
    its rows before using :func:`require_exactly_one_database_identity`.  They
    must not accept a schema or query supplied by request data.
    """

    def read_exactly_one(self, connection: ConnectionT_contra) -> DatabaseIdentity:
        """Return one identity or raise a fixed ``TenancyError``."""

        ...


def require_exactly_one_database_identity(
    identities: Iterable[DatabaseIdentity],
) -> DatabaseIdentity:
    """Select exactly one identity from an adapter-provided iterable.

    At most two items are consumed, so an accidentally unbounded source is not
    materialized.  Missing and duplicate records fail closed with distinct
    stable codes and fixed non-sensitive messages.
    """

    iterator = iter(identities)
    selected = tuple(islice(iterator, 2))
    if not selected:
        raise TenancyError(TenancyErrorCode.DATABASE_IDENTITY_MISSING)
    if len(selected) != 1:
        raise TenancyError(TenancyErrorCode.DATABASE_IDENTITY_CARDINALITY)

    identity = selected[0]
    if not isinstance(identity, DatabaseIdentity):
        raise TenancyError(TenancyErrorCode.DATABASE_IDENTITY_MISMATCH)
    return identity


def verify_database_identity(
    expected: ExpectedDatabaseIdentity,
    observed: DatabaseIdentity,
) -> None:
    """Fail closed unless the observed immutable identity matches exactly."""

    if not isinstance(expected, ExpectedDatabaseIdentity) or not isinstance(
        observed, DatabaseIdentity
    ):
        raise TenancyError(TenancyErrorCode.DATABASE_IDENTITY_MISMATCH)

    if (
        observed.tenant_id != expected.tenant_id
        or observed.database_uuid != expected.database_uuid
        or observed.schema_generation != expected.schema_generation
    ):
        raise TenancyError(TenancyErrorCode.DATABASE_IDENTITY_MISMATCH)
