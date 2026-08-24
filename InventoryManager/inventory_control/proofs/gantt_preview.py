"""Purpose-separated Gantt reorder preview confirmation proofs."""

from __future__ import annotations

import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from typing import Iterable, Mapping
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from inventory_control.crypto import CryptoCodecV1, RootKey

from .token_codec import canonical_json, join_signed_token, split_signed_token


GANTT_PREVIEW_PROOF_VERSION = 1
GANTT_PREVIEW_MAX_TTL_SECONDS = 600
GANTT_PREVIEW_PURPOSE = "inventory-manager/tenant-gantt-reorder-preview/v1"
_SAFE_VERSION = re.compile(r"^[a-z0-9][a-z0-9._:/-]{0,127}$")
_SNAPSHOT_HASH = re.compile(r"^[0-9a-f]{64}$")
_MAX_TOKEN_BYTES = 65_536


class GanttPreviewProofError(ValueError):
    """Stable error for any malformed, stale, or unauthorized proof."""


@dataclass(frozen=True, slots=True)
class GanttPreviewAuthority:
    tenant_uuid: UUID
    actor_user_uuid: UUID
    actor_session_uuid: UUID
    user_auth_version: int
    tenant_access_version: int
    tenant_timezone: str
    recovery_run_uuid: UUID
    recovery_hold_uuid: UUID
    recovery_hold_revision: int

    def __post_init__(self) -> None:
        for value in (
            self.tenant_uuid,
            self.actor_user_uuid,
            self.actor_session_uuid,
            self.recovery_run_uuid,
            self.recovery_hold_uuid,
        ):
            if not isinstance(value, UUID):
                raise GanttPreviewProofError("preview authority is invalid")
        for value in (
            self.user_auth_version,
            self.tenant_access_version,
            self.recovery_hold_revision,
        ):
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise GanttPreviewProofError("preview authority revision is invalid")
        try:
            if (
                not isinstance(self.tenant_timezone, str)
                or not self.tenant_timezone
                or len(self.tenant_timezone) > 64
            ):
                raise ValueError
            zone = ZoneInfo(self.tenant_timezone)
            if zone.key != self.tenant_timezone:
                raise ValueError
        except Exception:
            raise GanttPreviewProofError("preview authority is invalid") from None


@dataclass(frozen=True, slots=True, repr=False)
class GanttPreviewContent:
    snapshot_hash: str
    decisions: tuple[tuple[int, int, str], ...]
    assignments: tuple[tuple[int, int], ...]
    preview_date: date
    solver_version: str
    canonicalization_version: int = 1

    def __post_init__(self) -> None:
        if not isinstance(self.snapshot_hash, str) or not _SNAPSHOT_HASH.fullmatch(
            self.snapshot_hash
        ):
            raise GanttPreviewProofError("preview snapshot is invalid")
        if not isinstance(self.preview_date, date) or isinstance(
            self.preview_date, datetime
        ):
            raise GanttPreviewProofError("preview date is invalid")
        if not isinstance(self.solver_version, str) or not _SAFE_VERSION.fullmatch(
            self.solver_version
        ):
            raise GanttPreviewProofError("preview solver version is invalid")
        if (
            isinstance(self.canonicalization_version, bool)
            or not isinstance(self.canonicalization_version, int)
            or self.canonicalization_version < 1
        ):
            raise GanttPreviewProofError("preview canonicalization version is invalid")
        if self.decisions != tuple(sorted(self.decisions)):
            raise GanttPreviewProofError("preview decisions are not canonical")
        if self.assignments != tuple(sorted(self.assignments)):
            raise GanttPreviewProofError("preview assignments are not canonical")
        seen_decisions: set[tuple[int, int]] = set()
        for predecessor, successor, action in self.decisions:
            if (
                not _positive_int(predecessor)
                or not _positive_int(successor)
                or predecessor == successor
                or action not in {"keep", "separate"}
                or (predecessor, successor) in seen_decisions
            ):
                raise GanttPreviewProofError("preview decisions are invalid")
            seen_decisions.add((predecessor, successor))
        seen_assignments: set[int] = set()
        for rental_id, device_id in self.assignments:
            if (
                not _positive_int(rental_id)
                or not _positive_int(device_id)
                or rental_id in seen_assignments
            ):
                raise GanttPreviewProofError("preview assignments are invalid")
            seen_assignments.add(rental_id)

    @classmethod
    def from_values(
        cls,
        *,
        snapshot_hash: str,
        decisions: Iterable[Mapping[str, object]],
        assignments: Mapping[object, object],
        preview_date: date,
        solver_version: str,
        canonicalization_version: int = 1,
    ) -> "GanttPreviewContent":
        try:
            normalized_decisions = tuple(
                sorted(
                    (
                        _strict_positive_int(item["predecessor_rental_id"]),
                        _strict_positive_int(item["successor_rental_id"]),
                        _decision_action(item["action"]),
                    )
                    for item in decisions
                )
            )
            normalized_assignments = tuple(
                sorted(
                    (
                        _assignment_rental_id(rental_id),
                        _strict_positive_int(device_id),
                    )
                    for rental_id, device_id in assignments.items()
                )
            )
        except (KeyError, TypeError, ValueError):
            raise GanttPreviewProofError("preview action is invalid") from None
        return cls(
            snapshot_hash=snapshot_hash,
            decisions=normalized_decisions,
            assignments=normalized_assignments,
            preview_date=preview_date,
            solver_version=solver_version,
            canonicalization_version=canonicalization_version,
        )

    def decisions_json(self) -> list[dict[str, object]]:
        return [
            {
                "predecessor_rental_id": predecessor,
                "successor_rental_id": successor,
                "action": action,
            }
            for predecessor, successor, action in self.decisions
        ]

    def assignments_dict(self) -> dict[int, int]:
        return dict(self.assignments)

    def __repr__(self) -> str:
        return (
            "GanttPreviewContent("
            f"snapshot_hash={self.snapshot_hash!r}, "
            f"decision_count={len(self.decisions)}, "
            f"assignment_count={len(self.assignments)}, "
            f"preview_date={self.preview_date!r}, "
            f"solver_version={self.solver_version!r}, "
            f"canonicalization_version={self.canonicalization_version})"
        )


