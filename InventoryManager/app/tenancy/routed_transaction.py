"""Reusable trusted tenant transaction routing for background capabilities."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Protocol

from sqlalchemy.orm import Session

from app.tenancy.context import TenantContext
from inventory_control import ControlDatabase
from inventory_control.routing import AccountKind


class TenantRouterScope(Protocol):
    def __call__(self, control_session: Session): ...


class SqlAlchemyTenantTransactionProvider:
    """Open one verified DML transaction from a trusted tenant context."""

    def __init__(
        self,
        *,
        database: ControlDatabase,
        router_scope: TenantRouterScope,
    ) -> None:
        if not isinstance(database, ControlDatabase) or not callable(router_scope):
            raise TypeError("routed tenant transaction composition is invalid")
        self._database = database
        self._router_scope = router_scope

    @contextmanager
    def __call__(self, context: TenantContext):
        if not isinstance(context, TenantContext):
            raise TypeError("trusted tenant context is required")
        with self._database.transaction() as control_session:
            with self._router_scope(control_session) as router:
                if not callable(getattr(router, "get_engine", None)):
                    raise TypeError("tenant router is invalid")
                engine = router.get_engine(context, account_kind=AccountKind.DML)
        with Session(engine) as tenant_session:
            with tenant_session.begin():
                yield tenant_session


__all__ = ["SqlAlchemyTenantTransactionProvider"]
