"""Canonical, digest-only action payload shared by authorization protocols."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True, repr=False)
class CanonicalActionPayload:
    """Deterministic JSON retained transiently and represented by its digest."""

    digest_sha256: bytes
    _canonical_json: bytes = field(repr=False, compare=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.digest_sha256, bytes)
            or len(self.digest_sha256) != 32
        ):
            raise ValueError("canonical action payload digest is invalid")
        if not isinstance(self._canonical_json, bytes) or not self._canonical_json:
            raise ValueError("canonical action payload is invalid")
        if hashlib.sha256(self._canonical_json).digest() != self.digest_sha256:
            raise ValueError("canonical action payload digest does not match")

    @classmethod
    def from_value(cls, value: Any) -> "CanonicalActionPayload":
        _validate_json_value(value)
        encoded = json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
        return cls(hashlib.sha256(encoded).digest(), encoded)

    def __repr__(self) -> str:
        return "CanonicalActionPayload(<digest-only>)"


def _validate_json_value(value: Any) -> None:
    if value is None or isinstance(value, (str, bool)):
        return
    if isinstance(value, int) and not isinstance(value, bool):
        return
    if isinstance(value, list):
        for item in value:
            _validate_json_value(item)
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValueError("canonical action payload keys must be strings")
            _validate_json_value(item)
        return
    raise ValueError("canonical action payload contains an unsupported value")


__all__ = ["CanonicalActionPayload"]
