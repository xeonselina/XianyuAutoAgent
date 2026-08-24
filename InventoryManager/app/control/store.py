"""Short-lived sessions for the independent control database."""

from contextlib import contextmanager
from typing import ContextManager, Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from app.crypto import SecretBox


class ControlStore:
    def __init__(
        self,
        url: str,
        secret_box: SecretBox,
        pool_size: int = 5,
        max_overflow: int = 10,
        pool_timeout: float = 30,
    ) -> None:
        self.secret_box = secret_box
        engine_options = {"pool_pre_ping": True}
        if url.startswith(("mysql", "mariadb")):
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

    def session(self) -> ContextManager[Session]:
        return self._session_scope()

    def locked_session(
        self,
        names,
        timeout=0,
    ) -> ContextManager[Session]:
        return self._locked_session_scope(names, timeout)

    @contextmanager
    def _session_scope(self) -> Iterator[Session]:
        session = self._session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def _locked_session_scope(self, names, timeout) -> Iterator[Session]:
        """Serialize short MariaDB read-then-write transactions."""
        if self.engine.dialect.name not in {"mysql", "mariadb"}:
            with self._session_scope() as session:
                yield session
            return

        lock_names = sorted(set(names))
        acquired = []
        with self.engine.connect() as connection:
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
                session = self._session_factory(bind=connection)
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
        self.engine.dispose()
