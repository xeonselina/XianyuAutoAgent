"""SaaS Core member-seat arithmetic."""

from __future__ import annotations

from dataclasses import dataclass

from .errors import InvalidSeatCountError, SeatLimitExceededError


CORE_MEMBER_SEAT_CAP = 10


def _require_non_negative_integer(field_name: str, value: object) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise InvalidSeatCountError(
            f"{field_name} must be a non-negative integer"
        )


@dataclass(frozen=True, slots=True)
class SeatUsage:
    """Current-read counts for the one Core commercial quota.

    Callers supply only memberships that satisfy the active predicate and only
    pending invitations whose expiry is later than current database time.
    """

    active_memberships: int
    unexpired_pending_invitations: int

    def __post_init__(self) -> None:
        _require_non_negative_integer(
            "active_memberships", self.active_memberships
        )
        _require_non_negative_integer(
            "unexpired_pending_invitations",
            self.unexpired_pending_invitations,
        )

    @property
    def occupied_seats(self) -> int:
        return self.active_memberships + self.unexpired_pending_invitations

    @property
    def remaining_seats(self) -> int:
        return CORE_MEMBER_SEAT_CAP - self.occupied_seats

    @property
    def is_within_cap(self) -> bool:
        return self.occupied_seats <= CORE_MEMBER_SEAT_CAP


def has_seat_capacity(usage: SeatUsage, additional_seats: int = 1) -> bool:
    """Return whether a current-read allocation stays within the fixed cap."""

    if not isinstance(usage, SeatUsage):
        raise TypeError("usage must be a SeatUsage")
    _require_non_negative_integer("additional_seats", additional_seats)
    return usage.occupied_seats + additional_seats <= CORE_MEMBER_SEAT_CAP


def require_seat_capacity(usage: SeatUsage, additional_seats: int = 1) -> None:
    """Reject an allocation that would commit more than ten occupied seats."""

    if not has_seat_capacity(usage, additional_seats):
        raise SeatLimitExceededError("Core member seat limit exceeded")
