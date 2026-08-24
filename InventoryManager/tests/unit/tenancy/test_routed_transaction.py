from contextlib import contextmanager
from uuid import uuid4

import pytest
import sqlalchemy as sa

from app.tenancy import TenantContext, TenantContextSource
from app.tenancy.routed_transaction import SqlAlchemyTenantTransactionProvider
from inventory_control import ControlDatabase
from inventory_control.routing import AccountKind


class Router:
    def __init__(self, engine) -> None:
        self.engine = engine
        self.calls = []

    def get_engine(self, context, *, account_kind):
        self.calls.append((context, account_kind))
        return self.engine


class RouterScope:
    def __init__(self, router) -> None:
        self.router = router
        self.control_sessions = []

    @contextmanager
    def __call__(self, control_session):
        self.control_sessions.append(control_session)
        yield self.router


def _context() -> TenantContext:
    return TenantContext(
        tenant_id=uuid4(),
        access_version=3,
        source=TenantContextSource.WORKER_JOB,
        principal_ref="shared-worker",
        source_ref=str(uuid4()),
        request_id="request-1",
    )


def test_provider_routes_one_context_and_owns_one_tenant_transaction(
    mysql_control_database,
) -> None:
    control = mysql_control_database
    tenant_engine = mysql_control_database.engine
    router = Router(tenant_engine)
    scope = RouterScope(router)
    context = _context()
    provider = SqlAlchemyTenantTransactionProvider(
        database=control,
        router_scope=scope,
    )
    with provider(context) as session:
        assert session.scalar(sa.select(sa.literal(1))) == 1
        assert session.in_transaction()

    assert len(scope.control_sessions) == 1
    assert router.calls == [(context, AccountKind.DML)]


def test_provider_rejects_untrusted_context_before_route_resolution(
    mysql_control_database,
) -> None:
    control = mysql_control_database
    tenant_engine = mysql_control_database.engine
    router = Router(tenant_engine)
    provider = SqlAlchemyTenantTransactionProvider(
        database=control,
        router_scope=RouterScope(router),
    )
    with pytest.raises(TypeError, match="trusted tenant context"):
        with provider(object()):
            pass

    assert router.calls == []
