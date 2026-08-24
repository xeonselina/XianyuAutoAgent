from __future__ import annotations

import csv
from datetime import datetime, timedelta, timezone
from io import StringIO
from uuid import uuid4

import sqlalchemy as sa

from inventory_control.models import (
    PlatformAdminRateLimitCounter,
    PlatformAdminSession,
    PlatformAuditLog,
    RedemptionCode,
    RedemptionCodeReplacement,
)
from inventory_control.platform_http import PLATFORM_CSRF_HEADER_NAME
from tests.unit.control_plane.test_platform_subscription_adjustment_http_runtime import (
    harness,
)


def _generate(client, csrf, *, request_id=None, **overrides):
    payload = {
        "generation_request_id": str(request_id or uuid4()),
        "name": "August Core delivery",
        "quantity": 2,
        "service_duration_days": 30,
        "redeem_before": (
            datetime.now(timezone.utc) + timedelta(days=60)
        ).isoformat(),
        "channel": "direct_sales",
        "internal_note": "August direct customer delivery.",
    }
    payload.update(overrides)
    return client.post(
        "/platform/api/redemption-code-batches",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: csrf},
        json=payload,
    )


def test_generation_initial_csv_list_and_replay_are_bounded(harness):
    database, client, csrf, _, _ = harness
    request_id = uuid4()
    deadline = (datetime.now(timezone.utc) + timedelta(days=60)).isoformat()
    generated = _generate(
        client,
        csrf,
        request_id=request_id,
        redeem_before=deadline,
    )
    assert generated.status_code == 201
    payload = generated.get_json()["data"]
    assert payload["created"] is True
    assert payload["quantity"] == 2
    csv_rows = list(csv.DictReader(StringIO(payload["export_csv"])))
    plaintexts = {row["redemption_code"] for row in csv_rows}
    assert len(csv_rows) == 2
    assert all(len(value) == 26 for value in plaintexts)

    with database.transaction() as session:
        codes = tuple(
            session.scalars(
                sa.select(RedemptionCode).order_by(RedemptionCode.id)
            )
        )
        source, successor = codes
        platform_session = session.scalar(
            sa.select(PlatformAdminSession).where(
                PlatformAdminSession.revoked_at.is_(None)
            )
        )
        session.add(
            RedemptionCodeReplacement(
                id=str(uuid4()),
                source_code_uuid=source.id,
                replacement_code_uuid=successor.id,
                source_attempt_uuid=None,
                source_user_uuid=None,
                source_provisional_tenant_uuid=None,
                source_provisional_database_uuid=None,
                chain_root_code_uuid=source.id,
                chain_generation=1,
                plan_revision_uuid=source.plan_revision_uuid,
                entitlements_schema_version=(
                    source.entitlements_schema_version
                ),
                entitlements_digest=source.entitlements_digest,
                service_duration_seconds=source.service_duration_seconds,
                replacement_redeem_before=source.redeem_before,
                fenced_provisioning_generation=None,
                platform_admin_uuid=platform_session.platform_admin_id,
                platform_session_uuid=platform_session.id,
                reason_code="provisioning_replacement",
                idempotency_key=f"replacement:{source.id}",
                request_digest=b"r" * 32,
                expected_source_code_row_version=source.row_version,
                expected_source_attempt_row_version=None,
                current_recovery_run_uuid=(
                    source.created_under_recovery_run_uuid
                ),
                cleanup_outbox_event_uuid=None,
                platform_audit_uuid=str(uuid4()),
                created_at=source.created_at,
            )
        )

    listed = client.get(
        "/platform/api/redemption-codes?page=1&page_size=20&status=active",
        base_url="https://localhost",
    )
    assert listed.status_code == 200
    listed_payload = listed.get_json()["data"]
    assert listed_payload["total"] == 2
    assert all("masked_code" in item for item in listed_payload["items"])
    assert {item["channel"] for item in listed_payload["items"]} == {
        "direct_sales"
    }
    source_item = next(
        item for item in listed_payload["items"] if item["code_id"] == source.id
    )
    assert source_item["replacement_status"] == "issued"
    assert source_item["replacement_code_id"] == successor.id
    assert all(value not in listed.get_data(as_text=True) for value in plaintexts)

    replay = _generate(
        client,
        csrf,
        request_id=request_id,
        redeem_before=deadline,
    )
    assert replay.status_code == 201
    replay_payload = replay.get_json()["data"]
    assert replay_payload["created"] is False
    assert replay_payload["quantity"] == 0
    assert replay_payload["export_csv"] is None

    with database.new_session() as session:
        assert session.scalar(sa.select(sa.func.count(RedemptionCode.id))) == 2
        actions = list(
            session.scalars(
                sa.select(PlatformAuditLog.action).where(
                    PlatformAuditLog.action.like("platform.redemption_codes.%")
                )
            )
        )
    assert actions.count("platform.redemption_codes.generate") == 2
    assert actions.count("platform.redemption_codes.export") == 1
    assert actions.count("platform.redemption_codes.list") == 1


