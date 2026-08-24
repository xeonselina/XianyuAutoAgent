"""Root-key-derived MAC for payload-redacting D48 request contexts."""

from __future__ import annotations

import hmac

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from inventory_control.crypto import CryptoCodecV1, RootKey
from inventory_control.crypto.errors import CryptoConfigurationError

from .contracts import SensitiveActionContext


SENSITIVE_ACTION_CONTEXT_MAC_VERSION = 1
_KEY_BYTES = 32
_KEY_DOMAIN = "inventory-manager/sensitive-action-context-key/v1"
_BINDING_DOMAIN = "inventory-manager/sensitive-action-context-binding/v1"


def calculate_sensitive_action_context_mac(
    *,
    root_key: RootKey,
    context: SensitiveActionContext,
    mac_version: int = SENSITIVE_ACTION_CONTEXT_MAC_VERSION,
) -> bytes:
    """Authenticate the exact intent context without persisting its payload."""

    if not isinstance(root_key, RootKey):
        raise CryptoConfigurationError("sensitive action root key is invalid")
    if not isinstance(context, SensitiveActionContext):
        raise CryptoConfigurationError("sensitive action context is invalid")
    if mac_version != SENSITIVE_ACTION_CONTEXT_MAC_VERSION:
        raise CryptoConfigurationError(
            "sensitive action context MAC version is unsupported"
        )

    intent_bytes = CryptoCodecV1.uuid_bytes(context.intent_uuid)
    key = HKDF(
        algorithm=hashes.SHA256(),
        length=_KEY_BYTES,
        salt=intent_bytes,
        info=CryptoCodecV1.encode_parts(
            CryptoCodecV1.domain(_KEY_DOMAIN),
            intent_bytes,
            CryptoCodecV1.uint64(root_key.version),
            CryptoCodecV1.uint64(mac_version),
        ),
    ).derive(root_key._material_bytes())
    message = CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain(_BINDING_DOMAIN),
        intent_bytes,
        CryptoCodecV1.uuid_bytes(context.tenant_uuid),
        CryptoCodecV1.uuid_bytes(context.actor_user_uuid),
        CryptoCodecV1.uuid_bytes(context.actor_session_uuid),
        CryptoCodecV1.ascii_text(context.purpose.value),
        CryptoCodecV1.ascii_text(context.action_subtype),
        CryptoCodecV1.ascii_text(context.target_type),
        CryptoCodecV1.uuid_bytes(context.target_uuid),
        CryptoCodecV1.ascii_text(context.expected_target_revision),
        context.action_payload.digest_sha256,
        CryptoCodecV1.ascii_text(context.idempotency_key),
        CryptoCodecV1.uint64(context.canonicalization_version),
        CryptoCodecV1.uint64(root_key.version),
        CryptoCodecV1.uint64(mac_version),
    )
    return hmac.digest(key, message, "sha256")


def verify_sensitive_action_context_mac(
    *,
    root_key: RootKey,
    context: SensitiveActionContext,
    expected_mac: bytes,
    mac_version: int,
) -> bool:
    """Compare a stored context MAC in constant time, failing closed."""

    if not isinstance(expected_mac, bytes) or len(expected_mac) != 32:
        return False
    try:
        candidate = calculate_sensitive_action_context_mac(
            root_key=root_key,
            context=context,
            mac_version=mac_version,
        )
    except (CryptoConfigurationError, TypeError, ValueError):
        return False
    return hmac.compare_digest(candidate, expected_mac)


__all__ = [
    "SENSITIVE_ACTION_CONTEXT_MAC_VERSION",
    "calculate_sensitive_action_context_mac",
    "verify_sensitive_action_context_mac",
]
