"""Thread-safe bounded LRU cache for purpose-specific tenant engines."""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import Callable, Generic, List, Optional, Protocol, Tuple, TypeVar

from .identity import (
    AccountKind,
    RoutingIdentity,
    UuidValue,
    normalize_account_kind,
    normalize_uuid,
)


class DisposableEngine(Protocol):
    """Minimal engine surface required by the cache."""

    def dispose(self) -> None:
        ...


EngineT = TypeVar("EngineT", bound=DisposableEngine)


class EngineCacheError(RuntimeError):
    """Base class for cache lifecycle failures."""


class EngineDisposalError(EngineCacheError):
    """Raised after every removed engine received one disposal attempt."""


class StaleRoutingIdentityError(EngineCacheError):
    """Raised when a late route would replace a newer cached route version."""


class BoundedEngineCache(Generic[EngineT]):
    """A bounded LRU with exact routing-identity reuse and active retirement.

    The explicit factory receives a complete :class:`RoutingIdentity`; this
    component neither constructs nor accepts a DSN. Factory execution is kept
    under the cache lock so concurrent requests for one missing identity create
    exactly one engine.
    """

    def __init__(
        self,
        *,
        max_entries: int,
        factory: Callable[[RoutingIdentity], EngineT],
    ) -> None:
        if (
            isinstance(max_entries, bool)
            or not isinstance(max_entries, int)
            or max_entries <= 0
        ):
            raise ValueError("max_entries must be a positive integer")
        if not callable(factory):
            raise TypeError("engine factory must be callable")

        self._max_entries = max_entries
        self._factory = factory
        self._entries: "OrderedDict[RoutingIdentity, EngineT]" = OrderedDict()
        self._lock = threading.RLock()

    @property
    def max_entries(self) -> int:
        return self._max_entries

    def __len__(self) -> int:
        with self._lock:
            return len(self._entries)

    def identities(self) -> Tuple[RoutingIdentity, ...]:
        """Return an LRU-to-MRU immutable snapshot for diagnostics and tests."""

        with self._lock:
            return tuple(self._entries.keys())

    def get(self, identity: RoutingIdentity) -> Optional[EngineT]:
        """Return only an exact identity match and promote it to most-recent."""

        identity = _require_identity(identity)
        with self._lock:
            engine = self._entries.get(identity)
            if engine is not None:
                self._entries.move_to_end(identity)
            return engine

    def get_or_create(self, identity: RoutingIdentity) -> EngineT:
        """Reuse one exact identity or create it after retiring its old slot."""

        identity = _require_identity(identity)
        with self._lock:
            engine = self._entries.get(identity)
            if engine is not None:
                self._entries.move_to_end(identity)
                return engine

            same_purpose = [
                cached
                for cached in self._entries
                if cached.purpose_scope == identity.purpose_scope
            ]
            if same_purpose and identity.route_version <= same_purpose[0].route_version:
                raise StaleRoutingIdentityError(
                    "routing identity does not advance the cached route version"
                )
            stale_engines = self._remove_matching_locked(
                lambda cached: cached.purpose_scope == identity.purpose_scope
            )
            _dispose_all(stale_engines)

            engine = self._factory(identity)
            if not callable(getattr(engine, "dispose", None)):
                raise TypeError("engine factory result must provide dispose()")
            self._entries[identity] = engine
            self._entries.move_to_end(identity)

            capacity_evictions: List[EngineT] = []
            while len(self._entries) > self._max_entries:
                _, evicted = self._entries.popitem(last=False)
                capacity_evictions.append(evicted)
            _dispose_all(capacity_evictions)
            return engine

    def invalidate(
        self,
        *,
        tenant_uuid: Optional[UuidValue] = None,
        database_uuid: Optional[UuidValue] = None,
        account_kind: Optional[AccountKind] = None,
    ) -> int:
        """Dispose entries matching every supplied tenant/database/purpose filter.

        At least one selector is required; callers use :meth:`clear` for an
        intentional cache-wide invalidation.
        """

        if tenant_uuid is None and database_uuid is None and account_kind is None:
            raise ValueError("invalidate requires at least one selector")
        normalized_tenant = (
            normalize_uuid(tenant_uuid, "tenant UUID")
            if tenant_uuid is not None
            else None
        )
        normalized_database = (
            normalize_uuid(database_uuid, "database UUID")
            if database_uuid is not None
            else None
        )
        normalized_kind = (
            normalize_account_kind(account_kind) if account_kind is not None else None
        )

        def matches(identity: RoutingIdentity) -> bool:
            return (
                (normalized_tenant is None or identity.tenant_uuid == normalized_tenant)
                and (
                    normalized_database is None
                    or identity.database_uuid == normalized_database
                )
                and (
                    normalized_kind is None
                    or identity.account_kind == normalized_kind
                )
            )

        with self._lock:
            engines = self._remove_matching_locked(matches)
            _dispose_all(engines)
            return len(engines)

    def invalidate_tenant(self, tenant_uuid: UuidValue) -> int:
        return self.invalidate(tenant_uuid=tenant_uuid)

    def invalidate_database(self, database_uuid: UuidValue) -> int:
        return self.invalidate(database_uuid=database_uuid)

    def invalidate_purpose(
        self,
        *,
        account_kind: AccountKind,
        tenant_uuid: Optional[UuidValue] = None,
        database_uuid: Optional[UuidValue] = None,
    ) -> int:
        return self.invalidate(
            tenant_uuid=tenant_uuid,
            database_uuid=database_uuid,
            account_kind=account_kind,
        )

    def clear(self) -> int:
        """Remove and dispose all engines, returning the number removed."""

        with self._lock:
            engines = list(self._entries.values())
            self._entries.clear()
            _dispose_all(engines)
            return len(engines)

    def _remove_matching_locked(
        self, predicate: Callable[[RoutingIdentity], bool]
    ) -> List[EngineT]:
        matching = [identity for identity in self._entries if predicate(identity)]
        return [self._entries.pop(identity) for identity in matching]


def _require_identity(identity: RoutingIdentity) -> RoutingIdentity:
    if not isinstance(identity, RoutingIdentity):
        raise TypeError("cache operations require a complete RoutingIdentity")
    return identity


def _dispose_all(engines: List[EngineT]) -> None:
    first_error: Optional[Exception] = None
    for engine in engines:
        try:
            engine.dispose()
        except Exception as error:  # pragma: no cover - defensive adapter boundary
            if first_error is None:
                first_error = error
    if first_error is not None:
        raise EngineDisposalError(
            "one or more engines failed to dispose"
        ) from first_error
