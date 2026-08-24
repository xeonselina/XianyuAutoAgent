"""Immutable, purpose-specific identity for one routed database engine."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Tuple, Union

UuidValue = Union[str, uuid.UUID]


class AccountKind(str, Enum):
    """Database account purposes that must never share an engine."""

    DML = "dml"
    PLATFORM_READ = "platform_read"


@dataclass(frozen=True, slots=True, kw_only=True)
class RoutingIdentity:
    """The complete immutable identity of a cached tenant engine.

    A tenant UUID is deliberately present in addition to the immutable database
    UUID. The credential and route versions ensure an engine cannot survive a
    published route or credential transition merely because its tenant is the
    same.
    """

    tenant_uuid: UuidValue
    account_kind: AccountKind
    database_uuid: UuidValue
    username: str
    credential_generation: int
    root_key_version: int
    derivation_version: int
    route_version: int

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "tenant_uuid",
            _normalize_uuid(self.tenant_uuid, "tenant UUID"),
        )
        object.__setattr__(
            self,
            "database_uuid",
            _normalize_uuid(self.database_uuid, "database UUID"),
        )
        try:
            account_kind = AccountKind(self.account_kind)
        except (TypeError, ValueError):
            raise ValueError("account kind is unsupported") from None
        object.__setattr__(self, "account_kind", account_kind)

        if (
            not isinstance(self.username, str)
            or not self.username
            or self.username.strip() != self.username
            or "\x00" in self.username
        ):
            raise ValueError("username must be a non-empty canonical string")

        for field_name in (
            "credential_generation",
            "root_key_version",
            "derivation_version",
            "route_version",
        ):
            _require_positive_integer(getattr(self, field_name), field_name)

    @property
    def purpose_scope(self) -> Tuple[uuid.UUID, AccountKind]:
        """Return the database/account-purpose slot used for active retirement."""

        return self.database_uuid, self.account_kind


def normalize_uuid(value: UuidValue, label: str = "UUID") -> uuid.UUID:
    """Normalize a public cache selector without retaining ambiguous strings."""

    return _normalize_uuid(value, label)


def normalize_account_kind(value: AccountKind) -> AccountKind:
    try:
        return AccountKind(value)
    except (TypeError, ValueError):
        raise ValueError("account kind is unsupported") from None


def _normalize_uuid(value: UuidValue, label: str) -> uuid.UUID:
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except (ValueError, AttributeError):
            pass
    raise ValueError(f"{label} is invalid")


def _require_positive_integer(value: int, label: str) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
