import os
from datetime import date, datetime, time, timedelta

from app import create_app, db
from app.models.audit_log import AuditLog
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.services.gantt.reorder_service import GanttReorderService
from tests.support.reorder_fixtures import seeded_reorder_case
from tests.support.test_database import (
    assert_current_user_has_test_only_grants,
    build_mysql_test_config,
)

import pytest


@pytest.fixture
def app():
    if not os.environ.get("TEST_DATABASE_URL"):
        return create_app("testing")
    app = create_app(build_mysql_test_config())
    with app.app_context():
        with db.engine.connect() as connection:
            assert_current_user_has_test_only_grants(
                connection, db.engine.url.database
            )
    return app


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        db.create_all()
        yield db.session
        db.session.rollback()
        db.drop_all()


def test_analyze_returns_contact_fields(client, seeded_reorder_case):
    seeded_reorder_case.add_overlap_pair()

    response = client.post("/api/gantt/reorder/analyze")

    assert response.status_code == 200
    overlap = response.get_json()["data"]["overlaps"][0]
    assert overlap["predecessor"]["customer_name"] == "王先生"
    assert overlap["predecessor"]["customer_phone"] == "13800138000"
    assert overlap["predecessor"]["destination"] == "北京市朝阳区"


def test_preview_is_read_only(client, db_session, seeded_reorder_case):
    before = seeded_reorder_case.snapshot()

    response = client.post(
        "/api/gantt/reorder/preview", json={"decisions": []}
    )

    assert response.status_code == 200
    payload = response.get_json()["data"]
    assert payload["token"]
    assert payload["models"][0]["status"] in {"OPTIMAL", "FEASIBLE"}
    assert payload["changes"]
    db_session.expire_all()
    assert seeded_reorder_case.snapshot() == before


def test_preview_ignores_completed_past_not_shipped_conflicts(
    client, db_session, seeded_reorder_case
):
    past = date.today() - timedelta(days=60)
    stale_rentals = [
        Rental(
            device_id=seeded_reorder_case.first_device.id,
            start_date=past + timedelta(days=1),
            end_date=past + timedelta(days=4),
            ship_out_time=datetime.combine(past, time(19)),
            ship_in_time=datetime.combine(past + timedelta(days=6), time(12)),
            customer_name=f"历史测试客户{index}",
            customer_phone="13800000000",
            destination="历史测试地址",
            status="not_shipped",
        )
        for index in range(3)
    ]
    db_session.add_all(stale_rentals)
    db_session.commit()

    response = client.post(
        "/api/gantt/reorder/preview", json={"decisions": []}
    )

    assert response.status_code == 200
    model = response.get_json()["data"]["models"][0]
    assert model["status"] in {"OPTIMAL", "FEASIBLE"}
    assert model["movable_rentals"] == 2


