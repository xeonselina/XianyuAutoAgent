"""Short-lived sessions for the independent control database."""

from contextlib import contextmanager
from typing import ContextManager, Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.crypto import SecretBox


class ControlStore:
    def __init__(self, url: str, secret_box: SecretBox) -> None:
        self.secret_box = secret_box
        self.engine = create_engine(url, pool_pre_ping=True)
        self._session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

    def session(self) -> ContextManager[Session]:
        return self._session_scope()

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

    def dispose(self) -> None:
        self.engine.dispose()
