from dataclasses import FrozenInstanceError, fields
from uuid import uuid4

import pytest

from app.tenancy.context import (
    TenantContext,
    TenantContextProvider,
    TenantContextSource,
)


def make_context(**overrides):
    values = {
        "tenant_id": uuid4(),
        "access_version": 3,
        "source": TenantContextSource.WEB_SESSION,
        "principal_ref": "user:6d6b29f7",
        "source_ref": "session:984956c5",
        "request_id": "request:45b5f9d7",
    }
    values.update(overrides)
    return TenantContext(**values)


def test_tenant_context_is_immutable_and_contains_only_trusted_routing_fields():
    context = make_context()

    assert {field.name for field in fields(context)} == {
        "tenant_id",
        "access_version",
        "source",
        "principal_ref",
        "source_ref",
        "request_id",
    }
    assert not hasattr(context, "database_name")
    assert not hasattr(context, "connection_url")
    assert not hasattr(context, "permissions")

    with pytest.raises(FrozenInstanceError):
        context.access_version = 4


@pytest.mark.parametrize("source", list(TenantContextSource))
def test_tenant_context_accepts_only_declared_server_sources(source):
    assert make_context(source=source).source is source

    with pytest.raises(TypeError, match="TenantContextSource"):
        make_context(source=source.value)


@pytest.mark.parametrize(
    ("field_name", "value", "error_type"),
    [
        ("tenant_id", "client-tenant", TypeError),
        ("tenant_id", type(uuid4())(int=0), ValueError),
        ("access_version", True, TypeError),
        ("access_version", 0, ValueError),
        ("principal_ref", "", ValueError),
        ("source_ref", " client-value ", ValueError),
        ("request_id", None, TypeError),
    ],
)
def test_tenant_context_rejects_noncanonical_contract_values(
    field_name, value, error_type
):
    with pytest.raises(error_type):
        make_context(**{field_name: value})


def test_context_provider_is_structural_and_has_no_request_constructor():
    expected = make_context(source=TenantContextSource.WORKER_JOB)

    class WorkerProvider:
        def require_current(self):
            return expected

    provider = WorkerProvider()

    assert isinstance(provider, TenantContextProvider)
    assert provider.require_current() is expected
    assert not hasattr(TenantContext, "from_request")
