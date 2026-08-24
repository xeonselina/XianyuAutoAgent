"""Fail-closed startup authority for the external deployment marker.

The root-owned marker is loaded by a deployment adapter and supplied as a
trusted value.  This module performs no filesystem writes and never creates or
rotates a marker.  It only reconciles that value with the sole live
installation and the sole current, completed recovery epoch.
"""

from __future__ import annotations

from dataclasses import dataclass

import sqlalchemy as sa
from sqlalchemy.orm import Session, SessionTransactionOrigin

from inventory_control.models.foundation import Installation
from inventory_control.models.recovery import DisasterRecoveryRun
from inventory_control.operations.health import (
    HostRecoveryMarker,
    HostRecoveryMarkerMode,
)


class StartupAuthorityError(RuntimeError):
    """Stable startup rejection that carries no marker or database detail."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class StartupAuthorityTransactionError(StartupAuthorityError):
    pass


@dataclass(frozen=True, slots=True)
class StartupAuthority:
    installation_uuid: str
    recovery_run_uuid: str
    recovery_kind: str
    recovery_row_version: int
    marker_mode: HostRecoveryMarkerMode


class StartupAuthorityService:
    """Verify deployment marker, installation, and current recovery epoch."""

    def verify(
        self,
        session: Session,
        *,
        marker: HostRecoveryMarker,
    ) -> StartupAuthority:
        _require_clean_explicit_transaction(session)
        if not isinstance(marker, HostRecoveryMarker):
            raise StartupAuthorityError("STARTUP_MARKER_UNAVAILABLE")

        installations = tuple(
            session.scalars(
                sa.select(Installation)
                .where(Installation.retired_at.is_(None))
                .order_by(Installation.created_at, Installation.id)
                .limit(2)
                .execution_options(autoflush=False, populate_existing=True)
                .with_for_update()
            )
        )
        if len(installations) != 1:
            raise StartupAuthorityError("STARTUP_INSTALLATION_INVALID")
        installation = installations[0]
        if installation.marker_fingerprint != marker.installation_fingerprint:
            raise StartupAuthorityError("STARTUP_INSTALLATION_MISMATCH")

        runs = tuple(
            session.scalars(
                sa.select(DisasterRecoveryRun)
                .where(DisasterRecoveryRun.current_run_marker == "current")
                .limit(2)
                .execution_options(autoflush=False, populate_existing=True)
                .with_for_update()
            )
        )
        if len(runs) != 1:
            raise StartupAuthorityError("STARTUP_RECOVERY_RUN_INVALID")
        run = runs[0]
        if run.status != "completed":
            raise StartupAuthorityError("STARTUP_RECOVERY_NOT_COMPLETED")
        if run.host_installation_fingerprint != installation.marker_fingerprint:
            raise StartupAuthorityError("STARTUP_RECOVERY_INSTALLATION_MISMATCH")
        if run.deployment_marker_fingerprint != marker.marker_fingerprint:
            raise StartupAuthorityError("STARTUP_DEPLOYMENT_MARKER_MISMATCH")

        expected_mode = {
            "initial_baseline": HostRecoveryMarkerMode.NORMAL,
            "host_restore": HostRecoveryMarkerMode.HOST_RESTORE,
        }.get(run.kind)
        if expected_mode is None or marker.mode is not expected_mode:
            raise StartupAuthorityError("STARTUP_MARKER_MODE_MISMATCH")
        if (
            isinstance(run.row_version, bool)
            or not isinstance(run.row_version, int)
            or run.row_version < 1
        ):
            raise StartupAuthorityError("STARTUP_RECOVERY_RUN_INVALID")

        return StartupAuthority(
            installation_uuid=installation.id,
            recovery_run_uuid=run.id,
            recovery_kind=run.kind,
            recovery_row_version=run.row_version,
            marker_mode=marker.mode,
        )


def _require_clean_explicit_transaction(session: Session) -> None:
    if not isinstance(session, Session):
        raise TypeError("session must be a SQLAlchemy Session")
    transaction = session.get_transaction()
    if (
        transaction is None
        or transaction.origin is SessionTransactionOrigin.AUTOBEGIN
    ):
        raise StartupAuthorityTransactionError(
            "STARTUP_EXPLICIT_TRANSACTION_REQUIRED"
        )
    dirty = any(
        session.is_modified(instance, include_collections=True)
        for instance in session.dirty
    )
    if session.new or session.deleted or dirty:
        raise StartupAuthorityTransactionError("STARTUP_CLEAN_TRANSACTION_REQUIRED")


__all__ = [
    "StartupAuthority",
    "StartupAuthorityError",
    "StartupAuthorityService",
    "StartupAuthorityTransactionError",
]
