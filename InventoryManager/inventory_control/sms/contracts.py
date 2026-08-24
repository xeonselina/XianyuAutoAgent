"""Safe, versioned contracts at the SMS challenge boundary."""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass
from enum import Enum
from typing import Any, Protocol
from uuid import UUID

from inventory_control.action_payload import CanonicalActionPayload
from inventory_control.identity.phone import (
    CN_MOBILE_METADATA_VERSION,
    PHONE_NORMALIZATION_VERSION,
    PhoneIdentityNormalizer,
)


_REVISION_PATTERN = re.compile(r"[a-z0-9][a-z0-9._:/-]{0,127}", re.ASCII)
_UNKNOWN_SOURCE_BUCKET = "unknown"


class SmsPurpose(str, Enum):
    REGISTER = "register"
    LOGIN = "login"
    ACCEPT_INVITATION = "accept_invitation"
    INTEGRATION_CREDENTIAL_CHANGE = "integration_credential_change"
    SF_ACCOUNT_BIND = "sf_account_bind"
    SF_ACCOUNT_UNBIND = "sf_account_unbind"
    SF_ACCOUNT_REBIND = "sf_account_rebind"
    ADMIN_INVITATION = "admin_invitation"
    GRANT_ADMIN = "grant_admin"
    REVOKE_ADMIN = "revoke_admin"
    TENANT_DELETE = "tenant_delete"
    TENANT_DELETE_CANCEL = "tenant_delete_cancel"
    PHONE_CHANGE_OLD = "phone_change_old"
    PHONE_CHANGE_NEW = "phone_change_new"


class SmsDeliveryOutcome(str, Enum):
    SENT = "sent"
    SEND_UNKNOWN = "send_unknown"
    FAILED = "failed"


