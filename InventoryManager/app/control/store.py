"""Short-lived sessions for the independent control database."""

from contextlib import contextmanager
from typing import ContextManager, Iterator

from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker

from app.control.models import TenantMember
from app.crypto import SecretBox


class ControlStore:
    def __init__(
        self,
        url: str,
        secret_box: SecretBox,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: float = 30,
        maintenance_pool_timeout: float = 0.2,
    ) -> None:
        self.secret_box = secret_box
        is_mariadb = url.startswith(("mysql", "mariadb"))
        engine_options = {"pool_pre_ping": True}
        if is_mariadb:
            engine_options.update(
                pool_size=pool_size,
                max_overflow=max_overflow,
                pool_timeout=pool_timeout,
            )
        self.engine = create_engine(url, **engine_options)
        self._session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )
        if is_mariadb:
            self.maintenance_engine = create_engine(
                url,
                pool_pre_ping=True,
                pool_size=1,
                max_overflow=0,
                pool_timeout=maintenance_pool_timeout,
            )
            self._maintenance_session_factory = sessionmaker(
                bind=self.maintenance_engine,
                class_=Session,
                expire_on_commit=False,
            )
        else:
            self.maintenance_engine = self.engine
            self._maintenance_session_factory = self._session_factory

    def session(self) -> ContextManager[Session]:
        return self._session_scope()

    def locked_session(
        self,
        names,
        timeout=0,
    ) -> ContextManager[Session]:
        return self._locked_session_scope(names, timeout)

    def maintenance_locked_session(
        self,
        names,
        timeout=0,
    ) -> ContextManager[Session]:
        return self._locked_session_scope(
            names,
            timeout,
            engine=self.maintenance_engine,
            session_factory=self._maintenance_session_factory,
        )

    @contextmanager
    def tenant_members_locked_session(self, tenant_id):
        """Lock one tenant's members for invariant-preserving updates."""
        with self._session_scope() as session:
            members = session.scalars(
                select(TenantMember)
                .where(TenantMember.tenant_id == tenant_id)
                .order_by(TenantMember.id)
                .with_for_update()
            ).all()
            yield session, members

    @contextmanager
    def _session_scope(self, session_factory=None) -> Iterator[Session]:
        session_factory = session_factory or self._session_factory
        session = session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def _locked_session_scope(
        self,
        names,
        timeout,
        engine=None,
        session_factory=None,
    ) -> Iterator[Session]:
        """Serialize short MariaDB read-then-write transactions."""
        engine = engine or self.engine
        session_factory = session_factory or self._session_factory
        if engine.dialect.name not in {"mysql", "mariadb"}:
            with self._session_scope(session_factory) as session:
                yield session
            return

        lock_names = sorted(set(names))
        acquired = []
        with engine.connect() as connection:
            session = None
            try:
                for lock_name in lock_names:
                    result = connection.scalar(
                        text("SELECT GET_LOCK(:name, :timeout)"),
                        {"name": lock_name, "timeout": timeout},
                    )
                    if result != 1:
                        raise TimeoutError(
                            "timed out acquiring control database lock"
                        )
                    acquired.append(lock_name)
                connection.commit()
                session = session_factory(bind=connection)
                try:
                    yield session
                    session.commit()
                except Exception:
                    session.rollback()
                    raise
            finally:
                if session is not None:
                    session.close()
                for lock_name in reversed(acquired):
                    connection.execute(
                        text("SELECT RELEASE_LOCK(:name)"),
                        {"name": lock_name},
                    )
                connection.commit()

    def dispose(self) -> None:
        if self.maintenance_engine is not self.engine:
            self.maintenance_engine.dispose()
        self.engine.dispose()
