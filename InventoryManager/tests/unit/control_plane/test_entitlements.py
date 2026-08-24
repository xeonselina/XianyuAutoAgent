from __future__ import annotations

import hashlib

import pytest

from inventory_control.subscriptions import (
    CORE_ENTITLEMENTS_SCHEMA_VERSION,
    InvalidEntitlementSnapshotError,
    parse_core_entitlements,
)


def _valid_entitlements():
    return {
        "features": {
            "xianyu_sync": True,
            "advanced_statistics": False,
        },
        "limits": {"member_seats": 10},
    }


def test_core_snapshot_is_canonical_and_has_one_commercial_quota() -> None:
    snapshot = parse_core_entitlements(
        schema_version=CORE_ENTITLEMENTS_SCHEMA_VERSION,
        entitlements=_valid_entitlements(),
    )

    assert snapshot.canonical_json == (
        '{"features":{"advanced_statistics":false,"xianyu_sync":true},'
        '"limits":{"member_seats":10}}'
    )
    assert snapshot.digest_sha256 == hashlib.sha256(
        snapshot.canonical_json.encode("utf-8")
    ).digest()
    assert snapshot.member_seats == 10
    assert snapshot.allows("xianyu_sync") is True
    assert snapshot.allows("batch_shipping") is False


@pytest.mark.parametrize("schema_version", [None, True, 0, 2, "1"])
def test_unsupported_schema_versions_fail_closed(schema_version) -> None:
    with pytest.raises(InvalidEntitlementSnapshotError, match="unsupported"):
        parse_core_entitlements(
            schema_version=schema_version,
            entitlements=_valid_entitlements(),
        )


@pytest.mark.parametrize(
    "limits",
    [
        {},
        {"member_seats": None},
        {"member_seats": True},
        {"member_seats": "10"},
        {"member_seats": 0},
        {"member_seats": -1},
        {"member_seats": 9},
        {"member_seats": 11},
        {"member_seats": 10, "active_devices": 100},
        {"member_seats": 10, "monthly_rentals": 100},
        {"member_seats": 10, "integration_accounts": 5},
        {"member_seats": 10, "unknown": 1},
    ],
)
def test_candidate_and_unknown_limits_fail_closed(limits) -> None:
    entitlements = _valid_entitlements()
    entitlements["limits"] = limits

    with pytest.raises(InvalidEntitlementSnapshotError):
        parse_core_entitlements(schema_version=1, entitlements=entitlements)


@pytest.mark.parametrize(
    "entitlements",
    [
        None,
        {},
        {"limits": {"member_seats": 10}},
        {"features": {}, "limits": {"member_seats": 10}, "extra": {}},
        {"features": [], "limits": {"member_seats": 10}},
        {"features": {"Bad Key": True}, "limits": {"member_seats": 10}},
        {"features": {"valid_key": 1}, "limits": {"member_seats": 10}},
    ],
)
def test_malformed_snapshots_fail_closed(entitlements) -> None:
    with pytest.raises(InvalidEntitlementSnapshotError):
        parse_core_entitlements(schema_version=1, entitlements=entitlements)


def test_snapshot_does_not_alias_mutable_input() -> None:
    entitlements = _valid_entitlements()
    snapshot = parse_core_entitlements(schema_version=1, entitlements=entitlements)

    entitlements["features"]["xianyu_sync"] = False

    assert snapshot.allows("xianyu_sync") is True
    with pytest.raises(TypeError):
        snapshot.features["xianyu_sync"] = False