@dataclass(frozen=True, slots=True, repr=False)
class CanonicalSmsPhone:
    """A canonical phone carrying the normalizer and metadata revisions."""

    e164: str
    normalization_version: int
    metadata_version: str

    def __post_init__(self) -> None:
        normalizer = PhoneIdentityNormalizer()
        if (
            self.normalization_version != PHONE_NORMALIZATION_VERSION
            or self.metadata_version != CN_MOBILE_METADATA_VERSION
            or normalizer.normalize(self.e164) != self.e164
        ):
            raise ValueError("SMS phone identity is not a current canonical value")

    @classmethod
    def from_input(
        cls,
        raw_phone: str,
        *,
        normalizer: PhoneIdentityNormalizer | None = None,
    ) -> "CanonicalSmsPhone":
        selected = normalizer or PhoneIdentityNormalizer()
        return cls(
            e164=selected.normalize(raw_phone),
            normalization_version=selected.normalization_version,
            metadata_version=selected.metadata_version,
        )

    def __repr__(self) -> str:
        return (
            "CanonicalSmsPhone(<redacted>, "
            f"normalization_version={self.normalization_version!r}, "
            f"metadata_version={self.metadata_version!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class TrustedSourceBucket:
    """A source bucket constructed only by the trusted request boundary.

    No constructor in this module accepts headers.  Nginx/proxy trust handling
    must finish before application code constructs this value.
    """

    value: str

    def __post_init__(self) -> None:
        if self.value == _UNKNOWN_SOURCE_BUCKET:
            return
        prefix, separator, address = self.value.partition(":")
        if separator != ":" or prefix not in {"ip4", "ip6"}:
            raise ValueError("trusted source bucket is not canonical")
        parsed = ipaddress.ip_address(address)
        expected_prefix = "ip4" if parsed.version == 4 else "ip6"
        if prefix != expected_prefix or address != parsed.compressed:
            raise ValueError("trusted source bucket is not canonical")

    @classmethod
    def from_trusted_ip(cls, trusted_ip: str) -> "TrustedSourceBucket":
        parsed = ipaddress.ip_address(trusted_ip)
        prefix = "ip4" if parsed.version == 4 else "ip6"
        return cls(f"{prefix}:{parsed.compressed}")

    @classmethod
    def unknown(cls) -> "TrustedSourceBucket":
        return cls(_UNKNOWN_SOURCE_BUCKET)

    def __repr__(self) -> str:
        return "TrustedSourceBucket(<redacted>)"


@dataclass(frozen=True, slots=True, repr=False)
class SmsChallengeContext:
    purpose: SmsPurpose
    phone: CanonicalSmsPhone
    action_payload: CanonicalActionPayload
    authoritative_revision: str
    user_id: str | None = None
    tenant_id: str | None = None
    actor_session_id: str | None = None

    def __post_init__(self) -> None:
        try:
            purpose = SmsPurpose(self.purpose)
        except (TypeError, ValueError):
            raise ValueError("SMS challenge purpose is unsupported") from None
        object.__setattr__(self, "purpose", purpose)
        if not isinstance(self.phone, CanonicalSmsPhone):
            raise ValueError("SMS challenge requires a canonical phone")
        if not isinstance(self.action_payload, CanonicalActionPayload):
            raise ValueError("SMS challenge requires a canonical action payload")
        if (
            not isinstance(self.authoritative_revision, str)
            or _REVISION_PATTERN.fullmatch(self.authoritative_revision) is None
        ):
            raise ValueError("authoritative revision is invalid")
        for value in (self.user_id, self.tenant_id, self.actor_session_id):
            if value is not None:
                try:
                    parsed = UUID(value)
                except (AttributeError, TypeError, ValueError):
                    raise ValueError("SMS challenge context UUID is invalid") from None
                if str(parsed) != value.lower():
                    raise ValueError("SMS challenge context UUID is not canonical")

    def __repr__(self) -> str:
        return f"SmsChallengeContext(purpose={self.purpose.value!r}, <redacted>)"


@dataclass(frozen=True, slots=True)
class SmsPolicy:
    """Versioned deployment policy captured on every issued challenge."""

    version: int = 1
    challenge_ttl_seconds: int = 300
    resend_cooldown_seconds: int = 60
    max_wrong_attempts: int = 5
    phone_rolling_hour_limit: int = 5
    phone_shanghai_day_limit: int = 10
    source_rolling_hour_limit: int = 30
    source_shanghai_day_limit: int = 200

    def __post_init__(self) -> None:
        values = (
            self.version,
            self.challenge_ttl_seconds,
            self.resend_cooldown_seconds,
            self.max_wrong_attempts,
            self.phone_rolling_hour_limit,
            self.phone_shanghai_day_limit,
            self.source_rolling_hour_limit,
            self.source_shanghai_day_limit,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 1
            for value in values
        ):
            raise ValueError("SMS policy values must be positive integers")
        if (
            self.challenge_ttl_seconds > 300
            or self.resend_cooldown_seconds < 60
            or self.max_wrong_attempts > 5
            or self.phone_rolling_hour_limit > 5
            or self.phone_shanghai_day_limit > 10
            or self.source_rolling_hour_limit > 30
            or self.source_shanghai_day_limit > 200
        ):
            raise ValueError("SMS policy may not weaken the confirmed Core limits")


class SmsProviderRequest:
    """One plaintext-bearing value passed directly to a provider adapter."""

    __slots__ = (
        "challenge_id",
        "canonical_phone_e164",
        "purpose",
        "_plaintext_code",
    )

    def __init__(
        self,
        *,
        challenge_id: str,
        canonical_phone_e164: str,
        purpose: SmsPurpose,
        plaintext_code: str,
    ) -> None:
        if not (
            isinstance(plaintext_code, str)
            and len(plaintext_code) == 6
            and plaintext_code.isascii()
            and plaintext_code.isdigit()
        ):
            raise ValueError("SMS provider plaintext is invalid")
        self.challenge_id = challenge_id
        self.canonical_phone_e164 = canonical_phone_e164
        self.purpose = SmsPurpose(purpose)
        self._plaintext_code = plaintext_code

    def take_plaintext_code(self) -> str:
        """Return the code once to the adapter and erase this reference."""

        if self._plaintext_code is None:
            raise RuntimeError("SMS provider plaintext is no longer available")
        plaintext_code = self._plaintext_code
        self._plaintext_code = None
        return plaintext_code

    def _discard_plaintext(self) -> None:
        self._plaintext_code = None

    def __repr__(self) -> str:
        return (
            f"SmsProviderRequest(challenge_id={self.challenge_id!r}, "
            f"purpose={self.purpose.value!r}, <phone-and-code-redacted>)"
        )


class SmsProvider(Protocol):
    def send_verification(self, request: SmsProviderRequest) -> Any:
        """Consume ``request.take_plaintext_code()`` and submit one message."""


class PreparedSmsDelivery:
    """One-shot bridge from a committed challenge to the provider adapter."""

    __slots__ = (
        "challenge_id",
        "purpose",
        "_canonical_phone_e164",
        "_plaintext_code",
        "_dispatched",
    )

    def __init__(
        self,
        *,
        challenge_id: str,
        canonical_phone_e164: str,
        purpose: SmsPurpose,
        plaintext_code: str,
    ) -> None:
        self.challenge_id = challenge_id
        self.purpose = purpose
        self._canonical_phone_e164 = canonical_phone_e164
        self._plaintext_code = plaintext_code
        self._dispatched = False

    def dispatch_once(self, provider: SmsProvider) -> Any:
        """Pass plaintext to exactly one adapter invocation, clearing it first."""

        if self._dispatched or self._plaintext_code is None:
            raise RuntimeError("SMS delivery plaintext is no longer available")
        request = SmsProviderRequest(
            challenge_id=self.challenge_id,
            canonical_phone_e164=self._canonical_phone_e164,
            purpose=self.purpose,
            plaintext_code=self._plaintext_code,
        )
        self._dispatched = True
        self._plaintext_code = None
        try:
            return provider.send_verification(request)
        finally:
            request._discard_plaintext()

    def __repr__(self) -> str:
        state = "dispatched" if self._dispatched else "prepared"
        return (
            f"PreparedSmsDelivery(challenge_id={self.challenge_id!r}, "
            f"purpose={self.purpose.value!r}, state={state!r}, <redacted>)"
        )


@dataclass(frozen=True, slots=True)
class SmsVerificationResult:
    accepted: bool
    reason_code: str