@dataclass(frozen=True, slots=True)
class VerifiedGanttPreview:
    action_uuid: UUID
    content: GanttPreviewContent = field(repr=False)
    issued_at: datetime
    expires_at: datetime


def issue_gantt_preview_proof(
    *,
    root_key: RootKey,
    authority: GanttPreviewAuthority,
    content: GanttPreviewContent,
    database_now: datetime,
    ttl: timedelta = timedelta(seconds=GANTT_PREVIEW_MAX_TTL_SECONDS),
    action_uuid: UUID | None = None,
) -> str:
    if not isinstance(root_key, RootKey):
        raise GanttPreviewProofError("preview proof configuration is invalid")
    if not isinstance(authority, GanttPreviewAuthority) or not isinstance(
        content, GanttPreviewContent
    ):
        raise GanttPreviewProofError("preview proof input is invalid")
    issued_at = _utc(database_now)
    if (
        not isinstance(ttl, timedelta)
        or ttl <= timedelta(0)
        or ttl > timedelta(seconds=GANTT_PREVIEW_MAX_TTL_SECONDS)
        or ttl.microseconds != 0
    ):
        raise GanttPreviewProofError("preview proof TTL is invalid")
    action_uuid = action_uuid or uuid4()
    if not isinstance(action_uuid, UUID):
        raise GanttPreviewProofError("preview action identity is invalid")
    expires_at = issued_at + ttl
    payload = _payload(
        authority=authority,
        content=content,
        action_uuid=action_uuid,
        root_key_version=root_key.version,
        issued_at=issued_at,
        expires_at=expires_at,
    )
    encoded = canonical_json(payload)
    signature = hmac.digest(
        _derive_signing_key(root_key=root_key, action_uuid=action_uuid),
        encoded,
        "sha256",
    )
    return join_signed_token(encoded, signature)


def verify_gantt_preview_proof(
    *,
    token: object,
    root_key: RootKey,
    expected_authority: GanttPreviewAuthority,
    database_now: datetime,
) -> VerifiedGanttPreview:
    """Authenticate one proof against current trusted authority facts."""

    try:
        if not isinstance(root_key, RootKey) or not isinstance(
            expected_authority, GanttPreviewAuthority
        ):
            raise ValueError
        encoded, signature = split_signed_token(
            token,
            maximum_bytes=_MAX_TOKEN_BYTES,
        )
        payload = json.loads(encoded)
        if not isinstance(payload, dict) or canonical_json(payload) != encoded:
            raise ValueError
        action_uuid = UUID(payload["action_uuid"])
        expected_signature = hmac.digest(
            _derive_signing_key(root_key=root_key, action_uuid=action_uuid),
            encoded,
            "sha256",
        )
        if not hmac.compare_digest(signature, expected_signature):
            raise ValueError
        authority, content, issued_at, expires_at = _parse_payload(payload)
        now = _utc(database_now)
        if (
            payload["proof_version"] != GANTT_PREVIEW_PROOF_VERSION
            or payload["root_key_version"] != root_key.version
            or authority != expected_authority
            or issued_at > now
            or expires_at <= now
            or expires_at - issued_at
            > timedelta(seconds=GANTT_PREVIEW_MAX_TTL_SECONDS)
        ):
            raise ValueError
        return VerifiedGanttPreview(
            action_uuid=action_uuid,
            content=content,
            issued_at=issued_at,
            expires_at=expires_at,
        )
    except (KeyError, TypeError, ValueError, UnicodeError, json.JSONDecodeError):
        raise GanttPreviewProofError("preview proof is invalid or stale") from None


