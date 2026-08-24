"""Opaque browser-session and per-session CSRF token primitives."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass

from .errors import InvalidOpaqueTokenError


TOKEN_ENTROPY_BYTES = 32
TOKEN_ENTROPY_BITS = TOKEN_ENTROPY_BYTES * 8
TOKEN_DIGEST_BYTES = hashlib.sha256().digest_size

_SESSION_PREFIX = "ims1_"
_CSRF_PREFIX = "imc1_"
_ENCODED_RANDOM_LENGTH = 43
_ENCODED_RANDOM_PATTERN = re.compile(
    rf"[A-Za-z0-9_-]{{{_ENCODED_RANDOM_LENGTH}}}", flags=re.ASCII
)
_DUMMY_DIGEST = bytes(TOKEN_DIGEST_BYTES)


@dataclass(frozen=True, slots=True, repr=False)
class IssuedOpaqueToken:
    """One-time return value whose plaintext must never be persisted."""

    plaintext: str
    digest_sha256: bytes

    def __repr__(self) -> str:
        return "IssuedOpaqueToken(<redacted>)"


def _encode_random_material(material: bytes) -> str:
    return base64.urlsafe_b64encode(material).rstrip(b"=").decode("ascii")


def _has_token_shape(token: object, prefix: str) -> bool:
    if not isinstance(token, str) or not token.startswith(prefix):
        return False
    return _ENCODED_RANDOM_PATTERN.fullmatch(token[len(prefix) :]) is not None


def _digest_well_formed_token(token: str, prefix: str) -> bytes:
    if not _has_token_shape(token, prefix):
        raise InvalidOpaqueTokenError()
    return hashlib.sha256(token.encode("ascii")).digest()


def _issue_token(prefix: str) -> IssuedOpaqueToken:
    plaintext = prefix + _encode_random_material(
        secrets.token_bytes(TOKEN_ENTROPY_BYTES)
    )
    return IssuedOpaqueToken(
        plaintext=plaintext,
        digest_sha256=hashlib.sha256(plaintext.encode("ascii")).digest(),
    )


def issue_session_token() -> IssuedOpaqueToken:
    """Issue an opaque session bearer with 256 bits of CSPRNG entropy."""

    return _issue_token(_SESSION_PREFIX)


def issue_csrf_token() -> IssuedOpaqueToken:
    """Issue independent per-session CSRF material with 256 bits of entropy."""

    return _issue_token(_CSRF_PREFIX)


def digest_session_token(token: str) -> bytes:
    """Return the sole persistence representation of a session token."""

    return _digest_well_formed_token(token, _SESSION_PREFIX)


def digest_csrf_token(token: str) -> bytes:
    """Return the sole persistence representation of a CSRF token."""

    return _digest_well_formed_token(token, _CSRF_PREFIX)


def _constant_time_verify(
    presented_token: object,
    stored_digest: object,
    prefix: str,
) -> bool:
    token_is_valid = _has_token_shape(presented_token, prefix)
    if token_is_valid:
        candidate_digest = hashlib.sha256(
            presented_token.encode("ascii")
        ).digest()
    else:
        candidate_digest = _DUMMY_DIGEST

    digest_is_valid = isinstance(stored_digest, (bytes, bytearray, memoryview))
    if digest_is_valid:
        normalized_digest = bytes(stored_digest)
        digest_is_valid = len(normalized_digest) == TOKEN_DIGEST_BYTES
    else:
        normalized_digest = _DUMMY_DIGEST

    if not digest_is_valid:
        normalized_digest = _DUMMY_DIGEST

    digest_matches = hmac.compare_digest(candidate_digest, normalized_digest)
    return bool(token_is_valid and digest_is_valid and digest_matches)


def verify_session_token(presented_token: object, stored_digest: object) -> bool:
    """Verify a presented session token without revealing lookup state."""

    return _constant_time_verify(presented_token, stored_digest, _SESSION_PREFIX)


def verify_csrf_token(presented_token: object, stored_digest: object) -> bool:
    """Verify a presented CSRF token without revealing session state."""

    return _constant_time_verify(presented_token, stored_digest, _CSRF_PREFIX)
