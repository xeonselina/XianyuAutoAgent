"""Purpose-separated authenticated encryption for redemption bearers."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from inventory_control.crypto import (
    CryptoAuthenticationError,
    CryptoCodecV1,
    CryptoConfigurationError,
    EncryptedEnvelope,
    RootKey,
    decrypt_record,
    encrypt_record,
)
from inventory_control.crypto.codec import UuidValue

from .codes import (
    CanonicalRedemptionCode,
    InvalidRedemptionCodeError,
    canonicalize_redemption_code,
)


REDEMPTION_CODE_SECRET_PURPOSE = (
    "inventory-manager/redemption-code-secret/v1"
)
_UTC_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


@dataclass(frozen=True, slots=True)
class RedemptionCodeSecretContext:
    """Immutable code terms authenticated alongside encrypted plaintext."""

    code_uuid: UuidValue
    crypto_context_uuid: UuidValue
    batch_uuid: UuidValue
    plan_revision_uuid: UuidValue
    entitlements_schema_version: int
    entitlements_digest_sha256: bytes = field(repr=False)
    service_duration_seconds: int
    redeem_before: datetime
    created_under_recovery_run_uuid: UuidValue
    secret_revision: int = 1

    def __post_init__(self) -> None:
        for value in (
            self.code_uuid,
            self.crypto_context_uuid,
            self.batch_uuid,
            self.plan_revision_uuid,
            self.created_under_recovery_run_uuid,
        ):
            CryptoCodecV1.uuid_bytes(value)
        CryptoCodecV1.uint64(self.entitlements_schema_version)
        CryptoCodecV1.uint64(self.service_duration_seconds)
        CryptoCodecV1.uint64(self.secret_revision)
        if (
            not isinstance(self.entitlements_digest_sha256, bytes)
            or len(self.entitlements_digest_sha256) != 32
        ):
            raise CryptoConfigurationError("entitlement digest is invalid")
        if not isinstance(self.redeem_before, datetime) or (
            self.redeem_before.tzinfo is None
            or self.redeem_before.utcoffset() is None
        ):
            raise CryptoConfigurationError("redemption deadline must be timezone-aware")
        redeem_before_utc = self.redeem_before.astimezone(timezone.utc)
        _datetime_microseconds(redeem_before_utc)
        object.__setattr__(self, "redeem_before", redeem_before_utc)

    def canonical_aad(self) -> bytes:
        """Encode every immutable authority field in a fixed typed order."""

        return CryptoCodecV1.encode_parts(
            CryptoCodecV1.domain(REDEMPTION_CODE_SECRET_PURPOSE),
            CryptoCodecV1.uuid_bytes(self.code_uuid),
            CryptoCodecV1.uuid_bytes(self.crypto_context_uuid),
            CryptoCodecV1.uuid_bytes(self.batch_uuid),
            CryptoCodecV1.uuid_bytes(self.plan_revision_uuid),
            CryptoCodecV1.uint64(self.entitlements_schema_version),
            self.entitlements_digest_sha256,
            CryptoCodecV1.uint64(self.service_duration_seconds),
            CryptoCodecV1.uint64(_datetime_microseconds(self.redeem_before)),
            CryptoCodecV1.uuid_bytes(self.created_under_recovery_run_uuid),
            CryptoCodecV1.uint64(self.secret_revision),
        )


def encrypt_redemption_code(
    *,
    root_key: RootKey,
    context: RedemptionCodeSecretContext,
    code: object,
) -> EncryptedEnvelope:
    """Canonicalize and encrypt one bearer with a new random GCM nonce."""

    if not isinstance(context, RedemptionCodeSecretContext):
        raise CryptoConfigurationError("redemption code context is invalid")
    canonical = (
        code
        if isinstance(code, CanonicalRedemptionCode)
        else canonicalize_redemption_code(code)
    )
    return encrypt_record(
        root_key=root_key,
        purpose=REDEMPTION_CODE_SECRET_PURPOSE,
        record_uuid=context.crypto_context_uuid,
        revision=context.secret_revision,
        canonical_aad=context.canonical_aad(),
        plaintext=canonical.plaintext_bytes(),
    )


def decrypt_redemption_code(
    *,
    root_key: RootKey,
    context: RedemptionCodeSecretContext,
    envelope: EncryptedEnvelope,
) -> CanonicalRedemptionCode:
    """Authenticate code terms and return an exact canonical bearer."""

    if not isinstance(context, RedemptionCodeSecretContext):
        raise CryptoConfigurationError("redemption code context is invalid")
    plaintext = decrypt_record(
        root_key=root_key,
        envelope=envelope,
        purpose=REDEMPTION_CODE_SECRET_PURPOSE,
        record_uuid=context.crypto_context_uuid,
        revision=context.secret_revision,
        canonical_aad=context.canonical_aad(),
    )
    try:
        decoded = plaintext.decode("ascii")
        return CanonicalRedemptionCode(decoded)
    except (UnicodeDecodeError, InvalidRedemptionCodeError):
        raise CryptoAuthenticationError("record authentication failed") from None


def _datetime_microseconds(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() is None:
        raise CryptoConfigurationError("redemption deadline must be timezone-aware")
    delta = value.astimezone(timezone.utc) - _UTC_EPOCH
    microseconds = (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )
    CryptoCodecV1.uint64(microseconds)
    return microseconds
