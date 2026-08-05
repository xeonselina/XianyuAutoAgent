from datetime import date, datetime, time, timedelta

import pytest

from app import create_app, db
from app.models.device import Device
from app.models.device_model import DeviceModel
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.models.rental_relay_case import RentalRelayCase
from app.services.relay.relay_case_service import RelayCaseService


@pytest.fixture
def app():
    return create_app("testing")


@pytest.fixture
def db_session(app):
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.rollback()
        db.drop_all()


def add_device(db_session, suffix):
    model = DeviceModel(
        name=f"relay-{suffix}",
        display_name=f"接力型号 {suffix}",
        is_active=True,
    )
    db_session.add(model)
    db_session.flush()
    device = Device(
        name=f"R-{suffix}",
        model=model.name,
        model_id=model.id,
        is_accessory=False,
        lifecycle_status="active",
    )
    db_session.add(device)
    db_session.flush()
    return device


def add_pair(
    db_session,
    device,
    *,
    overlap_days,
    first_ship_out=date(2026, 8, 1),
    first_status="not_shipped",
    second_status="not_shipped",
):
    first_ship_in = first_ship_out + timedelta(days=8)
    second_ship_out = first_ship_in - timedelta(days=overlap_days)
    first = Rental(
        device_id=device.id,
        start_date=first_ship_out + timedelta(days=1),
        end_date=first_ship_out + timedelta(days=4),
        ship_out_time=datetime.combine(first_ship_out, time(19)),
        ship_in_time=datetime.combine(first_ship_in, time(12)),
        customer_name="前单收件人",
        customer_phone="13800138000",
        destination="杭州市西湖区",
        buyer_id="鹿鹿",
        lens_combo="lens_400mm",
        includes_handle=True,
        status=first_status,
    )
    second = Rental(
        device_id=device.id,
        start_date=second_ship_out + timedelta(days=3),
        end_date=second_ship_out + timedelta(days=7),
        ship_out_time=datetime.combine(second_ship_out, time(19)),
        ship_in_time=datetime.combine(second_ship_out + timedelta(days=9), time(12)),
        customer_name="后单收件人",
        customer_phone="13900139000",
        destination="上海市浦东新区",
        buyer_id="星星",
        lens_combo="lens_200mm",
        includes_lens_mount=True,
        status=second_status,
    )
    db_session.add_all([first, second])
    db_session.flush()
    return first, second


def test_candidates_require_two_full_overlap_days(app, db_session):
    one_day_device = add_device(db_session, "one")
    two_day_device = add_device(db_session, "two")
    one_day = add_pair(db_session, one_day_device, overlap_days=1)
    two_days = add_pair(db_session, two_day_device, overlap_days=2)
    db_session.commit()

    candidates = RelayCaseService.find_candidates()

    assert (one_day[0].id, one_day[1].id) not in candidates
    assert (two_days[0].id, two_days[1].id) in candidates
    assert candidates[(two_days[0].id, two_days[1].id)].overlap_days == 2


def test_candidates_only_compare_adjacent_non_cancelled_main_rentals(
    app, db_session
):
    device = add_device(db_session, "adjacent")
    first, middle = add_pair(db_session, device, overlap_days=2)
    middle.status = "cancelled"
    last = Rental(
        device_id=device.id,
        start_date=date(2026, 8, 9),
        end_date=date(2026, 8, 12),
        ship_out_time=datetime(2026, 8, 6, 19),
        ship_in_time=datetime(2026, 8, 15, 12),
        customer_name="最后一单",
        status="not_shipped",
    )
    child = Rental(
        device_id=device.id,
        parent_rental_id=first.id,
        start_date=date(2026, 8, 3),
        end_date=date(2026, 8, 4),
        ship_out_time=datetime(2026, 8, 2, 19),
        ship_in_time=datetime(2026, 8, 8, 12),
        customer_name="附件子单",
        status="not_shipped",
    )
    db_session.add_all([last, child])
    db_session.commit()

    candidates = RelayCaseService.find_candidates()

    assert list(candidates) == [(first.id, last.id)]
    assert all(child.id not in pair for pair in candidates)


