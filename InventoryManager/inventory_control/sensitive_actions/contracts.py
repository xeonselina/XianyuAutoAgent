"""Typed, payload-redacting contracts for D48 sensitive action intents."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from uuid import UUID

from inventory_control.action_payload import CanonicalActionPayload
from inventory_control.sms import PreparedSmsDelivery, SmsPurpose


SENSITIVE_ACTION_CANONICALIZATION_VERSION = 1
_IDENTIFIER = re.compile(r"[a-z][a-z0-9_.-]{0,63}", re.ASCII)
_REVISION = re.compile(r"[a-z0-9][a-z0-9._:/-]{0,127}", re.ASCII)
_D48_PURPOSES = frozenset(
    {
        SmsPurpose.INTEGRATION_CREDENTIAL_CHANGE,
        SmsPurpose.SF_ACCOUNT_BIND,
        SmsPurpose.SF_ACCOUNT_UNBIND,
        SmsPurpose.SF_ACCOUNT_REBIND,
        SmsPurpose.ADMIN_INVITATION,
        SmsPurpose.GRANT_ADMIN,
        SmsPurpose.REVOKE_ADMIN,
        SmsPurpose.TENANT_DELETE,
        SmsPurpose.TENANT_DELETE_CANCEL,
        SmsPurpose.PHONE_CHANGE_OLD,
        SmsPurpose.PHONE_CHANGE_NEW,
    }
)


class SensitiveActionChallengeRole(str, Enum):
    PRIMARY = "primary"
    OLD_PHONE = "old_phone"
    NEW_PHONE = "new_phone"


class SensitiveActionStatus(str, Enum):
    PENDING_VERIFICATION = "pending_verification"
    AUTHORIZED = "authorized"
    EXECUTING = "executing"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class SensitiveActionError(RuntimeError):
    pass


class SensitiveActionInputError(SensitiveActionError):
    pass


class SensitiveActionConflictError(SensitiveActionError):
    pass


@dataclass(frozen=True, slots=True)
class PreparedSensitiveAction:
    intent_uuid: UUID
    challenge_uuid: UUID
    expires_at: datetime
    delivery: PreparedSmsDelivery | None
    replayed: bool


@dataclass(frozen=True, slots=True)
class PreparedSensitivePhoneChange:
    """The two fixed-role deliveries for one phone-change intent."""

    intent_uuid: UUID
    old_challenge_uuid: UUID
    new_challenge_uuid: UUID
    expires_at: datetime
    deliveries: tuple[PreparedSmsDelivery, ...]
    replayed: bool


@dataclass(frozen=True, slots=True, repr=False)
class AuthorizedSensitiveAction:
    context: SensitiveActionContext
    challenge_uuid: UUID
    intent_row_version: int

    def __repr__(self) -> str:
        return (
            f"AuthorizedSensitiveAction(intent_uuid="
            f"{self.context.intent_uuid!r}, <authorization-redacted>)"
        )


@dataclass(frozen=True, slots=True)
class SensitiveActionAuthorizationResult:
    accepted: bool
    reason_code: str
    authorization: AuthorizedSensitiveAction | None = None
    already_succeeded: bool = False


@dataclass(frozen=True, slots=True, repr=False)
class SensitiveActionContext:
    """All immutable facts authenticated by one intent context MAC."""

    intent_uuid: UUID
    tenant_uuid: UUID
    actor_user_uuid: UUID
    actor_session_uuid: UUID
    purpose: SmsPurpose
    action_subtype: str
    target_type: str
    target_uuid: UUID
    expected_target_revision: str
    action_payload: CanonicalActionPayload
    idempotency_key: str
    canonicalization_version: int = SENSITIVE_ACTION_CANONICALIZATION_VERSION

    def __post_init__(self) -> None:
        identifiers = (
            self.intent_uuid,
            self.tenant_uuid,
            self.actor_user_uuid,
            self.actor_session_uuid,
            self.target_uuid,
        )
        if any(not isinstance(value, UUID) for value in identifiers):
            raise TypeError("sensitive action identifiers must be UUIDs")
        try:
            purpose = SmsPurpose(self.purpose)
        except (TypeError, ValueError):
            raise ValueError("sensitive action purpose is unsupported") from None
        if purpose not in _D48_PURPOSES:
            raise ValueError("sensitive action purpose is not a D48 purpose")
        object.__setattr__(self, "purpose", purpose)
        for name, value in (
            ("action_subtype", self.action_subtype),
            ("target_type", self.target_type),
        ):
            if not isinstance(value, str) or _IDENTIFIER.fullmatch(value) is None:
                raise ValueError(f"{name} is invalid")
        if (
            not isinstance(self.expected_target_revision, str)
            or _REVISION.fullmatch(self.expected_target_revision) is None
        ):
            raise ValueError("expected target revision is invalid")
        if not isinstance(self.action_payload, CanonicalActionPayload):
            raise TypeError("sensitive action payload is not canonical")
        if (
            not isinstance(self.idempotency_key, str)
            or not 1 <= len(self.idempotency_key) <= 128
            or not self.idempotency_key.isascii()
            or any(not 0x21 <= ord(value) <= 0x7E for value in self.idempotency_key)
        ):
            raise ValueError("sensitive action idempotency key is invalid")
        if self.canonicalization_version != SENSITIVE_ACTION_CANONICALIZATION_VERSION:
            raise ValueError("sensitive action canonicalization version is unsupported")

    def __repr__(self) -> str:
        return (
            f"SensitiveActionContext(intent_uuid={self.intent_uuid!r}, "
            f"purpose={self.purpose.value!r}, action_subtype="
            f"{self.action_subtype!r}, <payload-and-target-redacted>)"
        )


__all__ = [
    "SENSITIVE_ACTION_CANONICALIZATION_VERSION",
    "AuthorizedSensitiveAction",
    "PreparedSensitiveAction",
    "PreparedSensitivePhoneChange",
    "SensitiveActionChallengeRole",
    "SensitiveActionConflictError",
    "SensitiveActionContext",
    "SensitiveActionError",
    "SensitiveActionInputError",
    "SensitiveActionAuthorizationResult",
    "SensitiveActionStatus",
]