def test_single_reveal_and_active_revocation_are_audited(harness):
    database, client, csrf, _, _ = harness
    generated = _generate(client, csrf, quantity=1).get_json()["data"]
    row = next(csv.DictReader(StringIO(generated["export_csv"])))
    code_id = row["code_id"]
    plaintext = row["redemption_code"]

    reveal = client.post(
        f"/platform/api/redemption-codes/{code_id}/reveal",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: csrf},
        json={},
    )
    assert reveal.status_code == 200
    assert reveal.get_json()["data"]["code"] == plaintext

    revoked = client.post(
        f"/platform/api/redemption-codes/{code_id}/revoke",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: csrf},
        json={
            "expected_row_version": 1,
            "reason_code": "operator_revoked",
        },
    )
    assert revoked.status_code == 200
    assert revoked.get_json()["data"] == {
        "changed": True,
        "code_id": code_id,
        "row_version": 2,
        "status": "revoked",
    }

    replay = client.post(
        f"/platform/api/redemption-codes/{code_id}/revoke",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: csrf},
        json={
            "expected_row_version": 1,
            "reason_code": "operator_revoked",
        },
    )
    assert replay.status_code == 200
    assert replay.get_json()["data"]["changed"] is False

    with database.new_session() as session:
        actions = list(
            session.scalars(
                sa.select(PlatformAuditLog.action).where(
                    PlatformAuditLog.target_resource_id == code_id
                )
            )
        )
    assert actions.count("platform.redemption_codes.reveal") == 1
    assert actions.count("platform.redemption_codes.revoke") == 2


def test_single_reveal_has_an_explicit_multi_subject_rate_limit(harness):
    database, client, csrf, _, _ = harness
    generated = _generate(client, csrf, quantity=1).get_json()["data"]
    row = next(csv.DictReader(StringIO(generated["export_csv"])))
    route = f"/platform/api/redemption-codes/{row['code_id']}/reveal"

    for _ in range(5):
        response = client.post(
            route,
            base_url="https://localhost",
            headers={PLATFORM_CSRF_HEADER_NAME: csrf},
            json={},
        )
        assert response.status_code == 200
        assert response.get_json()["data"]["code"] == row["redemption_code"]

    blocked = client.post(
        route,
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: csrf},
        json={},
    )
    assert blocked.status_code == 429
    assert blocked.get_json()["data"]["code"] == (
        "PLATFORM_REDEMPTION_RATE_LIMITED"
    )

    with database.new_session() as session:
        counters = tuple(
            session.scalars(
                sa.select(PlatformAdminRateLimitCounter).where(
                    PlatformAdminRateLimitCounter.scope == "code_reveal"
                )
            )
        )
        outcomes = tuple(
            session.scalars(
                sa.select(PlatformAuditLog.outcome).where(
                    PlatformAuditLog.action
                    == "platform.redemption_codes.reveal",
                    PlatformAuditLog.target_resource_id == row["code_id"],
                )
            )
        )
    assert len(counters) == 3
    assert {counter.attempt_count for counter in counters} == {5}
    assert outcomes.count("succeeded") == 5
    assert outcomes.count("rate_limited") == 1


def test_reveal_rejection_commits_attempt_and_credential_free_audit(harness):
    database, client, csrf, _, _ = harness
    missing_id = str(uuid4())
    response = client.post(
        f"/platform/api/redemption-codes/{missing_id}/reveal",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: csrf},
        json={},
    )
    assert response.status_code == 404

    with database.new_session() as session:
        audit = session.scalar(
            sa.select(PlatformAuditLog).where(
                PlatformAuditLog.action
                == "platform.redemption_codes.reveal",
                PlatformAuditLog.target_resource_id == missing_id,
            )
        )
        counts = tuple(
            session.scalars(
                sa.select(PlatformAdminRateLimitCounter.attempt_count).where(
                    PlatformAdminRateLimitCounter.scope == "code_reveal"
                )
            )
        )
    assert audit.outcome == "rejected"
    assert audit.safe_reason_code == "redemption_code.reveal_rejected"
    assert audit.pii_revealed is False
    assert counts == (1, 1, 1)


def test_expired_code_rejection_commits_expiry_and_rejection_audit(harness):
    database, client, csrf, _, _ = harness
    generated = _generate(client, csrf, quantity=1).get_json()["data"]
    code_id = next(csv.DictReader(StringIO(generated["export_csv"])))["code_id"]
    with database.transaction() as session:
        code = session.get(RedemptionCode, code_id)
        code.redeem_before = datetime.now(timezone.utc) - timedelta(seconds=1)

    response = client.post(
        f"/platform/api/redemption-codes/{code_id}/revoke",
        base_url="https://localhost",
        headers={PLATFORM_CSRF_HEADER_NAME: csrf},
        json={
            "expected_row_version": 1,
            "reason_code": "operator_revoked",
        },
    )
    assert response.status_code == 409
    with database.new_session() as session:
        code = session.get(RedemptionCode, code_id)
        audit = session.scalar(
            sa.select(PlatformAuditLog).where(
                PlatformAuditLog.target_resource_id == code_id,
                PlatformAuditLog.action == "platform.redemption_codes.revoke",
            )
        )
        assert code.status == "expired"
        assert audit.outcome == "rejected"
        assert audit.safe_reason_code == "redemption_code.expired"


def test_redemption_routes_require_csrf_and_reject_unknown_shapes(harness):
    _, client, csrf, _, _ = harness
    missing_csrf = client.post(
        "/platform/api/redemption-code-batches",
        base_url="https://localhost",
        json={
            "generation_request_id": str(uuid4()),
            "name": "batch",
            "quantity": 1,
            "service_duration_days": 30,
            "redeem_before": (
                datetime.now(timezone.utc) + timedelta(days=1)
            ).isoformat(),
        },
    )
    duplicate_query = client.get(
        "/platform/api/redemption-codes?page=1&page=2",
        base_url="https://localhost",
    )
    unknown_field = _generate(client, csrf, unexpected="value")

    assert missing_csrf.status_code == 403
    assert duplicate_query.status_code == 400
    assert unknown_field.status_code == 400
