import pytest

from app.tenancy.errors import TenancyError, TenancyErrorCode


EXPECTED_CODES = {
    "TENANT_CONTEXT_REQUIRED",
    "UNTRUSTED_TENANT_SELECTOR",
    "TENANT_ROUTE_UNAVAILABLE",
    "DATABASE_IDENTITY_MISSING",
    "DATABASE_IDENTITY_CARDINALITY",
    "DATABASE_IDENTITY_MISMATCH",
    "STALE_TENANT_ACCESS_VERSION",
}


def test_tenancy_error_codes_are_stable_strings():
    assert {code.value for code in TenancyErrorCode} == EXPECTED_CODES

    for code in TenancyErrorCode:
        error = TenancyError(code)
        assert error.code == code.value
        assert str(error) == error.public_message


def test_tenancy_error_cannot_accept_a_free_form_sensitive_message():
    with pytest.raises(TypeError, match="TenancyErrorCode"):
        TenancyError("mysql://user:secret@host/private_schema")


def test_public_errors_do_not_expose_routing_or_comparison_details():
    forbidden_fragments = (
        "mysql://",
        "private_schema",
        "dsn",
        "expected",
        "observed",
    )

    for code in TenancyErrorCode:
        public_output = str(TenancyError(code)).lower()
        assert all(fragment not in public_output for fragment in forbidden_fragments)
