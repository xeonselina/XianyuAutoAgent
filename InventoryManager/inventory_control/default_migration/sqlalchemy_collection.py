"""SQLAlchemy scalar adapter for explicitly composed read-only collectors."""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from .collection import MigrationReconciliationCollectionError
from .manifest import DefaultTenantMigrationManifest
from .reconciliation import (
    ReconciliationObservation,
    ReconciliationRequirement,
)


@dataclass(frozen=True, slots=True)
class SqlAlchemyScalarReconciliationCollector:
    """Read exactly one integer/digest value without flushing or committing.

    Database selection and least-privilege/read-only grants remain composition
    responsibilities.  This adapter accepts only a SQLAlchemy ``Select`` with
    no ``FOR UPDATE`` clause and refuses a Session carrying pending writes, so
    reconciliation itself cannot incidentally flush application mutations.
    """

    key: str
    session: Session
    statement: sa.sql.Select

    def __post_init__(self) -> None:
        if (
            not isinstance(self.key, str)
            or not self.key
            or not isinstance(self.session, Session)
            or not isinstance(self.statement, sa.sql.Select)
            or self.statement._for_update_arg is not None
        ):
            raise MigrationReconciliationCollectionError()

    def collect(
        self,
        *,
        manifest: DefaultTenantMigrationManifest,
        requirement: ReconciliationRequirement,
    ) -> ReconciliationObservation:
        if (
            not isinstance(manifest, DefaultTenantMigrationManifest)
            or not isinstance(requirement, ReconciliationRequirement)
            or requirement.key != self.key
            or self.session.new
            or self.session.dirty
            or self.session.deleted
        ):
            raise MigrationReconciliationCollectionError()
        try:
            with self.session.no_autoflush:
                value = self.session.execute(
                    self.statement.execution_options(autoflush=False)
                ).scalar_one()
        except (SQLAlchemyError, TypeError, ValueError):
            raise MigrationReconciliationCollectionError() from None
        if isinstance(value, memoryview):
            value = value.tobytes()
        if value is not None and (
            isinstance(value, bool) or not isinstance(value, (int, bytes))
        ):
            raise MigrationReconciliationCollectionError()
        return ReconciliationObservation(key=self.key, observed=value)


__all__ = ["SqlAlchemyScalarReconciliationCollector"]
