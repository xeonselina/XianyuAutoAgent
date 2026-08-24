from datetime import datetime
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest
import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError

from app.models.database_identity import TenantDatabaseIdentity

from app.tenancy import (
    SqlAlchemyDatabaseIdentityReader,
    TenancyError,
    TenancyErrorCode,
)


def identity_table(metadata, with_singleton=True):
    constraints = []
    if with_singleton:
        constraints.append(sa.CheckConstraint("singleton_key = 1"))
    return sa.Table(
        "database_identity",
        metadata,
        sa.Column("singleton_key", sa.SmallInteger, primary_key=with_singleton),
        sa.Column("tenant_id", sa.String(36), nullable=False),
        sa.Column("database_uuid", sa.String(36), nullable=False),
        sa.Column("created_at", sa.DateTime, nullable=False),
        sa.Column("schema_generation", sa.BigInteger, nullable=False),
        *constraints,
    )


def test_sqlalchemy_reader_uses_current_database_and_returns_one_identity(
    mysql_routed_database,
):
    engine = mysql_routed_database.engine
    table = TenantDatabaseIdentity.__table__
    tenant_id = uuid4()
    database_uuid = uuid4()
    created_at = datetime(2026, 8, 22, 12, 0, 0)

    with engine.begin() as connection:
        connection.execute(
            table.insert().values(
                singleton_key=1,
                tenant_id=str(tenant_id),
                database_uuid=str(database_uuid),
                created_at=created_at,
                schema_generation=3,
            )
        )
        observed = SqlAlchemyDatabaseIdentityReader().read_exactly_one(connection)

    assert observed.tenant_id == tenant_id
    assert observed.database_uuid == database_uuid
    assert observed.created_at == created_at
    assert observed.schema_generation == 3


def test_sqlalchemy_reader_fails_closed_when_identity_table_is_missing():
    connection = Mock()
    connection.execute.side_effect = SQLAlchemyError()

    with pytest.raises(TenancyError) as caught:
        SqlAlchemyDatabaseIdentityReader().read_exactly_one(connection)

    assert caught.value.code == TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE.value


def test_sqlalchemy_reader_rejects_zero_or_multiple_rows():
    reader = SqlAlchemyDatabaseIdentityReader()
    connection = Mock()
    result = Mock()
    connection.execute.return_value = result

    result.all.return_value = []
    with pytest.raises(TenancyError) as missing:
        reader.read_exactly_one(connection)
    result.all.return_value = [
        SimpleNamespace(
            tenant_id=str(uuid4()),
            database_uuid=str(uuid4()),
            created_at=datetime(2026, 8, 22, 12, 0, 0),
            schema_generation=1,
        ),
        SimpleNamespace(
            tenant_id=str(uuid4()),
            database_uuid=str(uuid4()),
            created_at=datetime(2026, 8, 22, 12, 0, 0),
            schema_generation=1,
        ),
    ]
    with pytest.raises(TenancyError) as duplicate:
        reader.read_exactly_one(connection)

    assert missing.value.code == TenancyErrorCode.DATABASE_IDENTITY_MISSING.value
    assert duplicate.value.code == TenancyErrorCode.DATABASE_IDENTITY_CARDINALITY.value


def test_sqlalchemy_reader_rejects_malformed_identity_without_echoing_values(
    mysql_routed_database,
):
    engine = mysql_routed_database.engine
    table = TenantDatabaseIdentity.__table__
    sensitive_value = "not-a-uuid-private-schema"

    with engine.begin() as connection:
        connection.execute(
            table.insert().values(
                singleton_key=1,
                tenant_id=sensitive_value,
                database_uuid=str(uuid4()),
                created_at=datetime(2026, 8, 22, 12, 0, 0),
                schema_generation=1,
            )
        )
        with pytest.raises(TenancyError) as caught:
            SqlAlchemyDatabaseIdentityReader().read_exactly_one(connection)

    assert caught.value.code == TenancyErrorCode.DATABASE_IDENTITY_MISMATCH.value
    assert sensitive_value not in str(caught.value)
