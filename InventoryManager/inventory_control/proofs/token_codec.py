"""Canonical, URL-safe envelope helpers for short-lived HMAC proofs.

The helpers deliberately do not choose a purpose domain, derive a key, or
interpret a payload.  Each proof protocol remains responsible for those
security decisions while sharing one strict wire encoding.
"""

from __future__ import annotations

import base64
import json
import re


_TOKEN_SEGMENT = re.compile(rb"^[A-Za-z0-9_-]+$")
_SIGNATURE_BYTES = 32


def canonical_json(value: object) -> bytes:
    """Return the sole JSON representation accepted by proof protocols."""

    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def join_signed_token(payload: bytes, signature: bytes) -> str:
    """Encode canonical payload bytes and one HMAC-SHA256 signature."""

    if not isinstance(payload, bytes) or not payload:
        raise ValueError("proof payload is invalid")
    if not isinstance(signature, bytes) or len(signature) != _SIGNATURE_BYTES:
        raise ValueError("proof signature is invalid")
    return f"{_b64encode(payload)}.{_b64encode(signature)}"


def split_signed_token(
    token: object,
    *,
    maximum_bytes: int,
) -> tuple[bytes, bytes]:
    """Decode a canonical two-segment proof without interpreting its JSON."""

    if (
        not isinstance(token, str)
        or isinstance(maximum_bytes, bool)
        or not isinstance(maximum_bytes, int)
        or maximum_bytes < 128
    ):
        raise ValueError("proof token is invalid")
    encoded_token = token.encode("ascii")
    if not encoded_token or len(encoded_token) > maximum_bytes:
        raise ValueError("proof token is invalid")
    pieces = encoded_token.split(b".")
    if len(pieces) != 2 or any(
        _TOKEN_SEGMENT.fullmatch(piece) is None for piece in pieces
    ):
        raise ValueError("proof token is invalid")
    payload = _b64decode(pieces[0])
    signature = _b64decode(pieces[1])
    if not payload or len(signature) != _SIGNATURE_BYTES:
        raise ValueError("proof token is invalid")
    return payload, signature


def _b64encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: bytes) -> bytes:
    padding = b"=" * ((4 - len(value) % 4) % 4)
    decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    if _b64encode(decoded).encode("ascii") != value:
        raise ValueError("proof token is not canonically encoded")
    return decoded


__all__ = ["canonical_json", "join_signed_token", "split_signed_token"]
