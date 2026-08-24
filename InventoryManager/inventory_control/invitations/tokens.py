"""Opaque, single-generation tenant invitation tokens."""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from inventory_control.crypto import CryptoCodecV1, RootKey


INVITATION_DEFAULT_LIFETIME = timedelta(days=7)
_TOKEN_BYTES = 32
_TOKEN_SHAPE = re.compile(r"^[A-Za-z0-9_-]{43}$")
ADMIN_INVITATION_TOKEN_DERIVATION_VERSION = 1
_ADMIN_INVITATION_TOKEN_DOMAIN = (
    "inventory-manager/admin-invitation-response-token/v1"
)


class InvitationTokenError(ValueError):
    """Stable error that never identifies or echoes a token."""


@dataclass(frozen=True, slots=True)
class InvitationToken:
    value: str = field(repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or not _TOKEN_SHAPE.fullmatch(self.value):
            raise InvitationTokenError("invitation token is invalid")

    @property
    def digest_sha256(self) -> bytes:
        return hashlib.sha256(self.value.encode("ascii")).digest()


@dataclass(frozen=True, slots=True)
class InvitationTokenGeneration:
    generation: int
    token_digest_sha256: bytes = field(repr=False)
    expires_at: datetime

    def __post_init__(self) -> None:
        if (
            isinstance(self.generation, bool)
            or not isinstance(self.generation, int)
            or self.generation < 1
        ):
            raise InvitationTokenError("invitation token generation is invalid")
        if (
            not isinstance(self.token_digest_sha256, bytes)
            or len(self.token_digest_sha256) != 32
        ):
            raise InvitationTokenError("invitation token digest is invalid")
        if not isinstance(self.expires_at, datetime):
            raise InvitationTokenError("invitation expiry is invalid")


@dataclass(frozen=True, slots=True)
class IssuedInvitationToken:
    token: InvitationToken
    persisted: InvitationTokenGeneration


def issue_invitation_token(
    *,
    database_now: datetime,
    generation: int = 1,
) -> IssuedInvitationToken:
    if not isinstance(database_now, datetime):
        raise InvitationTokenError("database time is invalid")
    token = InvitationToken(secrets.token_urlsafe(_TOKEN_BYTES))
    return IssuedInvitationToken(
        token=token,
        persisted=InvitationTokenGeneration(
            generation=generation,
            token_digest_sha256=token.digest_sha256,
            expires_at=database_now + INVITATION_DEFAULT_LIFETIME,
        ),
    )


def derive_admin_invitation_token(
    *, root_key: RootKey, action_uuid: UUID
) -> InvitationToken:
    """Derive the replay-stable token for one authorized Admin invite."""

    if not isinstance(root_key, RootKey) or not isinstance(action_uuid, UUID):
        raise InvitationTokenError("admin invitation token context is invalid")
    action_bytes = CryptoCodecV1.uuid_bytes(action_uuid)
    material = HKDF(
        algorithm=hashes.SHA256(),
        length=_TOKEN_BYTES,
        salt=action_bytes,
        info=CryptoCodecV1.encode_parts(
            CryptoCodecV1.domain(_ADMIN_INVITATION_TOKEN_DOMAIN),
            action_bytes,
            CryptoCodecV1.uint64(root_key.version),
            CryptoCodecV1.uint64(
                ADMIN_INVITATION_TOKEN_DERIVATION_VERSION
            ),
        ),
    ).derive(root_key._material_bytes())
    value = base64.urlsafe_b64encode(material).rstrip(b"=").decode("ascii")
    return InvitationToken(value)


def rotate_invitation_token(
    current: InvitationTokenGeneration,
    *,
    database_now: datetime,
) -> IssuedInvitationToken:
    if not isinstance(current, InvitationTokenGeneration):
        raise TypeError("current must be an InvitationTokenGeneration")
    return issue_invitation_token(
        database_now=database_now,
        generation=current.generation + 1,
    )


def verify_invitation_token(
    *,
    submitted_token: object,
    submitted_generation: object,
    current: InvitationTokenGeneration,
    database_now: datetime,
) -> bool:
    """Verify current generation, digest and deadline without enumeration."""

    if not isinstance(current, InvitationTokenGeneration):
        raise TypeError("current must be an InvitationTokenGeneration")
    if not isinstance(database_now, datetime):
        raise InvitationTokenError("database time is invalid")
    if (
        isinstance(submitted_generation, bool)
        or not isinstance(submitted_generation, int)
        or submitted_generation != current.generation
        or current.expires_at <= database_now
    ):
        return False
    try:
        submitted = InvitationToken(submitted_token)
    except InvitationTokenError:
        return False
    return hmac.compare_digest(
        submitted.digest_sha256,
        current.token_digest_sha256,
    )
