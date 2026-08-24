"""Engine and unit-of-work helpers for the independent control database."""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Iterator, Mapping

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker


def read_database_utc_value(session: Session) -> object:
    """Read the database clock with UTC semantics on supported MySQL engines.

    MySQL-family ``CURRENT_TIMESTAMP`` follows the connection time zone.  Most
    control-plane rows store a naive ``DATETIME(6)`` interpreted as UTC, so
    treating that value as UTC would shift leases and expiry decisions when a
    session is configured for Asia/Shanghai.  Unsupported dialects fail closed.
    """

    if not isinstance(session, Session):
        raise TypeError("session must be a SQLAlchemy Session")
    dialect_name = session.get_bind().dialect.name
    if dialect_name not in {"mysql", "mariadb"}:
        raise RuntimeError("control database requires MySQL or MariaDB")
    return session.scalar(text("SELECT UTC_TIMESTAMP(6)"))


def read_database_utc_datetime(session: Session) -> datetime:
    """Return the supported database clock as one aware UTC datetime."""

    value = read_database_utc_value(session)
    if not isinstance(value, datetime):
        raise RuntimeError("control database did not return a timestamp")
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


@dataclass(frozen=True)
class ControlDatabase:
    """Owns the control-plane engine and its independent session factory."""

    engine: Engine
    session_factory: sessionmaker[Session]

    @classmethod
    def from_url(
        cls,
        database_url: str,
        *,
        engine_options: Mapping[str, Any] | None = None,
    ) -> "ControlDatabase":
        if not database_url or not database_url.strip():
            raise ValueError("control database URL must not be empty")

        engine = create_engine(database_url, **dict(engine_options or {}))
        factory = sessionmaker(
            bind=engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
        )
        return cls(engine=engine, session_factory=factory)

    def new_session(self) -> Session:
        """Return a new session; the caller owns its transaction and lifetime."""

        return self.session_factory()

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Run one control-plane transaction and always close its session."""

        with self.session_factory.begin() as session:
            yield session

    def dispose(self) -> None:
        """Release connections owned by this control-plane engine."""

        self.engine.dispose()