def test_list_item_contains_customer_equipment_and_computed_dates(
    app, db_session
):
    device = add_device(db_session, "detail")
    first, second = add_pair(db_session, device, overlap_days=2)
    db_session.commit()

    payload = RelayCaseService.list_cases(
        statuses=["pending"],
        ship_date_from=date(2026, 8, 1),
        ship_date_to=date(2026, 8, 31),
        today=date(2026, 8, 5),
    )

    assert payload["total"] == 1
    item = payload["items"][0]
    assert item["case_id"] is None
    assert item["status"] == "pending"
    assert item["planned_ship_date"] == "2026-08-06"
    assert item["planned_receive_date"] == (
        second.start_date - timedelta(days=1)
    ).isoformat()
    assert item["overlap_days"] == 2
    assert item["predecessor"] == {
        "id": first.id,
        "start_date": first.start_date.isoformat(),
        "end_date": first.end_date.isoformat(),
        "buyer_id": "鹿鹿",
        "customer_name": "前单收件人",
        "customer_phone": "13800138000",
        "destination": "杭州市西湖区",
    }
    assert item["successor"]["buyer_id"] == "星星"
    assert item["device"]["name"] == "R-detail"
    assert item["device"]["model_display_name"] == "接力型号 detail"
    assert item["lens_combo"] == "lens_400mm"
    assert [accessory["name"] for accessory in item["accessories"]] == ["手柄"]


def test_invalid_pending_is_hidden_but_notified_is_retained_with_warning(
    app, db_session
):
    pending_device = add_device(db_session, "pending-invalid")
    notified_device = add_device(db_session, "notified-invalid")
    pending_pair = add_pair(db_session, pending_device, overlap_days=2)
    notified_pair = add_pair(db_session, notified_device, overlap_days=2)
    db_session.add_all([
        RentalRelayCase(
            predecessor_rental_id=pending_pair[0].id,
            successor_rental_id=pending_pair[1].id,
            status="pending",
        ),
        RentalRelayCase(
            predecessor_rental_id=notified_pair[0].id,
            successor_rental_id=notified_pair[1].id,
            status="notified",
        ),
    ])
    db_session.flush()
    pending_pair[1].ship_out_time = pending_pair[0].ship_in_time
    notified_pair[1].ship_out_time = notified_pair[0].ship_in_time
    db_session.commit()

    payload = RelayCaseService.list_cases(
        statuses=["pending", "notified"],
        ship_date_from=date(2026, 8, 1),
        ship_date_to=date(2026, 8, 31),
    )

    assert payload["total"] == 1
    assert payload["items"][0]["status"] == "notified"
    assert payload["items"][0]["schedule_changed"] is True


def test_existing_binding_without_case_is_exposed_as_agreed(app, db_session):
    device = add_device(db_session, "bound")
    first, second = add_pair(db_session, device, overlap_days=2)
    binding = RentalRelayBinding(
        predecessor_rental_id=first.id,
        successor_rental_id=second.id,
    )
    db_session.add(binding)
    db_session.commit()

    payload = RelayCaseService.list_cases(
        statuses=["agreed"],
        ship_date_from=date(2026, 8, 1),
        ship_date_to=date(2026, 8, 31),
    )

    assert payload["total"] == 1
    assert payload["items"][0]["status"] == "agreed"
    assert payload["items"][0]["binding_id"] == binding.id


def test_list_filters_by_planned_ship_date_and_paginates(app, db_session):
    early_device = add_device(db_session, "early")
    late_device = add_device(db_session, "late")
    add_pair(
        db_session,
        early_device,
        overlap_days=2,
        first_ship_out=date(2026, 8, 1),
    )
    late_pair = add_pair(
        db_session,
        late_device,
        overlap_days=2,
        first_ship_out=date(2026, 8, 10),
    )
    db_session.commit()

    payload = RelayCaseService.list_cases(
        statuses=["pending"],
        ship_date_from=date(2026, 8, 15),
        ship_date_to=date(2026, 8, 15),
        page=1,
        per_page=1,
    )

    assert payload["total"] == 1
    assert payload["page"] == 1
    assert payload["per_page"] == 1
    assert payload["items"][0]["predecessor"]["id"] == late_pair[0].id
