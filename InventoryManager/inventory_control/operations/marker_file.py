"""Strict read-only loader for the root-owned deployment marker file."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Any

from .health import HostRecoveryMarker, HostRecoveryMarkerMode


MARKER_FORMAT_VERSION = 1
MAX_MARKER_BYTES = 4096
_EXPECTED_FIELDS = frozenset(
    {
        "format_version",
        "mode",
        "installation_fingerprint",
        "marker_fingerprint",
    }
)


class HostRecoveryMarkerLoadError(RuntimeError):
    """Fixed failure without a path, marker value, or OS error detail."""

    def __init__(self) -> None:
        super().__init__("deployment marker is unavailable")


def load_host_recovery_marker(
    path: str | os.PathLike[str],
    *,
    expected_owner_uid: int = 0,
) -> HostRecoveryMarker:
    """Load one bounded, non-symlink marker owned by the configured UID.

    Production callers retain the root-owner default.  Tests and deliberately
    unprivileged development wrappers may provide their own trusted UID; that
    selection is process configuration and is never read from the marker.
    """

    selected_path = _absolute_path(path)
    if (
        isinstance(expected_owner_uid, bool)
        or not isinstance(expected_owner_uid, int)
        or expected_owner_uid < 0
    ):
        raise ValueError("expected_owner_uid must be nonnegative")

    flags = os.O_RDONLY
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    descriptor: int | None = None
    try:
        descriptor = os.open(selected_path, flags)
        observed = os.fstat(descriptor)
        if (
            not stat.S_ISREG(observed.st_mode)
            or observed.st_uid != expected_owner_uid
            or observed.st_mode & 0o022
            or observed.st_size < 1
            or observed.st_size > MAX_MARKER_BYTES
        ):
            raise HostRecoveryMarkerLoadError()
        encoded = _read_exact_bounded(descriptor, observed.st_size)
    except HostRecoveryMarkerLoadError:
        raise
    except OSError:
        raise HostRecoveryMarkerLoadError() from None
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass

    payload = _decode_exact_json(encoded)
    try:
        if payload["format_version"] != MARKER_FORMAT_VERSION:
            raise HostRecoveryMarkerLoadError()
        mode = HostRecoveryMarkerMode(payload["mode"])
        return HostRecoveryMarker(
            mode=mode,
            installation_fingerprint=payload["installation_fingerprint"],
            marker_fingerprint=payload["marker_fingerprint"],
        )
    except HostRecoveryMarkerLoadError:
        raise
    except (KeyError, TypeError, ValueError):
        raise HostRecoveryMarkerLoadError() from None


def _absolute_path(path: str | os.PathLike[str]) -> Path:
    try:
        raw = os.fspath(path)
    except TypeError:
        raise HostRecoveryMarkerLoadError() from None
    if not isinstance(raw, str) or not raw or "\x00" in raw:
        raise HostRecoveryMarkerLoadError()
    selected = Path(raw)
    if not selected.is_absolute():
        raise HostRecoveryMarkerLoadError()
    return selected


def _read_exact_bounded(descriptor: int, expected_size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = expected_size + 1
    while remaining:
        piece = os.read(descriptor, min(remaining, 1024))
        if not piece:
            break
        chunks.append(piece)
        remaining -= len(piece)
    encoded = b"".join(chunks)
    if len(encoded) != expected_size or len(encoded) > MAX_MARKER_BYTES:
        raise HostRecoveryMarkerLoadError()
    return encoded


def _decode_exact_json(encoded: bytes) -> dict[str, Any]:
    def unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        selected: dict[str, Any] = {}
        for key, value in pairs:
            if key in selected:
                raise HostRecoveryMarkerLoadError()
            selected[key] = value
        return selected

    def reject_constant(_value: str) -> object:
        raise HostRecoveryMarkerLoadError()

    try:
        payload = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except HostRecoveryMarkerLoadError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        raise HostRecoveryMarkerLoadError() from None
    if not isinstance(payload, dict) or set(payload) != _EXPECTED_FIELDS:
        raise HostRecoveryMarkerLoadError()
    if type(payload.get("format_version")) is not int:
        raise HostRecoveryMarkerLoadError()
    return payload


__all__ = [
    "HostRecoveryMarkerLoadError",
    "MARKER_FORMAT_VERSION",
    "MAX_MARKER_BYTES",
    "load_host_recovery_marker",
]
