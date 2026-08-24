"""Canonical SaaS Core redemption-code primitives.

The bearer value is normalized before every lookup.  Callers persist only the
lookup digest plus the separately authenticated encrypted plaintext; this
module never logs or formats the full value for diagnostics.
"""

from __future__ import annotations

import hashlib
import secrets
import unicodedata
from dataclasses import dataclass, field


CROCKFORD_BASE32_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
REDEMPTION_CODE_LENGTH = 26
REDEMPTION_CODE_ENTROPY_BITS = 130
_MAX_SUBMITTED_CHARACTERS = 256
_ALIASES = {"O": "0", "I": "1", "L": "1"}
_VALID_CHARACTERS = frozenset(CROCKFORD_BASE32_ALPHABET)


class RedemptionCodeError(ValueError):
    """Base error whose text is safe to return without echoing a bearer."""


class InvalidRedemptionCodeError(RedemptionCodeError):
    """The submitted bearer cannot be canonicalized."""


@dataclass(frozen=True, slots=True)
class CanonicalRedemptionCode:
    """Short-lived canonical bearer and its deterministic lookup metadata."""

    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if (
            not isinstance(self.value, str)
            or len(self.value) != REDEMPTION_CODE_LENGTH
            or any(character not in _VALID_CHARACTERS for character in self.value)
        ):
            raise InvalidRedemptionCodeError("redemption code is invalid")

    @property
    def lookup_hash(self) -> bytes:
        return hashlib.sha256(self.value.encode("ascii")).digest()

    @property
    def lookup_hash_hex(self) -> str:
        return self.lookup_hash.hex()

    @property
    def prefix(self) -> str:
        """Return a non-authorizing hint suitable for an indexed list."""

        return self.value[:4]

    @property
    def masked(self) -> str:
        return f"{self.prefix}-{'*' * 18}-{self.value[-4:]}"

    def plaintext_bytes(self) -> bytes:
        """Return bytes only for immediate authenticated encryption."""

        return self.value.encode("ascii")


def generate_redemption_code() -> CanonicalRedemptionCode:
    """Generate one uniformly random 130-bit Crockford Base32 bearer."""

    return CanonicalRedemptionCode(
        "".join(
            secrets.choice(CROCKFORD_BASE32_ALPHABET)
            for _ in range(REDEMPTION_CODE_LENGTH)
        )
    )


def canonicalize_redemption_code(value: object) -> CanonicalRedemptionCode:
    """Apply the single approved normalization used by every code path.

    NFKC is applied first, then Unicode whitespace and ASCII hyphens are
    removed.  ASCII letters are uppercased and Crockford's O/I/L aliases are
    mapped before the exact length and alphabet checks.
    """

    if (
        not isinstance(value, str)
        or not value
        or len(value) > _MAX_SUBMITTED_CHARACTERS
        or "\x00" in value
    ):
        raise InvalidRedemptionCodeError("redemption code is invalid")

    normalized = unicodedata.normalize("NFKC", value)
    canonical_characters: list[str] = []
    for character in normalized:
        if character == "-" or character.isspace():
            continue
        if "a" <= character <= "z":
            character = chr(ord(character) - 32)
        character = _ALIASES.get(character, character)
        if character not in _VALID_CHARACTERS:
            raise InvalidRedemptionCodeError("redemption code is invalid")
        canonical_characters.append(character)

    if len(canonical_characters) != REDEMPTION_CODE_LENGTH:
        raise InvalidRedemptionCodeError("redemption code is invalid")
    return CanonicalRedemptionCode("".join(canonical_characters))


def redemption_code_lookup_hash(value: object) -> bytes:
    """Canonicalize a submitted bearer and return its binary SHA-256 digest."""

    return canonicalize_redemption_code(value).lookup_hash
