"""Shared authority contracts for durable control-plane jobs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy.orm import Session

from inventory_control.models.jobs import BackgroundJob


@dataclass(frozen=True, slots=True)
class AuthorityVerdict:
    allowed: bool
    reason_code: str | None = None
    recovery_review: bool = False

    def __post_init__(self) -> None:
        if self.allowed and (self.reason_code is not None or self.recovery_review):
            raise ValueError("allowed verdict cannot contain a denial reason")
        if not self.allowed and not self.reason_code:
            raise ValueError("denied verdict requires a reason code")


class JobAuthority(Protocol):
    """Acquire current authority before the job row, then evaluate it later.

    ``lock_current_job_authority`` must acquire every tenant/recovery/lifecycle
    row required by the selected phase in the caller-owned transaction.  The
    returned value is opaque to the queue service but remains protected until
    that transaction ends.  The queue service locks the job row last, reads the
    database clock, and only then calls ``evaluate_locked_job_authority``.
    """

    def lock_current_job_authority(
        self,
        session: Session,
        *,
        job: BackgroundJob,
        phase: str,
    ) -> Any: ...

    def evaluate_locked_job_authority(
        self,
        session: Session,
        *,
        locked_authority: Any,
        job: BackgroundJob,
        phase: str,
        now: datetime,
    ) -> AuthorityVerdict: ...
