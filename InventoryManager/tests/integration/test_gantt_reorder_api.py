import os
from contextlib import contextmanager
from dataclasses import replace
from datetime import date, datetime, time, timedelta, timezone
from uuid import UUID

from app import create_app, db
from app.models.audit_log import AuditLog
from app.models.device import Device
from app.models.rental import Rental
from app.models.rental_relay_binding import RentalRelayBinding
from app.services.gantt.reorder_service import GanttReorderService
from app.services.gantt.reorder_service import StalePreviewError
from app.services.gantt.http_runtime import (
    GANTT_SAAS_HTTP_RUNTIME_EXTENSION,
)
from inventory_control.crypto import RootKey
from inventory_control.domain.rbac import TenantRole
from inventory_control.domain.tenant_gate import EffectiveTenantGate
from inventory_control.proofs import (
    CurrentGanttPreviewAuthority,
    GanttPreviewAuthority,
    GanttPreviewProofAdapter,
)
from inventory_control.tenant_http import AuthContext
from tests.support.reorder_fixtures import seeded_reorder_case
from tests.support.test_database import (
    build_mysql_test_config,
    clear_guarded_mysql_test_rows,
    guarded_mysql_test_metadata,
)

import pytest
from sqlalchemy import update


_SAAS_ROOT_KEY = RootKey(version=7, material=b"s" * 32)


class _LegacyRouteTestRuntime:
    """Exercise historical scheduling behavior behind the new route seam.

    Production never installs this adapter.  Existing integration cases keep
    covering the scheduling transaction while separate boundary tests prove
    that an absent/malformed SaaS runtime cannot fall back to this signer.
    """

    def analyze(self, *, flask_request):
        return GanttReorderService.analyze()

    def view(self, *, flask_request, query):
        raise AssertionError("legacy Gantt view must remain unreachable")

    def preview(self, *, flask_request, decisions):
        return GanttReorderService.preview(decisions)

    def execute(self, *, flask_request, token):
        return GanttReorderService.execute(token)


def _saas_auth_context(**changes):
    values = {
        "session_id": "10000000-0000-4000-8000-000000000003",
        "user_id": "10000000-0000-4000-8000-000000000002",
        "membership_id": "10000000-0000-4000-8000-000000000006",
        "tenant_id": "10000000-0000-4000-8000-000000000001",
        "role": TenantRole.OPERATOR,
        "user_auth_version": 4,
        "tenant_access_version": 8,
        "tenant_timezone": "Asia/Shanghai",
        "effective_gate": EffectiveTenantGate.ACTIVE,
    }
    values.update(changes)
    return AuthContext(**values)


class _SaasAuthorityReader:
    def __init__(self):
        self.current = CurrentGanttPreviewAuthority(
            authority=GanttPreviewAuthority(
                tenant_uuid=UUID(
                    "10000000-0000-4000-8000-000000000001"
                ),
                actor_user_uuid=UUID(
                    "10000000-0000-4000-8000-000000000002"
                ),
                actor_session_uuid=UUID(
                    "10000000-0000-4000-8000-000000000003"
                ),
                user_auth_version=4,
                tenant_access_version=8,
                tenant_timezone="Asia/Shanghai",
                recovery_run_uuid=UUID(
                    "10000000-0000-4000-8000-000000000004"
                ),
                recovery_hold_uuid=UUID(
                    "10000000-0000-4000-8000-000000000005"
                ),
                recovery_hold_revision=2,
            ),
            membership_uuid=UUID(
                "10000000-0000-4000-8000-000000000006"
            ),
            role=TenantRole.OPERATOR,
            session_is_current=True,
            effective_gate=EffectiveTenantGate.ACTIVE,
            active_root_key=_SAAS_ROOT_KEY,
            database_now=datetime.now(timezone.utc).replace(microsecond=0),
            tenant_timezone="Asia/Shanghai",
        )
        self.calls = []

    def read_current(self, *, auth_context):
        self.calls.append(auth_context)
        return self.current

    @contextmanager
    def lock_current(self, *, auth_context):
        self.calls.append(auth_context)
        yield self.current


