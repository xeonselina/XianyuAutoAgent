"""Short-lived, purpose-separated D53 service-period confirmations."""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from inventory_control.crypto import CryptoCodecV1, RootKey

from .token_codec import canonical_json, join_signed_token, split_signed_token


SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_VERSION = 1
SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_MAX_TTL_SECONDS = 300
SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_PURPOSE = "platform:d53-confirmation:v1"
_MAX_TOKEN_BYTES = 16_384


class SubscriptionAdjustmentConfirmationError(ValueError):
    """One stable rejection for malformed, changed, or stale confirmation."""


@dataclass(frozen=True, slots=True)
class SubscriptionAdjustmentFences:
    """All mutable D53 authority facts captured by a preview."""

    tenant_uuid: UUID
    tenant_row_version: int
    tenant_access_version: int
    subscription_uuid: UUID
    subscription_row_version: int
    recovery_run_uuid: UUID
    recovery_run_row_version: int
    recovery_hold_uuid: UUID
    recovery_hold_revision: int
    recovery_hold_row_version: int
    deletion_request_uuid: UUID | None = None
    deletion_request_revision: int | None = None
    deletion_row_version: int | None = None
    suspension_uuid: UUID | None = None
    suspension_row_version: int | None = None
    suspension_generation: int | None = None
    suspension_action_uuid: UUID | None = None
    suspension_action_row_version: int | None = None

    def __post_init__(self) -> None:
        for value in (
            self.tenant_uuid,
            self.subscription_uuid,
            self.recovery_run_uuid,
            self.recovery_hold_uuid,
        ):
            if not isinstance(value, UUID):
                raise SubscriptionAdjustmentConfirmationError(
                    "adjustment confirmation fences are invalid"
                )
        for value in (
            self.tenant_row_version,
            self.tenant_access_version,
            self.subscription_row_version,
            self.recovery_run_row_version,
            self.recovery_hold_revision,
            self.recovery_hold_row_version,
        ):
            _require_positive_int(value)
        deletion_values = (
            self.deletion_request_uuid,
            self.deletion_request_revision,
            self.deletion_row_version,
        )
        if any(value is None for value in deletion_values) != all(
            value is None for value in deletion_values
        ):
            raise SubscriptionAdjustmentConfirmationError(
                "adjustment deletion fences are incomplete"
            )
        if self.deletion_request_uuid is not None:
            if not isinstance(self.deletion_request_uuid, UUID):
                raise SubscriptionAdjustmentConfirmationError(
                    "adjustment deletion fences are invalid"
                )
            _require_positive_int(self.deletion_request_revision)
            _require_positive_int(self.deletion_row_version)
        suspension_values = (
            self.suspension_uuid,
            self.suspension_row_version,
            self.suspension_generation,
            self.suspension_action_uuid,
            self.suspension_action_row_version,
        )
        if any(value is None for value in suspension_values) != all(
            value is None for value in suspension_values
        ):
            raise SubscriptionAdjustmentConfirmationError(
                "adjustment suspension fences are incomplete"
            )
        if self.suspension_uuid is not None:
            if not isinstance(self.suspension_uuid, UUID) or not isinstance(
                self.suspension_action_uuid, UUID
            ):
                raise SubscriptionAdjustmentConfirmationError(
                    "adjustment suspension fences are invalid"
                )
            _require_positive_int(self.suspension_row_version)
            _require_positive_int(self.suspension_generation)
            _require_positive_int(self.suspension_action_row_version)


@dataclass(frozen=True, slots=True)
class VerifiedSubscriptionAdjustmentConfirmation:
    action_uuid: UUID
    fences: SubscriptionAdjustmentFences
    request_digest: bytes = field(repr=False)
    preview_digest: bytes = field(repr=False)
    issued_at: datetime
    expires_at: datetime


