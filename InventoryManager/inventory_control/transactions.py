"""Shared SQLAlchemy transaction ownership primitives.

Services keep their domain-specific error classes, while this module owns the
single definition of a caller-created transaction and a clean unit of work.
It never begins, commits, or rolls back a transaction on the caller's behalf.
"""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.orm import Session, SessionTransaction, SessionTransactionOrigin


ErrorFactory = Callable[[], BaseException]


def require_caller_transaction(
    session: object,
    transaction_error: ErrorFactory,
    *,
    invalid_session_error: ErrorFactory | None = None,
    dirty_error: ErrorFactory | None = None,
    clean: bool = False,
    require_begin_origin: bool = False,
    accept_nested: bool = False,
) -> SessionTransaction:
    """Return the explicit outer transaction or raise the caller's error.

    ``AUTOBEGIN`` is never accepted: merely querying or adding an object must
    not silently establish write authority.  ``clean`` additionally rejects
    pending ORM changes so a migration step cannot inherit unrelated writes.
    """

    if not isinstance(session, Session):
        raise (invalid_session_error or transaction_error)()
    nested_transaction = session.get_nested_transaction() if accept_nested else None
    transaction = nested_transaction or session.get_transaction()
    invalid_origin = transaction is not None and (
        nested_transaction is None
        and (
            transaction.origin is SessionTransactionOrigin.AUTOBEGIN
            or (
                require_begin_origin
                and transaction.origin is not SessionTransactionOrigin.BEGIN
            )
        )
    )
    if transaction is None or invalid_origin:
        raise transaction_error()
    if clean and (
        session.new
        or session.deleted
        or any(
            session.is_modified(instance, include_collections=True)
            for instance in session.dirty
        )
    ):
        raise (dirty_error or transaction_error)()
    return transaction


__all__ = [
    "require_caller_transaction",
]
