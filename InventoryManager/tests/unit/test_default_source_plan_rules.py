from datetime import date, datetime
from types import SimpleNamespace

import pytest

from app.services.migration.default_source_plan import (
    LEGACY_NO_FACT_LOGISTICS_DAYS,
    _derive_logistics_days,
    _logical_type_id,
    _parse_structured_address,
)
from app.services.migration.express_type_backfill import (
    ExpressTypeBackfillInputError,
    ExpressTypeState,
    build_express_type_source_snapshot,
)


def test_exact_manifest_bound_legacy_six_maps_to_canonical_two() -> None:
    snapshot = build_express_type_source_snapshot(
        ((1, None), (2, 2), (778, 6)),
        legacy_6_to_2_rental_ids=(778,),
    )

    expected = dict(snapshot.expected_state_counts)
    assert snapshot.approved_legacy_6_to_2_count == 1
    assert expected[ExpressTypeState.HISTORICAL_NULL.value] == 0
    assert expected[ExpressTypeState.LEGACY_6.value] == 0
    assert expected[ExpressTypeState.CANONICAL_2.value] == 3


def test_legacy_six_override_rejects_an_id_without_that_exact_source_value() -> None:
    with pytest.raises(ExpressTypeBackfillInputError):
        build_express_type_source_snapshot(
            ((1, 6), (778, 2)),
            legacy_6_to_2_rental_ids=(778,),
        )


def test_address_parser_only_accepts_complete_ordered_chinese_sequence() -> None:
    destination = "收件人,13800000000,广东省广州市越秀区大塘街道16号"
    parsed = _parse_structured_address(destination)

    assert parsed == ("广东省", "广州市", "越秀区", "大塘街道16号")
    assert _parse_structured_address("广州市越秀区大塘街道16号") is None
    assert _parse_structured_address("广东省广州市大塘街道16号") is None


@pytest.mark.parametrize(
    ("ship_out", "ship_in", "scheduled", "expected"),
    (
        (datetime(2026, 8, 20), None, None, (1, "legacy_ship_out")),
        (None, datetime(2026, 8, 27), None, (1, "legacy_ship_in")),
        (None, None, datetime(2026, 8, 19), (2, "scheduled_ship")),
        (None, None, None, (LEGACY_NO_FACT_LOGISTICS_DAYS, "legacy_ui_1")),
    ),
)
def test_logistics_days_use_fixed_source_precedence(
    ship_out: datetime | None,
    ship_in: datetime | None,
    scheduled: datetime | None,
    expected: tuple[int, str],
) -> None:
    rental = SimpleNamespace(
        start_date=date(2026, 8, 22),
        end_date=date(2026, 8, 25),
        ship_out_time=ship_out,
        ship_in_time=ship_in,
        scheduled_ship_time=scheduled,
    )

    assert _derive_logistics_days(rental) == expected


def test_only_holder_and_tripod_models_become_logical_types() -> None:
    device = SimpleNamespace(model=None, name="普通配件")

    assert _logical_type_id(device, "手机支架") == 1
    assert _logical_type_id(device, "三脚架") == 2
    assert _logical_type_id(device, "游戏手柄") is None
