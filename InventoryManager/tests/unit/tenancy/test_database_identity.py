from dataclasses import FrozenInstanceError, fields
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest

from app.tenancy.database_identity import (
    DatabaseIdentity,
    DatabaseIdentityReader,
    ExpectedDatabaseIdentity,
    require_exactly_one_database_identity,
    verify_database_identity,
)
from app.tenancy.errors import TenancyError, TenancyErrorCode


TENANT_ID = UUID("252c1aea-53a4-4f80-a092-e42ba2153147")
DATABASE_ID = UUID("16779a37-8fd5-40a4-8611-f9de2aa04d5e")
CREATED_AT = datetime(2026, 8, 22, 10, 30, tzinfo=timezone.utc)


def make_observed(**overrides):
    values = {
        "tenant_id": TENANT_ID,
        "database_uuid": DATABASE_ID,
        "created_at": CREATED_AT,
        "schema_generation": 7,
    }
    values.update(overrides)
    return DatabaseIdentity(**values)


def make_expected(**overrides):
    values = {
        "tenant_id": TENANT_ID,
        "database_uuid": DATABASE_ID,
        "schema_generation": 7,
    }
    values.update(overrides)
    return ExpectedDatabaseIdentity(**values)


def test_database_identity_contracts_are_immutable_and_exclude_route_secrets():
    observed = make_observed()
    expected = make_expected()

    assert {field.name for field in fields(observed)} == {
        "tenant_id",
        "database_uuid",
        "created_at",
        "schema_generation",
    }
    assert {field.name for field in fields(expected)} == {
        "tenant_id",
        "database_uuid",
        "schema_generation",
    }
    for forbidden_field in ("database_name", "schema", "dsn", "username", "password"):
        assert not hasattr(observed, forbidden_field)
        assert not hasattr(expected, forbidden_field)

    with pytest.raises(FrozenInstanceError):
        observed.schema_generation = 8


def test_exactly_one_reader_helper_returns_the_only_identity():
    observed = make_observed()

    assert require_exactly_one_database_identity(item for item in [observed]) is observed


@pytest.mark.parametrize(
    ("identities", "expected_code"),
    [
        ([], TenancyErrorCode.DATABASE_IDENTITY_MISSING),
        (
            [make_observed(), make_observed()],
            TenancyErrorCode.DATABASE_IDENTITY_CARDINALITY,
        ),
    ],
)
def test_exactly_one_reader_helper_fails_closed(identities, expected_code):
    with pytest.raises(TenancyError) as caught:
        require_exactly_one_database_identity(identities)

    assert caught.value.code == expected_code.value


def test_exactly_one_reader_helper_rejects_an_unconverted_row_without_echoing_it():
    sensitive_row = {
        "schema": "private_schema",
        "dsn": "mysql://user:secret@host/private_schema",
    }

    with pytest.raises(TenancyError) as caught:
        require_exactly_one_database_identity([sensitive_row])

    assert caught.value.code == TenancyErrorCode.DATABASE_IDENTITY_MISMATCH.value
    assert "private_schema" not in str(caught.value)
    assert "mysql://" not in repr(caught.value)


def test_database_identity_reader_protocol_is_structural():
    observed = make_observed()

    class FixedReader:
        def read_exactly_one(self, connection):
            assert connection is sentinel
            return observed

    sentinel = object()
    reader = FixedReader()

    assert isinstance(reader, DatabaseIdentityReader)
    assert reader.read_exactly_one(sentinel) is observed


def test_verification_accepts_an_exact_identity_match():
    assert verify_database_identity(make_expected(), make_observed()) is None


@pytest.mark.parametrize(
    "observed",
    [
        make_observed(tenant_id=uuid4()),
        make_observed(database_uuid=uuid4()),
        make_observed(schema_generation=8),
    ],
)
def test_verification_uses_one_generic_error_for_every_mismatch(observed):
    expected = make_expected()

    with pytest.raises(TenancyError) as caught:
        verify_database_identity(expected, observed)

    assert caught.value.code == TenancyErrorCode.DATABASE_IDENTITY_MISMATCH.value
    output = f"{caught.value!s} {caught.value!r}"
    assert str(expected.tenant_id) not in output
    assert str(expected.database_uuid) not in output
    assert str(observed.tenant_id) not in output
    assert str(observed.database_uuid) not in output


@pytest.mark.parametrize(
    ("factory", "field_name", "value", "error_type"),
    [
        (make_observed, "tenant_id", "tenant", TypeError),
        (make_observed, "database_uuid", UUID(int=0), ValueError),
        (make_observed, "created_at", "2026-08-22", TypeError),
        (make_observed, "schema_generation", True, TypeError),
        (make_expected, "schema_generation", 0, ValueError),
    ],
)
def test_database_identity_contracts_reject_invalid_values(
    factory, field_name, value, error_type
):
    with pytest.raises(error_type):
        factory(**{field_name: value})