def issue_subscription_adjustment_confirmation(
    *,
    root_key: RootKey,
    fences: SubscriptionAdjustmentFences,
    platform_actor_uuid: UUID,
    platform_session_uuid: UUID,
    platform_auth_version: int,
    request_digest: bytes,
    preview_digest: bytes,
    database_now: datetime,
    ttl: timedelta = timedelta(
        seconds=SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_MAX_TTL_SECONDS
    ),
    action_uuid: UUID | None = None,
) -> str:
    """Issue a confirmation that is neither an authorization nor an MFA proof."""

    try:
        _require_root_key(root_key)
        if not isinstance(fences, SubscriptionAdjustmentFences):
            raise ValueError
        if not isinstance(platform_actor_uuid, UUID) or not isinstance(
            platform_session_uuid, UUID
        ):
            raise ValueError
        _require_positive_int(platform_auth_version)
        request_digest = _digest32(request_digest)
        preview_digest = _digest32(preview_digest)
        issued_at = _utc_second(database_now)
        if (
            not isinstance(ttl, timedelta)
            or ttl <= timedelta(0)
            or ttl
            > timedelta(
                seconds=SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_MAX_TTL_SECONDS
            )
            or ttl.microseconds != 0
        ):
            raise ValueError
        selected_action = action_uuid or uuid4()
        if not isinstance(selected_action, UUID):
            raise ValueError
        expires_at = issued_at + ttl
        payload = _payload(
            fences=fences,
            platform_actor_uuid=platform_actor_uuid,
            platform_session_uuid=platform_session_uuid,
            platform_auth_version=platform_auth_version,
            request_digest=request_digest,
            preview_digest=preview_digest,
            action_uuid=selected_action,
            root_key_version=root_key.version,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        encoded = canonical_json(payload)
        signature = hmac.digest(
            _derive_signing_key(
                root_key=root_key,
                action_uuid=selected_action,
            ),
            encoded,
            "sha256",
        )
        return join_signed_token(encoded, signature)
    except (TypeError, ValueError):
        raise SubscriptionAdjustmentConfirmationError(
            "adjustment confirmation input is invalid"
        ) from None


def verify_subscription_adjustment_confirmation(
    *,
    token: object,
    root_key: RootKey,
    expected_platform_actor_uuid: UUID,
    expected_platform_session_uuid: UUID,
    expected_platform_auth_version: int,
    expected_request_digest: bytes,
    database_now: datetime,
) -> VerifiedSubscriptionAdjustmentConfirmation:
    """Authenticate a token against the current platform session and request."""

    try:
        _require_root_key(root_key)
        if not isinstance(expected_platform_actor_uuid, UUID) or not isinstance(
            expected_platform_session_uuid, UUID
        ):
            raise ValueError
        _require_positive_int(expected_platform_auth_version)
        expected_digest = _digest32(expected_request_digest)
        encoded, signature = split_signed_token(
            token,
            maximum_bytes=_MAX_TOKEN_BYTES,
        )
        payload = json.loads(encoded)
        if not isinstance(payload, dict) or canonical_json(payload) != encoded:
            raise ValueError
        action_uuid = UUID(payload["action_uuid"])
        expected_signature = hmac.digest(
            _derive_signing_key(root_key=root_key, action_uuid=action_uuid),
            encoded,
            "sha256",
        )
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError
        parsed = _parse_payload(payload)
        now = _utc_second(database_now)
        if (
            payload["confirmation_version"]
            != SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_VERSION
            or payload["root_key_version"] != root_key.version
            or parsed["platform_actor_uuid"]
            != expected_platform_actor_uuid
            or parsed["platform_session_uuid"]
            != expected_platform_session_uuid
            or parsed["platform_auth_version"]
            != expected_platform_auth_version
            or not hmac.compare_digest(parsed["request_digest"], expected_digest)
            or parsed["issued_at"] > now
            or parsed["expires_at"] <= now
            or parsed["expires_at"] - parsed["issued_at"]
            > timedelta(
                seconds=SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_MAX_TTL_SECONDS
            )
        ):
            raise ValueError
        return VerifiedSubscriptionAdjustmentConfirmation(
            action_uuid=action_uuid,
            fences=parsed["fences"],
            request_digest=parsed["request_digest"],
            preview_digest=parsed["preview_digest"],
            issued_at=parsed["issued_at"],
            expires_at=parsed["expires_at"],
        )
    except (
        KeyError,
        TypeError,
        ValueError,
        UnicodeError,
        json.JSONDecodeError,
    ):
        raise SubscriptionAdjustmentConfirmationError(
            "adjustment confirmation is invalid or stale"
        ) from None


def subscription_adjustment_preview_digest(
    *,
    database_effective_at: datetime,
    calculation_base_at: datetime,
    before_expires_at: datetime,
    after_expires_at: datetime,
    before_status: str,
    after_status: str,
) -> bytes:
    """Hash the exact human-visible preview without accepting an after value."""

    if before_status not in {"active", "expired"} or after_status not in {
        "active",
        "expired",
    }:
        raise SubscriptionAdjustmentConfirmationError(
            "adjustment preview is invalid"
        )
    payload = {
        "after_expires_at": _utc_iso(after_expires_at),
        "after_status": after_status,
        "before_expires_at": _utc_iso(before_expires_at),
        "before_status": before_status,
        "calculation_base_at": _utc_iso(calculation_base_at),
        "database_effective_at": _utc_iso(database_effective_at),
    }
    return hashlib.sha256(canonical_json(payload)).digest()


def _payload(
    *,
    fences: SubscriptionAdjustmentFences,
    platform_actor_uuid: UUID,
    platform_session_uuid: UUID,
    platform_auth_version: int,
    request_digest: bytes,
    preview_digest: bytes,
    action_uuid: UUID,
    root_key_version: int,
    issued_at: datetime,
    expires_at: datetime,
) -> dict[str, object]:
    return {
        "action_uuid": str(action_uuid),
        "confirmation_version": SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_VERSION,
        "deletion_request_revision": fences.deletion_request_revision,
        "deletion_request_uuid": _optional_uuid(fences.deletion_request_uuid),
        "deletion_row_version": fences.deletion_row_version,
        "expires_at": int(expires_at.timestamp()),
        "issued_at": int(issued_at.timestamp()),
        "platform_actor_uuid": str(platform_actor_uuid),
        "platform_auth_version": platform_auth_version,
        "platform_session_uuid": str(platform_session_uuid),
        "preview_digest": preview_digest.hex(),
        "recovery_hold_revision": fences.recovery_hold_revision,
        "recovery_hold_row_version": fences.recovery_hold_row_version,
        "recovery_hold_uuid": str(fences.recovery_hold_uuid),
        "recovery_run_row_version": fences.recovery_run_row_version,
        "recovery_run_uuid": str(fences.recovery_run_uuid),
        "request_digest": request_digest.hex(),
        "root_key_version": root_key_version,
        "subscription_row_version": fences.subscription_row_version,
        "subscription_uuid": str(fences.subscription_uuid),
        "suspension_action_row_version": fences.suspension_action_row_version,
        "suspension_action_uuid": _optional_uuid(
            fences.suspension_action_uuid
        ),
        "suspension_generation": fences.suspension_generation,
        "suspension_row_version": fences.suspension_row_version,
        "suspension_uuid": _optional_uuid(fences.suspension_uuid),
        "tenant_access_version": fences.tenant_access_version,
        "tenant_row_version": fences.tenant_row_version,
        "tenant_uuid": str(fences.tenant_uuid),
    }


def _parse_payload(payload: dict[str, object]) -> dict[str, object]:
    expected_keys = {
        "action_uuid",
        "confirmation_version",
        "deletion_request_revision",
        "deletion_request_uuid",
        "deletion_row_version",
        "expires_at",
        "issued_at",
        "platform_actor_uuid",
        "platform_auth_version",
        "platform_session_uuid",
        "preview_digest",
        "recovery_hold_revision",
        "recovery_hold_row_version",
        "recovery_hold_uuid",
        "recovery_run_row_version",
        "recovery_run_uuid",
        "request_digest",
        "root_key_version",
        "subscription_row_version",
        "subscription_uuid",
        "suspension_action_row_version",
        "suspension_action_uuid",
        "suspension_generation",
        "suspension_row_version",
        "suspension_uuid",
        "tenant_access_version",
        "tenant_row_version",
        "tenant_uuid",
    }
    if set(payload) != expected_keys:
        raise ValueError
    fences = SubscriptionAdjustmentFences(
        tenant_uuid=UUID(payload["tenant_uuid"]),
        tenant_row_version=_strict_positive_int(payload["tenant_row_version"]),
        tenant_access_version=_strict_positive_int(
            payload["tenant_access_version"]
        ),
        subscription_uuid=UUID(payload["subscription_uuid"]),
        subscription_row_version=_strict_positive_int(
            payload["subscription_row_version"]
        ),
        recovery_run_uuid=UUID(payload["recovery_run_uuid"]),
        recovery_run_row_version=_strict_positive_int(
            payload["recovery_run_row_version"]
        ),
        recovery_hold_uuid=UUID(payload["recovery_hold_uuid"]),
        recovery_hold_revision=_strict_positive_int(
            payload["recovery_hold_revision"]
        ),
        recovery_hold_row_version=_strict_positive_int(
            payload["recovery_hold_row_version"]
        ),
        deletion_request_uuid=_nullable_uuid(payload["deletion_request_uuid"]),
        deletion_request_revision=_nullable_positive_int(
            payload["deletion_request_revision"]
        ),
        deletion_row_version=_nullable_positive_int(
            payload["deletion_row_version"]
        ),
        suspension_uuid=_nullable_uuid(payload["suspension_uuid"]),
        suspension_row_version=_nullable_positive_int(
            payload["suspension_row_version"]
        ),
        suspension_generation=_nullable_positive_int(
            payload["suspension_generation"]
        ),
        suspension_action_uuid=_nullable_uuid(
            payload["suspension_action_uuid"]
        ),
        suspension_action_row_version=_nullable_positive_int(
            payload["suspension_action_row_version"]
        ),
    )
    return {
        "fences": fences,
        "platform_actor_uuid": UUID(payload["platform_actor_uuid"]),
        "platform_session_uuid": UUID(payload["platform_session_uuid"]),
        "platform_auth_version": _strict_positive_int(
            payload["platform_auth_version"]
        ),
        "request_digest": _hex_digest(payload["request_digest"]),
        "preview_digest": _hex_digest(payload["preview_digest"]),
        "issued_at": datetime.fromtimestamp(
            _strict_positive_int(payload["issued_at"]), timezone.utc
        ),
        "expires_at": datetime.fromtimestamp(
            _strict_positive_int(payload["expires_at"]), timezone.utc
        ),
    }


def _derive_signing_key(*, root_key: RootKey, action_uuid: UUID) -> bytes:
    action_bytes = CryptoCodecV1.uuid_bytes(action_uuid)
    info = CryptoCodecV1.encode_parts(
        CryptoCodecV1.ascii_text(SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_PURPOSE),
        action_bytes,
        CryptoCodecV1.uint64(root_key.version),
        CryptoCodecV1.uint64(SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_VERSION),
    )
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=action_bytes,
        info=info,
    ).derive(root_key._material_bytes())


