"""Pure D64 project-completion and rehearsal scheduling rules."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Final


PROJECT_REHEARSAL_LEAD: Final[timedelta] = timedelta(hours=168)
_DIGEST_BYTES: Final[int] = 32
_SCHEMA_HEAD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}", re.ASCII)


class ProjectScheduleError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ProjectCompletionIdentity:
    """Migration-affecting implementation identity frozen at project completion."""

    implementation_digest: bytes
    image_digest: bytes
    migration_bundle_digest: bytes
    runtime_configuration_digest: bytes
    control_schema_head: str
    tenant_schema_head: str

    def __post_init__(self) -> None:
        for value, name in (
            (self.implementation_digest, "implementation_digest"),
            (self.image_digest, "image_digest"),
            (self.migration_bundle_digest, "migration_bundle_digest"),
            (
                self.runtime_configuration_digest,
                "runtime_configuration_digest",
            ),
        ):
            _digest(value, name)
        _head(self.control_schema_head, "control_schema_head")
        _head(self.tenant_schema_head, "tenant_schema_head")

    @property
    def digest(self) -> bytes:
        value = {
            "control_schema_head": self.control_schema_head,
            "image_digest": self.image_digest.hex(),
            "implementation_digest": self.implementation_digest.hex(),
            "migration_bundle_digest": self.migration_bundle_digest.hex(),
            "runtime_configuration_digest": (
                self.runtime_configuration_digest.hex()
            ),
            "tenant_schema_head": self.tenant_schema_head,
        }
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("ascii")
        return hashlib.sha256(encoded).digest()


@dataclass(frozen=True, slots=True)
class ProjectCompletionSchedule:
    completion_identity_digest: bytes
    project_complete_at: datetime
    earliest_rehearsal_at: datetime

    def __post_init__(self) -> None:
        _digest(self.completion_identity_digest, "completion_identity_digest")
        complete = _utc(self.project_complete_at, "project_complete_at")
        earliest = _utc(self.earliest_rehearsal_at, "earliest_rehearsal_at")
        object.__setattr__(self, "project_complete_at", complete)
        object.__setattr__(self, "earliest_rehearsal_at", earliest)
        if earliest != complete + PROJECT_REHEARSAL_LEAD:
            raise ProjectScheduleError(
                "earliest rehearsal must be exactly 168 hours after completion"
            )


@dataclass(frozen=True, slots=True)
class RehearsalWindow:
    completion_identity_digest: bytes
    project_complete_at: datetime
    earliest_rehearsal_at: datetime
    selected_window_at: datetime
    lead_seconds: int

    def __post_init__(self) -> None:
        _digest(self.completion_identity_digest, "completion_identity_digest")
        complete = _utc(self.project_complete_at, "project_complete_at")
        earliest = _utc(self.earliest_rehearsal_at, "earliest_rehearsal_at")
        selected = _utc(self.selected_window_at, "selected_window_at")
        object.__setattr__(self, "project_complete_at", complete)
        object.__setattr__(self, "earliest_rehearsal_at", earliest)
        object.__setattr__(self, "selected_window_at", selected)
        if earliest != complete + PROJECT_REHEARSAL_LEAD:
            raise ProjectScheduleError("rehearsal schedule identity is inconsistent")
        if selected < earliest:
            raise ProjectScheduleError("rehearsal window is earlier than T + 168h")
        expected_seconds = int((selected - complete).total_seconds())
        if self.lead_seconds != expected_seconds or self.lead_seconds < 604_800:
            raise ProjectScheduleError("rehearsal lead_seconds is invalid")


def record_project_completion(
    identity: ProjectCompletionIdentity,
    *,
    completed_at: datetime,
) -> ProjectCompletionSchedule:
    """Calculate T and T+168h after callers prove all prerequisites complete."""

    if not isinstance(identity, ProjectCompletionIdentity):
        raise TypeError("identity is invalid")
    complete = _utc(completed_at, "completed_at")
    return ProjectCompletionSchedule(
        completion_identity_digest=identity.digest,
        project_complete_at=complete,
        earliest_rehearsal_at=complete + PROJECT_REHEARSAL_LEAD,
    )


def refresh_project_completion(
    existing: ProjectCompletionSchedule,
    identity: ProjectCompletionIdentity,
    *,
    completed_at: datetime,
    affected_tests_rerun: bool,
) -> ProjectCompletionSchedule:
    """Keep exact replay or reset T after a migration-affecting identity change."""

    if not isinstance(existing, ProjectCompletionSchedule):
        raise TypeError("existing schedule is invalid")
    if not isinstance(identity, ProjectCompletionIdentity):
        raise TypeError("identity is invalid")
    if not isinstance(affected_tests_rerun, bool):
        raise TypeError("affected_tests_rerun must be a bool")
    if identity.digest == existing.completion_identity_digest:
        return existing
    if not affected_tests_rerun:
        raise ProjectScheduleError(
            "migration-affecting changes require related tests before resetting T"
        )
    new_complete = _utc(completed_at, "completed_at")
    if new_complete <= existing.project_complete_at:
        raise ProjectScheduleError("refreshed completion time must advance")
    return record_project_completion(identity, completed_at=new_complete)


def select_rehearsal_window(
    schedule: ProjectCompletionSchedule,
    *,
    selected_window_at: datetime,
) -> RehearsalWindow:
    """Select the first available operations window at or after T+168h."""

    if not isinstance(schedule, ProjectCompletionSchedule):
        raise TypeError("schedule is invalid")
    selected = _utc(selected_window_at, "selected_window_at")
    return RehearsalWindow(
        completion_identity_digest=schedule.completion_identity_digest,
        project_complete_at=schedule.project_complete_at,
        earliest_rehearsal_at=schedule.earliest_rehearsal_at,
        selected_window_at=selected,
        lead_seconds=int((selected - schedule.project_complete_at).total_seconds()),
    )


def _digest(value: object, field_name: str) -> bytes:
    if not isinstance(value, bytes) or len(value) != _DIGEST_BYTES:
        raise ProjectScheduleError(f"{field_name} must be a SHA-256 digest")
    return value


def _head(value: object, field_name: str) -> str:
    if not isinstance(value, str) or _SCHEMA_HEAD.fullmatch(value) is None:
        raise ProjectScheduleError(f"{field_name} is invalid")
    return value


def _utc(value: object, field_name: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ProjectScheduleError(f"{field_name} must be timezone-aware")
    return value.astimezone(timezone.utc)