class _ReleaseFailingSaasAuthorityReader(_SaasAuthorityReader):
    @contextmanager
    def lock_current(self, *, auth_context):
        self.calls.append(auth_context)
        yield self.current
        raise RuntimeError("control fence release failed")


@pytest.fixture(scope="module")
def app():
    if not os.environ.get("TEST_DATABASE_URL"):
        pytest.fail("TEST_DATABASE_URL is required for database tests")
    application = create_app(build_mysql_test_config())
    application.extensions[GANTT_SAAS_HTTP_RUNTIME_EXTENSION] = (
        _LegacyRouteTestRuntime()
    )
    with application.app_context():
        with guarded_mysql_test_metadata(db.engine, db.metadata):
            yield application
        db.session.remove()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db_session(app):
    with app.app_context():
        clear_guarded_mysql_test_rows(db.engine, db.metadata)
        try:
            yield db.session
        finally:
            db.session.rollback()
            db.session.remove()


def test_analyze_returns_contact_fields(client, seeded_reorder_case):
    seeded_reorder_case.add_overlap_pair()

    response = client.post("/api/gantt/reorder/analyze")

    assert response.status_code == 200
    overlap = response.get_json()["data"]["overlaps"][0]
    assert overlap["predecessor"]["customer_name"] == "王先生"
    assert overlap["predecessor"]["customer_phone"] == "13800138000"
    assert overlap["predecessor"]["destination"] == "北京市朝阳区"


def test_missing_planned_facts_block_analyze_and_preview(
    client, db_session, seeded_reorder_case
):
    seeded_reorder_case.first.planned_ship_out_date = None
    seeded_reorder_case.first.planned_return_date = None
    db_session.commit()

    analyze = client.post("/api/gantt/reorder/analyze")
    preview = client.post(
        "/api/gantt/reorder/preview", json={"decisions": []}
    )

    assert analyze.status_code == 409
    assert analyze.get_json()["data"]["code"] == "MISSING_PLANNED_LOGISTICS"
    assert preview.status_code == 409
    assert preview.get_json()["data"]["code"] == "MISSING_PLANNED_LOGISTICS"


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


def test_preview_schedules_planned_only_rows(
    client, db_session, seeded_reorder_case
):
    for rental in (seeded_reorder_case.first, seeded_reorder_case.second):
        rental.ship_out_time = None
        rental.ship_in_time = None
    db_session.commit()

    response = client.post(
        "/api/gantt/reorder/preview", json={"decisions": []}
    )

    assert response.status_code == 200
    changes = response.get_json()["data"]["changes"]
    assert changes
    assert all(change["ship_out_time"] is None for change in changes)
    assert all(change["planned_ship_out_date"] for change in changes)


def test_execute_rejects_planned_window_change_after_preview(
    client, db_session, seeded_reorder_case
):
    preview = client.post(
        "/api/gantt/reorder/preview", json={"decisions": []}
    ).get_json()["data"]
    rental = seeded_reorder_case.first
    rental.logistics_days = 1
    rental.planned_ship_out_date -= timedelta(days=1)
    rental.planned_return_date += timedelta(days=1)
    db_session.commit()

    response = client.post(
        "/api/gantt/reorder/execute", json={"token": preview["token"]}
    )

    assert response.status_code == 409
    assert "重新预览" in response.get_json()["message"]