def _payload(
    *,
    authority: GanttPreviewAuthority,
    content: GanttPreviewContent,
    action_uuid: UUID,
    root_key_version: int,
    issued_at: datetime,
    expires_at: datetime,
) -> dict[str, object]:
    return {
        "proof_version": GANTT_PREVIEW_PROOF_VERSION,
        "root_key_version": root_key_version,
        "action_uuid": str(action_uuid),
        "tenant_uuid": str(authority.tenant_uuid),
        "actor_user_uuid": str(authority.actor_user_uuid),
        "actor_session_uuid": str(authority.actor_session_uuid),
        "user_auth_version": authority.user_auth_version,
        "tenant_access_version": authority.tenant_access_version,
        "tenant_timezone": authority.tenant_timezone,
        "recovery_run_uuid": str(authority.recovery_run_uuid),
        "recovery_hold_uuid": str(authority.recovery_hold_uuid),
        "recovery_hold_revision": authority.recovery_hold_revision,
        "snapshot_hash": content.snapshot_hash,
        "decisions": content.decisions_json(),
        "assignments": {
            str(rental_id): device_id
            for rental_id, device_id in content.assignments
        },
        "preview_date": content.preview_date.isoformat(),
        "solver_version": content.solver_version,
        "canonicalization_version": content.canonicalization_version,
        "issued_at": int(issued_at.timestamp()),
        "expires_at": int(expires_at.timestamp()),
    }


def _parse_payload(payload):
    expected_keys = {
        "proof_version",
        "root_key_version",
        "action_uuid",
        "tenant_uuid",
        "actor_user_uuid",
        "actor_session_uuid",
        "user_auth_version",
        "tenant_access_version",
        "tenant_timezone",
        "recovery_run_uuid",
        "recovery_hold_uuid",
        "recovery_hold_revision",
        "snapshot_hash",
        "decisions",
        "assignments",
        "preview_date",
        "solver_version",
        "canonicalization_version",
        "issued_at",
        "expires_at",
    }
    if set(payload) != expected_keys:
        raise ValueError
    authority = GanttPreviewAuthority(
        tenant_uuid=UUID(payload["tenant_uuid"]),
        actor_user_uuid=UUID(payload["actor_user_uuid"]),
        actor_session_uuid=UUID(payload["actor_session_uuid"]),
        user_auth_version=_strict_positive_int(payload["user_auth_version"]),
        tenant_access_version=_strict_positive_int(payload["tenant_access_version"]),
        tenant_timezone=payload["tenant_timezone"],
        recovery_run_uuid=UUID(payload["recovery_run_uuid"]),
        recovery_hold_uuid=UUID(payload["recovery_hold_uuid"]),
        recovery_hold_revision=_strict_positive_int(payload["recovery_hold_revision"]),
    )
    content = GanttPreviewContent.from_values(
        snapshot_hash=payload["snapshot_hash"],
        decisions=payload["decisions"],
        assignments=payload["assignments"],
        preview_date=date.fromisoformat(payload["preview_date"]),
        solver_version=payload["solver_version"],
        canonicalization_version=_strict_positive_int(
            payload["canonicalization_version"]
        ),
    )
    issued_at = datetime.fromtimestamp(
        _strict_positive_int(payload["issued_at"]), timezone.utc
    )
    expires_at = datetime.fromtimestamp(
        _strict_positive_int(payload["expires_at"]), timezone.utc
    )
    return authority, content, issued_at, expires_at


def _derive_signing_key(*, root_key: RootKey, action_uuid: UUID) -> bytes:
    action_bytes = CryptoCodecV1.uuid_bytes(action_uuid)
    info = CryptoCodecV1.encode_parts(
        CryptoCodecV1.domain(GANTT_PREVIEW_PURPOSE),
        action_bytes,
        CryptoCodecV1.uint64(root_key.version),
        CryptoCodecV1.uint64(GANTT_PREVIEW_PROOF_VERSION),
    )
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=action_bytes,
        info=info,
    ).derive(root_key._material_bytes())


def _utc(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
        or value.microsecond != 0
    ):
        raise GanttPreviewProofError("preview database time is invalid")
    return value.astimezone(timezone.utc)


def _positive_int(value: object) -> bool:
    return not isinstance(value, bool) and isinstance(value, int) and value > 0


def _strict_positive_int(value: object) -> int:
    if not _positive_int(value):
        raise ValueError
    return value


def _decision_action(value: object) -> str:
    if value not in {"keep", "separate"}:
        raise ValueError
    return value


def _assignment_rental_id(value: object) -> int:
    if isinstance(value, str):
        if not value.isascii() or not value.isdigit() or value.startswith("0"):
            raise ValueError
        value = int(value)
    return _strict_positive_int(value)
