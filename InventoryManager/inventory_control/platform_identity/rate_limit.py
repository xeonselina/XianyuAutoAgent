"""Atomic, low-cardinality throttles for independent platform authentication."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from uuid import uuid4
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import sqlalchemy as sa
from sqlalchemy.dialects import mysql, sqlite
from sqlalchemy.orm import Session

from inventory_control.crypto import RootKey, derive_platform_auth_subject_digest
from inventory_control.models import PlatformAdminRateLimitCounter


_AUTH_SCOPES = frozenset({"password", "mfa"})
_SCOPES = _AUTH_SCOPES | {"code_reveal"}
_SUBJECT_TYPES = frozenset({"username", "ip", "device"})
_WINDOW_KINDS = frozenset({"rolling_hour", "calendar_day", "device_burst"})


class PlatformRateLimitBlocked(RuntimeError):
    """Internal throttle decision; public responses must mask bucket details."""

    def __init__(self, *, retry_at: datetime) -> None:
        super().__init__("Platform authentication is temporarily unavailable.")
        self.retry_at = retry_at


@dataclass(frozen=True, slots=True)
class PlatformRateLimitRule:
    scope: str
    subject_type: str
    window_kind: str
    window_duration: timedelta
    max_failures: int

    def __post_init__(self) -> None:
        if self.scope not in _SCOPES:
            raise ValueError("platform rate-limit scope is invalid")
        if self.subject_type not in _SUBJECT_TYPES:
            raise ValueError("platform rate-limit subject type is invalid")
        if self.window_kind not in _WINDOW_KINDS:
            raise ValueError("platform rate-limit window kind is invalid")
        if not isinstance(self.window_duration, timedelta):
            raise TypeError("platform rate-limit window duration is invalid")
        seconds = self.window_duration.total_seconds()
        if not seconds.is_integer() or not 1 <= seconds <= 86_400:
            raise ValueError("platform rate-limit window duration is invalid")
        if self.window_kind == "rolling_hour" and seconds != 3_600:
            raise ValueError("rolling-hour policy must use a one-hour window")
        if self.window_kind == "calendar_day" and seconds != 86_400:
            raise ValueError("calendar-day policy must use a one-day window")
        if (
            isinstance(self.max_failures, bool)
            or not isinstance(self.max_failures, int)
            or not 1 <= self.max_failures <= 1_000_000
        ):
            raise ValueError("platform rate-limit threshold is invalid")


@dataclass(frozen=True, slots=True)
class PlatformRateLimitPolicy:
    version: int
    calendar_timezone: str
    rules: tuple[PlatformRateLimitRule, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.version, bool)
            or not isinstance(self.version, int)
            or self.version < 1
        ):
            raise ValueError("platform rate-limit policy version is invalid")
        try:
            ZoneInfo(self.calendar_timezone)
        except (TypeError, ZoneInfoNotFoundError):
            raise ValueError("platform rate-limit calendar timezone is invalid") from None
        if not self.rules:
            raise ValueError("platform rate-limit policy requires explicit rules")
        identities = [
            (rule.scope, rule.subject_type, rule.window_kind)
            for rule in self.rules
        ]
        if len(identities) != len(set(identities)):
            raise ValueError("platform rate-limit policy contains duplicate rules")
        for scope in self.scopes:
            covered = {
                rule.subject_type for rule in self.rules if rule.scope == scope
            }
            if covered != _SUBJECT_TYPES:
                raise ValueError(
                    "each platform rate-limit scope must cover username, IP, and device"
                )

    @property
    def scopes(self) -> frozenset[str]:
        return frozenset(rule.scope for rule in self.rules)


@dataclass(frozen=True, slots=True)
class PlatformRateLimitSubjects:
    username: str
    ip: str
    device: str

    def __post_init__(self) -> None:
        for value in (self.username, self.ip, self.device):
            if (
                not isinstance(value, str)
                or not 1 <= len(value) <= 255
                or "\x00" in value
            ):
                raise ValueError("platform rate-limit subject is invalid")

    def value_for(self, subject_type: str) -> str:
        if subject_type == "username":
            return self.username
        if subject_type == "ip":
            return self.ip
        if subject_type == "device":
            return self.device
        raise ValueError("platform rate-limit subject type is invalid")


class PlatformAdminRateLimiter:
    """Check and update versioned platform-admin buckets in the caller tx."""

    def __init__(
        self,
        *,
        policy: PlatformRateLimitPolicy,
        root_key: RootKey,
    ) -> None:
        if not isinstance(policy, PlatformRateLimitPolicy):
            raise TypeError("policy must be a PlatformRateLimitPolicy")
        if not isinstance(root_key, RootKey):
            raise TypeError("root_key must be a RootKey")
        self._policy = policy
        self._root_key = root_key
        self._calendar_timezone = ZoneInfo(policy.calendar_timezone)

    @property
    def policy(self) -> PlatformRateLimitPolicy:
        return self._policy

    def check(
        self,
        session: Session,
        *,
        scope: str,
        subjects: PlatformRateLimitSubjects,
        now: datetime,
    ) -> None:
        """Lock all applicable buckets and reject a currently blocked subject."""

        current_time = _as_utc(now)
        for rule, digest, window_start, _ in self._facts(
            scope=scope,
            subjects=subjects,
            now=current_time,
        ):
            row = self._load_exact(
                session,
                scope=scope,
                digest=digest,
                window_kind=rule.window_kind,
                window_start=window_start,
            )
            if row is not None and (
                row.attempt_count >= rule.max_failures
                or (
                    row.blocked_until is not None
                    and _as_utc(row.blocked_until) > current_time
                )
            ):
                raise PlatformRateLimitBlocked(retry_at=_as_utc(row.expires_at))

    def record_failure(
        self,
        session: Session,
        *,
        scope: str,
        subjects: PlatformRateLimitSubjects,
        now: datetime,
    ) -> None:
        """Compatibility name for authentication failure accounting."""

        self.record_attempt(
            session,
            scope=scope,
            subjects=subjects,
            now=now,
        )

    def record_attempt(
        self,
        session: Session,
        *,
        scope: str,
        subjects: PlatformRateLimitSubjects,
        now: datetime,
    ) -> None:
        """Increment every scope bucket in stable order and atomically block."""

        current_time = _as_utc(now)
        for rule, digest, window_start, expires_at in self._facts(
            scope=scope,
            subjects=subjects,
            now=current_time,
        ):
            row, created = self._ensure_exact(
                session,
                scope=scope,
                digest=digest,
                rule=rule,
                window_start=window_start,
                expires_at=expires_at,
                now=current_time,
            )
            if row.attempt_count < 1:
                raise RuntimeError("platform rate-limit counter is corrupt")
            if created:
                next_count = 1
            else:
                next_count = row.attempt_count + 1
                row.attempt_count = next_count
                row.row_version += 1
            row.policy_version = self._policy.version
            row.updated_at = current_time
            if next_count >= rule.max_failures:
                row.blocked_until = expires_at
        session.flush()

    def _facts(
        self,
        *,
        scope: str,
        subjects: PlatformRateLimitSubjects,
        now: datetime,
    ) -> list[tuple[PlatformRateLimitRule, bytes, datetime, datetime]]:
        if scope not in _SCOPES:
            raise ValueError("platform rate-limit scope is invalid")
        if not isinstance(subjects, PlatformRateLimitSubjects):
            raise TypeError("subjects must be PlatformRateLimitSubjects")
        facts = []
        for rule in self._policy.rules:
            if rule.scope != scope:
                continue
            digest = derive_platform_auth_subject_digest(
                root_key=self._root_key,
                subject_type=rule.subject_type,
                subject_value=subjects.value_for(rule.subject_type),
            )
            window_start, expires_at = self._window_bounds(rule, now)
            facts.append((rule, digest, window_start, expires_at))
        facts.sort(key=lambda fact: (fact[0].window_kind, fact[1]))
        return facts

    def _window_bounds(
        self,
        rule: PlatformRateLimitRule,
        now: datetime,
    ) -> tuple[datetime, datetime]:
        if rule.window_kind == "calendar_day":
            local_now = now.astimezone(self._calendar_timezone)
            local_start = local_now.replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            local_end = local_start + timedelta(days=1)
            return local_start.astimezone(timezone.utc), local_end.astimezone(
                timezone.utc
            )
        seconds = int(rule.window_duration.total_seconds())
        epoch_seconds = int(now.timestamp())
        start_seconds = epoch_seconds - (epoch_seconds % seconds)
        start = datetime.fromtimestamp(start_seconds, tz=timezone.utc)
        return start, start + rule.window_duration

    @staticmethod
    def _load_exact(
        session: Session,
        *,
        scope: str,
        digest: bytes,
        window_kind: str,
        window_start: datetime,
    ) -> PlatformAdminRateLimitCounter | None:
        return session.scalar(
            sa.select(PlatformAdminRateLimitCounter)
            .where(
                PlatformAdminRateLimitCounter.scope == scope,
                PlatformAdminRateLimitCounter.subject_digest_sha256 == digest,
                PlatformAdminRateLimitCounter.window_kind == window_kind,
                PlatformAdminRateLimitCounter.window_started_at == window_start,
            )
            .with_for_update()
        )

    def _ensure_exact(
        self,
        session: Session,
        *,
        scope: str,
        digest: bytes,
        rule: PlatformRateLimitRule,
        window_start: datetime,
        expires_at: datetime,
        now: datetime,
    ) -> tuple[PlatformAdminRateLimitCounter, bool]:
        row = self._load_exact(
            session,
            scope=scope,
            digest=digest,
            window_kind=rule.window_kind,
            window_start=window_start,
        )
        if row is not None:
            return row, False

        candidate_id = str(uuid4())
        values = dict(
            id=candidate_id,
            scope=scope,
            subject_digest_sha256=digest,
            window_kind=rule.window_kind,
            window_started_at=window_start,
            attempt_count=1,
            policy_version=self._policy.version,
            blocked_until=(expires_at if rule.max_failures == 1 else None),
            expires_at=expires_at,
            row_version=1,
            created_at=now,
            updated_at=now,
        )
        table = PlatformAdminRateLimitCounter.__table__
        dialect = session.get_bind().dialect.name
        if dialect in {"mysql", "mariadb"}:
            statement = mysql.insert(table).values(**values)
            statement = statement.on_duplicate_key_update(id=table.c.id)
        elif dialect == "sqlite":
            statement = sqlite.insert(table).values(**values)
            statement = statement.on_conflict_do_nothing(
                index_elements=(
                    "scope",
                    "subject_digest_sha256",
                    "window_kind",
                    "window_started_at",
                )
            )
        else:
            raise RuntimeError("platform rate limiter requires MySQL or SQLite")
        session.execute(statement)
        row = self._load_exact(
            session,
            scope=scope,
            digest=digest,
            window_kind=rule.window_kind,
            window_start=window_start,
        )
        if row is None:
            raise RuntimeError("platform rate-limit counter could not be locked")
        return row, row.id == candidate_id


# Preserve the narrower authentication name for existing login/factor callers.
PlatformAuthRateLimiter = PlatformAdminRateLimiter


def _as_utc(value: datetime) -> datetime:
    if not isinstance(value, datetime):
        raise TypeError("platform rate-limit time must be a datetime")
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
