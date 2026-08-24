"""Opaque, namespace-separated platform setup/session/recovery credentials."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass


PLATFORM_TOKEN_ENTROPY_BYTES = 32
PLATFORM_TOKEN_ENTROPY_BITS = PLATFORM_TOKEN_ENTROPY_BYTES * 8
PLATFORM_TOKEN_DIGEST_BYTES = 32

_SETUP_PREFIX = "imps1_"
_SESSION_PREFIX = "impa1_"
_CSRF_PREFIX = "impc1_"
_RECOVERY_PREFIX = "impr1_"
_ENCODED_RANDOM_LENGTH = 43
_ENCODED_RANDOM_PATTERN = re.compile(
    rf"[A-Za-z0-9_-]{{{_ENCODED_RANDOM_LENGTH}}}", re.ASCII
)
_DUMMY_DIGEST = bytes(PLATFORM_TOKEN_DIGEST_BYTES)


class PlatformCredentialError(ValueError):
    code = "PLATFORM_CREDENTIAL_INVALID"

    def __init__(self) -> None:
        super().__init__("The platform credential is invalid.")


@dataclass(frozen=True, slots=True, repr=False)
class IssuedPlatformToken:
    plaintext: str
    digest_sha256: bytes

    def __repr__(self) -> str:
        return "IssuedPlatformToken(<redacted>)"


def issue_setup_token() -> IssuedPlatformToken:
    return _issue(_SETUP_PREFIX)


def issue_platform_session_token() -> IssuedPlatformToken:
    return _issue(_SESSION_PREFIX)


def issue_platform_csrf_token() -> IssuedPlatformToken:
    return _issue(_CSRF_PREFIX)


def issue_recovery_code() -> IssuedPlatformToken:
    return _issue(_RECOVERY_PREFIX)


def digest_setup_token(token: object) -> bytes:
    return _digest(token, _SETUP_PREFIX)


def digest_platform_session_token(token: object) -> bytes:
    return _digest(token, _SESSION_PREFIX)


def digest_platform_csrf_token(token: object) -> bytes:
    return _digest(token, _CSRF_PREFIX)


def digest_recovery_code(token: object) -> bytes:
    return _digest(token, _RECOVERY_PREFIX)


def verify_setup_token(token: object, digest: object) -> bool:
    return _verify(token, digest, _SETUP_PREFIX)


def verify_platform_session_token(token: object, digest: object) -> bool:
    return _verify(token, digest, _SESSION_PREFIX)


def verify_platform_csrf_token(token: object, digest: object) -> bool:
    return _verify(token, digest, _CSRF_PREFIX)


def verify_recovery_code(token: object, digest: object) -> bool:
    return _verify(token, digest, _RECOVERY_PREFIX)


def _issue(prefix: str) -> IssuedPlatformToken:
    random_part = base64.urlsafe_b64encode(
        secrets.token_bytes(PLATFORM_TOKEN_ENTROPY_BYTES)
    ).rstrip(b"=")
    plaintext = prefix + random_part.decode("ascii")
    return IssuedPlatformToken(
        plaintext=plaintext,
        digest_sha256=hashlib.sha256(plaintext.encode("ascii")).digest(),
    )


def _has_shape(token: object, prefix: str) -> bool:
    return bool(
        isinstance(token, str)
        and token.startswith(prefix)
        and _ENCODED_RANDOM_PATTERN.fullmatch(token[len(prefix) :]) is not None
    )


def _digest(token: object, prefix: str) -> bytes:
    if not _has_shape(token, prefix):
        raise PlatformCredentialError()
    return hashlib.sha256(token.encode("ascii")).digest()


def _verify(token: object, digest: object, prefix: str) -> bool:
    token_is_valid = _has_shape(token, prefix)
    candidate = (
        hashlib.sha256(token.encode("ascii")).digest()
        if token_is_valid
        else _DUMMY_DIGEST
    )
    digest_is_valid = isinstance(digest, (bytes, bytearray, memoryview))
    normalized = bytes(digest) if digest_is_valid else _DUMMY_DIGEST
    digest_is_valid = digest_is_valid and len(normalized) == PLATFORM_TOKEN_DIGEST_BYTES
    if not digest_is_valid:
        normalized = _DUMMY_DIGEST
    matches = hmac.compare_digest(candidate, normalized)
    return bool(token_is_valid and digest_is_valid and matches)

