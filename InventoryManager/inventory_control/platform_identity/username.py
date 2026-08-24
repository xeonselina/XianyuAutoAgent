"""Versioned canonicalization for the independent platform username domain."""

from __future__ import annotations

import re


PLATFORM_USERNAME_CANONICALIZATION_VERSION = 1
_USERNAME_PATTERN = re.compile(r"[a-z0-9][a-z0-9._-]{2,63}", re.ASCII)


class PlatformUsernameError(ValueError):
    code = "PLATFORM_CREDENTIAL_INVALID"

    def __init__(self) -> None:
        super().__init__("The platform credential is invalid.")


def canonicalize_platform_username(raw_username: object) -> str:
    """Return one lowercase ASCII username without tenant-phone semantics."""

    if not isinstance(raw_username, str):
        raise PlatformUsernameError()
    candidate = raw_username.strip(" ").lower()
    if _USERNAME_PATTERN.fullmatch(candidate) is None:
        raise PlatformUsernameError()
    return candidate

