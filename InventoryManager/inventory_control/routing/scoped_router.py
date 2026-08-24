"""Request-scoped control bindings for one process-wide tenant router.

The tenant engine cache must live for the process lifetime, while route and
root-key authority must be read from the caller's current control transaction.
This adapter keeps those lifetimes separate: a single
``TenantDatabaseRouter`` owns the bounded engine cache and two ContextVar-backed
adapters resolve the control ``Session`` only while ``bind()`` is active.
"""

from __future__ import annotations

import os
from contextlib import AbstractContextManager, contextmanager
from contextvars import ContextVar
from pathlib import Path
from typing import Iterator

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, SessionTransactionOrigin

from app.tenancy import TenancyError, TenancyErrorCode
from inventory_control.crypto import RootKey, SqlAlchemyRootKeyRegistry

from .router import TenantDatabaseRouter, TenantRoute
from .sqlalchemy_adapters import (
    DatabaseInstanceRegistry,
    SqlAlchemyEngineFactory,
    SqlAlchemyIdentityVerifier,
    SqlAlchemyRouteRepository,
    TenantEnginePoolSettings,
)


class _ControlSessionBinding:
    """One context-local caller-owned control transaction."""

    __slots__ = ("_current",)

    def __init__(self) -> None:
        self._current: ContextVar[Session | None] = ContextVar(
            f"tenant-router-control-session-{id(self)}",
            default=None,
        )

    @contextmanager
    def bind(self, session: Session) -> Iterator[None]:
        _require_explicit_transaction(session)
        if self._current.get() is not None:
            raise RuntimeError("tenant router control session is already bound")
        token = self._current.set(session)
        try:
            yield
        finally:
            self._current.reset(token)

    def require_current(self) -> Session:
        session = self._current.get()
        try:
            _require_explicit_transaction(session)
        except (TypeError, RuntimeError):
            raise TenancyError(
                TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE
            ) from None
        return session


class _ContextRouteRepository:
    """Delegate each route read to the currently bound control session."""

    __slots__ = ("_binding",)

    def __init__(self, binding: _ControlSessionBinding) -> None:
        self._binding = binding

    def get_current_ready_route(
        self,
        *,
        tenant_uuid,
        access_version: int,
        account_kind,
    ) -> TenantRoute | None:
        repository = SqlAlchemyRouteRepository(
            session=self._binding.require_current()
        )
        return repository.get_current_ready_route(
            tenant_uuid=tenant_uuid,
            access_version=access_version,
            account_kind=account_kind,
        )

    def __repr__(self) -> str:
        return "_ContextRouteRepository(request_scoped=True)"


class _ContextRootKeyProvider:
    """Resolve an exact registered key through the same control transaction."""

    __slots__ = ("_binding", "_root_key_directory")

    def __init__(
        self,
        binding: _ControlSessionBinding,
        *,
        root_key_directory: Path,
    ) -> None:
        self._binding = binding
        self._root_key_directory = root_key_directory

    def get_root_key(self, *, version: int) -> RootKey:
        ring = SqlAlchemyRootKeyRegistry(
            session=self._binding.require_current()
        ).load(self._root_key_directory)
        return ring.key_for_existing_reference(version)

    def __repr__(self) -> str:
        return "_ContextRootKeyProvider(request_scoped=True, material=<redacted>)"


class SqlAlchemyTenantRouterScope:
    """Provide request bindings around one shared, bounded tenant router.

    Construction validates deployment-owned objects without opening a database
    connection.  Calling the instance returns a context manager suitable for
    ``SqlAlchemyGanttSaasHttpRuntime``.  The binding is always reset, including
    when route resolution or engine creation raises.
    """

    __slots__ = ("_binding", "_router")

    def __init__(
        self,
        *,
        root_key_directory: str | os.PathLike[str],
        database_instances: DatabaseInstanceRegistry,
        engine_pool_settings: TenantEnginePoolSettings,
        max_cache_entries: int,
    ) -> None:
        if not isinstance(database_instances, DatabaseInstanceRegistry):
            raise TypeError(
                "database_instances must be a DatabaseInstanceRegistry"
            )
        if not isinstance(engine_pool_settings, TenantEnginePoolSettings):
            raise TypeError(
                "engine_pool_settings must be TenantEnginePoolSettings"
            )
        if (
            isinstance(max_cache_entries, bool)
            or not isinstance(max_cache_entries, int)
            or max_cache_entries < 1
        ):
            raise ValueError("max_cache_entries must be a positive integer")

        directory = _absolute_directory(root_key_directory)
        binding = _ControlSessionBinding()
        self._binding = binding
        self._router: TenantDatabaseRouter[Engine] = TenantDatabaseRouter(
            repository=_ContextRouteRepository(binding),
            root_key_provider=_ContextRootKeyProvider(
                binding,
                root_key_directory=directory,
            ),
            engine_factory=SqlAlchemyEngineFactory(
                registry=database_instances,
                pool=engine_pool_settings,
            ),
            identity_verifier=SqlAlchemyIdentityVerifier(),
            max_cache_entries=max_cache_entries,
        )

    def __call__(
        self,
        control_session: Session,
    ) -> AbstractContextManager[TenantDatabaseRouter[Engine]]:
        return self.bind(control_session)

    @contextmanager
    def bind(
        self,
        control_session: Session,
    ) -> Iterator[TenantDatabaseRouter[Engine]]:
        with self._binding.bind(control_session):
            yield self._router

    def __repr__(self) -> str:
        return "SqlAlchemyTenantRouterScope(shared_bounded_cache=True)"


def _absolute_directory(value: str | os.PathLike[str]) -> Path:
    try:
        raw = os.fspath(value)
    except TypeError:
        raise TypeError("root_key_directory must be an absolute path") from None
    if (
        not isinstance(raw, str)
        or not raw
        or "\x00" in raw
        or not Path(raw).is_absolute()
    ):
        raise ValueError("root_key_directory must be an absolute path")
    return Path(raw)


def _require_explicit_transaction(session: object) -> None:
    if not isinstance(session, Session):
        raise TypeError("control_session must be a SQLAlchemy Session")
    transaction = session.get_transaction()
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
    ):
        raise RuntimeError(
            "control_session must own an explicit active transaction"
        )


__all__ = ["SqlAlchemyTenantRouterScope"]