def _require_root_key(value: object) -> RootKey:
    if not isinstance(value, RootKey):
        raise ValueError
    return value


def _require_positive_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise SubscriptionAdjustmentConfirmationError(
            "adjustment confirmation revision is invalid"
        )
    return value


def _strict_positive_int(value: object) -> int:
    try:
        return _require_positive_int(value)
    except SubscriptionAdjustmentConfirmationError:
        raise ValueError from None


def _nullable_positive_int(value: object) -> int | None:
    return None if value is None else _strict_positive_int(value)


def _digest32(value: object) -> bytes:
    if not isinstance(value, bytes) or len(value) != 32:
        raise ValueError
    return bytes(value)


def _hex_digest(value: object) -> bytes:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError
    decoded = bytes.fromhex(value)
    if decoded.hex() != value:
        raise ValueError
    return _digest32(decoded)


def _optional_uuid(value: UUID | None) -> str | None:
    return str(value) if value is not None else None


def _nullable_uuid(value: object) -> UUID | None:
    return None if value is None else UUID(value)


def _utc_second(value: object) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError
    return value.astimezone(timezone.utc).replace(microsecond=0)


def _utc_iso(value: object) -> str:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise SubscriptionAdjustmentConfirmationError(
            "adjustment preview time is invalid"
        )
    return value.astimezone(timezone.utc).isoformat(timespec="microseconds")


__all__ = [
    "SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_MAX_TTL_SECONDS",
    "SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_PURPOSE",
    "SUBSCRIPTION_ADJUSTMENT_CONFIRMATION_VERSION",
    "SubscriptionAdjustmentConfirmationError",
    "SubscriptionAdjustmentFences",
    "VerifiedSubscriptionAdjustmentConfirmation",
    "issue_subscription_adjustment_confirmation",
    "subscription_adjustment_preview_digest",
    "verify_subscription_adjustment_confirmation",
]
