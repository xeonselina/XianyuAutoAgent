"""Read-only SQLAlchemy adapter for the platform root-key registry."""

from __future__ import annotations

import os

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from inventory_control.models.root_keys import PlatformRootKeyVersion
from inventory_control.transactions import require_caller_transaction

from .errors import CryptoConfigurationError, RootKeyLoadError
from .keyring import (
    RootKeyLifecycle,
    RootKeyRing,
    RootKeyVersionFact,
    load_root_key_ring,
)


class RootKeyRegistryError(RootKeyLoadError):
    """The authoritative non-secret registry could not be read safely."""


class RootKeyRegistryTransactionError(RootKeyRegistryError):
    """The caller did not provide a clean, explicit outer transaction."""


class SqlAlchemyRootKeyRegistry:
    """Load a key ring from one locking read of the authoritative registry.

    The caller owns the session, its explicit transaction, and its final
    commit or rollback.  This adapter never adds, updates, deletes, flushes,
    commits, or rolls back database state.
    """

    __slots__ = ("_session",)

    def __init__(self, *, session: Session) -> None:
        if not isinstance(session, Session):
            raise TypeError("session must be a SQLAlchemy Session")
        self._session = session

    def load(
        self,
        directory: str | os.PathLike[str],
    ) -> RootKeyRing:
        """Lock current registry rows and load their exact mounted files."""

        _require_clean_explicit_transaction(self._session)
        statement = (
            sa.select(PlatformRootKeyVersion)
            .order_by(PlatformRootKeyVersion.version)
            .execution_options(autoflush=False, populate_existing=True)
            .with_for_update()
        )
        try:
            rows = tuple(self._session.scalars(statement))
        except SQLAlchemyError:
            raise RootKeyRegistryError(
                "platform root key registry cannot be read safely"
            ) from None

        try:
            facts = tuple(
                RootKeyVersionFact(
                    version=row.version,
                    fingerprint_sha256=row.fingerprint_sha256.hex(),
                    status=RootKeyLifecycle(row.status),
                )
                for row in rows
            )
        except (AttributeError, CryptoConfigurationError, TypeError, ValueError):
            raise RootKeyRegistryError(
                "platform root key registry contains invalid metadata"
            ) from None

        return load_root_key_ring(directory, registry=facts)

    def load_root_key_ring(
        self,
        directory: str | os.PathLike[str],
    ) -> RootKeyRing:
        """Descriptive alias for :meth:`load`."""

        return self.load(directory)

    def __repr__(self) -> str:
        return "SqlAlchemyRootKeyRegistry(read_only=True, locking_read=True)"


def _require_clean_explicit_transaction(session: Session) -> None:
    require_caller_transaction(
        session,
        lambda: RootKeyRegistryTransactionError(
            "an explicit clean caller-owned transaction is required"
        ),
        clean=True,
    )


__all__ = [
    "RootKeyRegistryError",
    "RootKeyRegistryTransactionError",
    "SqlAlchemyRootKeyRegistry",
]