def test_preview_ignores_completed_past_not_shipped_conflicts(
    client, db_session, seeded_reorder_case
):
    past = date.today() - timedelta(days=60)
    stale_rentals = [
        Rental(
            device_id=seeded_reorder_case.first_device.id,
            start_date=past + timedelta(days=1),
            end_date=past + timedelta(days=4),
            logistics_days=0,
            planned_ship_out_date=past,
            planned_return_date=past + timedelta(days=5),
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


def test_execute_refreshes_cached_rental_for_locked_snapshot(
    db_session, seeded_reorder_case
):
    preview = GanttReorderService.preview([])
    cached_rental = seeded_reorder_case.first
    original_device_ids = {
        rental.id: rental.device_id
        for rental in Rental.query.order_by(Rental.id).all()
    }
    db_session.execute(
        update(Rental)
        .where(Rental.id == cached_rental.id)
        .values(destination="预览后的底层更新")
        .execution_options(synchronize_session=False)
    )
    assert cached_rental.destination != "预览后的底层更新"

    with pytest.raises(StalePreviewError, match="重新预览"):
        GanttReorderService.execute(preview["token"])

    db_session.expire_all()
    assert {
        rental.id: rental.device_id
        for rental in Rental.query.order_by(Rental.id).all()
    } == original_device_ids


def test_execute_refreshes_cached_device_for_locked_snapshot(
    db_session, seeded_reorder_case
):
    preview = GanttReorderService.preview([])
    cached_device = seeded_reorder_case.first_device
    original_device_ids = {
        rental.id: rental.device_id
        for rental in Rental.query.order_by(Rental.id).all()
    }
    db_session.execute(
        update(Device)
        .where(Device.id == cached_device.id)
        .values(lifecycle_status="sold")
        .execution_options(synchronize_session=False)
    )
    assert cached_device.lifecycle_status == "active"

    with pytest.raises(StalePreviewError, match="重新预览"):
        GanttReorderService.execute(preview["token"])

    db_session.expire_all()
    assert {
        rental.id: rental.device_id
        for rental in Rental.query.order_by(Rental.id).all()
    } == original_device_ids


def test_execute_locks_devices_before_rentals(
    db_session, seeded_reorder_case, monkeypatch
):
    preview = GanttReorderService.preview([])
    lock_entities = []
    original = GanttReorderService._query_with_optional_lock

    def record_lock(query, lock):
        if lock:
            lock_entities.extend(
                description["entity"]
                for description in query.column_descriptions
                if description.get("entity") is not None
            )
        return original(query, lock)

    monkeypatch.setattr(
        GanttReorderService,
        "_query_with_optional_lock",
        staticmethod(record_lock),
    )

    GanttReorderService.execute(preview["token"])

    assert lock_entities[0] is Device
    assert lock_entities.index(Device) < lock_entities.index(Rental)


def test_execute_rejects_candidate_device_set_expansion(
    db_session, seeded_reorder_case, monkeypatch
):
    preview = GanttReorderService.preview([])
    original_device_ids = {
        rental.id: rental.device_id
        for rental in Rental.query.order_by(Rental.id).all()
    }
    original = GanttReorderService._query_with_optional_lock
    injected = False

    def expand_before_device_lock(query, lock):
        nonlocal injected
        entities = {
            description.get("entity")
            for description in query.column_descriptions
        }
        if lock and Device in entities and not injected:
            injected = True
            db_session.add(Device(
                name="R-candidate-drift",
                model=seeded_reorder_case.first_device.model,
                model_id=seeded_reorder_case.first_device.model_id,
                is_accessory=False,
                lifecycle_status="active",
            ))
            db_session.flush()
        return original(query, lock)

    monkeypatch.setattr(
        GanttReorderService,
        "_query_with_optional_lock",
        staticmethod(expand_before_device_lock),
    )

    with pytest.raises(StalePreviewError, match="候选集合"):
        GanttReorderService.execute(preview["token"])

    db_session.expire_all()
    assert {
        rental.id: rental.device_id
        for rental in Rental.query.order_by(Rental.id).all()
    } == original_device_ids
    assert Device.query.filter_by(name="R-candidate-drift").count() == 0


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


def test_saas_preview_and_execute_never_read_generic_secret_key(
    app, db_session, seeded_reorder_case
):
    reader = _SaasAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)
    auth_context = _saas_auth_context()
    assert app.config.get("SECRET_KEY") is None
    preview = GanttReorderService.preview_saas(
        [],
        auth_context=auth_context,
        proof_adapter=adapter,
        tenant_session=db_session(),
    )
    result = GanttReorderService.execute_saas(
        preview["token"],
        auth_context=auth_context,
        proof_adapter=adapter,
        tenant_session=db_session(),
    )

    assert result["changes"] == preview["changes"]
    assert preview["token"].count(".") == 1
    assert _SAAS_ROOT_KEY._material_bytes().hex() not in preview["token"]
    assert reader.calls == [auth_context, auth_context, auth_context]
    assert AuditLog.query.filter_by(
        action="gantt_schedule_reordered"
    ).count() == len(preview["changes"])


def test_saas_execute_reports_uncertain_fence_release_after_tenant_commit(
    db_session, seeded_reorder_case
):
    reader = _ReleaseFailingSaasAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)
    auth_context = _saas_auth_context()
    preview = GanttReorderService.preview_saas(
        [],
        auth_context=auth_context,
        proof_adapter=adapter,
        tenant_session=db_session(),
    )

    result = GanttReorderService.execute_saas(
        preview["token"],
        auth_context=auth_context,
        proof_adapter=adapter,
        tenant_session=db_session(),
    )

    assert result["changes"] == preview["changes"]
    assert result["authority_fence_outcome"] == (
        "release_unknown_after_tenant_commit"
    )
    db_session.expire_all()
    assert AuditLog.query.filter_by(
        action="gantt_schedule_reordered"
    ).count() == len(preview["changes"])


