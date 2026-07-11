from app import create_app, db
from tests.support.reorder_fixtures import seeded_reorder_case

import pytest


@pytest.fixture
def app():
    return create_app("testing")


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
