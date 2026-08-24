"""Bounded background sweep for due tenant invitations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

import sqlalchemy as sa
from sqlalchemy.orm import Session

from inventory_control.database import ControlDatabase, read_database_utc_datetime
from inventory_control.jobs import DurableJobCapability, JobProcessTrigger
from inventory_control.models.invitations import TenantInvitation

from .persistence import (
    InvitationConflictError,
    InvitationPersistenceService,
    InvitationStaleRevisionError,
)


DatabaseClock = Callable[[Session], datetime]


@dataclass(frozen=True, slots=True)
class InvitationExpirySweepResult:
    candidate_invitations: int
    expired_invitations: int
    idempotent_replays: int
    concurrent_conflicts: int


class InvitationExpirySweep:
    """Expire a bounded due set with one short transaction per invitation.

    Seat usage already excludes rows whose deadline has passed, so this sweep
    is a durable state cleanup rather than the authority that releases quota.
    A crash or stale candidate is safe: the next current scan retries only rows
    that remain pending and due.
    """

    def __init__(
        self,
        *,
        database: ControlDatabase,
        invitations: InvitationPersistenceService,
        database_clock: DatabaseClock | None = None,
    ) -> None:
        if not isinstance(database, ControlDatabase):
            raise TypeError("control database is required")
        if not isinstance(invitations, InvitationPersistenceService):
            raise TypeError("invitation persistence service is required")
        if database_clock is not None and not callable(database_clock):
            raise TypeError("database_clock must be callable")
        self._database = database
        self._invitations = invitations
        self._database_clock = database_clock or read_database_utc_datetime

    def run_once(self, *, max_candidates: int) -> InvitationExpirySweepResult:
        _validate_max_candidates(max_candidates)
        with self._database.transaction() as session:
            scan_time = _as_utc(self._database_clock(session))
            candidates = tuple(
                session.execute(
                    sa.select(TenantInvitation.id, TenantInvitation.row_version)
                    .where(
                        TenantInvitation.status == "pending",
                        TenantInvitation.expires_at <= scan_time,
                    )
                    .order_by(
                        TenantInvitation.expires_at.asc(),
                        TenantInvitation.id.asc(),
                    )
                    .limit(max_candidates)
                )
            )

        expired = replayed = conflicts = 0
        for invitation_id, row_version in candidates:
            try:
                with self._database.transaction() as session:
                    result = self._invitations.expire(
                        session,
                        invitation_uuid=invitation_id,
                        expected_invitation_row_version=row_version,
                    )
            except (InvitationConflictError, InvitationStaleRevisionError):
                conflicts += 1
                continue
            if result.idempotent:
                replayed += 1
            else:
                expired += 1
        return InvitationExpirySweepResult(
            candidate_invitations=len(candidates),
            expired_invitations=expired,
            idempotent_replays=replayed,
            concurrent_conflicts=conflicts,
        )


def build_invitation_expiry_capability(
    *,
    database: ControlDatabase,
    invitations: InvitationPersistenceService,
    scan_interval: timedelta,
    max_candidates: int,
    database_clock: DatabaseClock | None = None,
) -> DurableJobCapability:
    """Register bounded invitation cleanup in the shared job process."""

    if not isinstance(scan_interval, timedelta) or scan_interval < timedelta(seconds=1):
        raise ValueError("scan_interval must be at least one second")
    _validate_max_candidates(max_candidates)
    sweep = InvitationExpirySweep(
        database=database,
        invitations=invitations,
        database_clock=database_clock,
    )
    return DurableJobCapability(
        handlers={},
        triggers=(
            JobProcessTrigger(
                name="invitation-expiry-sweep",
                interval=scan_interval,
                callback=lambda _now: sweep.run_once(max_candidates=max_candidates),
            ),
        ),
    )


def _validate_max_candidates(value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 1000:
        raise ValueError("max_candidates must be between 1 and 1000")


def _as_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise RuntimeError("control database did not return a timestamp")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "InvitationExpirySweep",
    "InvitationExpirySweepResult",
    "build_invitation_expiry_capability",
]
