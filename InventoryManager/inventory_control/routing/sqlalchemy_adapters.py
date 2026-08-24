"""SQLAlchemy adapters for trusted, purpose-separated tenant routes.

The public types in this module deliberately accept structured server
configuration rather than connection URLs.  Tenant database names and account
usernames come only from a validated :class:`TenantRoute`; passwords remain a
short-lived local value passed to ``URL.create``.
"""

from __future__ import annotations

import re
import hmac
import uuid
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Iterable, Mapping, Optional

import sqlalchemy as sa
from sqlalchemy.engine import Engine, URL
from sqlalchemy.orm import Session

from app.tenancy import (
    ExpectedDatabaseIdentity,
    SqlAlchemyDatabaseIdentityReader,
    TenancyError,
    TenancyErrorCode,
    verify_database_identity,
)
from inventory_control.models import (
    DatabaseIdentityControlRecord,
    Tenant,
    TenantDatabase,
)

from .identity import AccountKind, RoutingIdentity
from .router import AccountLoginState, TenantRoute, TenantRouteStatus


_DRIVER_COMPONENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")
_INSTANCE_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_.-]{0,127}$")
_ALLOWED_URL_OPTIONS = frozenset(
    {
        "charset",
        "connect_timeout",
        "read_timeout",
        "ssl_ca",
        "ssl_cert",
        "ssl_check_hostname",
        "ssl_key",
        "write_timeout",
    }
)


@dataclass(frozen=True, slots=True)
class DatabaseInstanceConfig:
    """Immutable location data loaded from trusted server configuration.

    ``options`` is a deliberately small allow-list of MySQL connection query
    options.  It cannot set a schema, run an initialization command, or carry a
    URL/credential field.
    """

    key: str
    host: str
    port: int = 3306
    dialect: str = "mysql"
    driver: str = "pymysql"
    options: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not _INSTANCE_KEY.fullmatch(self.key):
            raise ValueError("database instance key is invalid")
        _require_canonical_text("database host", self.host)
        if (
            isinstance(self.port, bool)
            or not isinstance(self.port, int)
            or not 1 <= self.port <= 65535
        ):
            raise ValueError("database port must be between 1 and 65535")
        if not isinstance(self.dialect, str) or not _DRIVER_COMPONENT.fullmatch(
            self.dialect
        ):
            raise ValueError("database dialect is invalid")
        if not isinstance(self.driver, str) or not _DRIVER_COMPONENT.fullmatch(
            self.driver
        ):
            raise ValueError("database driver is invalid")
        if self.dialect != "mysql" or self.driver != "pymysql":
            raise ValueError("only the mysql+pymysql tenant driver is supported")

        object.__setattr__(self, "options", _freeze_url_options(self.options))

    @property
    def drivername(self) -> str:
        return f"{self.dialect}+{self.driver}"

    def __repr__(self) -> str:
        return (
            "DatabaseInstanceConfig("
            f"key=<configured>, host=<configured>, port={self.port}, "
            f"drivername={self.drivername!r}, option_count={len(self.options)})"
        )


class DatabaseInstanceRegistry:
    """Read-only lookup of deployment-owned database instance locations."""

    __slots__ = ("_instances",)

    def __init__(self, instances: Iterable[DatabaseInstanceConfig]) -> None:
        if isinstance(instances, (str, bytes)):
            raise TypeError("instances must be DatabaseInstanceConfig values")
        resolved: dict[str, DatabaseInstanceConfig] = {}
        try:
            candidates = tuple(instances)
        except TypeError:
            raise TypeError(
                "instances must be an iterable of DatabaseInstanceConfig values"
            ) from None
        if not candidates:
            raise ValueError("at least one database instance is required")
        for instance in candidates:
            if not isinstance(instance, DatabaseInstanceConfig):
                raise TypeError("registry entries must be DatabaseInstanceConfig")
            if instance.key in resolved:
                raise ValueError("database instance keys must be unique")
            resolved[instance.key] = instance
        self._instances = MappingProxyType(resolved)

    def resolve(self, instance_key: str) -> DatabaseInstanceConfig:
        """Resolve a route-owned key without echoing it on failure."""

        try:
            instance = self._instances.get(instance_key)
        except (TypeError, AttributeError):
            instance = None
        if instance is None:
            raise TenancyError(TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)
        return instance

    def __len__(self) -> int:
        return len(self._instances)

    def __repr__(self) -> str:
        return f"DatabaseInstanceRegistry(instance_count={len(self)})"