def test_saas_execute_rejects_cross_session_proof_before_mutation(
    db_session, seeded_reorder_case
):
    reader = _SaasAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)
    auth_context = _saas_auth_context()
    preview = GanttReorderService.preview_saas(
        [],
        auth_context=auth_context,
        proof_adapter=adapter,
        tenant_session=db_session(),
    )
    before = seeded_reorder_case.snapshot()

    with pytest.raises(StalePreviewError, match="重新预览"):
        GanttReorderService.execute_saas(
            preview["token"],
            auth_context=_saas_auth_context(
                session_id="20000000-0000-4000-8000-000000000003"
            ),
            proof_adapter=adapter,
            tenant_session=db_session(),
        )

    db_session.expire_all()
    assert seeded_reorder_case.snapshot() == before
    assert AuditLog.query.count() == 0


def test_saas_execute_rejects_authority_revision_drift_before_mutation(
    db_session, seeded_reorder_case
):
    reader = _SaasAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)
    auth_context = _saas_auth_context()
    preview = GanttReorderService.preview_saas(
        [],
        auth_context=auth_context,
        proof_adapter=adapter,
        tenant_session=db_session(),
    )
    before = seeded_reorder_case.snapshot()
    reader.current = replace(
        reader.current,
        authority=replace(
            reader.current.authority,
            user_auth_version=5,
        ),
    )

    with pytest.raises(StalePreviewError, match="重新预览"):
        GanttReorderService.execute_saas(
            preview["token"],
            auth_context=auth_context,
            proof_adapter=adapter,
            tenant_session=db_session(),
        )

    db_session.expire_all()
    assert seeded_reorder_case.snapshot() == before
    assert AuditLog.query.count() == 0


def test_saas_execute_rejects_legacy_secret_key_token(
    db_session, seeded_reorder_case
):
    legacy_preview = GanttReorderService.preview([])
    before = seeded_reorder_case.snapshot()
    adapter = GanttPreviewProofAdapter(
        authority_reader=_SaasAuthorityReader()
    )

    with pytest.raises(StalePreviewError, match="重新预览"):
        GanttReorderService.execute_saas(
            legacy_preview["token"],
            auth_context=_saas_auth_context(),
            proof_adapter=adapter,
            tenant_session=db_session(),
        )

    db_session.expire_all()
    assert seeded_reorder_case.snapshot() == before
    assert AuditLog.query.count() == 0


def test_saas_preview_fails_authority_before_reading_tenant_graph(
    monkeypatch,
):
    reader = _SaasAuthorityReader()
    adapter = GanttPreviewProofAdapter(authority_reader=reader)

    def tenant_graph_must_not_be_read(*_args, **_kwargs):
        raise AssertionError("tenant graph was read before authority")

    monkeypatch.setattr(
        GanttReorderService,
        "_prepare_preview",
        tenant_graph_must_not_be_read,
    )

    with pytest.raises(ValueError, match="unavailable"):
        GanttReorderService.preview_saas(
            [],
            auth_context=_saas_auth_context(
                effective_gate=EffectiveTenantGate.SUSPENDED
            ),
            proof_adapter=adapter,
            tenant_session=object(),
        )

    assert reader.calls == []
