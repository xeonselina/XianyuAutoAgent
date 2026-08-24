"""Fixed-query SQLAlchemy adapter for tenant database identity."""

from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from .database_identity import (
    DatabaseIdentity,
    require_exactly_one_database_identity,
)
from .errors import TenancyError, TenancyErrorCode


_IDENTITY_METADATA = sa.MetaData()
_DATABASE_IDENTITY = sa.Table(
    "database_identity",
    _IDENTITY_METADATA,
    sa.Column("singleton_key", sa.SmallInteger, nullable=False),
    sa.Column("tenant_id", sa.String(36), nullable=False),
    sa.Column("database_uuid", sa.String(36), nullable=False),
    sa.Column("created_at", sa.DateTime, nullable=False),
    sa.Column("schema_generation", sa.BigInteger, nullable=False),
)


class SqlAlchemyDatabaseIdentityReader:
    """Read identity through a fixed unqualified query on the current engine."""

    def read_exactly_one(self, connection) -> DatabaseIdentity:
        try:
            rows = connection.execute(
                sa.select(
                    _DATABASE_IDENTITY.c.tenant_id,
                    _DATABASE_IDENTITY.c.database_uuid,
                    _DATABASE_IDENTITY.c.created_at,
                    _DATABASE_IDENTITY.c.schema_generation,
                ).limit(2)
            ).all()
        except SQLAlchemyError:
            raise TenancyError(TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE) from None

        identities = []
        for row in rows:
            try:
                identities.append(
                    DatabaseIdentity(
                        tenant_id=UUID(row.tenant_id),
                        database_uuid=UUID(row.database_uuid),
                        created_at=row.created_at,
                        schema_generation=row.schema_generation,
                    )
                )
            except (TypeError, ValueError, AttributeError):
                raise TenancyError(
                    TenancyErrorCode.DATABASE_IDENTITY_MISMATCH
                ) from None

        return require_exactly_one_database_identity(identities)