class SqlAlchemyRouteRepository:
    """Read a complete published route from a caller-owned control transaction.

    The lookup accepts only the trusted tenant UUID, the exact access version
    already established by the caller, and a typed account purpose.  Database
    names, usernames, URLs, and DSNs are never accepted as lookup inputs.
    """

    __slots__ = ("_session",)

    def __init__(self, *, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._session = session

    def get_current_ready_route(
        self,
        *,
        tenant_uuid: uuid.UUID,
        access_version: int,
        account_kind: AccountKind,
    ) -> Optional[TenantRoute]:
        """Return one exact, complete route or ``None`` on unsafe metadata."""

        if (
            not isinstance(tenant_uuid, uuid.UUID)
            or isinstance(access_version, bool)
            or not isinstance(access_version, int)
            or access_version < 1
            or not isinstance(account_kind, AccountKind)
        ):
            return None
        if not self._session.in_transaction():
            raise TenancyError(TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)

        statement = (
            sa.select(Tenant, TenantDatabase, DatabaseIdentityControlRecord)
            .join(TenantDatabase, TenantDatabase.tenant_id == Tenant.id)
            .join(
                DatabaseIdentityControlRecord,
                sa.and_(
                    DatabaseIdentityControlRecord.tenant_id == TenantDatabase.tenant_id,
                    DatabaseIdentityControlRecord.database_uuid
                    == TenantDatabase.database_uuid,
                ),
            )
            .where(
                Tenant.id == str(tenant_uuid),
                Tenant.access_version == access_version,
                TenantDatabase.status == TenantRouteStatus.READY.value,
            )
            .execution_options(autoflush=False, populate_existing=True)
            .with_for_update()
        )
        try:
            row = self._session.execute(statement).one_or_none()
        except Exception:
            raise TenancyError(
                TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE
            ) from None
        if row is None:
            return None

        tenant, route, identity = row
        return _project_current_route(
            tenant=tenant,
            route=route,
            identity=identity,
            account_kind=account_kind,
        )

    def __repr__(self) -> str:
        return "SqlAlchemyRouteRepository(caller_owned_transaction=True)"


@dataclass(frozen=True, slots=True)
class TenantEnginePoolSettings:
    """Small explicit defaults for every purpose-specific tenant engine."""

    pool_size: int = 1
    max_overflow: int = 0
    pool_timeout_seconds: int = 5
    pool_recycle_seconds: int = 300

    def __post_init__(self) -> None:
        _require_nonnegative_integer("max_overflow", self.max_overflow)
        _require_positive_integer("pool_size", self.pool_size)
        _require_positive_integer("pool_timeout_seconds", self.pool_timeout_seconds)
        _require_positive_integer("pool_recycle_seconds", self.pool_recycle_seconds)


class SqlAlchemyEngineFactory:
    """Build one tenant engine from structured trusted metadata.

    There is intentionally no constructor or method accepting a raw DSN.  The
    URL is held only as a local object and SQLAlchemy receives it directly,
    avoiding interpolation of usernames, passwords, or database names.
    """

    __slots__ = ("_pool", "_registry")

    def __init__(
        self,
        *,
        registry: DatabaseInstanceRegistry,
        pool: TenantEnginePoolSettings | None = None,
    ) -> None:
        if not isinstance(registry, DatabaseInstanceRegistry):
            raise TypeError("registry must be a DatabaseInstanceRegistry")
        if pool is not None and not isinstance(pool, TenantEnginePoolSettings):
            raise TypeError("pool must be TenantEnginePoolSettings")
        self._registry = registry
        self._pool = pool or TenantEnginePoolSettings()

    def create(
        self,
        *,
        route: TenantRoute,
        identity: RoutingIdentity,
        password: str,
    ) -> Engine:
        if not isinstance(route, TenantRoute):
            raise TenancyError(TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)
        if not isinstance(identity, RoutingIdentity):
            raise TenancyError(TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)
        if identity != route.routing_identity():
            raise TenancyError(TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)
        if (
            not isinstance(password, str)
            or not password
            or "\x00" in password
        ):
            raise TenancyError(TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)

        instance = self._registry.resolve(route.database_instance_key)
        url = URL.create(
            drivername=instance.drivername,
            username=route.username,
            password=password,
            host=instance.host,
            port=instance.port,
            database=route.database_name,
            query=dict(instance.options),
        )

        creation_failed = False
        try:
            engine = sa.create_engine(
                url,
                pool_size=self._pool.pool_size,
                max_overflow=self._pool.max_overflow,
                pool_timeout=self._pool.pool_timeout_seconds,
                pool_recycle=self._pool.pool_recycle_seconds,
                pool_pre_ping=True,
                pool_reset_on_return="rollback",
                pool_use_lifo=True,
                hide_parameters=True,
            )
        except Exception:
            creation_failed = True
        if creation_failed:
            raise TenancyError(TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)
        if not callable(getattr(engine, "connect", None)) or not callable(
            getattr(engine, "dispose", None)
        ):
            raise TenancyError(TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)
        return engine

    def __repr__(self) -> str:
        return (
            "SqlAlchemyEngineFactory("
            f"instance_count={len(self._registry)}, pool={self._pool!r})"
        )


class SqlAlchemyIdentityVerifier:
    """Verify exactly one unqualified identity row through a new engine."""

    __slots__ = ("_reader",)

    def __init__(self) -> None:
        self._reader = SqlAlchemyDatabaseIdentityReader()

    def verify(
        self,
        *,
        engine: Engine,
        expected: ExpectedDatabaseIdentity,
    ) -> None:
        if not isinstance(expected, ExpectedDatabaseIdentity) or not callable(
            getattr(engine, "connect", None)
        ):
            raise TenancyError(TenancyErrorCode.DATABASE_IDENTITY_MISMATCH)

        error_code: TenancyErrorCode | None = None
        try:
            with engine.connect() as connection:
                observed = self._reader.read_exactly_one(connection)
                verify_database_identity(expected, observed)
        except TenancyError as error:
            try:
                error_code = TenancyErrorCode(error.code)
            except ValueError:
                error_code = TenancyErrorCode.DATABASE_IDENTITY_MISMATCH
        except Exception:
            error_code = TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE

        if error_code is not None:
            raise TenancyError(error_code)

    def __repr__(self) -> str:
        return "SqlAlchemyIdentityVerifier(fixed_query=database_identity)"


def _project_current_route(
    *,
    tenant: Tenant,
    route: TenantDatabase,
    identity: DatabaseIdentityControlRecord,
    account_kind: AccountKind,
) -> Optional[TenantRoute]:
    """Convert ORM state only after every published fact is complete."""

    try:
        tenant_uuid = _canonical_uuid(tenant.id)
        database_uuid = _canonical_uuid(route.database_uuid)
        activation_commit_uuid = _canonical_uuid(
            route.activated_by_registration_commit_uuid
        )
        if route.dml_desired_state_recovery_run_id is not None:
            _canonical_uuid(route.dml_desired_state_recovery_run_id)

        _require_positive_integer("tenant access version", tenant.access_version)
        _require_positive_integer("route row version", route.row_version)
        _require_positive_integer(
            "activation route version", route.activation_route_version
        )
        _require_positive_integer(
            "activation credential generation",
            route.activation_credential_generation,
        )
        _require_canonical_text(
            "database instance key", route.database_instance_key
        )
        _require_canonical_text("database name", route.database_name)
        _require_canonical_text("schema version", route.schema_version)

        if (
            route.status != TenantRouteStatus.READY.value
            or route.tenant_id != tenant.id
            or identity.tenant_id != tenant.id
            or identity.database_uuid != route.database_uuid
            or identity.observed_schema_generation
            != identity.expected_schema_generation
            or not _schema_metadata_matches(identity, route.schema_version)
        ):
            return None
        _require_positive_integer(
            "expected schema generation", identity.expected_schema_generation
        )

        desired_state = AccountLoginState(route.dml_desired_login_state)
        observed_state = AccountLoginState(route.dml_observed_login_state)
        _require_positive_integer(
            "DML login state version", route.dml_login_state_version
        )

        if account_kind is AccountKind.DML:
            username = route.dml_username
            credential_generation = route.dml_credential_generation
            root_key_version = route.dml_root_key_version
            derivation_version = route.dml_derivation_version
            route_version = route.route_version
            if (
                desired_state is AccountLoginState.ACTIVE
                and observed_state is not AccountLoginState.ACTIVE
            ):
                return None
            projected_login_state = desired_state
        elif account_kind is AccountKind.PLATFORM_READ:
            username = route.platform_read_username
            credential_generation = route.platform_read_credential_generation
            root_key_version = route.platform_read_root_key_version
            derivation_version = route.platform_read_derivation_version
            route_version = route.platform_read_route_version
            projected_login_state = AccountLoginState.ACTIVE
        else:  # pragma: no cover - guarded by the public typed boundary
            return None

        _require_canonical_text("account username", username)
        _require_positive_integer(
            "credential generation", credential_generation
        )
        _require_positive_integer("root key version", root_key_version)
        _require_positive_integer("derivation version", derivation_version)
        _require_positive_integer("route version", route_version)

        # Constructing TenantRoute is the final validation boundary.  The
        # activation UUID is intentionally checked above but is historical
        # lineage and therefore does not enter the cache identity.
        del activation_commit_uuid
        return TenantRoute(
            tenant_uuid=tenant_uuid,
            tenant_access_version=tenant.access_version,
            status=TenantRouteStatus.READY,
            account_kind=account_kind,
            database_uuid=database_uuid,
            database_instance_key=route.database_instance_key,
            database_name=route.database_name,
            username=username,
            credential_generation=credential_generation,
            root_key_version=root_key_version,
            derivation_version=derivation_version,
            route_version=route_version,
            desired_login_state=projected_login_state,
            expected_schema_generation=identity.expected_schema_generation,
        )
    except (TypeError, ValueError, AttributeError):
        return None


def _canonical_uuid(value: object) -> uuid.UUID:
    if not isinstance(value, str) or len(value) != 36:
        raise ValueError("UUID metadata is invalid")
    parsed = uuid.UUID(value)
    if str(parsed) != value:
        raise ValueError("UUID metadata is not canonical")
    return parsed


def _schema_metadata_matches(
    identity: DatabaseIdentityControlRecord,
    route_schema_revision: object,
) -> bool:
    """Accept untouched legacy rows, but fail closed on partial/drifted facts."""

    values = (
        identity.expected_schema_revision,
        identity.expected_schema_sha256,
        identity.observed_schema_revision,
        identity.observed_schema_sha256,
    )
    if all(value is None for value in values):
        return True
    if any(value is None for value in values):
        return False
    try:
        expected_digest = bytes(identity.expected_schema_sha256)
        observed_digest = bytes(identity.observed_schema_sha256)
    except (TypeError, ValueError):
        return False
    return bool(
        identity.expected_schema_revision
        == identity.observed_schema_revision
        and route_schema_revision == identity.expected_schema_revision
        and len(expected_digest) == 32
        and len(observed_digest) == 32
        and hmac.compare_digest(expected_digest, observed_digest)
    )


def _freeze_url_options(options: Mapping[str, str]) -> Mapping[str, str]:
    if not isinstance(options, Mapping):
        raise TypeError("database options must be a mapping")
    if len(options) > len(_ALLOWED_URL_OPTIONS):
        raise ValueError("too many database options")

    frozen: dict[str, str] = {}
    for key, value in options.items():
        if not isinstance(key, str) or key not in _ALLOWED_URL_OPTIONS:
            raise ValueError("database option is not allowed")
        if (
            not isinstance(value, str)
            or not value
            or len(value) > 2048
            or any(ord(character) < 32 for character in value)
        ):
            raise ValueError("database option value is invalid")
        frozen[key] = value
    return MappingProxyType(frozen)


def _require_canonical_text(label: str, value: object) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or "\x00" in value
    ):
        raise ValueError(f"{label} must be a non-empty canonical string")


def _require_positive_integer(label: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")


def _require_nonnegative_integer(label: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"{label} must be a non-negative integer")
