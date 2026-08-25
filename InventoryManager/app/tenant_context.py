"""Request-scoped routing for tenant business database sessions."""

from contextvars import ContextVar, Token
from threading import Lock

from flask_sqlalchemy.session import Session
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine, URL

from app.control.models import Tenant
from app.crypto import SecretBox


_tenant_binding: ContextVar[tuple[int, Engine] | None] = ContextVar(
    "tenant_database_binding",
    default=None,
)


def bind_tenant(tenant_id: int, engine: Engine) -> Token:
    """Bind one tenant engine to the current execution context."""
    return _tenant_binding.set((tenant_id, engine))


def reset_tenant(token: Token) -> None:
    """Restore the binding that existed before ``bind_tenant``."""
    _tenant_binding.reset(token)

def clear_tenant_binding() -> None: _tenant_binding.set(None)

def current_tenant_id() -> int | None:
    """Return the current tenant id without exposing its engine."""
    binding = _tenant_binding.get()
    return binding[0] if binding is not None else None


def _current_tenant_engine() -> Engine | None:
    binding = _tenant_binding.get()
    return binding[1] if binding is not None else None


class TenantSession(Session):
    """Flask-SQLAlchemy session routed by the current tenant context."""

    def get_bind(
        self,
        mapper=None,
        clause=None,
        bind=None,
        **kwargs,
    ) -> Engine:
        if bind is not None:
            return bind

        tenant_engine = _current_tenant_engine()
        if tenant_engine is not None:
            return tenant_engine

        return super().get_bind(
            mapper=mapper,
            clause=clause,
            bind=bind,
            **kwargs,
        )


class TenantEngineRegistry:
    """Small, thread-safe cache of immutable per-tenant engines."""

    def __init__(
        self,
        secret_box: SecretBox,
        host: str,
        port: int,
        pool_size: int = 2,
    ) -> None:
        self._secret_box = secret_box
        self._host = host
        self._port = port
        self._pool_size = pool_size
        self._engines: dict[int, Engine] = {}
        self._lock = Lock()

    def get(self, tenant: Tenant) -> Engine:
        tenant_id = tenant.id
        with self._lock:
            engine = self._engines.get(tenant_id)
            if engine is None:
                password = self._secret_box.decrypt(
                    tenant.db_password_ciphertext,
                    purpose="tenant-db-password",
                )
                url = URL.create(
                    drivername="mysql+pymysql",
                    username=tenant.db_username,
                    password=password,
                    host=self._host,
                    port=self._port,
                    database=tenant.db_name,
                )
                engine = create_engine(
                    url,
                    pool_size=self._pool_size,
                    max_overflow=1,
                    pool_pre_ping=True,
                )
                self._engines[tenant_id] = engine
            return engine

    def dispose_all(self) -> None:
        with self._lock:
            engines = list(self._engines.values())
            self._engines.clear()
            for engine in engines:
                engine.dispose()
