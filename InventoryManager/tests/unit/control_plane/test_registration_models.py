import hashlib
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy.exc import DBAPIError

from inventory_control import ControlBase, ControlDatabase, User
from inventory_control.crypto import RootKey
from inventory_control.models import (
    PlanRevision,
    PlatformAdmin,
    RegistrationIntegrityIncident,
    TenantRegistrationAttempt,
)
from inventory_control.redemption import RedemptionCodeService
from inventory_control.subscriptions import parse_core_entitlements


NOW = datetime(2026, 8, 22, 12, 0, tzinfo=timezone.utc)
RUN_UUID = UUID("20000000-0000-4000-8000-000000000001")
PLAN_UUID = UUID("20000000-0000-4000-8000-000000000002")
ADMIN_UUID = UUID("20000000-0000-4000-8000-000000000003")
ROOT_KEY = RootKey(version=1, material=b"g" * 32)
ENTITLEMENTS = {"features": {}, "limits": {"member_seats": 10}}


@pytest.fixture
def database(mysql_control_database):
    value = mysql_control_database
    snapshot = parse_core_entitlements(schema_version=1, entitlements=ENTITLEMENTS)
    with value.transaction() as session:
        session.add(
            PlatformAdmin(
                id=str(ADMIN_UUID),
                username_canonical="registration-admin",
                status="active",
                password_hash_encoded="scrypt$redacted",
                password_hash_algorithm="scrypt",
                password_hash_version=1,
                created_at=NOW,
                updated_at=NOW,
            )
        )
        session.add(
            PlanRevision(
                id=str(PLAN_UUID),
                code="core",
                revision=1,
                name="Core",
                entitlements_schema_version=1,
                entitlements_json=ENTITLEMENTS,
                entitlements_digest=snapshot.digest_sha256,
                active=True,
            )
        )
        user = User(
            phone_e164="+8613812345678",
            phone_normalization_version=1,
            phone_metadata_version="cn-mobile-v1",
            status="active",
        )
        session.add(user)
        session.flush()
        generated = RedemptionCodeService().generate_batch(
            session,
            root_key=ROOT_KEY,
            current_recovery_run_uuid=RUN_UUID,
            recovery_run_completed=True,
            platform_admin_uuid=ADMIN_UUID,
            generation_request_uuid=uuid4(),
            plan_revision_uuid=PLAN_UUID,
            name="Registration fixtures",
            quantity=2,
            service_duration=timedelta(days=30),
            redeem_before=NOW + timedelta(days=30),
            database_now=NOW,
        )
        code_ids = tuple(str(item.code_uuid) for item in generated.issued_codes)
        user_id = user.id
    return value, user_id, code_ids


def attempt(user_id, code_id, **overrides):
    values = {
        "user_id": user_id,
        "redemption_code_id": code_id,
        "requested_tenant_name": "Acme Rentals",
        "status": "reserved",
        "idempotency_key": str(uuid4()),
        "request_digest": hashlib.sha256(b"registration").digest(),
        "provisioning_execution_generation": 1,
        "recovery_run_uuid": str(RUN_UUID),
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return TenantRegistrationAttempt(**values)


def test_one_code_has_at_most_one_registration_attempt(database):
    db, user_id, code_ids = database
    with db.transaction() as session:
        session.add(attempt(user_id, code_ids[0]))

    with pytest.raises(DBAPIError):
        with db.transaction() as session:
            session.add(attempt(user_id, code_ids[0]))


def test_provisioning_state_requires_complete_persisted_lease(database):
    db, user_id, code_ids = database
    with pytest.raises(DBAPIError):
        with db.transaction() as session:
            session.add(
                attempt(
                    user_id,
                    code_ids[0],
                    status="provisioning",
                )
            )

    with db.transaction() as session:
        session.add(
            attempt(
                user_id,
                code_ids[0],
                status="provisioning",
                lease_owner="worker-1",
                lease_token="lease-token",
                lease_expires_at=NOW + timedelta(minutes=5),
            )
        )


def test_superseded_and_active_states_require_their_immutable_anchor(database):
    db, user_id, code_ids = database
    for status in ("superseded_by_replacement", "active"):
        with pytest.raises(DBAPIError):
            with db.transaction() as session:
                session.add(attempt(user_id, code_ids[0], status=status))


def test_only_one_open_integrity_incident_can_cover_an_attempt(database):
    db, user_id, code_ids = database
    with db.transaction() as session:
        registration = attempt(user_id, code_ids[0], status="integrity_blocked")
        session.add(registration)
        session.flush()
        values = {
            "attempt_uuid": registration.id,
            "code_uuid": code_ids[0],
            "user_uuid": user_id,
            "detected_attempt_status": "integrity_blocked",
            "provisioning_generation": 1,
            "presence_bitmap": 3,
            "presence_digest": hashlib.sha256(b"partial-anchors").digest(),
            "current_recovery_run_uuid": str(RUN_UUID),
            "marker_generation": 1,
            "state": "open",
            "evidence_policy_version": 1,
            "safe_evidence_reference": "integrity-scan-1",
            "detected_at": NOW,
        }
        first = RegistrationIntegrityIncident(**values)
        session.add(first)
        session.flush()
        assert first.open_attempt_uuid == registration.id

    with pytest.raises(DBAPIError):
        with db.transaction() as session:
            session.add(RegistrationIntegrityIncident(**values))


def test_registration_tables_do_not_duplicate_phone_or_secret_material():
    attempt_columns = set(TenantRegistrationAttempt.__table__.columns.keys())
    forbidden = {
        "phone",
        "phone_e164",
        "otp",
        "otp_code",
        "database_password",
        "code_plaintext",
    }
    assert forbidden.isdisjoint(attempt_columns)
