"""Trusted tenant route resolution and verified engine creation."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from dataclasses import dataclass
from enum import Enum
from typing import Generic, Optional, Protocol, TypeVar, runtime_checkable

from app.tenancy import (
    ExpectedDatabaseIdentity,
    PlatformTenantReadContext,
    TenantContext,
    TenancyError,
    TenancyErrorCode,
)
from inventory_control.crypto import (
    RootKey,
    derive_platform_read_password,
    derive_tenant_dml_password,
)

from .engine_cache import (
    BoundedEngineCache,
    DisposableEngine,
)
from .identity import AccountKind, RoutingIdentity


class TenantRouteStatus(str, Enum):
    PROVISIONAL = "provisional"
    READY = "ready"
    FAILED = "failed"
    RETIRED = "retired"


class AccountLoginState(str, Enum):
    ACTIVE = "active"
    LOCKED = "locked"


@dataclass(frozen=True, slots=True, kw_only=True)
class TenantRoute:
    """Trusted, account-purpose-specific projection of the current route.

    It intentionally contains no password, root-key material, URL, or DSN.
    Database location fields are repository-controlled inputs for a future
    concrete engine adapter and never come from an HTTP request.
    """

    tenant_uuid: uuid.UUID
    tenant_access_version: int
    status: TenantRouteStatus
    account_kind: AccountKind
    database_uuid: uuid.UUID
    database_instance_key: str
    database_name: str
    username: str
    credential_generation: int
    root_key_version: int
    derivation_version: int
    route_version: int
    desired_login_state: AccountLoginState
    expected_schema_generation: int

    def __post_init__(self) -> None:
        _require_uuid("tenant_uuid", self.tenant_uuid)
        _require_uuid("database_uuid", self.database_uuid)
        for field_name in (
            "tenant_access_version",
            "credential_generation",
            "root_key_version",
            "derivation_version",
            "route_version",
            "expected_schema_generation",
        ):
            _require_positive_integer(field_name, getattr(self, field_name))
        for field_name in (
            "database_instance_key",
            "database_name",
            "username",
        ):
            _require_canonical_text(field_name, getattr(self, field_name))

        object.__setattr__(self, "status", _route_status(self.status))
        object.__setattr__(self, "account_kind", _account_kind(self.account_kind))
        object.__setattr__(
            self,
            "desired_login_state",
            _login_state(self.desired_login_state),
        )

    def routing_identity(self) -> RoutingIdentity:
        return RoutingIdentity(
            tenant_uuid=self.tenant_uuid,
            account_kind=self.account_kind,
            database_uuid=self.database_uuid,
            username=self.username,
            credential_generation=self.credential_generation,
            root_key_version=self.root_key_version,
            derivation_version=self.derivation_version,
            route_version=self.route_version,
        )


@runtime_checkable
class RouteRepository(Protocol):
    """Resolve only the current route for trusted context metadata."""

    def get_current_ready_route(
        self,
        *,
        tenant_uuid: uuid.UUID,
        access_version: int,
        account_kind: AccountKind,
    ) -> Optional[TenantRoute]:
        ...


@runtime_checkable
class RootKeyProvider(Protocol):
    """Return exactly the requested, already validated root-key version."""

    def get_root_key(self, *, version: int) -> RootKey:
        ...


EngineT_co = TypeVar("EngineT_co", bound=DisposableEngine, covariant=True)
EngineT_contra = TypeVar(
    "EngineT_contra", bound=DisposableEngine, contravariant=True
)


@runtime_checkable
class EngineFactory(Protocol[EngineT_co]):
    """Create an engine from trusted route metadata and an ephemeral password."""

    def create(
        self,
        *,
        route: TenantRoute,
        identity: RoutingIdentity,
        password: str,
    ) -> EngineT_co:
        ...


@runtime_checkable
class IdentityVerifier(Protocol[EngineT_contra]):
    """Verify the immutable identity through a newly created engine."""

    def verify(
        self,
        *,
        engine: EngineT_contra,
        expected: ExpectedDatabaseIdentity,
    ) -> None:
        ...


class _CreationRequest:
    """Short-lived factory input with an intentionally redacted repr."""

    __slots__ = ("expected", "identity", "password", "route")

    def __init__(
        self,
        *,
        route: TenantRoute,
        identity: RoutingIdentity,
        expected: ExpectedDatabaseIdentity,
        password: str,
    ) -> None:
        self.route = route
        self.identity = identity
        self.expected = expected
        self.password = password

    def __repr__(self) -> str:
        return "_CreationRequest(password=<redacted>)"


EngineT = TypeVar("EngineT", bound=DisposableEngine)


class TenantDatabaseRouter(Generic[EngineT]):
    """Resolve a trusted route, derive its password, and cache a verified engine."""

    __slots__ = (
        "_cache",
        "_engine_factory",
        "_identity_verifier",
        "_pending_creation",
        "_repository",
        "_root_keys",
    )

    def __init__(
        self,
        *,
        repository: RouteRepository,
        root_key_provider: RootKeyProvider,
        engine_factory: EngineFactory[EngineT],
        identity_verifier: IdentityVerifier[EngineT],
        max_cache_entries: int,
    ) -> None:
        _require_method(repository, "get_current_ready_route", "route repository")
        _require_method(root_key_provider, "get_root_key", "root-key provider")
        _require_method(engine_factory, "create", "engine factory")
        _require_method(identity_verifier, "verify", "identity verifier")

        self._repository = repository
        self._root_keys = root_key_provider
        self._engine_factory = engine_factory
        self._identity_verifier = identity_verifier
        self._pending_creation: ContextVar[Optional[_CreationRequest]] = ContextVar(
            f"tenant-router-creation-{id(self)}",
            default=None,
        )
        self._cache = BoundedEngineCache(
            max_entries=max_cache_entries,
            factory=self._create_verified_engine,
        )

    def __repr__(self) -> str:
        return f"TenantDatabaseRouter(max_cache_entries={self._cache.max_entries})"

    def get_engine(
        self,
        context: TenantContext,
        *,
        account_kind: AccountKind,
    ) -> EngineT:
        """Return a verified engine using only a server-trusted tenant context."""

        trusted_context = _trusted_context(context)
        requested_kind = _safe_account_kind(account_kind)
        if requested_kind is not AccountKind.DML:
            raise _route_unavailable()
        return self._get_engine_for_trusted_subject(
            tenant_uuid=trusted_context.tenant_id,
            access_version=trusted_context.access_version,
            account_kind=requested_kind,
        )

    def _get_engine_for_trusted_subject(
        self,
        *,
        tenant_uuid: uuid.UUID,
        access_version: int,
        account_kind: AccountKind,
    ) -> EngineT:
        route = self._resolve_route(
            tenant_uuid=tenant_uuid,
            access_version=access_version,
            account_kind=account_kind,
        )
        self._validate_route(
            route,
            tenant_uuid=tenant_uuid,
            access_version=access_version,
            account_kind=account_kind,
        )
        identity = route.routing_identity()

        cached = self._cache.get(identity)
        if cached is not None:
            return cached

        root_key = self._load_root_key(route.root_key_version)
        password = self._derive_password(route, root_key)
        expected = ExpectedDatabaseIdentity(
            tenant_id=route.tenant_uuid,
            database_uuid=route.database_uuid,
            schema_generation=route.expected_schema_generation,
        )
        request = _CreationRequest(
            route=route,
            identity=identity,
            expected=expected,
            password=password,
        )
        token = self._pending_creation.set(request)
        cache_failed = False
        try:
            try:
                engine = self._cache.get_or_create(identity)
            except TenancyError:
                raise
            except Exception:
                cache_failed = True
        finally:
            self._pending_creation.reset(token)
        if cache_failed:
            raise _route_unavailable()
        return engine

    def invalidate_tenant(self, context: TenantContext) -> int:
        trusted_context = _trusted_context(context)
        return self._invalidate_tenant_uuid(trusted_context.tenant_id)

    def invalidate_purpose(
        self,
        context: TenantContext,
        *,
        account_kind: AccountKind,
    ) -> int:
        trusted_context = _trusted_context(context)
        requested_kind = _safe_account_kind(account_kind)
        if requested_kind is not AccountKind.DML:
            raise _route_unavailable()
        return self._invalidate_subject_purpose(
            tenant_uuid=trusted_context.tenant_id,
            account_kind=requested_kind,
        )

    def _invalidate_tenant_uuid(self, tenant_uuid: uuid.UUID) -> int:
        invalidate_failed = False
        try:
            removed = self._cache.invalidate_tenant(tenant_uuid)
        except Exception:
            invalidate_failed = True
        if invalidate_failed:
            raise _route_unavailable()
        return removed

    def _invalidate_subject_purpose(
        self,
        *,
        tenant_uuid: uuid.UUID,
        account_kind: AccountKind,
    ) -> int:
        invalidate_failed = False
        try:
            removed = self._cache.invalidate_purpose(
                tenant_uuid=tenant_uuid,
                account_kind=account_kind,
            )
        except Exception:
            invalidate_failed = True
        if invalidate_failed:
            raise _route_unavailable()
        return removed

    def _resolve_route(
        self,
        *,
        tenant_uuid: uuid.UUID,
        access_version: int,
        account_kind: AccountKind,
    ) -> TenantRoute:
        repository_error_code: Optional[TenancyErrorCode] = None
        try:
            route = self._repository.get_current_ready_route(
                tenant_uuid=tenant_uuid,
                access_version=access_version,
                account_kind=account_kind,
            )
        except TenancyError as error:
            try:
                repository_error_code = TenancyErrorCode(error.code)
            except ValueError:
                repository_error_code = TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE
        except Exception:
            repository_error_code = TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE

        if repository_error_code is not None:
            self._discard_subject_purpose(tenant_uuid, account_kind)
            raise TenancyError(repository_error_code)

        if not isinstance(route, TenantRoute):
            self._discard_subject_purpose(tenant_uuid, account_kind)
            raise _route_unavailable()
        return route

    def _validate_route(
        self,
        route: TenantRoute,
        *,
        tenant_uuid: uuid.UUID,
        access_version: int,
        account_kind: AccountKind,
    ) -> None:
        if route.tenant_access_version != access_version:
            self._discard_subject_purpose(tenant_uuid, account_kind)
            raise TenancyError(TenancyErrorCode.STALE_TENANT_ACCESS_VERSION)
        if (
            route.tenant_uuid != tenant_uuid
            or route.account_kind != account_kind
        ):
            self._discard_subject_purpose(tenant_uuid, account_kind)
            raise _route_unavailable()
        if (
            route.status is not TenantRouteStatus.READY
            or route.desired_login_state is not AccountLoginState.ACTIVE
        ):
            self._discard_subject_purpose(tenant_uuid, account_kind)
            raise _route_unavailable()

    def _load_root_key(self, version: int) -> RootKey:
        provider_failed = False
        try:
            root_key = self._root_keys.get_root_key(version=version)
        except Exception:
            provider_failed = True
        if (
            provider_failed
            or not isinstance(root_key, RootKey)
            or root_key.version != version
        ):
            raise _route_unavailable()
        return root_key

    @staticmethod
    def _derive_password(route: TenantRoute, root_key: RootKey) -> str:
        common = dict(
            root_key=root_key,
            tenant_uuid=route.tenant_uuid,
            database_uuid=route.database_uuid,
            account_username=route.username,
            credential_generation=route.credential_generation,
            derivation_version=route.derivation_version,
        )
        derivation_failed = False
        try:
            if route.account_kind is AccountKind.DML:
                password = derive_tenant_dml_password(**common)
            else:
                password = derive_platform_read_password(**common)
        except Exception:
            derivation_failed = True
        if derivation_failed:
            raise _route_unavailable()
        return password

    def _create_verified_engine(self, identity: RoutingIdentity) -> EngineT:
        request = self._pending_creation.get()
        if request is None or request.identity != identity:
            raise _route_unavailable()
        factory_failed = False
        try:
            engine = self._engine_factory.create(
                route=request.route,
                identity=identity,
                password=request.password,
            )
        except Exception:
            factory_failed = True
        if factory_failed or not callable(getattr(engine, "dispose", None)):
            raise _route_unavailable()

        verification_error_code: Optional[TenancyErrorCode] = None
        try:
            result = self._identity_verifier.verify(
                engine=engine,
                expected=request.expected,
            )
            if result is not None:
                verification_error_code = (
                    TenancyErrorCode.DATABASE_IDENTITY_MISMATCH
                )
        except TenancyError as error:
            try:
                verification_error_code = TenancyErrorCode(error.code)
            except ValueError:
                verification_error_code = (
                    TenancyErrorCode.DATABASE_IDENTITY_MISMATCH
                )
        except Exception:
            verification_error_code = TenancyErrorCode.DATABASE_IDENTITY_MISMATCH

        if verification_error_code is not None:
            _dispose_failed_engine(engine)
            raise TenancyError(verification_error_code)
        return engine

    def _discard_subject_purpose(
        self,
        tenant_uuid: uuid.UUID,
        account_kind: AccountKind,
    ) -> None:
        try:
            self._cache.invalidate_purpose(
                tenant_uuid=tenant_uuid,
                account_kind=account_kind,
            )
        except Exception:
            # BoundedEngineCache removes entries before attempting disposal.
            # Keep the public failure fixed and do not resurrect the entry.
            pass


class PlatformTenantReadRouter(Generic[EngineT]):
    """Separate platform-only facade for SELECT-only tenant engines."""

    __slots__ = ("_router",)

    def __init__(self, router: TenantDatabaseRouter[EngineT]) -> None:
        if not isinstance(router, TenantDatabaseRouter):
            raise TypeError("router must be a TenantDatabaseRouter")
        self._router = router

    def get_engine(self, context: PlatformTenantReadContext) -> EngineT:
        trusted_context = _trusted_platform_read_context(context)
        return self._router._get_engine_for_trusted_subject(
            tenant_uuid=trusted_context.target_tenant_id,
            access_version=trusted_context.target_access_version,
            account_kind=AccountKind.PLATFORM_READ,
        )

    def invalidate_tenant(self, context: PlatformTenantReadContext) -> int:
        trusted_context = _trusted_platform_read_context(context)
        return self._router._invalidate_subject_purpose(
            tenant_uuid=trusted_context.target_tenant_id,
            account_kind=AccountKind.PLATFORM_READ,
        )


def _trusted_context(value: TenantContext) -> TenantContext:
    if not isinstance(value, TenantContext):
        raise TenancyError(TenancyErrorCode.TENANT_CONTEXT_REQUIRED)
    return value


def _trusted_platform_read_context(
    value: PlatformTenantReadContext,
) -> PlatformTenantReadContext:
    if not isinstance(value, PlatformTenantReadContext):
        raise TenancyError(TenancyErrorCode.TENANT_CONTEXT_REQUIRED)
    return value


def _safe_account_kind(value: AccountKind) -> AccountKind:
    try:
        return AccountKind(value)
    except (TypeError, ValueError):
        raise _route_unavailable() from None


def _route_unavailable() -> TenancyError:
    return TenancyError(TenancyErrorCode.TENANT_ROUTE_UNAVAILABLE)


def _dispose_failed_engine(engine: DisposableEngine) -> None:
    try:
        engine.dispose()
    except Exception:
        pass


def _require_uuid(field_name: str, value: object) -> None:
    if not isinstance(value, uuid.UUID):
        raise TypeError(f"{field_name} must be a UUID")
    if value.int == 0:
        raise ValueError(f"{field_name} must not be nil")


def _require_positive_integer(field_name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"{field_name} must be an integer")
    if value < 1:
        raise ValueError(f"{field_name} must be positive")


def _require_canonical_text(field_name: str, value: object) -> None:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if not value or value != value.strip() or "\x00" in value:
        raise ValueError(f"{field_name} must be a non-empty canonical value")


def _route_status(value: TenantRouteStatus) -> TenantRouteStatus:
    try:
        return TenantRouteStatus(value)
    except (TypeError, ValueError):
        raise ValueError("route status is unsupported") from None


def _account_kind(value: AccountKind) -> AccountKind:
    try:
        return AccountKind(value)
    except (TypeError, ValueError):
        raise ValueError("account kind is unsupported") from None


def _login_state(value: AccountLoginState) -> AccountLoginState:
    try:
        return AccountLoginState(value)
    except (TypeError, ValueError):
        raise ValueError("account login state is unsupported") from None


def _require_method(value: object, method_name: str, label: str) -> None:
    if not callable(getattr(value, method_name, None)):
        raise TypeError(f"{label} must provide {method_name}()")
