"""Versioned memory-hard password hashing for platform administrators."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from dataclasses import dataclass

try:  # Optional: the current repository environment does not require argon2-cffi.
    from argon2.low_level import Type as _Argon2Type
    from argon2.low_level import hash_secret_raw as _argon2_hash_secret_raw
except ImportError:  # pragma: no cover - exercised on deployments adding Argon2id.
    _Argon2Type = None
    _argon2_hash_secret_raw = None


_SALT_BYTES = 16
_HASH_BYTES = 32
_SCRYPT_N = 1 << 14
_SCRYPT_R = 8
_SCRYPT_P = 1
_ARGON2_MEMORY_KIB = 65536
_ARGON2_TIME_COST = 3
_ARGON2_PARALLELISM = 1
_PASSWORD_HASH_VERSION = 1
_DUMMY_PASSWORD = b"fixed-platform-password-dummy"


class PlatformPasswordError(ValueError):
    code = "PLATFORM_CREDENTIAL_INVALID"

    def __init__(self) -> None:
        super().__init__("The platform credential is invalid.")


@dataclass(frozen=True, slots=True, repr=False)
class PlatformPasswordHash:
    encoded: str
    algorithm: str
    version: int

    def __repr__(self) -> str:
        return (
            f"PlatformPasswordHash(algorithm={self.algorithm!r}, "
            f"version={self.version!r}, <redacted>)"
        )


class PlatformPasswordHasher:
    """Use Argon2id when installed, otherwise a versioned scrypt fallback."""

    @property
    def current_algorithm(self) -> str:
        return "argon2id" if _argon2_hash_secret_raw is not None else "scrypt"

    @property
    def current_version(self) -> int:
        return _PASSWORD_HASH_VERSION

    def hash(self, password: object) -> PlatformPasswordHash:
        password_bytes = _password_bytes(password)
        salt = secrets.token_bytes(_SALT_BYTES)
        if self.current_algorithm == "argon2id":
            digest = _argon2_digest(password_bytes, salt)
            parameters = (
                f"m={_ARGON2_MEMORY_KIB},t={_ARGON2_TIME_COST},"
                f"p={_ARGON2_PARALLELISM}"
            )
        else:
            digest = _scrypt_digest(password_bytes, salt)
            parameters = f"n={_SCRYPT_N},r={_SCRYPT_R},p={_SCRYPT_P}"
        encoded = "$".join(
            (
                "",
                f"{self.current_algorithm}-v{self.current_version}",
                parameters,
                _b64(salt),
                _b64(digest),
            )
        )
        return PlatformPasswordHash(
            encoded=encoded,
            algorithm=self.current_algorithm,
            version=self.current_version,
        )

    def verify(self, password: object, encoded_hash: object) -> bool:
        try:
            password_bytes = _password_bytes(password)
        except PlatformPasswordError:
            password_bytes = _DUMMY_PASSWORD
            password_is_valid = False
        else:
            password_is_valid = True

        parsed = _parse_hash(encoded_hash)
        if parsed is None:
            _burn_dummy(password_bytes)
            return False
        algorithm, version, parameters, salt, expected = parsed
        try:
            if algorithm == "scrypt" and version == 1:
                if parameters != (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P):
                    _burn_dummy(password_bytes)
                    return False
                candidate = hashlib.scrypt(
                    password_bytes,
                    salt=salt,
                    n=parameters[0],
                    r=parameters[1],
                    p=parameters[2],
                    dklen=len(expected),
                )
            elif algorithm == "argon2id" and version == 1:
                if _argon2_hash_secret_raw is None or parameters != (
                    _ARGON2_MEMORY_KIB,
                    _ARGON2_TIME_COST,
                    _ARGON2_PARALLELISM,
                ):
                    _burn_dummy(password_bytes)
                    return False
                candidate = _argon2_hash_secret_raw(
                    secret=password_bytes,
                    salt=salt,
                    time_cost=parameters[1],
                    memory_cost=parameters[0],
                    parallelism=parameters[2],
                    hash_len=len(expected),
                    type=_Argon2Type.ID,
                )
            else:
                _burn_dummy(password_bytes)
                return False
        except (TypeError, ValueError):
            _burn_dummy(password_bytes)
            return False
        return bool(password_is_valid and hmac.compare_digest(candidate, expected))

    def needs_rehash(self, encoded_hash: object) -> bool:
        parsed = _parse_hash(encoded_hash)
        if parsed is None:
            return True
        algorithm, version, parameters, _, expected = parsed
        desired = (
            (_ARGON2_MEMORY_KIB, _ARGON2_TIME_COST, _ARGON2_PARALLELISM)
            if self.current_algorithm == "argon2id"
            else (_SCRYPT_N, _SCRYPT_R, _SCRYPT_P)
        )
        return bool(
            algorithm != self.current_algorithm
            or version != self.current_version
            or parameters != desired
            or len(expected) != _HASH_BYTES
        )


def _password_bytes(password: object) -> bytes:
    if not isinstance(password, str):
        raise PlatformPasswordError()
    encoded = password.encode("utf-8")
    if len(encoded) < 12 or len(encoded) > 1024:
        raise PlatformPasswordError()
    return encoded


def _scrypt_digest(password: bytes, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password,
        salt=salt,
        n=_SCRYPT_N,
        r=_SCRYPT_R,
        p=_SCRYPT_P,
        dklen=_HASH_BYTES,
    )


def _argon2_digest(password: bytes, salt: bytes) -> bytes:
    return _argon2_hash_secret_raw(
        secret=password,
        salt=salt,
        time_cost=_ARGON2_TIME_COST,
        memory_cost=_ARGON2_MEMORY_KIB,
        parallelism=_ARGON2_PARALLELISM,
        hash_len=_HASH_BYTES,
        type=_Argon2Type.ID,
    )


def _burn_dummy(password: bytes) -> None:
    _scrypt_digest(password, bytes(_SALT_BYTES))


def _parse_hash(
    encoded_hash: object,
) -> tuple[str, int, tuple[int, int, int], bytes, bytes] | None:
    if not isinstance(encoded_hash, str):
        return None
    parts = encoded_hash.split("$")
    if len(parts) != 5 or parts[0] != "":
        return None
    algorithm_version, parameter_text, salt_text, digest_text = parts[1:]
    try:
        algorithm, version_text = algorithm_version.rsplit("-v", 1)
        version = int(version_text)
        parameter_items = [
            item.split("=", 1) for item in parameter_text.split(",")
        ]
        parameter_map = {key: int(value) for key, value in parameter_items}
        if len(parameter_map) != len(parameter_items):
            return None
        if algorithm == "scrypt":
            if set(parameter_map) != {"n", "r", "p"}:
                return None
            parameters = (
                parameter_map["n"],
                parameter_map["r"],
                parameter_map["p"],
            )
        elif algorithm == "argon2id":
            if set(parameter_map) != {"m", "t", "p"}:
                return None
            parameters = (
                parameter_map["m"],
                parameter_map["t"],
                parameter_map["p"],
            )
        else:
            return None
        salt = _unb64(salt_text)
        digest = _unb64(digest_text)
    except (KeyError, TypeError, ValueError):
        return None
    if len(salt) != _SALT_BYTES or len(digest) != _HASH_BYTES:
        return None
    return algorithm, version, parameters, salt, digest


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _unb64(value: str) -> bytes:
    if not value or any(character.isspace() for character in value):
        raise ValueError("invalid base64")
    padding = "=" * (-len(value) % 4)
    decoded = base64.b64decode(value + padding, altchars=b"-_", validate=True)
    if _b64(decoded) != value:
        raise ValueError("non-canonical base64")
    return decoded