def test_execute_matches_preview_and_preserves_child(
    client, db_session, seeded_reorder_case
):
    child_before = seeded_reorder_case.child_snapshot()
    main_ids_before = seeded_reorder_case.main_ids()
    child_ids_before = seeded_reorder_case.child_ids()
    preview = client.post(
        "/api/gantt/reorder/preview", json={"decisions": []}
    ).get_json()["data"]

    response = client.post(
        "/api/gantt/reorder/execute", json={"token": preview["token"]}
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["changes"] == preview["changes"]
    db_session.expire_all()
    assert seeded_reorder_case.child_snapshot() == child_before
    assert seeded_reorder_case.main_ids() == main_ids_before
    assert seeded_reorder_case.child_ids() == child_ids_before
    assert AuditLog.query.filter_by(action="gantt_schedule_reordered").count() == len(
        preview["changes"]
    )


def test_execute_rejects_child_change_after_preview(
    client, db_session, seeded_reorder_case
):
    preview = client.post(
        "/api/gantt/reorder/preview", json={"decisions": []}
    ).get_json()["data"]
    seeded_reorder_case.child.destination = "预览后修改"
    db_session.commit()

    response = client.post(
        "/api/gantt/reorder/execute", json={"token": preview["token"]}
    )

    assert response.status_code == 409
    assert "重新预览" in response.get_json()["message"]


def test_execute_rejects_preview_from_another_solver_version(
    client, seeded_reorder_case
):
    preview = client.post(
        "/api/gantt/reorder/preview", json={"decisions": []}
    ).get_json()["data"]
    payload = GanttReorderService._serializer().loads(preview["token"])
    payload["solver_version"] = "old-solver-version"
    incompatible_token = GanttReorderService._serializer().dumps(payload)

    response = client.post(
        "/api/gantt/reorder/execute", json={"token": incompatible_token}
    )

    assert response.status_code == 409
    assert "重新预览" in response.get_json()["message"]


def test_execute_persists_relay_binding_atomically(
    client, db_session, seeded_reorder_case
):
    predecessor, successor = seeded_reorder_case.add_overlap_pair()
    decisions = [{
        "predecessor_rental_id": predecessor.id,
        "successor_rental_id": successor.id,
        "action": "keep",
    }]
    preview = client.post(
        "/api/gantt/reorder/preview", json={"decisions": decisions}
    ).get_json()["data"]

    response = client.post(
        "/api/gantt/reorder/execute", json={"token": preview["token"]}
    )

    assert response.status_code == 200
    binding = RentalRelayBinding.query.filter_by(
        predecessor_rental_id=predecessor.id,
        successor_rental_id=successor.id,
    ).one()
    assert binding.id is not None
    db_session.refresh(predecessor)
    db_session.refresh(successor)
    assert predecessor.device_id == successor.device_id


def test_execute_rolls_back_every_change_on_injected_failure(
    client, db_session, seeded_reorder_case, monkeypatch
):
    preview = client.post(
        "/api/gantt/reorder/preview", json={"decisions": []}
    ).get_json()["data"]
    before = seeded_reorder_case.snapshot()

    def fail_audit(*_args, **_kwargs):
        raise RuntimeError("注入失败")

    monkeypatch.setattr(GanttReorderService, "_write_audit_rows", fail_audit)
    response = client.post(
        "/api/gantt/reorder/execute", json={"token": preview["token"]}
    )

    assert response.status_code == 500
    db_session.expire_all()
    assert seeded_reorder_case.snapshot() == before
    assert AuditLog.query.count() == 0


def test_execute_rolls_back_if_any_child_column_changes(
    client, db_session, seeded_reorder_case, monkeypatch
):
    preview = client.post(
        "/api/gantt/reorder/preview", json={"decisions": []}
    ).get_json()["data"]
    child_id = seeded_reorder_case.child.id
    original_order_no = seeded_reorder_case.child.xianyu_order_no
    apply_assignments = GanttReorderService._apply_device_assignments

    def change_unrelated_child_column(
        cls, rentals, devices, assignments, today
    ):
        apply_assignments(rentals, devices, assignments, today)
        child = next(rental for rental in rentals if rental.id == child_id)
        child.xianyu_order_no = "不应保留的修改"

    monkeypatch.setattr(
        GanttReorderService,
        "_apply_device_assignments",
        classmethod(change_unrelated_child_column),
    )

    response = client.post(
        "/api/gantt/reorder/execute", json={"token": preview["token"]}
    )

    assert response.status_code == 500
    db_session.expire_all()
    assert db_session.get(Rental, child_id).xianyu_order_no == original_order_no
    assert AuditLog.query.count() == 0


def test_reusing_preview_token_has_no_duplicate_side_effect(
    client, db_session, seeded_reorder_case
):
    preview = client.post(
        "/api/gantt/reorder/preview", json={"decisions": []}
    ).get_json()["data"]

    first = client.post(
        "/api/gantt/reorder/execute", json={"token": preview["token"]}
    )
    first_audit_count = AuditLog.query.count()
    second = client.post(
        "/api/gantt/reorder/execute", json={"token": preview["token"]}
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert AuditLog.query.count() == first_audit_count
