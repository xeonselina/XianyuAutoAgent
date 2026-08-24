"""Version-one SaaS Core entitlement snapshots.

Core has one commercial quota. Capacity controls such as provider rate limits
or database connection budgets intentionally do not appear in this schema.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from types import MappingProxyType
from typing import Mapping

from .seats import CORE_MEMBER_SEAT_CAP


CORE_ENTITLEMENTS_SCHEMA_VERSION = 1
_TOP_LEVEL_KEYS = frozenset({"features", "limits"})
_LIMIT_KEYS = frozenset({"member_seats"})
_FEATURE_KEY = re.compile(r"^[a-z][a-z0-9_.-]{0,127}$")
_MAX_FEATURES = 256


class InvalidEntitlementSnapshotError(ValueError):
    """An entitlement snapshot does not satisfy the Core v1 contract."""


@dataclass(frozen=True, slots=True)
class CoreEntitlementSnapshot:
    schema_version: int
    canonical_json: str
    digest_sha256: bytes
    features: Mapping[str, bool]
    member_seats: int

    def __post_init__(self) -> None:
        if self.schema_version != CORE_ENTITLEMENTS_SCHEMA_VERSION:
            raise InvalidEntitlementSnapshotError(
                "entitlement schema version is unsupported"
            )
        if not isinstance(self.canonical_json, str) or not self.canonical_json:
            raise InvalidEntitlementSnapshotError("entitlement snapshot is invalid")
        if not isinstance(self.digest_sha256, bytes) or len(self.digest_sha256) != 32:
            raise InvalidEntitlementSnapshotError("entitlement digest is invalid")
        if self.member_seats != CORE_MEMBER_SEAT_CAP:
            raise InvalidEntitlementSnapshotError("Core member seat limit is invalid")
        object.__setattr__(self, "features", MappingProxyType(dict(self.features)))

    @property
    def digest_hex(self) -> str:
        return self.digest_sha256.hex()

    def allows(self, feature_key: str) -> bool:
        if not isinstance(feature_key, str) or not _FEATURE_KEY.fullmatch(feature_key):
            raise InvalidEntitlementSnapshotError("entitlement feature key is invalid")
        return self.features.get(feature_key, False)


def parse_core_entitlements(
    *,
    schema_version: object,
    entitlements: object,
) -> CoreEntitlementSnapshot:
    """Validate and canonicalize a plan/code/subscription entitlement value."""

    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != CORE_ENTITLEMENTS_SCHEMA_VERSION
    ):
        raise InvalidEntitlementSnapshotError(
            "entitlement schema version is unsupported"
        )
    if not isinstance(entitlements, dict) or set(entitlements) != _TOP_LEVEL_KEYS:
        raise InvalidEntitlementSnapshotError("entitlement snapshot is invalid")

    raw_features = entitlements.get("features")
    raw_limits = entitlements.get("limits")
    if not isinstance(raw_features, dict) or len(raw_features) > _MAX_FEATURES:
        raise InvalidEntitlementSnapshotError("entitlement features are invalid")
    if not isinstance(raw_limits, dict) or set(raw_limits) != _LIMIT_KEYS:
        raise InvalidEntitlementSnapshotError("Core plan limits are invalid")

    member_seats = raw_limits.get("member_seats")
    if (
        isinstance(member_seats, bool)
        or not isinstance(member_seats, int)
        or member_seats != CORE_MEMBER_SEAT_CAP
    ):
        raise InvalidEntitlementSnapshotError("Core member seat limit is invalid")

    features: dict[str, bool] = {}
    for key, enabled in raw_features.items():
        if not isinstance(key, str) or not _FEATURE_KEY.fullmatch(key):
            raise InvalidEntitlementSnapshotError("entitlement feature key is invalid")
        if not isinstance(enabled, bool):
            raise InvalidEntitlementSnapshotError("entitlement feature value is invalid")
        features[key] = enabled

    normalized = {
        "features": features,
        "limits": {"member_seats": CORE_MEMBER_SEAT_CAP},
    }
    canonical_json = json.dumps(
        normalized,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(canonical_json.encode("utf-8")).digest()
    return CoreEntitlementSnapshot(
        schema_version=CORE_ENTITLEMENTS_SCHEMA_VERSION,
        canonical_json=canonical_json,
        digest_sha256=digest,
        features=features,
        member_seats=member_seats,
    )
